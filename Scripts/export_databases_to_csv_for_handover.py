"""Exports every SG database table and every raw scraped file to CSV, for
handing the project data to another team.

What comes out (default folder Handover/csv_export_<date>/ in the project root):

    01_raw_scraped/            one folder per source, one CSV per table
        <source_db>/<table>.csv        every scraper database (Instagram, Reddit,
                                       Facebook, YouTube, XHS, Google Maps,
                                       Google Trends, app stores, Lazada/TikTok
                                       Shop/forum, Meta Ads)
        tiktok_shop_raw/<file>.csv     raw TikTok Shop JSON / JSONL pulls, flattened
        trade_data/*.csv               UN Comtrade lens import/export figures
    02_tagged_and_consolidated/        built on top of the raw data
        voice_items_sg/voice_items.csv one row per comment/post/review, all channels
        voice_tags_sg/voice_tags.csv   model sentiment, themes, stage (all tag versions)
        theme_tags_sg/theme_tags.csv   barrier labels used by the barriers page
        journey_stage_sg/journey_stage.csv
    MANIFEST.csv               every file: source, table, rows in DB, rows in CSV, check
    DATA_DICTIONARY.csv        every column of every table, with its SQLite type
    README.txt                 how to read the folder

Not exported (listed in the manifest as "skipped"): backups, "before_*" and
"backup_*" snapshots, and test databases. Add them with --include-snapshots.

Each CSV is UTF-8 with a byte-order mark so Excel opens Chinese and accented text
correctly. Text with line breaks is quoted, so read it with a CSV reader, not by
splitting lines. Databases are opened read-only; nothing in the project changes.
After writing, each CSV is read back and its row count is compared with the
database; the script exits 1 if any file disagrees.

Run with:
    python Scripts/export_databases_to_csv_for_handover.py
    python Scripts/export_databases_to_csv_for_handover.py --out D:/somewhere
    python Scripts/export_databases_to_csv_for_handover.py --include-snapshots
"""

import argparse
import csv
import datetime
import glob
import json
import os
import shutil
import sqlite3
import sys

BASE_DIR = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
OUTPUT_DIR = os.path.join(BASE_DIR, "Scripts", "output")
DATA_DIR = os.path.join(BASE_DIR, "Scripts", "data")

RAW = "01_raw_scraped"
TAGGED = "02_tagged_and_consolidated"

# Every database the project uses, what it holds, and where it goes.
# A .db in output/ that is neither here nor a snapshot/test file is reported
# as "unregistered" so a new scraper's database cannot be left out silently.
DATABASES = {
    "instagram_data_sg.db": (RAW, "Instagram posts and comments (Apify)"),
    "facebook_data_sg.db": (RAW, "Facebook brand-page posts and comments"),
    "facebook_retailers_sg.db": (RAW, "Facebook retailer pages: posts and reviews"),
    "facebook_ads_sg.db": (RAW, "Meta Ad Library ads"),
    "reddit_data_sg.db": (RAW, "Reddit posts and comments"),
    "youtube_data_sg.db": (RAW, "YouTube videos and comments"),
    "xhs_data_sg.db": (RAW, "Xiaohongshu (RedNote) posts and comments"),
    "gmaps_data_sg.db": (RAW, "Google Maps places and reviews (optical retailers)"),
    "trends_data_sg.db": (RAW, "Google Trends interest over time"),
    "app_data_sg.db": (RAW, "MyACUVUE app: store reviews, metadata, privacy labels"),
    "sg_acuvue.db": (RAW, "Lazada / TikTok Shop products, reviews, and forum posts"),
    "scraped_sources.db": (RAW, "Log of which brand/keyword pulls were run"),
    "voice_items_sg.db": (TAGGED, "Unified item table across all channels"),
    "voice_tags_sg.db": (TAGGED, "Model-assigned sentiment, themes, stage per item"),
    "theme_tags_sg.db": (TAGGED, "Model-assigned barrier labels"),
    "journey_stage_sg.db": (TAGGED, "Journey stage per item"),
}

# Name patterns for files that are copies or experiments, not the live data.
SNAPSHOT_MARKERS = (".backup_", ".before_", "_BACKUP_", "_pre_", "_restored_")
TEST_MARKERS = ("test_", "_test")


def is_snapshot(name):
    stem = os.path.splitext(name)[0]
    return any(m in name for m in SNAPSHOT_MARKERS) or any(
        stem.startswith(m) or stem.endswith(m) for m in TEST_MARKERS
    )


def cell(value):
    return "" if value is None else value


def write_rows(path, header, rows):
    """Writes header + rows to path; returns the number of data rows."""
    os.makedirs(os.path.dirname(path), exist_ok=True)
    n = 0
    with open(path, "w", newline="", encoding="utf-8-sig") as fh:
        w = csv.writer(fh)
        w.writerow(header)
        for row in rows:
            w.writerow([cell(v) for v in row])
            n += 1
    return n


def count_csv_rows(path):
    csv.field_size_limit(min(sys.maxsize, 2**31 - 1))
    with open(path, newline="", encoding="utf-8-sig") as fh:
        return max(sum(1 for _ in csv.reader(fh)) - 1, 0)


def flatten(obj, prefix=""):
    """Nested dicts become dotted columns; lists are kept as JSON text."""
    out = {}
    if isinstance(obj, dict):
        for k, v in obj.items():
            key = f"{prefix}.{k}" if prefix else str(k)
            if isinstance(v, dict):
                out.update(flatten(v, key))
            elif isinstance(v, list):
                out[key] = json.dumps(v, ensure_ascii=False)
            else:
                out[key] = v
    else:
        out[prefix or "value"] = obj
    return out


class Exporter:
    def __init__(self, out_dir):
        self.out_dir = out_dir
        self.manifest = []
        self.dictionary = []

    def record(self, group, source, table, path, rows_src, rows_csv, note=""):
        rel = os.path.relpath(path, self.out_dir).replace("\\", "/") if path else ""
        status = "skipped" if not path else ("ok" if rows_src == rows_csv else "MISMATCH")
        self.manifest.append(
            [group, source, table, rel, rows_src, rows_csv, status, note]
        )
        return status

    def export_db(self, group, db_name, description):
        db_path = os.path.join(OUTPUT_DIR, db_name)
        stem = os.path.splitext(db_name)[0]
        con = sqlite3.connect(f"file:{db_path}?mode=ro", uri=True)
        try:
            tables = [
                r[0]
                for r in con.execute(
                    "SELECT name FROM sqlite_master WHERE type='table' "
                    "AND name NOT LIKE 'sqlite_%' ORDER BY name"
                )
            ]
            for t in tables:
                info = con.execute(f'PRAGMA table_info("{t}")').fetchall()
                cols = [r[1] for r in info]
                for r in info:
                    self.dictionary.append([db_name, t, r[0] + 1, r[1], r[2]])
                total = con.execute(f'SELECT COUNT(*) FROM "{t}"').fetchone()[0]
                path = os.path.join(self.out_dir, group, stem, f"{t}.csv")
                cur = con.execute(f'SELECT * FROM "{t}"')
                write_rows(path, cols, cur)
                status = self.record(
                    group, db_name, t, path, total, count_csv_rows(path), description
                )
                print(f"  {status:8} {db_name} / {t}: {total} rows")
        finally:
            con.close()

    def export_json_file(self, src_path, dest_dir):
        """Flattens a JSON array or JSONL file of records into one CSV."""
        name = os.path.basename(src_path)
        stem, ext = os.path.splitext(name)
        with open(src_path, encoding="utf-8") as fh:
            if ext.lower() == ".jsonl":
                records = [json.loads(line) for line in fh if line.strip()]
            else:
                data = json.load(fh)
                records = data if isinstance(data, list) else [data]
        flat = [flatten(r) for r in records]
        header = []
        for rec in flat:
            for k in rec:
                if k not in header:
                    header.append(k)
        path = os.path.join(dest_dir, f"{stem}.csv")
        write_rows(path, header, ([rec.get(h) for h in header] for rec in flat))
        status = self.record(
            RAW, name, "(json records)", path, len(flat), count_csv_rows(path),
            "raw TikTok Shop pull, nested fields flattened (lists kept as JSON text)",
        )
        print(f"  {status:8} {name}: {len(flat)} rows")

    def copy_csv(self, src_path, dest_dir, note):
        name = os.path.basename(src_path)
        os.makedirs(dest_dir, exist_ok=True)
        path = os.path.join(dest_dir, name)
        shutil.copyfile(src_path, path)
        n = count_csv_rows(src_path)
        status = self.record(RAW, name, "(csv copy)", path, n, count_csv_rows(path), note)
        print(f"  {status:8} {name}: {n} rows")


README = """SG contact-lens project: data handover (CSV export)
Created {stamp} by Scripts/export_databases_to_csv_for_handover.py

Folders
  01_raw_scraped/             Data as collected from each channel. One folder per
                              source database, one CSV per table. Some tables also
                              carry columns added at scrape time (translation,
                              model sentiment, journey stage); these are labelled
                              as such in DATA_DICTIONARY.csv by column name.
  02_tagged_and_consolidated/ Built from the raw data. voice_items is every comment,
                              post and review in one table (key: item_id); voice_tags
                              holds the model's sentiment, themes and journey stage
                              per item_id. voice_tags contains every tag version;
                              filter to the latest taxonomy_version before counting.
  MANIFEST.csv                Every file, its source, rows in the database, rows in
                              the CSV, and a check (ok / MISMATCH / skipped).
  DATA_DICTIONARY.csv         Every column of every table with its type.

Reading the files
  - UTF-8 with byte-order mark: Excel opens it directly; Python: encoding="utf-8-sig".
  - Text fields can contain line breaks inside quotes. Use a CSV reader.
  - Empty cell = no value (NULL) in the database.
  - Dates are as stored by each scraper (mostly ISO text); they are not unified in
    the raw folders. voice_items has one unified date column.

Not included
  Database backups, "before_*" snapshots, and test databases (see "skipped" rows
  in MANIFEST.csv). API keys and .env files are never read.
"""


def main():
    ap = argparse.ArgumentParser(description=__doc__.split("\n\n")[0])
    ap.add_argument("--out", help="output folder (default Handover/csv_export_<date>)")
    ap.add_argument(
        "--include-snapshots",
        action="store_true",
        help="also export backups, before_* snapshots and test databases",
    )
    args = ap.parse_args()

    today = datetime.date.today().isoformat()
    out_dir = os.path.abspath(
        args.out or os.path.join(BASE_DIR, "Handover", f"csv_export_{today}")
    )
    os.makedirs(out_dir, exist_ok=True)
    ex = Exporter(out_dir)
    print(f"Writing to {out_dir}\n")

    print("Databases")
    on_disk = sorted(glob.glob(os.path.join(OUTPUT_DIR, "**", "*.db"), recursive=True))
    for db_name, (group, desc) in DATABASES.items():
        if not os.path.exists(os.path.join(OUTPUT_DIR, db_name)):
            print(f"  MISSING  {db_name} (expected but not on disk)")
            ex.record(group, db_name, "", "", 0, 0, "expected database not found")
            continue
        ex.export_db(group, db_name, desc)

    registered = set(DATABASES)
    for path in on_disk:
        name = os.path.basename(path)
        if name in registered:
            continue
        if is_snapshot(name):
            if args.include_snapshots:
                ex.export_db(RAW + "_snapshots", name, "backup/snapshot/test copy")
            else:
                ex.record("", name, "", "", "", "", "snapshot, backup or test database")
        else:
            print(f"  UNREGISTERED  {name}: add it to DATABASES in this script")
            ex.record("", name, "", "", "", "", "UNREGISTERED: not exported, add to DATABASES")

    print("\nRaw TikTok Shop files")
    tt_dir = os.path.join(DATA_DIR, "tiktok_shop_sg")
    for f in sorted(glob.glob(os.path.join(tt_dir, "*.json*"))):
        ex.export_json_file(f, os.path.join(out_dir, RAW, "tiktok_shop_raw"))

    print("\nTrade data")
    for f in sorted(glob.glob(os.path.join(OUTPUT_DIR, "UN Comtrade*.csv"))):
        ex.copy_csv(f, os.path.join(out_dir, RAW, "trade_data"),
                    "UN Comtrade lens trade figures, copied as-is")

    with open(os.path.join(out_dir, "MANIFEST.csv"), "w", newline="", encoding="utf-8-sig") as fh:
        w = csv.writer(fh)
        w.writerow(["group", "source", "table", "csv_file", "rows_in_source",
                    "rows_in_csv", "check", "note"])
        w.writerows(ex.manifest)
    with open(os.path.join(out_dir, "DATA_DICTIONARY.csv"), "w", newline="", encoding="utf-8-sig") as fh:
        w = csv.writer(fh)
        w.writerow(["database", "table", "column_position", "column", "sqlite_type"])
        w.writerows(ex.dictionary)
    with open(os.path.join(out_dir, "README.txt"), "w", encoding="utf-8") as fh:
        fh.write(README.format(stamp=datetime.datetime.now().strftime("%Y-%m-%d %H:%M")))

    ok = sum(1 for m in ex.manifest if m[6] == "ok")
    bad = [m for m in ex.manifest if m[6] == "MISMATCH" or "UNREGISTERED" in m[7] or "not found" in m[7]]
    files = [m for m in ex.manifest if m[3]]
    rows = sum(m[5] for m in files if isinstance(m[5], int))
    print(f"\n{ok}/{len(files)} files verified, {rows:,} rows in total.")
    if bad:
        print("Problems:")
        for m in bad:
            print("  ", m[1], m[2], m[6], m[7])
        return 1
    return 0


if __name__ == "__main__":
    sys.exit(main())
