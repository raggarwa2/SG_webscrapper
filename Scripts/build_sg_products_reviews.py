"""Consolidates SG product/pricing/review sources into sg_acuvue.db.

Sources:
  - Scripts/output/tiktok_shop_sg_pricing_labeled.csv  (TikTok Shop listings, no review text)
  - Scripts/output/test_colored_lens.db  (Lazada colored/cosmetic lens listings + reviews)
  - Scripts/output/test_solutions.db     (Lazada lens-solution/eye-drop listings + reviews)

Writes two tables into Scripts/output/sg_acuvue.db:
  - products: one row per distinct SKU/listing across all three sources
  - reviews:  one row per individual Lazada review (TikTok Shop data has no
              review text, only aggregate avg_rating/review_count on the
              product row itself)

Both tables are dropped and rebuilt on every run — the source CSVs/DBs are
the source of truth, this is not an incremental append.

sentiment/attribute_tags/attribute_notes/confidence columns are created on
`reviews` and left NULL here; extract_sentiment_sg.py fills them in a
separate (costed, LLM-backed) pass.

Run with:
    python Scripts/build_sg_products_reviews.py
"""

import os
import re
import sqlite3
from datetime import datetime, timedelta, timezone

import pandas as pd

from journey_stage_map import COMPLIANCE_JOURNEY_STAGE, journey_stage_for

BASE_DIR = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
OUTPUT_DIR = os.path.join(BASE_DIR, "Scripts", "output")

TIKTOK_CSV = os.path.join(OUTPUT_DIR, "tiktok_shop_sg_pricing_labeled.csv")
COLORED_LENS_DB = os.path.join(OUTPUT_DIR, "test_colored_lens.db")
SOLUTIONS_DB = os.path.join(OUTPUT_DIR, "test_solutions.db")
SG_DB = os.path.join(OUTPUT_DIR, "sg_acuvue.db")

# Raw scraped brand string -> tracked brand_group used by the dashboard's
# brand filter/color palette (mirrors HK app.py's BRAND_COLORS keys, plus
# "Other" for solution/eye-drop/colored-lens SKUs that don't belong to one
# of the five tracked competitor brands).
BRAND_GROUP_MAP = {
    "myacuvue": "Acuvue",
    "acuvue": "Acuvue",
    "alcon": "Alcon",
    "opti free": "Alcon",       # Opti-Free is an Alcon solution line
    "opti-free": "Alcon",
    "bausch + lomb": "Bausch & Lomb",
    "bausch & lomb": "Bausch & Lomb",
    "coopervision": "CooperVision",
    "olens": "Olens",
    "renu": "Bausch & Lomb",    # ReNu is a Bausch & Lomb solution brand
    "blink": "Other",
    "no brand": "Other",
}


def brand_group_for(raw_brand: str) -> str:
    if not raw_brand or pd.isna(raw_brand):
        return "Other"
    return BRAND_GROUP_MAP.get(str(raw_brand).strip().lower(), "Other")


def to_float(val):
    try:
        if val is None or (isinstance(val, str) and val.strip() == ""):
            return None
        if isinstance(val, float) and pd.isna(val):
            return None
        f = float(val)
        return None if pd.isna(f) else f
    except (ValueError, TypeError):
        return None


def to_int(val):
    f = to_float(val)
    return int(f) if f is not None else None


_RELATIVE_DATE_RE = re.compile(
    r"(\d+)\s+(day|week|month|year)s?\s+ago", re.I
)


def parse_review_date(date_str: str, pulled_at: str):
    """Lazada review dates are a mix of ISO dates ('2025-11-19') and relative
    strings ('1 week ago', '5 days ago'). Relative strings are resolved
    against the row's own pulled_at scrape timestamp (not "now") so re-running
    this script later doesn't shift historical review dates."""
    if not date_str or pd.isna(date_str) or str(date_str).strip() == "":
        return None
    date_str = str(date_str).strip()
    m = _RELATIVE_DATE_RE.match(date_str)
    if m:
        n, unit = int(m.group(1)), m.group(2).lower()
        try:
            ref = pd.to_datetime(pulled_at, errors="coerce", utc=True)
        except Exception:
            ref = None
        if ref is None or pd.isna(ref):
            return None
        delta_days = {"day": 1, "week": 7, "month": 30, "year": 365}[unit] * n
        return (ref - timedelta(days=delta_days)).strftime("%Y-%m-%d")
    parsed = pd.to_datetime(date_str, errors="coerce")
    return parsed.strftime("%Y-%m-%d") if pd.notna(parsed) else None


# Rows that are obviously not lens/lens-care products at all, mismatched by
# the brand/category labeler's keyword collision (documented in scripts.md:
# "CooperVision pull was 100% junk, matched on 'vision'"). Matched on
# substrings in product_name; excluded from `products` entirely rather than
# flagged, since they're not lens data of any kind, compliance or otherwise.
_JUNK_PRODUCT_NAME_SUBSTRINGS = ["tempered glass", "screen protector"]

# TikTok Shop categories that are actual contact lenses (as opposed to
# solutions/eye-drops/supplements). A tracked-brand listing in one of these
# categories, sold by an ordinary TikTok Shop seller rather than the brand's
# own official store, is the same illegal-online-powered-lens pattern flagged
# in sku_query_master_sg.csv's is_flagged/flag_note columns (HSA finding:
# direct online sale of contact lenses -- powered or cosmetic -- to
# consumers is illegal in SG) -- a compliance/brand-protection signal, not
# ordinary consideration/purchase product data.
_ACTUAL_LENS_CATEGORIES = {"Daily Disposable Lens", "Biweekly Lens", "Colored/Cosmetic Lens"}


def _is_junk_row(product_name: str) -> bool:
    name = str(product_name).lower()
    return any(s in name for s in _JUNK_PRODUCT_NAME_SUBSTRINGS)


def load_tiktok_products() -> pd.DataFrame:
    df = pd.read_csv(TIKTOK_CSV)
    df.columns = [c.strip().lstrip("﻿") for c in df.columns]

    junk_mask = df["product_name"].apply(_is_junk_row)
    if junk_mask.any():
        print(f"Dropping {junk_mask.sum()} junk row(s) (keyword-collision false positives):")
        for _, r in df[junk_mask].iterrows():
            print(f"  - [{r['brand']}] {r['product_name'][:80]}")
    df = df[~junk_mask].reset_index(drop=True)

    out = pd.DataFrame(
        {
            "source_sku": df["url"],  # TikTok Shop URL is the stable per-listing key
            "listed_brand": df["brand"],
            "brand": df["brand"].apply(brand_group_for),
            "product_name": df["product_name"],
            "pack_size": df["pack_size"],
            "category": df["category"],
            "site": "tiktok_shop",
            "store_name": df["store_name"],
            "currency": df["currency"],
            "selling_price": df["sell_price"].apply(to_float),
            "original_price": df["normal_price"].apply(to_float),
            "is_promo": df["is_promo"].astype(bool),
            "promo_label": df["promo_label"],
            "avg_rating": df["avg_rating"].apply(to_float),
            "review_count": df["review_count"].apply(to_int),
            "url": df["url"],
            "priority_tier": df["priority_tier"],
            "scraped_at": df["scraped_at"],
        }
    )
    # A tracked-brand (not "Other") listing of an actual lens category on an
    # ordinary TikTok Shop seller storefront -- not the brand's own official
    # store -- is a grey-market/compliance signal, not normal product data.
    # No "official store" field exists in this scrape, so this flags every
    # such listing; a follow-up pass could narrow this if official-store
    # metadata becomes available.
    out["compliance_flag"] = (out["brand"] != "Other") & out["category"].isin(_ACTUAL_LENS_CATEGORIES)
    return out


def _lazada_category_for(row) -> str:
    name = str(row.get("ProductName", "")).lower()
    if "eye drop" in name or str(row.get("Brand", "")).strip().lower() == "blink":
        return "Eye Drops/Lubricant"
    return "Lens Solution/Care"


def load_lazada_db(path: str, category_fn, is_grey_market_monitor: bool = False) -> tuple[pd.DataFrame, pd.DataFrame]:
    """Returns (products_df, reviews_df) for one Lazada test db. Each db has
    one row per (SKU, review) pair, with product-level fields (Price,
    OverallRating, ...) repeated on every row for that SKU, and review-level
    fields (Date, Reviewer, Rating, ReviewText) blank on rows with no review.

    is_grey_market_monitor=True (test_colored_lens.db) means every row in
    this db IS the compliance-monitor output itself (confirmed by
    sku_query_master_sg.csv's flag_note, which cites this exact file as
    evidence of the illegal-powered/cosmetic-lens-listing pattern) -- so
    every product from it is flagged, not treated as ordinary product data."""
    conn = sqlite3.connect(path)
    raw = pd.read_sql_query("SELECT * FROM lazada_data", conn)
    conn.close()

    products_rows = []
    for sku, grp in raw.groupby("SKU"):
        first = grp.iloc[0]
        category = category_fn(first) if category_fn == _lazada_category_for else "Colored/Cosmetic Lens"
        products_rows.append(
            {
                "source_sku": sku,
                "listed_brand": first["Brand"],
                "brand": brand_group_for(first["Brand"]),
                "product_name": first["ProductName"],
                "pack_size": first["PackSize"],
                "category": category,
                "site": "lazada_sg",
                "store_name": first["SellerType"],
                "currency": "SGD",
                "selling_price": to_float(first["Price"]),
                "original_price": to_float(first["OriginalPrice"]),
                "is_promo": to_float(first["OriginalPrice"]) is not None
                and to_float(first["Price"]) is not None
                and to_float(first["OriginalPrice"]) > to_float(first["Price"]),
                "promo_label": None,
                "avg_rating": to_float(first["OverallRating"]),
                "review_count": to_int(first["TotalReviews"]),
                "url": None,
                "priority_tier": first.get("priority"),
                "scraped_at": first["pulled_at"],
                "compliance_flag": is_grey_market_monitor,
            }
        )
    products_df = pd.DataFrame(products_rows)

    review_rows = []
    reviewed = raw[raw["ReviewText"].astype(str).str.strip() != ""]
    for _, r in reviewed.iterrows():
        review_rows.append(
            {
                "source_sku": r["SKU"],
                "brand": brand_group_for(r["Brand"]),
                "listed_brand": r["Brand"],
                "site": "lazada_sg",
                "store_name": r["SellerType"],
                "reviewer": r["Reviewer"],
                "rating": to_int(r["Rating"]),
                "review_text": r["ReviewText"],
                "review_date": parse_review_date(r["Date"], r["pulled_at"]),
                "helpful_count": to_int(r["Helpful"]),
                "scraped_at": r["pulled_at"],
            }
        )
    reviews_df = pd.DataFrame(review_rows)
    return products_df, reviews_df


def build():
    tiktok_products = load_tiktok_products()
    colored_products, colored_reviews = load_lazada_db(
        COLORED_LENS_DB, category_fn=lambda row: "Colored/Cosmetic Lens",
        is_grey_market_monitor=True,
    )
    solutions_products, solutions_reviews = load_lazada_db(
        SOLUTIONS_DB, category_fn=_lazada_category_for, is_grey_market_monitor=False
    )

    products = pd.concat(
        [tiktok_products, colored_products, solutions_products], ignore_index=True
    )
    products["market"] = "SG"
    products["original_price"] = pd.to_numeric(products["original_price"], errors="coerce")
    products["selling_price"] = pd.to_numeric(products["selling_price"], errors="coerce")
    products["discount_pct"] = 0.0
    mask = (
        products["original_price"].notna()
        & products["selling_price"].notna()
        & (products["original_price"] > products["selling_price"])
    )
    products.loc[mask, "discount_pct"] = (
        (products.loc[mask, "original_price"] - products.loc[mask, "selling_price"])
        / products.loc[mask, "original_price"]
        * 100
    )
    _SITE_TO_SOURCE_KEY = {"lazada_sg": "lazada", "tiktok_shop": "tiktok_shop"}
    products["journey_stage"] = products.apply(
        lambda r: COMPLIANCE_JOURNEY_STAGE
        if r["compliance_flag"]
        else journey_stage_for(_SITE_TO_SOURCE_KEY[r["site"]]),
        axis=1,
    )
    products.insert(0, "id", range(1, len(products) + 1))

    reviews = pd.concat([colored_reviews, solutions_reviews], ignore_index=True)
    reviews["market"] = "SG"
    # Match each review to its product row via source_sku (unique within a
    # given site, so also match on site to avoid cross-source collisions).
    sku_to_id = products.set_index(["site", "source_sku"])["id"].to_dict()
    reviews["product_id"] = reviews.apply(
        lambda r: sku_to_id.get((r["site"], r["source_sku"])), axis=1
    )
    reviews.insert(0, "id", range(1, len(reviews) + 1))
    for col in ("sentiment", "attribute_tags", "attribute_notes", "confidence"):
        reviews[col] = None

    conn = sqlite3.connect(SG_DB)
    products.to_sql("products", conn, if_exists="replace", index=False)
    reviews.to_sql("reviews", conn, if_exists="replace", index=False)
    conn.close()

    print(f"products: {len(products)} rows ({products['site'].value_counts().to_dict()})")
    print(f"  compliance_flag=True: {int(products['compliance_flag'].sum())} rows "
          f"(grey-market/illegal-online-lens signal, not ordinary product data)")
    print(f"reviews:  {len(reviews)} rows, {reviews['product_id'].isna().sum()} unmatched to a product")
    print(f"Wrote to {SG_DB}")


if __name__ == "__main__":
    build()
