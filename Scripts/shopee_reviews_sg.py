#!/usr/bin/env python3
"""
shopee_reviews_sg.py -- Shopee Singapore REVIEW text via Apify.

Ported from apify_shopee_reviews_th.py (Acne-Aid / Thailand project) per
the SG scraping plan (Phase 2). The actor choice and confirmed
input/output field schema below are the TH script's directly-reusable
groundwork (per the plan) -- only TRACKED_BRANDS, the input file default,
and the output filename/channel label changed for SG.

ACTOR (confirmed on TH data, 2026-08-07 -- see apify_shopee_reviews_th.py's
own header for the two-actors-tried history): zen-studio/shopee-product-
reviews-scraper. Every review lands as its own row in the run's ordinary
DEFAULT dataset (itemId/shopId included on each review row for joining
back to product data) -- no hidden sub-dataset.

CONFIRMED INPUT SCHEMA (via the actor's own listing):
    Required: startUrls        -- list of {"url": "..."} objects (Apify's
                                   standard start-URL format -- NOT bare
                                   strings; confirmed via a real 400 error
                                   on the TH side, same convention applies
                                   here)
    Optional: starFilter       -- "all" or 1-5
              contentFilter    -- all / with comments / with media / local
              maxReviewsPerProduct -- default 1000; set explicitly to
                                   control cost (0 = full history, up to
                                   ~14,000 on very popular products)

OUTPUT FIELDS (27 per review, one row per review): reviewId, itemId,
shopId, ratingStar, comment, createdAt, editedAt, author, authorId,
authorPortrait, authorLoyaltyTier, isAnonymous, isRepeatPurchase,
likeCount, status, region, detailedRating, variations, images, videos,
shopReply, followUp, templateTags, overallFit, sizeInfoTags,
authorMeasurements, scrapedAt.

CONFIRMED PRICING (TH data): $3.99 per 1,000 reviews (Apify's Free plan
rate; less on paid Apify plans -- Bronze $3.79, Silver $3.29, Gold+ $2.99).
No separate per-product charge -- this actor only bills for reviews.

Input item list: read from sku_query_master_shopee_mapped_sg.csv, written
by shopee_discovery_sg.py -- the SG SKU list already joined against real
Shopee URLs. This is the coverage FRAME, not the raw scrape result -- a
query with zero matched URLs is a visible gap (logged as a warning), not
silently absent.

Output file: output/shopee_singapore_reviews_<YYYYMMDD>.csv -- dated so a
later run doesn't silently overwrite an earlier one; also carries
sku_key/priority/query through from the master list for traceability back
to a specific competitive-set cell.

Usage:
    # quick test today -- 5 items, dumps raw output, does NOT save
    python shopee_reviews_sg.py --max-items 5 --dry-run

    # full run once field names are confirmed against real SG data
    python shopee_reviews_sg.py --max-reviews-per-product 100
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
from datetime import datetime, timezone
from pathlib import Path
from typing import Optional, List

import requests
from dotenv import load_dotenv

load_dotenv()

APIFY_BASE = "https://api.apify.com/v2"
ACTOR_ID = "zen-studio/shopee-product-reviews-scraper"

# MyACUVUE-ecosystem brands, per sku_query_master_sg.csv / context.md's
# Competitors Studied section. "Mixed" covers the brand-agnostic grey-market
# sweep row (generic_powered_cosmetic_lens).
TRACKED_BRANDS = {
    "ACUVUE", "Alcon", "CooperVision", "Bausch & Lomb", "Olens", "Mixed",
}

os.makedirs("output", exist_ok=True)
LOG_PATH = f"output/shopee_reviews_sg_{datetime.now().strftime('%Y%m%d_%H%M')}.log"
logging.basicConfig(
    level=logging.INFO,
    format="%(asctime)s [%(levelname)s] %(message)s",
    handlers=[logging.FileHandler(LOG_PATH, encoding="utf-8"), logging.StreamHandler(sys.stdout)],
)
log = logging.getLogger(__name__)


# ── Apify run/poll/fetch -- identical shape to apify_pricing_th.py ────────
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
    for attempt in range(90):  # 90 x 10s = 15 min
        time.sleep(10)
        status = requests.get(status_url, params={"token": token}, timeout=15).json()["data"]["status"]
        log.info(f" [{label}] status: {status} (attempt {attempt + 1})")
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
    log.info(f" [{label}] retrieved {len(items)} items")
    return items


def _pick(d: dict, *keys: str, default=None):
    """Same fallback-key helper as apify_pricing_th.py -- actor output
    field names are unconfirmed against SG data until a dry-run checks them."""
    for k in keys:
        v = d.get(k)
        if v not in (None, ""):
            return v
    return default


def _dump_raw(label: str, items: list[dict]) -> None:
    path = f"output/apify_raw_reviews_sg_{re.sub(r'[^\\w]+', '_', label)}.json"
    with open(path, "w", encoding="utf-8") as f:
        json.dump(items[:5], f, ensure_ascii=False, indent=2)
    log.info(f" Raw sample (first 5 of {len(items)}) written to {path}")


# ── Item list loader -- reads sku_query_master_shopee_mapped_sg.csv (built
# by shopee_discovery_sg.py), NOT a raw scrape CSV directly. Explodes its
# pipe-separated `shopee_urls` column to one row per URL so each gets its
# own actor call, carrying sku_key/priority/query through for provenance.
# Queries with 0 matched URLs are skipped (nothing to review-scrape) but
# stay visible via the loader's logged gap count.
def load_item_urls(path: Path) -> List[dict]:
    with open(path, encoding="utf-8-sig", newline="") as f:
        rows = list(csv.DictReader(f))
    out = []
    n_gaps = 0
    for r in rows:
        brand = r.get("brand", "")
        urls_field = (r.get("shopee_urls") or "").strip()
        if brand not in TRACKED_BRANDS or not urls_field:
            if brand in TRACKED_BRANDS:
                n_gaps += 1
            continue
        for url in [u.strip() for u in urls_field.split("|") if u.strip()]:
            out.append({
                "brand": brand,
                "url": url,
                "sku_key": r.get("sku_key", ""),
                "priority": r.get("priority", ""),
                "query": r.get("query", ""),
            })
    if n_gaps:
        log.warning(f" {n_gaps} queries in {path.name} have zero matched Shopee URLs -- "
                    f"skipped here, not silently substituted with anything else")
    # dedupe by url
    seen = set()
    deduped = []
    for r in out:
        if r["url"] not in seen:
            seen.add(r["url"])
            deduped.append(r)
    return deduped


# ── Review field extraction -- CONFIRMED field names on TH data (actor's
# own listing). Unlike zen-studio/shopee-product-detail-scraper, each
# dataset item here IS a review row directly -- no nesting to unwrap.
# itemId/shopId are present on every review row already, for joining back
# to pricing data.
def extract_review_rows(review_item: dict, brand: str, now: str, sku_key: str = "", priority: str = "", query: str = "") -> List[dict]:
    text = _pick(review_item, "comment", default="")
    if not text:
        return []
    return [{
        "brand": brand,
        "sku_key": sku_key,
        "priority": priority,
        "query": query,
        "item_id": _pick(review_item, "itemId"),
        "shop_id": _pick(review_item, "shopId"),
        "review_id": _pick(review_item, "reviewId"),
        "rating": _pick(review_item, "ratingStar"),
        "review_date": _pick(review_item, "createdAt"),
        "review_text": text,
        "reviewer_name": _pick(review_item, "author"),
        "like_count": _pick(review_item, "likeCount"),
        "variation": _pick(review_item, "variations"),
        "scraped_at": now,
    }]


def main():
    parser = argparse.ArgumentParser(description="Shopee SG review scrape via Apify")
    parser.add_argument("--actor", default=ACTOR_ID, help="Apify actor id, e.g. zen-studio/shopee-product-reviews-scraper")
    parser.add_argument("--items", default="sku_query_master_shopee_mapped_sg.csv",
                         help="CSV mapping the SG SKU master list to real Shopee URLs "
                              "(sku_key,priority,brand,product_name,query,n_shopee_matches,shopee_urls), "
                              "written by shopee_discovery_sg.py")
    parser.add_argument("--max-items", type=int, default=0,
                         help="Cap how many item URLs to send this run (0 = all). Use a small number for a first test.")
    parser.add_argument("--max-reviews-per-product", type=int, default=100)
    parser.add_argument("--dry-run", action="store_true",
                         help="Dump raw Apify output to output/apify_raw_reviews_sg_*.json, do NOT write a CSV")
    args = parser.parse_args()

    token = os.getenv("APIFY_TOKEN")
    if not token:
        log.error("APIFY_TOKEN not set in .env")
        raise SystemExit(1)

    items_path = Path(args.items)
    if not items_path.exists():
        log.error(f"Item list not found: {items_path}. Run shopee_discovery_sg.py first to build it.")
        raise SystemExit(1)

    item_urls = load_item_urls(items_path)
    if args.max_items:
        item_urls = item_urls[: args.max_items]
    log.info(f"Loaded {len(item_urls)} tracked-brand item URLs from {items_path.name}")

    now = datetime.now(timezone.utc).isoformat()
    all_rows: List[dict] = []

    # One actor call per item URL keeps brand attribution simple and exact --
    # no batching ambiguity about which review belongs to which brand.
    for row in item_urls:
        label = f"{row['brand']}:{row['url'][-20:]}"
        try:
            items = apify_run(
                token, args.actor,
                {
                    "startUrls": [{"url": row["url"]}],
                    "maxReviewsPerProduct": args.max_reviews_per_product,
                },
                label,
            )
        except Exception as e:
            log.warning(f" {label}: {e}")
            continue

        if args.dry_run:
            _dump_raw(label, items)
            continue

        for it in items:
            all_rows.extend(extract_review_rows(
                it, row["brand"], now,
                sku_key=row.get("sku_key", ""), priority=row.get("priority", ""), query=row.get("query", ""),
            ))

    if args.dry_run:
        log.info("[DRY-RUN] Raw samples written per item. Check field names before a full run.")
        raise SystemExit(0)

    out_path = Path("output") / f"shopee_singapore_reviews_{datetime.now().strftime('%Y%m%d')}.csv"
    fieldnames = ["brand", "sku_key", "priority", "query", "item_id", "shop_id", "review_id",
                  "rating", "review_date", "review_text", "reviewer_name", "like_count",
                  "variation", "scraped_at"]
    with open(out_path, "w", newline="", encoding="utf-8-sig") as f:
        writer = csv.DictWriter(f, fieldnames=fieldnames)
        writer.writeheader()
        writer.writerows(all_rows)

    log.info(f"[EXPORT] {out_path}: {len(all_rows)} review rows")
    from collections import Counter
    for brand, n in Counter(r["brand"] for r in all_rows).most_common():
        log.info(f"  {brand}: {n}")


if __name__ == "__main__":
    main()
