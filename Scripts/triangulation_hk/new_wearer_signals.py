"""
New-wearer signal extraction — keyword pass across reviews, XHS posts/comments,
LIHKG posts, and Facebook reviews. Built for the 2026-07-02 client meeting: the
client's Wave 6/7 research explicitly tracks "New Wearers" as a distinct segment
(see insight.txt market-of-purchase slides), so this checks whether our own
external data can say anything about that segment organically.

Facebook reviews live in a separate db (output/facebook_data.db, see
facebook_reviews_merge.py's module docstring) — opened as a second connection
here rather than ATTACHed, same treatment reputation_crosscheck.py/
monthly_trends.py give the YouTube db. Skipped entirely (not an error) if that
db doesn't exist yet.

No LLM cost — plain keyword matching (EN + Traditional/Simplified Chinese).
Run: python triangulation/new_wearer_signals.py
"""
import os
import re
import sqlite3
from collections import defaultdict

DB = "output/lensdata.db"
FACEBOOK_DB = "output/facebook_data.db"

KEYWORDS = [
    # English
    "first time", "first pair", "first contact lens", "new to contact lens",
    "just started wearing", "beginner", "never worn", "never wore",
    "switching from glasses", "switched from glasses", "first-time user",
    "new wearer", "new to lenses", "trying contact lens for the first",
    # Chinese (Traditional + Simplified)
    "新手", "初次戴", "第一次戴", "剛開始戴", "新手上路", "初戴", "新手推薦",
    "第一次配", "新手必看", "入門", "第一次買隱形眼鏡", "第一次用隱形眼鏡",
    "首次配戴", "首次購買", "由眼鏡轉戴", "戴眼鏡轉隱形",
]

PATTERN = re.compile("|".join(re.escape(k) for k in KEYWORDS), re.IGNORECASE)


def scan(rows):
    """rows: list of (brand, text, url_or_id) -> matches"""
    hits = []
    for brand, text, ref in rows:
        if not text:
            continue
        m = PATTERN.search(text)
        if m:
            hits.append((brand, m.group(0), text.strip()[:220], ref))
    return hits


def main():
    conn = sqlite3.connect(DB)
    conn.row_factory = sqlite3.Row
    cur = conn.cursor()

    all_hits = defaultdict(list)  # source -> list of hits

    # Reviews (HK only — this is the HK-framework triangulation)
    cur.execute("""
        SELECT brand, COALESCE(review_text_en, '') || ' ' || COALESCE(review_text_zh, ''), product_code
        FROM reviews WHERE market='HK'
    """)
    rows = [(r[0], r[1], r[2]) for r in cur.fetchall()]
    all_hits["reviews"] = scan(rows)

    # XHS posts
    cur.execute("""
        SELECT COALESCE(brand_mentioned, brand_keyword),
               COALESCE(title,'') || ' ' || COALESCE(content_en,'') || ' ' || COALESCE(content_zh,''),
               url
        FROM xhs_posts
    """)
    rows = [(r[0], r[1], r[2]) for r in cur.fetchall()]
    all_hits["xhs_posts"] = scan(rows)

    # XHS comments (join to post for brand)
    cur.execute("""
        SELECT COALESCE(p.brand_mentioned, p.brand_keyword),
               COALESCE(c.content_en,'') || ' ' || COALESCE(c.content_zh,''),
               c.post_id
        FROM xhs_comments c LEFT JOIN xhs_posts p ON c.post_id = p.post_id
    """)
    rows = [(r[0], r[1], r[2]) for r in cur.fetchall()]
    all_hits["xhs_comments"] = scan(rows)

    # LIHKG posts
    cur.execute("""
        SELECT NULLIF(mentioned_brands,''), COALESCE(text_english,'') || ' ' || COALESCE(text_original,''), thread_url
        FROM lihkg_posts
    """)
    rows = [(r[0], r[1], r[2]) for r in cur.fetchall()]
    all_hits["lihkg_posts"] = scan(rows)

    # Facebook reviews (separate db)
    if os.path.exists(FACEBOOK_DB):
        fb_conn = sqlite3.connect(FACEBOOK_DB)
        fb_cur = fb_conn.cursor()
        fb_cur.execute("""
            SELECT NULLIF(mentioned_brands,''), COALESCE(text_english,'') || ' ' || COALESCE(text_original,''), review_url
            FROM fb_reviews
        """)
        rows = [(r[0], r[1], r[2]) for r in fb_cur.fetchall()]
        all_hits["facebook_reviews"] = scan(rows)
        fb_conn.close()

    total = sum(len(v) for v in all_hits.values())
    print(f"Total new-wearer keyword hits: {total}")
    for src, hits in all_hits.items():
        print(f"  {src}: {len(hits)}")

    # Brand breakdown
    BRAND_CANON = {"olens": "Olens", "acuvue": "Acuvue", "alcon": "Alcon",
                   "bausch & lomb": "Bausch & Lomb", "coopervision": "CooperVision"}
    brand_counts = defaultdict(int)
    for hits in all_hits.values():
        for brand, kw, text, ref in hits:
            key = BRAND_CANON.get((brand or "").strip().lower(), brand or "(unattributed)")
            brand_counts[key] += 1

    lines = ["# New-Wearer Signal Scan — Keyword Pass\n",
             "Plain keyword matching (no LLM) across HK reviews, XHS posts/comments, LIHKG posts, "
             "and Facebook reviews.\n",
             f"**Total hits: {total}**\n",
             "## By source\n",
             "| Source | Hits |", "|---|---|"]
    for src, hits in all_hits.items():
        lines.append(f"| {src} | {len(hits)} |")

    lines += ["\n## By brand\n", "| Brand | Hits |", "|---|---|"]
    for brand, n in sorted(brand_counts.items(), key=lambda x: -x[1]):
        lines.append(f"| {brand} | {n} |")

    lines += ["\n## Example quotes (paraphrase-ready, first 40 per source)\n"]
    for src, hits in all_hits.items():
        lines.append(f"\n### {src}\n")
        for brand, kw, text, ref in hits[:40]:
            lines.append(f"- **[{brand or 'unattributed'}]** (matched \"{kw}\") — {text}  \n  _ref: {ref}_")

    with open("output/triangulation/new_wearer_signals.md", "w", encoding="utf-8") as f:
        f.write("\n".join(lines))

    print("\nWritten -> output/triangulation/new_wearer_signals.md")
    conn.close()


if __name__ == "__main__":
    main()
