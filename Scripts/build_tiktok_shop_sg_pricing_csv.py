"""
build_tiktok_shop_sg_pricing_csv.py

SG equivalent of the TH project's build_tiktok_shop_pricing_csv.py -- the
labeling/CSV-build step that runs AFTER tiktok_pipeline_sg.py's raw pull,
same relationship the TH original has to tiktok_pipeline.py.

WHY THIS EXISTS: tiktok_pipeline_sg.py's own PriceRecord rows are close to
raw -- brand comes straight from which search term found the listing, not
from checking the listing actually mentions that brand. Confirmed 2026-09-24
against real SG raw pulls (data/tiktok_shop_sg/tiktok_raw_*.json) this is a
real problem here too, same failure mode the TH script's own header
describes (4/13 Clean & Clear rows were unrelated products): EVERY
CooperVision row in the sampled raw pull is a false positive -- security
cameras and night-vision goggles/telescopes, matched on the generic word
"vision" in TikTok's loose keyword search, zero actual CooperVision lens
products. Bausch + Lomb and Olens rows, by contrast, were all genuine. This
script applies the same title-must-contain-brand-alias gate the TH script
uses, closing the loop between what was SEARCHED and what gets ACCEPTED.

Differences from the TH original (besides market/currency/brand roster):
  - No separate sku_query_master.csv / config.py to cross-check against in
    this project (see day_1_plan.md -- SG brand/keyword master lives
    directly in tiktok_pipeline_sg.py's PipelineConfig.brands). This script
    imports that dict directly as both the alias-gate source AND the known-
    brand filter, instead of hand-maintaining a second copy the way the TH
    script's _BRAND_ALIASES does -- one source of truth, can't drift from
    the actual search terms used.
  - review_count/avg_rating: the TH script's header notes these "simply
    aren't in the raw TikTok Shop data" for TH. NOT true for SG -- confirmed
    2026-09-24 against raw Alcon/MyACUVUE pulls, both fields are present in
    the actor's raw item (`review_count`, `product_rating`), just null on
    some listings. tiktok_pipeline_sg.py's PriceRecord now carries these
    through (added alongside this script) -- passed through here as-is, not
    None like the TH build script does.
  - category taxonomy is contact-lens-specific (Daily/Biweekly/Monthly/
    Colored/Solution/Eye Drops/Supplement), built from context.md's ACUVUE
    product line + competitor brand notes, not the skincare
    config.FUNCTIONALITY_MAP bucket set the TH script reads.
  - No snapshot_label curation exists yet for this project (TH's Rule 10 /
    _SNAPSHOT_LABELS was built from months of known TH sale-event dates).
    Every pull date here is unlabeled by default -- add real event labels to
    _SNAPSHOT_LABELS below once SG sale-event dates are actually tracked,
    same "never silently blend into an existing label" discipline as the
    TH original.

Run after a fresh SG TikTok Shop pull lands in data/tiktok_shop_sg/:
    python build_tiktok_shop_sg_pricing_csv.py
"""
from __future__ import annotations

import csv
import json
import re
import sys
from datetime import datetime, timezone
from pathlib import Path

from tiktok_pipeline_sg import PipelineConfig  # single source of truth for brand/alias terms

SCRIPT_DIR = Path(__file__).resolve().parent
DATA_DIR = SCRIPT_DIR / "data" / "tiktok_shop_sg"

OUT_CSV_LATEST = DATA_DIR / "tiktok_shop_sg_pricing_labeled.csv"
_RUN_STAMP = datetime.now(timezone.utc).strftime("%Y%m%dT%H%M%SZ")
OUT_CSV_TIMESTAMPED = DATA_DIR / f"tiktok_shop_sg_pricing_labeled_{_RUN_STAMP}.csv"
REJECTED_CSV = DATA_DIR / f"tiktok_shop_sg_pricing_rejected_{_RUN_STAMP}.csv"

_CFG = PipelineConfig()
KNOWN_BRANDS = set(_CFG.brands)
_BRAND_ALIASES = {brand: [t.lower() for t in terms] for brand, terms in _CFG.brands.items()}

COLUMNS = [
    "brand", "site", "store_name", "product_name", "pack_size", "category",
    "sell_price", "normal_price", "is_promo", "promo_label",
    "review_count", "avg_rating", "currency", "url", "priority_tier",
    "scraped_at", "snapshot_label",
]

# No curated SG sale-event calendar exists yet (see module docstring) --
# add real dates here once tracked, same discipline as the TH project's
# Rule 10 table. Every pull date falls through to "unlabeled_<date>" until
# then, which is visible/greppable rather than silently blended together.
_SNAPSHOT_LABELS: dict[str, str] = {}


def _snapshot_label(pulled_at_utc: str) -> str:
    date = (pulled_at_utc or "")[:10]
    label = _SNAPSHOT_LABELS.get(date)
    if label is None:
        label = f"unlabeled_{date}" if date else "unlabeled"
    return label


def _brand_mentioned_in_title(brand: str, name: str) -> bool:
    """True if the product title actually contains the brand or one of the
    same search-term aliases tiktok_pipeline_sg.py used to find it. Fails
    OPEN (returns True) for a brand with no alias list configured, so an
    unmapped/new brand isn't silently dropped -- mirrors the TH script's
    same fail-open rule."""
    aliases = _BRAND_ALIASES.get(brand)
    if not aliases:
        return True
    key = (name or "").lower()
    return any(alias in key for alias in aliases)


# Contact-lens pack sizing shows up as volume (ml/L, solutions/eye drops),
# unit counts (pairs/pcs/vials, lenses), or box multiples ("x 3") -- broader
# than the TH skincare script's ml/g-only regex. Order matters: try the more
# specific unit patterns before the bare "x N" multiplier so e.g.
# "300mL x 3" reports as "300ml x3" not just "x3".
_PACK_SIZE_RE = re.compile(
    r"(\d+(?:\.\d+)?\s*m?[lL]\s*(?:x\s*\d+)?)"      # 300mL, 10ML, 300mL x 3
    r"|(\d+\s*(?:pairs?|p)\b)"                        # 5 Pairs, 2P
    r"|(\d+\s*(?:pcs|vials?|softgels?|tablets?))"     # 24 vials, 120 softgels
    r"|(\d+\s*(?:day|month)s?\b)",                     # 1 Day, 1 Month (wear schedule, not a count,
    re.IGNORECASE,                                     # but the only "size" info some titles carry
)


def _parse_pack_size(name: str) -> str | None:
    if not name:
        return None
    m = _PACK_SIZE_RE.search(name)
    if not m:
        return None
    return next(g for g in m.groups() if g).strip()


# Category priority matters: check colored/cosmetic BEFORE wear-schedule,
# since e.g. "1 DAY ACUVUE Define ... Color Contact Lenses" is both --
# context.md itself buckets ACUVUE Define under "color/cosmetic lenses"
# first, wear schedule second.
_CATEGORY_RULES: list[tuple[str, list[str]]] = [
    ("Colored/Cosmetic Lens", ["color", "colour", "define", "olens", "circle lens", "cosmetic lens"]),
    ("Daily Disposable Lens", ["1 day", "1-day", "1day", "daily disposable", "clariti", "myday"]),
    ("Biweekly Lens", ["2 week", "2-week", "biweekly", "oasys"]),
    ("Monthly Lens", ["1 month", "monthly", "biofinity", "total30", "air optix"]),
    ("Lens Solution/Care", ["solution", "multi-purpose", "multipurpose", "disinfecting", "renu",
                             "opti-free", "optic-free", "lens case"]),
    ("Eye Drops/Lubricant", ["eye drop", "eyedrop", "lubricant", "systane", "tears naturale"]),
    ("Supplement/Vitamin", ["vitamin", "areds", "softgel", "supplement"]),
]


def _derive_category(name: str) -> str:
    if not name:
        return "Other/Unclassified"
    key = name.lower()
    for bucket, needles in _CATEGORY_RULES:
        if any(needle in key for needle in needles):
            return bucket
    return "Other/Unclassified"


def read_records() -> list[dict]:
    seen_ids: set[str] = set()
    out = []
    for path in sorted(DATA_DIR.glob("tiktok_shop_sg_*.jsonl")):
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
                seen_ids.add(record_id)
                out.append(rec)
    return out


def build_rows(records: list[dict]) -> tuple[list[dict], list[dict]]:
    """Returns (accepted_rows, rejected_rows). Rejected rows are kept, not
    discarded, so the false-positive matches (like the CooperVision/security-
    camera example above) stay reviewable instead of silently vanishing."""
    out = []
    rejected = []
    for rec in records:
        brand = rec.get("brand")
        if brand not in KNOWN_BRANDS:
            continue
        name = rec.get("product_name_raw") or ""
        row = {
            "brand": brand,
            "site": "tiktok_shop",
            "store_name": rec.get("seller_name") or "",
            "product_name": name,
            "pack_size": _parse_pack_size(name),
            "category": _derive_category(name),
            "sell_price": rec.get("current_price"),
            "normal_price": rec.get("list_price"),
            "is_promo": rec.get("is_promo"),
            "promo_label": rec.get("promo_label"),
            "review_count": rec.get("review_count"),
            "avg_rating": rec.get("avg_rating"),
            "currency": rec.get("currency") or "SGD",
            "url": rec.get("sku_url") or "",
            "priority_tier": rec.get("priority_tier"),
            "scraped_at": rec.get("pulled_at_utc") or "",
            "snapshot_label": _snapshot_label(rec.get("pulled_at_utc") or ""),
        }
        if _brand_mentioned_in_title(brand, name):
            out.append(row)
        else:
            row["reject_reason"] = "brand_not_in_title"
            rejected.append(row)
    return out, rejected


def main():
    if not DATA_DIR.exists():
        print(f"[ERROR] {DATA_DIR} does not exist -- run tiktok_pipeline_sg.py first", file=sys.stderr)
        raise SystemExit(1)

    records = read_records()
    if not records:
        print(f"[WARN] No tiktok_shop_sg_*.jsonl pulls found in {DATA_DIR} -- nothing to build")
        raise SystemExit(0)

    rows, rejected = build_rows(records)

    before_by_brand: dict[str, int] = {}
    for r in rows + rejected:
        before_by_brand[r["brand"]] = before_by_brand.get(r["brand"], 0) + 1

    with open(OUT_CSV_TIMESTAMPED, "w", newline="", encoding="utf-8-sig") as f:
        writer = csv.DictWriter(f, fieldnames=COLUMNS)
        writer.writeheader()
        writer.writerows(rows)
    print(f"Wrote {len(rows)} accepted rows to {OUT_CSV_TIMESTAMPED}")

    with open(OUT_CSV_LATEST, "w", newline="", encoding="utf-8-sig") as f:
        writer = csv.DictWriter(f, fieldnames=COLUMNS)
        writer.writeheader()
        writer.writerows(rows)
    print(f"Refreshed {OUT_CSV_LATEST} (same content, stable name for downstream use)")

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

    missing = [b for b in KNOWN_BRANDS if b not in by_brand]
    if missing:
        print(f"  (no TikTok Shop rows for: {', '.join(missing)})")


if __name__ == "__main__":
    main()
