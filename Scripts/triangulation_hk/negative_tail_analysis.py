# ============================================================
# Negative Tail Analysis — what's actually driving low-star reviews
# ============================================================
# Classifies EVERY HK review (all star ratings) via gpt-4o-mini into BOTH a
# complaint category (COMPLAINT_CATEGORIES) and a separately-worded praise
# category (PRAISE_CATEGORIES) — the two taxonomies are independent so a
# mixed review can carry a real complaint and a real praise at once. Writes:
#   - negative_tail_reviews.csv   — one row per review, every rating 1-5,
#     used by the dashboard's interactive "max rating" filter so the
#     complaint/praise breakdown can be explored live (1-star only, up to
#     2-star, up to 3-star, etc.) without re-running this script.
#   - negative_tail_analysis.md/.csv — a static default report scoped to
#     1-star reviews only (~130), the same "negative tail" headline view
#     as before, for anyone reading the file directly rather than using
#     the dashboard.
#
# Also cross-checks against triangulation/run_triangulation.py's Prompt C
# output (prompt_c_attribute_quadrant.csv), which already scores
# attribute sentiment across reviews + XHS + reputation.csv. If a brand's
# top complaint category has a comparable attribute that's ALSO praised
# a lot elsewhere (e.g. "comfort/dryness" complaints vs. plenty of
# positive "comfortable for eyes" mentions), that's a polarizing
# attribute — some customers love it, others really don't — worth
# flagging distinctly from attributes that are uniformly one-sided.
#
# Usage:
#   python negative_tail_analysis.py
#
# Scope: Hong Kong data only, same as the rest of triangulation/. The
# default static report is 1-star only (~130 reviews) — a small base.
# Per-brand splits under 15 reviews (at whatever rating cutoff is in
# view) are flagged as directional, not reliable.
# ============================================================

import argparse
import json
import re
import sqlite3
from collections import Counter
from pathlib import Path

import pandas as pd
from dotenv import load_dotenv

load_dotenv()

ROOT = Path(__file__).resolve().parent.parent
DEFAULT_DB = ROOT / "output" / "lensdata.db"
DEFAULT_OUT = ROOT / "output" / "triangulation"

CLASSIFY_BATCH_SIZE = 15
SMALL_BASE_THRESHOLD = 15  # per-brand review count below this = directional only
DEFAULT_REPORT_MAX_RATING = 1  # the static .md/.csv report defaults to 1-star only

COMPLAINT_CATEGORIES = [
    "comfort/dryness",
    "price",
    "shipping/fulfillment",
    "product mismatch/counterfeit concern",
    "customer service",
    "packaging",
    "quality/defect (other)",
    "no complaint / positive feedback",
    "unclear / insufficient detail",
]

# A separate, positively-framed taxonomy for what a review PRAISES. Kept distinct
# from COMPLAINT_CATEGORIES rather than reusing the same labels for both directions
# — "product mismatch/counterfeit concern" or "quality/defect (other)" read as
# complaints even when the review being classified is a 5-star rave, which was
# confusing in the dashboard's Praise view. Categories roughly mirror the
# complaint list topic-for-topic so the two views stay comparable, but with
# wording that makes sense when applied to positive reviews.
PRAISE_CATEGORIES = [
    "comfort",
    "value for money",
    "shipping/fulfillment",
    "authenticity / genuine product",
    "customer service",
    "packaging",
    "quality/reliability (other)",
    "general satisfaction / no specific theme",
    "no praise / negative review",
    "unclear / insufficient detail",
]

# Rough conceptual links from a complaint category to a Prompt C attribute-quadrant
# attribute, used only for the polarization cross-check. Left empty where there's no
# defensible match — better to skip a comparison than force a tenuous one.
COMPLAINT_TO_ATTRIBUTE = {
    "comfort/dryness": "comfortable for eyes",
    "product mismatch/counterfeit concern": "trustworthy brand",
}
POLARIZATION_MIN_POSITIVE_MENTIONS = 3  # floor to filter noise, not a claim of significance


# ============================================================
# DB loading
# ============================================================

def load_reviews_hk(db_path: Path) -> pd.DataFrame:
    """All HK reviews with English text, any star rating 1-5 (the single stray
    rating=0 row seen in the data is excluded as a data artifact)."""
    conn = sqlite3.connect(db_path)
    df = pd.read_sql_query(
        "SELECT reviews.*, products.url AS source_url FROM reviews "
        "LEFT JOIN products ON reviews.product_code = products.product_code "
        "WHERE reviews.market = 'HK' AND reviews.rating BETWEEN 1 AND 5 "
        "AND reviews.review_text_en IS NOT NULL AND TRIM(reviews.review_text_en) != ''",
        conn,
    )
    conn.close()
    return df


# ============================================================
# LLM classification (same robust batch + straggler-retry pattern as
# run_triangulation.py's classify.py — kept local rather than imported
# so this script stays a single self-contained file).
# ============================================================

CLASSIFY_INSTRUCTIONS = f"""You are analyzing contact lens reviews (all star ratings) for a market research project.

For each numbered review below, identify:
1. "category": the SINGLE best-fit COMPLAINT category, copied verbatim from this list:
{json.dumps(COMPLAINT_CATEGORIES, ensure_ascii=False)}
   Guidance:
   - Use "no complaint / positive feedback" for reviews that are simply happy/satisfied with nothing
     wrong reported (e.g. "great product, will buy again") — do NOT force these into a complaint bucket.
   - Use "quality/defect (other)" for a real complaint about product quality/defects/fit/prescription
     that doesn't fit comfort/dryness, packaging, or the other named categories.
   - Use "unclear / insufficient detail" only when the review has no usable content (e.g. blank,
     "good", a single emoji, or otherwise gives no signal either way).
2. "praise_category": the SINGLE best-fit PRAISE category, copied verbatim from this separate list:
{json.dumps(PRAISE_CATEGORIES, ensure_ascii=False)}
   Guidance:
   - This is independent of "category" above — a mixed review can name a specific complaint AND a
     specific praise (e.g. complains about price but praises comfort); classify both.
   - Use "no praise / negative review" when the review is a straightforward complaint with nothing
     positive called out.
   - Use "general satisfaction / no specific theme" for reviews that are happy overall but don't name
     a specific thing they liked (e.g. "great product, will buy again").
   - Use "unclear / insufficient detail" only when the review has no usable content.
3. "summary": a one-sentence PARAPHRASED (not verbatim) English summary of what the review actually
   says (complaint OR praise, whichever applies), under 20 words.

Return ONLY a JSON array with exactly {{n}} objects, one per review, in the same order, each with
keys: category, praise_category, summary. No other text in your response."""


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
    return {
        "category": "unclear / insufficient detail",
        "praise_category": "unclear / insufficient detail",
        "summary": None,
    }


def _sanitize_classification(obj) -> dict:
    if not isinstance(obj, dict):
        return _empty_classification()
    category = obj.get("category")
    if category not in COMPLAINT_CATEGORIES:
        category = "unclear / insufficient detail"
    praise_category = obj.get("praise_category")
    if praise_category not in PRAISE_CATEGORIES:
        praise_category = "unclear / insufficient detail"
    summary = obj.get("summary")
    summary = summary if isinstance(summary, str) else None
    return {"category": category, "praise_category": praise_category, "summary": summary}


def classify_batch(texts: list, client):
    """Returns a sanitized list of classifications, or None if the batch could not
    be parsed / didn't come back 1:1 (caller should retry, not cache, on None)."""
    numbered = "\n".join(f"{i + 1}. {t[:600]}" for i, t in enumerate(texts))
    prompt = CLASSIFY_INSTRUCTIONS.replace("{n}", str(len(texts))) + f"\n\nReviews:\n{numbered}"
    try:
        resp = client.chat.completions.create(
            model="gpt-4o-mini",
            messages=[{"role": "user", "content": prompt}],
            max_tokens=2000,
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


def classify_all_reviews(reviews: pd.DataFrame, cache_path: Path) -> pd.DataFrame:
    items = [
        {
            "key": r.content_hash, "brand": r.brand, "rating": r.rating, "text": r.review_text_en,
            "source_url": getattr(r, "source_url", "") or "",
        }
        for r in reviews.itertuples()
    ]

    cache = _load_cache(cache_path)
    # An item only counts as cached once it has both the complaint and praise
    # category — older cache entries written before praise_category existed
    # are treated as missing and get reclassified.
    to_fetch = [it for it in items if "praise_category" not in cache.get(it["key"], {})]
    print(f"  {len(items)} reviews, {len(items) - len(to_fetch)} already cached, {len(to_fetch)} to classify")

    if to_fetch:
        client = _get_openai_client()
        stragglers = []
        for i in range(0, len(to_fetch), CLASSIFY_BATCH_SIZE):
            batch = to_fetch[i:i + CLASSIFY_BATCH_SIZE]
            results = classify_batch([b["text"] for b in batch], client)
            if results is None:
                stragglers.extend(batch)
            else:
                for b, res in zip(batch, results):
                    cache[b["key"]] = res
            print(f"  classified {min(i + CLASSIFY_BATCH_SIZE, len(to_fetch))}/{len(to_fetch)}")
            _save_cache(cache_path, cache)

        if stragglers:
            print(f"  retrying {len(stragglers)} straggler items one at a time...")
            for b in stragglers:
                results = classify_batch([b["text"]], client)
                cache[b["key"]] = results[0] if results else _empty_classification()
            _save_cache(cache_path, cache)

    rows = []
    for it in items:
        res = cache.get(it["key"], _empty_classification())
        rows.append({
            "brand": it["brand"], "rating": it["rating"], "text": it["text"], "source_url": it["source_url"],
            "category": res.get("category", "other"),
            "praise_category": res.get("praise_category", "other"),
            "summary": res.get("summary"),
        })
    return pd.DataFrame(rows)


# ============================================================
# Aggregation
# ============================================================

def compute_category_breakdown(classified: pd.DataFrame) -> pd.DataFrame:
    """`classified` should already be filtered to whatever rating cutoff is in
    scope (e.g. rating == 1 for the default report) — this just aggregates
    whatever subset it's given."""
    rows = []
    for brand, brand_df in classified.groupby("brand"):
        brand_total = len(brand_df)
        small_base = brand_total < SMALL_BASE_THRESHOLD
        counts = Counter(brand_df["category"])
        for category in COMPLAINT_CATEGORIES:
            count = counts.get(category, 0)
            rows.append({
                "brand": brand,
                "category": category,
                "count": count,
                "pct_of_brand_reviews": round(count / brand_total * 100, 1) if brand_total else 0.0,
                "brand_review_total": brand_total,
                "small_base_flag": small_base,
            })
    df = pd.DataFrame(rows)
    return df[df["count"] > 0].sort_values(["brand", "count"], ascending=[True, False]).reset_index(drop=True)


def compute_qualitative_examples(classified: pd.DataFrame, n_per_group: int = 3) -> pd.DataFrame:
    rows = []
    for (brand, category), group in classified.groupby(["brand", "category"]):
        examples = group[group["summary"].notna()].head(n_per_group)
        for r in examples.itertuples():
            rows.append({
                "brand": brand, "category": category,
                "summary": r.summary, "source_url": r.source_url,
            })
    return pd.DataFrame(rows).sort_values(["brand", "category"]).reset_index(drop=True)


def compute_polarization_candidates(breakdown: pd.DataFrame, out_dir: Path) -> list:
    prompt_c_path = out_dir / "prompt_c_attribute_quadrant.csv"
    if not prompt_c_path.exists():
        return []  # graceful skip — run_triangulation.py hasn't been run yet
    attr_df = pd.read_csv(prompt_c_path)

    candidates = []
    for brand, brand_df in breakdown.groupby("brand"):
        top_categories = set(brand_df.nlargest(2, "count")["category"])
        for category in top_categories:
            attribute = COMPLAINT_TO_ATTRIBUTE.get(category)
            if not attribute:
                continue
            match = attr_df[
                (attr_df["brand"] == brand) & (attr_df["attribute"] == attribute)
                & (attr_df["sentiment"] == "positive")
            ]
            positive_mentions = int(match["mentions"].sum()) if not match.empty else 0
            if positive_mentions >= POLARIZATION_MIN_POSITIVE_MENTIONS:
                complaint_row = brand_df[brand_df["category"] == category].iloc[0]
                candidates.append(
                    f"{brand}: \"{category}\" is a top complaint ({int(complaint_row['count'])} reviews, "
                    f"{complaint_row['pct_of_brand_reviews']}% of this brand's reviews in scope) — but \"{attribute}\" "
                    f"also gets {positive_mentions} positive mentions elsewhere (Prompt C). Possible polarizing "
                    f"attribute: some customers love it, others don't, rather than a uniformly negative signal."
                )
    return candidates


# ============================================================
# Output
# ============================================================

def write_negative_tail_reviews_raw(classified_all: pd.DataFrame, out_dir: Path) -> None:
    """One row per review, every rating 1-5 — the file the dashboard's interactive
    rating-cutoff filter reads, so the whole tab can be re-sliced live without
    re-running this script."""
    cols = ["brand", "rating", "category", "praise_category", "summary", "source_url"]
    classified_all[cols].to_csv(out_dir / "negative_tail_reviews.csv", index=False, encoding="utf-8-sig")
    print(f"  Raw per-review data written -> negative_tail_reviews.csv ({len(classified_all)} reviews, all ratings)")


def write_negative_tail(breakdown: pd.DataFrame, examples: pd.DataFrame, candidates: list, out_dir: Path, max_rating: int) -> None:
    breakdown.to_csv(out_dir / "negative_tail_analysis.csv", index=False, encoding="utf-8-sig")
    examples.to_csv(out_dir / "negative_tail_examples.csv", index=False, encoding="utf-8-sig")

    total_reviews = breakdown.drop_duplicates("brand")["brand_review_total"].sum()
    scope = "1-star" if max_rating == 1 else f"{max_rating}-star or lower"
    lines = [f"# Negative Tail Analysis — What's Driving {scope.title()} Reviews\n"]
    lines.append(
        f"Based on {total_reviews} HK reviews rated {scope} — a small base. Treat every split here as "
        "directional, not statistically robust, especially per-brand. (The dashboard's Negative Tail tab "
        "lets you explore other rating cutoffs interactively; this file is the 1-star default.)\n"
    )

    small_base_brands = sorted(breakdown[breakdown["small_base_flag"]]["brand"].unique().tolist())
    if small_base_brands:
        lines.append(
            f"**Small-base brands (fewer than {SMALL_BASE_THRESHOLD} reviews in scope — directional only):** "
            f"{', '.join(small_base_brands)}.\n"
        )

    lines.append(
        "**Note on the three catch-all categories:** the six specific categories (product "
        "mismatch/counterfeit, comfort/dryness, shipping/fulfillment, customer service, packaging, "
        "price) are reviews that clearly named one of those issues. Everything else used to be lumped "
        "into one generic \"other\" bucket — that's been split into three more specific ones so \"other\" "
        "doesn't hide what's actually going on: **quality/defect (other)** (a real complaint that isn't "
        "one of the six named issues), **no complaint / positive feedback** (a happy review, nothing "
        "wrong), and **unclear / insufficient detail** (blank or uninformative text).\n"
    )

    lines.append("## Complaint category breakdown, per brand\n")
    lines.append("| Brand | Category | Count | % of brand's reviews in scope |")
    lines.append("|---|---|---|---|")
    for r in breakdown.itertuples():
        flag = " *" if r.small_base_flag else ""
        lines.append(f"| {r.brand}{flag} | {r.category} | {r.count} | {r.pct_of_brand_reviews}% |")
    lines.append(f"\n_\\* small-base brand (under {SMALL_BASE_THRESHOLD} reviews in scope) — directional only._")

    lines.append("\n## Qualitative appendix — representative paraphrased complaints\n")
    for (brand, category), group in examples.groupby(["brand", "category"]):
        lines.append(f"**{brand} — {category}**")
        for r in group.itertuples():
            lines.append(f"- [{r.summary}]({r.source_url})" if r.source_url else f"- {r.summary}")
        lines.append("")

    lines.append("## Polarization candidates — complaints that are ALSO praised elsewhere\n")
    if candidates:
        for c in candidates:
            lines.append(f"- {c}")
    else:
        lines.append(
            "None found (or run `python triangulation/run_triangulation.py` first — this check reads "
            "its Prompt C output)."
        )

    (out_dir / "negative_tail_analysis.md").write_text("\n".join(lines), encoding="utf-8")
    print(f"  Negative Tail written -> negative_tail_analysis.md/.csv, negative_tail_examples.csv")


def main():
    parser = argparse.ArgumentParser(description="Negative Tail Analysis — review complaint categories, all ratings")
    parser.add_argument("--db", default=str(DEFAULT_DB))
    parser.add_argument("--out", default=str(DEFAULT_OUT))
    args = parser.parse_args()

    db_path = Path(args.db)
    out_dir = Path(args.out)
    out_dir.mkdir(parents=True, exist_ok=True)
    cache_path = out_dir / "negative_tail_cache.json"

    if not db_path.exists():
        print(f"Database not found: {db_path}")
        return

    reviews = load_reviews_hk(db_path)
    print(f"Loaded {len(reviews)} HK reviews (all ratings)")
    if reviews.empty:
        print("No reviews found — nothing to do.")
        return

    classified_all = classify_all_reviews(reviews, cache_path)
    write_negative_tail_reviews_raw(classified_all, out_dir)

    # Static default report: 1-star only, same headline view as before.
    classified_default = classified_all[classified_all["rating"] <= DEFAULT_REPORT_MAX_RATING]
    breakdown = compute_category_breakdown(classified_default)
    examples = compute_qualitative_examples(classified_default)
    candidates = compute_polarization_candidates(breakdown, out_dir)
    write_negative_tail(breakdown, examples, candidates, out_dir, DEFAULT_REPORT_MAX_RATING)


if __name__ == "__main__":
    main()
