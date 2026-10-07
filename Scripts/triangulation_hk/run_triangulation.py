# ============================================================
# Triangulation Analysis — checks scraped review/product data
# against the research framework described in insight.txt
# ============================================================
# What this does (see insight.txt for the full brief):
#   Prompt A — channel coverage gap check
#   Prompt B — purchase-barrier language match
#   Prompt C — attribute quadrant validation
#   Prompt D — combined triangulation summary (one page per brand)
#
# Usage:
#   python run_triangulation.py                 # runs all four prompts
#   python run_triangulation.py --prompt a      # channel coverage only, no LLM/cost
#   python run_triangulation.py --prompt b      # barrier match only
#   python run_triangulation.py --prompt c      # attribute quadrant only
#   python run_triangulation.py --prompt d      # combined summary only
#
# Scope: Hong Kong data only (market == 'HK'). Thailand rows are excluded
# because the reference taxonomy/barriers/attributes are HK-specific.
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

from mappings import BARRIERS, CHANNEL_TAXONOMY, ATTRIBUTE_QUADRANT, ATTRIBUTE_TO_QUADRANT

load_dotenv()

ROOT = Path(__file__).resolve().parent.parent
DEFAULT_DB = ROOT / "output" / "lensdata.db"
DEFAULT_YOUTUBE_DB = ROOT / "output" / "youtube_data.db"
DEFAULT_INSTAGRAM_DB = ROOT / "output" / "instagram_data.db"
DEFAULT_FACEBOOK_DB = ROOT / "output" / "facebook_data.db"
DEFAULT_OUT = ROOT / "output" / "triangulation"

CLASSIFY_BATCH_SIZE = 15  # reviews/posts per LLM classification call


# ============================================================
# DB loading (HK only)
# ============================================================

def load_products_hk(db_path: Path) -> pd.DataFrame:
    conn = sqlite3.connect(db_path)
    df = pd.read_sql_query("SELECT * FROM products WHERE market = 'HK'", conn)
    conn.close()
    return df


def load_reviews_hk(db_path: Path) -> pd.DataFrame:
    """Joins in products.url as source_url so each review can be traced back to its product page."""
    conn = sqlite3.connect(db_path)
    df = pd.read_sql_query(
        "SELECT reviews.*, products.url AS source_url FROM reviews "
        "LEFT JOIN products ON reviews.product_code = products.product_code "
        "WHERE reviews.market = 'HK' "
        "AND reviews.review_text_en IS NOT NULL AND TRIM(reviews.review_text_en) != ''",
        conn,
    )
    conn.close()
    return df


def load_xhs_posts(db_path: Path) -> pd.DataFrame:
    """xhs_posts has no market column — content is HK-brand-keyword seeded already."""
    conn = sqlite3.connect(db_path)
    try:
        df = pd.read_sql_query(
            "SELECT * FROM xhs_posts WHERE content_en IS NOT NULL AND TRIM(content_en) != ''",
            conn,
        )
    except pd.errors.DatabaseError:
        df = pd.DataFrame()
    conn.close()
    return df


def load_retailer_evidence(research_dir: Path) -> pd.DataFrame:
    """
    Combines Research/distribution.csv and Research/pricing.csv (HK rows only) into
    one retailer-evidence table: retailer | status | source_url | source_file.
    Both files are manually curated by the research team (separate from the scraper)
    and both carry a source_url, so this is the evidence used to flag "known but not
    yet scraped" channels in Prompt A, with a clickable citation for each claim.
    """
    frames = []

    dist_path = research_dir / "distribution.csv"
    if dist_path.exists():
        d = pd.read_csv(dist_path)
        d = d[d["market"] == "HK"][["retailer", "status", "source_url"]].copy()
        d["source_file"] = "distribution.csv"
        frames.append(d)
    else:
        print(f"  (note: {dist_path} not found — skipping)")

    price_path = research_dir / "pricing.csv"
    if price_path.exists():
        p = pd.read_csv(price_path)
        p = p[p["market"] == "HK"][["store", "source_url"]].rename(columns={"store": "retailer"}).copy()
        p["status"] = "Observed price"
        p["source_file"] = "pricing.csv"
        frames.append(p)
    else:
        print(f"  (note: {price_path} not found — skipping)")

    if not frames:
        return pd.DataFrame(columns=["retailer", "status", "source_url", "source_file"])
    return pd.concat(frames, ignore_index=True).drop_duplicates(subset=["retailer", "source_url"])


def load_reputation_csv(research_dir: Path) -> pd.DataFrame:
    """
    Research/reputation.csv — manually curated external forum/press sentiment quotes
    (e.g. Baby Kingdom threads), HK rows only. Same shape of signal as reviews/XHS
    (consumer language about brands), so it's fed into the same barrier/attribute
    classification pass, each row carrying its own source_url for traceability.
    """
    path = research_dir / "reputation.csv"
    if not path.exists():
        print(f"  (note: {path} not found — skipping reputation.csv as a classification source)")
        return pd.DataFrame(columns=["brand", "summary", "source_url"])
    df = pd.read_csv(path)
    return df[df["market"] == "HK"][["brand", "summary", "source_url"]].copy()


_SOCIAL_COLUMNS = ["key", "brand", "text", "source_url"]


def load_youtube(db_path: Path) -> pd.DataFrame:
    """youtube_comments joined to youtube_videos; brand/comment_text_en already
    English + canonical-cased (matches reviews.brand), HK only, relevance-filtered
    (video judged on-brand and comment judged lens-relevant) upstream by youtube_signals.py."""
    if not db_path.exists():
        print(f"  (note: {db_path} not found — skipping YouTube as a classification source)")
        return pd.DataFrame(columns=_SOCIAL_COLUMNS)
    conn = sqlite3.connect(db_path)
    try:
        df = pd.read_sql_query(
            "SELECT c.content_hash AS key, c.brand AS brand, c.comment_text_en AS text, "
            "v.url AS source_url FROM youtube_comments c "
            "JOIN youtube_videos v ON c.video_id = v.video_id "
            "WHERE c.market = 'HK' AND v.brand_relevant != 0 AND c.is_lens_relevant != 0 "
            "AND c.comment_text_en IS NOT NULL AND TRIM(c.comment_text_en) != ''",
            conn,
        )
    except pd.errors.DatabaseError:
        df = pd.DataFrame(columns=_SOCIAL_COLUMNS)
    conn.close()
    return df


def load_instagram(db_path: Path) -> pd.DataFrame:
    """ig_comments joined to ig_posts; same relevance-gating pattern as YouTube, plus
    post-level brand_relevant since HK resellers hashtag-stuff multiple brands onto one post."""
    if not db_path.exists():
        print(f"  (note: {db_path} not found — skipping Instagram as a classification source)")
        return pd.DataFrame(columns=_SOCIAL_COLUMNS)
    conn = sqlite3.connect(db_path)
    try:
        df = pd.read_sql_query(
            "SELECT c.content_hash AS key, c.brand AS brand, c.comment_text_en AS text, "
            "p.url AS source_url FROM ig_comments c "
            "JOIN ig_posts p ON c.post_id = p.post_id "
            "WHERE c.market = 'HK' AND p.is_lens_relevant != 0 AND p.brand_relevant != 0 "
            "AND c.is_lens_relevant != 0 "
            "AND c.comment_text_en IS NOT NULL AND TRIM(c.comment_text_en) != ''",
            conn,
        )
    except pd.errors.DatabaseError:
        df = pd.DataFrame(columns=_SOCIAL_COLUMNS)
    conn.close()
    return df


def load_facebook(db_path: Path) -> pd.DataFrame:
    """fb_reviews has no market column (the 5 tracked pages are HK-only by construction)
    and mentioned_brands is comma-joined/multi-valued, so a review naming two brands is
    exploded into one classification item per brand — same as how facebook_signals.py
    handles per-brand metrics elsewhere in the dashboard."""
    if not db_path.exists():
        print(f"  (note: {db_path} not found — skipping Facebook as a classification source)")
        return pd.DataFrame(columns=_SOCIAL_COLUMNS)
    conn = sqlite3.connect(db_path)
    try:
        df = pd.read_sql_query(
            "SELECT id, mentioned_brands, text_english, review_url FROM fb_reviews "
            "WHERE mentioned_brands IS NOT NULL AND TRIM(mentioned_brands) != '' "
            "AND text_english IS NOT NULL AND TRIM(text_english) != ''",
            conn,
        )
    except pd.errors.DatabaseError:
        df = pd.DataFrame()
    conn.close()
    if df.empty:
        return pd.DataFrame(columns=_SOCIAL_COLUMNS)
    df["brand"] = df["mentioned_brands"].str.split(",")
    df = df.explode("brand")
    df["brand"] = df["brand"].str.strip()
    df["key"] = "fb::" + df["id"].astype(str) + "::" + df["brand"]
    df = df.rename(columns={"text_english": "text", "review_url": "source_url"})
    return df[_SOCIAL_COLUMNS]


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


def compute_channel_coverage(products: pd.DataFrame, reviews: pd.DataFrame, evidence_df: pd.DataFrame) -> pd.DataFrame:
    rows = []
    for cat in CHANNEL_TAXONOMY:
        name, examples, online = cat["category"], cat["examples"], cat["online"]

        if name == "HKTVmall":
            prod_mask = products["site"] == "hktvmall"
            rev_mask = reviews["site"] == "hktvmall"
            matched_stores = ["(all HKTVmall marketplace sellers)"]
        elif examples:
            prod_mask = _text_match_mask(products["store_name"], examples)
            rev_mask = _text_match_mask(reviews["store_name"], examples)
            matched_stores = sorted(products.loc[prod_mask, "store_name"].dropna().unique().tolist())
        else:
            prod_mask = pd.Series(False, index=products.index)
            rev_mask = pd.Series(False, index=reviews.index)
            matched_stores = []

        product_count = int(prod_mask.sum())
        review_count = int(rev_mask.sum())
        scraped = "Y" if product_count > 0 else "N"

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
            if evidence_matches:
                notes += " Known retailers per research: " + "; ".join(evidence_matches) + "."
        elif scraped == "Y":
            notes = f"Scraped via: {', '.join(matched_stores)}. Example: {sample_scraped_url}"
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
        "\n_Offline categories (independent optical stores, chain optical stores, "
        "supermarkets/department stores, optometric centres, open-concept shops) are "
        "listed above for completeness against the reference framework, but are not "
        "prioritized — a web scraper cannot reach physical/walk-in retail._"
    )

    md_path.write_text("\n".join(lines), encoding="utf-8")
    print(f"  Prompt A written -> {md_path.name}, {csv_path.name}")


# ============================================================
# Shared LLM classification pass (feeds Prompts B and C)
# ============================================================

ALL_ATTRIBUTES = [attr for attrs in ATTRIBUTE_QUADRANT.values() for attr in attrs]

CLASSIFY_INSTRUCTIONS = f"""You are analyzing Hong Kong contact lens customer reviews and social media \
posts for a market research triangulation project.

For each numbered text below, identify:
1. "barriers": which of these exact phrases (copy verbatim from this list, or return an empty \
list) the text expresses as a reason for NOT choosing/switching to a brand:
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


def classify_all(reviews: pd.DataFrame, xhs_posts: pd.DataFrame, reputation: pd.DataFrame,
                  social_sources: dict, cache_path: Path) -> pd.DataFrame:
    """
    Returns one row per review/post/reputation-quote/social-comment with brand +
    classification fields merged in. Every item carries a source_url so quotes in the
    output can link back to the original review page / XHS post / forum thread / video
    / IG post / FB review.

    `social_sources` is {source_label: df} where each df already has the normalized
    columns key/brand/text/source_url (see load_youtube/load_instagram/load_facebook) —
    a generic loop handles any number of these without growing this function's signature
    further as sources get added.
    """
    # reviews.brand is the canonical casing (from products/reviews tables); xhs and
    # reputation.csv sometimes use different casing (e.g. "OLENS" vs "Olens") for the
    # same brand — normalize so they aren't counted as separate brands downstream.
    canonical_brands = sorted(reviews["brand"].dropna().unique().tolist())
    brand_lookup = {b.lower(): b for b in canonical_brands}

    def _normalize_brand(name: str) -> str:
        if not name:
            return "other"
        return brand_lookup.get(name.strip().lower(), name)

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
    for rep in reputation.itertuples():
        items.append({
            "key": f"reputation::{rep.source_url}", "brand": _normalize_brand(rep.brand), "source": "reputation.csv",
            "text": rep.summary, "source_url": rep.source_url,
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
        "_External scraped data only (HKTVmall, 393lens, XHS, YouTube, Instagram, Facebook). "
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
    """Copies existing prompt_*.csv/.md files into output/triangulation/history/<timestamp>_<label>/
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
    parser = argparse.ArgumentParser(description="Triangulation analysis (insight.txt Prompts A-D)")
    parser.add_argument("--prompt", choices=["a", "b", "c", "d", "all"], default="all")
    parser.add_argument("--db", default=str(DEFAULT_DB))
    parser.add_argument("--youtube-db", default=str(DEFAULT_YOUTUBE_DB))
    parser.add_argument("--instagram-db", default=str(DEFAULT_INSTAGRAM_DB))
    parser.add_argument("--facebook-db", default=str(DEFAULT_FACEBOOK_DB))
    parser.add_argument("--out", default=str(DEFAULT_OUT))
    parser.add_argument("--research-dir", default=str(ROOT / "Research"))
    parser.add_argument("--archive-label", default="auto",
                         help="Label used when archiving this run's prior outputs to "
                              "output/triangulation/history/ before overwriting them.")
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

    print(f"Reading {db_path} (HK only)...")
    products = load_products_hk(db_path)
    reviews = load_reviews_hk(db_path)
    print(f"  {len(products)} products, {len(reviews)} reviews with English text")

    channel_df = barrier_matrix = attribute_detail = quadrant_share = None
    zero_match, themes_df, flags = [], pd.DataFrame(), []

    if args.prompt in ("a", "all"):
        print("Prompt A — channel coverage...")
        evidence_df = load_retailer_evidence(research_dir)
        channel_df = compute_channel_coverage(products, reviews, evidence_df)
        write_prompt_a(channel_df, out_dir)

    if args.prompt in ("b", "c", "d", "all"):
        print("Loading XHS posts, Research/reputation.csv, YouTube/Instagram/Facebook "
              "and running LLM classification (reused by Prompts B, C, D)...")
        xhs_posts = load_xhs_posts(db_path)
        reputation = load_reputation_csv(research_dir)
        social_sources = {
            "youtube_comment": load_youtube(Path(args.youtube_db)),
            "instagram_comment": load_instagram(Path(args.instagram_db)),
            "facebook_review": load_facebook(Path(args.facebook_db)),
        }
        for label, df in social_sources.items():
            print(f"  {label}: {len(df)} rows")
        classified = classify_all(reviews, xhs_posts, reputation, social_sources, cache_path)
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
            channel_df = compute_channel_coverage(products, reviews, evidence_df)
        brands = sorted(reviews["brand"].dropna().unique().tolist())
        write_prompt_d(channel_df, barrier_matrix, zero_match, themes_df,
                       attribute_detail, quadrant_share, flags, brands, out_dir)

    print(f"\nDone. Outputs in: {out_dir}")


if __name__ == "__main__":
    main()
