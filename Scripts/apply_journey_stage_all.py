"""Adds a journey_stage column (see journey_stage_map.py) to every SG content
table that doesn't already have one. Safe to rerun — skips any (db, table)
pair whose journey_stage column already exists rather than re-adding it.

Run with:
    python Scripts/apply_journey_stage_all.py
"""

import os
import sqlite3

from journey_stage_map import journey_stage_for

BASE_DIR = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
OUTPUT_DIR = os.path.join(BASE_DIR, "Scripts", "output")

# (db filename, table, source key into JOURNEY_STAGE_BY_SOURCE)
TARGETS = [
    ("sg_acuvue.db", "products", "lazada"),          # overwritten per-row below (mixed sources)
    ("sg_acuvue.db", "reviews", "lazada"),
    ("sg_acuvue.db", "forum_posts", "kiasuparents_forum"),
    ("xhs_data_sg.db", "xhs_posts", "xhs"),
    ("youtube_data_sg.db", "yt_videos", "youtube"),
    ("reddit_data_sg.db", "reddit_posts", "reddit"),
    ("facebook_data_sg.db", "fb_posts", "facebook"),
    ("instagram_data_sg.db", "ig_posts", "instagram"),
]

# products mixes two sites (lazada_sg, tiktok_shop) in one table, so it needs
# a per-row UPDATE keyed on the `site` column rather than one constant value.
PRODUCTS_SITE_TO_SOURCE = {"lazada_sg": "lazada", "tiktok_shop": "tiktok_shop"}


def has_column(cur, table, column):
    cur.execute(f"PRAGMA table_info({table})")
    return column in [row[1] for row in cur.fetchall()]


def apply_constant(cur, table, source_key):
    if has_column(cur, table, "journey_stage"):
        print(f"  {table}: journey_stage already present, skipping")
        return
    cur.execute(f"ALTER TABLE {table} ADD COLUMN journey_stage TEXT")
    cur.execute(f"UPDATE {table} SET journey_stage = ?", (journey_stage_for(source_key),))
    print(f"  {table}: set journey_stage = '{journey_stage_for(source_key)}' on all rows")


def apply_products(cur):
    if has_column(cur, "products", "journey_stage"):
        print("  products: journey_stage already present, skipping")
        return
    cur.execute("ALTER TABLE products ADD COLUMN journey_stage TEXT")
    for site, source_key in PRODUCTS_SITE_TO_SOURCE.items():
        cur.execute(
            "UPDATE products SET journey_stage = ? WHERE site = ?",
            (journey_stage_for(source_key), site),
        )
    print("  products: set journey_stage per-row by site")


def main():
    for db_name, table, source_key in TARGETS:
        db_path = os.path.join(OUTPUT_DIR, db_name)
        if not os.path.exists(db_path):
            print(f"[skip] {db_name} not found")
            continue
        conn = sqlite3.connect(db_path)
        cur = conn.cursor()
        print(f"{db_name}:")
        if table == "products":
            apply_products(cur)
        else:
            apply_constant(cur, table, source_key)
        conn.commit()
        conn.close()


if __name__ == "__main__":
    main()
