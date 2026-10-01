"""
watsons_scraper.py — Watsons Thailand pricing scraper for the Acne-Aid competitive set

*** MAPPED FROM bigc_scraper.py on 2026-08-08 — NOT YET VALIDATED against real
*** Watsons Thailand HTML. Run a small --batch-size 2 test discover first and
*** eyeball url_mapping.csv before trusting this at scale. See "THINGS TO TEST
*** BEFORE TRUSTING THIS SCRIPT" note near the top of extract_product() and
*** LINK_RE below.

Two stages, run together or separately:

  STAGE 1 (discover): For each search term (e.g. "CeraVe Blemish Control
  Cleanser 88ML"), hits Watsons Thailand's site search (watsons.co.th/en/search?text=...) via the
  Apify Stealth Web Scraper actor, pulls candidate product links + titles out
  of the results page, and picks the best match by simple token overlap +
  pack-size matching. Writes a mapping CSV: search_term -> matched watsons_url.

  STAGE 2 (scrape): For each matched URL, hits the product page via the same
  actor, parses the schema.org JSON-LD Product block (name, sku, gtin, brand,
  price, currency, availability), and saves incrementally to SQLite (WAL mode)
  + optional CSV export.

INPUT: a CSV with your ~100 SKU search terms. Minimal columns required:
    search_term, brand, sku_ref
  Optional columns used to improve matching:
    expected_size   (e.g. "88ML" — helps disambiguate pack sizes)

Example input CSV (skus_to_find.csv):
    search_term,brand,sku_ref,expected_size
    CeraVe Blemish Control Cleanser 88ML,CeraVe,Liq Cleanser 1x100ml,88ML
    Cetaphil Daily Facial Cleanser 118 ML,Cetaphil,Liq Cleanser 1x100ml,118ML
    ...

USAGE:
    pip install requests

    # Stage 1 only — build the URL mapping
    python watsons_scraper.py discover --input skus_to_find.csv --out url_mapping.csv --token YOUR_APIFY_TOKEN

    # Review url_mapping.csv, fix/drop any bad matches manually, then:

    # Stage 2 only — scrape the matched URLs
    python watsons_scraper.py scrape --input url_mapping.csv --token YOUR_APIFY_TOKEN --db watsons_pricing.db --export-csv

    # Or run both stages back to back:
    python watsons_scraper.py all --input skus_to_find.csv --token YOUR_APIFY_TOKEN --db watsons_pricing.db --export-csv

NOTES:
  - Reuses the same Apify actor as bigc_scraper.py: lentic_clockss/stealth-web-scraper
    (Cloudflare bypass via residential proxy + stealth browser). Watsons TH
    sits behind similar bot protection to Big C, so this should carry over,
    but it has NOT yet been manually validated against Watsons TH the way
    the Watsons version was on 2026-07-29 — run a small test batch first.
  - UNVALIDATED ASSUMPTIONS carried over / guessed for Watsons TH (fix these
    once you've run a real test batch and looked at discover_debug.html):
      1. SEARCH_URL_TMPL guessed as watsons.co.th/en/search?text={query} —
         Watsons' regional sites have used both /search?text= and /search?q=
         in the past; verify against a real browser search first.
      2. LINK_RE — CONFIRMED 2026-08-08 against a real product URL:
         /en/{slug}/p/BP_{code} (e.g. /en/acne-aid-acne-aid-liquid-cleanser-
         500-ml./p/BP_296340). Same BP_ prefix as Watsons SG/MY/HK. Only
         confirmed on a product page directly, not yet on a search RESULTS
         page — verify discover's match rate before trusting it at scale.
      2b. ALTERNATIVE ACTOR spotted in Apify Store:
          stealth_mode/watsons-reviews-scraper (actor id Epx76bgwTNkLCj7gi,
          $3/1,000 results). Despite the "Reviews" name, its input is
          literally "URLs of the product details urls to scrape" — i.e. it
          takes direct product page URLs like the generic stealth-web-scraper
          does. NOT yet confirmed whether its output includes price/currency/
          availability or only review data — check a real run's output
          schema before switching run_actor()/ACTOR_ENDPOINT over to it.
      3. Category listing pages: unknown whether Watsons TH embeds
         structured item data in listing pages or only product pages —
         assume product-page-only (like Big C) until proven otherwise.
      4. RESOLVED 2026-08-08: extract_product()'s JSON-LD path works, but
         needed a fix — Watsons TH uses "AggregateOffer" (not plain "Offer")
         with lowPrice/highPrice fields when a product is on promo. The
         "price" field holds LIST price (e.g. 770), NOT the current/sale
         price — the real displayed price (e.g. 499, 35% off) is in
         "lowPrice". extract_product() now returns lowPrice as "price" and
         highPrice as a new "list_price" field when AggregateOffer is
         present, falling back to plain offer.price otherwise. Confirmed
         against a live 8.8-sale product page (Acne-Aid Liquid Cleanser
         500ml, BP_296340: JSON-LD had price=770/lowPrice=499/highPrice=770,
         matching the displayed ฿499.00 35% off / ฿770.00 list on-page).
         The regex FALLBACK (id="pdp_brand-title" etc.) is still Big-C-
         specific markup and untested on Watsons — low priority now that
         the JSON-LD path is confirmed working for both name/brand/price.
"""

import argparse
import csv
import json
import os
import re
import shutil
import sqlite3
import sys
import time
from typing import Optional

import requests

try:
    from dotenv import load_dotenv
    load_dotenv()  # reads .env in the current working directory
except ImportError:
    pass  # dotenv not installed — fall back to whatever's already in os.environ


def resolve_token(cli_token: Optional[str]) -> str:
    """Token resolution order: --token flag > APIFY_TOKEN env var (.env or shell)."""
    token = cli_token or os.environ.get("APIFY_TOKEN")
    if not token:
        print(
            "ERROR: no Apify token found. Either pass --token YOUR_TOKEN, "
            "or set APIFY_TOKEN in a .env file / environment variable.",
            file=sys.stderr,
        )
        sys.exit(1)
    return token

ACTOR_ID = "lentic_clockss~stealth-web-scraper"
ACTOR_ENDPOINT = f"https://api.apify.com/v2/acts/{ACTOR_ID}/run-sync-get-dataset-items"
# Pinned build: the actor's maintainer published build 0.2.2 on 2026-08-27 (02:14 UTC)
# and it crashes on every single call before fetching any URL (AttributeError in the
# actor's own INPUT_ECHO debug step: "Schema validation failed: must be string"),
# independent of our input. Confirmed via the run log (exit_code 91) and confirmed
# 0.1.39 (the last build before the break, 2026-08-24) works cleanly against a real
# Watsons product page. Pin explicitly rather than floating on the "latest" tag so a
# future bad actor-side release doesn't silently break every run again.
ACTOR_BUILD = "0.1.39"
SEARCH_URL_TMPL = "https://www.watsons.co.th/en/search?text={query}"  # UNVALIDATED — verify pattern (see NOTES above)

# CONFIRMED 2026-08-08 against a real Watsons TH product page:
#   https://www.watsons.co.th/en/acne-aid-acne-aid-liquid-cleanser-500-ml./p/BP_296340
# Pattern is /en/{slug}/p/BP_{code} — NOT /en/p/{slug}/BP_{code}.html as
# originally guessed (no .html suffix, "p" segment comes AFTER the slug).
# Still only confirmed on product pages directly, not yet on a live search
# RESULTS page — if discover's match rate looks low, check discover_debug.html
# in case search results markup differs from product-page markup.
LINK_RE = re.compile(r'href="(/en/([a-z0-9\-\.]+)/p/(BP_\d+))"', re.IGNORECASE)

# Item 4: bundle/multipack detection — flags listings that are likely
# multi-unit packs, so they don't silently skew per-unit price comparisons.
# NOTE: "1x100ml" means ONE 100ml unit, not a bundle — only a leading
# multiplier of 2 or more counts as an actual multipack (e.g. "2x100ml").
MULTIPACK_XN_RE = re.compile(r'\b(\d+)\s*[x×]\s*\d+', re.IGNORECASE)
MULTIPACK_OTHER_RE = re.compile(
    r'\b\d+\s*-?\s*pack\b|\btwin\s*pack\b|\bbundle\b|\bset\s*of\s*\d+\b',
    re.IGNORECASE,
)


def flag_multipack(text: str) -> bool:
    """Return True if the given text (search term or scraped product name)
    looks like a multi-unit bundle/pack rather than a single unit."""
    if not text:
        return False
    if MULTIPACK_OTHER_RE.search(text):
        return True
    m = MULTIPACK_XN_RE.search(text)
    if m and int(m.group(1)) >= 2:
        return True
    return False


def backup_db(db_path: str):
    """Item 11: copy the existing DB to a timestamped backup file before any
    write session begins. No-op if the DB doesn't exist yet (first run)."""
    if not os.path.exists(db_path):
        return
    ts = time.strftime("%Y%m%dT%H%M%S")
    backup_path = f"{db_path}.bak.{ts}"
    shutil.copy2(db_path, backup_path)
    print(f"Backed up existing DB to {backup_path}")


def read_csv_rows(path: str) -> list[dict]:
    """Item 9: read CSVs tolerant of a BOM (utf-8-sig handles both BOM and
    plain utf-8 transparently, so it's safe to use unconditionally)."""
    with open(path, newline="", encoding="utf-8-sig") as f:
        return list(csv.DictReader(f))


def write_csv_rows(path: str, rows: list[dict], fieldnames: list[str], max_retries: int = 5, retry_delay: float = 3.0):
    """Item 9: write CSVs with a BOM so Thai/non-Latin text displays
    correctly when opened directly in Excel instead of mojibake.

    Retries on PermissionError — this happens when the file is open in
    Excel (Windows locks it for exclusive access) or a Google Drive sync
    transiently holds it. Falls back to a timestamped sibling file if the
    lock never clears, so progress is never silently lost.
    """
    last_error = None
    for attempt in range(max_retries):
        try:
            with open(path, "w", newline="", encoding="utf-8-sig") as f:
                writer = csv.DictWriter(f, fieldnames=fieldnames)
                writer.writeheader()
                writer.writerows(rows)
            return
        except PermissionError as e:
            last_error = e
            print(f"  WARNING: '{path}' is locked (attempt {attempt + 1}/{max_retries}) — "
                  f"likely open in Excel or mid Google-Drive-sync. Close it if it's open. "
                  f"Retrying in {retry_delay}s...")
            time.sleep(retry_delay)

    # Every retry failed — write to a fallback path instead of losing the data
    fallback_path = f"{path}.RECOVER_{time.strftime('%Y%m%dT%H%M%S')}.csv"
    print(f"  Could not write to '{path}' after {max_retries} attempts ({last_error}). "
          f"Writing to '{fallback_path}' instead so nothing is lost — "
          f"close the locked file and rename/merge it back manually.")
    with open(fallback_path, "w", newline="", encoding="utf-8-sig") as f:
        writer = csv.DictWriter(f, fieldnames=fieldnames)
        writer.writeheader()
        writer.writerows(rows)


# ---------------------------------------------------------------------------
# Apify calls
# ---------------------------------------------------------------------------

_actor_opaque_id_cache: dict[str, str] = {}


def _resolve_actor_id(token: str) -> Optional[str]:
    """Resolve ACTOR_ID's 'user~name' slug to Apify's opaque actId, which is
    what actor-runs listings key on (not the slug). Cached per-process."""
    if ACTOR_ID in _actor_opaque_id_cache:
        return _actor_opaque_id_cache[ACTOR_ID]
    try:
        resp = requests.get(f"https://api.apify.com/v2/acts/{ACTOR_ID}", params={"token": token}, timeout=30)
        opaque_id = resp.json().get("data", {}).get("id")
        _actor_opaque_id_cache[ACTOR_ID] = opaque_id
        return opaque_id
    except Exception:
        return None


def abort_orphaned_runs(token: str):
    """Item 14: when run-sync-get-dataset-items hits its 300s wait cap and
    returns 'run-timeout-exceeded' to us, the underlying actor RUN keeps
    executing on Apify's infrastructure independently — the sync endpoint
    only gives up on WAITING for it, it doesn't abort it. Confirmed
    2026-08-09: a batch already superseded by its own split-retry
    (checkpoint already written, script already on the next batch) was
    still shown RUNNING on Apify 8+ minutes later, burning credits for
    nothing. Since this script runs batches strictly sequentially, ANY run
    still RUNNING for this actor at the moment we're about to start a new
    one is guaranteed to be an orphan from a previous timed-out call — safe
    to abort unconditionally."""
    opaque_id = _resolve_actor_id(token)
    if not opaque_id:
        return
    try:
        resp = requests.get(
            "https://api.apify.com/v2/actor-runs",
            params={"token": token, "status": "RUNNING", "limit": 50},
            timeout=30,
        )
        for run in resp.json().get("data", {}).get("items", []):
            if run.get("actId") == opaque_id:
                run_id = run.get("id")
                requests.post(f"https://api.apify.com/v2/actor-runs/{run_id}/abort", params={"token": token}, timeout=30)
                print(f"  Cleaned up orphaned actor run {run_id} (from an earlier timed-out call)")
    except Exception as e:
        print(f"  NOTE: couldn't check for orphaned runs to clean up ({e})", file=sys.stderr)


def run_actor(urls: list[str], token: str, batch_label: str = "", max_concurrency: int = 5, _depth: int = 0) -> list[dict]:
    """Run the Stealth Web Scraper actor synchronously on a batch of URLs and
    return the raw dataset items.

    NOTE: this actor's real input schema (confirmed via its build metadata)
    uses `urls` as a flat array of URL strings, and `proxyGroup` as a flat
    string field — NOT the standard Apify Web Scraper convention of
    `startUrls: [{"url": ...}]` + nested `proxyConfiguration`. Using the
    wrong field names causes the actor to silently fall back to its own
    default example input instead of erroring, which is a easy trap.

    IMPORTANT: the actor's own default maxConcurrency is 1 (fully serial —
    one page at a time). Left unset, 91 queries at ~15-20s each serially is
    ~25-35 minutes for a single discover/scrape run. We explicitly raise it
    here; tune down if pages start coming back blocked/rate-limited, since
    higher concurrency can trip anti-bot detection on some sites.

    Apify's run-sync-get-dataset-items endpoint enforces a hard 300-second
    cap on the whole run, regardless of our own request timeout — if a
    batch of slow/blocked pages pushes past that, the platform returns a
    "run-timeout-exceeded" error for the ENTIRE batch, discarding whatever
    already succeeded. Rather than losing the whole batch, split it in half
    and retry each half recursively (down to single URLs at worst).
    """
    # The actor enforces a hard server-side cap of 5 on maxConcurrency —
    # anything above that gets rejected with a 400 invalid-input error for
    # the ENTIRE batch (confirmed 2026-08-08: a run with --max-concurrency 8
    # failed all 91/91 rows before a single page was even attempted). Clamp
    # here so no caller can trigger that failure mode again.
    if max_concurrency > 5:
        print(f"  NOTE: max_concurrency={max_concurrency} exceeds the actor's hard cap of 5 — "
              f"clamping to 5.", file=sys.stderr)
        max_concurrency = 5

    payload = {
        "urls": urls,
        "proxyGroup": "RESIDENTIAL",
        "outputFormat": "both",
        "maxConcurrency": max_concurrency,
    }
    try:
        resp = requests.post(
            ACTOR_ENDPOINT,
            params={"token": token, "build": ACTOR_BUILD},
            json=payload,
            timeout=900,  # our own client-side timeout; the platform's own 300s cap is the real limit
        )
    except requests.exceptions.RequestException as e:
        # Item 15: a raw transport-level failure (e.g. WinError 10054
        # connection-reset) — not an HTTP error status, so resp was never
        # assigned. Confirmed 2026-08-09: this was previously unhandled and
        # crashed the entire multi-hour run on one flaky connection instead
        # of just failing the one batch. Treat it like the platform-timeout
        # path: split and retry if possible, otherwise give up on just this
        # URL so the run can continue.
        print(f"  Connection error on batch {batch_label} ({e}) — retrying...", file=sys.stderr)
        if len(urls) > 1:
            mid = len(urls) // 2
            first_half = run_actor(urls[:mid], token, batch_label=f"{batch_label}-a", max_concurrency=max_concurrency, _depth=_depth + 1)
            second_half = run_actor(urls[mid:], token, batch_label=f"{batch_label}-b", max_concurrency=max_concurrency, _depth=_depth + 1)
            return first_half + second_half
        if _depth < 5:
            return run_actor(urls, token, batch_label=f"{batch_label}-retry", max_concurrency=max_concurrency, _depth=_depth + 1)
        print(f"  ERROR: giving up on {urls} after repeated connection errors", file=sys.stderr)
        return []
    if resp.status_code >= 400:
        is_platform_timeout = "run-timeout-exceeded" in resp.text
        if is_platform_timeout:
            # The run that just timed out on us is still executing on
            # Apify's side — see abort_orphaned_runs() docstring.
            abort_orphaned_runs(token)
        if is_platform_timeout and len(urls) > 1:
            mid = len(urls) // 2
            print(f"  Batch {batch_label} of {len(urls)} hit Apify's 300s platform timeout — "
                  f"splitting into two halves ({mid} + {len(urls) - mid}) and retrying...")
            first_half = run_actor(urls[:mid], token, batch_label=f"{batch_label}-a", max_concurrency=max_concurrency, _depth=_depth + 1)
            second_half = run_actor(urls[mid:], token, batch_label=f"{batch_label}-b", max_concurrency=max_concurrency, _depth=_depth + 1)
            return first_half + second_half
        print(f"  ERROR running actor for batch {batch_label}: {resp.status_code} {resp.text[:300]}", file=sys.stderr)
        return []
    items = resp.json()
    # Safety check: if the actor ever falls back to its default input again
    # (e.g. a future field-name change), we'll catch it here instead of
    # silently getting garbage results.
    returned_urls = {item.get("url") for item in items} if isinstance(items, list) else set()
    if returned_urls and not returned_urls & set(urls):
        print(
            f"  WARNING: none of the requested URLs were echoed back in the results for "
            f"batch {batch_label}. Got back: {returned_urls}. This usually means the "
            f"input payload didn't match the actor's schema — check check_actor_schema.py output.",
            file=sys.stderr,
        )
    return items


def chunked(items: list, size: int):
    for i in range(0, len(items), size):
        yield items[i:i + size]


# Extracts a pack size like "88ML", "236 ML", "2 oz", "120 GM" from product
# text — used to derive a size hint from sku_query_master.csv's product_name
# column, since that canonical file doesn't have its own expected_size field.
SIZE_RE = re.compile(r'(\d+(?:\.\d+)?)\s*(ml|g|gm|oz)\b', re.IGNORECASE)

# Fixed output schema for url_mapping.csv. Writes always use exactly this
# column set — never inferred from row.keys() or results[0].keys() — because
# a resumed run can mix rows carried forward from an older/legacy-schema
# mapping file with freshly computed rows from the current schema, and
# csv.DictWriter errors if any row has a field outside the given fieldnames.
MAPPING_FIELDNAMES = [
    "search_term", "brand", "sku_ref", "expected_size",
    "priority", "format", "product_name", "is_flagged", "flag_note",
    "matched_url", "matched_title", "confidence", "possible_multipack", "notes",
]


def to_mapping_row(row: dict) -> dict:
    """Force any row (freshly computed or loaded from an existing/legacy
    mapping file) into exactly MAPPING_FIELDNAMES, filling anything missing
    with an empty string. Extra keys not in the schema are silently dropped
    rather than causing a write-time crash."""
    return {k: row.get(k, "") for k in MAPPING_FIELDNAMES}


def extract_size_hint(text: str) -> str:
    if not text:
        return ""
    matches = SIZE_RE.findall(text)
    if not matches:
        return ""
    num, unit = matches[-1]  # size is usually the last number+unit in the name
    return f"{num}{unit.upper()}"


def normalize_row(row: dict) -> dict:
    """Accept either the canonical sku_query_master.csv schema
    (sku_key, priority, format, brand, product_name, query, is_flagged,
    flag_note) or the older ad-hoc schema this script originally used
    (search_term, brand, sku_ref, expected_size), and produce a consistent
    internal shape either way. Canonical schema takes priority when present.
    """
    if "query" in row:  # canonical sku_query_master.csv schema
        return {
            "search_term": row.get("query", ""),
            "brand": row.get("brand", ""),
            "sku_ref": row.get("sku_key", ""),
            "expected_size": extract_size_hint(row.get("product_name", "")),
            "priority": row.get("priority", ""),
            "format": row.get("format", ""),
            "product_name": row.get("product_name", ""),
            "is_flagged": row.get("is_flagged", "False"),
            "flag_note": row.get("flag_note", ""),
        }
    # older ad-hoc schema — kept for backward compatibility only
    return {
        "search_term": row.get("search_term", ""),
        "brand": row.get("brand", ""),
        "sku_ref": row.get("sku_ref", ""),
        "expected_size": row.get("expected_size", ""),
        "priority": row.get("priority", ""),
        "format": row.get("format", ""),
        "product_name": row.get("product_name", ""),
        "is_flagged": "True" if not row.get("expected_size", "").strip() else "False",
        "flag_note": row.get("notes", "") if not row.get("expected_size", "").strip() else "",
    }


# ---------------------------------------------------------------------------
# Stage 1: discovery via search
# ---------------------------------------------------------------------------

def extract_candidates(html: str) -> list[dict]:
    """Pull candidate product links + surrounding text out of a search
    results (or category) page. Best-effort regex-based extraction."""
    candidates = []
    for m in LINK_RE.finditer(html):
        path, slug, product_id = m.group(1), m.group(2), m.group(3)
        # try to grab a nearby product name for matching — look at the slug
        # itself (hyphenated, close to the product name) as a fallback
        candidates.append({
            "url": f"https://www.watsons.co.th{path}",
            "slug": slug,
            "product_id": product_id,
        })
    return candidates


def score_match(search_term: str, expected_size: str, candidate: dict) -> float:
    """Simple scoring: token overlap between search term and slug, bonus if
    the expected pack size appears in the slug."""
    term_tokens = set(re.findall(r"[a-z0-9]+", search_term.lower()))
    slug_tokens = set(re.findall(r"[a-z0-9]+", candidate["slug"].lower()))
    if not term_tokens:
        return 0.0
    overlap = len(term_tokens & slug_tokens) / len(term_tokens)

    size_bonus = 0.0
    size_penalty = 0.0
    if expected_size:
        size_digits = re.sub(r"[^0-9]", "", expected_size)
        if size_digits:
            # Item 13: was `size_digits in candidate["slug"]` — a plain
            # substring check, so expected "50" matched inside "150-ml"
            # (confirmed 2026-08-09: a 50ML query top-matched a 150ml
            # product at score 1.03). Extract actual size tokens from the
            # slug (hyphens/dots normalized to spaces so "150-ml" parses
            # like "150 ml") and require an exact number match for the
            # bonus; if the slug has a DIFFERENT explicit size, penalize
            # instead of silently letting a wrong-size candidate win.
            normalized_slug = re.sub(r"[-.]", " ", candidate["slug"].lower())
            slug_sizes = {m.group(1) for m in SIZE_RE.finditer(normalized_slug)}
            if size_digits in slug_sizes:
                size_bonus = 0.3
            elif slug_sizes:
                size_penalty = 0.5

    return overlap + size_bonus - size_penalty


def discover(input_csv: str, out_csv: str, token: str, batch_size: int = 10, sleep_between: float = 1.0, max_concurrency: int = 5, force: bool = False):
    raw_rows = read_csv_rows(input_csv)  # item 9: BOM-tolerant read
    rows = [normalize_row(r) for r in raw_rows]

    # --- Item 1: pre-run summary before any paid call ---
    from collections import Counter
    brand_counts = Counter(r["brand"] for r in rows)
    unique_skus = len({r["sku_ref"] for r in rows})
    flagged = [r for r in rows if r.get("is_flagged") == "True"]
    schema_used = "canonical sku_query_master.csv" if "query" in raw_rows[0] else "legacy ad-hoc schema"

    print(f"=== Pre-run summary: {input_csv} ({schema_used}) ===")
    print(f"Total query count: {len(rows)}")
    print(f"Unique SKU-family count: {unique_skus}")
    print("Breakdown by brand:")
    for brand, count in sorted(brand_counts.items()):
        print(f"  {brand}: {count}")
    if flagged:
        print(f"Flagged rows (is_flagged=True): {len(flagged)}")
        for r in flagged:
            print(f"  - {r['search_term']} (sku_ref={r['sku_ref']}) — {r.get('flag_note', '')}")
    print("=" * 40)

    # Resume support: if out_csv already exists from a previous (possibly
    # interrupted) run, carry forward any rows that already got a real
    # matched_url, and only re-query the ones that failed or never ran.
    # Natural key: (sku_ref, brand, search_term) uniquely identifies a query
    # row in the master file.
    current_keys = {(r["sku_ref"], r["brand"], r["search_term"]) for r in rows}
    carried_forward = {}
    if os.path.exists(out_csv) and not force:
        try:
            previous = read_csv_rows(out_csv)
            dropped_orphans = 0
            dropped_wrong_site = 0
            for r in previous:
                key = (r.get("sku_ref", ""), r.get("brand", ""), r.get("search_term", ""))
                matched_url = r.get("matched_url") or ""
                if matched_url and "watsons.co.th" not in matched_url:
                    # Guard against contamination from other scrapers (e.g.
                    # bigc_scraper.py) sharing the same default out_csv
                    # filename in this working directory — confirmed
                    # 2026-08-08/09: 72 bigc.co.th URLs were silently carried
                    # forward and nearly got scraped/committed as Watsons
                    # pricing. Never carry forward a non-Watsons URL.
                    dropped_wrong_site += 1
                    continue
                if matched_url and key in current_keys:
                    # Normalize through to_mapping_row so a carried-forward
                    # row from an older/legacy-schema file (missing columns
                    # like format/priority/is_flagged) can't crash the CSV
                    # writer later when mixed with freshly computed rows.
                    carried_forward[key] = to_mapping_row(r)
                elif matched_url:
                    dropped_orphans += 1
            if dropped_wrong_site:
                print(f"WARNING: dropped {dropped_wrong_site} carried-forward row(s) from {out_csv} with a "
                      f"non-watsons.co.th matched_url (contamination from another scraper sharing this "
                      f"filename) — these will be re-queried fresh.")
            if dropped_orphans:
                print(f"Dropped {dropped_orphans} carried-forward row(s) from {out_csv} that no longer "
                      f"match any query in the current {input_csv} (e.g. renamed/removed entries).")
        except Exception as e:
            print(f"Could not read existing {out_csv} to resume ({e}) — starting fresh.")

    if carried_forward:
        before = len(rows)
        rows = [r for r in rows if (r["sku_ref"], r["brand"], r["search_term"]) not in carried_forward]
        print(f"Resume: {len(carried_forward)}/{before} queries already matched in {out_csv} — "
              f"carrying those forward and only re-querying the remaining {len(rows)} "
              f"(use --force to re-query everything from scratch)")
    print()

    if not rows:
        print("Nothing left to discover — every query already has a match. Nothing to do.")
        return

    results = list(carried_forward.values())
    processed_this_run = 0
    total_to_process = len(rows)

    for batch in chunked(rows, batch_size):
        search_urls = [SEARCH_URL_TMPL.format(query=requests.utils.quote(r["search_term"])) for r in batch]
        print(f"  Searching batch of {len(batch)}: {[r['search_term'] for r in batch]}")
        items = run_actor(search_urls, token, batch_label="discover", max_concurrency=max_concurrency)
        url_to_item = {item.get("url"): item for item in items}

        # Item 12: the actor flags its own incomplete fetches via
        # dataQuality="partial" (confirmed 2026-08-09 — a partial fetch of
        # this Angular/SAP-Commerce storefront returns the app shell before
        # the client-side product-search API call finishes, so the HTML has
        # no product grid yet). That's the real cause of the intermittent
        # "no product links found" failures, not a broken regex. Retry once,
        # serially, for any URL that came back partial/blocked with zero
        # candidates before giving up on it.
        # NOTE: confirmed via a real dataset sample (2026-08-09) that the
        # actor's dataQuality values are "ok" (good) and "partial" (bad) —
        # NOT "full"/other. Checking `!= "full"` would misfire a retry on
        # every genuinely good "ok" fetch, so match "partial" explicitly.
        retry_urls = []
        for search_url in search_urls:
            item = url_to_item.get(search_url, {})
            html = item.get("html", "")
            is_bad_quality = item.get("dataQuality") == "partial" or item.get("blocked")
            if html and is_bad_quality and not extract_candidates(html):
                retry_urls.append(search_url)
        if retry_urls:
            print(f"    Retrying {len(retry_urls)} partial/blocked fetch(es) with no product links found...")
            retry_items = run_actor(retry_urls, token, batch_label="discover-retry", max_concurrency=1)
            for item in retry_items:
                url_to_item[item.get("url")] = item

        url_to_html = {url: item.get("html", "") for url, item in url_to_item.items()}

        for row, search_url in zip(batch, search_urls):
            html = url_to_html.get(search_url, "")
            is_multipack = flag_multipack(row.get("search_term", ""))  # item 4

            if not html:
                results.append(to_mapping_row({**row, "matched_url": "", "matched_title": "", "confidence": 0, "possible_multipack": is_multipack, "notes": "no html returned"}))
                continue

            candidates = extract_candidates(html)
            if not candidates:
                results.append(to_mapping_row({**row, "matched_url": "", "matched_title": "", "confidence": 0, "possible_multipack": is_multipack, "notes": "no product links found in search results"}))
                continue

            scored = [
                (score_match(row["search_term"], row.get("expected_size", ""), c), c)
                for c in candidates
            ]
            scored.sort(key=lambda x: x[0], reverse=True)
            best_score, best = scored[0]

            match_is_multipack = is_multipack or flag_multipack(best["slug"])

            results.append(to_mapping_row({
                **row,
                "matched_url": best["url"],
                "matched_title": best["slug"].replace("-", " "),
                "confidence": round(best_score, 2),
                "possible_multipack": match_is_multipack,
                "notes": "top of {} candidates".format(len(candidates)) if best_score > 0.3 else "LOW CONFIDENCE - review manually",
            }))

        processed_this_run += len(batch)

        # Item 7: write out after every batch, not just at the end, so an
        # interruption leaves a usable partial file instead of nothing.
        if results:
            write_csv_rows(out_csv, results, MAPPING_FIELDNAMES)
            print(f"    (checkpoint: {len(results)} total rows written to {out_csv}; "
                  f"{processed_this_run}/{total_to_process} processed in this run)")

        time.sleep(sleep_between)

    write_csv_rows(out_csv, results, MAPPING_FIELDNAMES)  # item 9: BOM-safe write

    def _conf(r):
        """Confidence may be a string (loaded from a carried-forward CSV row)
        or a float (freshly computed this run) — normalize before comparing."""
        try:
            return float(r.get("confidence") or 0)
        except (TypeError, ValueError):
            return 0.0

    def _truthy(v):
        """possible_multipack may be a Python bool (fresh) or the string
        'True'/'False' (carried forward from CSV) — normalize both."""
        return v is True or str(v).strip().lower() == "true"

    n_matched = sum(1 for r in results if r.get("matched_url"))
    n_low_conf = sum(1 for r in results if r.get("matched_url") and _conf(r) < 0.3)
    n_multipack = sum(1 for r in results if _truthy(r.get("possible_multipack")))
    print(f"\nWrote {len(results)} rows to {out_csv}")
    print(f"Matched: {n_matched}/{len(results)}  |  Low confidence (review manually): {n_low_conf}")
    if n_multipack:
        print(f"Possible multipack/bundle listings flagged: {n_multipack} — review 'possible_multipack' column before including in per-unit price comparisons")
    print("IMPORTANT: open the output CSV and eyeball the 'matched_url'/'matched_title' "
          "columns before proceeding to scrape — this is fuzzy matching, not exact.")


# ---------------------------------------------------------------------------
# Stage 2: scrape matched product pages
# ---------------------------------------------------------------------------

def find_json_ld_blocks(html: str) -> list[dict]:
    blocks = []
    for match in re.finditer(r'<script type="application/ld\+json"[^>]*>(.*?)</script>', html, re.DOTALL):
        raw = match.group(1).strip()
        try:
            data = json.loads(raw)
        except json.JSONDecodeError:
            continue
        if isinstance(data, list):
            blocks.extend([d for d in data if isinstance(d, dict)])
        elif isinstance(data, dict):
            blocks.append(data)
    return blocks


def extract_product(html: str) -> Optional[dict]:
    for block in find_json_ld_blocks(html):
        if block.get("@type") == "Product":
            offer = block.get("offers", {}) or {}
            brand = block.get("brand", {}) or {}

            # CONFIRMED 2026-08-08 on Watsons TH: this site uses @type
            # "AggregateOffer" (not plain "Offer") with lowPrice/highPrice
            # fields when a product is on promo. offer["price"] holds the
            # LIST price (e.g. 770), NOT the current sale price — the actual
            # displayed/sale price (e.g. 499, 35% off) is in offer["lowPrice"].
            # When lowPrice is present, treat it as the current price and
            # keep highPrice as the list price for reference/discount-calc.
            is_aggregate = isinstance(offer, dict) and offer.get("@type") == "AggregateOffer"
            low_price = offer.get("lowPrice") if is_aggregate else None
            high_price = offer.get("highPrice") if is_aggregate else None

            if low_price is not None:
                current_price = low_price
                list_price = high_price
            else:
                current_price = offer.get("price") if isinstance(offer, dict) else None
                list_price = None

            return {
                "name": block.get("name"),
                "sku": block.get("sku"),
                "gtin": block.get("gtin"),
                "brand": brand.get("name") if isinstance(brand, dict) else brand,
                "price": current_price,       # now the ACTUAL/sale price when on promo
                "list_price": list_price,     # None when not on promo / not AggregateOffer
                "currency": offer.get("priceCurrency") if isinstance(offer, dict) else None,
                "availability": offer.get("availability") if isinstance(offer, dict) else None,
            }
    # FALLBACK regex path — this block is Big-C-specific markup carried over
    # unchanged and almost certainly will NOT match Watsons TH's HTML.
    # UNVALIDATED: view-source a real Watsons TH product page and replace
    # the id="pdp_brand-title" / "productDetail_baht" selectors below with
    # whatever Watsons actually uses. The <h1> name fallback is generic
    # enough it may work as-is; the brand/price selectors need replacing.
    out = {}
    m = re.search(r'<h1>([^<]+)</h1>', html)
    if m:
        out["name"] = m.group(1).strip()
    m = re.search(r'id="pdp_brand-title">([^<]+)<', html)  # TODO: replace — Watsons markup
    if m:
        out["brand"] = m.group(1).strip()
    m = re.search(r'productDetail_baht[^>]*>\s*</span>\s*([\d,]+\.\d{2})', html)  # TODO: replace — Watsons markup
    if m:
        out["price"] = m.group(1).replace(",", "")
    return out if out else None


def init_db(db_path: str):
    conn = sqlite3.connect(db_path)
    conn.execute("PRAGMA journal_mode=WAL;")
    conn.execute("""
        CREATE TABLE IF NOT EXISTS watsons_pricing (
            id INTEGER PRIMARY KEY AUTOINCREMENT,
            snapshot_label TEXT,
            sku_ref TEXT,
            brand TEXT,
            search_term TEXT,
            watsons_url TEXT,
            product_name TEXT,
            product_sku TEXT,
            gtin TEXT,
            price TEXT,
            list_price TEXT,
            currency TEXT,
            availability TEXT,
            possible_multipack INTEGER DEFAULT 0,
            scraped_at TEXT DEFAULT (datetime('now')),
            notes TEXT
        )
    """)

    # Migration: an older version of this script may have already created
    # watsons_pricing without snapshot_label/possible_multipack. CREATE TABLE
    # IF NOT EXISTS won't add columns to an existing table, so check and
    # patch it here before anything tries to reference those columns.
    existing_cols = {row[1] for row in conn.execute("PRAGMA table_info(watsons_pricing)").fetchall()}
    migrations = {
        "snapshot_label": "ALTER TABLE watsons_pricing ADD COLUMN snapshot_label TEXT DEFAULT ''",
        "possible_multipack": "ALTER TABLE watsons_pricing ADD COLUMN possible_multipack INTEGER DEFAULT 0",
        "list_price": "ALTER TABLE watsons_pricing ADD COLUMN list_price TEXT",
    }
    for col, ddl in migrations.items():
        if col not in existing_cols:
            print(f"Migrating existing DB: adding missing column '{col}' to watsons_pricing")
            conn.execute(ddl)
    if migrations.keys() - existing_cols:
        conn.commit()
        # SQLite ALTER TABLE ADD COLUMN can't backfill NULL snapshot_label
        # rows with '' retroactively via the DDL default on older SQLite
        # versions in all cases — normalize explicitly to be safe.
        conn.execute("UPDATE watsons_pricing SET snapshot_label = '' WHERE snapshot_label IS NULL")
        conn.commit()

    # An older, pre-migration DB had no uniqueness constraint at all, so it
    # may already contain duplicate (watsons_url, snapshot_label) rows from
    # earlier runs. Creating the unique index below would fail on those —
    # clean up by keeping only the most recent row (highest id) per key.
    dupes = conn.execute("""
        SELECT watsons_url, snapshot_label, COUNT(*) c
        FROM watsons_pricing
        GROUP BY watsons_url, snapshot_label
        HAVING c > 1
    """).fetchall()
    if dupes:
        print(f"Found {len(dupes)} duplicate (watsons_url, snapshot_label) group(s) in the existing DB "
              f"from before this script tracked uniqueness — keeping only the most recent row for each.")
        conn.execute("""
            DELETE FROM watsons_pricing
            WHERE id NOT IN (
                SELECT MAX(id) FROM watsons_pricing GROUP BY watsons_url, snapshot_label
            )
        """)
        conn.commit()

    # Item 10: natural key for dedup within the same snapshot day —
    # (watsons_url, snapshot_label) uniquely identifies "this SKU, this pull".
    # Different snapshot_labels (different days/events) are NOT deduped
    # against each other, so price history over time is preserved.
    conn.execute("""
        CREATE UNIQUE INDEX IF NOT EXISTS idx_watsons_pricing_natural_key
        ON watsons_pricing (watsons_url, snapshot_label)
    """)
    conn.commit()
    return conn


def get_already_scraped(conn, snapshot_label: str) -> set:
    """Item 8: resume support — URLs already saved for this exact snapshot
    label, so a re-run after an interruption doesn't re-pay for them.

    IMPORTANT: only counts a URL as "done" if it actually got a real price.
    A row can exist in the DB from a failed attempt (e.g. the 2026-08-08
    incident where every request failed with invalid-input due to
    max_concurrency > 5, but all 91 rows still got INSERTed with
    price=NULL and a MISSING PRICE note) — those must NOT block a retry,
    or a corrected re-run silently thinks everything is already done while
    the DB actually holds zero usable price data for that snapshot.
    """
    cursor = conn.execute(
        "SELECT watsons_url FROM watsons_pricing WHERE snapshot_label = ? "
        "AND price IS NOT NULL AND TRIM(price) != ''",
        (snapshot_label,),
    )
    return {row[0] for row in cursor.fetchall()}


def scrape(input_csv: str, token: str, db_path: str, export_csv: Optional[str], batch_size: int = 10, sleep_between: float = 1.0, snapshot_label: str = "", force: bool = False, max_concurrency: int = 5):
    all_rows = read_csv_rows(input_csv)  # item 9: BOM-tolerant read
    rows = [r for r in all_rows if r.get("matched_url")]
    wrong_site = [r for r in rows if "watsons.co.th" not in r["matched_url"]]
    if wrong_site:
        print(f"WARNING: skipping {len(wrong_site)} row(s) with a non-watsons.co.th matched_url "
              f"(contamination guard) — these will never be scraped as Watsons pricing.")
        rows = [r for r in rows if "watsons.co.th" in r["matched_url"]]

    print(f"Loaded {len(rows)} matched URLs to scrape from {input_csv}")
    if snapshot_label:
        print(f"Snapshot label: {snapshot_label}")
    else:
        print("WARNING: no --snapshot-label given. Rows will still be deduped/resumed using an "
              "empty-string label, but you won't be able to tell this run apart from any other "
              "unlabeled run later. Strongly recommend passing one, e.g. --snapshot-label 8.8_sale_2026-08-08")

    # Item 11: backup before any write session begins
    backup_db(db_path)

    conn = init_db(db_path)

    # Item 8: resume support — skip URLs already scraped for this exact snapshot label
    already_done = set() if force else get_already_scraped(conn, snapshot_label)
    if already_done and not force:
        skip_count = sum(1 for r in rows if r["matched_url"] in already_done)
        if skip_count:
            print(f"Resume: {skip_count}/{len(rows)} URLs already scraped for this snapshot label — skipping "
                  f"(use --force to re-scrape and overwrite them anyway)")
        rows = [r for r in rows if r["matched_url"] not in already_done]

    if not rows:
        print("Nothing left to scrape (all URLs already done for this snapshot label, or input was empty).")
        conn.close()
        return

    all_results = []

    for batch in chunked(rows, batch_size):
        urls = [r["matched_url"] for r in batch]
        print(f"  Scraping batch of {len(batch)} product pages...")
        items = run_actor(urls, token, batch_label="scrape", max_concurrency=max_concurrency)
        url_to_item = {item.get("url"): item for item in items}

        # Item 12: same partial-fetch retry as discover() — a product page
        # can also come back as an unhydrated app shell with no JSON-LD yet.
        # dataQuality values are "ok"/"partial", not "full" — see discover().
        retry_urls = []
        for url in urls:
            item = url_to_item.get(url, {})
            html = item.get("html", "")
            is_bad_quality = item.get("dataQuality") == "partial" or item.get("blocked")
            if html and is_bad_quality and not extract_product(html):
                retry_urls.append(url)
        if retry_urls:
            print(f"    Retrying {len(retry_urls)} partial/blocked product page fetch(es)...")
            retry_items = run_actor(retry_urls, token, batch_label="scrape-retry", max_concurrency=1)
            for item in retry_items:
                url_to_item[item.get("url")] = item

        for row in batch:
            item = url_to_item.get(row["matched_url"], {})
            html = item.get("html", "")
            blocked = item.get("blocked", None)
            status = item.get("statusCode", None)

            product = extract_product(html) if html else None
            product_name = product.get("name") if product else None
            # Item 4: flag multipack using both the scraped product name and
            # the original search term / matched title, whichever is available
            is_multipack = flag_multipack(product_name) or flag_multipack(row.get("search_term", "")) or flag_multipack(row.get("matched_title", ""))

            record = {
                "snapshot_label": snapshot_label,
                "sku_ref": row.get("sku_ref", ""),
                "brand": row.get("brand", ""),
                "search_term": row.get("search_term", ""),
                "watsons_url": row["matched_url"],
                "product_name": product_name,
                "product_sku": product.get("sku") if product else None,
                "gtin": product.get("gtin") if product else None,
                "price": product.get("price") if product else None,
                "list_price": product.get("list_price") if product else None,
                "currency": product.get("currency") if product else None,
                "availability": product.get("availability") if product else None,
                "possible_multipack": int(is_multipack),
                "notes": "" if product and product.get("price") else f"NO PRICE (status={status}, blocked={blocked})",
            }
            all_results.append(record)

            # Item 10: INSERT OR REPLACE on the natural key (watsons_url, snapshot_label)
            # — reruns within the same snapshot day overwrite rather than duplicate;
            # different snapshot_labels (different days) are untouched.
            conn.execute("""
                INSERT OR REPLACE INTO watsons_pricing
                (snapshot_label, sku_ref, brand, search_term, watsons_url, product_name, product_sku, gtin, price, list_price, currency, availability, possible_multipack, notes)
                VALUES (:snapshot_label, :sku_ref, :brand, :search_term, :watsons_url, :product_name, :product_sku, :gtin, :price, :list_price, :currency, :availability, :possible_multipack, :notes)
            """, record)
            conn.commit()  # item 7: incremental save, per-row

            status_label = "OK" if record["price"] else "MISSING PRICE"
            multipack_tag = " [POSSIBLE MULTIPACK]" if is_multipack else ""
            print(f"    {row['matched_url']}: {status_label}{multipack_tag}")

        # Item 7: write the CSV export after every batch, not just at the end,
        # so an interruption leaves a usable partial file, not nothing.
        if export_csv and all_results:
            fieldnames = list(all_results[0].keys())
            write_csv_rows(export_csv, all_results, fieldnames)

        time.sleep(sleep_between)

    conn.close()

    n_ok = sum(1 for r in all_results if r["price"])
    n_multipack = sum(1 for r in all_results if r["possible_multipack"])
    print(f"\nSaved {len(all_results)} rows to {db_path} (table: watsons_pricing)")
    print(f"Prices successfully extracted: {n_ok}/{len(all_results)}")
    if n_multipack:
        print(f"Possible multipack/bundle listings: {n_multipack} — exclude these before per-unit price averaging")

    if export_csv:
        print(f"Exported to {export_csv}")

    # Item 3: cost estimate calibration — be honest this isn't a trusted number yet
    print(
        "\nCost note: the actor's advertised rate is ~$2 per 1,000 successful pages. "
        "This has only been spot-checked on a handful of test pages so far, not calibrated "
        "against a real run of this size — check your actual Apify usage/cost dashboard "
        "after this run to see the real per-page cost, rather than trusting the theoretical rate."
    )


# ---------------------------------------------------------------------------
# CLI
# ---------------------------------------------------------------------------

def main():
    ap = argparse.ArgumentParser(description="Watsons Thailand pricing scraper")
    sub = ap.add_subparsers(dest="command", required=True)

    p_discover = sub.add_parser("discover", help="Find Watsons TH product URLs for your SKU list via search")
    p_discover.add_argument("--input", required=True, help="CSV with columns: search_term, brand, sku_ref[, expected_size]")
    p_discover.add_argument("--out", default="url_mapping.csv")
    p_discover.add_argument("--token", default=None, help="Apify token (optional if APIFY_TOKEN is set in .env)")
    p_discover.add_argument("--batch-size", type=int, default=5, help="Kept small since the actor's sync API endpoint has a hard 300s server-side timeout regardless of client timeout settings — a batch of slow/hanging pages can blow past it.")
    p_discover.add_argument("--max-concurrency", type=int, default=5, help="Actor default is 1 (serial, slow); hard cap is 5, values above that are clamped automatically.")
    p_discover.add_argument("--force", action="store_true", help="Re-query everything from scratch, ignoring any existing matches already in --out")

    p_scrape = sub.add_parser("scrape", help="Scrape matched product pages from a discovery output CSV")
    p_scrape.add_argument("--input", required=True, help="CSV with a matched_url column (output of 'discover')")
    p_scrape.add_argument("--token", default=None, help="Apify token (optional if APIFY_TOKEN is set in .env)")
    p_scrape.add_argument("--db", default="watsons_pricing.db")
    p_scrape.add_argument("--export-csv", nargs="?", const="watsons_pricing_export.csv", default=None)
    p_scrape.add_argument("--batch-size", type=int, default=10)
    p_scrape.add_argument("--snapshot-label", default="", help="e.g. '8.8_sale_2026-08-08' or 'steady_state_2026-07-29' — tags this run so multiple snapshots over time stay distinguishable")
    p_scrape.add_argument("--force", action="store_true", help="Re-scrape and overwrite URLs already saved for this snapshot label (default: skip them)")
    p_scrape.add_argument("--max-concurrency", type=int, default=5, help="Actor default is 1 (serial, slow); hard cap is 5, values above that are clamped automatically.")

    p_all = sub.add_parser("all", help="Run discover then scrape in one go")
    p_all.add_argument("--input", required=True)
    p_all.add_argument("--token", default=None, help="Apify token (optional if APIFY_TOKEN is set in .env)")
    p_all.add_argument("--db", default="watsons_pricing.db")
    p_all.add_argument("--export-csv", nargs="?", const="watsons_pricing_export.csv", default=None)
    p_all.add_argument("--batch-size", type=int, default=10)
    p_all.add_argument("--mapping-out", default="url_mapping.csv")
    p_all.add_argument("--snapshot-label", default="")
    p_all.add_argument("--force", action="store_true")
    p_all.add_argument("--max-concurrency", type=int, default=5)

    args = ap.parse_args()
    token = resolve_token(args.token)

    if args.command == "discover":
        discover(args.input, args.out, token, batch_size=args.batch_size, max_concurrency=args.max_concurrency, force=args.force)
    elif args.command == "scrape":
        scrape(args.input, token, args.db, args.export_csv, batch_size=args.batch_size, snapshot_label=args.snapshot_label, force=args.force, max_concurrency=args.max_concurrency)
    elif args.command == "all":
        discover(args.input, args.mapping_out, token, batch_size=args.batch_size, max_concurrency=args.max_concurrency, force=args.force)
        print("\n--- Discovery complete. Starting scrape stage. ---\n")
        scrape(args.mapping_out, token, args.db, args.export_csv, batch_size=args.batch_size, snapshot_label=args.snapshot_label, force=args.force, max_concurrency=args.max_concurrency)


if __name__ == "__main__":
    main()
