"""
tiktok_pipeline_sg.py

TikTok Shop (Singapore) pricing discovery pipeline — MyACUVUE / J&J Vision SG
-------------------------------------------------------------------------------
Purpose:
  Pull steady-state and promotional pricing for MyACUVUE + competitor lens
  brands (Alcon, CooperVision, Bausch & Lomb, Olens) from TikTok Shop
  Singapore, normalized into the same PriceRecord schema used for the
  Shopee/Lazada SG pulls, so all sources feed one dataset.

  Ported from tiktok_pipeline.py (Acne-Aid / Thailand project) — see
  Scripts/scripts.md for the porting notes this follows. Changes from the
  TH original: market/country_code TH->SG, currency THB->SGD, brand list
  rebuilt for the contact-lens category, English-only search terms (no
  Thai-script synonyms needed — SG is majority English).

Decision on record (carried over from the TH project, still applies):
  - No official TikTok API covers TikTok Shop pricing/product data.
  - Path chosen: custom scraper via Apify, same approach as Shopee/Lazada.
  - Fallback: if scraping proves unreliable/blocked, TikTok Shop is treated
    as a secondary/"nice to have" source, not a blocker.

Standing principles this pipeline must respect (see context.md):
  - Multi-timestamp pulls required (steady-state vs. promo) — never treat a
    single snapshot as ground truth.
  - External-only data — no dependency on internal/client data (see plan's
    scope boundary: no CRM/registration/WhatsApp data in scope yet).
  - Keep this file and its outputs in THIS project only — do not write into
    or read from the Thailand (acne-aid) or Hong Kong (xhs) project files/DB.

This is a scaffold, same as the TH original: the fetch layer talks to a
real Apify actor, but the actor's field-name mapping is unverified for SG
results until a --dry-run is inspected.
"""

from __future__ import annotations

import os
import json
import csv
import re
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
log = logging.getLogger("tiktok_pipeline_sg")

APIFY_BASE = "https://api.apify.com/v2"
# Same actor as the TH pipeline (pratikdani/tiktok-shop-search-scraper) --
# keyword + country_code search, matches this pipeline's need. NOT YET
# VERIFIED that this actor's country_code param supports "SG" (only "TH"
# was confirmed in the TH project). Run --dry-run first; if country_code=SG
# returns nothing or errors, the actor may need a different param value or
# a different actor entirely -- check data/tiktok_shop_sg/tiktok_raw_*.json
# before trusting a full run. Output field names are also unverified
# against real SG data (same caveat as the TH project).
TIKTOK_ACTOR = "pratikdani/tiktok-shop-search-scraper"


# ---------------------------------------------------------------------------
# 1. Config
# ---------------------------------------------------------------------------

@dataclass
class PipelineConfig:
    market: str = "SG"
    source: str = "tiktok_shop"
    output_dir: Path = Path("./data/tiktok_shop_sg")
    # Brand -> search terms used to locate storefronts/listings.
    # English-only terms -- SG is majority English, no local-script
    # synonyms needed (unlike the TH original's Thai-script entries).
    brands: dict = field(default_factory=lambda: {
        "MyACUVUE": ["acuvue", "myacuvue", "acuvue oasys", "acuvue 1-day"],
        "Alcon": ["alcon", "air optix", "dailies total30", "dailies"],
        "CooperVision": ["coopervision", "biofinity", "clariti", "myday"],
        "Bausch + Lomb": ["bausch lomb", "bausch + lomb", "biotrue", "ultra contact lens"],
        "Olens": ["olens", "o-lens"],
    })
    # Hero/priority SKUs get pulled every run; long-tail SKUs pulled less often.
    priority_tiers: dict = field(default_factory=lambda: {"high": [], "medium": [], "low": []})
    request_delay_seconds: float = 2.5  # polite pacing between requests
    max_retries: int = 3
    max_items_per_term: int = 20  # Apify actor result cap per search term


# ---------------------------------------------------------------------------
# 2. Normalized record — matches the shared Control Tower schema
#    (mirrors the Shopee/Lazada SG pull format so all sources merge)
# ---------------------------------------------------------------------------

@dataclass
class PriceRecord:
    record_id: str            # stable hash of source+sku_url
    source: str                # "tiktok_shop"
    market: str                 # "SG"
    brand: str
    product_name_raw: str        # original listing text
    product_name_en: Optional[str]  # filled by translation step (usually not_required for SG)
    sku_url: str
    seller_name: Optional[str]
    list_price: Optional[float]      # pre-discount / steady-state reference price
    current_price: float              # price shown at pull time
    is_promo: bool                     # current_price < list_price at pull time
    promo_label: Optional[str]          # e.g. "9.9 Sale", "Flash Sale"
    currency: str
    pulled_at_utc: str                   # ISO timestamp — critical for multi-timestamp analysis
    priority_tier: Optional[str]          # "high" / "medium" / "low" / None (unmatched)
    competitor_match_sku: Optional[str]    # hero SKU this maps to, if a competitor product
    translation_status: str                 # "pending" | "done" | "not_required"
    review_count: Optional[int]              # aggregate review count -- present on some SG
                                               # listings (confirmed 2026-09-24 against raw Alcon
                                               # pull items), null on others; not the review TEXT
                                               # (see tiktok_reviews_sg.py for that), just the count
                                               # TikTok Shop itself already surfaces per listing
    avg_rating: Optional[float]               # aggregate star rating, same source/caveat as above


# ---------------------------------------------------------------------------
# 2.5. Scraped-source tracking — avoids re-spending Apify credits on a
#    brand/term already pulled. Separate tiny SQLite db per output_dir,
#    same rationale as youtube_scraper_sg.py's yt_scraped_sources: a
#    source stays "done" until --force-rescrape is passed.
# ---------------------------------------------------------------------------

_SCRAPED_SCHEMA = """
CREATE TABLE IF NOT EXISTS scraped_sources (
    market          TEXT NOT NULL,
    brand           TEXT NOT NULL,
    term            TEXT NOT NULL,
    last_scraped_at TEXT NOT NULL,
    items_found     INTEGER,
    PRIMARY KEY (market, brand, term)
);
"""


def open_scraped_db(cfg: "PipelineConfig") -> sqlite3.Connection:
    cfg.output_dir.mkdir(parents=True, exist_ok=True)
    conn = sqlite3.connect(cfg.output_dir / "scraped_sources.db", timeout=60)
    conn.execute("PRAGMA journal_mode=WAL")
    conn.executescript(_SCRAPED_SCHEMA)
    conn.commit()
    return conn


def get_scraped_terms(conn: sqlite3.Connection, market: str) -> set:
    """Returns the set of (brand, term) pairs already pulled from Apify at
    least once for this market."""
    return {
        (row[0], row[1])
        for row in conn.execute("SELECT brand, term FROM scraped_sources WHERE market = ?", (market,))
    }


def mark_term_scraped(conn: sqlite3.Connection, market: str, brand: str, term: str, items_found: int) -> None:
    conn.execute(
        """INSERT INTO scraped_sources (market, brand, term, last_scraped_at, items_found)
           VALUES (?, ?, ?, ?, ?)
           ON CONFLICT(market, brand, term)
           DO UPDATE SET last_scraped_at = excluded.last_scraped_at, items_found = excluded.items_found""",
        (market, brand, term, datetime.now(timezone.utc).isoformat(), items_found),
    )
    conn.commit()


# ---------------------------------------------------------------------------
# 3. Fetch layer
# ---------------------------------------------------------------------------

def _pick(d: dict, *keys: str, default=None):
    """Try each candidate key in order -- actor output field names are
    unverified against real SG data (see TIKTOK_ACTOR comment above)."""
    for k in keys:
        v = d.get(k)
        if v not in (None, ""):
            return v
    return default


def _apify_run(token: str, actor_id: str, run_input: dict, label: str) -> list[dict]:
    """Run/poll/fetch-dataset against an Apify actor. Same shape as the
    TH pipeline's pattern."""
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


def _dump_raw(brand: str, items: list[dict], cfg: PipelineConfig) -> None:
    cfg.output_dir.mkdir(parents=True, exist_ok=True)
    path = cfg.output_dir / f"tiktok_raw_{brand.replace(' ', '_')}.json"
    with path.open("w", encoding="utf-8") as f:
        json.dump(items[:5], f, ensure_ascii=False, indent=2)
    log.info(f"  Raw sample (first 5 of {len(items)}) written to {path}")


def _parse_money(v) -> Optional[float]:
    if v is None:
        return None
    # Strip everything except digits/dot -- handles "S$31.34", "$31.34",
    # "31.34" etc. in one pass (order-dependent replace() chains break on
    # "S$" since stripping "$" first leaves a stray "S").
    s = re.sub(r"[^0-9.]", "", str(v)).strip()
    if not s:
        return None
    try:
        return float(s)
    except ValueError:
        return None


def _parse_int(v) -> Optional[int]:
    if v is None:
        return None
    try:
        return int(float(v))
    except (ValueError, TypeError):
        return None


def _parse_float(v) -> Optional[float]:
    if v is None:
        return None
    try:
        return float(v)
    except (ValueError, TypeError):
        return None


def _extract_tiktok_prices(item: dict) -> tuple[Optional[float], Optional[float]]:
    """Returns (current_price, list_price).

    The TH project's confirmed field mapping (`real_price` = current
    price, nested `skus.<id>.real_price.origin_price_decimal` = list
    price) does NOT hold for SG data -- verified against a live
    --dry-run pull 2026-09-23: `real_price` is null on every SG item,
    and `skus` is an empty dict on every item (no nested origin price
    available at all). The actual current price for SG results lives in
    `min_price`/`max_price`/`avg_price` (identical to each other on every
    sampled row, formatted "S$31.34"). `original_price` is present as a
    bare number (e.g. "87", "33", "7") but doesn't behave like a
    pre-discount price -- values were sometimes LOWER than the current
    price, which is impossible for a genuine list price -- so it is not
    used here. list_price is left None (no promo/is_promo detection)
    until a real discounted item's raw JSON confirms what actually
    carries the pre-discount price for this actor/region.
    """
    current = _parse_money(item.get("min_price") or item.get("avg_price") or item.get("max_price"))
    return current, None


def print_coverage(cfg: PipelineConfig) -> None:
    """Compares cfg.brands (what SHOULD be scraped) against
    scraped_sources.db (what actually HAS been, via a real non-dry run)
    and prints any gap. Catches exactly the mistake of running --dry-run
    (which never writes to disk or marks a term scraped) and mistaking
    that for real coverage."""
    if not (cfg.output_dir / "scraped_sources.db").exists():
        log.warning(f"No scraped_sources.db in {cfg.output_dir} -- nothing has been scraped for real yet "
                     f"(a --dry-run does not count, by design)")
        return
    conn = open_scraped_db(cfg)
    scraped = get_scraped_terms(conn, cfg.market)
    conn.close()

    configured = {(brand, term) for brand, terms in cfg.brands.items() for term in terms}
    missing = configured - scraped
    if not missing:
        log.info(f"[COVERAGE] All {len(configured)} configured brand/term combos have been scraped at least once.")
        return
    log.warning(f"[COVERAGE] {len(missing)}/{len(configured)} configured brand/term combos have NEVER been "
                 f"scraped for real (dry-runs don't count):")
    for brand, term in sorted(missing):
        log.warning(f"  MISSING: brand='{brand}' term='{term}'")


def fetch_raw_listings(
    brand: str, search_terms: list[str], cfg: PipelineConfig,
    token: str, dry_run: bool = False,
    scraped_conn: Optional[sqlite3.Connection] = None,
    already_scraped: Optional[set] = None,
    force_rescrape: bool = False,
) -> list[dict]:
    """
    TikTok Shop SG search + listing retrieval via Apify.

    Runs one actor call per search term and merges results. Maps actor
    output fields onto the raw-dict shape normalize_record() expects: url,
    title, current_price, list_price, seller_name, promo_label, currency.

    `already_scraped`, if provided, is the set of (brand, term) pairs
    already pulled before -- those terms are skipped entirely (no Apify
    call, no credits spent) unless force_rescrape. `scraped_conn`, if
    provided, records each term right after its Apify call succeeds --
    same as youtube_scraper_sg.py's tracking, a --dry-run (scraped_conn=
    None) never locks in tracking state.
    """
    all_items: list[dict] = []
    for term in search_terms:
        if not force_rescrape and already_scraped and (brand, term) in already_scraped:
            log.info(f"Skipping already-scraped term (Apify credits saved): brand='{brand}' term='{term}'")
            continue
        log.info(f"Searching TikTok Shop SG for brand='{brand}' term='{term}'")
        try:
            items = _apify_run(
                token, TIKTOK_ACTOR,
                {"keyword": term, "country_code": "SG", "limit": min(cfg.max_items_per_term, 10)},
                f"tiktok:{brand}:{term}",
            )
        except Exception as e:
            log.error(f"Apify run failed for brand='{brand}' term='{term}': {e}")
            continue
        if scraped_conn is not None:
            mark_term_scraped(scraped_conn, cfg.market, brand, term, len(items))
        all_items.extend(items)
        time.sleep(cfg.request_delay_seconds)

    if dry_run:
        _dump_raw(brand, all_items, cfg)

    raw_listings: list[dict] = []
    for item in all_items:
        try:
            product_id = _pick(item, "product_id", "id", "product_id_str", "productId")
            url = _pick(item, "url", "productUrl", "product_url")
            if not url and product_id:
                # Guessed URL pattern -- this actor's output has no direct
                # product URL field at all, confirmed against TH output.
                url = f"https://shop.tiktok.com/view/product/{product_id}"

            current_price, list_price = _extract_tiktok_prices(item)

            seller = item.get("seller") or {}
            seller_name = _pick(seller, "seller_name", "sellerName") or _pick(item, "seller_name", "sellerName")

            raw_listings.append({
                "url": url or "",
                "title": _pick(item, "product_title", "product_name", "title", "productTitle", "name", default=""),
                "seller_name": seller_name,
                "current_price": current_price,
                "list_price": list_price,
                "promo_label": _pick(item, "promo_label", "promotionText"),
                "currency": "SGD",
                "review_count": _parse_int(_pick(item, "review_count", "reviewCount")),
                "avg_rating": _parse_float(_pick(item, "product_rating", "productRating")),
            })
        except Exception as e:
            log.warning(f"Skipping unparseable raw item for '{brand}': {e}")

    return raw_listings


# ---------------------------------------------------------------------------
# 4. Normalization
# ---------------------------------------------------------------------------

def _make_record_id(source: str, sku_url: str, pull_date: str) -> str:
    """Date-scoped so the SAME product URL pulled on two different days gets
    two DIFFERENT record_ids -- without this, a second day's pull of an
    already-seen SKU would be silently dropped as a "duplicate" of the
    first day's, discarding the new price entirely.
    pull_date should be a YYYY-MM-DD string (date portion only, so re-runs
    within the same day still correctly dedupe against each other)."""
    return hashlib.sha256(f"{source}:{sku_url}:{pull_date}".encode("utf-8")).hexdigest()[:16]


def normalize_record(raw: dict, brand: str, cfg: PipelineConfig) -> PriceRecord:
    """Map one raw scraped listing into the shared PriceRecord schema."""
    sku_url = raw.get("url", "")
    current_price = float(raw.get("current_price", 0.0))
    list_price = raw.get("list_price")
    list_price = float(list_price) if list_price is not None else None
    is_promo = bool(list_price and current_price < list_price)

    name_raw = raw.get("title", "")
    # Generic non-ASCII check (not Thai-specific despite the TH project's
    # comment) -- SG listings are expected to be ASCII/English already, so
    # this should mostly evaluate to "not_required".
    needs_translation = any(ord(ch) > 127 for ch in name_raw)

    pull_date = datetime.now(timezone.utc).strftime("%Y-%m-%d")
    return PriceRecord(
        record_id=_make_record_id(cfg.source, sku_url, pull_date),
        source=cfg.source,
        market=cfg.market,
        brand=brand,
        product_name_raw=name_raw,
        product_name_en=None,
        sku_url=sku_url,
        seller_name=raw.get("seller_name"),
        list_price=list_price,
        current_price=current_price,
        is_promo=is_promo,
        promo_label=raw.get("promo_label"),
        currency=raw.get("currency", "SGD"),
        pulled_at_utc=datetime.now(timezone.utc).isoformat(),
        priority_tier=_match_priority_tier(name_raw, cfg),
        competitor_match_sku=raw.get("competitor_match_sku"),
        translation_status="pending" if needs_translation else "not_required",
        review_count=raw.get("review_count"),
        avg_rating=raw.get("avg_rating"),
    )


def _match_priority_tier(product_name: str, cfg: PipelineConfig) -> Optional[str]:
    """
    Placeholder matcher against a High/Medium/Low SKU list. Populate
    cfg.priority_tiers with the confirmed MyACUVUE hero SKUs (from
    context.md's product line) once that priority list is confirmed, and
    do real matching here (fuzzy match on name/pack size) instead of
    returning None.
    """
    for tier, skus in cfg.priority_tiers.items():
        if any(sku.lower() in product_name.lower() for sku in skus):
            return tier
    return None


# ---------------------------------------------------------------------------
# 5. Translation hook (stub, same as TH project -- likely unneeded for SG
#    since listings are expected to already be in English)
# ---------------------------------------------------------------------------

def translate_pending(records: list[PriceRecord]) -> list[PriceRecord]:
    """
    TODO: wire this up to the same GPT-4o-mini translation approach used
    elsewhere in the project (see translate_lazada_th.py) if any SG
    listings turn out non-English. Every record must be
    translation_status == "done" or "not_required" before it feeds
    downstream analysis.
    """
    for r in records:
        if r.translation_status == "pending":
            log.info(f"[STUB] Would translate: {r.product_name_raw!r}")
            # r.product_name_en = call_translation_service(r.product_name_raw)
            # r.translation_status = "done"
    return records


# ---------------------------------------------------------------------------
# 6. Storage — append-only, timestamped, so we retain every pull
#    (never overwrite — multi-timestamp comparison is the whole point).
#    Written incrementally per brand (not once at the end of the whole
#    run) so a crash/interrupt partway through a multi-brand run doesn't
#    lose the brands that already finished.
# ---------------------------------------------------------------------------

def new_output_path(cfg: PipelineConfig) -> Path:
    cfg.output_dir.mkdir(parents=True, exist_ok=True)
    stamp = datetime.now(timezone.utc).strftime("%Y%m%dT%H%M%SZ")
    return cfg.output_dir / f"tiktok_shop_sg_{stamp}.jsonl"


def append_records(records: list[PriceRecord], out_path: Path) -> None:
    if not records:
        return
    with out_path.open("a", encoding="utf-8") as f:
        for r in records:
            f.write(json.dumps(asdict(r), ensure_ascii=False) + "\n")
            f.flush()
    log.info(f"Appended {len(records)} records -> {out_path}")


def export_csv(cfg: PipelineConfig) -> Optional[Path]:
    """Consolidates every tiktok_shop_sg_*.jsonl pull in output_dir into
    one CSV -- for handing off to someone who isn't going to read JSONL.
    Every pull (every timestamped file) is included as its own rows, not
    deduped down to "latest only" -- multi-timestamp history is the whole
    point of this pipeline's design (see module docstring), so collapsing
    it here would throw away exactly the promo-vs-steady-state comparison
    the data exists to support. If only the latest snapshot is wanted,
    filter the CSV's pulled_at_utc column after export instead."""
    jsonl_files = sorted(cfg.output_dir.glob("tiktok_shop_sg_*.jsonl"))
    if not jsonl_files:
        log.warning(f"No tiktok_shop_sg_*.jsonl files found in {cfg.output_dir} -- nothing to export")
        return None

    fieldnames = [f.name for f in fields(PriceRecord)]
    out_path = cfg.output_dir / "tiktok_shop_sg_export.csv"
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
    log.info(f"Exported {row_count} rows from {len(jsonl_files)} file(s) -> {out_path}")
    return out_path


# ---------------------------------------------------------------------------
# 7. Orchestration
# ---------------------------------------------------------------------------

def run_pull(
    cfg: PipelineConfig, token: str,
    brand_filter: Optional[list[str]] = None, dry_run: bool = False,
    force_rescrape: bool = False,
) -> Optional[Path]:
    if brand_filter:
        configured = {b.lower().replace("&", "and") for b in cfg.brands}
        unmatched = [b for b in brand_filter if b.lower().replace("&", "and") not in configured]
        if unmatched:
            log.warning(f"--brand name(s) not in cfg.brands, will be silently skipped: {unmatched} "
                        f"(configured brands: {list(cfg.brands)})")

    scraped_conn = None if dry_run else open_scraped_db(cfg)
    already_scraped: set = set()
    if scraped_conn is not None and not force_rescrape:
        already_scraped = get_scraped_terms(scraped_conn, cfg.market)
        if already_scraped:
            log.info(f"[TRACK] {len(already_scraped)} brand/term source(s) already scraped before — "
                      f"skipping (use --force-rescrape to re-pull and re-spend Apify credits)")

    out_path = None if dry_run else new_output_path(cfg)
    total_records = 0

    for brand, terms in cfg.brands.items():
        if brand_filter:
            norm_filter = {b.lower().replace("&", "and") for b in brand_filter}
            if brand.lower().replace("&", "and") not in norm_filter:
                continue
        try:
            raw_listings = fetch_raw_listings(
                brand, terms, cfg, token, dry_run=dry_run,
                scraped_conn=scraped_conn, already_scraped=already_scraped,
                force_rescrape=force_rescrape,
            )
        except Exception as e:
            log.error(f"Fetch failed for brand '{brand}': {e}")
            continue

        brand_records: list[PriceRecord] = []
        for raw in raw_listings:
            try:
                brand_records.append(normalize_record(raw, brand, cfg))
            except Exception as e:
                log.warning(f"Skipping unparseable listing for '{brand}': {e}")

        if dry_run:
            log.info(f"[DRY-RUN] {brand}: parsed {len(brand_records)} records (not written to disk):")
            for r in brand_records:
                log.info(f"  {r.brand:15} | {r.current_price!s:>10} {r.currency} | {r.product_name_raw}")
            total_records += len(brand_records)
            continue

        brand_records = translate_pending(brand_records)
        # Written immediately per brand -- if a later brand's Apify call
        # fails or the process is interrupted, this brand's records are
        # already safely on disk.
        append_records(brand_records, out_path)
        total_records += len(brand_records)

    if scraped_conn is not None:
        scraped_conn.close()

    if dry_run:
        log.info(f"[DRY-RUN] Total parsed: {total_records} records (not written to disk)")
        return None

    log.info(f"[DONE] Total written: {total_records} records -> {out_path}")
    return out_path


if __name__ == "__main__":
    parser = argparse.ArgumentParser(description="TikTok Shop SG pricing pull (via Apify)")
    parser.add_argument("--brand", nargs="+", help='e.g. --brand "MyACUVUE" "Alcon"')
    parser.add_argument("--max-items", type=int, default=20, help="Per-search-term item cap")
    parser.add_argument("--dry-run", action="store_true",
                         help="Dump raw Apify output to data/tiktok_shop_sg/tiktok_raw_*.json and print "
                              "parsed rows, but do NOT write the timestamped JSONL output")
    parser.add_argument(
        "--force-rescrape", action="store_true",
        help="Re-call Apify for brand/term sources already scraped before (by default, a "
             "source recorded in scraped_sources.db is skipped to avoid re-spending Apify "
             "credits on the same keyword pull). Use this to pick up new listings on a "
             "brand/term you've already pulled.",
    )
    parser.add_argument(
        "--export-csv", action="store_true",
        help="Consolidate every tiktok_shop_sg_*.jsonl pull into one CSV "
             "(data/tiktok_shop_sg/tiktok_shop_sg_export.csv) and exit -- does not scrape.",
    )
    parser.add_argument(
        "--coverage", action="store_true",
        help="Print which configured brand/term combos have never been scraped for real "
             "(a --dry-run does not count), then exit -- does not scrape.",
    )
    args = parser.parse_args()

    cfg = PipelineConfig(max_items_per_term=args.max_items)

    if args.coverage:
        print_coverage(cfg)
        raise SystemExit(0)

    if args.export_csv:
        export_csv(cfg)
        raise SystemExit(0)

    apify_token = os.getenv("APIFY_TOKEN")
    if not apify_token:
        log.error("APIFY_TOKEN not set in .env")
        raise SystemExit(1)

    run_pull(cfg, apify_token, brand_filter=args.brand, dry_run=args.dry_run, force_rescrape=args.force_rescrape)
