"""
Acne-Aid Thailand — Market Intelligence Pipeline
==================================================
Standalone project. References the architecture of the HK contact lens
pipeline (pipeline_v2.py) as a design pattern only — no code is imported
from it, and that file is never modified. New brand, new market, new
folder, new database, per the project's own "separate projects, separate
modules" principle.

ARCHITECTURE (borrowed patterns from the lens pipeline, adapted here):
  - SQLite WAL + single-writer-thread            -> same pattern, new schema
  - ThreadPoolExecutor parallel workers            -> same pattern
  - Pydantic structured LLM output for extraction  -> same pattern, new model
  - Cost tracker for gpt-4o-mini                   -> reused as-is (same model)
  - Config-driven brand list, no code changes      -> same pattern, new YAML

WHAT'S DIFFERENT FROM THE LENS PIPELINE (validated in Phase 0, 2026-07-14):
  - Boots.co.th needs NO Playwright at all -- confirmed server-rendered HTML,
    plain `requests` works.
  - Watsons.co.th blocks plain HTTP at the connection level (Akamai-style).
    Needs Claude in Chrome or an Apify actor -- confirmed dead end for
    Playwright, see discover_watsons_th().
  - Pantip.com needs NO Playwright -- confirmed static HTML, robots.txt
    does not block general scraping.
  - Shopee TH is NOT covered by this pipeline.
  - Category taxonomy is skincare -- see classify_skincare_type().

AUDIT FIXES (2026-08-08, Boots checklist audit):
  - #10 Dedup: products table previously upserted price fields keyed ONLY by
    product_code -- every rerun silently overwrote yesterday's price with
    today's, destroying the multi-timestamp price history this project
    explicitly needs (Context.md sec. 5). Fixed by adding a `price_history`
    table keyed by (product_code, pull_date): same-day reruns update in
    place (correct -- one snapshot per SKU per day), different-day reruns
    insert a new row (price history preserved). `products` table is kept
    as-is as the "current state" table for existing dashboard consumers.
  - #11 Backup before write: backup_db() now copies the DB to a timestamped
    file before any write operation in run() (and before the standalone
    Boots-review translation script's writes), consistent with project
    standard. No-ops safely if the DB doesn't exist yet.

USAGE:
  python pipeline_th.py                          # full run, all enabled sites
  python pipeline_th.py --site boots_th          # Boots only
  python pipeline_th.py --site pantip            # Pantip search (capped at 10 results/keyword)
  python pipeline_th.py --site pantip_deep       # Pantip room-crawl deep extraction (opt-in, slow --
                                                  # see discover_pantip_deep() for why this exists)
  python pipeline_th.py --brand "Acne-Aid" "CeraVe"
  python pipeline_th.py --discover-only
"""

import argparse
import hashlib
import json
import logging
import queue
import re
import shutil
import sqlite3
import threading
import time
import urllib.parse
import urllib.request
from concurrent.futures import ThreadPoolExecutor, as_completed
from datetime import datetime, timezone
from pathlib import Path
from typing import Dict, List, Optional

import openpyxl
import requests
import yaml
from bs4 import BeautifulSoup
from dotenv import load_dotenv
from openai import OpenAI
from pydantic import BaseModel, Field

load_dotenv()

# ── LOGGING ──────────────────────────────────────────────────────────────

logging.basicConfig(
    level=logging.INFO,
    format="%(asctime)s [%(levelname)s] %(message)s",
    handlers=[logging.StreamHandler()],
)
log = logging.getLogger(__name__)


# ── BACKUP HELPER (AUDIT FIX #11) ───────────────────────────────────────
# Called before any write operation. Copies the DB file to a timestamped
# backup alongside it. Safe no-op if the DB doesn't exist yet (first run).

def backup_db(db_path: str) -> Optional[str]:
    src = Path(db_path)
    if not src.exists():
        log.info(f"[BACKUP] {db_path} does not exist yet -- skipping backup (first run)")
        return None
    ts = datetime.now(timezone.utc).strftime("%Y%m%d_%H%M%S")
    backup_path = src.with_name(f"{src.stem}.backup_{ts}{src.suffix}")
    try:
        shutil.copy2(src, backup_path)
        log.info(f"[BACKUP] {db_path} -> {backup_path}")
        return str(backup_path)
    except Exception as e:
        log.warning(f"[BACKUP] Failed to back up {db_path}: {e}")
        return None


# ── DATABASE SCHEMA ──────────────────────────────────────────────────────
# Same WAL + single-writer-thread pattern as the lens pipeline. Schema is
# new: pack_size and skincare category replace lens-specific fields;
# forum_posts table is new (Pantip has no concept of a "product page").
# price_history added 2026-08-08 (audit fix #10) -- see module docstring.

SCHEMA = """
CREATE TABLE IF NOT EXISTS products (
    product_code    TEXT PRIMARY KEY,
    brand           TEXT    NOT NULL,
    site            TEXT    NOT NULL,
    store_name      TEXT,
    name_th_or_en   TEXT,
    pack_size       TEXT,
    category        TEXT,
    url             TEXT,
    sell_price      REAL,
    normal_price    REAL,
    review_count    INTEGER,
    avg_rating      REAL,
    item_code       TEXT,
    currency        TEXT    DEFAULT 'THB',
    discovered_at   TEXT,
    scraped_at      TEXT
);

CREATE TABLE IF NOT EXISTS product_reviews (
    id              INTEGER PRIMARY KEY AUTOINCREMENT,
    product_code    TEXT    NOT NULL,
    brand           TEXT    NOT NULL,
    site            TEXT    NOT NULL,
    reviewer_name   TEXT,
    rating          REAL,
    review_text     TEXT,
    review_date     TEXT,
    external_review_id TEXT UNIQUE,
    scraped_at      TEXT
);

CREATE TABLE IF NOT EXISTS forum_posts (
    id              INTEGER PRIMARY KEY AUTOINCREMENT,
    brand           TEXT    NOT NULL,
    site            TEXT    NOT NULL,
    post_title      TEXT,
    post_date       TEXT,
    post_url        TEXT,
    content_th      TEXT,
    content_en      TEXT,
    topic_tags      TEXT,
    content_hash    TEXT    UNIQUE,
    scraped_at      TEXT
);

CREATE TABLE IF NOT EXISTS price_history (
    id              INTEGER PRIMARY KEY AUTOINCREMENT,
    product_code    TEXT    NOT NULL,
    brand           TEXT    NOT NULL,
    site            TEXT    NOT NULL,
    pull_date       TEXT    NOT NULL,
    sell_price      REAL,
    normal_price    REAL,
    scraped_at      TEXT,
    UNIQUE(product_code, pull_date)
);

CREATE INDEX IF NOT EXISTS idx_products_brand ON products(brand);
CREATE INDEX IF NOT EXISTS idx_products_site  ON products(site);
CREATE INDEX IF NOT EXISTS idx_reviews_product ON product_reviews(product_code);
CREATE INDEX IF NOT EXISTS idx_posts_brand    ON forum_posts(brand);
CREATE INDEX IF NOT EXISTS idx_price_history_product ON price_history(product_code);
CREATE INDEX IF NOT EXISTS idx_price_history_date ON price_history(pull_date);
"""


def _migrate_price_history_collision(conn: sqlite3.Connection) -> None:
    """
    HOTFIX (2026-08-08): if a `price_history` table already exists from a
    prior partial run WITHOUT the `pull_date` column this schema requires,
    `CREATE TABLE IF NOT EXISTS` in SCHEMA silently leaves it as-is, and the
    very next statement (CREATE INDEX ... ON price_history(pull_date)) then
    fails with "no such column: pull_date" -- crashing before SCHEMA even
    finishes executing. This must run BEFORE executescript(SCHEMA), not
    inside _migrate_schema() (which only runs after SCHEMA succeeds).

    Data is never dropped: the old table is renamed aside with a timestamp
    so it stays on disk for inspection, and a correct price_history table
    gets created fresh by the SCHEMA script right after this runs.
    """
    tables = {row["name"] for row in conn.execute(
        "SELECT name FROM sqlite_master WHERE type='table'"
    ).fetchall()}
    if "price_history" not in tables:
        return
    cols = {row["name"] for row in conn.execute("PRAGMA table_info(price_history)").fetchall()}
    if "pull_date" in cols:
        return
    ts = datetime.now(timezone.utc).strftime("%Y%m%d_%H%M%S")
    old_name = f"price_history_legacy_{ts}"
    log.warning(f"[MIGRATE] Existing 'price_history' table is missing 'pull_date' -- "
                f"renaming it to '{old_name}' (data preserved, not dropped) so a correct "
                f"price_history table can be created.")
    conn.execute(f"ALTER TABLE price_history RENAME TO {old_name}")
    conn.commit()


def open_db(path: str) -> sqlite3.Connection:
    conn = sqlite3.connect(path, check_same_thread=False, timeout=60)
    conn.row_factory = sqlite3.Row
    conn.execute("PRAGMA journal_mode=WAL")
    conn.execute("PRAGMA synchronous=NORMAL")
    conn.execute("PRAGMA busy_timeout=60000")
    _migrate_price_history_collision(conn)
    conn.executescript(SCHEMA)
    conn.commit()
    _migrate_schema(conn)
    return conn


def _migrate_schema(conn: sqlite3.Connection) -> None:
    """
    Adds any columns that don't exist yet on an already-created products
    table. CREATE TABLE IF NOT EXISTS (in SCHEMA above) only handles brand
    new databases -- it silently does nothing to a table that already
    exists with an older structure. This function is what actually keeps
    an existing DB file in sync when the schema grows (e.g. adding
    avg_rating/item_code for the Boots review feature on 2026-07-18).
    Safe to run every time open_db() is called -- it's a no-op if the
    columns already exist.
    """
    existing_cols = {row["name"] for row in conn.execute("PRAGMA table_info(products)").fetchall()}
    needed_cols = {
        "avg_rating": "REAL",
        "item_code": "TEXT",
    }
    for col, col_type in needed_cols.items():
        if col not in existing_cols:
            log.info(f"[MIGRATE] Adding missing column products.{col} ({col_type}) to existing DB")
            conn.execute(f"ALTER TABLE products ADD COLUMN {col} {col_type}")

    existing_review_cols = {row["name"] for row in conn.execute("PRAGMA table_info(product_reviews)").fetchall()}
    if "review_text_en" not in existing_review_cols:
        log.info("[MIGRATE] Adding missing column product_reviews.review_text_en (TEXT) to existing DB")
        conn.execute("ALTER TABLE product_reviews ADD COLUMN review_text_en TEXT")
    conn.commit()


def _db_writer(path: str, write_q: queue.Queue, done: threading.Event) -> None:
    """Single writer thread -- same pattern as the lens pipeline. Zero
    write contention: workers never touch SQLite directly, they push
    rows onto write_q and this thread is the only one that commits."""
    conn = sqlite3.connect(path, timeout=60)
    conn.execute("PRAGMA journal_mode=WAL")
    conn.execute("PRAGMA synchronous=NORMAL")

    while True:
        try:
            item = write_q.get(timeout=2.0)
        except queue.Empty:
            if done.is_set() and write_q.empty():
                break
            continue
        if item is None:
            write_q.task_done()
            break

        kind, rows = item
        if kind == "posts" and rows:
            for r in rows:
                try:
                    conn.execute(
                        """INSERT OR IGNORE INTO forum_posts
                           (brand, site, post_title, post_date, post_url,
                            content_th, content_en, topic_tags, content_hash, scraped_at)
                           VALUES (?,?,?,?,?,?,?,?,?,?)""",
                        (
                            r["brand"], r["site"], r["post_title"], r["post_date"],
                            r["post_url"], r["content_th"], r["content_en"],
                            r.get("topic_tags"), r["content_hash"], r["scraped_at"],
                        ),
                    )
                except Exception as e:
                    log.warning(f"[DB] Post insert error: {e}")
            conn.commit()

        elif kind == "reviews" and rows:
            for r in rows:
                try:
                    conn.execute(
                        """INSERT OR IGNORE INTO product_reviews
                           (product_code, brand, site, reviewer_name, rating,
                            review_text, review_date, external_review_id, scraped_at)
                           VALUES (?,?,?,?,?,?,?,?,?)""",
                        (
                            r["product_code"], r["brand"], r["site"], r["reviewer_name"],
                            r["rating"], r["review_text"], r["review_date"],
                            r["external_review_id"], r["scraped_at"],
                        ),
                    )
                except Exception as e:
                    log.warning(f"[DB] Review insert error: {e}")
            conn.commit()

        elif kind == "review_count_update" and rows:
            for r in rows:
                try:
                    conn.execute(
                        "UPDATE products SET review_count=?, avg_rating=? WHERE product_code=?",
                        (r["review_count"], r["avg_rating"], r["product_code"]),
                    )
                except Exception as e:
                    log.warning(f"[DB] Review count update error: {e}")
            conn.commit()

        write_q.task_done()

    conn.close()


# ── COST TRACKER (same model as lens pipeline: gpt-4o-mini) ──────────────

class CostTracker:
    INPUT_COST = 0.150 / 1_000_000
    OUTPUT_COST = 0.600 / 1_000_000

    def __init__(self):
        self._lock = threading.Lock()
        self.input_tokens = 0
        self.output_tokens = 0

    def add(self, usage):
        with self._lock:
            self.input_tokens += getattr(usage, "prompt_tokens", 0)
            self.output_tokens += getattr(usage, "completion_tokens", 0)

    @property
    def cost(self) -> float:
        return self.input_tokens * self.INPUT_COST + self.output_tokens * self.OUTPUT_COST

    def report(self):
        log.info(f"[COST] {self.input_tokens:,} in + {self.output_tokens:,} out = ${self.cost:.4f}")


cost_tracker = CostTracker()


# ── CATEGORY CLASSIFICATION (skincare, not lens type) ─────────────────────

_CATEGORY_RULES: list[tuple[str, list[str]]] = [
    ("Cleanser",        ["cleanser", "wash", "foam", "ล้างหน้า", "โฟม"]),
    ("Lotion/Moisturizer", ["lotion", "cream", "moistur", "moistus", "บำรุงผิว"]),
    ("Serum",            ["serum", "เซรั่ม"]),
    ("Sunscreen",        ["sunscreen", "spf", "sun ", "กันแดด"]),
    ("Toner",            ["toner", "โทนเนอร์"]),
    ("Micellar/Makeup Removal", ["micellar", "makeup remover"]),
    ("Spot Treatment",   ["spot", "blemish", "acne gel", "acne care"]),
    ("Body Care",        ["body oil", "body lotion", "shower", "bath"]),
]


def classify_skincare_type(name: Optional[str]) -> Optional[str]:
    if not name:
        return None
    low = name.lower()
    for category, keywords in _CATEGORY_RULES:
        if any(kw in low for kw in keywords):
            return category
    return None


def _parse_pack_size(name: Optional[str]) -> Optional[str]:
    """Extract pack size like '100 ML', '236ml', '50 G.' from a product name."""
    if not name:
        return None
    m = re.search(r"(\d+(?:\.\d+)?)\s*(ml|ML|g\.|G\.|g|Ml)", name)
    return f"{m.group(1)}{m.group(2).lower().rstrip('.')}" if m else None


def _parse_price(text: str) -> Optional[float]:
    if not text:
        return None
    cleaned = re.sub(r"[^\d.]", "", text)
    return float(cleaned) if cleaned else None


# ── BOOTS.CO.TH DISCOVERY + PRICING ───────────────────────────────────────
# CONFIRMED WORKING (2026-07-14): server-rendered HTML, no Playwright,
# no bot-blocking observed on a plain `requests` call.

_BOOTS_HEADERS = {
    "User-Agent": (
        "Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 "
        "(KHTML, like Gecko) Chrome/124.0.0.0 Safari/537.36"
    ),
    "Accept-Language": "th-TH,th;q=0.9,en;q=0.8",
    "Accept": "text/html,application/xhtml+xml,application/xml;q=0.9,*/*;q=0.8",
}


# ── SKU QUERY SOURCE (AUDIT FIX #1, 2026-08-08) ──────────────────────────
# Previously, Boots search keywords came from config_th.yaml's per-brand
# `boots_keywords` list -- a parallel, hand-maintained keyword set that
# didn't match the project's canonical coverage frame. Now loads directly
# from sku_query_master.csv (the same file Shopee/BigC scrapers use),
# columns: sku_key, priority, format, brand, product_name, query,
# is_flagged, flag_note. `query` is the literal Boots search keyword.

import csv as _sku_csv


def load_sku_queries(csv_path: str, brand_filter: Optional[List[str]] = None) -> List[dict]:
    """Reads sku_query_master.csv and returns one dict per row, optionally
    filtered to brand_filter (case-insensitive match on the `brand` column)."""
    rows: List[dict] = []
    with open(csv_path, encoding="utf-8-sig") as f:
        reader = _sku_csv.DictReader(f)
        for r in reader:
            if brand_filter and r["brand"].lower() not in [b.lower() for b in brand_filter]:
                continue
            rows.append(r)
    return rows


def print_sku_query_summary(rows: List[dict]) -> None:
    """Pre-run summary printed before any call -- checklist item #1: total
    query count, unique SKU-family count, breakdown by brand, and any
    flagged/uncertain rows called out explicitly."""
    from collections import Counter

    total = len(rows)
    families = {r["sku_key"] for r in rows}
    by_brand = Counter(r["brand"] for r in rows)
    flagged = [r for r in rows if str(r.get("is_flagged", "")).strip().lower() in ("true", "1", "yes")]

    log.info("=" * 60)
    log.info("[SKU SOURCE] sku_query_master.csv pre-run summary")
    log.info(f"  Total queries:        {total}")
    log.info(f"  Unique SKU families:  {len(families)}")
    log.info("  By brand:")
    for brand, n in sorted(by_brand.items()):
        log.info(f"    {brand}: {n}")
    if flagged:
        log.warning(f"  {len(flagged)} FLAGGED/uncertain row(s) -- review before trusting downstream:")
        for r in flagged:
            log.warning(f"    - {r['sku_key']} | {r['brand']} | {r['query']} -- {r.get('flag_note', '')}")
    else:
        log.info("  No flagged rows.")
    log.info("=" * 60)


def discover_boots_th(
    sku_rows: List[dict],
    config: dict,
    conn: Optional[sqlite3.Connection] = None,
    lock: Optional[threading.Lock] = None,
) -> List[dict]:
    """
    Keyword search across every brand present in sku_rows -- one HTTP
    search per distinct (brand, query) pair from sku_query_master.csv.

    IMPORTANT (tested 2026-07-14): keep keywords in ENGLISH here. Thai-language
    keywords were tested against this endpoint and made things WORSE, not
    better -- Boots.co.th's catalog is entered in English/Latin script, so a
    Thai query doesn't match real listings. "Acne-Aid" (EN) returned 21/21
    correct products; the Thai transliteration returned 218 results, 90% of
    which were unrelated brands. Same pattern held for CeraVe (79% noise).
    Do not "fix" this by adding Thai keywords without re-testing empirically
    first.

    If conn+lock are passed, saves each brand's results immediately after
    that brand finishes, so a run left unattended keeps partial progress
    even if a later brand fails or the connection drops.
    """
    now = datetime.now(timezone.utc).isoformat()
    all_products: List[dict] = []
    session = requests.Session()
    session.headers.update(_BOOTS_HEADERS)

    # boots_name_filter is a Boots-specific noise-suppression regex, kept in
    # config_th.yaml (not part of the canonical SKU file -- it's an artifact
    # of Boots' relevance-ranked search, not a real SKU attribute).
    name_filters = {b["name"]: b.get("boots_name_filter") for b in config.get("brands", [])}

    from collections import defaultdict
    rows_by_brand: Dict[str, List[dict]] = defaultdict(list)
    for r in sku_rows:
        rows_by_brand[r["brand"]].append(r)

    for brand_name, rows in rows_by_brand.items():
        brand_products: List[dict] = []
        name_filter = name_filters.get(brand_name)

        # Same query text can repeat across sku_key rows for a brand (e.g. a
        # competitor's single SKU mapped to several Acne-Aid pack sizes) --
        # dedupe queries per brand so we don't re-search Boots for the exact
        # same keyword twice in one run.
        seen_queries: set = set()
        queries = []
        for r in rows:
            q = r["query"]
            if q not in seen_queries:
                seen_queries.add(q)
                queries.append(q)

        for keyword in queries:
            log.info(f"[DISCOVER] Boots.co.th | {brand_name} | keyword: {keyword}")
            for page in range(1, 11):
                params = {"keyword": keyword}
                if page > 1:
                    params["page"] = page
                try:
                    resp = session.get(
                        config["sites"]["boots_th"]["search_url"], params=params, timeout=20
                    )
                except Exception as e:
                    log.warning(f"[DISCOVER] Boots.co.th | {brand_name} page {page}: {e}")
                    break
                if resp.status_code != 200:
                    log.warning(f"[DISCOVER] Boots.co.th | {brand_name} page {page}: HTTP {resp.status_code}")
                    break

                try:
                    soup = BeautifulSoup(resp.text, "html.parser")
                    cells = soup.select("div.product-cell")
                except Exception as e:
                    log.warning(f"[DISCOVER] Boots.co.th | {brand_name} page {page}: parse error {e}")
                    break
                if not cells:
                    break

                # item_codes are embedded in the page's Nuxt payload (not in the
                # visible HTML), but confirmed (2026-07-14, live test) to appear
                # in the same order as the visible product-cell divs on the page.
                item_codes = re.findall(r'item_code:"(\d+)"', resp.text)

                for idx, cell in enumerate(cells):
                    try:
                        name_el = cell.select_one(".product-description")
                        sell_el = cell.select_one(".sell-price")
                        normal_el = cell.select_one(".normal-price")
                        name = name_el.get_text(strip=True) if name_el else None
                        if not name:
                            continue

                        # Boots' search is relevance-ranked, not exact-match -- fine for
                        # distinctive brand names, but generic-word brands (e.g. "Clean and
                        # Clear") pull in unrelated products whose descriptions just contain
                        # those words (confirmed 2026-07-19: 118/132 raw hits for "Clean and
                        # Clear" were noise like "Rexona ... Clean & Fresh"). name_filter is
                        # an optional per-brand regex in config_th.yaml to reject those.
                        if name_filter and not re.search(name_filter, name, re.IGNORECASE):
                            continue

                        code_raw = f"boots_th|{name}"
                        product_code = "boots_" + hashlib.md5(code_raw.encode()).hexdigest()[:12]
                        item_code = item_codes[idx] if idx < len(item_codes) else None

                        brand_products.append({
                            "product_code": product_code,
                            "brand": brand_name,
                            "site": "boots_th",
                            "store_name": "Boots.co.th",
                            "name_th_or_en": name,
                            "pack_size": _parse_pack_size(name),
                            "category": classify_skincare_type(name),
                            "url": resp.url,
                            "sell_price": _parse_price(sell_el.get_text()) if sell_el else None,
                            "normal_price": _parse_price(normal_el.get_text()) if normal_el else None,
                            "review_count": None,   # filled in later by extract_boots_reviews()
                            "avg_rating": None,
                            "item_code": item_code,
                            "currency": "THB",
                            "discovered_at": now,
                            "scraped_at": now,
                        })
                    except Exception as e:
                        log.warning(f"[DISCOVER] Boots.co.th | {brand_name}: skipped one malformed product card ({e})")
                        continue

                log.info(f"[DISCOVER] Boots.co.th | {brand_name} | page {page}: {len(cells)} products")
                time.sleep(1.5)

        # Save this brand's results immediately -- don't wait for every
        # brand to finish. Protects progress on an unattended run.
        if conn is not None and lock is not None:
            n_saved = save_products(conn, brand_products, lock)
            log.info(f"[DISCOVER] Boots.co.th | {brand_name}: {n_saved} saved to DB (incremental)")

        all_products.extend(brand_products)

    return all_products


# ── WATSONS.CO.TH DISCOVERY (Playwright required -- confirmed dead end) ──
# Plain HTTP confirmed blocked (403) at connection level, same as Watsons
# HK (Akamai-style). Headless Playwright, even with a stealth script
# applied, still gets "Access Denied" -- same bot-fingerprint wall.
# Needs Claude in Chrome or an Apify actor instead. Kept as an interface
# stub so it can be swapped later without changing how run() calls it.

def discover_watsons_th(config: dict, brand_filter: Optional[List[str]] = None) -> List[dict]:
    """CONFIRMED NOT WORKING (tested 2026-07-14): see module notes above.
    Currently always returns an empty list."""
    log.warning("[DISCOVER] Watsons.co.th: SKIPPED -- confirmed blocked at the browser-automation "
                "level (Access Denied), same as plain HTTP. Needs Claude in Chrome or an Apify actor, "
                "not a Playwright script.")
    return []


# ── PANTIP DISCOVERY + EXTRACTION ─────────────────────────────────────────
# CONFIRMED WORKING: static HTML, plain requests, robots.txt does not
# block general scraping (only specific bots + /ads.php).

class ForumPost(BaseModel):
    post_title: str = Field(description="Thread title")
    post_date: str = Field(description="Date if visible, else empty string")
    content_summary: str = Field(description="A 1-3 sentence faithful paraphrase of what the post/thread discusses about the brand -- NOT a verbatim quote")
    sentiment: str = Field(description="One of: positive, negative, mixed, neutral")
    topics: List[str] = Field(description="Short topic tags, e.g. ['pricing', 'breakouts', 'packaging', 'availability']")


class ForumPostPage(BaseModel):
    posts: List[ForumPost] = Field(description="All distinct discussion threads found relevant to the brand")


def discover_pantip(config: dict, client: OpenAI, brand_filter: Optional[List[str]] = None) -> List[dict]:
    """
    Search Pantip for each brand's keywords, then run the search-results
    page through the LLM to extract structured, brand-relevant discussion
    points. Feeds the brand-feedback / reputation pillar, not pricing.
    """
    now = datetime.now(timezone.utc).isoformat()
    posts: List[dict] = []
    headers = {"User-Agent": _BOOTS_HEADERS["User-Agent"]}

    for brand in config["brands"]:
        brand_name = brand["name"]
        if brand_filter and brand_name.lower() not in [b.lower() for b in brand_filter]:
            continue

        for keyword in brand.get("pantip_keywords", [brand_name]):
            search_url = config["sites"]["pantip"]["search_url_template"].format(
                keyword=urllib.parse.quote(keyword)
            )
            log.info(f"[DISCOVER] Pantip | {brand_name} | keyword: {keyword}")

            resp = None
            backoff = 5.0
            for attempt in range(4):
                try:
                    resp = requests.get(search_url, headers=headers, timeout=20)
                except Exception as e:
                    log.warning(f"[DISCOVER] Pantip | {brand_name}: {e}")
                    resp = None
                    break
                if resp.status_code == 429:
                    log.warning(f"[DISCOVER] Pantip | {brand_name}: HTTP 429 (rate limited), "
                                f"backing off {backoff:.0f}s (attempt {attempt + 1}/4)")
                    time.sleep(backoff)
                    backoff *= 2
                    continue
                break

            if resp is None or resp.status_code != 200:
                status = resp.status_code if resp is not None else "request failed"
                log.warning(f"[DISCOVER] Pantip | {brand_name}: giving up on keyword '{keyword}' ({status})")
                time.sleep(3.0)
                continue

            soup = BeautifulSoup(resp.text, "html.parser")
            for tag in soup(["script", "style", "nav", "footer"]):
                tag.decompose()
            text_blob = soup.get_text(" ", strip=True)[:15_000]

            extracted = _llm_extract_forum_posts(text_blob, brand_name, client)
            for p in extracted:
                raw_key = f"{brand_name}|{keyword}|{p.post_title}|{p.content_summary[:50]}"
                c_hash = hashlib.md5(raw_key.encode()).hexdigest()
                posts.append({
                    "brand": brand_name,
                    "site": "pantip",
                    "post_title": p.post_title,
                    "post_date": p.post_date,
                    "post_url": search_url,
                    "content_th": None,   # summary is already extracted/translated by the LLM
                    "content_en": p.content_summary,
                    "topic_tags": json.dumps({"sentiment": p.sentiment, "topics": p.topics}, ensure_ascii=False),
                    "content_hash": c_hash,
                    "scraped_at": now,
                })
            log.info(f"[DISCOVER] Pantip | {brand_name} | kw={keyword}: {len(extracted)} threads extracted")
            time.sleep(3.0)

    return posts


def _llm_extract_forum_posts(
    text_blob: str, brand_name: str, client: OpenAI, source_desc: str = "search-results page"
) -> List[ForumPost]:
    if not text_blob.strip():
        return []
    prompt = f"""The text below is a Pantip.com (Thai forum) {source_desc} for the brand "{brand_name}".
Identify distinct discussion threads that are actually about this brand -- ignore navigation, ads, and unrelated threads.
For each relevant thread, extract: post_title, post_date (if visible, else empty string),
a faithful 1-3 sentence paraphrase of the discussion (do not quote verbatim), overall sentiment, and topic tags
(e.g. pricing, breakouts, packaging, availability, comparison to other brands).
If nothing relevant is found, return an empty list.

TEXT:
{text_blob}"""
    try:
        resp = client.beta.chat.completions.parse(
            model="gpt-4o-mini",
            messages=[{"role": "user", "content": prompt}],
            response_format=ForumPostPage,
            max_tokens=2000,
        )
        cost_tracker.add(resp.usage)
        return resp.choices[0].message.parsed.posts or []
    except Exception as e:
        log.warning(f"[LLM] Pantip extraction failed: {e}")
        return []


# ── PANTIP DEEP DISCOVERY (room-crawl candidates + full-thread extraction) ──
# discover_pantip() above is capped hard at 10 results per keyword -- confirmed
# 2026-07-24 by inspecting the search page's embedded __NEXT_DATA__: it
# reports e.g. "total": "พบ 2,620 กระทู้" (2,620 found) but "last_page": true
# on page 1, and ?page=2/?page=3 return the exact same 10 rows. That's a
# platform limit on the public search endpoint, not something pacing or
# retries can get past.
#
# To get real volume, this uses the existing bulk room-crawl file
# (pantip_room_threads v2.csv.xlsx -- ~103k threads from the beauty room,
# collected in an earlier project phase) as a CANDIDATE LIST: filter its
# title/tags for brand keyword matches, then fetch each matching thread's
# real page for full content instead of relying on capped search snippets.
# That file has no post/comment body text (comments_json is empty for every
# row) -- only title/url/tags, which is why the body + comments are fetched
# live here.
#
# Two endpoints per thread, both confirmed working via plain requests
# (2026-07-24):
#   - GET https://pantip.com/topic/{id}
#       Server-rendered HTML main post. Title: h1.display-post-title.
#       Body: .main-post-inner .display-post-story. topic_type: the value
#       of hidden input #topic-type -- this varies per thread (seen 3 and 4
#       on two different threads), needed for the comments call below, so
#       it's read per-thread rather than hardcoded.
#   - GET https://pantip.com/forum/topic/render_comments?tid={id}&type={t}
#       Clean JSON: {comments: [{message: "...", ...}, ...]}. Two gotchas
#       found by testing (2026-07-24):
#         1. REQUIRES header X-Requested-With: XMLHttpRequest -- without it,
#            the server silently returns a full HTML page instead of JSON
#            (no error, just the wrong content type).
#         2. The JSON body has a UTF-8 BOM that trips up requests' own
#            .json() (raises "Expecting value" at char 0) -- decode with
#            r.content.decode("utf-8-sig") first.
#       Comment "message" fields can contain raw HTML (<br />, <img>, etc)
#       -- stripped via BeautifulSoup.get_text() before handing to the LLM.
#
# Same 429-backoff pattern as discover_pantip() applies to both calls.

_PANTIP_AJAX_HEADERS = {**_BOOTS_HEADERS, "X-Requested-With": "XMLHttpRequest"}


def _load_room_crawl_candidates(
    xlsx_path: str, config: dict, brand_filter: Optional[List[str]] = None
) -> List[dict]:
    """Reads the bulk room-crawl xlsx and returns one row per (brand, thread)
    match against that brand's pantip_keywords, matched case-insensitively
    against title+tags only (the only text columns available in that file).
    A thread that matches more than one brand's keywords produces one
    candidate row per matching brand."""
    brands = config["brands"]
    if brand_filter:
        wanted = {b.lower() for b in brand_filter}
        brands = [b for b in brands if b["name"].lower() in wanted]
    brand_patterns = [
        (b["name"], [kw.lower() for kw in b.get("pantip_keywords", [b["name"]])])
        for b in brands
    ]

    wb = openpyxl.load_workbook(xlsx_path, read_only=True)
    ws = wb.active
    header: Optional[Dict[str, int]] = None
    candidates: List[dict] = []

    for row in ws.iter_rows(values_only=True):
        if header is None:
            header = {name: i for i, name in enumerate(row)}
            continue
        title = row[header["title"]]
        tags = row[header["tags"]]
        title = "" if title is None else str(title)
        tags = "" if tags is None else str(tags)
        haystack = f"{title} {tags}".lower()
        for brand_name, keywords in brand_patterns:
            if any(kw in haystack for kw in keywords):
                candidates.append({
                    "brand": brand_name,
                    "thread_id": str(row[header["thread_id"]]),
                    "url": row[header["url"]],
                    "title": title,
                })
    wb.close()
    return candidates


def _fetch_pantip_thread_text(thread_id: str, url: str) -> Optional[str]:
    """Fetches one thread's main post + comments and returns a combined text
    blob ready for LLM extraction, or None if the thread couldn't be read
    after retries (deleted thread, persistent block, etc)."""
    resp = None
    backoff = 5.0
    for _ in range(4):
        try:
            resp = requests.get(url, headers=_BOOTS_HEADERS, timeout=20)
        except Exception as e:
            log.warning(f"[DEEP] Pantip | thread {thread_id}: {e}")
            return None
        if resp.status_code == 429:
            time.sleep(backoff)
            backoff *= 2
            continue
        break
    if resp is None or resp.status_code != 200:
        return None

    soup = BeautifulSoup(resp.text, "html.parser")
    title_el = soup.select_one("h1.display-post-title")
    body_el = soup.select_one(".main-post-inner .display-post-story")
    tag_els = soup.select(".display-post-tag-wrapper a.tag-item")
    type_el = soup.select_one("#topic-type")
    title = title_el.get_text(strip=True) if title_el else ""
    body = body_el.get_text(" ", strip=True) if body_el else ""
    tags = ", ".join(t.get_text(strip=True) for t in tag_els)
    topic_type = type_el["value"] if type_el and type_el.has_attr("value") else "2"

    comments_text = ""
    resp2 = None
    backoff = 5.0
    for _ in range(4):
        try:
            resp2 = requests.get(
                "https://pantip.com/forum/topic/render_comments",
                params={"tid": thread_id, "param": "", "type": topic_type, "time": f"{time.time():.3f}"},
                headers=_PANTIP_AJAX_HEADERS, timeout=20,
            )
        except Exception as e:
            log.warning(f"[DEEP] Pantip | thread {thread_id} comments: {e}")
            resp2 = None
            break
        if resp2.status_code == 429:
            time.sleep(backoff)
            backoff *= 2
            continue
        break
    if resp2 is not None and resp2.status_code == 200:
        try:
            data = json.loads(resp2.content.decode("utf-8-sig"))
            messages = [c.get("message", "") for c in data.get("comments", []) if c.get("message")]
            comments_text = " ".join(
                BeautifulSoup(m, "html.parser").get_text(" ", strip=True) for m in messages[:40]
            )
        except Exception as e:
            log.warning(f"[DEEP] Pantip | thread {thread_id}: comment parse error {e}")

    text_blob = f"{title}\nTags: {tags}\n{body}\nComments: {comments_text}"
    return text_blob[:15_000]


def discover_pantip_deep(
    config: dict,
    client: OpenAI,
    xlsx_path: str,
    brand_filter: Optional[List[str]] = None,
    conn: Optional[sqlite3.Connection] = None,
    write_q: Optional[queue.Queue] = None,
    max_workers: int = 4,
) -> int:
    """Room-crawl-candidate version of Pantip discovery -- see module notes
    above for why this exists (search endpoint hard-caps at 10/keyword).
    Saves posts incrementally onto write_q every _SAVE_EVERY threads so an
    unattended multi-hour run keeps partial progress. Returns post count."""
    _SAVE_EVERY = 20
    now = datetime.now(timezone.utc).isoformat()

    candidates = _load_room_crawl_candidates(xlsx_path, config, brand_filter)
    log.info(f"[DEEP] Pantip | {len(candidates)} candidate threads from room-crawl file")

    # Skip threads already saved by this method in a previous run -- dedup
    # key is (brand, thread_id) via content_hash, not the LLM's paraphrase
    # text, so it's stable across reruns even if the LLM's wording changes.
    existing_hashes: set = set()
    if conn is not None:
        existing_hashes = {
            row["content_hash"]
            for row in conn.execute(
                "SELECT content_hash FROM forum_posts WHERE site='pantip_deep'"
            ).fetchall()
        }

    def _hash_for(brand: str, thread_id: str, idx: int) -> str:
        return hashlib.md5(f"{brand}|pantip_deep|{thread_id}|{idx}".encode()).hexdigest()

    pending = [
        c for c in candidates
        if _hash_for(c["brand"], c["thread_id"], 0) not in existing_hashes
    ]
    log.info(f"[DEEP] Pantip | {len(pending)} threads not yet processed (skipping {len(candidates) - len(pending)} already saved)")

    total_posts = 0
    processed = 0
    batch: List[dict] = []

    def _process_one(cand: dict) -> List[dict]:
        text_blob = _fetch_pantip_thread_text(cand["thread_id"], cand["url"])
        time.sleep(1.0)  # polite pacing per thread, on top of the 429 backoff inside the fetch
        if not text_blob:
            return []
        extracted = _llm_extract_forum_posts(
            text_blob, cand["brand"], client, source_desc="discussion thread"
        )
        rows = []
        for i, p in enumerate(extracted):
            rows.append({
                "brand": cand["brand"],
                "site": "pantip_deep",
                "post_title": p.post_title or cand["title"],
                "post_date": p.post_date,
                "post_url": cand["url"],
                "content_th": None,
                "content_en": p.content_summary,
                "topic_tags": json.dumps({"sentiment": p.sentiment, "topics": p.topics}, ensure_ascii=False),
                "content_hash": _hash_for(cand["brand"], cand["thread_id"], i),
                "scraped_at": now,
            })
        return rows

    with ThreadPoolExecutor(max_workers=max_workers) as executor:
        futures = {executor.submit(_process_one, c): c for c in pending}
        for future in as_completed(futures):
            rows = future.result()
            batch.extend(rows)
            total_posts += len(rows)
            processed += 1
            if len(batch) >= _SAVE_EVERY and write_q is not None:
                write_q.put(("posts", batch))
                batch = []
            if processed % 50 == 0:
                log.info(f"[DEEP] Pantip | {processed}/{len(pending)} threads processed, {total_posts} posts so far")

    if batch and write_q is not None:
        write_q.put(("posts", batch))

    log.info(f"[DEEP] Pantip | done: {processed} threads processed, {total_posts} posts extracted")
    return total_posts


# ── BOOTS.CO.TH REVIEW EXTRACTION ─────────────────────────────────────────
# CONFIRMED WORKING (2026-07-14): found via live Playwright network
# interception on one product page, then confirmed the underlying API
# works with plain `requests` -- no browser needed at all.
#
#   GET https://store.boots.co.th/api/v1/review?item_code={code}&page=1&size=1000&locale=en
#
# Returns clean JSON: {page_information: {...}, entities: [{rating, text,
# name, created_at, ...}, ...]}. No auth needed. Keyed by item_code, which
# is captured during discover_boots_th() from the search page's embedded
# Nuxt payload (confirmed to align in order with visible product cells).
#
# IMPORTANT: the review COUNT shown in a product page's HTML ("Review (5)")
# is server-rendered and accurate, but the review LIST in that same HTML
# is always empty ("No review" placeholder) even when the count is > 0 --
# actual review text only loads via this API, client-side, after page
# hydration. Don't try to scrape review text from the product page HTML
# itself; it's never there.

def extract_boots_reviews(
    db_path: str,
    write_q: queue.Queue,
    brand_filter: Optional[List[str]] = None,
    max_workers: int = 4,
) -> int:
    """Reads boots_th products with a known item_code from the DB, fetches
    reviews for each via the API above, and pushes results onto write_q.
    Returns the count of products processed (not review count)."""
    conn = sqlite3.connect(db_path, timeout=60)
    conn.row_factory = sqlite3.Row
    query = "SELECT product_code, brand, item_code FROM products WHERE site='boots_th' AND item_code IS NOT NULL"
    params = []
    if brand_filter:
        placeholders = ",".join("?" * len(brand_filter))
        query += f" AND brand IN ({placeholders})"
        params = brand_filter
    rows = conn.execute(query, params).fetchall()
    conn.close()

    log.info(f"[REVIEWS] Boots.co.th: {len(rows)} products with item_code to check")

    session = requests.Session()
    session.headers.update(_BOOTS_HEADERS)
    now = datetime.now(timezone.utc).isoformat()
    processed = 0

    def _fetch_one(row):
        try:
            resp = session.get(
                "https://store.boots.co.th/api/v1/review",
                params={"item_code": row["item_code"], "page": 1, "size": 1000, "locale": "en"},
                timeout=20,
            )
            if resp.status_code != 200:
                return row["product_code"], row["brand"], [], None
            data = resp.json()
            entities = data.get("entities", [])
            ratings = [e["rating"] for e in entities if e.get("rating") is not None]
            avg_rating = round(sum(ratings) / len(ratings), 2) if ratings else None
            reviews = [{
                "product_code": row["product_code"],
                "brand": row["brand"],
                "site": "boots_th",
                "reviewer_name": e.get("name") or None,
                "rating": e.get("rating"),
                "review_text": e.get("text") or None,
                "review_date": e.get("created_at"),
                "external_review_id": e.get("id"),
                "scraped_at": now,
            } for e in entities]
            return row["product_code"], row["brand"], reviews, avg_rating
        except Exception as e:
            log.warning(f"[REVIEWS] Boots.co.th | item_code={row['item_code']}: {e}")
            return row["product_code"], row["brand"], [], None

    with ThreadPoolExecutor(max_workers=max_workers) as executor:
        futures = {executor.submit(_fetch_one, row): row for row in rows}
        for future in as_completed(futures):
            product_code, brand, reviews, avg_rating = future.result()
            if reviews:
                write_q.put(("reviews", reviews))
            if avg_rating is not None or reviews:
                write_q.put(("review_count_update", [{
                    "product_code": product_code,
                    "review_count": len(reviews),
                    "avg_rating": avg_rating,
                }]))
            processed += 1
            if processed % 50 == 0:
                log.info(f"[REVIEWS] Boots.co.th: {processed}/{len(rows)} products checked")
            time.sleep(0.3)  # polite pacing even though this is a clean API, not a scrape

    log.info(f"[REVIEWS] Boots.co.th: done, {processed} products checked")
    return processed


# ── SAVE HELPERS ─────────────────────────────────────────────────────────

def save_products(conn: sqlite3.Connection, products: List[dict], lock: threading.Lock) -> int:
    """
    Upserts current-state rows into `products` (keyed by product_code --
    this table always reflects the LATEST scrape only, same as before).

    AUDIT FIX #10 (2026-08-08): additionally inserts one row per product
    into `price_history`, keyed by (product_code, pull_date). Same-day
    reruns update that day's row in place (correct -- one snapshot per SKU
    per day); different-day reruns insert a NEW row, so price history
    across pulls survives instead of being silently overwritten the way
    the `products` table alone was doing. pull_date is derived from each
    row's scraped_at timestamp (first 10 chars of the ISO string).
    """
    inserted = 0
    with lock:
        for p in products:
            try:
                cur = conn.execute(
                    """INSERT INTO products
                       (product_code, brand, site, store_name, name_th_or_en, pack_size,
                        category, url, sell_price, normal_price, review_count, avg_rating,
                        item_code, currency, discovered_at, scraped_at)
                       VALUES (?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?)
                       ON CONFLICT(product_code) DO UPDATE SET
                         sell_price   = excluded.sell_price,
                         normal_price = excluded.normal_price,
                         item_code    = COALESCE(excluded.item_code, products.item_code),
                         scraped_at   = excluded.scraped_at""",
                    (
                        p["product_code"], p["brand"], p["site"], p["store_name"],
                        p["name_th_or_en"], p["pack_size"], p["category"], p["url"],
                        p["sell_price"], p["normal_price"], p.get("review_count"),
                        p.get("avg_rating"), p.get("item_code"),
                        p["currency"], p["discovered_at"], p["scraped_at"],
                    ),
                )
                if cur.rowcount == 1:
                    inserted += 1

                pull_date = (p.get("scraped_at") or "")[:10]
                if pull_date:
                    conn.execute(
                        """INSERT INTO price_history
                           (product_code, brand, site, pull_date, sell_price, normal_price, scraped_at)
                           VALUES (?,?,?,?,?,?,?)
                           ON CONFLICT(product_code, pull_date) DO UPDATE SET
                             sell_price   = excluded.sell_price,
                             normal_price = excluded.normal_price,
                             scraped_at   = excluded.scraped_at""",
                        (
                            p["product_code"], p["brand"], p["site"], pull_date,
                            p["sell_price"], p["normal_price"], p["scraped_at"],
                        ),
                    )
            except Exception as e:
                log.warning(f"[DB] Product insert error: {e}")
        conn.commit()
    return inserted


# ── CSV EXPORT (client deliverable — DB stays internal, CSVs are the output) ──
# Same principle as the lens pipeline's csv_export.py: SQLite is the safe,
# concurrent-write internal engine; CSV is what gets handed to the client.
# Regenerated fresh from the DB on every run -- never hand-edited.

import csv as _csv


def export_csvs(db_path: str, output_dir: str, config_path: str = "config_th.yaml", timestamp: Optional[str] = None) -> dict:
    """Export products, forum_posts, and price_history tables to client-ready
    CSV files. Each filename gets a datestamp suffix (e.g. acneaid_th_pricing_20260808_1430.csv)
    so every run produces new files instead of overwriting the last one -- old
    exports stay on disk as a natural audit trail. Pass `timestamp` explicitly
    to keep all 4 files from one run sharing the same stamp; if omitted,
    generates one now. Returns a dict of {table_name: row_count} for logging/verification."""
    conn = open_db(db_path)
    counts = {}
    ts = timestamp or datetime.now().strftime("%Y%m%d_%H%M")

    # Per-brand boots_name_filter (config_th.yaml) excludes keyword-search
    # noise (e.g. "Clean and Clear" matching unrelated products that just
    # contain the words "clean"/"clear") at EXPORT time only -- the raw rows
    # stay in the DB untouched, this just keeps them out of the client CSV.
    name_filters: Dict[str, str] = {}
    try:
        with open(config_path, encoding="utf-8") as f:
            _cfg = yaml.safe_load(f)
        for b in _cfg.get("brands", []):
            if b.get("boots_name_filter"):
                name_filters[b["name"]] = b["boots_name_filter"]
    except FileNotFoundError:
        pass

    exports = {
        "acneaid_th_pricing.csv": (
            "SELECT brand, site, store_name, name_th_or_en, pack_size, category, "
            "sell_price, normal_price, review_count, avg_rating, currency, url, scraped_at "
            "FROM products ORDER BY brand, site, sell_price",
        ),
        "acneaid_th_price_history.csv": (
            "SELECT product_code, brand, site, pull_date, sell_price, normal_price, scraped_at "
            "FROM price_history ORDER BY brand, product_code, pull_date",
        ),
        "acneaid_th_product_reviews.csv": (
            "SELECT r.brand, r.site, r.product_code, r.reviewer_name, r.rating, r.review_text, "
            "r.review_text_en, r.review_date, r.scraped_at, p.name_th_or_en AS _product_name "
            "FROM product_reviews r LEFT JOIN products p ON p.product_code = r.product_code "
            "ORDER BY r.brand, r.review_date DESC",
        ),
        "acneaid_th_brand_feedback.csv": (
            "SELECT brand, site, post_title, post_date, content_en, topic_tags, post_url, scraped_at "
            "FROM forum_posts ORDER BY brand, post_date DESC",
        ),
    }

    name_filtered_exports = {"acneaid_th_pricing.csv": "name_th_or_en",
                              "acneaid_th_product_reviews.csv": "_product_name"}

    for base_filename, (query,) in exports.items():
        stem, ext = base_filename.rsplit(".", 1)
        filename = f"{stem}_{ts}.{ext}"

        rows = conn.execute(query).fetchall()
        if base_filename in name_filtered_exports and name_filters:
            name_col = name_filtered_exports[base_filename]
            n_before = len(rows)
            rows = [
                r for r in rows
                if not (r["site"] == "boots_th" and r["brand"] in name_filters
                        and not re.search(name_filters[r["brand"]], r[name_col] or "", re.IGNORECASE))
            ]
            if len(rows) != n_before:
                log.info(f"[EXPORT] {filename}: filtered {n_before - len(rows)} keyword-noise rows "
                        f"(kept in DB, excluded from export) via boots_name_filter")
        path = Path(output_dir) / filename
        if rows:
            header = [k for k in rows[0].keys() if not k.startswith("_")]
            with open(path, "w", newline="", encoding="utf-8-sig") as f:
                writer = _csv.writer(f)
                writer.writerow(header)
                for row in rows:
                    writer.writerow(tuple(row[k] for k in header))
        else:
            # Still write an empty file with headers so the client sees the
            # expected structure even before that source has data.
            with open(path, "w", newline="", encoding="utf-8-sig") as f:
                pass
        counts[filename] = len(rows)
        log.info(f"[EXPORT] {filename}: {len(rows)} rows")

    conn.close()
    return counts


# ── RUN SUMMARY ───────────────────────────────────────────────────────────

def write_summary(db_path: str, output_dir: str, run_start: datetime) -> None:
    conn = open_db(db_path)
    elapsed = (datetime.now(timezone.utc) - run_start).total_seconds()

    products = conn.execute(
        "SELECT brand, site, COUNT(*) as n FROM products GROUP BY brand, site ORDER BY brand, site"
    ).fetchall()
    posts = conn.execute(
        "SELECT brand, site, COUNT(*) as n FROM forum_posts GROUP BY brand, site ORDER BY brand, site"
    ).fetchall()
    total_p = conn.execute("SELECT COUNT(*) FROM products").fetchone()[0]
    total_posts = conn.execute("SELECT COUNT(*) FROM forum_posts").fetchone()[0]
    total_ph = conn.execute("SELECT COUNT(*) FROM price_history").fetchone()[0]
    conn.close()

    lines = [
        "# Acne-Aid Thailand Pipeline -- Run Summary",
        f"**Date:** {run_start.strftime('%Y-%m-%d %H:%M')}  ",
        f"**Duration:** {int(elapsed // 60)}m {int(elapsed % 60)}s  ",
        "",
        "## Products (Pricing)",
        "| Brand | Site | Count |",
        "|---|---|---:|",
    ]
    for row in products:
        lines.append(f"| {row['brand']} | {row['site']} | {row['n']} |")
    lines += [f"| **Total** | | **{total_p}** |", ""]

    lines += [
        "## Forum Posts (Brand Feedback)",
        "| Brand | Site | Count |",
        "|---|---|---:|",
    ]
    for row in posts:
        lines.append(f"| {row['brand']} | {row['site']} | {row['n']} |")
    lines += [f"| **Total** | | **{total_posts}** |", ""]

    lines += [
        "## Price History",
        f"- Total dated price-history rows: **{total_ph}**",
        "",
    ]

    lines += [
        "## Cost",
        f"- Input tokens:  {cost_tracker.input_tokens:,}",
        f"- Output tokens: {cost_tracker.output_tokens:,}",
        f"- **Estimated: ${cost_tracker.cost:.4f}**",
        "",
    ]

    path = Path(output_dir) / f"summary_{datetime.now().strftime('%Y%m%d_%H%M')}.md"
    path.write_text("\n".join(lines), encoding="utf-8")
    log.info(f"[SUMMARY] Written -> {path}")


# ── MAIN ORCHESTRATOR ─────────────────────────────────────────────────────

def run(
    config_path: str = "config_th.yaml",
    brand_filter: Optional[List[str]] = None,
    site_filter: Optional[List[str]] = None,
    discover_only: bool = False,
    auto_export_csv: bool = True,
) -> None:
    with open(config_path, encoding="utf-8") as f:
        config = yaml.safe_load(f)

    output_dir = config.get("output", {}).get("directory", "output")
    db_path = str(Path(output_dir) / "acneaid_th.db")
    Path(output_dir).mkdir(parents=True, exist_ok=True)

    fh = logging.FileHandler(
        Path(output_dir) / f"pipeline_{datetime.now().strftime('%Y%m%d_%H%M')}.log", encoding="utf-8"
    )
    fh.setFormatter(logging.Formatter("%(asctime)s [%(levelname)s] %(message)s"))
    log.addHandler(fh)

    active_sites = [s.lower() for s in site_filter] if site_filter else None
    run_start = datetime.now(timezone.utc)

    def _site_on(name: str) -> bool:
        return active_sites is None or name in active_sites

    log.info("=" * 60)
    log.info(f"Acne-Aid TH Pipeline | {run_start.strftime('%Y-%m-%d %H:%M')} | "
             f"brands={brand_filter or 'all'} | sites={active_sites or 'all'}")
    log.info("=" * 60)

    # AUDIT FIX #11: back up the DB before this run touches it with any
    # write (schema migration in open_db() included). No-op on first run.
    backup_db(db_path)

    conn = open_db(db_path)
    lock = threading.Lock()

    # ── Boots.co.th ──
    if config["sites"]["boots_th"]["enabled"] and _site_on("boots_th"):
        # AUDIT FIX #1: load queries from the canonical sku_query_master.csv
        # (same file Shopee/BigC use), not a parallel config_th.yaml keyword
        # list. Path is configurable via config["sku_query_master_csv"],
        # defaulting to the file sitting alongside this script.
        sku_csv_path = config.get("sku_query_master_csv", "sku_query_master.csv")
        sku_rows = load_sku_queries(sku_csv_path, brand_filter)
        print_sku_query_summary(sku_rows)

        boots_products = discover_boots_th(sku_rows, config, conn=conn, lock=lock)
        log.info(f"[DISCOVER] Boots.co.th: {len(boots_products)} products processed (saved incrementally per brand)")
    else:
        log.info("[SKIP] boots_th not enabled or not in --site filter")

    # ── Watsons.co.th ──
    if config["sites"]["watsons_th"]["enabled"] and _site_on("watsons_th"):
        watsons_products = discover_watsons_th(config, brand_filter)
        n_new = save_products(conn, watsons_products, lock)
        log.info(f"[DISCOVER] Watsons.co.th: {n_new} new/updated products")
    else:
        log.info("[SKIP] watsons_th not enabled or not in --site filter")

    # ── Boots.co.th Reviews ── (opt-in only: must be explicitly named via --site boots_reviews)
    if active_sites and "boots_reviews" in active_sites:
        write_q = queue.Queue()
        done_evt = threading.Event()
        writer = threading.Thread(target=_db_writer, args=(db_path, write_q, done_evt), daemon=False)
        writer.start()

        n_checked = extract_boots_reviews(db_path, write_q, brand_filter)

        done_evt.set()
        write_q.put(None)
        writer.join()
        log.info(f"[REVIEWS] Boots.co.th: {n_checked} products checked for reviews")
    else:
        log.info("[SKIP] boots_reviews -- only runs when explicitly requested via --site boots_reviews")

    # ── Pantip ──
    if config["sites"]["pantip"]["enabled"] and _site_on("pantip") and not discover_only:
        client = OpenAI()   # only instantiated here — pricing-only runs never need an API key
        write_q = queue.Queue()
        done_evt = threading.Event()
        writer = threading.Thread(target=_db_writer, args=(db_path, write_q, done_evt), daemon=False)
        writer.start()

        posts = discover_pantip(config, client, brand_filter)
        write_q.put(("posts", posts))

        done_evt.set()
        write_q.put(None)
        writer.join()
        log.info(f"[DISCOVER] Pantip: {len(posts)} forum posts extracted")
    else:
        log.info("[SKIP] pantip not enabled, not in --site filter, or --discover-only set")

    # ── Pantip (deep/room-crawl) ── (opt-in only: must be explicitly named via --site pantip_deep)
    if active_sites and "pantip_deep" in active_sites:
        client = OpenAI()
        xlsx_path = config["sites"]["pantip_deep"]["room_crawl_xlsx"]
        write_q = queue.Queue()
        done_evt = threading.Event()
        writer = threading.Thread(target=_db_writer, args=(db_path, write_q, done_evt), daemon=False)
        writer.start()

        n_posts = discover_pantip_deep(config, client, xlsx_path, brand_filter, conn=conn, write_q=write_q)

        done_evt.set()
        write_q.put(None)
        writer.join()
        log.info(f"[DEEP] Pantip (room-crawl): {n_posts} forum posts extracted")
    else:
        log.info("[SKIP] pantip_deep -- only runs when explicitly requested via --site pantip_deep")

    conn.close()
    write_summary(db_path, output_dir, run_start)

    # AUTO CSV EXPORT (2026-08-08): every run now writes client-ready CSVs
    # by default -- SQLite stays the internal engine (dedup, price history,
    # backup all depend on it), but you no longer need a separate
    # --export-csv invocation to get files you can open directly. Disable
    # with --no-csv if you only want the DB updated (e.g. mid-debugging).
    if auto_export_csv:
        counts = export_csvs(db_path, output_dir, config_path=config_path)
        log.info(f"[EXPORT] Auto-exported CSVs: {counts}")
    else:
        log.info("[EXPORT] Skipped (--no-csv) -- run with --export-csv later to generate client CSVs.")

    cost_tracker.report()
    log.info("\nPipeline run complete.")


# ── CLI ────────────────────────────────────────────────────────────────────

if __name__ == "__main__":
    parser = argparse.ArgumentParser(description="Acne-Aid Thailand Market Intelligence Pipeline")
    parser.add_argument("--config", default="config_th.yaml")
    parser.add_argument("--brand", nargs="+", help='e.g. --brand "Acne-Aid" "CeraVe"')
    parser.add_argument("--site", nargs="+", help="e.g. --site boots_th  or  --site pantip")
    parser.add_argument("--pricing-only", action="store_true",
                         help="Shortcut: run only Boots.co.th + Watsons.co.th pricing, skip Pantip/LLM entirely. "
                              "No OpenAI key needed. Safe to run unattended -- saves per brand as it goes.")
    parser.add_argument("--discover-only", action="store_true", help="Skip Pantip LLM extraction, pricing only")
    parser.add_argument("--export-csv", action="store_true",
                         help="Skip the pipeline entirely; just export the current DB to client-ready CSVs")
    parser.add_argument("--no-csv", action="store_true",
                         help="Skip the automatic end-of-run CSV export (DB is still updated as normal)")
    parser.add_argument("--debug", action="store_true")
    args = parser.parse_args()

    if args.debug:
        log.setLevel(logging.DEBUG)

    if args.export_csv:
        with open(args.config, encoding="utf-8") as f:
            _cfg = yaml.safe_load(f)
        _out_dir = _cfg.get("output", {}).get("directory", "output")
        _db_path = str(Path(_out_dir) / "acneaid_th.db")
        counts = export_csvs(_db_path, _out_dir)
        log.info(f"[EXPORT] CSV export complete: {counts}")
        raise SystemExit(0)

    site_filter = args.site
    discover_only = args.discover_only
    if args.pricing_only:
        site_filter = ["boots_th"]   # watsons_th excluded: confirmed blocked, see discover_watsons_th docstring
        discover_only = True
        log.info("[MODE] --pricing-only: Boots.co.th only (Watsons confirmed blocked, "
                  "Pantip/LLM skipped). No API key needed.")

    run(
        config_path=args.config,
        brand_filter=args.brand,
        site_filter=site_filter,
        discover_only=discover_only,
        auto_export_csv=not args.no_csv,
    )
