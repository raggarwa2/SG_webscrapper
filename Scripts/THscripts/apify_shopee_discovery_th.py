#!/usr/bin/env python3
"""
apify_shopee_discovery_th.py

Fills the gaps in sku_query_master_shopee_mapped.csv -- queries from the
91-row master list (sku_competitor_map.py, via build_sku_query_master.py)
that had ZERO matched Shopee URLs when joined against the existing
acneaid_th_pricing_shopee_only.csv scrape. Confirmed 8 such gaps
(2026-08-07): mostly Micellar Water (Eucerin/Bifesta/CeraVe) and one
Smooth E / one Neutrogena cell.

WHY A SEPARATE DISCOVERY STEP: those 8 gaps might mean "never scraped"
(the existing Shopee pull just didn't happen to search for that exact
product) or "doesn't exist on Shopee" (the SKU/competitor cell genuinely
isn't listed there). There's no way to tell those apart without actually
searching -- so this runs a real keyword search per gap query using the
cheap gio21/shopee-scraper actor (same one apify_pricing_th.py already
uses for pricing, ~$2.99/1,000 results) BEFORE the review script spends
its per-review-actor budget ($7.99/1k products + $3.99/1k reviews) on
something that might not exist at all.

Matching a returned item to the expected product_name uses the same
word-overlap heuristic as the earlier coverage check (>=50% of
significant words present) -- NOT the project's full match_competitor_rows()
logic (pack size, bundle/format-word guards). Treat a "found" match here
as a candidate to spot-check, not a locked mapping -- same caveat already
flagged when sku_query_master_shopee_mapped.csv was first built.

Usage:
    # quick test today -- dry-run, just prints what each gap query returns
    python apify_shopee_discovery_th.py --dry-run

    # real run -- updates sku_query_master_shopee_mapped.csv in place
    # (backs up the existing file first, never overwrites blind)
    python apify_shopee_discovery_th.py --max-items 10
"""
from __future__ import annotations

import os
import re
import sys
import csv
import json
import time
import shutil
import logging
import argparse
from datetime import datetime, timezone
from pathlib import Path
from typing import List

import requests
from dotenv import load_dotenv

load_dotenv()

APIFY_BASE = "https://api.apify.com/v2"
ACTOR_ID = "gio21/shopee-scraper"  # same cheap keyword-search actor apify_pricing_th.py uses for pricing

os.makedirs("output", exist_ok=True)
LOG_PATH = f"output/apify_discovery_{datetime.now().strftime('%Y%m%d_%H%M')}.log"
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
    """Same >=50%-significant-word heuristic used to build the coverage
    check -- a lightweight filter, not the project's full matcher."""
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


def backup_if_exists(path: Path) -> None:
    if not path.exists():
        return
    stamp = datetime.now().strftime("%Y%m%d_%H%M%S")
    backup_path = path.parent / f"{path.stem}_BACKUP_{stamp}{path.suffix}"
    shutil.copy2(path, backup_path)
    log.info(f" [backup] {path.name} -> {backup_path.name}")


def main():
    parser = argparse.ArgumentParser(description="Fill gap queries in the Shopee master-mapped file via keyword discovery")
    parser.add_argument("--master", default="sku_query_master_shopee_mapped.csv")
    parser.add_argument("--max-items", type=int, default=10, help="Max results per keyword search")
    parser.add_argument("--dry-run", action="store_true",
                         help="Print what each gap query returns, do NOT update the master file")
    args = parser.parse_args()

    token = os.getenv("APIFY_TOKEN")
    if not token:
        log.error("APIFY_TOKEN not set in .env")
        raise SystemExit(1)

    master_path = Path(args.master)
    with open(master_path, encoding="utf-8-sig", newline="") as f:
        rows = list(csv.DictReader(f))

    gap_rows = [r for r in rows if int(r.get("n_shopee_matches", 0) or 0) == 0]
    log.info(f"Found {len(gap_rows)} gap queries with zero matched URLs in {master_path.name}")

    updated = 0
    for r in gap_rows:
        label = f"{r['brand']}:{r['sku_key']}"
        log.info(f"[DISCOVER] {label} | query: {r['query']}")
        try:
            items = apify_run(
                token, ACTOR_ID,
                {"keywords": [r["query"]], "country": "TH", "maxItems": args.max_items},
                label,
            )
        except Exception as e:
            log.warning(f" {label}: {e}")
            continue

        if args.dry_run:
            log.info(f" [DRY-RUN] {len(items)} raw items returned for '{r['query']}':")
            for it in items[:5]:
                name = _pick(it, "name", "title", "productName", default="?")
                log.info(f"   - {name}")
            continue

        matched_urls = find_best_match_urls(items, r["product_name"])
        if matched_urls:
            r["n_shopee_matches"] = str(len(matched_urls))
            r["shopee_urls"] = " | ".join(matched_urls)
            updated += 1
            log.info(f" -> {len(matched_urls)} candidate URL(s) found for {label}")
        else:
            log.info(f" -> still 0 matches for {label} (searched, genuinely not found on Shopee)")
        time.sleep(1.5)

    if args.dry_run:
        log.info("[DRY-RUN] No file updates written.")
        raise SystemExit(0)

    backup_if_exists(master_path)
    with open(master_path, "w", newline="", encoding="utf-8") as f:
        writer = csv.DictWriter(f, fieldnames=[
            "sku_key", "priority", "brand", "product_name", "query",
            "n_shopee_matches", "shopee_urls",
        ])
        writer.writeheader()
        writer.writerows(rows)

    log.info(f"[EXPORT] {master_path}: {updated}/{len(gap_rows)} gap queries resolved, file updated in place")


if __name__ == "__main__":
    main()
