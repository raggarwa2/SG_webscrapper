#!/usr/bin/env python3
"""
lazada_pricing_th.py

Pulls Acne-Aid + competitor SKU pricing AND reviews from Lazada Thailand
via the Apify actor "fatihtahta/lazada-scraper" (Lazada Scraper | All-In-One).

Mirrors the conventions used elsewhere in this project:
  - SQLite storage, WAL mode
  - DB-only by default; --export-csv is explicit
  - Incremental per-batch saving (safe to Ctrl-C and resume)
  - Schema-migration-safe (ALTER TABLE ADD COLUMN, not just CREATE TABLE IF NOT EXISTS)

------------------------------------------------------------------------------
CONFIRMED INPUT SCHEMA (verified directly from Apify Console JSON tab, 2026-07-27)
------------------------------------------------------------------------------
{
    "country": "th",
    "enrich_data": false,
    "getReviews": true,
    "limit": 10,
    "maxReviews": 20,
    "queries": ["Acne-Aid Liq Cleanser 100ml", "Acne-Aid Gentle Cleanser 100ml", ...]
}

Key points:
  - `queries` accepts a LIST — you can batch many search terms into ONE
    actor run rather than one API call per product. This script batches
    all queries from your input CSV into a single call by default (cheaper,
    faster), but supports --batch-size if you want to split into smaller
    chunks (e.g. to keep each run's cost/duration bounded, or to checkpoint
    progress across a large SKU list).
  - `limit` = max products returned PER query.
  - `maxReviews` = max reviews pulled PER product (only used if getReviews=true).
  - `enrich_data` left as false by default (per the confirmed example) —
    flip to true if you find you need deeper per-product enrichment and are
    willing to pay for the extra requests it implies.

------------------------------------------------------------------------------
CONFIRMED OUTPUT SCHEMA (verified from a real test run, 2026-07-27)
------------------------------------------------------------------------------
Each dataset item has a "record_type" of either "product" or "review".

PRODUCT record — key fields used here:
  product.product_id, product.sku, product.brand
  title (top-level)
  seller.seller_name
  pricing.price, pricing.original_price, pricing.discount
  metrics.rating, metrics.review_count, metrics.sales_count
  media.badges[].bizType  -> contains "lazMall" if it's an official LazMall
                             listing; ABSENT means third-party reseller.
                             (seller_name alone is NOT reliable for this —
                             e.g. seller_name "Konvy" can still be lazMall-badged)
  source_context.search_query -> which of our input queries produced this

REVIEW record — key fields used here:
  product_id             -> joins back to the product record above
  review.buyer_name, review.rating, review.review_time
  review.review_content_list -> LIST of {attribute, content} pairs;
                                 joined with " | " into one ReviewText field
  review.like_count

IMPORTANT CONFIRMED LIMITATION: in a test run with 3 batched queries,
limit=10, getReviews=true, maxReviews=20 -> only ONE product (out of 30
returned) had any reviews attached at all. This strongly suggests getReviews
applies to roughly one product per RUN, not per query or per product in the
batch. If review coverage across every SKU matters, use --batch-size 1 (one
query per actor call) rather than batching many queries together -- costs
more calls, but each is cheap, and it's the only way we've confirmed to
reliably get reviews per product.

There is no explicit "PackSize" field in the output -- we extract it with a
regex over the product title (looks for a number followed by ml/g/gm/oz).
This is best-effort; titles are inconsistent (bundles, multi-packs, Thai
text) so spot-check this column rather than trusting it blindly.
------------------------------------------------------------------------------
"""

import argparse
import csv
import os
import re
import sqlite3
import sys
import time
from datetime import datetime, timezone

import requests

# Optional: if python-dotenv is installed and a .env file is present in the
# working directory (or a parent), load it automatically so APIFY_TOKEN can
# live in .env instead of requiring a manual `export`/`$env:` each session.
# Falls back silently if python-dotenv isn't installed -- doesn't break
# anything for people who prefer setting the env var directly.
try:
    from dotenv import load_dotenv
    load_dotenv()
except ImportError:
    pass

# ------------------------------------------------------------------------
# CONFIG
# ------------------------------------------------------------------------

ACTOR_ID = "fatihtahta/lazada-scraper"
APIFY_API_BASE = "https://api.apify.com/v2"
APIFY_TOKEN = os.environ.get("APIFY_TOKEN")

DEFAULT_DB_PATH = "acne_aid_th.db"          # adjust to your existing project DB filename
TABLE_NAME = "lazada_data"

# Columns matching the schema we've been validating manually via Claude/Gemini in Chrome
CSV_COLUMNS = [
    "Date", "Reviewer", "Rating", "ReviewText", "Helpful",
    "SKU", "ProductName", "Brand", "PackSize", "SellerType",
    "Price", "OriginalPrice", "DiscountPercent", "Channel",
    "OverallRating", "TotalReviews",
]

# Internal bookkeeping columns added on top of the CSV schema
EXTRA_COLUMNS = ["query_used", "acne_aid_sku", "priority", "pulled_at"]

ALL_COLUMNS = CSV_COLUMNS + EXTRA_COLUMNS


# ------------------------------------------------------------------------
# DB SETUP (schema-migration-safe)
# ------------------------------------------------------------------------

def get_db(db_path: str) -> sqlite3.Connection:
    conn = sqlite3.connect(db_path)
    conn.execute("PRAGMA journal_mode=WAL;")
    ensure_schema(conn)
    return conn


def ensure_schema(conn: sqlite3.Connection):
    conn.execute(f"""
        CREATE TABLE IF NOT EXISTS {TABLE_NAME} (
            id INTEGER PRIMARY KEY AUTOINCREMENT
        )
    """)
    cur = conn.execute(f"PRAGMA table_info({TABLE_NAME})")
    existing_cols = {row[1] for row in cur.fetchall()}
    for col in ALL_COLUMNS:
        if col not in existing_cols:
            conn.execute(f'ALTER TABLE {TABLE_NAME} ADD COLUMN "{col}" TEXT')
    conn.commit()


def insert_rows(conn: sqlite3.Connection, rows: list[dict]):
    if not rows:
        return
    cols = ALL_COLUMNS
    placeholders = ", ".join(["?"] * len(cols))
    col_list = ", ".join(f'"{c}"' for c in cols)
    sql = f'INSERT INTO {TABLE_NAME} ({col_list}) VALUES ({placeholders})'
    values = [[row.get(c) for c in cols] for row in rows]
    conn.executemany(sql, values)
    conn.commit()


# ------------------------------------------------------------------------
# APIFY CALL
# ------------------------------------------------------------------------

def call_lazada_actor(queries: list[str], limit: int, max_reviews: int,
                       get_reviews: bool = True, enrich_data: bool = False) -> list[dict]:
    """
    Runs the actor synchronously with a BATCH of queries in one call.
    Confirmed schema: country, enrich_data, getReviews, limit, maxReviews, queries.
    """
    if not APIFY_TOKEN:
        raise RuntimeError(
            "APIFY_TOKEN environment variable is not set.\n"
            "  Fix options:\n"
            "  1) PowerShell:  $env:APIFY_TOKEN = \"your_token\"\n"
            "  2) bash/Linux:  export APIFY_TOKEN=\"your_token\"\n"
            "  3) Put APIFY_TOKEN=your_token in a .env file in this folder "
            "(requires: pip install python-dotenv)"
        )

    url = f"{APIFY_API_BASE}/acts/{ACTOR_ID.replace('/', '~')}/run-sync-get-dataset-items"
    payload = {
        "country": "th",
        "enrich_data": enrich_data,
        "getReviews": get_reviews,
        "limit": limit,
        "maxReviews": max_reviews,
        "queries": queries,
    }
    params = {"token": APIFY_TOKEN}

    resp = requests.post(url, params=params, json=payload, timeout=600)
    if not resp.ok:
        # Apify returns a JSON body with the real validation reason on 400s --
        # raise_for_status() alone only gives the generic status line, which
        # hides exactly what's wrong with the payload. Surface it here.
        try:
            detail = resp.json()
        except ValueError:
            detail = resp.text
        raise RuntimeError(
            f"Apify API error {resp.status_code} calling actor.\n"
            f"  Payload sent: {payload}\n"
            f"  Apify response: {detail}"
        )
    return resp.json()


# ------------------------------------------------------------------------
# NORMALIZATION (confirmed real schema — see docstring above)
# ------------------------------------------------------------------------

_PACK_SIZE_RE = re.compile(r'(\d+\.?\d*)\s?(ml|g|gm|oz)\b', re.IGNORECASE)


def extract_pack_size(title: str) -> str:
    """Best-effort pack size extraction from product title. Spot-check results."""
    m = _PACK_SIZE_RE.search(title or "")
    return f"{m.group(1)}{m.group(2)}" if m else ""


def normalize_product(raw: dict) -> dict:
    ent = raw.get("product", {}) or {}
    pricing = raw.get("pricing", {}) or {}
    metrics = raw.get("metrics", {}) or {}
    media = raw.get("media", {}) or {}
    badges = [b.get("bizType") for b in media.get("badges", [])]
    seller_type = "LazMall" if "lazMall" in badges else "Reseller"
    title = raw.get("title", "")

    return {
        "product_id": ent.get("product_id") or raw.get("record_id"),
        "SKU": ent.get("sku", ""),
        "ProductName": title,
        "Brand": ent.get("brand", ""),
        "PackSize": extract_pack_size(title),
        "SellerType": seller_type,
        "Price": pricing.get("price", ""),
        "OriginalPrice": pricing.get("original_price", ""),
        "DiscountPercent": pricing.get("discount", ""),
        "OverallRating": metrics.get("rating", ""),
        "TotalReviews": metrics.get("review_count", ""),
        "query_used": raw.get("source_context", {}).get("search_query", ""),
    }


def normalize_review(raw: dict) -> dict:
    review = raw.get("review", {}) or {}
    content_parts = [c.get("content", "") for c in review.get("review_content_list", []) if c.get("content")]
    return {
        "product_id": raw.get("product_id"),
        "Date": review.get("review_time", ""),
        "Reviewer": review.get("buyer_name", ""),
        "Rating": review.get("rating", ""),
        "ReviewText": " | ".join(content_parts),
        "Helpful": review.get("like_count", 0),
    }


def build_rows(raw_items: list[dict], query_lookup: dict) -> list[dict]:
    """
    Joins review records back to their product record (pricing/brand/etc.)
    to produce one flat row per review, matching CSV_COLUMNS. Products with
    zero reviews still get one row each (with blank review fields) so we
    don't silently lose pricing data for less-reviewed SKUs.

    NOTE: per the confirmed limitation above, expect most products in a
    batched run to have zero reviews — that's the actor, not a bug here.
    """
    now = datetime.now(timezone.utc).isoformat()

    products_by_id = {}
    review_raws = []
    for item in raw_items:
        if item.get("record_type") == "product":
            p = normalize_product(item)
            products_by_id[p["product_id"]] = p
        elif item.get("record_type") == "review":
            review_raws.append(item)

    rows = []
    seen_product_ids = set()

    for r in review_raws:
        rv = normalize_review(r)
        pid = rv["product_id"]
        prod = products_by_id.get(pid, {})
        meta = query_lookup.get(prod.get("query_used", ""), {"acne_aid_sku": "", "priority": ""})
        rows.append({
            "Date": rv["Date"], "Reviewer": rv["Reviewer"], "Rating": rv["Rating"],
            "ReviewText": rv["ReviewText"], "Helpful": rv["Helpful"],
            "SKU": prod.get("SKU", ""), "ProductName": prod.get("ProductName", ""),
            "Brand": prod.get("Brand", ""), "PackSize": prod.get("PackSize", ""),
            "SellerType": prod.get("SellerType", ""), "Price": prod.get("Price", ""),
            "OriginalPrice": prod.get("OriginalPrice", ""), "DiscountPercent": prod.get("DiscountPercent", ""),
            "Channel": "Lazada Thailand",
            "OverallRating": prod.get("OverallRating", ""), "TotalReviews": prod.get("TotalReviews", ""),
            "query_used": prod.get("query_used", ""),
            "acne_aid_sku": meta["acne_aid_sku"], "priority": meta["priority"],
            "pulled_at": now,
        })
        seen_product_ids.add(pid)

    for pid, prod in products_by_id.items():
        if pid in seen_product_ids:
            continue
        meta = query_lookup.get(prod.get("query_used", ""), {"acne_aid_sku": "", "priority": ""})
        rows.append({
            "Date": "", "Reviewer": "", "Rating": "", "ReviewText": "", "Helpful": "",
            "SKU": prod.get("SKU", ""), "ProductName": prod.get("ProductName", ""),
            "Brand": prod.get("Brand", ""), "PackSize": prod.get("PackSize", ""),
            "SellerType": prod.get("SellerType", ""), "Price": prod.get("Price", ""),
            "OriginalPrice": prod.get("OriginalPrice", ""), "DiscountPercent": prod.get("DiscountPercent", ""),
            "Channel": "Lazada Thailand",
            "OverallRating": prod.get("OverallRating", ""), "TotalReviews": prod.get("TotalReviews", ""),
            "query_used": prod.get("query_used", ""),
            "acne_aid_sku": meta["acne_aid_sku"], "priority": meta["priority"],
            "pulled_at": now,
        })

    return rows


# ------------------------------------------------------------------------
# SKU LIST LOADING
# ------------------------------------------------------------------------

def load_sku_list(path: str) -> list[dict]:
    """
    Expects the SKU_query_master CSV (canonical query source, built from
    sku_list.md): sku_key, priority, format, brand, product_name, query,
    is_flagged, flag_note.

    One row per brand x SKU-family query already resolved upstream (blank/
    no-match cells per sku_list.md's legend are already excluded -- this
    loader does not re-derive that logic).

    `sku_key` is mapped to the internal "acne_aid_sku" field name so the
    rest of this script (query_lookup, DB columns) doesn't need to change --
    it's really a "SKU family key" shared across Acne-Aid + its matched
    competitor rows, not literally an Acne-Aid-only field.

    Flagged rows (is_flagged == "True") are loaded and queried like any
    other row, but are surfaced in the pre-run summary so you can decide
    whether to exclude them before spending on the actor call.
    """
    rows = []
    with open(path, newline="", encoding="utf-8") as f:
        reader = csv.DictReader(f)
        for r in reader:
            rows.append({
                "acne_aid_sku": r.get("sku_key", "").strip(),
                "priority": r.get("priority", "").strip(),
                "brand": r.get("brand", "").strip(),
                "product_name": r.get("product_name", "").strip(),
                "query": r.get("query", "").strip(),
                "is_flagged": r.get("is_flagged", "").strip(),
                "flag_note": r.get("flag_note", "").strip(),
            })
    return [r for r in rows if r["query"]]


def summarize_sku_list(sku_list: list[dict]) -> None:
    """
    Pre-run verification summary -- prints counts so you can eyeball that
    the load looks right (right row count, right brand mix, any flags)
    before a single Apify call is made or a dollar is spent.
    """
    n = len(sku_list)
    n_families = len({r["acne_aid_sku"] for r in sku_list})
    by_brand = {}
    for r in sku_list:
        by_brand[r["brand"]] = by_brand.get(r["brand"], 0) + 1
    flagged = [r for r in sku_list if r["is_flagged"].strip().lower() == "true"]

    print("--- SKU list verification ---")
    print(f"  Total queries loaded: {n}")
    print(f"  Unique SKU families:  {n_families}")
    print("  Rows per brand:")
    for brand, count in sorted(by_brand.items(), key=lambda kv: -kv[1]):
        print(f"    {brand:<20} {count}")
    if flagged:
        print(f"  FLAGGED rows ({len(flagged)}) -- confirm before trusting these mappings:")
        for r in flagged:
            print(f"    [{r['acne_aid_sku']}] {r['brand']}: {r['product_name']}")
            if r["flag_note"]:
                print(f"      note: {r['flag_note']}")
    print("-" * 60)


def chunk(lst: list, size: int):
    for i in range(0, len(lst), size):
        yield lst[i:i + size]


# ------------------------------------------------------------------------
# CSV EXPORT
# ------------------------------------------------------------------------

def export_csv(conn: sqlite3.Connection, out_path: str):
    cur = conn.execute(f'SELECT {", ".join(CSV_COLUMNS)} FROM {TABLE_NAME}')
    rows = cur.fetchall()
    with open(out_path, "w", newline="", encoding="utf-8") as f:
        writer = csv.writer(f)
        writer.writerow(CSV_COLUMNS)
        writer.writerows(rows)
    print(f"Exported {len(rows)} rows to {out_path}")


# ------------------------------------------------------------------------
# MAIN
# ------------------------------------------------------------------------
# COST ESTIMATION
# ------------------------------------------------------------------------

PRICE_PER_1000_RESULTS = 2.99  # actor's LISTED price -- kept for reference only, see note below
MIN_LIMIT = 10  # CONFIRMED: Apify rejects input.limit < 10 with a 400 (validated 2026-07-27)

# CALIBRATION DATA POINT (2026-07-27): a real 2-batch run (--batch-size 1,
# --limit 10, --max-reviews 20) that returned 185 review rows for the FIRST
# product alone cost $0.36 TOTAL in Apify Console -- not the $1.26+ that a
# naive "$2.99 per 1,000 dataset records" calculation would predict (185
# reviews + 10 products alone would be ~$0.58 on that model, before batch 2
# is even counted). This strongly suggests the actual billing is closer to
# a per-RUN cost (roughly $0.18/batch observed here) than a per-dataset-item
# cost. Treat this as a single data point, not a certainty -- recalibrate
# EMPIRICAL_COST_PER_BATCH below as more real runs confirm or contradict it.
EMPIRICAL_COST_PER_BATCH = 0.18  # observed: $0.36 / 2 batches, 2026-07-27


def estimate_cost(num_queries: int, limit: int, max_reviews: int, batch_size: int,
                   cost_per_batch: float = EMPIRICAL_COST_PER_BATCH):
    """
    PRIMARY estimate: empirical, based on a real observed run
    ($0.36 for 2 single-query batches = ~$0.18/batch). This is the number
    to trust for budgeting.

    SECONDARY estimate: the old per-dataset-item theoretical model
    ($2.99/1,000 records), kept for reference -- it significantly
    OVER-estimated cost in our one real test, so treat it as a rough
    ceiling/sanity-check, not the number to budget against.

    Both are estimates. Always confirm actual cost in Apify Console
    (Runs -> a run -> Usage/Cost) -- and if a new run's real cost diverges
    from EMPIRICAL_COST_PER_BATCH, update that constant.
    """
    num_batches = -(-num_queries // batch_size)  # ceil division
    total_products = num_queries * limit

    # Empirical (trust this one)
    empirical_cost = num_batches * cost_per_batch

    # Theoretical per-item model (reference only -- known to overestimate)
    reviews_low = num_batches * max_reviews
    reviews_high = total_products * max_reviews
    results_low = total_products + reviews_low
    results_high = total_products + reviews_high
    theoretical_cost_low = (results_low / 1000) * PRICE_PER_1000_RESULTS
    theoretical_cost_high = (results_high / 1000) * PRICE_PER_1000_RESULTS

    return {
        "num_batches": num_batches,
        "total_products_est": total_products,
        "empirical_cost": empirical_cost,
        "cost_per_batch_used": cost_per_batch,
        "theoretical_cost_low": theoretical_cost_low,
        "theoretical_cost_high": theoretical_cost_high,
    }


def print_cost_estimate(est: dict):
    print("--- Cost estimate ---")
    print(f"  Actor calls (batches):        {est['num_batches']}")
    print(f"  Estimated product records:    {est['total_products_est']}")
    print(f"  EMPIRICAL ESTIMATE (trust this): ${est['empirical_cost']:.2f}"
          f"  ({est['num_batches']} batches x ${est['cost_per_batch_used']:.2f}/batch,"
          f" calibrated from a real Apify Console run on 2026-07-27)")
    print(f"  Theoretical per-item model (reference/ceiling, known to overestimate):"
          f" ${est['theoretical_cost_low']:.2f} - ${est['theoretical_cost_high']:.2f}")
    print("  NOTE: only 1 real run has been used to calibrate the empirical figure.")
    print("  Always verify actual cost in Apify Console after each run, and update")
    print("  EMPIRICAL_COST_PER_BATCH in this script if real costs diverge.")
    print("-" * 60)


# ------------------------------------------------------------------------
# MAIN
# ------------------------------------------------------------------------

def main():
    parser = argparse.ArgumentParser(description="Lazada Thailand pricing + reviews puller (Apify actor)")
    parser.add_argument("--skus", default="sku_query_master.csv",
                         help="Path to the SKU_query_master CSV (sku_key,priority,format,brand,"
                              "product_name,query,is_flagged,flag_note). Defaults to "
                              "sku_query_master.csv in the current folder.")
    parser.add_argument("--db", default=DEFAULT_DB_PATH, help="SQLite DB path")
    parser.add_argument("--limit", type=int, default=10,
                         help="Max products per search query (Apify enforces a minimum of 10 -- "
                              "lower values are rejected with a 400 error")
    parser.add_argument("--max-reviews", type=int, default=20, help="Max reviews per product")
    parser.add_argument("--batch-size", type=int, default=10,
                         help="How many queries to send per actor call (queries accepts a list; "
                              "batching keeps each run bounded and gives incremental checkpoints)")
    parser.add_argument("--no-reviews", action="store_true", help="Set getReviews=false")
    parser.add_argument("--enrich", action="store_true", help="Set enrich_data=true")
    parser.add_argument("--export-csv", metavar="OUT_PATH", default=None,
                         help="If set, also export the full table to this CSV path after running")
    parser.add_argument("--dry-run", action="store_true",
                         help="Print planned batches AND cost estimate without calling Apify or touching the DB")
    parser.add_argument("--yes", action="store_true",
                         help="Skip the cost-confirmation prompt and run immediately")
    parser.add_argument("--max-cost", type=float, default=None,
                         help="Abort automatically if the EMPIRICAL cost estimate exceeds this dollar amount")
    parser.add_argument("--cost-per-batch", type=float, default=EMPIRICAL_COST_PER_BATCH,
                         help=f"Override the empirical per-batch cost used for estimation "
                              f"(default ${EMPIRICAL_COST_PER_BATCH:.2f}, calibrated from a real "
                              f"run on 2026-07-27 -- update this as you gather more real data points)")
    args = parser.parse_args()

    if args.limit < MIN_LIMIT:
        print(f"ERROR: --limit {args.limit} is below Apify's confirmed minimum of {MIN_LIMIT}. "
              f"Requests with limit < {MIN_LIMIT} are rejected with a 400 error -- "
              f"use --limit {MIN_LIMIT} or higher.")
        return

    sku_list = load_sku_list(args.skus)
    print(f"Loaded {len(sku_list)} queries from {args.skus}")
    summarize_sku_list(sku_list)

    query_lookup = {
        row["query"]: {"acne_aid_sku": row["acne_aid_sku"], "priority": row["priority"]}
        for row in sku_list
    }
    all_queries = [row["query"] for row in sku_list]
    batches = list(chunk(all_queries, args.batch_size))

    est = estimate_cost(
        num_queries=len(all_queries),
        limit=args.limit,
        max_reviews=args.max_reviews,
        batch_size=args.batch_size,
        cost_per_batch=args.cost_per_batch,
    )
    print_cost_estimate(est)

    if args.dry_run:
        for i, batch in enumerate(batches, start=1):
            print(f"  [DRY RUN] batch {i}/{len(batches)} ({len(batch)} queries): {batch}")
        return

    if args.max_cost is not None and est["empirical_cost"] > args.max_cost:
        print(f"ABORTING: estimated cost ${est['empirical_cost']:.2f} exceeds "
              f"--max-cost ${args.max_cost:.2f}. Adjust --limit/--max-reviews/--batch-size, "
              f"raise --max-cost, or split the SKU file into smaller pieces.")
        return

    if not args.yes:
        resp = input(f"Proceed with {est['num_batches']} actor call(s), "
                      f"est. ${est['empirical_cost']:.2f}? [y/N]: ").strip().lower()
        if resp != "y":
            print("Aborted by user.")
            return

    conn = get_db(args.db)

    for i, batch in enumerate(batches, start=1):
        print(f"[Batch {i}/{len(batches)}] Querying Lazada TH for {len(batch)} products...")
        try:
            raw_items = call_lazada_actor(
                queries=batch,
                limit=args.limit,
                max_reviews=args.max_reviews,
                get_reviews=not args.no_reviews,
                enrich_data=args.enrich,
            )
        except Exception as e:
            print(f"  ERROR calling actor for batch {i}: {e}")
            continue

        normalized = build_rows(raw_items, query_lookup)
        n_with_reviews = sum(1 for r in normalized if r["ReviewText"])
        insert_rows(conn, normalized)
        print(f"  -> saved {len(normalized)} rows ({n_with_reviews} with review text) (committed)")
        time.sleep(1)

    if args.export_csv:
        export_csv(conn, args.export_csv)

    conn.close()
    print("Done.")


if __name__ == "__main__":
    main()
