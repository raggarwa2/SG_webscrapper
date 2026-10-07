# ============================================================
# Triangulation Analysis (Singapore) — checks scraped review/product data
# against the research framework in mappings.py
# ============================================================
# Adapted from triangulation_hk/run_triangulation.py.
#   Prompt A — channel coverage gap check
#   Prompt B — purchase-barrier language match
#   Prompt C — attribute quadrant validation
#   Prompt D — combined triangulation summary (one page per brand)
#
# Usage (from the Scripts/ folder):
#   python triangulation_sg/run_triangulation.py                 # runs all four prompts
#   python triangulation_sg/run_triangulation.py --prompt a      # channel coverage only, no LLM/cost
#   python triangulation_sg/run_triangulation.py --prompt b      # barrier match only
#   python triangulation_sg/run_triangulation.py --prompt c      # attribute quadrant only
#   python triangulation_sg/run_triangulation.py --prompt d      # combined summary only
#
# Scope: Singapore only (market == 'SG'). Sources: Lazada/TikTok Shop products + Lazada
# reviews, XHS, YouTube, Instagram, Facebook, Reddit, Kiasuparents forum summaries.
# ============================================================

import argparse
import json
import re
import shutil
import sqlite3
from collections import Counter
from datetime import datetime
from pathlib import Path

import pandas as pd
from dotenv import load_dotenv

from mappings import (BARRIERS, CHANNEL_TAXONOMY, ATTRIBUTE_QUADRANT, ATTRIBUTE_TO_QUADRANT,
                      BRAND_ALIASES, FOCUS_BRANDS)

load_dotenv()

ROOT = Path(__file__).resolve().parent.parent
OUT_ROOT = ROOT / "output"
DEFAULT_DB = OUT_ROOT / "sg_acuvue.db"
DEFAULT_XHS_DB = OUT_ROOT / "xhs_data_sg.db"
DEFAULT_YOUTUBE_DB = OUT_ROOT / "youtube_data_sg.db"
DEFAULT_INSTAGRAM_DB = OUT_ROOT / "instagram_data_sg.db"
DEFAULT_FACEBOOK_DB = OUT_ROOT / "facebook_data_sg.db"
DEFAULT_REDDIT_DB = OUT_ROOT / "reddit_data_sg.db"
DEFAULT_GMAPS_DB = OUT_ROOT / "gmaps_data_sg.db"
DEFAULT_APP_DB = OUT_ROOT / "app_data_sg.db"
DEFAULT_OUT = OUT_ROOT / "triangulation_sg"
DEFAULT_RESEARCH_DIR = ROOT / "data" / "research"

CLASSIFY_BATCH_SIZE = 15  # reviews/posts per LLM classification call


def normalize_brand(name) -> str:
    """Map every spelling used across the SG tables onto one canonical brand name."""
    if not isinstance(name, str) or not name.strip():
        return "other"
    return BRAND_ALIASES.get(name.strip().lower(), name.strip())


# ============================================================
# DB loading (SG only)
# ============================================================

_SOCIAL_COLUMNS = ["key", "brand", "text", "source_url"]


def _query(db_path: Path, sql: str, label: str, columns=None) -> pd.DataFrame:
    """Runs sql against db_path; returns an empty frame (and says why) if the DB or
    table is missing so one absent source doesn't abort the whole run."""
    if not db_path.exists():
        print(f"  (note: {db_path} not found — skipping {label})")
        return pd.DataFrame(columns=columns or [])
    conn = sqlite3.connect(db_path)
    try:
        return pd.read_sql_query(sql, conn)
    except (pd.errors.DatabaseError, sqlite3.Error) as e:
        print(f"  (note: {label} query failed: {e} — skipping)")
        return pd.DataFrame(columns=columns or [])
    finally:
        conn.close()


def load_products_sg(db_path: Path) -> pd.DataFrame:
    return _query(db_path, "SELECT * FROM products WHERE market = 'SG'", "products")


def load_reviews_sg(db_path: Path) -> pd.DataFrame:
    """Joins products.url as source_url so each review traces back to its product page.
    Reviews carry no content_hash, so a stable key is built from the row id."""
    df = _query(
        db_path,
        "SELECT 'review::' || r.id AS content_hash, r.brand, r.site, r.store_name, "
        "r.review_text AS review_text_en, p.url AS source_url FROM reviews r "
        "LEFT JOIN products p ON r.product_id = p.id "
        "WHERE r.market = 'SG' AND r.review_text IS NOT NULL AND TRIM(r.review_text) != ''",
        "reviews",
    )
    df["brand"] = df["brand"].map(normalize_brand)
    return df


def load_xhs_posts(db_path: Path) -> pd.DataFrame:
    """XHS is China-wide; keep only posts the scraper judged Singapore-relevant."""
    return _query(
        db_path,
        "SELECT * FROM xhs_posts WHERE market_relevant != 0 "
        "AND content_en IS NOT NULL AND TRIM(content_en) != ''",
        "XHS",
    )


def load_forum_posts(db_path: Path) -> pd.DataFrame:
    """sg_acuvue.db forum_posts (Kiasuparents) — LLM summaries of forum threads; the SG
    analogue of HK's reputation.csv. Same signal shape, so it joins the classification pass."""
    df = _query(
        db_path,
        "SELECT brand, content_summary AS summary, post_url AS source_url, "
        "COALESCE(content_hash, CAST(id AS TEXT)) AS ckey FROM forum_posts "
        "WHERE content_summary IS NOT NULL AND TRIM(content_summary) != ''",
        "Kiasuparents forum posts",
        columns=["brand", "summary", "source_url", "ckey"],
    )
    return df


def load_retailer_evidence(research_dir: Path) -> pd.DataFrame:
    """
    Optional Research/distribution.csv and pricing.csv (SG rows) — manually curated
    retailer evidence for "known but not yet scraped" channels. Neither file exists for
    SG yet, so this normally returns an empty table and Prompt A reports scraper coverage only.
    """
    frames = []
    dist_path = research_dir / "distribution.csv"
    if dist_path.exists():
        d = pd.read_csv(dist_path)
        d = d[d["market"] == "SG"][["retailer", "status", "source_url"]].copy()
        d["source_file"] = "distribution.csv"
        frames.append(d)
    price_path = research_dir / "pricing.csv"
    if price_path.exists():
        p = pd.read_csv(price_path)
        p = p[p["market"] == "SG"][["store", "source_url"]].rename(columns={"store": "retailer"}).copy()
        p["status"] = "Observed price"
        p["source_file"] = "pricing.csv"
        frames.append(p)
    if not frames:
        print(f"  (note: no distribution.csv/pricing.csv in {research_dir} — Prompt A shows scraper coverage only)")
        return pd.DataFrame(columns=["retailer", "status", "source_url", "source_file"])
    return pd.concat(frames, ignore_index=True).drop_duplicates(subset=["retailer", "source_url"])


def load_gmaps_coverage(db_path: Path) -> pd.DataFrame:
    """Per-chain place/review counts from the Google Maps scrape (offline optical retailers)."""
    return _query(
        db_path,
        "SELECT p.chain, COUNT(DISTINCT p.place_id) AS places, "
        "(SELECT COUNT(*) FROM gmaps_reviews r WHERE r.chain = p.chain) AS reviews "
        "FROM gmaps_places p GROUP BY p.chain",
        "Google Maps", ["chain", "places", "reviews"],
    )


def load_app_review_count(db_path: Path) -> int:
    df = _query(db_path, "SELECT COUNT(*) AS n FROM app_reviews WHERE country = 'sg' OR country = 'SG'",
                "app reviews", ["n"])
    if df.empty or not df.loc[0, "n"]:
        df = _query(db_path, "SELECT COUNT(*) AS n FROM app_reviews", "app reviews", ["n"])
    return int(df.loc[0, "n"]) if not df.empty else 0


def load_youtube(db_path: Path) -> pd.DataFrame:
    return _query(
        db_path,
        "SELECT c.content_hash AS key, c.brand AS brand, c.comment_text_en AS text, "
        "v.url AS source_url FROM yt_comments c JOIN yt_videos v ON c.video_id = v.video_id "
        "WHERE c.market = 'SG' AND v.brand_relevant != 0 AND c.is_lens_relevant != 0 "
        "AND c.comment_text_en IS NOT NULL AND TRIM(c.comment_text_en) != ''",
        "YouTube", _SOCIAL_COLUMNS,
    )


def load_instagram(db_path: Path) -> pd.DataFrame:
    return _query(
        db_path,
        "SELECT c.content_hash AS key, c.brand AS brand, c.comment_text_en AS text, "
        "p.url AS source_url FROM ig_comments c JOIN ig_posts p ON c.post_id = p.post_id "
        "WHERE c.market = 'SG' AND p.is_lens_relevant != 0 AND p.brand_relevant != 0 "
        "AND p.market_relevant != 0 AND c.is_lens_relevant != 0 "
        "AND c.comment_text_en IS NOT NULL AND TRIM(c.comment_text_en) != ''",
        "Instagram", _SOCIAL_COLUMNS,
    )


def load_facebook(db_path: Path) -> pd.DataFrame:
    """fb_comments joined to fb_posts for the post URL. No English-translation column
    exists for Facebook in SG, so comment_text is used as-is (the classifier handles
    mixed English/Singlish)."""
    return _query(
        db_path,
        "SELECT c.content_hash AS key, c.brand AS brand, c.comment_text AS text, "
        "p.url AS source_url FROM fb_comments c JOIN fb_posts p ON c.post_id = p.post_id "
        "WHERE c.market = 'SG' AND c.is_lens_relevant != 0 AND p.is_lens_relevant != 0 "
        "AND c.comment_text IS NOT NULL AND TRIM(c.comment_text) != ''",
        "Facebook", _SOCIAL_COLUMNS,
    )


def load_reddit(db_path: Path) -> pd.DataFrame:
    return _query(
        db_path,
        "SELECT c.content_hash AS key, c.brand AS brand, c.comment_text AS text, "
        "p.permalink AS source_url FROM reddit_comments c "
        "JOIN reddit_posts p ON c.post_id = p.post_id "
        "WHERE c.market = 'SG' AND p.brand_relevant != 0 AND c.is_lens_relevant != 0 "
        "AND c.comment_text IS NOT NULL AND TRIM(c.comment_text) != ''",
        "Reddit", _SOCIAL_COLUMNS,
    )


# ============================================================
# Prompt A — channel coverage gap check
# ============================================================

def _text_match_mask(series: pd.Series, needles: list) -> pd.Series:
    """Word-boundary match so short names like 'Line' don't hit inside 'Online'."""
    mask = pd.Series(False, index=series.index)
    text = series.fillna("").str.lower()
    for needle in needles:
        pattern = r"\b" + re.escape(needle.lower()) + r"\b"
        mask |= text.str.contains(pattern, regex=True)
    return mask


def compute_channel_coverage(products: pd.DataFrame, reviews: pd.DataFrame, evidence_df: pd.DataFrame,
                             gmaps: pd.DataFrame = None, app_review_count: int = 0) -> pd.DataFrame:
    rows = []
    for cat in CHANNEL_TAXONOMY:
        name, examples, online = cat["category"], cat["examples"], cat["online"]

        sites = cat.get("sites", [])
        prod_mask = pd.Series(False, index=products.index)
        rev_mask = pd.Series(False, index=reviews.index)
        matched_stores = []
        if sites:
            prod_mask |= products["site"].isin(sites)
            rev_mask |= reviews["site"].isin(sites)
            matched_stores = [f"(all {', '.join(sites)} sellers)"]
        if examples:
            ex_prod = _text_match_mask(products["store_name"], examples)
            ex_rev = _text_match_mask(reviews["store_name"], examples)
            prod_mask |= ex_prod
            rev_mask |= ex_rev
            matched_stores += sorted(products.loc[ex_prod, "store_name"].dropna().unique().tolist())

        product_count = int(prod_mask.sum())
        review_count = int(rev_mask.sum())

        # Non-product coverage: Google Maps retailer reviews and app-store reviews.
        side_sources = []
        if gmaps is not None and not gmaps.empty and cat.get("gmaps_chains"):
            hit = gmaps[gmaps["chain"].isin(cat["gmaps_chains"])]
            if not hit.empty:
                review_count += int(hit["reviews"].sum())
                side_sources.append("Google Maps: " + ", ".join(
                    f"{r.chain} ({r.places} places, {r.reviews} reviews)" for r in hit.itertuples()))
        if cat.get("app_reviews") and app_review_count:
            review_count += app_review_count
            side_sources.append(f"app-store reviews ({app_review_count})")
        scraped = "Y" if (product_count > 0 or side_sources) else "N"

        # A clickable example of an actual scraped product page, so the claim is checkable.
        sample_scraped_url = ""
        if product_count > 0:
            urls = products.loc[prod_mask, "url"].dropna()
            sample_scraped_url = urls.iloc[0] if not urls.empty else ""

        evidence_matches = []
        if not evidence_df.empty:
            needles = examples or [name]
            hit = evidence_df[_text_match_mask(evidence_df["retailer"], needles)]
            # One representative link per retailer+source+status (a retailer can have
            # dozens of pricing.csv rows, one per SKU) — count shows there's more.
            grouped = hit.groupby(["retailer", "status", "source_file"]).agg(
                source_url=("source_url", "first"), n=("source_url", "count")
            ).reset_index()
            evidence_matches = [
                f"[{r.retailer} ({r.status}, per {r.source_file}"
                + (f", {r.n} entries" if r.n > 1 else "") + f")]({r.source_url})"
                for r in grouped.itertuples()
            ]

        if not online:
            notes = "Offline / physical retail — out of scope for scraper gap-closing."
            if side_sources:
                notes += " Covered via " + "; ".join(side_sources) + "."
            if evidence_matches:
                notes += " Known retailers per research: " + "; ".join(evidence_matches) + "."
        elif scraped == "Y":
            notes = f"Scraped via: {', '.join(matched_stores) or 'no product listings'}."
            if sample_scraped_url:
                notes += f" Example: {sample_scraped_url}"
            if side_sources:
                notes += " Also: " + "; ".join(side_sources) + "."
        elif evidence_matches:
            notes = "Known to exist per research team: " + "; ".join(evidence_matches) + " — not yet scraped."
        else:
            notes = "No current coverage; no corroborating evidence of specific retailers to target."

        rows.append({
            "taxonomy_category": name,
            "online_channel": online,
            "scraped": scraped,
            "product_count": product_count,
            "review_count": review_count,
            "sample_scraped_url": sample_scraped_url,
            "research_evidence": " | ".join(evidence_matches),
            "notes": notes,
        })

    df = pd.DataFrame(rows)

    # Priority = online + not scraped, ranked by how many "Present" retailers
    # the research team has already confirmed exist for that category.
    def _present_count(notes: str) -> int:
        return notes.count("(Present)")

    df["priority_rank"] = None
    gap_mask = (df["online_channel"]) & (df["scraped"] == "N")
    gaps = df[gap_mask].copy()
    if not gaps.empty:
        gaps["_score"] = gaps["notes"].apply(_present_count)
        gaps = gaps.sort_values("_score", ascending=False)
        df.loc[gaps.index, "priority_rank"] = range(1, len(gaps) + 1)

    return df


def write_prompt_a(df: pd.DataFrame, out_dir: Path) -> None:
    csv_path = out_dir / "prompt_a_channel_coverage.csv"
    md_path = out_dir / "prompt_a_channel_coverage.md"
    df.to_csv(csv_path, index=False, encoding="utf-8-sig")

    lines = ["# Prompt A — Channel Coverage Gap Check\n"]
    lines.append("| Category | Online? | Scraped Y/N | Products | Reviews | Priority | Notes |")
    lines.append("|---|---|---|---|---|---|---|")
    for r in df.itertuples():
        priority = "" if pd.isna(r.priority_rank) else str(int(r.priority_rank))
        lines.append(
            f"| {r.taxonomy_category} | {'Yes' if r.online_channel else 'No'} | "
            f"{r.scraped} | {r.product_count} | {r.review_count} | {priority} | {r.notes} |"
        )

    lines.append("\n## Highest-priority online gaps to close first")
    gaps = df[(df["online_channel"]) & (df["scraped"] == "N")].sort_values("priority_rank")
    if gaps.empty:
        lines.append("None — all online categories have at least some coverage.")
    else:
        for r in gaps.itertuples():
            lines.append(f"{int(r.priority_rank) if not pd.isna(r.priority_rank) else '-'}. **{r.taxonomy_category}** — {r.notes}")

    lines.append(
        "\n_Offline categories (optical chains, independent optical stores, optometrist/ECP clinics, "
        "supermarkets/department stores) are "
        "listed above for completeness against the reference framework, but are not "
        "prioritized — a web scraper cannot reach physical/walk-in retail._"
    )

    md_path.write_text("\n".join(lines), encoding="utf-8")
    print(f"  Prompt A written -> {md_path.name}, {csv_path.name}")


# ============================================================
# Shared LLM classification pass (feeds Prompts B and C)
# ============================================================

ALL_ATTRIBUTES = [attr for attrs in ATTRIBUTE_QUADRANT.values() for attr in attrs]

CLASSIFY_INSTRUCTIONS = f"""You are analyzing Singapore contact lens customer reviews and social media \
posts for a market research triangulation project.

For each numbered text below, identify:
1. "barriers": which of these exact phrases (copy verbatim from this list, or return an empty \
list) the text expresses as a barrier to choosing, registering with, or staying with a brand:
{json.dumps(BARRIERS, ensure_ascii=False)}
2. "attributes": which of these exact attribute phrases (copy verbatim, or empty list) the text \
discusses, each paired with a sentiment ("positive", "negative", or "neutral"):
{json.dumps(ALL_ATTRIBUTES, ensure_ascii=False)}
3. "other_themes": 0-3 short (2-4 word) free-text labels for any other recurring complaint or \
praise theme that is NOT already covered by the barrier list above (empty list if none).
4. "quote": if any barriers or attributes were found, a short PARAPHRASED (not verbatim) English \
quote capturing the gist in under 20 words, else null.

Return ONLY a JSON array with exactly {{n}} objects, one per text, in the same order, each with \
keys: barriers, attributes, other_themes, quote. Texts with no relevant content get \
barriers: [], attributes: [], other_themes: [], quote: null. No other text in your response."""


def _get_openai_client():
    from openai import OpenAI
    return OpenAI()


def _load_cache(cache_path: Path) -> dict:
    if cache_path.exists():
        return json.loads(cache_path.read_text(encoding="utf-8"))
    return {}


def _save_cache(cache_path: Path, cache: dict) -> None:
    cache_path.parent.mkdir(parents=True, exist_ok=True)
    cache_path.write_text(json.dumps(cache, ensure_ascii=False), encoding="utf-8")


def _empty_classification():
    return {"barriers": [], "attributes": [], "other_themes": [], "quote": None}


def _sanitize_classification(obj) -> dict:
    """The model occasionally returns malformed shapes (nested lists, non-string
    themes, etc.) — coerce defensively instead of letting a bad field crash
    downstream aggregation or silently poison a Counter."""
    if not isinstance(obj, dict):
        return _empty_classification()

    barriers = obj.get("barriers", [])
    barriers = [b for b in barriers if isinstance(b, str)] if isinstance(barriers, list) else []

    attributes = obj.get("attributes", [])
    clean_attrs = []
    if isinstance(attributes, list):
        for a in attributes:
            if isinstance(a, dict) and isinstance(a.get("attribute"), str):
                sentiment = a.get("sentiment")
                clean_attrs.append({
                    "attribute": a["attribute"],
                    "sentiment": sentiment if sentiment in ("positive", "negative", "neutral") else "neutral",
                })

    themes = obj.get("other_themes", [])
    clean_themes = [t for t in themes if isinstance(t, str)] if isinstance(themes, list) else []

    quote = obj.get("quote")
    quote = quote if isinstance(quote, str) else None

    return {"barriers": barriers, "attributes": clean_attrs, "other_themes": clean_themes, "quote": quote}


def classify_batch(texts: list, client):
    """Returns a sanitized list of classifications, or None if the batch could not
    be parsed / didn't come back with one result per text (caller should NOT cache
    a None — it means "retry", not "nothing found")."""
    numbered = "\n".join(f"{i + 1}. {t[:600]}" for i, t in enumerate(texts))
    prompt = CLASSIFY_INSTRUCTIONS.replace("{n}", str(len(texts))) + f"\n\nTexts:\n{numbered}"
    try:
        resp = client.chat.completions.create(
            model="gpt-4o-mini",
            messages=[{"role": "user", "content": prompt}],
            max_tokens=4000,
        )
        raw = resp.choices[0].message.content.strip()
        raw = re.sub(r"^```(?:json)?\s*|\s*```$", "", raw, flags=re.MULTILINE).strip()
        results = json.loads(raw)
        if isinstance(results, list) and len(results) == len(texts):
            return [_sanitize_classification(r) for r in results]
        print(f"  [warn] classify batch: expected {len(texts)}, got {len(results) if isinstance(results, list) else type(results)} — will retry individually")
    except Exception as e:
        print(f"  [warn] classify batch failed: {e} — will retry individually")
    return None


def classify_all(reviews: pd.DataFrame, xhs_posts: pd.DataFrame, forum_posts: pd.DataFrame,
                  social_sources: dict, cache_path: Path) -> pd.DataFrame:
    """
    Returns one row per review/post/forum-summary/social-comment with brand +
    classification fields merged in. Every item carries a source_url so quotes in the
    output can link back to the original review page / XHS post / forum thread / video
    / IG post / FB review.

    `social_sources` is {source_label: df} where each df already has the normalized
    columns key/brand/text/source_url (see load_youtube/load_instagram/load_facebook) —
    a generic loop handles any number of these without growing this function's signature
    further as sources get added.
    """
    # Brand spellings differ across SG tables ("MyACUVUE"/"ACUVUE"/"Acuvue",
    # "Bausch + Lomb"/"Bausch & Lomb") — normalize so they aren't counted as separate brands.
    _normalize_brand = normalize_brand

    items = []
    for r in reviews.itertuples():
        items.append({
            "key": r.content_hash, "brand": r.brand, "source": "review",
            "text": r.review_text_en, "source_url": getattr(r, "source_url", "") or "",
        })
    for p in xhs_posts.itertuples():
        text = (getattr(p, "content_en", "") or "") or (getattr(p, "title", "") or "")
        items.append({
            "key": p.post_id, "brand": _normalize_brand(getattr(p, "brand_mentioned", "")),
            "source": "xhs_post", "text": text, "source_url": getattr(p, "url", "") or "",
        })
    for fp in forum_posts.itertuples():
        items.append({
            "key": f"forum::{fp.ckey}", "brand": _normalize_brand(fp.brand), "source": "kiasuparents_forum",
            "text": fp.summary, "source_url": fp.source_url,
        })
    for source_label, df in social_sources.items():
        for s in df.itertuples():
            items.append({
                "key": s.key, "brand": _normalize_brand(s.brand), "source": source_label,
                "text": s.text, "source_url": getattr(s, "source_url", "") or "",
            })

    items = [it for it in items if it["text"] and it["text"].strip()]

    cache = _load_cache(cache_path)
    to_fetch = [it for it in items if it["key"] not in cache]
    print(f"  {len(items)} items total, {len(items) - len(to_fetch)} already cached, {len(to_fetch)} to classify")

    if to_fetch:
        client = _get_openai_client()
        stragglers = []
        for i in range(0, len(to_fetch), CLASSIFY_BATCH_SIZE):
            batch = to_fetch[i:i + CLASSIFY_BATCH_SIZE]
            results = classify_batch([b["text"] for b in batch], client)
            if results is None:
                stragglers.extend(batch)  # batch-level failure — retry these one at a time below
            else:
                for b, res in zip(batch, results):
                    cache[b["key"]] = res
            print(f"  classified {min(i + CLASSIFY_BATCH_SIZE, len(to_fetch))}/{len(to_fetch)}")
            _save_cache(cache_path, cache)

        if stragglers:
            print(f"  retrying {len(stragglers)} straggler items one at a time (batch-level failures above)...")
            for b in stragglers:
                results = classify_batch([b["text"]], client)
                cache[b["key"]] = results[0] if results else _empty_classification()
            _save_cache(cache_path, cache)
            print(f"  stragglers done")

    rows = []
    for it in items:
        res = cache.get(it["key"], _empty_classification())
        rows.append({
            "brand": it["brand"], "source": it["source"], "text": it["text"],
            "source_url": it["source_url"],
            "barriers": res.get("barriers", []), "attributes": res.get("attributes", []),
            "other_themes": res.get("other_themes", []), "quote": res.get("quote"),
        })
    return pd.DataFrame(rows)


# ============================================================
# Prompt B — barrier language match
# ============================================================

def compute_barrier_tables(classified: pd.DataFrame):
    counts = Counter()
    quotes = {}
    for r in classified.itertuples():
        for barrier in r.barriers:
            if barrier not in BARRIERS:
                continue
            key = (r.brand, barrier)
            counts[key] += 1
            quotes.setdefault(key, [])
            if r.quote and len(quotes[key]) < 3:
                quotes[key].append((r.quote, r.source, r.source_url))

    def _fmt_quotes(qs):
        # markdown-link each quote back to its source (review page / XHS post / forum thread)
        parts = []
        for quote, source, url in qs:
            parts.append(f"[{quote}]({url}) ({source})" if url else f"{quote} ({source}, no link on file)")
        return " | ".join(parts)

    rows = [
        {"brand": b, "barrier": barrier, "match_count": n, "example_quotes": _fmt_quotes(quotes.get((b, barrier), []))}
        for (b, barrier), n in counts.items()
    ]
    matrix = pd.DataFrame(rows).sort_values(["brand", "match_count"], ascending=[True, False]) if rows else pd.DataFrame(
        columns=["brand", "barrier", "match_count", "example_quotes"]
    )

    matched_barriers = {barrier for (_, barrier) in counts}
    zero_match = [b for b in BARRIERS if b not in matched_barriers]

    theme_counter = Counter()
    for r in classified.itertuples():
        for theme in r.other_themes:
            theme_counter[theme] += 1
    themes_df = pd.DataFrame(theme_counter.most_common(), columns=["theme", "count"])

    return matrix, zero_match, themes_df


def write_prompt_b(matrix: pd.DataFrame, zero_match: list, themes_df: pd.DataFrame, out_dir: Path) -> None:
    csv_path = out_dir / "prompt_b_barrier_matches.csv"
    md_path = out_dir / "prompt_b_barrier_matches.md"
    matrix.to_csv(csv_path, index=False, encoding="utf-8-sig")

    lines = ["# Prompt B — Barrier Language Match\n", "## Brand x barrier matches\n"]
    lines.append("| Brand | Barrier | Matches | Example quotes (paraphrased) |")
    lines.append("|---|---|---|---|")
    for r in matrix.itertuples():
        lines.append(f"| {r.brand} | {r.barrier} | {r.match_count} | {r.example_quotes} |")

    lines.append("\n## Barriers with zero matches across all data")
    lines.append(", ".join(zero_match) if zero_match else "None — every barrier surfaced at least once.")

    lines.append("\n## Recurring complaint themes NOT on the barrier list (divergences)")
    if themes_df.empty:
        lines.append("None found.")
    else:
        lines.append("| Theme | Mentions |")
        lines.append("|---|---|")
        for r in themes_df.itertuples():
            lines.append(f"| {r.theme} | {r.count} |")

    md_path.write_text("\n".join(lines), encoding="utf-8")
    print(f"  Prompt B written -> {md_path.name}, {csv_path.name}")


# ============================================================
# Prompt C — attribute quadrant validation
# ============================================================

def compute_attribute_tables(classified: pd.DataFrame):
    counts = Counter()
    sample_urls = {}
    for r in classified.itertuples():
        for att in r.attributes:
            attr, sentiment = att.get("attribute"), att.get("sentiment", "neutral")
            if attr not in ATTRIBUTE_TO_QUADRANT:
                continue
            key = (r.brand, attr, ATTRIBUTE_TO_QUADRANT[attr], sentiment)
            counts[key] += 1
            if key not in sample_urls and r.source_url:
                sample_urls[key] = f"[{r.source}]({r.source_url})"

    rows = [
        {"brand": b, "attribute": a, "quadrant": q, "sentiment": s, "mentions": n,
         "example_source": sample_urls.get((b, a, q, s), "")}
        for (b, a, q, s), n in counts.items()
    ]
    detail = pd.DataFrame(rows).sort_values(["brand", "quadrant", "mentions"], ascending=[True, True, False]) if rows else pd.DataFrame(
        columns=["brand", "attribute", "quadrant", "sentiment", "mentions", "example_source"]
    )

    quadrant_share = (
        detail.groupby(["brand", "quadrant"])["mentions"].sum().reset_index()
        if not detail.empty else pd.DataFrame(columns=["brand", "quadrant", "mentions"])
    )
    flags = []
    for brand in quadrant_share["brand"].unique() if not quadrant_share.empty else []:
        sub = quadrant_share[quadrant_share["brand"] == brand].set_index("quadrant")["mentions"]
        low = sub.get("Low Importance", 0)
        key = sub.get("Key Drivers", 0)
        if low > key:
            flags.append(f"{brand}: 'Low Importance' attributes ({low} mentions) get MORE discussion than 'Key Drivers' ({key} mentions).")

    return detail, quadrant_share, flags


def write_prompt_c(detail: pd.DataFrame, quadrant_share: pd.DataFrame, flags: list, out_dir: Path) -> None:
    csv_path = out_dir / "prompt_c_attribute_quadrant.csv"
    md_path = out_dir / "prompt_c_attribute_quadrant.md"
    detail.to_csv(csv_path, index=False, encoding="utf-8-sig")

    lines = ["# Prompt C — Attribute Quadrant Validation\n", "## Quadrant share of conversation, per brand\n"]
    lines.append("| Brand | Quadrant | Mentions |")
    lines.append("|---|---|---|")
    for r in quadrant_share.itertuples():
        lines.append(f"| {r.brand} | {r.quadrant} | {r.mentions} |")

    lines.append("\n## Brand x attribute x sentiment detail\n")
    lines.append("| Brand | Attribute | Quadrant | Sentiment | Mentions | Example source |")
    lines.append("|---|---|---|---|---|---|")
    for r in detail.itertuples():
        lines.append(f"| {r.brand} | {r.attribute} | {r.quadrant} | {r.sentiment} | {r.mentions} | {r.example_source} |")

    lines.append("\n## Flags — 'Low Importance' outweighing 'Key Drivers'")
    lines.append("\n".join(f"- {f}" for f in flags) if flags else "None found.")

    md_path.write_text("\n".join(lines), encoding="utf-8")
    print(f"  Prompt C written -> {md_path.name}, {csv_path.name}")


# ============================================================
# Prompt D — combined triangulation summary
# ============================================================

def write_prompt_d(channel_df: pd.DataFrame, barrier_matrix: pd.DataFrame, zero_match: list,
                    themes_df: pd.DataFrame, attribute_detail: pd.DataFrame,
                    quadrant_share: pd.DataFrame, flags: list, brands: list, out_dir: Path) -> None:
    client = _get_openai_client()
    md_path = out_dir / "prompt_d_triangulation_summary.md"

    sections = ["# Prompt D — Combined Triangulation Summary\n"]
    sections.append(
        "_External scraped data only (Lazada, TikTok Shop, XHS, YouTube, Instagram, Facebook, Reddit, Kiasuparents). "
        "No internal brand tracking, sales, or testing data was used in this analysis._\n"
    )

    online_gaps = channel_df[(channel_df["online_channel"]) & (channel_df["scraped"] == "N")]
    sections.append("## Channel coverage (all brands)")
    if online_gaps.empty:
        sections.append("All online taxonomy categories have some scraper coverage.\n")
    else:
        gap_list = ", ".join(online_gaps.sort_values("priority_rank")["taxonomy_category"])
        sections.append(f"Zero coverage on these online categories: {gap_list}.\n")

    for brand in brands:
        b_barriers = barrier_matrix[barrier_matrix["brand"] == brand] if not barrier_matrix.empty else barrier_matrix
        b_themes = themes_df.head(5) if not themes_df.empty else themes_df
        b_quadrant = quadrant_share[quadrant_share["brand"] == brand] if not quadrant_share.empty else quadrant_share

        top_barriers = b_barriers.sort_values("match_count", ascending=False).head(5)
        barrier_summary = "; ".join(f"{r.barrier} ({r.match_count})" for r in top_barriers.itertuples()) or "no barrier matches found"
        quadrant_summary = "; ".join(f"{r.quadrant}: {r.mentions}" for r in b_quadrant.itertuples()) or "no attribute mentions found"
        theme_summary = "; ".join(f"{r.theme} ({r.count})" for r in b_themes.itertuples()) if not b_themes.empty else "none"
        brand_flags = [f for f in flags if f.startswith(brand + ":")]

        prompt = f"""You are drafting a one-page market-research findings section for the brand "{brand}", \
comparing external scraped review/social data against a reference research framework (channel \
taxonomy, purchase barriers, attribute-importance quadrant).

Data for this brand:
- Top barrier matches found in reviews/social posts: {barrier_summary}
- Zero-match barriers across ALL brands (never surfaced in any scraped text): {", ".join(zero_match) or "none"}
- Recurring complaint/praise themes NOT on the reference barrier list: {theme_summary}
- Attribute-quadrant mention totals: {quadrant_summary}
- Flags: {"; ".join(brand_flags) or "none"}

Write 3-5 short paragraphs (or bullet points) stating, for this brand specifically, where the \
scraped data CONFIRMS the reference research framework and where it DIVERGES. State every \
divergence as a testable hypothesis (e.g. "reviews suggest X, contrary to the reference framework's \
Y — worth flagging as a real signal or a data gap"), never as a settled conclusion. Do not reference \
any internal brand tracking, sales, or testing data — external scraped data only. Plain markdown, no \
headings above ### level."""

        resp = client.chat.completions.create(
            model="gpt-4o-mini",
            messages=[{"role": "user", "content": prompt}],
            max_tokens=800,
        )
        sections.append(f"## {brand}\n")
        sections.append(resp.choices[0].message.content.strip() + "\n")
        print(f"  drafted summary for {brand}")

    md_path.write_text("\n".join(sections), encoding="utf-8")
    print(f"  Prompt D written -> {md_path.name}")


# ============================================================
# Main
# ============================================================

def _archive_outputs(out_dir: Path, label: str) -> None:
    """Copies existing prompt_*.csv/.md files into output/triangulation_sg/history/<timestamp>_<label>/
    before this run overwrites them, so a later run's outputs can always be diffed
    against a prior one (there's no git repo / other versioning for this data)."""
    existing = [p for p in out_dir.glob("prompt_*.*") if p.is_file()]
    if not existing:
        return
    ts = datetime.now().strftime("%Y-%m-%d_%H%M%S")
    archive_dir = out_dir / "history" / f"{ts}_{label}"
    archive_dir.mkdir(parents=True, exist_ok=True)
    for p in existing:
        shutil.copy2(p, archive_dir / p.name)
    print(f"  Archived previous outputs -> {archive_dir}")


def main():
    parser = argparse.ArgumentParser(description="Singapore triangulation analysis (Prompts A-D)")
    parser.add_argument("--prompt", choices=["a", "b", "c", "d", "all"], default="all")
    parser.add_argument("--db", default=str(DEFAULT_DB))
    parser.add_argument("--xhs-db", default=str(DEFAULT_XHS_DB))
    parser.add_argument("--youtube-db", default=str(DEFAULT_YOUTUBE_DB))
    parser.add_argument("--instagram-db", default=str(DEFAULT_INSTAGRAM_DB))
    parser.add_argument("--facebook-db", default=str(DEFAULT_FACEBOOK_DB))
    parser.add_argument("--reddit-db", default=str(DEFAULT_REDDIT_DB))
    parser.add_argument("--gmaps-db", default=str(DEFAULT_GMAPS_DB))
    parser.add_argument("--app-db", default=str(DEFAULT_APP_DB))
    parser.add_argument("--out", default=str(DEFAULT_OUT))
    parser.add_argument("--research-dir", default=str(DEFAULT_RESEARCH_DIR))
    parser.add_argument("--archive-label", default="auto",
                         help="Label used when archiving this run's prior outputs to "
                              "output/triangulation_sg/history/ before overwriting them.")
    args = parser.parse_args()

    db_path = Path(args.db)
    out_dir = Path(args.out)
    research_dir = Path(args.research_dir)
    out_dir.mkdir(parents=True, exist_ok=True)
    cache_path = out_dir / "cache.json"

    if not db_path.exists():
        print(f"Database not found: {db_path}")
        return

    if args.prompt in ("b", "c", "d", "all"):
        _archive_outputs(out_dir, args.archive_label)

    print(f"Reading {db_path} (SG only)...")
    products = load_products_sg(db_path)
    reviews = load_reviews_sg(db_path)
    print(f"  {len(products)} products, {len(reviews)} reviews with English text")

    gmaps_cov = load_gmaps_coverage(Path(args.gmaps_db))
    app_n = load_app_review_count(Path(args.app_db))
    channel_df = barrier_matrix = attribute_detail = quadrant_share = None
    zero_match, themes_df, flags = [], pd.DataFrame(), []

    if args.prompt in ("a", "all"):
        print("Prompt A — channel coverage...")
        evidence_df = load_retailer_evidence(research_dir)
        channel_df = compute_channel_coverage(products, reviews, evidence_df, gmaps_cov, app_n)
        write_prompt_a(channel_df, out_dir)

    if args.prompt in ("b", "c", "d", "all"):
        print("Loading XHS, Kiasuparents, YouTube/Instagram/Facebook/Reddit "
              "and running LLM classification (reused by Prompts B, C, D)...")
        xhs_posts = load_xhs_posts(Path(args.xhs_db))
        forum_posts = load_forum_posts(db_path)
        social_sources = {
            "youtube_comment": load_youtube(Path(args.youtube_db)),
            "instagram_comment": load_instagram(Path(args.instagram_db)),
            "facebook_comment": load_facebook(Path(args.facebook_db)),
            "reddit_comment": load_reddit(Path(args.reddit_db)),
        }
        for label, df in social_sources.items():
            print(f"  {label}: {len(df)} rows")
        classified = classify_all(reviews, xhs_posts, forum_posts, social_sources, cache_path)
        barrier_matrix, zero_match, themes_df = compute_barrier_tables(classified)
        attribute_detail, quadrant_share, flags = compute_attribute_tables(classified)

        if args.prompt in ("b", "all"):
            print("Prompt B — barrier matches...")
            write_prompt_b(barrier_matrix, zero_match, themes_df, out_dir)

        if args.prompt in ("c", "all"):
            print("Prompt C — attribute quadrant...")
            write_prompt_c(attribute_detail, quadrant_share, flags, out_dir)

    if args.prompt in ("d", "all"):
        print("Prompt D — combined summary (one LLM call per brand)...")
        if channel_df is None:
            evidence_df = load_retailer_evidence(research_dir)
            channel_df = compute_channel_coverage(products, reviews, evidence_df, gmaps_cov, app_n)
        brands = FOCUS_BRANDS
        write_prompt_d(channel_df, barrier_matrix, zero_match, themes_df,
                       attribute_detail, quadrant_share, flags, brands, out_dir)

    print(f"\nDone. Outputs in: {out_dir}")


if __name__ == "__main__":
    main()
