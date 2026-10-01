"""
tiktok_reviews_sg.py

TikTok Shop (Singapore) REVIEW text pull -- sibling to tiktok_pipeline_sg.py,
same relationship apify_shopee_reviews_th.py has to apify_pricing_th.py in
the Thailand project: the pricing pipeline only ever pulls product/price
fields (confirmed 2026-09-24 -- tiktok_pipeline_sg.py's PriceRecord schema
and every tiktok_shop_sg_*.jsonl pull to date have zero review/comment
text), this script fills that gap.

ACTOR: maximedupre/tiktok-shop-reviews-scraper -- a dedicated TikTok Shop
review actor, confirmed (via the actor's own Apify listing, 2026-09-24) to:
  - take `productTargets`: an array of TikTok Shop product URLs or numeric
    product IDs (1-500 per run) -- exactly the `sku_url` values already
    sitting in data/tiktok_shop_sg/tiktok_shop_sg_*.jsonl from the pricing
    pipeline, so no new product-discovery step is needed here.
  - support `storefront: "SG"` directly (one of 9 markets: US/GB/SG/MY/
    PH/TH/VN/ID/JP/MX) -- unlike the pricing actor, no unverified
    country_code guess involved.
  - return one row per review with: product{id,name,url,overallRating,...},
    rating, text, publishedAt, media[], reviewer{name,accountId,
    avatarUrl,country}, purchase{isVerifiedPurchase,isIncentivized},
    variant{sku,name,attributes}. Confirmed via the actor's published
    schema, NOT yet verified against a live SG dry-run -- run --dry-run
    first and inspect data/tiktok_shop_sg/tiktok_raw_reviews_*.json before
    trusting field names on a full pull (same discipline as the pricing
    pipeline's TIKTOK_ACTOR caveat).

Source of product URLs: this script does NOT re-discover products. It reads
every tiktok_shop_sg_*.jsonl file already written by tiktok_pipeline_sg.py
and takes the latest-pulled_at sku_url per (brand, sku_url), so review
coverage always matches whatever the pricing pipeline has actually found.
Run tiktok_pipeline_sg.py first (or at least once) before this script has
anything to review-scrape.

Standing principles this pipeline must respect (see context.md, and the
header of tiktok_pipeline_sg.py):
  - Multi-timestamp pulls -- never overwrite, append-only, timestamped.
  - External-only data.
  - Keep this file and its outputs in THIS project only.

Usage:
    # quick test -- 1 product per brand, dumps raw output, does NOT save
    python tiktok_reviews_sg.py --max-products-per-brand 1 --dry-run

    # full run once field names are confirmed against a real dry-run
    python tiktok_reviews_sg.py --review-limit 50

    python tiktok_reviews_sg.py --export-csv
"""

from __future__ import annotations

import os
import json
import csv
import time
import hashlib
import logging
import argparse
import sqlite3
from dataclasses import dataclass, field, asdict, fields
from datetime import datetime, timezone
from pathlib import Path
from typing import Optional

import requests
from dotenv import load_dotenv

load_dotenv()

logging.basicConfig(level=logging.INFO, format="%(asctime)s | %(levelname)s | %(message)s")
log = logging.getLogger("tiktok_reviews_sg")

APIFY_BASE = "https://api.apify.com/v2"
REVIEWS_ACTOR = "maximedupre/tiktok-shop-reviews-scraper"


# ---------------------------------------------------------------------------
# 1. Config
# ---------------------------------------------------------------------------

@dataclass
class ReviewPipelineConfig:
    market: str = "SG"
    storefront: str = "SG"
    source: str = "tiktok_shop"
    output_dir: Path = Path("./data/tiktok_shop_sg")  # same dir as tiktok_pipeline_sg.py -- reviews join pricing by sku_url
    request_delay_seconds: float = 2.5
    review_limit: Optional[int] = 100  # None = all available reviews (actor default) -- costs more, set explicitly
    star_rating_filter: str = "any"


# ---------------------------------------------------------------------------
# 2. Normalized record
# ---------------------------------------------------------------------------

@dataclass
class ReviewRecord:
    record_id: str            # stable hash -- see _make_review_id()
    source: str                 # "tiktok_shop"
    market: str
    brand: str
    product_id: Optional[str]
    product_url: str
    product_name: Optional[str]
    rating: Optional[int]        # 1-5
    review_text: Optional[str]
    review_date_utc: Optional[str]   # publishedAt, as returned by the actor
    reviewer_name: Optional[str]
    reviewer_country: Optional[str]
    is_verified_purchase: Optional[bool]
    has_media: bool
    variant_sku: Optional[str]
    pulled_at_utc: str


# ---------------------------------------------------------------------------
# 2.5 Scraped-source tracking -- reuses the same scraped_sources.db file
#    tiktok_pipeline_sg.py already writes to this output_dir, but its own
#    table (review_scraped_sources), keyed by product_url not brand/term --
#    reviews are pulled per-product, pricing per-search-term, so the units
#    of "already scraped" differ and must not collide.
# ---------------------------------------------------------------------------

_REVIEW_SCRAPED_SCHEMA = """
CREATE TABLE IF NOT EXISTS review_scraped_sources (
    market          TEXT NOT NULL,
    product_url     TEXT NOT NULL,
    last_scraped_at TEXT NOT NULL,
    reviews_found   INTEGER,
    PRIMARY KEY (market, product_url)
);
"""


def open_scraped_db(cfg: ReviewPipelineConfig) -> sqlite3.Connection:
    cfg.output_dir.mkdir(parents=True, exist_ok=True)
    conn = sqlite3.connect(cfg.output_dir / "scraped_sources.db", timeout=60)
    conn.execute("PRAGMA journal_mode=WAL")
    conn.executescript(_REVIEW_SCRAPED_SCHEMA)
    conn.commit()
    return conn


def get_scraped_product_urls(conn: sqlite3.Connection, market: str) -> set:
    return {
        row[0]
        for row in conn.execute(
            "SELECT product_url FROM review_scraped_sources WHERE market = ?", (market,)
        )
    }


def mark_product_scraped(conn: sqlite3.Connection, market: str, product_url: str, reviews_found: int) -> None:
    conn.execute(
        """INSERT INTO review_scraped_sources (market, product_url, last_scraped_at, reviews_found)
           VALUES (?, ?, ?, ?)
           ON CONFLICT(market, product_url)
           DO UPDATE SET last_scraped_at = excluded.last_scraped_at, reviews_found = excluded.reviews_found""",
        (market, product_url, datetime.now(timezone.utc).isoformat(), reviews_found),
    )
    conn.commit()


# ---------------------------------------------------------------------------
# 3. Product-URL sourcing -- read what tiktok_pipeline_sg.py already found,
#    do NOT re-discover products here.
# ---------------------------------------------------------------------------

def load_product_urls_from_pricing(cfg: ReviewPipelineConfig) -> dict[str, list[dict]]:
    """Scans every tiktok_shop_sg_*.jsonl in cfg.output_dir (written by
    tiktok_pipeline_sg.py) and returns {brand: [{"url":..., "name":...}]},
    deduped to the LATEST pulled_at_utc row per (brand, sku_url) -- a
    product can appear in several timestamped pricing pulls, we only need
    one review-scrape target per product, not one per historical price
    snapshot.
    """
    jsonl_files = sorted(cfg.output_dir.glob("tiktok_shop_sg_*.jsonl"))
    if not jsonl_files:
        log.warning(f"No tiktok_shop_sg_*.jsonl pricing pulls found in {cfg.output_dir} -- "
                    f"run tiktok_pipeline_sg.py first, there is nothing to review-scrape yet.")
        return {}

    latest: dict[tuple[str, str], dict] = {}  # (brand, sku_url) -> row
    for jf in jsonl_files:
        with jf.open("r", encoding="utf-8") as f:
            for line in f:
                line = line.strip()
                if not line:
                    continue
                row = json.loads(line)
                url = row.get("sku_url")
                brand = row.get("brand")
                if not url or not brand:
                    continue
                key = (brand, url)
                if key not in latest or row.get("pulled_at_utc", "") > latest[key].get("pulled_at_utc", ""):
                    latest[key] = row

    by_brand: dict[str, list[dict]] = {}
    for (brand, url), row in latest.items():
        by_brand.setdefault(brand, []).append({"url": url, "name": row.get("product_name_raw", "")})
    return by_brand


# ---------------------------------------------------------------------------
# 4. Fetch layer
# ---------------------------------------------------------------------------

def _pick(d: dict, *keys: str, default=None):
    for k in keys:
        v = d.get(k)
        if v not in (None, ""):
            return v
    return default


def _apify_run(token: str, actor_id: str, run_input: dict, label: str) -> list[dict]:
    """Same run/poll/fetch shape as tiktok_pipeline_sg.py's _apify_run."""
    actor_slug = actor_id.replace("/", "~")
    auth = {"Authorization": f"Bearer {token}"}
    r = requests.post(
        f"{APIFY_BASE}/acts/{actor_slug}/runs",
        json=run_input,
        headers=auth,
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
        status = requests.get(status_url, headers=auth, timeout=15).json()["data"]["status"]
        log.info(f"  [{label}] status: {status} (attempt {attempt + 1})")
        if status == "SUCCEEDED":
            break
        if status in ("FAILED", "ABORTED", "TIMED-OUT"):
            raise RuntimeError(f"Apify run {run_id} ended with: {status}")
    else:
        raise TimeoutError(f"Apify run {run_id} did not finish in 15 minutes")

    items_r = requests.get(
        f"{APIFY_BASE}/datasets/{dataset_id}/items",
        params={"format": "json"},
        headers=auth,
        timeout=60,
    )
    items_r.raise_for_status()
    items = items_r.json()
    log.info(f"  [{label}] retrieved {len(items)} items")
    return items


def _dump_raw(brand: str, items: list[dict], cfg: ReviewPipelineConfig) -> None:
    cfg.output_dir.mkdir(parents=True, exist_ok=True)
    path = cfg.output_dir / f"tiktok_raw_reviews_{brand.replace(' ', '_')}.json"
    with path.open("w", encoding="utf-8") as f:
        json.dump(items[:5], f, ensure_ascii=False, indent=2)
    log.info(f"  Raw sample (first 5 of {len(items)}) written to {path}")


def fetch_reviews_for_brand(
    brand: str, products: list[dict], cfg: ReviewPipelineConfig, token: str,
    dry_run: bool = False,
    scraped_conn: Optional[sqlite3.Connection] = None,
    already_scraped: Optional[set] = None,
    force_rescrape: bool = False,
) -> list[dict]:
    """One Apify call per brand, batching every not-yet-scraped product URL
    for that brand into a single `productTargets` list (actor accepts up to
    500) -- cheaper than one call per product, and still exact per-product
    attribution afterward since every review row carries `product.url`.
    """
    targets = [p["url"] for p in products
               if force_rescrape or not already_scraped or p["url"] not in already_scraped]
    skipped = len(products) - len(targets)
    if skipped:
        log.info(f"[{brand}] Skipping {skipped} already-scraped product(s) (Apify credits saved)")
    if not targets:
        return []

    log.info(f"[{brand}] Fetching reviews for {len(targets)} product(s)")
    run_input = {
        "productTargets": targets,
        "storefront": cfg.storefront,
        "starRatingFilter": cfg.star_rating_filter,
        "reviewOrder": "recommended",
    }
    if cfg.review_limit is not None:
        run_input["reviewLimit"] = cfg.review_limit

    try:
        items = _apify_run(token, REVIEWS_ACTOR, run_input, f"reviews:{brand}")
    except Exception as e:
        log.error(f"Apify review run failed for brand='{brand}': {e}")
        return []

    if dry_run:
        _dump_raw(brand, items, cfg)
        return items

    # Record each targeted URL as scraped -- even a product with zero
    # reviews returned is "scraped" (nothing to re-pull), same convention
    # as tiktok_pipeline_sg.py marking a search term scraped regardless of
    # item count.
    if scraped_conn is not None:
        found_by_url: dict[str, int] = {}
        for it in items:
            u = _pick(it.get("product", {}) or {}, "url")
            if u:
                found_by_url[u] = found_by_url.get(u, 0) + 1
        for url in targets:
            mark_product_scraped(scraped_conn, cfg.market, url, found_by_url.get(url, 0))

    time.sleep(cfg.request_delay_seconds)
    return items


# ---------------------------------------------------------------------------
# 5. Normalization
# ---------------------------------------------------------------------------

def _make_review_id(source: str, product_url: str, reviewer_id: str, published_at: str, text: str) -> str:
    """No native reviewId in this actor's schema (unlike the Shopee TH
    review actor, which has one) -- hash the fields that together identify
    one review (product + reviewer + timestamp + first 50 chars of text)
    so re-running the same product doesn't create duplicate rows, but two
    different reviews on the same product by the same reviewer at
    different times still get distinct ids."""
    basis = f"{source}:{product_url}:{reviewer_id}:{published_at}:{text[:50]}"
    return hashlib.sha256(basis.encode("utf-8")).hexdigest()[:16]


def normalize_review(item: dict, brand: str, cfg: ReviewPipelineConfig) -> Optional[ReviewRecord]:
    product = item.get("product") or {}
    reviewer = item.get("reviewer") or {}
    purchase = item.get("purchase") or {}
    variant = item.get("variant") or {}
    media = item.get("media") or []

    text = _pick(item, "text")
    rating = _pick(item, "rating")
    if not text and rating is None:
        # Nothing worth keeping -- some actor rows can be rating-only with
        # no written text; that's fine (still a signal), but a totally
        # empty row (no text AND no rating) isn't a review.
        return None

    product_url = _pick(product, "url", default="")
    reviewer_id = _pick(reviewer, "accountId", default="") or _pick(reviewer, "name", default="")
    published_at = _pick(item, "publishedAt", default="")

    return ReviewRecord(
        record_id=_make_review_id(cfg.source, product_url, str(reviewer_id), str(published_at), text or ""),
        source=cfg.source,
        market=cfg.market,
        brand=brand,
        product_id=_pick(product, "id"),
        product_url=product_url,
        product_name=_pick(product, "name"),
        rating=int(rating) if rating is not None else None,
        review_text=text,
        review_date_utc=published_at or None,
        reviewer_name=_pick(reviewer, "name"),
        reviewer_country=_pick(reviewer, "country"),
        is_verified_purchase=purchase.get("isVerifiedPurchase"),
        has_media=bool(media),
        variant_sku=_pick(variant, "sku"),
        pulled_at_utc=datetime.now(timezone.utc).isoformat(),
    )


# ---------------------------------------------------------------------------
# 6. Storage -- append-only, timestamped, same convention as
#    tiktok_pipeline_sg.py (never overwrite).
# ---------------------------------------------------------------------------

def new_output_path(cfg: ReviewPipelineConfig) -> Path:
    cfg.output_dir.mkdir(parents=True, exist_ok=True)
    stamp = datetime.now(timezone.utc).strftime("%Y%m%dT%H%M%SZ")
    return cfg.output_dir / f"tiktok_shop_sg_reviews_{stamp}.jsonl"


def append_records(records: list[ReviewRecord], out_path: Path) -> None:
    if not records:
        return
    with out_path.open("a", encoding="utf-8") as f:
        for r in records:
            f.write(json.dumps(asdict(r), ensure_ascii=False, default=str) + "\n")
            f.flush()
    log.info(f"Appended {len(records)} review records -> {out_path}")


def export_csv(cfg: ReviewPipelineConfig) -> Optional[Path]:
    jsonl_files = sorted(cfg.output_dir.glob("tiktok_shop_sg_reviews_*.jsonl"))
    if not jsonl_files:
        log.warning(f"No tiktok_shop_sg_reviews_*.jsonl files found in {cfg.output_dir} -- nothing to export")
        return None

    fieldnames = [f.name for f in fields(ReviewRecord)]
    out_path = cfg.output_dir / "tiktok_shop_sg_reviews_export.csv"
    row_count = 0
    with out_path.open("w", encoding="utf-8-sig", newline="") as f:
        writer = csv.DictWriter(f, fieldnames=fieldnames)
        writer.writeheader()
        for jf in jsonl_files:
            with jf.open("r", encoding="utf-8") as jf_handle:
                for line in jf_handle:
                    line = line.strip()
                    if not line:
                        continue
                    writer.writerow(json.loads(line))
                    row_count += 1
    log.info(f"Exported {row_count} review rows from {len(jsonl_files)} file(s) -> {out_path}")
    return out_path


# ---------------------------------------------------------------------------
# 7. Orchestration
# ---------------------------------------------------------------------------

def run_pull(
    cfg: ReviewPipelineConfig, token: str,
    brand_filter: Optional[list[str]] = None, dry_run: bool = False,
    force_rescrape: bool = False, max_products_per_brand: Optional[int] = None,
) -> Optional[Path]:
    by_brand = load_product_urls_from_pricing(cfg)
    if not by_brand:
        return None

    if brand_filter:
        norm_filter = {b.lower().replace("&", "and") for b in brand_filter}
        by_brand = {b: v for b, v in by_brand.items() if b.lower().replace("&", "and") in norm_filter}
        if not by_brand:
            log.warning(f"--brand filter {brand_filter} matched nothing in the pricing data "
                        f"(available brands: {list(load_product_urls_from_pricing(cfg))})")
            return None

    scraped_conn = None if dry_run else open_scraped_db(cfg)
    already_scraped: set = set()
    if scraped_conn is not None and not force_rescrape:
        already_scraped = get_scraped_product_urls(scraped_conn, cfg.market)
        if already_scraped:
            log.info(f"[TRACK] {len(already_scraped)} product(s) already review-scraped before -- "
                     f"skipping (use --force-rescrape to re-pull and re-spend Apify credits)")

    out_path = None if dry_run else new_output_path(cfg)
    total_records = 0

    for brand, products in by_brand.items():
        if max_products_per_brand:
            products = products[:max_products_per_brand]

        items = fetch_reviews_for_brand(
            brand, products, cfg, token, dry_run=dry_run,
            scraped_conn=scraped_conn, already_scraped=already_scraped,
            force_rescrape=force_rescrape,
        )
        if dry_run:
            log.info(f"[DRY-RUN] {brand}: {len(items)} raw review item(s) (not written to disk)")
            total_records += len(items)
            continue

        brand_records = []
        for it in items:
            try:
                rec = normalize_review(it, brand, cfg)
                if rec is not None:
                    brand_records.append(rec)
            except Exception as e:
                log.warning(f"Skipping unparseable review for '{brand}': {e}")

        append_records(brand_records, out_path)
        total_records += len(brand_records)

    if scraped_conn is not None:
        scraped_conn.close()

    if dry_run:
        log.info(f"[DRY-RUN] Total raw review items: {total_records} (not written to disk)")
        return None

    log.info(f"[DONE] Total written: {total_records} review records -> {out_path}")
    return out_path


if __name__ == "__main__":
    parser = argparse.ArgumentParser(description="TikTok Shop SG review pull (via Apify)")
    parser.add_argument("--brand", nargs="+", help='e.g. --brand "MyACUVUE" "Alcon"')
    parser.add_argument("--review-limit", type=int, default=100,
                         help="Max reviews per product (actor param). Set 0 for all available reviews (costs more).")
    parser.add_argument("--max-products-per-brand", type=int, default=None,
                         help="Cap how many products per brand to review-scrape this run (useful for a cheap test)")
    parser.add_argument("--dry-run", action="store_true",
                         help="Dump raw Apify output to data/tiktok_shop_sg/tiktok_raw_reviews_*.json and print "
                              "counts, but do NOT write the timestamped JSONL output")
    parser.add_argument(
        "--force-rescrape", action="store_true",
        help="Re-call Apify for products already review-scraped before (by default, a product recorded "
             "in scraped_sources.db's review_scraped_sources table is skipped to avoid re-spending Apify "
             "credits). Use this to pick up new reviews on a product you've already pulled.",
    )
    parser.add_argument(
        "--export-csv", action="store_true",
        help="Consolidate every tiktok_shop_sg_reviews_*.jsonl pull into one CSV and exit -- does not scrape.",
    )
    args = parser.parse_args()

    cfg = ReviewPipelineConfig(review_limit=(None if args.review_limit == 0 else args.review_limit))

    if args.export_csv:
        export_csv(cfg)
        raise SystemExit(0)

    apify_token = os.getenv("APIFY_TOKEN")
    if not apify_token:
        log.error("APIFY_TOKEN not set in .env")
        raise SystemExit(1)

    run_pull(
        cfg, apify_token, brand_filter=args.brand, dry_run=args.dry_run,
        force_rescrape=args.force_rescrape, max_products_per_brand=args.max_products_per_brand,
    )
