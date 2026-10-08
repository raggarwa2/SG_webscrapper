"""
Do the pages agree? Run from Dashboard/:  python consistency_check.py

Every page must report the same number for the same thing. The story pages read voice_data directly; the per-channel pages and the
desk-research page read each scraper's own tables, which now take their sentiment label from voice_data.unify. This script rebuilds
the per-channel numbers the way those pages do and compares them with the brand pool, then reconciles the counts that appear on
more than one page. Exit code 1 if anything differs.
"""

import sqlite3
import sys
import warnings

import pandas as pd

warnings.filterwarnings("ignore")

import facebook_signals  # noqa: E402
import instagram_signals  # noqa: E402
import reddit_signals  # noqa: E402
import voice_data as vd  # noqa: E402
import youtube_signals  # noqa: E402
from sg_common import SG_DB, normalize_brand, read_table, xhs_attributed, XHS_DB  # noqa: E402

LABELS = ["positive", "neutral", "mixed", "negative"]
problems = []


def net(s: pd.Series) -> float:
    return round(100 * ((s == "positive").mean() - (s == "negative").mean()), 1)


def check(name: str, ok: bool, detail: str = "") -> None:
    print(("ok    " if ok else "DIFF  ") + name + (f"  {detail}" if detail else ""))
    if not ok:
        problems.append(name)


d = vd.load()
p = vd.pool(d)

# 1. per-channel pages vs the brand pool: same items, same label
for name, mod in (("YouTube", youtube_signals), ("Reddit", reddit_signals), ("Instagram", instagram_signals), ("Facebook", facebook_signals)):
    _, c, _ = mod.load_sg_dashboard_data()
    on = mod.on_topic_comments(c)
    on = on[on["brand"].isin(vd.charts.BRAND_ORDER) & on["sentiment"].isin(LABELS)]
    pool_src = p[p["source"] == name]
    check(f"{name}: items on the channel page = items in the pool", len(on) == len(pool_src), f"{len(on)} vs {len(pool_src)}")
    for b, g in on.groupby("brand"):
        q = pool_src[pool_src["brand_std"] == b]
        check(f"{name} / {b}: n and net sentiment", len(g) == len(q) and net(g["sentiment"]) == net(q["sentiment"]),
              f"page n={len(g)} net={net(g['sentiment'])}, pool n={len(q)} net={net(q['sentiment'])}")

# 2. Xiaohongshu posts: same label for every pooled item
xhs = vd.unify(read_table(XHS_DB, "SELECT * FROM xhs_posts"), "xhs_posts", "post_id")
xhs["brand_mentioned"] = xhs["brand_mentioned"].map(normalize_brand)   # as app.load_data does
att = xhs_attributed(xhs)
att = att[att["content_en"].notna() & (att["content_en"].astype(str).str.strip() != "")]   # a post with no text is not an item
x_pool = p[p["source"] == "Xiaohongshu"]
check("Xiaohongshu posts: brand n and net sentiment", len(att[att["sentiment"].isin(LABELS)]) == len(x_pool)
      and all(net(att[att["brand_mentioned"].map(normalize_brand) == b]["sentiment"]) == net(x_pool[x_pool["brand_std"] == b]["sentiment"])
              for b in x_pool["brand_std"].unique()))

# 3. counts that appear on more than one page
con = sqlite3.connect(SG_DB)
n_products = con.execute("SELECT COUNT(*) FROM products").fetchone()[0]
con.close()
try:
    cov = pd.read_csv(vd.Path(SG_DB).parent / "triangulation_sg" / "prompt_a_channel_coverage.csv", encoding="utf-8-sig")
    check("Desk research channel table: product listings = products table", int(cov["product_count"].sum()) == n_products,
          f"{int(cov['product_count'].sum())} vs {n_products}")
except OSError:
    print("skip  Prompt A file not found")
raw = vd.raw_counts()
passport_total = int(vd.raw_by_source()["collected"].sum())
check("Data & method: channel passport total = every item in voice_items", passport_total == sum(v["collected"] for v in raw.values()),
      f"{passport_total} vs {sum(v['collected'] for v in raw.values())}")
check("Strip and sidebar: pool size = items in the pool", raw["consumer_voice"]["pool"] == len(p), f"{raw['consumer_voice']['pool']} vs {len(p)}")

print("\nAll pages agree." if not problems else f"\n{len(problems)} difference(s): " + "; ".join(problems))
sys.exit(1 if problems else 0)
