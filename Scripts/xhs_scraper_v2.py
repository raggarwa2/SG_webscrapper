#!/usr/bin/env python3
"""
xhs_scraper.py — Xiaohongshu (RedNote / 小紅書) data collection via Apify
Standalone script — sits alongside pipeline_v2.py, shares config.yaml + lensdata.db.

Usage:
    python xhs_scraper.py                        # all brands in config
    python xhs_scraper.py --brand Acuvue         # single brand
    python xhs_scraper.py --max-items 100        # more posts per keyword set

Prerequisites:
    pip install requests openai pydantic pyyaml
    export APIFY_TOKEN=apify_api_xxxxxxxxxxxx
    export OPENAI_API_KEY=sk-xxxxxxxxxxxx

Output:
    - Rows inserted into output/lensdata.db  →  table: xhs_posts
    - Log written to  output/xhs_YYYYMMDD_HHMM.log
"""

import os
import sys
import json
import time
import hashlib
import sqlite3
import logging
import argparse
import requests
import yaml
from datetime import datetime
from typing import Optional
from dotenv import load_dotenv
from openai import OpenAI

from pydantic import BaseModel
load_dotenv()

# ── Paths ──────────────────────────────────────────────────────────────────
DB_PATH     = "output/lensdata.db"
CONFIG_PATH = "config.yaml"
LOG_PATH    = f"output/xhs_{datetime.now().strftime('%Y%m%d_%H%M')}.log"
APIFY_BASE  = "https://api.apify.com/v2"

# ── Logging ──────────────────────────────────────────────────────────────────────
os.makedirs("output", exist_ok=True)
logging.basicConfig(
    level=logging.INFO,
    format="%(asctime)s  %(levelname)-8s  %(message)s",
    handlers=[
        logging.FileHandler(LOG_PATH, encoding="utf-8"),
        logging.StreamHandler(sys.stdout),
    ],
)
log = logging.getLogger(__name__)

# ── Pydantic models ───────────────────────────────────────────────────────────
VALID_THEMES = [
    "comfort", "dryness", "colour", "price", "value",
    "packaging", "delivery", "authenticity", "brand_comparison",
    "recommendation", "warning", "vision_clarity",
]

class XHSPostAnalysis(BaseModel):
    content_en:      str        # concise English translation
    sentiment:       str        # positive | neutral | negative
    themes:          list[str]  # 1–4 items from VALID_THEMES
    brand_mentioned: str        # Acuvue | Alcon | Bausch & Lomb | OLENS | REVIA | CooperVision | other

class XHSCommentAnalysis(BaseModel):
    content_en: str       # concise English translation (max 60 words)
    sentiment:  str       # positive | neutral | negative
    themes:     list[str] # 1–3 items from VALID_THEMES

SYSTEM_PROMPT = f"""You analyse Xiaohongshu (RedNote) posts about contact lenses in Hong Kong.
Respond ONLY with valid JSON matching the required schema. No markdown, no preamble.

Rules:
- content_en : concise English translation of title + body (max 150 words)
- sentiment  : exactly one of: positive | neutral | negative
- themes     : 1–4 items chosen from {VALID_THEMES}
- brand_mentioned : exactly one of: Acuvue | Alcon | Bausch & Lomb | OLENS | REVIA | CooperVision | other
"""

COMMENT_SYSTEM_PROMPT = f"""You analyse individual comments on Xiaohongshu contact lens posts.
Respond ONLY with valid JSON. No markdown, no preamble.

Rules:
- content_en : concise English translation of the comment (max 60 words)
- sentiment  : exactly one of: positive | neutral | negative
- themes     : 1–3 items chosen from {VALID_THEMES}
"""

# ── SQLite ────────────────────────────────────────────────────────────────────
def get_conn() -> sqlite3.Connection:
    conn = sqlite3.connect(DB_PATH)
    conn.execute("PRAGMA journal_mode=WAL")
    conn.execute("PRAGMA busy_timeout=60000")
    conn.execute("PRAGMA synchronous=NORMAL")
    return conn

def init_schema(conn: sqlite3.Connection) -> None:
    """Add xhs_posts table if it doesn't exist — non-destructive."""
    conn.executescript("""
        CREATE TABLE IF NOT EXISTS xhs_posts (
            id              INTEGER PRIMARY KEY AUTOINCREMENT,
            post_id         TEXT    UNIQUE NOT NULL,
            brand_keyword   TEXT    NOT NULL,
            title           TEXT,
            content_zh      TEXT,
            content_en      TEXT,
            sentiment       TEXT,
            themes          TEXT,           -- stored as JSON list
            brand_mentioned TEXT,
            author          TEXT,
            likes           INTEGER DEFAULT 0,
            collects        INTEGER DEFAULT 0,
            comments        INTEGER DEFAULT 0,
            publish_date    TEXT,
            url             TEXT,
            scraped_at      TEXT    NOT NULL
        );
        CREATE INDEX IF NOT EXISTS idx_xhs_brand     ON xhs_posts(brand_keyword);
        CREATE INDEX IF NOT EXISTS idx_xhs_sentiment ON xhs_posts(sentiment);
        CREATE INDEX IF NOT EXISTS idx_xhs_date      ON xhs_posts(publish_date);

        CREATE TABLE IF NOT EXISTS xhs_comments (
            id          INTEGER PRIMARY KEY AUTOINCREMENT,
            post_id     TEXT    NOT NULL,
            comment_id  TEXT    UNIQUE,
            author      TEXT,
            content_zh  TEXT,
            content_en  TEXT,
            sentiment   TEXT,
            themes      TEXT,           -- stored as JSON list
            likes       INTEGER DEFAULT 0,
            scraped_at  TEXT    NOT NULL,
            FOREIGN KEY (post_id) REFERENCES xhs_posts(post_id)
        );
        CREATE INDEX IF NOT EXISTS idx_xhs_comments_post ON xhs_comments(post_id);
    """)
    # Migration: add content_en to existing tables that predate this column
    try:
        conn.execute("ALTER TABLE xhs_comments ADD COLUMN content_en TEXT")
        conn.commit()
        log.info("Migrated xhs_comments: added content_en column")
    except sqlite3.OperationalError:
        pass  # column already exists
    conn.commit()
    log.info("DB schema ready (xhs_posts)")

# ── Apify ─────────────────────────────────────────────────────────────────────
def apify_run_one(token: str, actor_id: str, keyword: str, max_items: int) -> list[dict]:
    """
    Run Apify actor for ONE keyword, poll until SUCCEEDED, return dataset items.
    Uses zen-studio/rednote-search-scraper input schema (keyword + limit).
    """
    # Apify URL uses ~ not / for actor IDs
    actor_slug = actor_id.replace("/", "~")

    # 1. Start run
    r = requests.post(
        f"{APIFY_BASE}/acts/{actor_slug}/runs",
        json={
            "keywords": [keyword],   # API requires array, not string
            "limit": max_items,
        },
        params={"token": token},
        timeout=30,
    )
    if not r.ok:
        log.error(f"  Apify 400 body: {r.text[:500]}")
    r.raise_for_status()
    run_info   = r.json()["data"]
    run_id     = run_info["id"]
    dataset_id = run_info["defaultDatasetId"]
    log.info(f"  Apify run started → run_id={run_id}")

    # 2. Poll status (max 15 min)
    status_url = f"{APIFY_BASE}/actor-runs/{run_id}"
    for attempt in range(90):           # 90 × 10s = 15 min
        time.sleep(10)
        status = requests.get(status_url, params={"token": token}, timeout=15) \
                         .json()["data"]["status"]
        log.info(f"  Run status: {status}  (attempt {attempt + 1})")
        if status == "SUCCEEDED":
            break
        if status in ("FAILED", "ABORTED", "TIMED-OUT"):
            raise RuntimeError(f"Apify run {run_id} ended with: {status}")
    else:
        raise TimeoutError(f"Apify run {run_id} did not finish in 15 minutes")

    # 3. Fetch results
    items_r = requests.get(
        f"{APIFY_BASE}/datasets/{dataset_id}/items",
        params={"token": token, "format": "json", "limit": max_items},
        timeout=60,
    )
    items_r.raise_for_status()
    posts = items_r.json()
    log.info(f"  Retrieved {len(posts)} posts for keyword: {keyword}")
    return posts


def apify_run(token: str, actor_id: str, keywords: list[str], max_items: int) -> list[dict]:
    """Run actor once per keyword and combine results (deduped by post_id)."""
    all_posts: list[dict] = []
    seen_ids: set[str] = set()
    per_kw = max(10, max_items // max(len(keywords), 1))

    for kw in keywords:
        try:
            posts = apify_run_one(token, actor_id, kw, per_kw)
            for p in posts:
                pid = str(p.get("postId") or p.get("id") or p.get("noteId") or "")
                if pid and pid not in seen_ids:
                    seen_ids.add(pid)
                    all_posts.append(p)
        except Exception as e:
            log.warning(f"  Keyword '{kw}' failed: {e}")
        time.sleep(2)

    log.info(f"Total unique posts across all keywords: {len(all_posts)}")
    return all_posts

# ── Field extraction — handles schema differences between Apify actors ────────
def _pick(d: dict, *keys: str, default="") -> str:
    """Return first non-empty value from a list of dot-path keys."""
    for k in keys:
        if "." in k:
            parts = k.split(".", 1)
            sub = d.get(parts[0])
            if isinstance(sub, dict):
                v = sub.get(parts[1], "")
                if v:
                    return str(v)
        else:
            v = d.get(k, "")
            if v:
                return str(v)
    return default

def extract_fields(post: dict) -> dict:
    # zen-studio/rednote-search-scraper schema:
    #   url, title, desc, author.nickname, engagement.liked_count,
    #   engagement.collected_count, engagement.comments_count
    # Extract post ID from URL: /discovery/item/POST_ID?...
    raw_url = _pick(post, "url", "postUrl", "shareUrl")
    post_id = ""
    if "/item/" in raw_url:
        post_id = raw_url.split("/item/")[1].split("?")[0]
    if not post_id:
        post_id = _pick(post, "postId", "id", "noteId")
    
    # Engagement lives in nested object
    eng = post.get("engagement", {}) if isinstance(post.get("engagement"), dict) else {}
    
    return {
        "post_id":  post_id[:64],
        "title":    _pick(post, "title", "name")[:500],
        "content":  _pick(post, "desc", "content", "body", "description")[:5000],
        "author":   _pick(post, "author.nickname", "user.nickname",
                               "nickname", "author")[:200],
        "likes":    int(eng.get("liked_count") or _pick(post, "likes", "likedCount") or 0),
        "collects": int(eng.get("collected_count") or _pick(post, "collects") or 0),
        "comments": int(eng.get("comments_count") or _pick(post, "comments") or 0),
        "date":     _pick(post, "scrapedAt", "time", "createTime",
                               "publishTime", "timestamp")[:50],
        "url":      raw_url[:500],
    }

# ── GPT-4o-mini — same method as pipeline_v2.py ──────────────────────────────
openai_client = OpenAI()

def analyse_post(title: str, content: str) -> Optional[XHSPostAnalysis]:
    text = f"Title: {title}\n\n{content}".strip()
    if len(text) < 10:
        return None
    try:
        resp = openai_client.beta.chat.completions.parse(
            model="gpt-4o-mini",
            messages=[
                {"role": "system", "content": SYSTEM_PROMPT},
                {"role": "user",   "content": text},
            ],
            response_format=XHSPostAnalysis,
            max_tokens=400,
        )
        return resp.choices[0].message.parsed
    except Exception as e:
        log.warning(f"GPT parse failed: {e}")
        return None

# ── DB read (for skip-already-collected logic) ──────────────────────────────────
def load_existing_post_ids(conn: sqlite3.Connection) -> set[str]:
    """Post IDs already in xhs_posts — used to skip GPT analysis on repeat runs."""
    rows = conn.execute("SELECT post_id FROM xhs_posts").fetchall()
    return {r[0] for r in rows}

def load_posts_missing_comments(conn: sqlite3.Connection) -> list[tuple[str, str]]:
    """Return (post_id, url) for posts not yet represented in xhs_comments."""
    rows = conn.execute("""
        SELECT p.post_id, p.url
        FROM xhs_posts p
        LEFT JOIN xhs_comments c ON p.post_id = c.post_id
        WHERE c.post_id IS NULL
          AND p.url IS NOT NULL
          AND p.url != ''
    """).fetchall()
    return rows

# ── Apify — comments fetch ────────────────────────────────────────────────────
def apify_fetch_comments_batch(
    token: str, actor_id: str, urls: list[str], max_comments: int
) -> list[dict]:
    """Run comments actor for a batch of post URLs; return raw dataset items."""
    actor_slug = actor_id.replace("/", "~")
    r = requests.post(
        f"{APIFY_BASE}/acts/{actor_slug}/runs",
        json={
            "mode":        "comments",
            "postUrls":    urls,
            "maxComments": max_comments,
        },
        params={"token": token},
        timeout=30,
    )
    if not r.ok:
        log.error(f"  Comments Apify 400: {r.text[:500]}")
    r.raise_for_status()
    run_info   = r.json()["data"]
    run_id     = run_info["id"]
    dataset_id = run_info["defaultDatasetId"]
    log.info(f"  Comments run started → run_id={run_id}  ({len(urls)} URLs)")

    for attempt in range(90):
        time.sleep(10)
        status = requests.get(
            f"{APIFY_BASE}/actor-runs/{run_id}", params={"token": token}, timeout=15
        ).json()["data"]["status"]
        log.info(f"  Comments run status: {status}  (attempt {attempt + 1})")
        if status == "SUCCEEDED":
            break
        if status in ("FAILED", "ABORTED", "TIMED-OUT"):
            raise RuntimeError(f"Comments run {run_id} ended with: {status}")
    else:
        raise TimeoutError(f"Comments run {run_id} did not finish in 15 minutes")

    items_r = requests.get(
        f"{APIFY_BASE}/datasets/{dataset_id}/items",
        params={"token": token, "format": "json", "limit": len(urls) * max_comments + 10},
        timeout=60,
    )
    items_r.raise_for_status()
    items = items_r.json()
    log.info(f"  Retrieved {len(items)} items from comments run")
    return items

def _post_id_from_url(url: str) -> str:
    if "/item/" in url:
        return url.split("/item/")[1].split("?")[0]
    if "/explore/" in url:
        return url.split("/explore/")[1].split("?")[0]
    return ""

def extract_comment_fields(item: dict) -> dict:
    """
    Extract fields from a flat comment item returned by zhorex/rednote-xiaohongshu-scraper.
    Each dataset item is one comment (mode=comments returns flat rows, not nested).
    Fields: postId, postUrl, content, authorName, likes, publishedAt
    """
    post_id = _pick(item, "postId") or _post_id_from_url(_pick(item, "postUrl"))
    content = _pick(item, "content")[:2000]
    author  = _pick(item, "authorName")[:200]
    # No commentId in actor output — synthesise a stable hash
    raw_key    = f"{post_id}:{author}:{content}"
    comment_id = hashlib.md5(raw_key.encode()).hexdigest()[:24]
    return {
        "post_id":    post_id[:64],
        "comment_id": comment_id,
        "author":     author,
        "content":    content,
        "likes":      int(_pick(item, "likes") or 0),
    }

# ── GPT — comment analysis ────────────────────────────────────────────────────
def analyse_comment(content: str) -> Optional[XHSCommentAnalysis]:
    if len(content.strip()) < 5:
        return None
    try:
        resp = openai_client.beta.chat.completions.parse(
            model="gpt-4o-mini",
            messages=[
                {"role": "system", "content": COMMENT_SYSTEM_PROMPT},
                {"role": "user",   "content": content},
            ],
            response_format=XHSCommentAnalysis,
            max_tokens=250,
        )
        return resp.choices[0].message.parsed
    except Exception as e:
        log.warning(f"GPT comment parse failed: {e}")
        return None

# ── DB write — comments ───────────────────────────────────────────────────────
def save_comment(
    conn: sqlite3.Connection,
    post_id: str,
    cf: dict,
    a: Optional[XHSCommentAnalysis],
) -> bool:
    try:
        conn.execute(
            """INSERT OR IGNORE INTO xhs_comments
               (post_id, comment_id, author, content_zh, content_en, sentiment, themes, likes, scraped_at)
               VALUES (?,?,?,?,?,?,?,?,?)""",
            (
                post_id,
                cf["comment_id"] or None,
                cf["author"],
                cf["content"],
                a.content_en      if a else None,
                a.sentiment       if a else None,
                json.dumps(a.themes, ensure_ascii=False) if a else None,
                cf["likes"],
                datetime.now().isoformat(),
            ),
        )
        conn.commit()
        return conn.execute("SELECT changes()").fetchone()[0] > 0
    except sqlite3.Error as e:
        log.warning(f"Comment save failed ({post_id}): {e}")
        return False


# ── DB write ──────────────────────────────────────────────────────────────────
def save_post(
    conn: sqlite3.Connection,
    brand: str,
    f: dict,
    a: Optional[XHSPostAnalysis],
) -> bool:
    """INSERT OR IGNORE — skips duplicates silently. Returns True if new row."""
    try:
        conn.execute(
            """INSERT OR IGNORE INTO xhs_posts
               (post_id, brand_keyword, title, content_zh, content_en,
                sentiment, themes, brand_mentioned, author,
                likes, collects, comments, publish_date, url, scraped_at)
               VALUES (?,?,?,?,?,?,?,?,?,?,?,?,?,?,?)""",
            (
                f["post_id"], brand, f["title"], f["content"],
                a.content_en       if a else None,
                a.sentiment        if a else None,
                json.dumps(a.themes, ensure_ascii=False) if a else None,
                a.brand_mentioned  if a else None,
                f["author"],
                f["likes"], f["collects"], f["comments"],
                f["date"], f["url"],
                datetime.now().isoformat(),
            ),
        )
        conn.commit()
        return conn.execute("SELECT changes()").fetchone()[0] > 0
    except sqlite3.Error as e:
        log.warning(f"DB write failed for {f['post_id']}: {e}")
        return False

# ── Comments phase ────────────────────────────────────────────────────────────
def run_comments_phase(
    conn: sqlite3.Connection,
    token: str,
    comments_actor: str,
    max_comments: int,
    batch_size: int,
) -> None:
    """Fetch + analyse comments for every post not yet covered in xhs_comments."""
    missing = load_posts_missing_comments(conn)
    if not missing:
        log.info("Comments: all posts already have comments — nothing to fetch.")
        return

    log.info(f"Comments: {len(missing)} posts need comments ({batch_size} URLs/batch)")
    total_saved = 0
    consecutive_failures = 0

    for batch_start in range(0, len(missing), batch_size):
        batch = missing[batch_start: batch_start + batch_size]
        urls  = [url for _, url in batch]
        url_to_post_id = {_post_id_from_url(url) or "": post_id for post_id, url in batch}

        log.info(f"  Batch {batch_start // batch_size + 1}: {len(urls)} URLs")
        try:
            items = apify_fetch_comments_batch(token, comments_actor, urls, max_comments)
            consecutive_failures = 0
        except Exception as e:
            log.error(f"  Comments batch failed: {e}")
            consecutive_failures += 1
            if consecutive_failures >= 3 or "403" in str(e):
                log.error("  Stopping comments phase — likely out of Apify credits (403 Forbidden). Top up and re-run --comments-only.")
                break
            time.sleep(5)
            continue

        # Log sample keys from first item to help diagnose field naming on first run
        if items:
            log.info(f"  Sample item keys: {list(items[0].keys())[:15]}")

        # Each item from zhorex actor is one flat comment row
        batch_saved = 0
        for item in items:
            cf = extract_comment_fields(item)
            if not cf["content"] or not cf["post_id"]:
                continue
            a = analyse_comment(cf["content"])
            if save_comment(conn, cf["post_id"], cf, a):
                batch_saved += 1

        log.info(f"  → {batch_saved} comments saved this batch")
        total_saved += batch_saved
        time.sleep(3)

    log.info(f"Comments phase done — {total_saved} total comments saved")


# ── Main ──────────────────────────────────────────────────────────────────────
def run(brand_filter: Optional[str], max_items: int, skip_comments: bool, comments_only: bool = False, max_comments_override: Optional[int] = None) -> None:
    token = os.environ.get("APIFY_TOKEN", "").strip()
    if not token:
        sys.exit("ERROR: APIFY_TOKEN environment variable is not set.\n"
                 "Get your token from https://console.apify.com/account/integrations")

    with open(CONFIG_PATH, encoding="utf-8") as fh:
        config = yaml.safe_load(fh)

    hk      = config["markets"]["HK"]
    xhs_cfg = hk.get("sites", {}).get("xhs", {})
    actor            = xhs_cfg.get("apify_actor_id", "zen-studio/rednote-search-scraper")
    comments_actor   = xhs_cfg.get("comments_actor_id", "epctex/xiaohongshu-scraper")
    max_comments     = max_comments_override if max_comments_override is not None else xhs_cfg.get("max_comments_per_post", 5)
    comment_batch    = xhs_cfg.get("comment_batch_size", 50)

    conn = get_conn()
    init_schema(conn)
    existing_ids = load_existing_post_ids(conn)
    log.info(f"Already in DB: {len(existing_ids)} posts (will skip re-analyzing these)")

    brands = hk["brands"]
    if brand_filter:
        brands = [b for b in brands if b["name"].lower() == brand_filter.lower()]
        if not brands:
            sys.exit(f"Brand '{brand_filter}' not found in config.yaml")

    total_saved  = 0
    total_posts  = 0
    start_time   = time.time()

    # ── Phase 1: scrape posts ─────────────────────────────────────────────────
    if comments_only:
        log.info("--comments-only: skipping post scrape phase")
    for brand in brands if not comments_only else []:
        name = brand["name"]
        keywords = brand.get("xhs_keywords") or brand.get("hktvmall_keywords", [name])
        log.info(f"{'─'*60}")
        log.info(f"Brand: {name}  |  keywords: {keywords}  |  max_items: {max_items}")

        try:
            posts = apify_run(token, actor, keywords, max_items)
        except Exception as e:
            log.error(f"Apify failed for {name}: {e}")
            continue

        brand_saved = 0
        brand_skipped = 0
        for post in posts:
            f = extract_fields(post)
            if not f["post_id"] or (not f["title"] and not f["content"]):
                continue
            if f["post_id"] in existing_ids:
                brand_skipped += 1
                continue
            a = analyse_post(f["title"], f["content"])
            if save_post(conn, name, f, a):
                brand_saved += 1
                existing_ids.add(f["post_id"])

        log.info(f"  → {brand_saved} new posts saved, {brand_skipped} skipped (already in DB)  ({len(posts)} retrieved)")
        total_saved += brand_saved
        total_posts += len(posts)
        time.sleep(3)

    elapsed = round(time.time() - start_time)
    log.info(f"{'─'*60}")
    log.info(f"Posts done — {total_saved}/{total_posts} saved  |  {elapsed}s")

    # ── Phase 2: fetch + analyse comments ────────────────────────────────────
    if skip_comments:
        log.info("Comments phase skipped (--skip-comments)")
    else:
        log.info(f"{'─'*60}")
        log.info(f"Starting comments phase  |  actor: {comments_actor}  |  max/post: {max_comments}")
        run_comments_phase(conn, token, comments_actor, max_comments, comment_batch)

    conn.close()
    log.info(f"{'─'*60}")
    log.info(f"All done  |  DB: {DB_PATH}  |  Log: {LOG_PATH}")

# ── CLI ───────────────────────────────────────────────────────────────────────
if __name__ == "__main__":
    ap = argparse.ArgumentParser(
        description="Scrape Xiaohongshu posts via Apify and store in lensdata.db"
    )
    ap.add_argument(
        "--brand",
        type=str,
        default=None,
        help="Single brand name to scrape (default: all brands in config.yaml)",
    )
    ap.add_argument(
        "--max-items",
        type=int,
        default=200,
        help="Max posts per keyword set (default: 200; lower it for cheap test runs)",
    )
    ap.add_argument(
        "--max-comments",
        type=int,
        default=None,
        help="Max comments per post (overrides config.yaml; default: 5)",
    )
    ap.add_argument(
        "--skip-comments",
        action="store_true",
        default=False,
        help="Skip the comment-fetching phase (posts only)",
    )
    ap.add_argument(
        "--comments-only",
        action="store_true",
        default=False,
        help="Skip post scraping; only fetch comments for posts already in DB",
    )
    ap.add_argument(
        "--retranslate-comments",
        action="store_true",
        default=False,
        help="Re-run GPT on existing comments missing content_en translation",
    )
    args = ap.parse_args()

    if args.retranslate_comments:
        conn = get_conn()
        init_schema(conn)
        rows = conn.execute(
            "SELECT id, content_zh FROM xhs_comments WHERE content_en IS NULL AND content_zh IS NOT NULL"
        ).fetchall()
        log.info(f"Retranslating {len(rows)} comments missing content_en ...")
        for row_id, content_zh in rows:
            a = analyse_comment(content_zh)
            if a:
                conn.execute(
                    "UPDATE xhs_comments SET content_en=?, sentiment=?, themes=? WHERE id=?",
                    (a.content_en, a.sentiment,
                     json.dumps(a.themes, ensure_ascii=False), row_id),
                )
                conn.commit()
        log.info("Retranslation done.")
        conn.close()
    else:
        run(
            brand_filter=args.brand,
            max_items=args.max_items,
            max_comments_override=args.max_comments,
            skip_comments=args.skip_comments,
            comments_only=args.comments_only,
        )
