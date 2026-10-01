#!/usr/bin/env python3
"""
shopee_discovery_sg.py

Discovery step for Shopee Singapore: runs one keyword search per query in
sku_query_master_sg.csv via the Apify actor "gio21/shopee-scraper" (the
same cheap keyword-search actor apify_pricing_th.py used for Shopee TH
pricing), matches results back to each query's product_name, and writes a
mapped CSV (sku_query_master_shopee_mapped_sg.csv) carrying the matched
product URLs. That mapped file is the input shopee_reviews_sg.py expects.

WHY A SEPARATE DISCOVERY STEP (same reasoning as apify_shopee_discovery_th.py
/ apify_shopee_reviews_th.py on the TH side): review-pulling actors bill
per review ($3.99/1,000 via zen-studio/shopee-product-reviews-scraper) and
need a real product URL as input, not a keyword. Running the cheap
discovery actor first (gio21/shopee-scraper, ~$2.99/1,000 results) to find
the URLs -- and skipping queries with zero matches -- avoids spending
review-actor budget on products that don't exist on Shopee SG at all.

UNLIKE apify_pricing_th.py's discover_shopee_th_by_sku(): this script does
NOT import from pipeline_th.py / read config_th.yaml. Those are TH-project
infra (Acne-Aid classification, Watsons TH helpers) with no SG equivalent
per the plan's scope note -- this is a standalone port of just the Shopee
actor-call + matching pattern, not the shared pipeline module.

Matching a returned item to the expected product_name uses the same
word-overlap heuristic as apify_shopee_discovery_th.py (>=50% of
significant words present) -- a lightweight filter, not a strict matcher.
Treat a "found" match as a candidate to spot-check, not a locked mapping.

NOT YET VERIFIED FOR SG: gio21/shopee-scraper's "country" param accepting
"SG" (TH runs used "TH"; Shopee Singapore is shopee.sg). Confirm with a
small --dry-run / --max-items test before a full run -- see this project's
plan doc, Verification approach.

Usage:
    # quick test today -- dry-run, just prints what each query returns
    python shopee_discovery_sg.py --dry-run --max-items 5

    # real run -- writes sku_query_master_shopee_mapped_sg.csv
    python shopee_discovery_sg.py --max-items 10
"""
from __future__ import annotations

import os
import re
import sys
import csv
import json
import time
import logging
import argparse
from datetime import datetime
from pathlib import Path
from typing import List

import requests
from dotenv import load_dotenv

load_dotenv()

APIFY_BASE = "https://api.apify.com/v2"
ACTOR_ID = "gio21/shopee-scraper"
# CONFIRMED (SG test run, 2026-09-24): the actor rejects maxItems < 10 with
# a 400 ("Field input.maxItems must be >= 10") -- same style of minimum as
# fatihtahta/lazada-scraper's MIN_LIMIT in lazada_pricing_sg.py, just not
# documented anywhere in apify_shopee_discovery_th.py's TH-side usage.
MIN_MAX_ITEMS = 10

os.makedirs("output", exist_ok=True)
LOG_PATH = f"output/shopee_discovery_sg_{datetime.now().strftime('%Y%m%d_%H%M')}.log"
logging.basicConfig(
    level=logging.INFO,
    format="%(asctime)s [%(levelname)s] %(message)s",
    handlers=[logging.FileHandler(LOG_PATH, encoding="utf-8"), logging.StreamHandler(sys.stdout)],
)
log = logging.getLogger(__name__)


def apify_run(token: str, actor_id: str, run_input: dict, label: str) -> list[dict]:
    actor_slug = actor_id.replace("/", "~")
    r = requests.post(
        f"{APIFY_BASE}/acts/{actor_slug}/runs",
        json=run_input,
        params={"token": token},
        timeout=30,
    )
    if not r.ok:
        log.error(f" [{label}] Apify error body: {r.text[:500]}")
    r.raise_for_status()
    run_info = r.json()["data"]
    run_id, dataset_id = run_info["id"], run_info["defaultDatasetId"]
    log.info(f" [{label}] Apify run started -> run_id={run_id}")

    status_url = f"{APIFY_BASE}/actor-runs/{run_id}"
    for attempt in range(60):  # 60 x 10s = 10 min, keyword search is fast
        time.sleep(10)
        status = requests.get(status_url, params={"token": token}, timeout=15).json()["data"]["status"]
        log.info(f" [{label}] status: {status} (attempt {attempt + 1})")
        if status == "SUCCEEDED":
            break
        if status in ("FAILED", "ABORTED", "TIMED-OUT"):
            raise RuntimeError(f"Apify run {run_id} ended with: {status}")
    else:
        raise TimeoutError(f"Apify run {run_id} did not finish in 10 minutes")

    items_r = requests.get(
        f"{APIFY_BASE}/datasets/{dataset_id}/items",
        params={"token": token, "format": "json"},
        timeout=60,
    )
    items_r.raise_for_status()
    items = items_r.json()
    log.info(f" [{label}] retrieved {len(items)} items")
    return items


def _pick(d: dict, *keys: str, default=None):
    for k in keys:
        v = d.get(k)
        if v not in (None, ""):
            return v
    return default


def _normalize_words(text: str) -> list[str]:
    text = re.sub(r"[^a-z0-9]+", " ", text.lower())
    return [w for w in text.split() if w]


def find_best_match_urls(items: list[dict], product_name: str) -> List[str]:
    """Same >=50%-significant-word heuristic as apify_shopee_discovery_th.py
    -- a lightweight filter, not the project's full matcher."""
    sig_words = [w for w in _normalize_words(product_name) if len(w) >= 3 and not w.isdigit()]
    if not sig_words:
        return []
    min_hits = max(1, -(-len(sig_words) * 5 // 10))  # ceil(50%)

    matched_urls = []
    for it in items:
        name = _pick(it, "name", "title", "productName", default="")
        url = _pick(it, "url", "itemUrl", "link", default="")
        if not name or not url:
            continue
        squashed = "".join(_normalize_words(name))
        hits = sum(1 for w in sig_words if w in squashed)
        if hits >= min_hits:
            matched_urls.append(url)
    return matched_urls


def load_sku_list(path: Path) -> List[dict]:
    with open(path, encoding="utf-8-sig", newline="") as f:
        rows = list(csv.DictReader(f))
    return [r for r in rows if (r.get("query") or "").strip()]


def main():
    parser = argparse.ArgumentParser(description="Shopee SG discovery: keyword-search sku_query_master_sg.csv, write matched-URL CSV")
    parser.add_argument("--skus", default="sku_query_master_sg.csv",
                         help="Path to the SKU_query_master CSV (same file lazada_pricing_sg.py reads)")
    parser.add_argument("--out", default="sku_query_master_shopee_mapped_sg.csv",
                         help="Output CSV path (input for shopee_reviews_sg.py)")
    parser.add_argument("--max-items", type=int, default=10, help="Max results per keyword search")
    parser.add_argument("--max-queries", type=int, default=0,
                         help="Cap how many SKU rows to search this run (0 = all). Use a small number "
                              "for a first test -- each query is a separate paid actor call.")
    parser.add_argument("--dry-run", action="store_true",
                         help="Print what each query returns, do NOT write the mapped CSV")
    args = parser.parse_args()

    if args.max_items < MIN_MAX_ITEMS:
        log.error(f"--max-items {args.max_items} is below the actor's confirmed minimum of "
                  f"{MIN_MAX_ITEMS} (rejected with a 400 error). Use --max-items {MIN_MAX_ITEMS} or higher.")
        raise SystemExit(1)

    token = os.getenv("APIFY_TOKEN")
    if not token:
        log.error("APIFY_TOKEN not set in .env")
        raise SystemExit(1)

    sku_path = Path(args.skus)
    if not sku_path.exists():
        log.error(f"SKU list not found: {sku_path}")
        raise SystemExit(1)

    sku_rows = load_sku_list(sku_path)
    if args.max_queries:
        sku_rows = sku_rows[: args.max_queries]
    log.info(f"Loaded {len(sku_rows)} queries from {sku_path.name}")

    out_rows = []
    n_matched = 0
    for r in sku_rows:
        label = f"{r['brand']}:{r['sku_key']}"
        log.info(f"[DISCOVER] {label} | query: {r['query']}")
        try:
            items = apify_run(
                token, ACTOR_ID,
                {"keywords": [r["query"]], "country": "SG", "maxItems": args.max_items},
                label,
            )
        except Exception as e:
            log.warning(f" {label}: {e}")
            items = []

        if args.dry_run:
            log.info(f" [DRY-RUN] {len(items)} raw items returned for '{r['query']}':")
            for it in items[:5]:
                name = _pick(it, "name", "title", "productName", default="?")
                log.info(f"   - {name}")
            time.sleep(1.5)
            continue

        matched_urls = find_best_match_urls(items, r["product_name"])
        if matched_urls:
            n_matched += 1
            log.info(f" -> {len(matched_urls)} candidate URL(s) found for {label}")
        else:
            log.info(f" -> 0 matches for {label}")

        out_rows.append({
            "sku_key": r["sku_key"],
            "priority": r["priority"],
            "brand": r["brand"],
            "product_name": r["product_name"],
            "query": r["query"],
            "n_shopee_matches": str(len(matched_urls)),
            "shopee_urls": " | ".join(matched_urls),
        })
        time.sleep(1.5)

    if args.dry_run:
        log.info("[DRY-RUN] No file written.")
        raise SystemExit(0)

    out_path = Path(args.out)
    with open(out_path, "w", newline="", encoding="utf-8") as f:
        writer = csv.DictWriter(f, fieldnames=[
            "sku_key", "priority", "brand", "product_name", "query",
            "n_shopee_matches", "shopee_urls",
        ])
        writer.writeheader()
        writer.writerows(out_rows)

    log.info(f"[EXPORT] {out_path}: {n_matched}/{len(sku_rows)} queries matched, file written")


if __name__ == "__main__":
    main()
