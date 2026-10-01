#!/usr/bin/env python3
"""
translate_shopee_reviews_th.py

Translation pass for output/shopee_thailand_reviews_<YYYYMMDD>.csv (from
apify_shopee_reviews_th.py). Mirrors the project's existing
translate_lazada_th.py convention:
    - Model: gpt-4o-mini
    - Batches multiple rows per API call to control cost
    - Adds a `ReviewText_EN` column (original `review_text` left untouched)
    - Tracks and reports actual spend using confirmed 2026 pricing:
      $0.15/1M input tokens, $0.60/1M output tokens (same figures
      verified 2026-07-27 for the Lazada translation pass)

Unlike the Lazada script, there's no `ProductName_EN` column here --
the Shopee review CSV doesn't carry a scraped Thai product name field
(the `query` column is already English, generated from sku_competitor_map.py,
not the actual Shopee listing title). Only review text needs translating.

SCHEMA ADAPTATION NOTE (2026-08-07): this script is CSV-only -- unlike
Lazada, there's no equivalent SQLite table (apify_shopee_reviews_th.py
never added a DB write step, only a dated CSV per run). So the 4 fixes
below adapt Lazada's DB-based patterns to a CSV-only equivalent:
    - Lazada's `pulled_at` timestamp column  -> Shopee's `scraped_at`
    - Lazada's SQL `WHERE pulled_at >= ?`    -> Python-side row filter
    - Lazada's composite natural key (no true review ID) -> Shopee's own
      `review_id` (the platform's real reviewId, already unique -- a
      better key than any composite fallback)

FIX 1 -- --since filtering: --since <ISO date/datetime> filters loaded
rows to scraped_at >= that value BEFORE building the translation batch,
so re-running after a new scrape doesn't silently re-translate (and
re-pay for) every old row already in the CSV.

FIX 2 -- incremental writes: the output CSV is rewritten after every
batch, not just once at the end -- an interruption partway through still
leaves everything translated so far safely on disk.

FIX 3 -- resume support: if --output already exists, its rows are read
first and keyed by review_id (falling back to a composite key of
item_id + reviewer_name + review_date + review_text[:80] if review_id
is ever blank). Any row whose key already has a non-empty ReviewText_EN
is reused instead of re-sent to the API -- re-running the exact same
command after a crash costs nothing for rows already done.

FIX 4 -- utf-8-sig throughout: both the main input read and the new
resume-read use utf-8-sig (BOM), and the output writer already did --
so Thai text opens correctly in Excel instead of showing as mojibake,
and a BOM on a resume-read doesn't corrupt the first column's header key.

Requires: OPENAI_API_KEY in .env (same as the rest of the pipeline).
Requires: pip install openai python-dotenv

Usage:
    python translate_shopee_reviews_th.py --input output/shopee_thailand_reviews_20260807.csv --since 2026-08-07
"""
from __future__ import annotations

import argparse
import csv
import json
import os
import sys
import time
import logging
from datetime import datetime
from pathlib import Path

from dotenv import load_dotenv
load_dotenv()

try:
    from openai import OpenAI
except ImportError:
    OpenAI = None

MODEL = "gpt-4o-mini"
# Confirmed pricing, verified 2026-07-27 (OpenAI standard tier) -- same
# figures translate_lazada_th.py uses, kept consistent across the project.
PRICE_PER_1M_INPUT = 0.15
PRICE_PER_1M_OUTPUT = 0.60

TRANSLATE_BATCH_SIZE = 15  # rows per OpenAI call -- balances cost vs. call count

logging.basicConfig(level=logging.INFO, format="%(asctime)s [%(levelname)s] %(message)s")
log = logging.getLogger(__name__)


def translate_batch(client, texts: list[str]) -> tuple[list[str], int, int]:
    """Returns (translations, input_tokens, output_tokens). Empty/whitespace
    entries pass through as empty strings without spending a token on them."""
    indexed = [(i, t) for i, t in enumerate(texts) if t and t.strip()]
    if not indexed:
        return [""] * len(texts), 0, 0

    numbered = "\n".join(f"{n}: {t}" for n, (_, t) in enumerate(indexed))
    prompt = (
        "Translate the following Thai product reviews to natural English. "
        "Keep the numbering exactly as given. Return ONLY a JSON object "
        'mapping each number (as a string) to its English translation, '
        'e.g. {"0": "...", "1": "..."}. No other text.\n\n' + numbered
    )

    resp = client.chat.completions.create(
        model=MODEL,
        messages=[{"role": "user", "content": prompt}],
        temperature=0,
    )
    usage = resp.usage
    raw = resp.choices[0].message.content.strip()
    raw = raw.removeprefix("```json").removeprefix("```").removesuffix("```").strip()

    try:
        mapping = json.loads(raw)
    except json.JSONDecodeError:
        log.warning(" Failed to parse translation JSON, leaving batch untranslated")
        mapping = {}

    out = [""] * len(texts)
    for n, (orig_i, _) in enumerate(indexed):
        out[orig_i] = mapping.get(str(n), "")

    return out, usage.prompt_tokens, usage.completion_tokens


def natural_key(row: dict) -> str:
    """Prefers Shopee's own review_id (a real unique platform ID) --
    falls back to a composite key only if review_id is ever blank,
    mirroring translate_lazada_th.py's fallback approach for rows
    without a true ID."""
    review_id = (row.get("review_id") or "").strip()
    if review_id:
        return f"rid:{review_id}"
    return "composite:" + "|".join([
        (row.get("item_id") or "").strip(),
        (row.get("reviewer_name") or "").strip(),
        (row.get("review_date") or "").strip(),
        (row.get("review_text") or "")[:80].strip(),
    ])


def load_existing_translations(out_path: Path) -> dict[str, str]:
    """FIX 3 (resume support): reads an already-partially-translated
    --output file, if present, and returns {natural_key: ReviewText_EN}
    for every row that already has a non-empty translation."""
    if not out_path.exists():
        return {}
    cache: dict[str, str] = {}
    with open(out_path, encoding="utf-8-sig", newline="") as f:
        for row in csv.DictReader(f):
            en = (row.get("ReviewText_EN") or "").strip()
            if en:
                cache[natural_key(row)] = en
    log.info(f" [resume] Found {len(cache)} already-translated rows in existing {out_path.name}")
    return cache


def write_csv(out_path: Path, fieldnames: list[str], rows: list[dict]) -> None:
    with open(out_path, "w", newline="", encoding="utf-8-sig") as f:
        writer = csv.DictWriter(f, fieldnames=fieldnames)
        writer.writeheader()
        writer.writerows(rows)


def main():
    parser = argparse.ArgumentParser(description="Translate Shopee review text to English (gpt-4o-mini)")
    parser.add_argument("--input", required=True, help="shopee_thailand_reviews_<date>.csv from apify_shopee_reviews_th.py")
    parser.add_argument("--output", default=None, help="Defaults to <input>_translated.csv")
    parser.add_argument("--batch-size", type=int, default=TRANSLATE_BATCH_SIZE)
    parser.add_argument("--limit", type=int, default=0, help="Only translate the first N rows (0 = all) -- useful for a cheap test")
    parser.add_argument("--since", default=None,
                         help="ISO date/datetime (e.g. 2026-08-07 or 2026-08-07T00:00:00) -- "
                              "only rows with scraped_at >= this are loaded, so re-running "
                              "after a new scrape doesn't silently re-translate old rows")
    args = parser.parse_args()

    if OpenAI is None:
        log.error("openai package not installed -- pip install openai")
        raise SystemExit(1)
    api_key = os.getenv("OPENAI_API_KEY")
    if not api_key:
        log.error("OPENAI_API_KEY not set in .env")
        raise SystemExit(1)
    client = OpenAI(api_key=api_key)

    in_path = Path(args.input)
    if not in_path.exists():
        log.error(f"Input file not found: {in_path}")
        raise SystemExit(1)
    out_path = Path(args.output) if args.output else in_path.with_name(in_path.stem + "_translated.csv")

    with open(in_path, encoding="utf-8-sig", newline="") as f:
        reader = csv.DictReader(f)
        fieldnames = reader.fieldnames + ["ReviewText_EN"] if "ReviewText_EN" not in (reader.fieldnames or []) else reader.fieldnames
        all_rows = list(reader)

    n_total = len(all_rows)
    if args.since:
        since_dt = datetime.fromisoformat(args.since)
        rows = []
        for r in all_rows:
            scraped_at = (r.get("scraped_at") or "").strip()
            try:
                row_dt = datetime.fromisoformat(scraped_at.replace("Z", "+00:00"))
            except ValueError:
                rows.append(r)  # unparseable timestamp -- don't silently drop, keep it
                continue
            # compare naively if one side is tz-naive and the other isn't
            if row_dt.tzinfo is None or since_dt.tzinfo is None:
                row_dt, since_cmp = row_dt.replace(tzinfo=None), since_dt.replace(tzinfo=None)
            else:
                since_cmp = since_dt
            if row_dt >= since_cmp:
                rows.append(r)
        log.info(f"[LOAD] {len(rows)}/{n_total} rows loaded from {in_path.name} (--since {args.since} filter applied)")
    else:
        rows = all_rows
        log.info(f"[LOAD] {len(rows)} rows loaded from {in_path.name} (no --since filter -- ALL rows included)")

    if args.limit:
        rows = rows[: args.limit]

    # FIX 3 (resume support): reuse any already-translated rows from a prior,
    # interrupted run instead of re-sending them to the API.
    cache = load_existing_translations(out_path)
    n_reused = 0
    for r in rows:
        cached = cache.get(natural_key(r))
        if cached:
            r["ReviewText_EN"] = cached
            n_reused += 1
        else:
            r["ReviewText_EN"] = ""
    if n_reused:
        log.info(f" [resume] Reusing {n_reused}/{len(rows)} translations already done -- not re-sent to the API")

    to_translate_idx = [i for i, r in enumerate(rows) if not r["ReviewText_EN"]]

    total_in_tokens = 0
    total_out_tokens = 0
    n_translated = 0

    for start in range(0, len(to_translate_idx), args.batch_size):
        batch_idx = to_translate_idx[start : start + args.batch_size]
        batch = [rows[i] for i in batch_idx]
        texts = [r.get("review_text", "") for r in batch]
        try:
            translations, in_tok, out_tok = translate_batch(client, texts)
        except Exception as e:
            log.warning(f" Batch {start}-{start+len(batch)} failed: {e}")
            translations = [""] * len(batch)
            in_tok = out_tok = 0

        for r, en in zip(batch, translations):
            r["ReviewText_EN"] = en
            if en:
                n_translated += 1

        total_in_tokens += in_tok
        total_out_tokens += out_tok

        # FIX 2 (incremental writes): save after every batch, not just at the
        # end -- an interruption partway through still leaves everything
        # translated so far safely on disk.
        write_csv(out_path, fieldnames, rows)
        log.info(f" Translated {start+len(batch)}/{len(to_translate_idx)} new rows "
                 f"({len(rows)} total in file) -- saved to {out_path.name}")
        time.sleep(0.3)  # light rate-limit courtesy

    write_csv(out_path, fieldnames, rows)  # final write, covers the n_reused==len(rows) no-op-loop case too
    cost = (total_in_tokens / 1_000_000 * PRICE_PER_1M_INPUT) + (total_out_tokens / 1_000_000 * PRICE_PER_1M_OUTPUT)
    log.info(f"[EXPORT] {out_path}: {n_reused} reused + {n_translated} newly translated "
             f"= {n_reused + n_translated}/{len(rows)} rows have English text")
    log.info(f"[COST] {total_in_tokens} input tokens + {total_out_tokens} output tokens = ${cost:.4f}")


if __name__ == "__main__":
    main()
