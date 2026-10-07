# ============================================================
# Share of Voice — shelf presence vs. social conversation, per HK brand
# ============================================================
# For each HK brand, compares:
#   share of shelf   = % of HK products
#   share of voice   = % of brand-attributed XHS posts
#   (review count is also reported, and used to size the dashboard's
#   quadrant-chart bubbles)
#
# Brands above the y=x line get more social conversation than their
# shelf presence would predict ("overindexed"); brands below get less
# ("underindexed").
#
# Also breaks down each brand's own XHS sentiment mix (positive/negative/
# neutral %) and a net-sentiment score, so high-voice brands can be told
# apart on whether that voice is positive or just loud.
#
# Usage:
#   python share_of_voice.py                # writes share_of_voice.md + .csv
#
# Scope: Hong Kong data only, same as run_triangulation.py. XHS share is
# computed against brand-attributed posts only — posts XHS assigned to
# "other" (unattributed) are excluded from that denominator, not from
# the products/reviews counts.
# ============================================================

import argparse
import json
import sqlite3
from collections import Counter
from pathlib import Path

import pandas as pd

ROOT = Path(__file__).resolve().parent.parent
DEFAULT_DB = ROOT / "output" / "lensdata.db"
DEFAULT_OUT = ROOT / "output" / "triangulation"

SMALL_BASE_THRESHOLD = 100  # HK product count below this = "smaller base" footnote
XHS_SMALL_BASE_THRESHOLD = 200  # brand-attributed XHS post count below this = low-confidence bubble
DIVERGENCE_THRESHOLD_PP = 20  # |XHS net sentiment - review net sentiment| above this = "Platform divergence"
MIN_THEME_COUNT = 30  # drop XHS theme tags rarer than this from the theme-sentiment breakdown


def compute_share_of_voice(db_path: Path):
    conn = sqlite3.connect(db_path)
    products = pd.read_sql_query("SELECT * FROM products WHERE market = 'HK'", conn)
    reviews = pd.read_sql_query("SELECT * FROM reviews WHERE market = 'HK'", conn)
    try:
        xhs = pd.read_sql_query("SELECT brand_mentioned, sentiment FROM xhs_posts", conn)
    except pd.errors.DatabaseError:
        xhs = pd.DataFrame(columns=["brand_mentioned", "sentiment"])
    conn.close()

    canonical_brands = sorted(products["brand"].dropna().unique().tolist())
    # XHS brand tags sometimes differ in casing from the canonical DB brand
    # names (e.g. "OLENS" vs "Olens") — normalize so they aren't undercounted.
    brand_lookup = {b.lower(): b for b in canonical_brands}
    xhs["brand_norm"] = xhs["brand_mentioned"].apply(
        lambda x: brand_lookup.get(str(x).strip().lower()) if pd.notna(x) else None
    )
    xhs_attributed = xhs[xhs["brand_norm"].notna()]

    total_products = len(products)
    total_reviews = len(reviews)
    total_xhs_attributed = len(xhs_attributed)
    total_xhs_excluded = len(xhs) - total_xhs_attributed

    rows = []
    for brand in canonical_brands:
        product_count = int((products["brand"] == brand).sum())
        review_count = int((reviews["brand"] == brand).sum())
        brand_posts = xhs_attributed[xhs_attributed["brand_norm"] == brand]
        xhs_count = len(brand_posts)

        pct_products = product_count / total_products * 100 if total_products else 0.0
        pct_reviews = review_count / total_reviews * 100 if total_reviews else 0.0
        pct_xhs = xhs_count / total_xhs_attributed * 100 if total_xhs_attributed else 0.0
        gap_pp = pct_xhs - pct_products
        small_base = product_count < SMALL_BASE_THRESHOLD

        # Sentiment mix within this brand's own posts. Anything outside the three
        # expected labels (e.g. a stray "warning" value seen in the data) is bucketed
        # as "unclassified" rather than silently dropped or crashing the split.
        positive_count = int((brand_posts["sentiment"] == "positive").sum())
        negative_count = int((brand_posts["sentiment"] == "negative").sum())
        neutral_count = int((brand_posts["sentiment"] == "neutral").sum())
        unclassified_count = xhs_count - positive_count - negative_count - neutral_count

        pct_positive = positive_count / xhs_count * 100 if xhs_count else 0.0
        pct_negative = negative_count / xhs_count * 100 if xhs_count else 0.0
        pct_neutral = neutral_count / xhs_count * 100 if xhs_count else 0.0
        # Net sentiment as a share of THIS brand's own posts (not the grand total) —
        # a volume-independent quality score, comparable across brands regardless
        # of how much they're talked about.
        net_sentiment_pct = (positive_count - negative_count) / xhs_count * 100 if xhs_count else 0.0
        xhs_small_base = xhs_count < XHS_SMALL_BASE_THRESHOLD

        # Review-based sentiment proxy: % five-star minus % one-star, same "net" shape
        # as the XHS score, so the two are directly comparable side by side.
        brand_reviews = reviews[reviews["brand"] == brand]
        five_star_count = int((brand_reviews["rating"] == 5).sum())
        one_star_count = int((brand_reviews["rating"] == 1).sum())
        pct_five_star = five_star_count / review_count * 100 if review_count else 0.0
        pct_one_star = one_star_count / review_count * 100 if review_count else 0.0
        review_sentiment_proxy = pct_five_star - pct_one_star
        platform_divergence_pp = net_sentiment_pct - review_sentiment_proxy
        platform_divergence_flag = abs(platform_divergence_pp) > DIVERGENCE_THRESHOLD_PP

        position = "overindexed on social vs. shelf" if gap_pp >= 0 else "underindexed on social vs. shelf"
        sentence = (
            f"{brand} is {position} by {abs(gap_pp):.1f}pp "
            f"({pct_xhs:.1f}% of voice vs {pct_products:.1f}% of shelf)."
        )
        if small_base:
            sentence += f" Based on a smaller base ({product_count} HK products, under {SMALL_BASE_THRESHOLD}) — this ratio is more volatile."

        sentiment_label = "net positive" if net_sentiment_pct > 0 else ("net negative" if net_sentiment_pct < 0 else "net neutral")
        sentiment_sentence = (
            f"{brand}'s XHS posts run {sentiment_label} ({net_sentiment_pct:+.1f}%: "
            f"{pct_positive:.0f}% positive, {pct_negative:.0f}% negative, {pct_neutral:.0f}% neutral)."
        )
        if xhs_small_base:
            sentence_suffix = f" Based on a smaller base ({xhs_count} XHS posts, under {XHS_SMALL_BASE_THRESHOLD}) — lower-confidence."
            sentiment_sentence += sentence_suffix
        if gap_pp >= 0 and net_sentiment_pct > 0:
            sentiment_sentence += " High social voice here is backed by genuinely positive sentiment, not just volume."
        elif gap_pp >= 0 and net_sentiment_pct <= 0:
            sentiment_sentence += " High social voice is driven by volume, not sentiment quality — worth flagging."

        divergence_sentence = (
            f"{brand}: XHS net sentiment {net_sentiment_pct:+.1f}% vs. review net sentiment "
            f"(%5★ − %1★) {review_sentiment_proxy:+.1f}% — {abs(platform_divergence_pp):.1f}pp apart."
        )
        if platform_divergence_flag:
            divergence_sentence += (
                " Platform divergence — worth noting these are different moments in the customer "
                "journey (XHS often reflects aspirational/pre-purchase sentiment, reviews reflect "
                "post-purchase experience), not necessarily a contradiction."
            )

        rows.append({
            "brand": brand,
            "product_count": product_count,
            "review_count": review_count,
            "xhs_post_count": xhs_count,
            "pct_products": round(pct_products, 1),
            "pct_reviews": round(pct_reviews, 1),
            "pct_xhs_posts": round(pct_xhs, 1),
            "gap_pp": round(gap_pp, 1),
            "position": position,
            "small_base_flag": small_base,
            "sentence": sentence,
            "positive_count": positive_count,
            "negative_count": negative_count,
            "neutral_count": neutral_count,
            "unclassified_count": unclassified_count,
            "pct_positive": round(pct_positive, 1),
            "pct_negative": round(pct_negative, 1),
            "pct_neutral": round(pct_neutral, 1),
            "net_sentiment_pct": round(net_sentiment_pct, 1),
            "sentiment_sentence": sentiment_sentence,
            "xhs_small_base_flag": xhs_small_base,
            "pct_five_star": round(pct_five_star, 1),
            "pct_one_star": round(pct_one_star, 1),
            "review_sentiment_proxy": round(review_sentiment_proxy, 1),
            "platform_divergence_pp": round(platform_divergence_pp, 1),
            "platform_divergence_flag": platform_divergence_flag,
            "divergence_sentence": divergence_sentence,
        })

    df = pd.DataFrame(rows).sort_values("gap_pp", ascending=False).reset_index(drop=True)
    meta = {
        "total_products": total_products,
        "total_reviews": total_reviews,
        "total_xhs_attributed": total_xhs_attributed,
        "total_xhs_excluded": total_xhs_excluded,
    }
    return df, meta


def compute_theme_sentiment(db_path: Path) -> pd.DataFrame:
    """Per brand, per XHS theme tag (comfort, price, packaging, etc. — whatever
    the scraper already tagged): count of positive/neutral/negative posts. A
    post can carry multiple theme tags, so it contributes to each of its themes
    — this shows WHERE a brand's net sentiment score is actually coming from,
    not just the aggregate number. Themes rarer than MIN_THEME_COUNT overall
    are dropped to keep the breakdown readable."""
    conn = sqlite3.connect(db_path)
    products = pd.read_sql_query("SELECT DISTINCT brand FROM products WHERE market = 'HK'", conn)
    try:
        xhs = pd.read_sql_query("SELECT brand_mentioned, sentiment, themes FROM xhs_posts", conn)
    except pd.errors.DatabaseError:
        xhs = pd.DataFrame(columns=["brand_mentioned", "sentiment", "themes"])
    conn.close()

    canonical_brands = sorted(products["brand"].dropna().unique().tolist())
    brand_lookup = {b.lower(): b for b in canonical_brands}
    xhs["brand_norm"] = xhs["brand_mentioned"].apply(
        lambda x: brand_lookup.get(str(x).strip().lower()) if pd.notna(x) else None
    )
    xhs = xhs[xhs["brand_norm"].notna()].copy()

    def parse_themes(val):
        try:
            return json.loads(val) if val else []
        except Exception:
            return []

    xhs["themes_list"] = xhs["themes"].apply(parse_themes)

    overall_theme_counts = Counter(t for lst in xhs["themes_list"] for t in lst)
    keep_themes = {t for t, n in overall_theme_counts.items() if n >= MIN_THEME_COUNT}

    rows = []
    for r in xhs.itertuples():
        for theme in r.themes_list:
            if theme in keep_themes:
                rows.append({"brand": r.brand_norm, "theme": theme, "sentiment": r.sentiment})
    exploded = pd.DataFrame(rows)
    if exploded.empty:
        return pd.DataFrame(columns=["brand", "theme", "sentiment", "count", "pct_within_brand_theme"])

    grouped = exploded.groupby(["brand", "theme", "sentiment"]).size().rename("count").reset_index()
    theme_totals = grouped.groupby(["brand", "theme"])["count"].transform("sum")
    grouped["pct_within_brand_theme"] = (grouped["count"] / theme_totals * 100).round(1)
    return grouped.sort_values(["brand", "theme", "sentiment"]).reset_index(drop=True)


def write_share_of_voice(df: pd.DataFrame, meta: dict, theme_sentiment: pd.DataFrame, out_dir: Path) -> None:
    csv_path = out_dir / "share_of_voice.csv"
    md_path = out_dir / "share_of_voice.md"
    theme_csv_path = out_dir / "share_of_voice_theme_sentiment.csv"
    df.to_csv(csv_path, index=False, encoding="utf-8-sig")
    theme_sentiment.to_csv(theme_csv_path, index=False, encoding="utf-8-sig")

    lines = ["# Share of Voice — Shelf vs. Social, per HK Brand\n"]
    lines.append(
        f"Share of shelf is % of {meta['total_products']} HK products. Share of voice is % of "
        f"{meta['total_xhs_attributed']} brand-attributed XHS posts — {meta['total_xhs_excluded']} "
        "posts XHS could not attribute to a tracked brand (\"other\") are excluded from that "
        "denominator, not counted for any brand.\n"
    )

    lines.append("| Brand | Products | Reviews | XHS posts | % of shelf | % of reviews | % of voice | Gap (pp) |")
    lines.append("|---|---|---|---|---|---|---|---|")
    for r in df.itertuples():
        lines.append(
            f"| {r.brand} | {r.product_count} | {r.review_count} | {r.xhs_post_count} | "
            f"{r.pct_products}% | {r.pct_reviews}% | {r.pct_xhs_posts}% | {r.gap_pp:+.1f} |"
        )

    lines.append("\n## Reading the gap")
    for r in df.itertuples():
        lines.append(f"- {r.sentence}")

    lines.append(
        "\n_Positive gap = overindexed on social relative to shelf (above the y=x reference line "
        "on the quadrant chart); negative gap = underindexed (below the line)._"
    )

    lines.append("\n## Volume vs. sentiment — is high voice backed by positive sentiment?")
    lines.append(
        "Net sentiment is (% positive − % negative) as a share of THAT BRAND's own XHS posts "
        "— a volume-independent quality score, not a share of the grand total. This tests "
        "whether high-voice brands are winning on volume alone or on volume AND sentiment.\n"
    )
    lines.append("| Brand | XHS posts | % positive | % negative | % neutral | Net sentiment |")
    lines.append("|---|---|---|---|---|---|")
    for r in df.itertuples():
        lines.append(
            f"| {r.brand} | {r.xhs_post_count} | {r.pct_positive}% | {r.pct_negative}% | "
            f"{r.pct_neutral}% | {r.net_sentiment_pct:+.1f}% |"
        )

    lines.append("\n### Reading volume against sentiment")
    for r in df.itertuples():
        lines.append(f"- {r.sentiment_sentence}")

    small_base_xhs = df[df["xhs_small_base_flag"]]
    if not small_base_xhs.empty:
        listing = "; ".join(f"{r.brand} ({r.xhs_post_count} posts)" for r in small_base_xhs.itertuples())
        lines.append(
            f"\n_Lower-confidence (fewer than {XHS_SMALL_BASE_THRESHOLD} brand-attributed XHS posts): "
            f"{listing}. Rendered with reduced opacity and a distinct outline on the dashboard's "
            "volume-vs-sentiment chart._"
        )

    lines.append("\n## Platform divergence — XHS sentiment vs. review sentiment\n")
    lines.append(
        "XHS net sentiment (% positive − % negative, social posts) compared against a review-based "
        "sentiment proxy (% five-star − % one-star, same shape so the two numbers are directly "
        f"comparable). A gap over {DIVERGENCE_THRESHOLD_PP}pp is flagged as \"Platform divergence\" — "
        "this is not necessarily a contradiction: XHS often reflects aspirational/pre-purchase "
        "sentiment, while reviews reflect post-purchase experience — different moments in the "
        "customer journey.\n"
    )
    lines.append("| Brand | XHS net sentiment | Review net sentiment (%5★−%1★) | Gap (pp) | Flag |")
    lines.append("|---|---|---|---|---|")
    for r in df.itertuples():
        flag = "Platform divergence" if r.platform_divergence_flag else ""
        lines.append(
            f"| {r.brand} | {r.net_sentiment_pct:+.1f}% | {r.review_sentiment_proxy:+.1f}% | "
            f"{r.platform_divergence_pp:+.1f} | {flag} |"
        )
    lines.append("\n### Reading the divergence")
    for r in df.itertuples():
        lines.append(f"- {r.divergence_sentence}")

    if not theme_sentiment.empty:
        lines.append("\n## Theme-level sentiment breakdown — where each brand's score comes from\n")
        lines.append(
            f"For each brand, the sentiment mix (% positive/neutral/negative) within each XHS theme tag "
            f"(themes mentioned fewer than {MIN_THEME_COUNT} times overall are dropped for readability). "
            "A post can carry multiple theme tags, so it contributes to each one.\n"
        )
        lines.append("| Brand | Theme | Sentiment | Count | % within brand+theme |")
        lines.append("|---|---|---|---|---|")
        for r in theme_sentiment.itertuples():
            lines.append(f"| {r.brand} | {r.theme} | {r.sentiment} | {r.count} | {r.pct_within_brand_theme}% |")

    md_path.write_text("\n".join(lines), encoding="utf-8")
    print(f"  Share of Voice written -> {md_path.name}, {csv_path.name}")


def main():
    parser = argparse.ArgumentParser(description="Share of Voice — shelf vs. social, per HK brand")
    parser.add_argument("--db", default=str(DEFAULT_DB))
    parser.add_argument("--out", default=str(DEFAULT_OUT))
    args = parser.parse_args()

    db_path = Path(args.db)
    out_dir = Path(args.out)
    out_dir.mkdir(parents=True, exist_ok=True)

    if not db_path.exists():
        print(f"Database not found: {db_path}")
        return

    df, meta = compute_share_of_voice(db_path)
    theme_sentiment = compute_theme_sentiment(db_path)
    write_share_of_voice(df, meta, theme_sentiment, out_dir)


if __name__ == "__main__":
    main()
