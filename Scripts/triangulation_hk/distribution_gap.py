# ============================================================
# Distribution Gap — of the retailers the research team confirmed carry
# each brand, how many are we actually capturing in scraping?
# ============================================================
# Continuation of Prompt A's channel-coverage check (run_triangulation.py),
# but retailer-level rather than channel-category-level: cross-references
# Research/distribution.csv's researched retailer list against the
# distinct stores actually present in lensdata.db, quantifying the gap by
# name, not just a count.
#
# Only 3 researched retailers currently have any scraped match at all
# (HKTVmall, 393lens.com, CL-Mall.com) — every other researched retailer is
# a genuine, expected gap given the scraper's current site coverage, not a
# name-matching bug. This script surfaces that gap explicitly.
#
# Usage:
#   python triangulation/distribution_gap.py
#
# Scope: Hong Kong data only, same as the rest of triangulation/.
# ============================================================

import sqlite3
from pathlib import Path

import pandas as pd

ROOT = Path(__file__).resolve().parent.parent
DEFAULT_DB = ROOT / "output" / "lensdata.db"
DEFAULT_OUT = ROOT / "output" / "triangulation"
DEFAULT_RESEARCH = ROOT / "Research"

# Retailer name (as written in distribution.csv) -> matching products.site
# value. HKTVmall is a marketplace with dozens of individual seller
# store_names, so it's matched by site rather than store_name — same
# special-case run_triangulation.py's compute_channel_coverage() already
# uses. Every other researched retailer has no entry here on purpose: we
# don't scrape it (yet), so it has no scraped match by construction.
RETAILER_ALIAS_MAP = {
    "HKTVmall": "hktvmall",
    "393lens.com": "393lens",
    "CL-Mall.com": "cl_mall",
}

RESEARCHED_STATUSES = ["Present", "Exclusive"]


# ============================================================
# Loading (HK only)
# ============================================================

def load_distribution_hk(research_dir: Path) -> pd.DataFrame:
    df = pd.read_csv(research_dir / "distribution.csv")
    return df[(df["market"] == "HK") & (df["status"].isin(RESEARCHED_STATUSES))][
        ["brand", "retailer", "status"]
    ].copy()


def load_scraped_stores_hk(db_path: Path) -> pd.DataFrame:
    conn = sqlite3.connect(db_path)
    df = pd.read_sql_query(
        "SELECT DISTINCT brand, site, store_name FROM products WHERE market = 'HK'", conn
    )
    conn.close()
    return df


# ============================================================
# Coverage computation
# ============================================================

def match_retailer(retailer: str, scraped_stores: pd.DataFrame, brand: str) -> bool:
    site = RETAILER_ALIAS_MAP.get(retailer)
    if site is None:
        return False
    return not scraped_stores[(scraped_stores["brand"] == brand) & (scraped_stores["site"] == site)].empty


def compute_coverage(distribution: pd.DataFrame, scraped_stores: pd.DataFrame) -> pd.DataFrame:
    rows = []
    for brand, grp in distribution.groupby("brand"):
        researched = sorted(grp["retailer"].unique().tolist())
        scraped = [r for r in researched if match_retailer(r, scraped_stores, brand)]
        missing = [r for r in researched if r not in scraped]
        researched_count = len(researched)
        scraped_count = len(scraped)
        coverage_pct = round(scraped_count / researched_count * 100, 1) if researched_count else 0.0
        rows.append({
            "brand": brand,
            "researched_count": researched_count,
            "scraped_count": scraped_count,
            "coverage_pct": coverage_pct,
            "missing_retailers": "; ".join(missing),
        })
    return pd.DataFrame(rows).sort_values("coverage_pct", ascending=False).reset_index(drop=True)


# ============================================================
# Output
# ============================================================

def write_outputs(coverage: pd.DataFrame, out_dir: Path) -> None:
    out_dir.mkdir(parents=True, exist_ok=True)
    coverage.to_csv(out_dir / "distribution_gap.csv", index=False, encoding="utf-8-sig")

    total_researched = coverage["researched_count"].sum()
    total_scraped = coverage["scraped_count"].sum()
    overall_pct = round(total_scraped / total_researched * 100, 1) if total_researched else 0.0

    lines = ["# Distribution Gap — Researched vs. Scraped Retailer Coverage\n"]
    lines.append(
        "Continuation of the Channel Coverage check (Prompt A), one level more specific: for each "
        "brand, how many of the retailers `Research/distribution.csv` confirms carry it (status "
        "Present or Exclusive) do we actually have in the scraped catalogue? Matched via a small "
        "explicit alias map (HKTVmall, 393lens.com, CL-Mall.com — the only 3 researched retailers "
        "with any scraped presence today), not fuzzy name matching.\n"
    )
    lines.append(
        f"**Overall: {total_scraped} of {total_researched} researched retailer-brand pairs scraped "
        f"({overall_pct}%).**\n"
    )
    lines.append(
        "_Note: `Sorra` is a scraped site with zero rows in `distribution.csv` — newly added, not "
        "yet in the research team's scope. Not counted as a gap since it was never researched._\n"
    )

    lines.append("| Brand | Researched Retailers | Scraped Retailers | Coverage % | Missing Retailers |")
    lines.append("|---|---|---|---|---|")
    for r in coverage.itertuples():
        lines.append(
            f"| {r.brand} | {r.researched_count} | {r.scraped_count} | {r.coverage_pct}% | {r.missing_retailers} |"
        )

    lines.append("\n## Retailers with no scraped match at all, by name")
    all_missing = []
    for r in coverage.itertuples():
        if r.missing_retailers:
            all_missing.extend(r.missing_retailers.split("; "))
    missing_counts = pd.Series(all_missing).value_counts()
    if missing_counts.empty:
        lines.append("None — every researched retailer has a scraped match.")
    else:
        for retailer, n in missing_counts.items():
            lines.append(f"- **{retailer}** — missing for {n} brand{'s' if n != 1 else ''}")

    (out_dir / "distribution_gap.md").write_text("\n".join(lines), encoding="utf-8")
    print("  Distribution Gap written -> distribution_gap.md, distribution_gap.csv")


def main():
    import argparse
    parser = argparse.ArgumentParser(description="Distribution coverage gap quantification")
    parser.add_argument("--db", default=str(DEFAULT_DB))
    parser.add_argument("--out", default=str(DEFAULT_OUT))
    parser.add_argument("--research", default=str(DEFAULT_RESEARCH))
    args = parser.parse_args()

    db_path = Path(args.db)
    out_dir = Path(args.out)
    research_dir = Path(args.research)

    if not db_path.exists():
        print(f"Database not found: {db_path}")
        return

    distribution = load_distribution_hk(research_dir)
    scraped_stores = load_scraped_stores_hk(db_path)
    print(f"Loaded {len(distribution)} researched HK retailer-brand rows, "
          f"{scraped_stores['site'].nunique()} distinct scraped sites")

    coverage = compute_coverage(distribution, scraped_stores)
    write_outputs(coverage, out_dir)
    print(f"\nDone. Outputs in: {out_dir}")


if __name__ == "__main__":
    main()
