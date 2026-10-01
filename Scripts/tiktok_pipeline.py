"""
tiktok_pipeline.py

TikTok Shop (Thailand) pricing discovery pipeline — Acne-Aid Growth Diagnostic
-------------------------------------------------------------------------------
Purpose:
  Pull steady-state and promotional pricing for Acne-Aid + competitor SKUs
  (CeraVe, Cetaphil, Neutrogena, La Roche-Posay, Eucerin, Smooth E) from
  TikTok Shop Thailand, and normalize output into the same schema used for
  Shopee / Lazada / Watsons.co.th pulls, so all sources feed one Pricing
  Control Tower dataset.

Decision on record (per project discussion):
  - No official TikTok API covers TikTok Shop pricing/product data
    (Research API / Commercial Content API only cover ads & public content).
  - TikTok Creative Center only surfaces ad/creative trends, not SKU pricing.
  - Path chosen: custom scraper, consistent with the Shopee/Lazada/Watsons
    approach already in use ("external-only, fast not pristine").
  - Fallback: if scraping proves unreliable/blocked, TikTok Shop is treated
    as a secondary/"nice to have" source. Shopee (>50% of Thai e-commerce)
    + Lazada + Watsons already cover the Control Tower's core steady-state
    and promo pricing needs.

Standing principles this pipeline must respect (see Context.md):
  - Multi-timestamp pulls required (steady-state vs. promo, e.g. mid-year
    "7.7" mega-sale) — never treat a single snapshot as ground truth.
  - Translate Thai-language listing text before any downstream analysis
    (same ChatGPT-based translation approach used on the HK project).
  - External-only data — no dependency on Inova's internal sell-in/sell-out.
  - Keep this file and its outputs in THIS project only — do not write
    into or read from the Hong Kong contact-lens project's files/DB.

This is a scaffold: the fetch layer is stubbed with clear TODOs marking
where actual scraping/browser-automation logic goes. Everything downstream
(normalization, dedup, translation hook, storage) is meant to be run as-is.
"""

from __future__ import annotations

import os
import json
import time
import hashlib
import logging
import argparse
from dataclasses import dataclass, field, asdict
from datetime import datetime, timezone
from pathlib import Path
from typing import Optional

import requests
from dotenv import load_dotenv

load_dotenv()

logging.basicConfig(level=logging.INFO, format="%(asctime)s | %(levelname)s | %(message)s")
log = logging.getLogger("tiktok_pipeline")

APIFY_BASE = "https://api.apify.com/v2"
# Swapped 2026-07-29: novi/tiktok-shop-scraper's free trial expired and it
# now requires a paid rental (403 actor-is-not-rented) before it can run at
# all -- confirmed via a live --dry-run call, no scrape happened, no cost.
# Also considered ace_scraper/tiktok-shop-product-scraper, but its input is
# an array of already-known productIds (a detail *enricher*), not a keyword
# search -- can't discover listings for a brand name the way this pipeline
# needs, so it was ruled out without writing any code against it.
#
# pratikdani/tiktok-shop-search-scraper: keyword + country_code="TH", real
# keyword search (matches this pipeline's actual need). Its own docs cap
# `limit` at 10 per call -- see the min() in fetch_raw_listings(). Output
# field names are STILL unverified against real data (same caveat as
# apify_pricing_th.py's Watsons/Shopee actors, and as novi's actor before
# it) -- run --dry-run first and check data/tiktok_shop/tiktok_raw_*.json
# before trusting a full run.
TIKTOK_ACTOR = "pratikdani/tiktok-shop-search-scraper"


# ---------------------------------------------------------------------------
# 1. Config
# ---------------------------------------------------------------------------

@dataclass
class PipelineConfig:
    market: str = "TH"
    source: str = "tiktok_shop"
    output_dir: Path = Path("./data/tiktok_shop")
    # Brand -> search terms used to locate storefronts/listings.
    # SKU-level matching happens in normalize_record() via priority_map.
    brands: dict = field(default_factory=lambda: {
        "Acne-Aid": ["acne aid", "แอคเน่ เอด"],
        "CeraVe": ["cerave"],
        "Cetaphil": ["cetaphil"],
        "Neutrogena": ["neutrogena"],
        "Eucerin": ["eucerin"],
        "Smooth E": ["smooth e"],
        # Confirmed competitive set per acne-aid-th CONTEXT.md SS13
        # (2026-07-19/20): Clean and Clear + Oxe'Cure replace La
        # Roche-Posay, which is deprioritized (data already collected is
        # kept, just not re-pulled going forward).
        "Clean and Clear": ["clean and clear", "clean & clear"],
        "Oxe'Cure": ["oxe'cure", "oxecure", "oxe cure"],
    })
    # Hero/priority SKUs get pulled every run; long-tail SKUs pulled less often.
    priority_tiers: dict = field(default_factory=lambda: {"high": [], "medium": [], "low": []})
    request_delay_seconds: float = 2.5  # polite pacing between requests
    max_retries: int = 3
    max_items_per_term: int = 20  # Apify actor result cap per search term


# ---------------------------------------------------------------------------
# 2. Normalized record — matches the shared Control Tower schema
#    (mirrors the Shopee/Lazada/Watsons pull format so all sources merge)
# ---------------------------------------------------------------------------

@dataclass
class PriceRecord:
    record_id: str            # stable hash of source+sku_url
    source: str                # "tiktok_shop"
    market: str                 # "TH"
    brand: str
    product_name_raw: str        # original (Thai or mixed)
    product_name_en: Optional[str]  # filled by translation step
    sku_url: str
    seller_name: Optional[str]
    list_price: Optional[float]      # pre-discount / steady-state reference price
    current_price: float              # price shown at pull time
    is_promo: bool                     # current_price < list_price at pull time
    promo_label: Optional[str]          # e.g. "7.7 Mega Sale", "Flash Sale"
    currency: str
    pulled_at_utc: str                   # ISO timestamp — critical for multi-timestamp analysis
    priority_tier: Optional[str]          # "high" / "medium" / "low" / None (unmatched)
    competitor_match_sku: Optional[str]    # hero SKU this maps to, if a competitor product
    translation_status: str                 # "pending" | "done" | "not_required"


# ---------------------------------------------------------------------------
# 3. Fetch layer (STUB — replace with actual scraping/automation logic)
# ---------------------------------------------------------------------------

def _pick(d: dict, *keys: str, default=None):
    """Try each candidate key in order -- actor output field names are
    unverified against real data (see TIKTOK_ACTOR comment above)."""
    for k in keys:
        v = d.get(k)
        if v not in (None, ""):
            return v
    return default


def _apify_run(token: str, actor_id: str, run_input: dict, label: str) -> list[dict]:
    """Run/poll/fetch-dataset against an Apify actor. Same shape as the
    Watsons/Shopee pattern in apify_pricing_th.py."""
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
    s = str(v).replace(",", "").replace("฿", "").strip()
    try:
        return float(s)
    except ValueError:
        return None


def _extract_tiktok_prices(item: dict) -> tuple[Optional[float], Optional[float]]:
    """Returns (current_price, list_price).

    Confirmed against real pratikdani/tiktok-shop-search-scraper output
    2026-07-29: the top-level `original_price`/`max_price`/`min_price`
    fields are ALL actually the current (post-discount) price -- they
    match `real_price` exactly on every sample row despite the misleading
    names. The genuine pre-discount price only appears nested under
    `skus.<sku_id>.real_price.origin_price_decimal` (there can be more
    than one sku/variant; the first one found is used as representative).
    """
    current = _parse_money(item.get("real_price"))
    list_price = None
    skus = item.get("skus")
    if isinstance(skus, dict):
        for sku in skus.values():
            rp = sku.get("real_price") or {}
            origin = rp.get("origin_price_decimal", rp.get("origin_price_format"))
            if origin is not None:
                list_price = _parse_money(origin)
                break
    return current, list_price


def fetch_raw_listings(
    brand: str, search_terms: list[str], cfg: PipelineConfig,
    token: str, dry_run: bool = False,
) -> list[dict]:
    """
    TikTok Shop TH search + listing retrieval via the novi/tiktok-shop-scraper
    Apify actor (region="TH" explicitly supported by that actor).

    Runs one actor call per search term (brands like "La Roche-Posay" have
    multiple synonyms) and merges results. Maps actor output fields onto the
    raw-dict shape normalize_record() expects: url, title, current_price,
    list_price, seller_name, promo_label, currency.
    """
    all_items: list[dict] = []
    for term in search_terms:
        log.info(f"Searching TikTok Shop TH for brand='{brand}' term='{term}'")
        try:
            items = _apify_run(
                token, TIKTOK_ACTOR,
                {"keyword": term, "country_code": "TH", "limit": min(cfg.max_items_per_term, 10)},
                f"tiktok:{brand}:{term}",
            )
        except Exception as e:
            log.error(f"Apify run failed for brand='{brand}' term='{term}': {e}")
            continue
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
                # product URL field at all, confirmed against real output.
                url = f"https://shop.tiktok.com/view/product/{product_id}"

            current_price, list_price = _extract_tiktok_prices(item)

            seller = item.get("seller") or {}
            seller_name = _pick(seller, "seller_name", "sellerName") or _pick(item, "seller_name", "sellerName")

            raw_listings.append({
                "url": url or "",
                # "title"/"productTitle"/"name" (old novi-actor guesses) kept
                # as fallbacks; real field confirmed 2026-07-29 is product_title.
                "title": _pick(item, "product_title", "product_name", "title", "productTitle", "name", default=""),
                "seller_name": seller_name,
                "current_price": current_price,
                "list_price": list_price,
                "promo_label": _pick(item, "promo_label", "promotionText"),
                "currency": "THB",
            })
        except Exception as e:
            log.warning(f"Skipping unparseable raw item for '{brand}': {e}")

    return raw_listings


# ---------------------------------------------------------------------------
# 4. Normalization
# ---------------------------------------------------------------------------

def _make_record_id(source: str, sku_url: str, pull_date: str) -> str:
    """Date-scoped so the SAME product URL pulled on two different days gets
    two DIFFERENT record_ids. Critical: build_tiktok_shop_pricing_csv.py's
    read_records() dedupes by record_id keeping first-seen (files processed
    in chronological filename order) -- without the date component, a
    second day's pull of an already-seen SKU would be silently dropped as
    a "duplicate" of the first day's, discarding the new price entirely.
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
    needs_translation = any(ord(ch) > 127 for ch in name_raw)  # crude Thai-script check

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
        currency=raw.get("currency", "THB"),
        pulled_at_utc=datetime.now(timezone.utc).isoformat(),
        priority_tier=_match_priority_tier(name_raw, cfg),
        competitor_match_sku=raw.get("competitor_match_sku"),
        translation_status="pending" if needs_translation else "not_required",
    )


def _match_priority_tier(product_name: str, cfg: PipelineConfig) -> Optional[str]:
    """
    Placeholder matcher against the client's High/Medium/Low SKU list.
    Once the client returns the confirmed prioritized SKU list (open item
    in Context.md §8), populate cfg.priority_tiers and do real matching
    here (fuzzy match on name/pack size) instead of returning None.
    """
    for tier, skus in cfg.priority_tiers.items():
        if any(sku.lower() in product_name.lower() for sku in skus):
            return tier
    return None


# ---------------------------------------------------------------------------
# 5. Translation hook (same ChatGPT-based approach as the rest of the project)
# ---------------------------------------------------------------------------

def translate_pending(records: list[PriceRecord]) -> list[PriceRecord]:
    """
    TODO: wire this up to the same translation approach used elsewhere in
    the project (ChatGPT-based Thai->English) rather than analyzing raw
    Thai product titles. Every record must be translation_status == "done"
    or "not_required" before it feeds the Brand/Consumer Feedback or
    Pricing Recommendation layers.
    """
    for r in records:
        if r.translation_status == "pending":
            log.info(f"[STUB] Would translate: {r.product_name_raw!r}")
            # r.product_name_en = call_translation_service(r.product_name_raw)
            # r.translation_status = "done"
    return records


# ---------------------------------------------------------------------------
# 6. Storage — append-only, timestamped, so we retain every pull
#    (never overwrite — multi-timestamp comparison is the whole point)
# ---------------------------------------------------------------------------

def write_records(records: list[PriceRecord], cfg: PipelineConfig) -> Path:
    cfg.output_dir.mkdir(parents=True, exist_ok=True)
    stamp = datetime.now(timezone.utc).strftime("%Y%m%dT%H%M%SZ")
    out_path = cfg.output_dir / f"tiktok_shop_th_{stamp}.jsonl"
    with out_path.open("w", encoding="utf-8") as f:
        for r in records:
            f.write(json.dumps(asdict(r), ensure_ascii=False) + "\n")
    log.info(f"Wrote {len(records)} records -> {out_path}")
    return out_path


# ---------------------------------------------------------------------------
# 7. Orchestration
# ---------------------------------------------------------------------------

def run_pull(
    cfg: PipelineConfig, token: str,
    brand_filter: Optional[list[str]] = None, dry_run: bool = False,
) -> Optional[Path]:
    all_records: list[PriceRecord] = []

    if brand_filter:
        configured = {b.lower().replace("&", "and") for b in cfg.brands}
        unmatched = [b for b in brand_filter if b.lower().replace("&", "and") not in configured]
        if unmatched:
            log.warning(f"--brand name(s) not in cfg.brands, will be silently skipped: {unmatched} "
                        f"(configured brands: {list(cfg.brands)})")

    for brand, terms in cfg.brands.items():
        # Normalize "&"/"and" so "--brand \"Clean & Clear\"" matches the
        # config's official "Clean and Clear" key -- an exact-string match
        # here silently skipped the brand entirely with no warning (see
        # 2026-07-29 run), which looks identical to "ran fine, zero results".
        if brand_filter:
            norm_filter = {b.lower().replace("&", "and") for b in brand_filter}
            if brand.lower().replace("&", "and") not in norm_filter:
                continue
        try:
            raw_listings = fetch_raw_listings(brand, terms, cfg, token, dry_run=dry_run)
        except Exception as e:
            log.error(f"Fetch failed for brand '{brand}': {e}")
            continue

        for raw in raw_listings:
            try:
                all_records.append(normalize_record(raw, brand, cfg))
            except Exception as e:
                log.warning(f"Skipping unparseable listing for '{brand}': {e}")

    if dry_run:
        log.info(f"[DRY-RUN] Parsed {len(all_records)} records (not written to disk):")
        for r in all_records:
            log.info(f"  {r.brand:15} | {r.current_price!s:>10} {r.currency} | {r.product_name_raw}")
        return None

    all_records = translate_pending(all_records)
    return write_records(all_records, cfg)


if __name__ == "__main__":
    parser = argparse.ArgumentParser(description="TikTok Shop TH pricing pull (via Apify)")
    parser.add_argument("--brand", nargs="+", help='e.g. --brand "Acne-Aid" "CeraVe""')
    parser.add_argument("--max-items", type=int, default=20, help="Per-search-term item cap")
    parser.add_argument("--dry-run", action="store_true",
                         help="Dump raw Apify output to data/tiktok_shop/tiktok_raw_*.json and print "
                              "parsed rows, but do NOT write the timestamped JSONL output")
    args = parser.parse_args()

    apify_token = os.getenv("APIFY_TOKEN")
    if not apify_token:
        log.error("APIFY_TOKEN not set in .env")
        raise SystemExit(1)

    cfg = PipelineConfig(max_items_per_term=args.max_items)
    run_pull(cfg, apify_token, brand_filter=args.brand, dry_run=args.dry_run)
