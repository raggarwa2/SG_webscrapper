# ============================================================
# Price Tier vs. Sentiment — do premium-priced SKUs get worse (or better)
# star ratings than budget SKUs?
# ============================================================
# Buckets every priced HK product into three tiers by within-market price
# percentile (Budget / Mid / Premium = bottom / middle / top third), then
# checks whether the 1-star rate and 5-star rate differ meaningfully across
# tiers — overall, and per brand. Per-brand cells with too few reviews to be
# meaningful are flagged as thin and excluded from that brand's test, not
# silently tested anyway.
#
# Usage:
#   python triangulation/price_sentiment.py
#
# Scope: Hong Kong data only, same as the rest of triangulation/ — pricing
# is HKD and tiers are relative to the HK product catalogue, not comparable
# across markets.
# ============================================================

import sqlite3
from itertools import product as _iproduct
from pathlib import Path

import pandas as pd
from scipy.stats import chi2_contingency

ROOT = Path(__file__).resolve().parent.parent
DEFAULT_DB = ROOT / "output" / "lensdata.db"
DEFAULT_OUT = ROOT / "output" / "triangulation"

MIN_CELL_REVIEWS = 15  # per tier, per brand — below this the cell is "thin" and excluded from that brand's test
SIGNIFICANCE_LEVEL = 0.05
TIER_ORDER = ["Budget", "Mid", "Premium"]


# ============================================================
# DB loading (HK only)
# ============================================================

def load_priced_products_hk(db_path: Path) -> pd.DataFrame:
    conn = sqlite3.connect(db_path)
    df = pd.read_sql_query(
        "SELECT product_code, brand, selling_price FROM products "
        "WHERE market = 'HK' AND selling_price IS NOT NULL",
        conn,
    )
    conn.close()
    return df


def load_reviews_hk(db_path: Path) -> pd.DataFrame:
    """Rating 1-5 only — same stray rating=0 exclusion as negative_tail_analysis.py."""
    conn = sqlite3.connect(db_path)
    df = pd.read_sql_query(
        "SELECT product_code, brand, rating FROM reviews "
        "WHERE market = 'HK' AND rating BETWEEN 1 AND 5",
        conn,
    )
    conn.close()
    return df


# ============================================================
# Tiering
# ============================================================

def assign_tiers(products: pd.DataFrame):
    """Percentile-split tiers on the HK priced-product distribution: Budget =
    bottom third, Mid = middle third, Premium = top third, using the 33rd and
    66th percentile price as breakpoints. Uses explicit <=/> comparisons
    (rather than pd.qcut) so ties sitting exactly on a breakpoint land
    predictably in the lower tier instead of raising on a duplicate bin edge —
    this HK price list has heavy clustering at round numbers (e.g. 28 SKUs at
    exactly $195)."""
    q33 = products["selling_price"].quantile(1 / 3)
    q66 = products["selling_price"].quantile(2 / 3)

    def _tier(price):
        if price <= q33:
            return "Budget"
        if price <= q66:
            return "Mid"
        return "Premium"

    out = products.copy()
    out["tier"] = out["selling_price"].apply(_tier)
    return out, q33, q66


def tier_price_ranges(products_tiered: pd.DataFrame) -> dict:
    ranges = {}
    for tier, grp in products_tiered.groupby("tier"):
        ranges[tier] = (grp["selling_price"].min(), grp["selling_price"].max())
    return ranges


# ============================================================
# Sentiment summary + significance testing
# ============================================================

def tier_summary(reviews_tiered: pd.DataFrame, products_tiered: pd.DataFrame,
                  q33: float, q66: float, price_ranges: dict) -> pd.DataFrame:
    """Overall (all-brand) tier-level summary: product count, review count,
    average rating, % one-star, % five-star, and the tier's price bounds
    (same bounds narrated in the .md breakpoints section) so consumers of
    the CSV — e.g. the dashboard — can label charts without recomputing
    percentiles themselves."""
    product_counts = products_tiered.groupby("tier")["product_code"].nunique()
    price_bounds = {
        "Budget": (price_ranges["Budget"][0], q33),
        "Mid": (q33, q66),
        "Premium": (q66, price_ranges["Premium"][1]),
    }
    rows = []
    for tier in TIER_ORDER:
        grp = reviews_tiered[reviews_tiered["tier"] == tier]
        n = len(grp)
        lo, hi = price_bounds[tier]
        rows.append({
            "tier": tier,
            "product_count": int(product_counts.get(tier, 0)),
            "review_count": n,
            "avg_rating": round(grp["rating"].mean(), 2) if n else float("nan"),
            "pct_one_star": round((grp["rating"] == 1).mean() * 100, 1) if n else 0.0,
            "pct_five_star": round((grp["rating"] == 5).mean() * 100, 1) if n else 0.0,
            "price_min": round(float(lo)),
            "price_max": round(float(hi)),
        })
    return pd.DataFrame(rows)


def brand_tier_summary(reviews_tiered: pd.DataFrame) -> pd.DataFrame:
    """Brand x tier grid (every brand x every tier, even where a cell is
    empty) with a thin_cell flag for cells below MIN_CELL_REVIEWS."""
    brands = sorted(reviews_tiered["brand"].dropna().unique().tolist())
    rows = []
    for brand, tier in _iproduct(brands, TIER_ORDER):
        grp = reviews_tiered[(reviews_tiered["brand"] == brand) & (reviews_tiered["tier"] == tier)]
        n = len(grp)
        rows.append({
            "brand": brand,
            "tier": tier,
            "review_count": n,
            "avg_rating": round(grp["rating"].mean(), 2) if n else float("nan"),
            "pct_one_star": round((grp["rating"] == 1).mean() * 100, 1) if n else 0.0,
            "pct_five_star": round((grp["rating"] == 5).mean() * 100, 1) if n else 0.0,
            "thin_cell": n < MIN_CELL_REVIEWS,
        })
    return pd.DataFrame(rows)


def chi_square_test(reviews_subset: pd.DataFrame, star_value: int):
    """3-tier x [is_star / not] contingency test on whatever subset is
    passed in (overall, or one brand). Returns None if any tier is missing
    or empty — a test against a missing cell isn't meaningful."""
    tab = pd.crosstab(reviews_subset["tier"], reviews_subset["rating"] == star_value)
    tab = tab.reindex(TIER_ORDER)
    if tab.isna().any().any() or (tab.sum(axis=1) == 0).any():
        return None
    chi2, pvalue, dof, _ = chi2_contingency(tab)
    return {"chi2": round(float(chi2), 3), "dof": int(dof), "p_value": round(float(pvalue), 4),
            "significant": bool(pvalue < SIGNIFICANCE_LEVEL)}


def run_all_tests(reviews_tiered: pd.DataFrame, brand_summary: pd.DataFrame) -> pd.DataFrame:
    rows = []
    for metric, star_value in (("one_star_rate", 1), ("five_star_rate", 5)):
        result = chi_square_test(reviews_tiered, star_value)
        rows.append({"scope": "Overall", "metric": metric, "tested": result is not None, "note": "", **(result or {})})

    for brand, brand_cells in brand_summary.groupby("brand"):
        thin_tiers = brand_cells[brand_cells["thin_cell"]]["tier"].tolist()
        present_tiers = brand_cells[brand_cells["review_count"] > 0]["tier"].tolist()
        missing_tiers = [t for t in TIER_ORDER if t not in present_tiers]
        skip_reason = ""
        if missing_tiers:
            skip_reason = f"missing tier(s): {', '.join(missing_tiers)}"
        elif thin_tiers:
            skip_reason = f"thin cell(s) under {MIN_CELL_REVIEWS} reviews: {', '.join(thin_tiers)}"

        brand_reviews = reviews_tiered[reviews_tiered["brand"] == brand]
        for metric, star_value in (("one_star_rate", 1), ("five_star_rate", 5)):
            if skip_reason:
                rows.append({"scope": brand, "metric": metric, "tested": False, "note": skip_reason})
            else:
                result = chi_square_test(brand_reviews, star_value)
                rows.append({"scope": brand, "metric": metric, "tested": result is not None,
                             "note": "" if result is not None else "test could not be computed", **(result or {})})
    return pd.DataFrame(rows)


# ============================================================
# Plain-language interpretation
# ============================================================

def _rate_direction(summary_df: pd.DataFrame, pct_col: str):
    s = summary_df.set_index("tier")[pct_col]
    s = s[s.index.isin(TIER_ORDER)]
    high_tier, low_tier = s.idxmax(), s.idxmin()
    return high_tier, s[high_tier], low_tier, s[low_tier]


def _interpret_clause(metric_key: str, high_tier: str) -> str:
    """Cautious, non-causal interpretive clause. Only ever attached when the
    chi-square test for the relevant scope came back significant."""
    if metric_key == "one_star_rate" and high_tier == "Premium":
        return "suggesting elevated expectations at higher price points may not always be met"
    if metric_key == "one_star_rate" and high_tier == "Budget":
        return "suggesting budget-tier products draw more dissatisfaction than pricier alternatives"
    if metric_key == "five_star_rate" and high_tier == "Premium":
        return "consistent with higher-priced products more often meeting expectations"
    if metric_key == "five_star_rate" and high_tier == "Budget":
        return "suggesting budget shoppers are, if anything, easier to satisfy"
    return "though the pattern doesn't map to a simple price-quality story (Mid-tier is the outlier)"


def build_summary_sentence(scope_label: str, metric_label: str, metric_key: str,
                            summary_df: pd.DataFrame, test_row: dict) -> str:
    if not test_row.get("tested"):
        note = test_row.get("note", "insufficient data")
        return f"**{scope_label} — {metric_label}:** not tested ({note})."
    if not test_row["significant"]:
        return (f"**{scope_label} — {metric_label}:** no statistically meaningful difference across price "
                f"tiers (chi-square p={test_row['p_value']}). No clear pattern found.")
    high_tier, high_pct, low_tier, low_pct = _rate_direction(summary_df, f"pct_{'one_star' if metric_key == 'one_star_rate' else 'five_star'}")
    clause = _interpret_clause(metric_key, high_tier)
    return (f"**{scope_label} — {metric_label}:** {high_tier}-tier products show a higher {metric_label} "
            f"({high_pct}%) than {low_tier}-tier ({low_pct}%), {clause} (chi-square p={test_row['p_value']}).")


# ============================================================
# Output
# ============================================================

def write_outputs(overall_summary, brand_summary, tests_df, q33, q66, price_ranges,
                   overall_review_count, excluded_review_count, out_dir: Path) -> None:
    out_dir.mkdir(parents=True, exist_ok=True)

    overall_summary.to_csv(out_dir / "price_sentiment_tiers.csv", index=False, encoding="utf-8-sig")
    brand_summary.to_csv(out_dir / "price_sentiment_brand.csv", index=False, encoding="utf-8-sig")
    tests_df.to_csv(out_dir / "price_sentiment_tests.csv", index=False, encoding="utf-8-sig")

    lines = ["# Price Tier vs. Sentiment\n"]
    lines.append(
        f"Based on {overall_review_count} HK reviews matched to a priced product "
        f"({excluded_review_count} HK reviews excluded — no price on file for that product). "
        "Tiers are relative to the HK catalogue only; not comparable to Thailand pricing.\n"
    )

    # "\$" (escaped) rather than "$" — Streamlit's st.markdown renders unescaped
    # $...$ pairs as LaTeX math, which would mangle "HK$30 - HK$168" into a
    # formula instead of showing it as currency.
    lines.append("## Tier breakpoints (33rd / 66th percentile of HK product price)\n")
    lines.append(f"- **Budget:** HK\\${price_ranges['Budget'][0]:.0f} – HK\\${q33:.0f} (bottom third)")
    lines.append(f"- **Mid:** HK\\${q33:.0f} – HK\\${q66:.0f} (middle third)")
    lines.append(f"- **Premium:** HK\\${q66:.0f} – HK\\${price_ranges['Premium'][1]:.0f} (top third)\n")

    lines.append("## Tier-level summary\n")
    lines.append("| Tier | Products | Reviews | Avg. rating | % 1-star | % 5-star |")
    lines.append("|---|---|---|---|---|---|")
    for r in overall_summary.itertuples():
        lines.append(f"| {r.tier} | {r.product_count} | {r.review_count} | {r.avg_rating} | {r.pct_one_star}% | {r.pct_five_star}% |")

    lines.append("\n## Statistical test — overall (all brands combined)\n")
    overall_tests = tests_df[tests_df["scope"] == "Overall"]
    for r in overall_tests.itertuples():
        row = r._asdict() if hasattr(r, "_asdict") else dict(zip(overall_tests.columns, r[1:]))
        metric_label = "one-star rate" if r.metric == "one_star_rate" else "five-star rate"
        lines.append(build_summary_sentence("Overall", metric_label, r.metric, overall_summary, row))
    lines.append("")

    lines.append("## Per-brand breakdown\n")
    lines.append("| Brand | Tier | Reviews | Avg. rating | % 1-star | % 5-star | Thin cell? |")
    lines.append("|---|---|---|---|---|---|---|")
    for r in brand_summary.itertuples():
        thin = "yes (<15 reviews)" if r.thin_cell else ""
        lines.append(f"| {r.brand} | {r.tier} | {r.review_count} | {r.avg_rating} | {r.pct_one_star}% | {r.pct_five_star}% | {thin} |")

    lines.append("\n## Statistical test — per brand\n")
    lines.append(
        f"Only run for brands where every tier has at least {MIN_CELL_REVIEWS} reviews; "
        "otherwise flagged as thin and skipped rather than tested on a misleadingly small base.\n"
    )
    for brand, brand_df in brand_summary.groupby("brand"):
        brand_tests = tests_df[tests_df["scope"] == brand]
        for r in brand_tests.itertuples():
            row = dict(zip(brand_tests.columns, r[1:]))
            metric_label = "one-star rate" if r.metric == "one_star_rate" else "five-star rate"
            lines.append(build_summary_sentence(brand, metric_label, r.metric, brand_df, row))
        lines.append("")

    (out_dir / "price_sentiment.md").write_text("\n".join(lines), encoding="utf-8")
    print(f"  Price vs. Sentiment written -> price_sentiment.md, "
          f"price_sentiment_tiers.csv, price_sentiment_brand.csv, price_sentiment_tests.csv")


def main():
    import argparse
    parser = argparse.ArgumentParser(description="Price Tier vs. Sentiment analysis")
    parser.add_argument("--db", default=str(DEFAULT_DB))
    parser.add_argument("--out", default=str(DEFAULT_OUT))
    args = parser.parse_args()

    db_path = Path(args.db)
    out_dir = Path(args.out)

    if not db_path.exists():
        print(f"Database not found: {db_path}")
        return

    products = load_priced_products_hk(db_path)
    reviews = load_reviews_hk(db_path)
    print(f"Loaded {len(products)} priced HK products, {len(reviews)} rated HK reviews")

    products_tiered, q33, q66 = assign_tiers(products)
    price_ranges = tier_price_ranges(products_tiered)
    print(f"Breakpoints: Budget <= HK${q33:.0f}  |  Mid HK${q33:.0f}-{q66:.0f}  |  Premium > HK${q66:.0f}")

    reviews_tiered = reviews.merge(
        products_tiered[["product_code", "tier"]], on="product_code", how="inner"
    )
    excluded = len(reviews) - len(reviews_tiered)
    print(f"{len(reviews_tiered)} reviews matched to a priced/tiered product ({excluded} excluded — no price on file)")

    overall_summary = tier_summary(reviews_tiered, products_tiered, q33, q66, price_ranges)
    brand_summary = brand_tier_summary(reviews_tiered)
    tests_df = run_all_tests(reviews_tiered, brand_summary)

    write_outputs(
        overall_summary, brand_summary, tests_df, q33, q66, price_ranges,
        len(reviews_tiered), excluded, out_dir,
    )
    print(f"\nDone. Outputs in: {out_dir}")


if __name__ == "__main__":
    main()
