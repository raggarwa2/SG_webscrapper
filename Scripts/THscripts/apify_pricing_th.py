#!/usr/bin/env python3
"""
apify_pricing_th.py — Watsons TH + Shopee TH pricing via Apify actors
Standalone script, sibling to pipeline_th.py -- same run/poll/fetch-dataset
Apify pattern as xhs_scraper_v2.py (HK contact-lens project, Xiaohongshu via
Apify). Reused here as a pattern only: different actors, different brands,
same acneaid_th.db.

WHY THIS EXISTS: pipeline_th.py's discover_watsons_th() and config_th.yaml's
shopee_th block both confirm these two sources are hard-blocked for plain
HTTP and headless Playwright alike (Akamai-style wall on Watsons, JS-SPA +
403'd internal API on Shopee). DISCOVERY_REPORT.md flagged the fix as a
choice between Claude-in-Chrome or a paid Apify actor -- this script is
that Apify path.

Actors:
  - Watsons TH: stealth_mode/watsons-product-search-scraper
      Input: {"urls": [search_url], "max_items_per_url": N}
      Explicitly supports watsons.co.th; takes real search-result URLs.
  - Shopee TH:  gio21/shopee-scraper
      Input: {"keywords": [...], "country": "TH", "maxItems": N}
      Highest-usage Shopee actor on the Apify store, native TH support.

Both actors' output field names are UNVERIFIED against real data as of
writing -- extract_watsons_fields()/extract_shopee_fields() use the _pick()
fallback-key pattern from xhs_scraper_v2.py precisely because of this. Run
--dry-run first and check output/apify_raw_*.json before trusting a full run.

Usage:
    python apify_pricing_th.py --site watsons_th --brand "Acne-Aid" --max-items 10 --dry-run
    python apify_pricing_th.py --site shopee_th  --brand "Acne-Aid" --max-items 10 --dry-run
    python apify_pricing_th.py --site watsons_th shopee_th          # full run, all brands

    # SKU-targeted Shopee search (one query per named SKU/competitor
    # equivalent from sku_list.md, see build_shopee_sku_queries.py),
    # instead of one generic keyword per brand -- dry-run a few rows first:
    python apify_pricing_th.py --site shopee_th --skus skus_shopee_full.csv --max-items 10 --dry-run
"""

import os
import re
import sys
import csv
import json
import time
import hashlib
import logging
import argparse
import sqlite3
import threading
import urllib.parse
from datetime import datetime, timezone
from pathlib import Path
from typing import Optional, List

import requests
import yaml
from dotenv import load_dotenv

from pipeline_th import (
    open_db, save_products, classify_skincare_type,
    _parse_pack_size, _parse_price, export_csvs,
)

load_dotenv()

APIFY_BASE = "https://api.apify.com/v2"
CONFIG_PATH = "config_th.yaml"
WATSONS_ACTOR = "stealth_mode/watsons-product-search-scraper"
SHOPEE_ACTOR = "gio21/shopee-scraper"

os.makedirs("output", exist_ok=True)
LOG_PATH = f"output/apify_pricing_{datetime.now().strftime('%Y%m%d_%H%M')}.log"
logging.basicConfig(
    level=logging.INFO,
    format="%(asctime)s [%(levelname)s] %(message)s",
    handlers=[logging.FileHandler(LOG_PATH, encoding="utf-8"), logging.StreamHandler(sys.stdout)],
)
log = logging.getLogger(__name__)


# ── Apify run/poll/fetch — same shape as xhs_scraper_v2.py's apify_run_one ──
def apify_run(token: str, actor_id: str, run_input: dict, label: str) -> list[dict]:
    actor_slug = actor_id.replace("/", "~")
    r = requests.post(
        f"{APIFY_BASE}/acts/{actor_slug}/runs",
        json=run_input,
        params={"token": token},
        timeout=30,
    )
    if not r.ok:
        log.error(f"  [{label}] Apify error body: {r.text[:500]}")
    r.raise_for_status()
    run_info = r.json()["data"]
    run_id, dataset_id = run_info["id"], run_info["defaultDatasetId"]
    log.info(f"  [{label}] Apify run started -> run_id={run_id}")

    status_url = f"{APIFY_BASE}/actor-runs/{run_id}"
    for attempt in range(90):  # 90 x 10s = 15 min
        time.sleep(10)
        status = requests.get(status_url, params={"token": token}, timeout=15).json()["data"]["status"]
        log.info(f"  [{label}] status: {status} (attempt {attempt + 1})")
        if status == "SUCCEEDED":
            break
        if status in ("FAILED", "ABORTED", "TIMED-OUT"):
            raise RuntimeError(f"Apify run {run_id} ended with: {status}")
    else:
        raise TimeoutError(f"Apify run {run_id} did not finish in 15 minutes")

    items_r = requests.get(
        f"{APIFY_BASE}/datasets/{dataset_id}/items",
        params={"token": token, "format": "json"},
        timeout=60,
    )
    items_r.raise_for_status()
    items = items_r.json()
    log.info(f"  [{label}] retrieved {len(items)} items")
    return items


def _pick(d: dict, *keys: str, default=None):
    """Same fallback-key helper as xhs_scraper_v2.py -- actor output field
    names differ from what the docs promise; try each candidate in order."""
    for k in keys:
        v = d.get(k)
        if v not in (None, ""):
            return v
    return default


def _dump_raw(site: str, brand: str, items: list[dict]) -> None:
    path = f"output/apify_raw_{site}_{brand.replace(' ', '_')}.json"
    with open(path, "w", encoding="utf-8") as f:
        json.dump(items[:5], f, ensure_ascii=False, indent=2)
    log.info(f"  Raw sample (first 5 of {len(items)}) written to {path}")


def ensure_price_history_table(conn: sqlite3.Connection) -> None:
    """Creates price_history if it doesn't exist yet. Unlike products
    (upserted on product_code -- only the latest price survives), this
    upserts on (product_code, pull_date): same-day reruns update in place,
    cross-day pulls accumulate a real history.

    2026-08-27 FIX: this function previously defined its OWN schema
    (scraped_at, category, no pull_date) that diverged from the schema
    pipeline_th.py's open_db()/SCHEMA actually creates (pull_date TEXT NOT
    NULL, UNIQUE(product_code, pull_date)) -- and since main() always calls
    open_db() before this function, the real table already existed by the
    time this ran, so `CREATE TABLE IF NOT EXISTS` here was always a no-op
    and every save_price_history() INSERT (which never populated pull_date)
    failed with a NOT NULL constraint violation. Confirmed: all 863 rows
    from the 2026-08-27 Shopee refresh silently failed this way -- no
    historical trail exists for that pull in this DB. Fixed by matching
    pipeline_th.py's real schema here too (so this function is also correct
    if ever called against a fresh DB that hasn't gone through open_db()
    first), and keeping `category` (the same classify_skincare_type()
    free-text read already computed per item -- see
    extract_watsons_fields/extract_shopee_fields, added here so a
    family/functionality-level price TREND becomes possible from
    data_access.load_price_history()) as an additive ALTER TABLE column on
    top of that real schema, not a competing one. Rows inserted before this
    fix have no category (NULL), not a wrong one."""
    conn.executescript("""
        CREATE TABLE IF NOT EXISTS price_history (
            id              INTEGER PRIMARY KEY AUTOINCREMENT,
            product_code    TEXT    NOT NULL,
            brand           TEXT    NOT NULL,
            site            TEXT    NOT NULL,
            pull_date       TEXT    NOT NULL,
            sell_price      REAL,
            normal_price    REAL,
            scraped_at      TEXT,
            UNIQUE(product_code, pull_date)
        );
        CREATE INDEX IF NOT EXISTS idx_price_history_product ON price_history(product_code);
        CREATE INDEX IF NOT EXISTS idx_price_history_date ON price_history(pull_date);
    """)
    existing_cols = {row[1] for row in conn.execute("PRAGMA table_info(price_history)").fetchall()}
    if "category" not in existing_cols:
        conn.execute("ALTER TABLE price_history ADD COLUMN category TEXT")
    conn.commit()


def save_price_history(conn: sqlite3.Connection, products: list[dict], lock: threading.Lock) -> int:
    """Upsert on (product_code, pull_date) -- same shape as
    pipeline_th.save_products()'s own price_history insert (lines ~1105-
    1119), extended with the category column this script added. pull_date
    is derived from scraped_at the same way pipeline_th.py does; a row
    with no parseable scraped_at is skipped rather than inserted with a
    NULL pull_date (which the NOT NULL constraint would reject anyway).
    Same lock pattern as pipeline_th.save_products() so writes against the
    same connection don't race."""
    inserted = 0
    with lock:
        for p in products:
            pull_date = (p.get("scraped_at") or "")[:10]
            if not pull_date:
                log.warning(f"[DB] Price history skip (no scraped_at): {p.get('product_code')}")
                continue
            try:
                conn.execute(
                    """INSERT INTO price_history
                       (product_code, brand, site, pull_date, sell_price, normal_price, scraped_at, category)
                       VALUES (?,?,?,?,?,?,?,?)
                       ON CONFLICT(product_code, pull_date) DO UPDATE SET
                         sell_price   = excluded.sell_price,
                         normal_price = excluded.normal_price,
                         scraped_at   = excluded.scraped_at,
                         category     = excluded.category""",
                    (
                        p["product_code"], p["brand"], p["site"], pull_date,
                        p["sell_price"], p["normal_price"], p["scraped_at"], p.get("category"),
                    ),
                )
                inserted += 1
            except Exception as e:
                log.warning(f"[DB] Price history insert error: {e}")
        conn.commit()
    return inserted


def export_price_history_csv(conn: sqlite3.Connection, output_dir: str) -> int:
    """Exports price_history to a client/dashboard-ready CSV, same
    utf-8-sig + regenerate-fresh-every-run convention as pipeline_th.py's
    export_csvs(). Dashboard reads this via a dedicated data_access.py
    loader (app/lib/data_access.py) once copied into the dashboard's
    data/ dir -- see its README's "Completing the data" section for that
    manual-copy pattern.

    Writes to the SAME filename pipeline_th.py's own export_csvs() writes
    (both scripts share one acneaid_th.db) -- column layout now matches
    pipeline_th.py's SELECT (product_code, brand, site, pull_date,
    sell_price, normal_price, scraped_at) plus this script's own category
    addition appended, so whichever script runs last no longer silently
    changes the file's schema out from under the other (2026-08-27 fix,
    same session as the pull_date NOT NULL bug above)."""
    rows = conn.execute(
        "SELECT product_code, brand, site, pull_date, sell_price, normal_price, scraped_at, category "
        "FROM price_history ORDER BY brand, product_code, pull_date"
    ).fetchall()
    path = Path(output_dir) / "acneaid_th_price_history.csv"
    with open(path, "w", newline="", encoding="utf-8-sig") as f:
        writer = csv.writer(f)
        writer.writerow(["product_code", "brand", "site", "pull_date", "sell_price", "normal_price", "scraped_at", "category"])
        for r in rows:
            writer.writerow(tuple(r))
    return len(rows)


# ── Watsons TH ────────────────────────────────────────────────────────────
def extract_watsons_fields(item: dict, brand: str, now: str) -> dict:
    raw_name = _pick(item, "name", "title", "productName", "product_name", default="")
    url = _pick(item, "url", "productUrl", "product_url", "link", default="")
    sell = _parse_price(str(_pick(item, "price", "sellingPrice", "sell_price", "salePrice", default="") or ""))
    normal = _parse_price(str(_pick(item, "originalPrice", "listPrice", "regularPrice", "normal_price", default="") or ""))
    return {
        "product_code": "watsons_" + hashlib.md5((url or raw_name or str(item)).encode()).hexdigest()[:12],
        "brand": brand,
        "site": "watsons_th",
        "store_name": "Watsons.co.th",
        "name_th_or_en": raw_name[:300] if raw_name else None,
        "pack_size": _parse_pack_size(raw_name),
        "category": classify_skincare_type(raw_name),
        "url": url or None,
        "sell_price": sell,
        "normal_price": normal,
        "review_count": _pick(item, "reviewCount", "review_count", "ratingCount"),
        "avg_rating": _pick(item, "rating", "avgRating", "avg_rating"),
        "item_code": _pick(item, "code", "productCode", "sku"),
        "currency": "THB",
        "discovered_at": now,
        "scraped_at": now,
    }


def discover_watsons_th_apify(
    config: dict, token: str, brand_filter: Optional[List[str]] = None,
    max_items: int = 20, dry_run: bool = False,
) -> List[dict]:
    now = datetime.now(timezone.utc).isoformat()
    products: List[dict] = []
    for brand in config["brands"]:
        name = brand["name"]
        if brand_filter and name.lower() not in [b.lower() for b in brand_filter]:
            continue
        search_url = (
            f"https://www.watsons.co.th/en/search?text={urllib.parse.quote(name)}"
            f"&useDefaultSearch=false&brandRedirect=true"
        )
        log.info(f"[DISCOVER] Watsons.co.th (Apify) | {name} | {search_url}")
        try:
            items = apify_run(
                token, WATSONS_ACTOR,
                {"urls": [search_url], "max_items_per_url": max_items, "ignore_url_failures": True},
                f"watsons:{name}",
            )
        except Exception as e:
            log.warning(f"  Watsons TH | {name}: {e}")
            continue

        if dry_run:
            _dump_raw("watsons_th", name, items)

        for it in items:
            products.append(extract_watsons_fields(it, name, now))
        log.info(f"[DISCOVER] Watsons.co.th (Apify) | {name}: {len(items)} raw items")
    return products


# ── Shopee TH ─────────────────────────────────────────────────────────────
def extract_shopee_fields(item: dict, brand: str, now: str) -> dict:
    raw_name = _pick(item, "name", "title", "productName", default="")
    url = _pick(item, "url", "itemUrl", "link", default="")
    sell = _parse_price(str(_pick(item, "price", "sellingPrice", "salePrice", "priceMin", default="") or ""))
    normal = _parse_price(str(_pick(item, "originalPrice", "priceBeforeDiscount", "listPrice", default="") or ""))
    return {
        "product_code": "shopee_" + hashlib.md5((url or raw_name or str(item)).encode()).hexdigest()[:12],
        "brand": brand,
        "site": "shopee_th",
        "store_name": _pick(item, "shopName", "sellerName", "shop_name", default="Shopee TH"),
        "name_th_or_en": raw_name[:300] if raw_name else None,
        "pack_size": _parse_pack_size(raw_name),
        "category": classify_skincare_type(raw_name),
        "url": url or None,
        "sell_price": sell,
        "normal_price": normal,
        "review_count": _pick(item, "reviewCount", "reviews", "review_count", "rating_count"),
        "avg_rating": _pick(item, "rating", "itemRating", "avg_rating"),
        "item_code": _pick(item, "itemId", "item_id", "productId"),
        "currency": "THB",
        "discovered_at": now,
        "scraped_at": now,
    }


def discover_shopee_th_apify(
    config: dict, token: str, brand_filter: Optional[List[str]] = None,
    max_items: int = 20, dry_run: bool = False,
) -> List[dict]:
    now = datetime.now(timezone.utc).isoformat()
    products: List[dict] = []
    for brand in config["brands"]:
        name = brand["name"]
        if brand_filter and name.lower() not in [b.lower() for b in brand_filter]:
            continue
        log.info(f"[DISCOVER] Shopee.co.th (Apify) | {name}")
        try:
            items = apify_run(
                token, SHOPEE_ACTOR,
                {"keywords": [name], "country": "TH", "maxItems": max_items},
                f"shopee:{name}",
            )
        except Exception as e:
            log.warning(f"  Shopee TH | {name}: {e}")
            continue

        if dry_run:
            _dump_raw("shopee_th", name, items)

        for it in items:
            products.append(extract_shopee_fields(it, name, now))
        log.info(f"[DISCOVER] Shopee.co.th (Apify) | {name}: {len(items)} raw items")
    return products


def load_sku_queries(path: str) -> List[dict]:
    """Reads a CSV with columns acne_aid_sku,priority,query -- same shape
    as lazada_pricing_th.py's --skus input (see skus_lazada_full.csv /
    build_shopee_sku_queries.py, which generates skus_shopee_full.csv from
    sku_list.md)."""
    with open(path, encoding="utf-8-sig", newline="") as f:
        return list(csv.DictReader(f))


def classify_query_brand(query: str, config: dict) -> str:
    """Best-effort brand tag for a SKU-targeted query. These queries are
    script-generated as "{brand} {product text}" (see
    build_shopee_sku_queries.py), so a plain substring check against
    config_th.yaml's brand list is enough -- this is not the fuzzy
    multi-token classifier shopee_reconcile.py needs for noisy scraped
    titles."""
    q = query.lower().replace("&", "and")
    for brand in config["brands"]:
        if brand["name"].lower().replace("&", "and") in q:
            return brand["name"]
    return "Unknown"


def discover_shopee_th_by_sku(
    config: dict, token: str, sku_rows: List[dict],
    max_items: int = 10, dry_run: bool = False,
) -> List[dict]:
    """SKU-targeted alternative to discover_shopee_th_apify()'s brand-only
    keyword search: one actor call per named query from sku_list.md (e.g.
    "CeraVe Blemish Control Cleanser 88ml") instead of one call per brand.
    Tags each result with acne_aid_sku/priority/query_used so downstream
    analysis can check "did we find THIS SKU" directly, rather than
    fuzzy-matching brand-level results after the fact the way
    shopee_reconcile.py has to (see its 2026-07-29 note on why that's the
    harder path).

    One query per actor call, not batched: gio21/shopee-scraper's keyword-
    batching behavior is unverified (see this file's top docstring), and
    `maxItems` caps the whole call rather than per keyword, so batching
    many queries into one call would make per-SKU coverage unreliable.
    """
    now = datetime.now(timezone.utc).isoformat()
    products: List[dict] = []
    for row in sku_rows:
        query = row["query"]
        log.info(f"[DISCOVER] Shopee.co.th (Apify, SKU-targeted) | {row['acne_aid_sku']} | {query}")
        try:
            items = apify_run(
                token, SHOPEE_ACTOR,
                {"keywords": [query], "country": "TH", "maxItems": max_items},
                f"shopee_sku:{row['acne_aid_sku']}",
            )
        except Exception as e:
            log.warning(f"  Shopee TH | {query}: {e}")
            continue

        brand = classify_query_brand(query, config)

        if dry_run:
            _dump_raw("shopee_th_sku", re.sub(r"[^\w]+", "_", f"{row['acne_aid_sku']}_{brand}_{query}"), items)

        for it in items:
            fields = extract_shopee_fields(it, brand, now)
            fields["acne_aid_sku"] = row["acne_aid_sku"]
            fields["priority"] = row["priority"]
            fields["query_used"] = query
            products.append(fields)
        log.info(f"[DISCOVER] Shopee.co.th (Apify, SKU-targeted) | {row['acne_aid_sku']}: {len(items)} raw items")
    return products


def export_sku_targeted_csv(products: List[dict], out_dir: str) -> str:
    """Writes the SKU-tagged Shopee pull to its own CSV, separate from the
    shared products SQLite table/export_csvs() output -- those don't carry
    SKU provenance (acne_aid_sku/priority/query_used), and this is a
    Shopee-only concept that shouldn't force a schema change onto the
    table other sites also write to."""
    path = Path(out_dir) / "shopee_th_sku_targeted.csv"
    fieldnames = [
        "acne_aid_sku", "priority", "query_used", "brand", "site", "store_name",
        "name_th_or_en", "pack_size", "category", "url", "sell_price", "normal_price",
        "review_count", "avg_rating", "item_code", "currency", "scraped_at",
    ]
    with open(path, "w", newline="", encoding="utf-8-sig") as f:
        writer = csv.DictWriter(f, fieldnames=fieldnames, extrasaction="ignore")
        writer.writeheader()
        for p in products:
            writer.writerow(p)
    return str(path)


# ── CLI ───────────────────────────────────────────────────────────────────
if __name__ == "__main__":
    parser = argparse.ArgumentParser(description="Watsons TH + Shopee TH pricing via Apify (pricing-only, no LLM)")
    parser.add_argument("--config", default=CONFIG_PATH)
    parser.add_argument("--site", nargs="+", choices=["watsons_th", "shopee_th"], default=["watsons_th", "shopee_th"])
    parser.add_argument("--brand", nargs="+", help='e.g. --brand "Acne-Aid"')
    parser.add_argument("--skus", help="Path to CSV with columns acne_aid_sku,priority,query "
                                        "(e.g. skus_shopee_full.csv) -- SKU-targeted Shopee search, "
                                        "overrides --brand for shopee_th only")
    parser.add_argument("--max-items", type=int, default=20, help="Per-brand item cap per site")
    parser.add_argument("--dry-run", action="store_true",
                         help="Dump raw Apify output to output/apify_raw_*.json and print parsed rows, but do NOT write to the DB")
    args = parser.parse_args()

    token = os.getenv("APIFY_TOKEN")
    if not token:
        log.error("APIFY_TOKEN not set in .env")
        raise SystemExit(1)

    with open(args.config, encoding="utf-8") as f:
        config = yaml.safe_load(f)

    all_products: List[dict] = []
    if "watsons_th" in args.site:
        all_products += discover_watsons_th_apify(
            config, token, brand_filter=args.brand, max_items=args.max_items, dry_run=args.dry_run
        )
    shopee_sku_products: List[dict] = []
    if "shopee_th" in args.site:
        if args.skus:
            sku_rows = load_sku_queries(args.skus)
            shopee_sku_products = discover_shopee_th_by_sku(
                config, token, sku_rows, max_items=args.max_items, dry_run=args.dry_run
            )
            all_products += shopee_sku_products
        else:
            all_products += discover_shopee_th_apify(
                config, token, brand_filter=args.brand, max_items=args.max_items, dry_run=args.dry_run
            )

    if args.dry_run:
        log.info(f"[DRY-RUN] Parsed {len(all_products)} rows (not written to DB):")
        for p in all_products:
            log.info(f"  {p['site']:12} | {p['brand']:15} | {p['sell_price']!s:>10} THB | {p['name_th_or_en']}")
        raise SystemExit(0)

    out_dir = config.get("output", {}).get("directory", "output")
    db_path = f"{out_dir}/acneaid_th.db"
    conn = open_db(db_path)
    lock = threading.Lock()
    ensure_price_history_table(conn)
    n_new = save_products(conn, all_products, lock)
    log.info(f"[DB] {n_new} new products inserted ({len(all_products)} total rows processed)")
    n_hist = save_price_history(conn, all_products, lock)
    log.info(f"[DB] {n_hist} price history rows inserted")
    n_hist_csv = export_price_history_csv(conn, out_dir)
    log.info(f"[EXPORT] acneaid_th_price_history.csv: {n_hist_csv} rows")

    counts = export_csvs(db_path, out_dir, args.config)
    log.info(f"[EXPORT] {counts}")

    if shopee_sku_products:
        sku_csv_path = export_sku_targeted_csv(shopee_sku_products, out_dir)
        log.info(f"[EXPORT] {sku_csv_path}: {len(shopee_sku_products)} rows")
