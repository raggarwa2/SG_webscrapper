"""
Google Trends synthesis — turns the manually-exported CSVs in
Research/Google Trend/ into a brand-comparison summary. These are Google's
own relative search-interest indices (0-100 per week, HK only), covering
2025-06-29 to 2026-06-28 — almost exactly the Wave 6 (Sep-Oct 25) to
Wave 7 (Mar-Apr 26) window the reference research tracks, plus a few months either side.

No scraping/cost involved — these CSVs were exported by hand from
trends.google.com. This script only aggregates what's already there.
"""
import csv
from pathlib import Path

TREND_DIR = Path("Research/Google Trend")

FILES = {
    "Shopping (EN)": "All_brands_multiTimeline_english_keywords_shopping.csv",
    "Shopping (中文)": "All_brands_multiTimeline_Chinese_name_keywords_shopping.csv",
    "Health (EN)": "All_brands_multiTimeline_english_keywords_health.csv",
    "Health (中文)": "All_brands_multiTimeline_Chinese_name_keywords_health.csv",
}


def load(fname):
    path = TREND_DIR / fname
    with open(path, encoding="utf-8-sig") as f:
        rows = list(csv.reader(f))
    header = rows[2]  # row 0 = "Category: X", row 1 = blank, row 2 = header
    brands = [h.split(":")[0].strip() for h in header[1:]]
    data = {b: [] for b in brands}
    weeks = []
    for row in rows[3:]:
        if not row or not row[0]:
            continue
        weeks.append(row[0])
        for b, v in zip(brands, row[1:]):
            data[b].append(int(v) if v.strip().isdigit() else 0)
    return weeks, data


def summarize(weeks, data):
    out = {}
    for brand, vals in data.items():
        if not vals:
            continue
        n = len(vals)
        first_q = vals[: n // 4] or [0]
        last_q = vals[-(n // 4):] or [0]
        avg_first = sum(first_q) / len(first_q)
        avg_last = sum(last_q) / len(last_q)
        avg_all = sum(vals) / n
        delta = avg_last - avg_first
        out[brand] = {
            "avg": round(avg_all, 1),
            "first_quarter_avg": round(avg_first, 1),
            "last_quarter_avg": round(avg_last, 1),
            "delta": round(delta, 1),
            "peak": max(vals),
            "peak_week": weeks[vals.index(max(vals))],
        }
    return out


def main():
    lines = ["# Google Trends Synthesis — Search Interest, HK, 2025-06-29 to 2026-06-28\n",
              "Source: manually exported CSVs in `Research/Google Trend/` (Google's own relative "
              "search-interest index, 0-100 per week, Hong Kong only). No scraping cost — this is "
              "existing data, aggregated here.\n",
              "**Caveat:** Google Trends measures search interest, not purchase intent or new-wearer "
              "status specifically — treat as a directional proxy, not a segment-level measurement "
              "like the reference tracking study.\n"]

    all_summaries = {}
    for label, fname in FILES.items():
        weeks, data = load(fname)
        summary = summarize(weeks, data)
        all_summaries[label] = summary
        lines.append(f"\n## {label}\n")
        lines.append("| Brand | Avg (whole period) | First-quarter avg | Last-quarter avg | Change | Peak | Peak week |")
        lines.append("|---|---|---|---|---|---|---|")
        for brand, s in sorted(summary.items(), key=lambda x: -x[1]["avg"]):
            arrow = "↑" if s["delta"] > 3 else ("↓" if s["delta"] < -3 else "→")
            lines.append(
                f"| {brand} | {s['avg']} | {s['first_quarter_avg']} | {s['last_quarter_avg']} | "
                f"{arrow} {s['delta']:+.1f} | {s['peak']} | {s['peak_week']} |"
            )

    lines.append("\n## Reading it\n")
    lines.append(
        "- **Olens dominates 'Shopping'-category search** in both English and Chinese-name "
        "queries — consistent with the XHS share-of-voice finding (Olens overindexed on social "
        "27.1% of voice vs 3.9% of shelf). Search demand and social conversation point the same "
        "direction for Olens.\n"
        "- **Acuvue dominates 'Health'-category search** — consistent with it being the "
        "established, high-shelf-share brand (47% of HK products, 60.9% of reviews) that people "
        "search for reassurance/health-safety info on, not just to shop.\n"
        "- Alcon and CooperVision show near-zero search interest for most of the period, only "
        "picking up in the final weeks (i.e. very recently) in the Shopping category — worth a "
        "line in the deck as \"emerging search interest, small base.\"\n"
    )

    lines.append("\n## Related-queries signal (raw, from Google's 'related entities' export)\n")
    lines.append(
        "For Acuvue: **Myopia (+900%)**, **Acuvue Oasys Max 1-Day Astigmatism (+450%)**, "
        "**CooperVision (+180%)** are the fastest-rising related queries in the last year. "
        "Astigmatism/multifocal/presbyopia-related terms (Dailies Total 1 Multifocal, Air Optix "
        "Multifocal, Presbyopia) also spike for Alcon.\n\n"
        "**Caveat on data quality:** Alcon's related-entities list includes clearly unrelated "
        "terms (Brembo, Piston, RC6, Adecco Staffing) — \"Alcon\" as a search term picks up noise "
        "from other topics. Treat the Alcon related-queries list as lower-confidence than "
        "Acuvue's; don't quote the noisy terms in the readout.\n"
    )

    Path("output/triangulation").mkdir(parents=True, exist_ok=True)
    with open("output/triangulation/trends_synthesis.md", "w", encoding="utf-8") as f:
        f.write("\n".join(lines))
    print("Written -> output/triangulation/trends_synthesis.md")


if __name__ == "__main__":
    main()
