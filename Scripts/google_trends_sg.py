"""
google_trends_sg.py -- Google Trends interest-over-time for the SG brand search terms.

Source status: GO (Logs/summary.md, 2026-10-01). No Apify -- uses the
`pytrends-modern` library (the original pytrends was archived Apr 2025),
which calls Google Trends' public web endpoints from this machine's own IP.

WHAT THE NUMBERS MEAN
  Google Trends returns a NORMALIZED 0-100 interest index (100 = peak
  popularity for the terms in that request over the window), NOT absolute
  search volume. Terms are only comparable within one batch, so every batch
  carries the same anchor term ("contact lens") -- use `--anchor-scale` views
  (value / anchor value) in the dashboard when comparing across batches.

COLLECTION STANCE
  source_access_method = public_web, collection_risk = medium (unofficial
  endpoint, own IP, 429-prone). Sequential requests only, 8-15 s between
  calls, exponential backoff on 429, and a one-time 5-year weekly snapshot per
  batch (trends_scraped_sources) so history is never re-downloaded unless
  --force-rescrape. Nothing is logged except term lists and row counts.

Own db: Scripts/output/trends_data_sg.db
  trends_interest, trends_related, trends_scraped_sources

Usage (run --dry-run first):
  python Scripts/google_trends_sg.py --dry-run
  python Scripts/google_trends_sg.py
  python Scripts/google_trends_sg.py --skip-related --export-csv
"""

import argparse
import csv
import logging
import os
import random
import sqlite3
import sys
import time
from datetime import datetime, timezone

SCRIPT_DIR = os.path.dirname(os.path.abspath(__file__))
DEFAULT_DB = os.path.join(SCRIPT_DIR, "output", "trends_data_sg.db")

SOURCE_ACCESS_METHOD = "public_web"
COLLECTION_RISK = "medium"

GEO = "SG"
TIMEFRAME = "today 5-y"  # weekly points, ~260 observations
ANCHOR_TERM = "contact lens"
BATCH_SIZE = 4  # + anchor = 5, Google Trends' per-request maximum
SLEEP_RANGE = (8.0, 15.0)
MAX_RETRIES = 4

# Brand -> search terms. Taken from BRAND_KEYWORDS / BRAND_ALIASES in
# reddit_scraper_sg.py; kept to 1-2 unambiguous consumer-facing terms per brand
# (generic words like "vision" or "dailies" alone would be noise).
BRAND_TERMS = {
    "MyACUVUE":      ["Acuvue"],
    "Alcon":         ["Air Optix", "Dailies Total30"],
    "CooperVision":  ["Biofinity", "CooperVision"],
    "Bausch + Lomb": ["Biotrue", "Bausch Lomb"],
    "Olens":         ["Olens"],
}

logging.basicConfig(level=logging.INFO, format="[%(levelname)s] %(message)s")
log = logging.getLogger("google_trends_sg")


def term_brand_map() -> dict:
    m = {ANCHOR_TERM: "(anchor)"}
    for brand, terms in BRAND_TERMS.items():
        for t in terms:
            m[t] = brand
    return m


def build_batches() -> list:
    terms = [t for ts in BRAND_TERMS.values() for t in ts]
    return [terms[i:i + BATCH_SIZE] + [ANCHOR_TERM] for i in range(0, len(terms), BATCH_SIZE)]


def batch_key(batch: list) -> str:
    return f"{GEO}|{TIMEFRAME}|" + "|".join(sorted(batch))


# ── DB ────────────────────────────────────────────────────────────────
def open_db(path: str) -> sqlite3.Connection:
    os.makedirs(os.path.dirname(path), exist_ok=True)
    conn = sqlite3.connect(path)
    conn.execute("PRAGMA journal_mode=WAL")
    conn.executescript("""
        CREATE TABLE IF NOT EXISTS trends_interest (
            term TEXT NOT NULL,
            brand TEXT NOT NULL,
            geo TEXT NOT NULL,
            date TEXT NOT NULL,
            value INTEGER,
            is_partial INTEGER,
            batch_key TEXT,
            pulled_at TEXT NOT NULL,
            source_access_method TEXT NOT NULL,
            collection_risk TEXT NOT NULL,
            PRIMARY KEY (term, geo, date, batch_key)
        );
        CREATE TABLE IF NOT EXISTS trends_related (
            term TEXT NOT NULL,
            brand TEXT NOT NULL,
            geo TEXT NOT NULL,
            kind TEXT NOT NULL,            -- 'top' | 'rising'
            related_query TEXT NOT NULL,
            value TEXT,                    -- top: 0-100; rising: % growth or 'Breakout'
            pulled_at TEXT NOT NULL,
            source_access_method TEXT NOT NULL,
            collection_risk TEXT NOT NULL,
            PRIMARY KEY (term, geo, kind, related_query, pulled_at)
        );
        CREATE TABLE IF NOT EXISTS trends_scraped_sources (
            batch_key TEXT PRIMARY KEY,
            terms TEXT,
            rows_saved INTEGER,
            pulled_at TEXT NOT NULL
        );
    """)
    conn.commit()
    return conn


def already_scraped(conn, key: str) -> bool:
    return conn.execute("SELECT 1 FROM trends_scraped_sources WHERE batch_key=?", (key,)).fetchone() is not None


# ── Google Trends calls ───────────────────────────────────────────────
def polite_sleep():
    time.sleep(random.uniform(*SLEEP_RANGE))


def with_backoff(fn, label: str):
    """Run fn(); on 429/transient failure wait 2^n * 30 s and retry."""
    for attempt in range(1, MAX_RETRIES + 1):
        try:
            return fn()
        except Exception as exc:  # TooManyRequestsError / ResponseError / network
            if attempt == MAX_RETRIES:
                raise
            wait = 30 * (2 ** (attempt - 1))
            log.warning(f"[RETRY] {label}: {type(exc).__name__} (attempt {attempt}/{MAX_RETRIES}), waiting {wait}s")
            time.sleep(wait)


def make_client():
    from pytrends_modern import TrendReq
    return TrendReq(hl="en-SG", tz=-480, geo=GEO, timeout=(10, 25), retries=2, backoff_factor=0.5)


def fetch_interest(client, batch: list):
    def _go():
        client.build_payload(batch, timeframe=TIMEFRAME, geo=GEO)
        return client.interest_over_time()
    return with_backoff(_go, f"interest {batch}")


def fetch_related(client, term: str):
    def _go():
        client.build_payload([term], timeframe=TIMEFRAME, geo=GEO)
        return client.related_queries()
    return with_backoff(_go, f"related {term!r}")


# ── Save ──────────────────────────────────────────────────────────────
def interest_rows(df, batch: list, key: str, pulled_at: str) -> list:
    tmap = term_brand_map()
    rows = []
    if df is None or df.empty:
        return rows
    partial = df["isPartial"] if "isPartial" in df.columns else None
    for term in batch:
        if term not in df.columns:
            continue
        for i, (idx, val) in enumerate(df[term].items()):
            is_partial = int(bool(partial.iloc[i])) if partial is not None else 0
            rows.append((term, tmap[term], GEO, idx.strftime("%Y-%m-%d"), int(val), is_partial,
                         key, pulled_at, SOURCE_ACCESS_METHOD, COLLECTION_RISK))
    return rows


def related_rows(result: dict, term: str, brand: str, pulled_at: str) -> list:
    rows = []
    for kind in ("top", "rising"):
        df = (result.get(term) or {}).get(kind)
        if df is None or getattr(df, "empty", True):
            continue
        for _, r in df.iterrows():
            rows.append((term, brand, GEO, kind, str(r["query"]), str(r["value"]), pulled_at,
                         SOURCE_ACCESS_METHOD, COLLECTION_RISK))
    return rows


def save_batch(conn, key, batch, i_rows, r_rows, pulled_at):
    """One transaction per batch (Drive-synced DB: many tiny commits have
    silently dropped writes before -- see Logs/summary.md 2026-09-30)."""
    with conn:
        conn.executemany("INSERT OR IGNORE INTO trends_interest VALUES (?,?,?,?,?,?,?,?,?,?)", i_rows)
        conn.executemany("INSERT OR IGNORE INTO trends_related VALUES (?,?,?,?,?,?,?,?,?)", r_rows)
        conn.execute("INSERT OR REPLACE INTO trends_scraped_sources VALUES (?,?,?,?)",
                     (key, ", ".join(batch), len(i_rows), pulled_at))


def export_csv(conn, out_dir: str):
    os.makedirs(out_dir, exist_ok=True)
    stamp = datetime.now().strftime("%Y%m%d_%H%M")
    path = os.path.join(out_dir, f"trends_sg_interest_{stamp}.csv")
    cur = conn.execute("SELECT term, brand, geo, date, value, is_partial, pulled_at FROM trends_interest ORDER BY term, date")
    with open(path, "w", newline="", encoding="utf-8") as f:
        w = csv.writer(f)
        w.writerow([c[0] for c in cur.description])
        w.writerows(cur)
    log.info(f"[EXPORT] {path}")


# ── Main ──────────────────────────────────────────────────────────────
def run(args):
    batches = build_batches()
    related_terms = [] if args.skip_related else [t for ts in BRAND_TERMS.values() for t in ts]
    n_requests = len(batches) + len(related_terms)
    log.info(f"[PLAN] geo={GEO} timeframe={TIMEFRAME} anchor={ANCHOR_TERM!r} | "
             f"{len(batches)} interest batches + {len(related_terms)} related lookups = {n_requests} requests, "
             f"~{int(n_requests * sum(SLEEP_RANGE) / 2)}s with sleeps")
    for b in batches:
        log.info(f"[PLAN] batch: {b}")
    log.info("[NOTE] Values are a normalized 0-100 interest index, not search volume.")

    if args.dry_run:
        log.info("[DRY-RUN] No requests made, nothing written.")
        return 0

    conn = open_db(args.db)
    client = make_client()
    pulled_at = datetime.now(timezone.utc).isoformat(timespec="seconds")
    tmap = term_brand_map()
    total = 0

    for batch in batches:
        key = batch_key(batch)
        if already_scraped(conn, key) and not args.force_rescrape:
            log.info(f"[SKIP] already pulled: {batch}")
            continue
        log.info(f"[PULL] interest_over_time: {batch}")
        df = fetch_interest(client, batch)
        i_rows = interest_rows(df, batch, key, pulled_at)
        r_rows = []
        for term in (t for t in batch if t in related_terms):
            polite_sleep()
            log.info(f"[PULL] related_queries: {term!r}")
            try:
                r_rows += related_rows(fetch_related(client, term), term, tmap[term], pulled_at)
            except Exception as exc:
                log.warning(f"[WARN] related queries failed for {term!r}: {type(exc).__name__}")
        save_batch(conn, key, batch, i_rows, r_rows, pulled_at)
        total += len(i_rows)
        log.info(f"[SAVED] {len(i_rows)} interest rows, {len(r_rows)} related rows")
        polite_sleep()

    log.info(f"[DONE] {total} interest rows saved to {args.db}")
    if args.export_csv:
        export_csv(conn, os.path.join(SCRIPT_DIR, "output"))
    conn.close()
    return 0


def main():
    p = argparse.ArgumentParser(description="Google Trends (SG) brand-term interest over time")
    p.add_argument("--dry-run", action="store_true", help="print the request plan; no requests, no writes")
    p.add_argument("--force-rescrape", action="store_true", help="re-pull batches already in trends_scraped_sources")
    p.add_argument("--skip-related", action="store_true", help="skip related/rising query lookups")
    p.add_argument("--export-csv", action="store_true")
    p.add_argument("--db", default=DEFAULT_DB)
    return run(p.parse_args())


if __name__ == "__main__":
    sys.exit(main())
