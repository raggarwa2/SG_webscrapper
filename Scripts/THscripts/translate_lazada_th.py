#!/usr/bin/env python3
"""
translate_lazada_th.py

Post-processing pass for data pulled by lazada_pricing_th.py. Does three things:

  1. PACK-SIZE MISMATCH FLAGGING
     Compares the pack size we actually got back (e.g. from a "500ml" product
     that surfaced when we searched "50ml") against the size implied by the
     original query/SKU. Adds a `SizeMatch` column (True/False/Unknown) so
     mismatched noise (bundles, wrong pack sizes) can be filtered out before
     analysis -- flags by default, only drops rows if --drop-mismatches is set.

  2. DATE NORMALIZATION
     Lazada mixes absolute dates ("2026-06-21") and relative text
     ("2 weeks ago") in the same review set. This converts relative dates
     into absolute ISO dates using each row's `pulled_at` timestamp as the
     reference point, added as a new `DateNormalized` column (original `Date`
     column is left untouched).

  3. ENGLISH TRANSLATION (via OpenAI gpt-4o-mini)
     Adds `ReviewText_EN` and `ProductName_EN` columns with English
     translations, matching the project's existing convention (same model
     used elsewhere in this project for LLM-based extraction). Batches
     multiple rows per API call to control cost, and tracks/reports actual
     spend using confirmed 2026 pricing: $0.15/1M input tokens,
     $0.60/1M output tokens (verified 2026-07-27).

------------------------------------------------------------------------------
INPUT
------------------------------------------------------------------------------
Reads from the SQLite DB written by lazada_pricing_th.py (default table
`lazada_data`), since that DB has `query_used`, `acne_aid_sku`, and
`pulled_at` -- fields the CSV export doesn't include but which this script
needs for pack-size comparison and date normalization. A `--csv` input mode
is also supported for translation-only use (no pack-size/date logic, since
those need the extra DB columns), e.g. if you only have a CSV export.

OUTPUT
------------------------------------------------------------------------------
Writes a new CSV (or updates a new SQLite table `lazada_data_clean`) with all
original columns plus: SizeMatch, DateNormalized, ReviewText_EN, ProductName_EN.

Requires: OPENAI_API_KEY environment variable (or in a .env file, same as
the main pipeline). Requires: pip install openai pydantic python-dotenv
------------------------------------------------------------------------------
"""

import argparse
import csv
import json
import os
import re
import sqlite3
import sys
import time
from datetime import datetime, timedelta, timezone

try:
    from dotenv import load_dotenv
    load_dotenv()
except ImportError:
    pass

try:
    from openai import OpenAI
except ImportError:
    OpenAI = None

try:
    from pydantic import BaseModel, ValidationError
except ImportError:
    BaseModel = None
    ValidationError = Exception


# ------------------------------------------------------------------------
# CONFIG
# ------------------------------------------------------------------------

OPENAI_API_KEY = os.environ.get("OPENAI_API_KEY")
MODEL = "gpt-4o-mini"

# Confirmed pricing, verified 2026-07-27 (OpenAI standard tier)
PRICE_PER_1M_INPUT = 0.15
PRICE_PER_1M_OUTPUT = 0.60

DEFAULT_DB_PATH = "acne_aid_th.db"
SOURCE_TABLE = "lazada_data"
CLEAN_TABLE = "lazada_data_clean"

TRANSLATE_BATCH_SIZE = 15  # rows per OpenAI call -- balances cost vs. call count


# ------------------------------------------------------------------------
# PACK-SIZE MISMATCH DETECTION
# ------------------------------------------------------------------------

_SIZE_RE = re.compile(r'(\d+\.?\d*)\s?(ml|g|gm|oz)\b', re.IGNORECASE)


def extract_size(text: str):
    """Returns (number, unit) tuple, or None if no size pattern found."""
    if not text:
        return None
    m = _SIZE_RE.search(text)
    if not m:
        return None
    return (float(m.group(1)), m.group(2).lower())


def sizes_match(expected, actual, tolerance_pct=5.0):
    """
    Compares two (number, unit) tuples. Same unit required; numeric value
    allowed a small tolerance (default 5%) to absorb rounding differences
    (e.g. "100ml" vs "100.0ml"). Bundles/multi-packs (e.g. "2x100ml") won't
    match a "100ml" expectation under this simple check -- that's intentional,
    since a bundle IS a different SKU for pricing purposes.
    """
    if expected is None or actual is None:
        return None  # "Unknown" -- couldn't extract one or both sizes
    exp_num, exp_unit = expected
    act_num, act_unit = actual
    if exp_unit != act_unit:
        return False
    if exp_num == 0:
        return act_num == 0
    diff_pct = abs(exp_num - act_num) / exp_num * 100
    return diff_pct <= tolerance_pct


def compute_size_match(query_used: str, product_name: str, pack_size_field: str) -> str:
    """Returns 'True', 'False', or 'Unknown' as a string (CSV-friendly)."""
    expected = extract_size(query_used)
    actual = extract_size(pack_size_field) or extract_size(product_name)
    result = sizes_match(expected, actual)
    if result is None:
        return "Unknown"
    return "True" if result else "False"


# ------------------------------------------------------------------------
# DATE NORMALIZATION
# ------------------------------------------------------------------------

_RELATIVE_RE = re.compile(
    r'(\d+)\s*(day|days|week|weeks|month|months|year|years)\s*ago', re.IGNORECASE
)


def normalize_date(date_field: str, pulled_at: str) -> str:
    """
    Converts a relative date string ("2 weeks ago") into an absolute ISO
    date using `pulled_at` as the reference "now". Absolute dates (already
    YYYY-MM-DD) are passed through unchanged. Empty/unparseable dates return
    empty string.
    """
    if not date_field:
        return ""

    date_field = date_field.strip()

    # Already absolute (YYYY-MM-DD or similar) -- pass through
    if re.match(r'^\d{4}-\d{2}-\d{2}', date_field):
        return date_field[:10]

    m = _RELATIVE_RE.search(date_field)
    if not m:
        return ""  # unparseable (e.g. unexpected format) -- leave blank, don't guess

    amount = int(m.group(1))
    unit = m.group(2).lower()

    try:
        ref = datetime.fromisoformat(pulled_at.replace("Z", "+00:00"))
    except (ValueError, AttributeError):
        ref = datetime.now(timezone.utc)

    if unit.startswith("day"):
        delta = timedelta(days=amount)
    elif unit.startswith("week"):
        delta = timedelta(weeks=amount)
    elif unit.startswith("month"):
        delta = timedelta(days=amount * 30)  # approximate -- good enough for pricing-corridor analysis
    elif unit.startswith("year"):
        delta = timedelta(days=amount * 365)
    else:
        return ""

    return (ref - delta).date().isoformat()


# ------------------------------------------------------------------------
# TRANSLATION (OpenAI gpt-4o-mini, batched, cost-tracked)
# ------------------------------------------------------------------------

if BaseModel is not None:
    class TranslationItem(BaseModel):
        id: int
        review_text_en: str
        product_name_en: str

    class TranslationBatch(BaseModel):
        translations: list[TranslationItem]
else:
    TranslationItem = None
    TranslationBatch = None


class CostTracker:
    def __init__(self):
        self.input_tokens = 0
        self.output_tokens = 0
        self.calls = 0

    def add(self, usage):
        self.input_tokens += usage.prompt_tokens
        self.output_tokens += usage.completion_tokens
        self.calls += 1

    @property
    def cost(self):
        return (self.input_tokens / 1_000_000 * PRICE_PER_1M_INPUT +
                self.output_tokens / 1_000_000 * PRICE_PER_1M_OUTPUT)

    def print_summary(self):
        print(f"--- Translation cost ---")
        print(f"  API calls:      {self.calls}")
        print(f"  Input tokens:   {self.input_tokens:,}")
        print(f"  Output tokens:  {self.output_tokens:,}")
        print(f"  ACTUAL COST:    ${self.cost:.4f}")
        print(f"  (gpt-4o-mini @ ${PRICE_PER_1M_INPUT}/1M in, ${PRICE_PER_1M_OUTPUT}/1M out, verified 2026-07-27)")


def translate_batch(client, rows: list[dict], tracker: CostTracker) -> dict:
    """
    Sends up to TRANSLATE_BATCH_SIZE rows in one call. Returns
    {row_index: {"review_text_en": ..., "product_name_en": ...}}.
    Uses Pydantic to validate the structured JSON response.
    """
    items = [
        {"id": i, "review_text": r["ReviewText"], "product_name": r["ProductName"]}
        for i, r in enumerate(rows)
    ]

    system_prompt = (
        "You translate Thai/mixed-language e-commerce review text and product "
        "names into natural English. Preserve meaning and tone; don't add "
        "commentary. Return ONLY valid JSON matching this exact schema: "
        '{"translations": [{"id": int, "review_text_en": str, "product_name_en": str}]} '
        "-- one entry per input item, in the same order, matching the given id."
    )
    user_prompt = json.dumps({"items": items}, ensure_ascii=False)

    response = client.chat.completions.create(
        model=MODEL,
        messages=[
            {"role": "system", "content": system_prompt},
            {"role": "user", "content": user_prompt},
        ],
        response_format={"type": "json_object"},
        temperature=0,
    )

    tracker.add(response.usage)

    raw = response.choices[0].message.content
    try:
        parsed = json.loads(raw)
        if TranslationBatch is not None:
            validated = TranslationBatch(**parsed)
            results = {item.id: {"review_text_en": item.review_text_en,
                                  "product_name_en": item.product_name_en}
                       for item in validated.translations}
        else:
            results = {item["id"]: {"review_text_en": item["review_text_en"],
                                     "product_name_en": item["product_name_en"]}
                       for item in parsed["translations"]}
    except (json.JSONDecodeError, ValidationError, KeyError) as e:
        print(f"  WARNING: failed to parse translation batch response ({e}). "
              f"Rows in this batch will have empty _EN fields.")
        results = {}

    return results


# ------------------------------------------------------------------------
# DB / CSV I/O
# ------------------------------------------------------------------------

CSV_COLUMNS = [
    "Date", "Reviewer", "Rating", "ReviewText", "Helpful",
    "SKU", "ProductName", "Brand", "PackSize", "SellerType",
    "Price", "OriginalPrice", "DiscountPercent", "Channel",
    "OverallRating", "TotalReviews",
]
EXTRA_COLUMNS = ["query_used", "acne_aid_sku", "priority", "pulled_at"]
NEW_COLUMNS = ["SizeMatch", "DateNormalized", "ReviewText_EN", "ProductName_EN"]


def load_from_db(db_path: str, since: str = None) -> list[dict]:
    """
    since: optional ISO date/datetime string (e.g. "2026-08-01"). If given,
    only rows with pulled_at >= since are loaded -- lets you isolate a new
    scrape run from older rows already sitting in the same table/DB that
    were already translated in a prior pass (this table accumulates across
    every lazada_pricing_th.py run, old and new, with no separation).
    """
    conn = sqlite3.connect(db_path)
    conn.row_factory = sqlite3.Row
    if since:
        cur = conn.execute(f"SELECT * FROM {SOURCE_TABLE} WHERE pulled_at >= ?", (since,))
    else:
        cur = conn.execute(f"SELECT * FROM {SOURCE_TABLE}")
    rows = [dict(r) for r in cur.fetchall()]
    conn.close()
    return rows


def load_from_csv(csv_path: str) -> list[dict]:
    with open(csv_path, newline="", encoding="utf-8-sig") as f:
        rows = list(csv.DictReader(f))
    for r in rows:
        r.setdefault("query_used", "")
        r.setdefault("pulled_at", "")
    return rows


def write_output_csv(rows: list[dict], out_path: str):
    fieldnames = CSV_COLUMNS + NEW_COLUMNS + ["query_used", "acne_aid_sku", "priority"]
    # utf-8-sig (adds a BOM) instead of plain utf-8: Excel auto-detects UTF-8 correctly
    # on a normal double-click open with the BOM present. Without it, Excel falls back
    # to the system locale (Windows-1252) and Thai text renders as garbled mojibake --
    # this is purely an Excel-reading-the-file issue, not a data issue, but the BOM
    # avoids needing the manual Data > From Text/CSV > UTF-8 import workaround every time.
    with open(out_path, "w", newline="", encoding="utf-8-sig") as f:
        writer = csv.DictWriter(f, fieldnames=fieldnames, extrasaction="ignore")
        writer.writeheader()
        writer.writerows(rows)
    print(f"Wrote {len(rows)} rows to {out_path}")


# ------------------------------------------------------------------------
# MAIN
# ------------------------------------------------------------------------

def main():
    parser = argparse.ArgumentParser(description="Clean, date-normalize, and translate Lazada TH data")
    parser.add_argument("--db", default=DEFAULT_DB_PATH, help="Source SQLite DB (default mode)")
    parser.add_argument("--since", default=None,
                         help="Only load rows with pulled_at >= this ISO date/datetime "
                              "(e.g. 2026-08-01). Use this to isolate a new scrape run from "
                              "older rows in the same DB table that were already translated.")
    parser.add_argument("--csv", default=None, help="Use a CSV instead of the DB (translation-only; "
                                                       "pack-size/date logic needs DB's extra columns)")
    parser.add_argument("--out", required=True, help="Output CSV path")
    parser.add_argument("--drop-mismatches", action="store_true",
                         help="Drop rows flagged SizeMatch=False instead of just flagging them")
    parser.add_argument("--no-translate", action="store_true",
                         help="Skip translation entirely (only do size-match + date normalization)")
    parser.add_argument("--yes", action="store_true", help="Skip cost confirmation prompt for translation")
    args = parser.parse_args()

    if args.csv:
        rows = load_from_csv(args.csv)
        print(f"Loaded {len(rows)} rows from CSV: {args.csv}")
    else:
        rows = load_from_db(args.db, since=args.since)
        since_note = f" (pulled_at >= {args.since})" if args.since else " (ALL rows in table -- includes any older runs)"
        print(f"Loaded {len(rows)} rows from DB: {args.db} (table {SOURCE_TABLE}){since_note}")

    if not rows:
        print("No rows found -- nothing to do.")
        return

    # --- Step 0: deduplication ---
    # A single popular product can surface as a match for multiple different
    # search queries (e.g. a broadly-relevant Acne-Aid product matching both
    # "Liq Cleanser 50ml" and "Gentle Cleanser 50ml" searches), causing its
    # reviews to be pulled and saved more than once. Dedup on the natural key
    # of (SKU, Reviewer, Date, ReviewText) -- keeps the first occurrence.
    before = len(rows)
    seen = set()
    deduped_rows = []
    for r in rows:
        key = (r.get("SKU", ""), r.get("Reviewer", ""), r.get("Date", ""), r.get("ReviewText", "")[:80])
        if key in seen:
            continue
        seen.add(key)
        deduped_rows.append(r)
    rows = deduped_rows
    n_removed = before - len(rows)
    if n_removed:
        print(f"Deduplication: removed {n_removed} duplicate rows ({before} -> {len(rows)}) "
              f"-- same product/review pair matched multiple search queries.")

    # --- Step 1: pack-size mismatch flagging ---
    for r in rows:
        r["SizeMatch"] = compute_size_match(
            r.get("query_used", ""), r.get("ProductName", ""), r.get("PackSize", "")
        )
    n_false = sum(1 for r in rows if r["SizeMatch"] == "False")
    n_unknown = sum(1 for r in rows if r["SizeMatch"] == "Unknown")
    print(f"SizeMatch: {len(rows) - n_false - n_unknown} True, {n_false} False, {n_unknown} Unknown")

    if args.drop_mismatches:
        before = len(rows)
        rows = [r for r in rows if r["SizeMatch"] != "False"]
        print(f"Dropped {before - len(rows)} mismatched rows (--drop-mismatches)")

    # --- Step 2: date normalization ---
    for r in rows:
        r["DateNormalized"] = normalize_date(r.get("Date", ""), r.get("pulled_at", ""))
    n_normalized = sum(1 for r in rows if r["DateNormalized"])
    print(f"DateNormalized: {n_normalized}/{len(rows)} rows resolved to an absolute date")

    # --- Step 3: translation ---
    for r in rows:
        r["ReviewText_EN"] = ""
        r["ProductName_EN"] = ""

    if not args.no_translate:
        # Resume support: if --out already exists (e.g. left over from a run that got
        # interrupted), reuse its translations instead of paying to redo them. Matched
        # on the same natural key used for dedup above.
        already_translated = {}
        if os.path.exists(args.out):
            with open(args.out, newline="", encoding="utf-8-sig") as f:
                for prior in csv.DictReader(f):
                    if prior.get("ReviewText_EN", "").strip():
                        key = (prior.get("SKU", ""), prior.get("Reviewer", ""),
                               prior.get("Date", ""), prior.get("ReviewText", "")[:80])
                        already_translated[key] = prior
            if already_translated:
                print(f"Found existing output at {args.out} -- resuming: "
                      f"{len(already_translated)} rows already translated, will skip those.")
                for r in rows:
                    key = (r.get("SKU", ""), r.get("Reviewer", ""), r.get("Date", ""),
                           r.get("ReviewText", "")[:80])
                    if key in already_translated:
                        r["ReviewText_EN"] = already_translated[key].get("ReviewText_EN", "")
                        r["ProductName_EN"] = already_translated[key].get("ProductName_EN", "")

        rows_needing_translation = [r for r in rows if not r.get("ReviewText_EN", "").strip()
                                     and (r.get("ReviewText", "").strip()
                                          or r.get("ProductName", "").strip())]
        n_batches = -(-len(rows_needing_translation) // TRANSLATE_BATCH_SIZE)
        # Rough pre-flight estimate: ~150 tokens in + ~150 tokens out per row (conservative)
        est_input_tokens = len(rows_needing_translation) * 150
        est_output_tokens = len(rows_needing_translation) * 150
        est_cost = (est_input_tokens / 1_000_000 * PRICE_PER_1M_INPUT +
                    est_output_tokens / 1_000_000 * PRICE_PER_1M_OUTPUT)
        print(f"--- Translation pre-flight estimate ---")
        print(f"  Rows to translate: {len(rows_needing_translation)} in {n_batches} batch(es)")
        print(f"  Rough estimated cost: ${est_cost:.4f} (conservative; actual tracked cost will be printed after)")
        print("-" * 60)

        if OpenAI is None:
            print("ERROR: 'openai' package not installed. Run: pip install openai")
            print("Skipping translation -- output will have empty _EN columns.")
        elif not OPENAI_API_KEY:
            print("ERROR: OPENAI_API_KEY not set (env var or .env file). "
                  "Skipping translation -- output will have empty _EN columns.")
        else:
            if not args.yes:
                resp = input(f"Proceed with translation (~${est_cost:.4f} estimated)? [y/N]: ").strip().lower()
                if resp != "y":
                    print("Translation skipped by user. Continuing with empty _EN columns.")
                    rows_needing_translation = []

            if rows_needing_translation:
                client = OpenAI(api_key=OPENAI_API_KEY)
                tracker = CostTracker()

                for batch_start in range(0, len(rows_needing_translation), TRANSLATE_BATCH_SIZE):
                    batch = rows_needing_translation[batch_start:batch_start + TRANSLATE_BATCH_SIZE]
                    batch_num = batch_start // TRANSLATE_BATCH_SIZE + 1
                    print(f"[Translate batch {batch_num}/{n_batches}] {len(batch)} rows...")
                    try:
                        results = translate_batch(client, batch, tracker)
                    except Exception as e:
                        print(f"  ERROR translating batch {batch_num}: {e}")
                        continue
                    for i, row in enumerate(batch):
                        if i in results:
                            row["ReviewText_EN"] = results[i]["review_text_en"]
                            row["ProductName_EN"] = results[i]["product_name_en"]
                    time.sleep(0.5)

                    # Checkpoint: write full output after EVERY batch, not just at the
                    # end. If this run is interrupted (Ctrl-C, crash, terminal closed),
                    # everything translated so far is still saved to --out.
                    write_output_csv(rows, args.out)

                tracker.print_summary()

    write_output_csv(rows, args.out)
    print("Done.")


if __name__ == "__main__":
    main()
