"""
Build data/acneaid_th_tiktok_shop_pricing.csv from the raw
data/tiktok_shop/tiktok_shop_th_*.jsonl pulls (tiktok_pipeline.py, root).

Why a separate build step instead of reading the jsonl live in the app:
(1) tiktok_pipeline.py's PriceRecord schema is missing pack_size/category/
review_count/avg_rating -- pack_size and category are derivable from
product_name_raw (same keyword/regex approach as Boots/Shopee/Lazada), but
review_count/avg_rating simply aren't in the raw TikTok Shop data and stay
None; (2) there are multiple timestamped pull files (one per run) that
need merging + deduping by record_id, plus a known placeholder/test file
(2026-07-24, fake product/111 and product/222 URLs) that must be excluded
-- detected by real TikTok Shop product IDs always being long (16+ digit)
numeric strings vs. the placeholder's 3-digit fake IDs, not by hardcoding
that file's name (future placeholder-like test runs would hit the same
filter); (3) brand names in the raw pulls already match config.py's
canonical spelling, but rows for brands outside config.ALL_TRACKED_BRANDS
(if the pipeline's brand dict ever drifts) are dropped, not guessed at.

Run after a fresh TikTok Shop pull lands in data/tiktok_shop/:
    python dashboard/acneaid_dashboard/scripts/build_tiktok_shop_pricing_csv.py
(4) sku_query_master.csv is the project's canonical SKU/brand coverage file
(sku_key, priority, format, brand, product_name, query, is_flagged,
flag_note -- one row per SKU x competitor-brand pairing). This script cross-
checks its `brand` column against config.ALL_TRACKED_BRANDS and the local
_BRAND_ALIASES gate below, and warns (does not silently pass) if the master
file lists a brand neither of those knows about -- catches brand-roster
drift at the source of truth rather than only at config.py's copy of it.
sku_query_master.csv's product_name/query columns are SKU-level competitor
product names, not brand spelling variants, so they aren't used to build
the alias list itself -- that stays hand-maintained in _BRAND_ALIASES
below (Thai script, hyphenation, etc., none of which the master file
carries).
"""
from __future__ import annotations

import csv
import json
import re
import sys
from datetime import datetime, timezone
from pathlib import Path

PROJECT_ROOT = Path(__file__).resolve().parent.parent  # dashboard/acneaid_dashboard
REPO_ROOT = PROJECT_ROOT.parent.parent
TIKTOK_DIR = REPO_ROOT / "data" / "tiktok_shop"
DATA_DIR = PROJECT_ROOT / "data"

# Stable filename other scripts (build_facts.py's load_tiktok_shop()) read --
# refreshed on every run so downstream doesn't need to know about timestamps.
OUT_CSV_LATEST = DATA_DIR / "acneaid_th_tiktok_shop_pricing.csv"
# Per-run timestamped snapshot -- the primary output artifact, kept forever
# as an audit trail (same append-only-history principle as
# tiktok_pipeline.py's own tiktok_shop_th_*.jsonl naming).
_RUN_STAMP = datetime.now(timezone.utc).strftime("%Y%m%dT%H%M%SZ")
OUT_CSV_TIMESTAMPED = DATA_DIR / f"acneaid_th_tiktok_shop_pricing_{_RUN_STAMP}.csv"

SKU_MASTER_PATH = REPO_ROOT / "sku_query_master.csv"

sys.path.insert(0, str(PROJECT_ROOT / "app"))
from lib import config  # noqa: E402


def _load_master_brands() -> set[str]:
    """Reads sku_query_master.csv's `brand` column. Returns empty set (with
    a warning) if the file is missing rather than crashing -- this check is
    a cross-verification, not a hard dependency."""
    if not SKU_MASTER_PATH.exists():
        print(f"  [WARN] sku_query_master.csv not found at {SKU_MASTER_PATH} -- "
              "skipping brand-roster cross-check")
        return set()
    with open(SKU_MASTER_PATH, encoding="utf-8-sig", newline="") as f:
        reader = csv.DictReader(f)
        return {row["brand"].strip() for row in reader if row.get("brand")}


def _check_brand_roster_drift() -> None:
    master_brands = _load_master_brands()
    if not master_brands:
        return
    tracked = set(config.ALL_TRACKED_BRANDS)
    aliased = set(_BRAND_ALIASES.keys())
    missing_from_tracked = master_brands - tracked
    missing_from_aliases = master_brands - aliased
    if missing_from_tracked:
        print(f"  [WARN] sku_query_master.csv brands not in config.ALL_TRACKED_BRANDS: "
              f"{sorted(missing_from_tracked)}")
    if missing_from_aliases:
        print(f"  [WARN] sku_query_master.csv brands with no _BRAND_ALIASES entry "
              f"(brand-mention gate will fail OPEN / not gate them): {sorted(missing_from_aliases)}")
    if not missing_from_tracked and not missing_from_aliases:
        print(f"  [OK] sku_query_master.csv's {len(master_brands)} brands all covered "
              "by config.ALL_TRACKED_BRANDS and _BRAND_ALIASES")

COLUMNS = [
    "brand", "site", "store_name", "name_th_or_en", "pack_size", "category",
    "sell_price", "normal_price", "review_count", "avg_rating", "currency",
    "url", "scraped_at", "snapshot_label",
]

# Per rules.md Rule 10's snapshot-labeling convention. Real known pull dates
# only -- never inferred/guessed (Rule 10's backfill rule). TikTok Shop has
# no july_baseline single date (channel-dependent per Rule 10's table); its
# actual pre-8.8 pulls landed 2026-07-29 (see data/tiktok_shop/tiktok_shop_th_
# 20260729T*.jsonl -- the 2026-07-24 files are the excluded placeholder/test
# pull, filtered out in read_records() before this ever runs). 2026-08-08
# matches Rule 10's "all others" 8.8-sale pull date exactly.
_SNAPSHOT_LABELS = {
    "2026-07-29": "july_baseline",
    "2026-08-08": "8.8_sale_2026-08-08",
    # Routine post-sale refresh, not a sale event and not baseline -- not
    # the "~2 weeks out"/9.9 snapshot Rule 10 flags either (that's TBD,
    # anchored around 2026-09-09 per dim_date.csv, not this date).
    "2026-08-27": "refresh_2026-08-27",
}


def _snapshot_label(pulled_at_utc: str) -> str:
    """Never silently blends an unmapped pull date into an existing label --
    flags it instead so a new snapshot gets a deliberate label added to
    _SNAPSHOT_LABELS above (per Rule 10 item 3) rather than inheriting one
    by accident."""
    date = (pulled_at_utc or "")[:10]
    label = _SNAPSHOT_LABELS.get(date)
    if label is None:
        print(f"  [WARN] no snapshot_label mapping for pull date {date!r} -- "
              "add one to _SNAPSHOT_LABELS before trusting this row in a "
              "cross-snapshot comparison")
        label = f"unlabeled_{date}" if date else "unlabeled"
    return label

_PACK_SIZE_RE = re.compile(r"(\d+(?:\.\d+)?)\s*(ml|g)\b", re.IGNORECASE)
_REAL_PRODUCT_ID_RE = re.compile(r"/product/(\d+)")

# Brand -> alias/search-term list, mirrors tiktok_pipeline.py's PipelineConfig.brands
# exactly. Used as a title-must-contain-alias gate: the TikTok Shop keyword-search
# actor (pratikdani/tiktok-shop-search-scraper) does loose relevance matching, not
# exact-brand search, so a search for "clean and clear" can surface totally
# unrelated listings (a kids' floor mat, a phone screen protector, a Buddhist
# candle whose product line happens to be named "Clean & Clear", a wrong-brand
# sunscreen) that get silently tagged with the searched brand and no downstream
# check. Confirmed 2026-08-08: 4/13 Clean & Clear TikTok Shop rows were exactly
# this failure mode. Applying the same per-brand alias check tiktok_pipeline.py
# already uses to SEARCH also gates ACCEPTANCE, closing the loop.
_BRAND_ALIASES = {
    "Acne-Aid": ["acne aid", "acne-aid", "acneaid", "แอคเน่ เอด", "แอคเน่เอด"],
    "CeraVe": ["cerave", "cera ve"],
    "Cetaphil": ["cetaphil"],
    "Neutrogena": ["neutrogena"],
    "Eucerin": ["eucerin"],
    "Smooth E": ["smooth e", "smoothe"],
    "Clean and Clear": ["clean and clear", "clean & clear", "clean&clear", "cleanandclear"],
    "Oxe'Cure": ["oxe'cure", "oxecure", "oxe cure"],
}


def _brand_mentioned_in_title(brand: str, name: str) -> bool:
    """True if the product title actually contains the brand (or a known
    alias), case-insensitive. Fails OPEN (returns True) for brands not in
    _BRAND_ALIASES so an unmapped/new brand isn't silently dropped -- the
    known contamination pattern is specific to keyword-search false
    positives on the brands we actively search for."""
    aliases = _BRAND_ALIASES.get(brand)
    if not aliases:
        return True
    key = (name or "").lower()
    return any(alias in key for alias in aliases)


def _parse_pack_size(name: str) -> str | None:
    if not name:
        return None
    m = _PACK_SIZE_RE.search(name)
    return f"{m.group(1)}{m.group(2).lower()}" if m else None


def _derive_category(name: str) -> str:
    """Same keyword match as build_lazada_pricing_csv.py's _derive_category
    -- input here is a full (often Thai-script) product name, not a short
    category label, so an honest "Other/Unclassified" fallback is used
    instead of transforms.bucket_functionality()'s verbatim-passthrough
    fallback (which is only appropriate for Boots/Shopee's real short
    category field)."""
    if not name:
        return "Other/Unclassified"
    key = name.lower()
    for needle, bucket in config.FUNCTIONALITY_MAP.items():
        if needle in key:
            return bucket
    return "Other/Unclassified"


def _is_placeholder(sku_url: str) -> bool:
    """The 2026-07-24 test pull used fake URLs like .../product/111 and
    .../product/222 -- real TikTok Shop product IDs are long (16+ digit)
    numeric strings, so a short numeric ID is a reliable placeholder
    signal regardless of which file it's in."""
    m = _REAL_PRODUCT_ID_RE.search(sku_url or "")
    return bool(m) and len(m.group(1)) < 10


def read_records() -> list[dict]:
    seen_ids: set[str] = set()
    out = []
    for path in sorted(TIKTOK_DIR.glob("tiktok_shop_th_*.jsonl")):
        if path.stat().st_size == 0:
            continue
        with open(path, encoding="utf-8") as f:
            for line in f:
                line = line.strip()
                if not line:
                    continue
                rec = json.loads(line)
                record_id = rec.get("record_id")
                if not record_id or record_id in seen_ids:
                    continue
                if _is_placeholder(rec.get("sku_url", "")):
                    continue
                seen_ids.add(record_id)
                out.append(rec)
    return out


def build_rows(records: list[dict]) -> tuple[list[dict], list[dict]]:
    """Returns (accepted_rows, rejected_rows). Rejected rows are kept (not
    discarded) so they can be reviewed / re-triaged rather than silently
    vanishing -- same principle as tiktok_pipeline.py's own dry-run dumps."""
    out = []
    rejected = []
    for rec in records:
        brand = rec.get("brand")
        if brand not in config.ALL_TRACKED_BRANDS:
            continue
        name = rec.get("product_name_raw") or ""
        row = {
            "brand": brand,
            "site": "tiktok_shop",
            "store_name": rec.get("seller_name") or "",
            "name_th_or_en": name,
            "pack_size": _parse_pack_size(name),
            "category": _derive_category(name),
            "sell_price": rec.get("current_price"),
            "normal_price": rec.get("list_price"),
            "review_count": None,
            "avg_rating": None,
            "currency": rec.get("currency") or "THB",
            "url": rec.get("sku_url") or "",
            "scraped_at": rec.get("pulled_at_utc") or "",
            "snapshot_label": _snapshot_label(rec.get("pulled_at_utc") or ""),
        }
        if _brand_mentioned_in_title(brand, name):
            out.append(row)
        else:
            row["reject_reason"] = "brand_not_in_title"
            rejected.append(row)
    return out, rejected


REJECTED_CSV = DATA_DIR / f"acneaid_th_tiktok_shop_pricing_rejected_{_RUN_STAMP}.csv"


def main():
    print("Checking brand roster against sku_query_master.csv ...")
    _check_brand_roster_drift()
    print()

    records = read_records()
    rows, rejected = build_rows(records)

    # before-counts include what would have shipped pre-fix (accepted + rejected)
    before_by_brand: dict[str, int] = {}
    for r in rows + rejected:
        before_by_brand[r["brand"]] = before_by_brand.get(r["brand"], 0) + 1

    DATA_DIR.mkdir(parents=True, exist_ok=True)

    # Write the timestamped snapshot -- the durable, never-overwritten artifact.
    with open(OUT_CSV_TIMESTAMPED, "w", newline="", encoding="utf-8-sig") as f:
        writer = csv.DictWriter(f, fieldnames=COLUMNS)
        writer.writeheader()
        writer.writerows(rows)
    print(f"Wrote {len(rows)} accepted rows to {OUT_CSV_TIMESTAMPED}")

    # Refresh the stable filename downstream scripts (build_facts.py) read.
    with open(OUT_CSV_LATEST, "w", newline="", encoding="utf-8-sig") as f:
        writer = csv.DictWriter(f, fieldnames=COLUMNS)
        writer.writeheader()
        writer.writerows(rows)
    print(f"Refreshed {OUT_CSV_LATEST} (same content, stable name for downstream scripts)")

    if rejected:
        with open(REJECTED_CSV, "w", newline="", encoding="utf-8-sig") as f:
            writer = csv.DictWriter(f, fieldnames=COLUMNS + ["reject_reason"])
            writer.writeheader()
            writer.writerows(rejected)
        print(f"Wrote {len(rejected)} rejected rows (brand not in title) to {REJECTED_CSV} for review")

    by_brand: dict[str, int] = {}
    for row in rows:
        by_brand[row["brand"]] = by_brand.get(row["brand"], 0) + 1

    print("\nBefore -> After (accepted) per brand:")
    for brand in sorted(before_by_brand):
        before_n = before_by_brand.get(brand, 0)
        after_n = by_brand.get(brand, 0)
        flag = "  <-- rows removed" if after_n < before_n else ""
        print(f"  {brand}: {before_n} -> {after_n}{flag}")

    missing = [b for b in config.ALL_TRACKED_BRANDS if b not in by_brand]
    if missing:
        print(f"  (no TikTok Shop rows for: {', '.join(missing)})")


if __name__ == "__main__":
    main()
