# ==================================================================
# Facebook Social-Listening Module — MyACUVUE Singapore (standalone)
# ==================================================================
# Purpose:
#   Add Facebook as a consumer-feedback source for the MyACUVUE/J&J
#   Vision Singapore engagement (context.md — Awareness/Engagement
#   journey stages, same slot Instagram/YouTube/Reddit fill). Pulls
#   each brand's own official Page posts via an Apify Facebook actor,
#   then pulls comments on those posts — official-page comments are
#   the actual consumer-feedback surface here (price/registration/
#   trust complaints left directly under brand posts), same as the
#   IG/YouTube comment streams.
#
# WHY THIS IS PAGE-MODE ONLY, NOT HASHTAG/KEYWORD MODE:
#   Unlike Instagram (public hashtag search) or Reddit (public keyword
#   search), Facebook has no equivalent open keyword-search surface
#   reachable via a standard Apify actor — Facebook Search is
#   login-gated and actively scraper-hostile. What IS reachable without
#   login is a Page's own public post history, the same "profile mode"
#   instagram_scraper_th.py already supports as its --source profile
#   option. So this module only has that one mode: PAGES below, no
#   HASHTAGS/keyword equivalent. If a public post-search actor turns up
#   later, add a keyword mode the same way Reddit/Instagram have one.
#
# Status: STANDALONE MODULE — own SQLite db (facebook_data_sg.db).
#   NOT wired into any pipeline. Review sample output first; merge
#   into any downstream analysis is a separate, explicit step.
#
# Ported from instagram_scraper_th.py's architecture (run_actor() poll
#   loop, ig_scraped_sources cost-tracking table, brand-relevance/
#   sentiment LLM batch pattern) — same as every other SG social module
#   in this repo (youtube_scraper_sg.py, reddit_scraper_sg.py).
#
# IMPORTANT — project separation:
#   Keep this file and its outputs in THIS project only — do not point
#   it at the Thailand (acne-aid) or Hong Kong (xhs) project's DB/
#   output folders, and do not import data from them. External-only
#   data, Singapore market only (per context.md's scope boundary).
#
# Competitive set (per context.md): MyACUVUE vs Alcon (Air Optix,
# Dailies, Total30), CooperVision, Bausch & Lomb, Olens.
#
# Page handles (PAGES below) — verified via web search 2026-09-25, not
#   guessed. Confidence varies by brand; see inline notes. Re-verify
#   with --dry-run before trusting volume, same discipline as every
#   other handle/hashtag list in this repo:
#     - MyACUVUE:      facebook.com/acuvuesg — confirmed live (own posts
#                       indexed, e.g. "MyACUVUE turns ONE" anniversary post)
#     - CooperVision:   facebook.com/coopervisionsg — confirmed (~9,865 likes)
#     - Bausch + Lomb:  facebook.com/BauschandLombSG — confirmed
#     - Alcon:          NO Singapore-specific Page surfaced in search
#                        (only global/US myalcon.com content) — left
#                        empty, same as instagram_scraper_th.py left
#                        Acne-Aid's IG profile empty pending discovery
#     - Olens:          facebook.com/olensglobal — this is the GLOBAL
#                        Page (196K followers), not SG-specific; expect
#                        non-SG content mixed in, filter/interpret
#                        accordingly (same caveat as Olens on other
#                        channels in this project)
#
# Actor choice — CONFIRMED live 2026-09-25 against acuvuesg/coopervisionsg
#   (startUrls+resultsLimit input, real dataset items inspected, not just
#   a 201/run-started check):
#   POSTS_ACTOR "apify/facebook-posts-scraper" — returns postId, text,
#     likes, shares, time/timestamp, isVideo, url (a share-link, often
#     /reel/... for video posts) AND topLevelUrl (the stable canonical
#     .../posts/<id> permalink — extract_post_fields() prefers this one
#     for `url`, since it's what the comments actor needs as input).
#     Does NOT return a comments-count field at all — comments_count is
#     stored as NULL (unknown), not 0, see extract_post_fields().
#   COMMENTS_ACTOR "apify/facebook-comments-scraper" — takes a post's
#     topLevelUrl, returns text, profileName (flat author name — prefer
#     over the nested `author.name` dict), likesCount, date, commentId.
#     On a post with zero comments it returns a single {"error":
#     "no_items", ...} row with no `text` key, which extract_comment_
#     fields() already drops via its `if not text: return None` guard.
#   FINDING from this live test (both acuvuesg and coopervisionsg, 10-15
#   posts each): organic engagement on these official SG-adjacent brand
#   Pages is very thin (0-8 likes/post, most posts had zero comments) —
#   budget expectations accordingly, same as the low-signal-density
#   finding already flagged for Reddit SG in scripts.md.
#
# Cost model: confirmed live — ~$0.001 per posts-scraper call (10-15
#   posts), ~$0.001-0.003 per comments-scraper call (one post). Cheap
#   enough that --max-posts-with-comments is mostly for smoke-testing,
#   not real cost control, but still run a small --dry-run first.
#
# Setup required: APIFY_TOKEN and OPENAI_API_KEY in .env for this
#   project (already populated per day_1_plan.md Phase 0).
#
# Usage:
#   python facebook_scraper_sg.py --dry-run
#   python facebook_scraper_sg.py --brand "MyACUVUE" --market SG
#   python facebook_scraper_sg.py --max-posts 30
#   python facebook_scraper_sg.py --skip-comments
#   python facebook_scraper_sg.py --classify-existing
#   python facebook_scraper_sg.py --export-csv
# ==================================================================

import argparse
import csv
import hashlib
import json
import logging
import re
import sqlite3
import time
from datetime import datetime, timezone
from pathlib import Path
from typing import Dict, List, Optional

import os
import requests
from dotenv import load_dotenv
from openai import OpenAI

load_dotenv()

logging.basicConfig(
    level=logging.INFO,
    format="%(asctime)s [%(levelname)s] %(message)s",
    handlers=[logging.StreamHandler()],
)
log = logging.getLogger(__name__)

APIFY_BASE = "https://api.apify.com/v2"

# UNVERIFIED -- see header note. Override with --posts-actor/
# --comments-actor if these slugs are wrong or you prefer different ones.
POSTS_ACTOR = "apify/facebook-posts-scraper"
COMMENTS_ACTOR = "apify/facebook-comments-scraper"

# ── CONFIG: official Page handles per market (page mode only) ────────
# See header note for verification status per brand.
PAGES = {
    "SG": {
        "MyACUVUE":      ["acuvuesg"],
        "Alcon":         [],
        # ^ left empty deliberately -- no SG-specific Page confirmed in
        # search (see header note). Revisit if one surfaces.
        "CooperVision":  ["coopervisionsg"],
        "Bausch + Lomb": ["BauschandLombSG"],
        "Olens":         ["olensglobal"],
        # ^ global Page, not SG-specific -- expect mixed-market content.
    },
}

# Literal brand-name aliases -- kept identical to youtube_scraper_sg.py/
# reddit_scraper_sg.py's BRAND_ALIASES so a post/comment mentioning a
# competitor by name on the "wrong" brand's page (e.g. a comparison
# comment) is still caught correctly downstream.
BRAND_ALIASES = {
    "MyACUVUE":      ["acuvue", "myacuvue", "acuvue oasys", "acuvue moist"],
    "Alcon":         ["alcon", "air optix", "dailies total30", "dailies", "freshlook"],
    "CooperVision":  ["coopervision", "biofinity", "clariti", "myday", "avaira"],
    "Bausch + Lomb": ["bausch lomb", "bausch + lomb", "bausch & lomb", "biotrue", "ultra contact"],
    "Olens":         ["olens", "o-lens"],
}

CLASSIFY_BATCH_SIZE = 20

# ── DB SCHEMA (separate db -- facebook_data_sg.db) ────────────────────

SCHEMA = """
CREATE TABLE IF NOT EXISTS fb_posts (
    post_id          TEXT PRIMARY KEY,
    brand            TEXT NOT NULL,
    market            TEXT NOT NULL,
    page              TEXT,
    text              TEXT,
    likes_count       INTEGER,
    comments_count    INTEGER,
    shares_count      INTEGER,
    published_at      TEXT,
    url               TEXT,
    discovered_at     TEXT,
    is_lens_relevant  INTEGER
);

CREATE TABLE IF NOT EXISTS fb_comments (
    id                         INTEGER PRIMARY KEY AUTOINCREMENT,
    post_id                    TEXT NOT NULL,
    brand                      TEXT NOT NULL,
    market                     TEXT NOT NULL,
    author                     TEXT,
    comment_text               TEXT,
    like_count                 INTEGER,
    published_at               TEXT,
    content_hash                TEXT UNIQUE,
    scraped_at                 TEXT,
    sentiment                  TEXT,
    is_purchase_barrier_signal INTEGER,
    is_lens_relevant           INTEGER,
    FOREIGN KEY(post_id) REFERENCES fb_posts(post_id)
);

-- Tracks which (brand, page) combos have already had a paid Apify run
-- made for them, so re-running the script doesn't re-spend credits on
-- the same page pull every time. A source stays "done" until
-- --force-rescrape is passed. Same pattern as every other SG module's
-- *_scraped_sources table.
CREATE TABLE IF NOT EXISTS fb_scraped_sources (
    brand           TEXT NOT NULL,
    market          TEXT NOT NULL,
    page            TEXT NOT NULL,
    last_scraped_at TEXT NOT NULL,
    items_found     INTEGER,
    PRIMARY KEY (brand, market, page)
);

CREATE INDEX IF NOT EXISTS idx_fb_posts_brand    ON fb_posts(brand);
CREATE INDEX IF NOT EXISTS idx_fb_comments_brand ON fb_comments(brand);
CREATE INDEX IF NOT EXISTS idx_fb_comments_post  ON fb_comments(post_id);
"""


def open_db(path: str) -> sqlite3.Connection:
    Path(path).parent.mkdir(parents=True, exist_ok=True)
    conn = sqlite3.connect(path, timeout=60)
    conn.row_factory = sqlite3.Row
    conn.execute("PRAGMA journal_mode=WAL")
    conn.executescript(SCHEMA)
    # Dashboard filter col: global (non-SG) pages are excluded from SG metrics.
    if "market_relevant" not in {r[1] for r in conn.execute("PRAGMA table_info(fb_posts)")}:
        conn.execute("ALTER TABLE fb_posts ADD COLUMN market_relevant INTEGER DEFAULT 1")
    conn.execute("UPDATE fb_posts SET market_relevant = 0 WHERE page = 'olensglobal'")
    conn.commit()
    return conn


def get_scraped_source_keys(conn: sqlite3.Connection) -> set:
    return {
        (row["brand"], row["market"], row["page"])
        for row in conn.execute("SELECT brand, market, page FROM fb_scraped_sources")
    }


def mark_source_scraped(conn: sqlite3.Connection, brand: str, market: str, page: str, items_found: int) -> None:
    conn.execute(
        """INSERT INTO fb_scraped_sources (brand, market, page, last_scraped_at, items_found)
           VALUES (?, ?, ?, ?, ?)
           ON CONFLICT(brand, market, page)
           DO UPDATE SET last_scraped_at = excluded.last_scraped_at, items_found = excluded.items_found""",
        (brand, market, page, datetime.now(timezone.utc).isoformat(), items_found),
    )
    conn.commit()


# ── LENS/EYE-CARE-RELEVANCE WHITELIST (regex, no LLM cost) ───────────
# Identical term list to youtube_scraper_sg.py/reddit_scraper_sg.py --
# whitelist-not-blacklist: flags (does NOT drop) posts/comments with no
# explicit lens/eye-care term, so low-volume data isn't silently
# thrown away.

LENS_RELEVANCE_TERMS_EN = [
    "contact lens", "contacts", "colored contacts", "coloured contacts",
    "daily disposable", "astigmatism", "eye care", "dry eyes",
    "power lens", "prescription lens", "optometrist", "cornea",
    "myopia", "lens fitting", "eye exam", "circle lens",
]
_LENS_TERM_PATTERN_EN = re.compile(
    "|".join(t.replace(" ", r"\s*") for t in LENS_RELEVANCE_TERMS_EN),
    re.IGNORECASE,
)


def _is_lens_relevant(text: str) -> bool:
    return bool(_LENS_TERM_PATTERN_EN.search(text or ""))


# ── COST TRACKER (same model/rates as youtube_scraper_sg.py) ─────────

class CostTracker:
    INPUT_COST = 0.150 / 1_000_000
    OUTPUT_COST = 0.600 / 1_000_000

    def __init__(self):
        self.input_tokens = 0
        self.output_tokens = 0

    def add(self, usage):
        self.input_tokens += getattr(usage, "prompt_tokens", 0)
        self.output_tokens += getattr(usage, "completion_tokens", 0)

    @property
    def cost(self) -> float:
        return self.input_tokens * self.INPUT_COST + self.output_tokens * self.OUTPUT_COST

    def report(self):
        log.info(f"[COST] {self.input_tokens:,} in + {self.output_tokens:,} out = ${self.cost:.4f}")


cost_tracker = CostTracker()


# ── LLM CLASSIFICATION (mirrors reddit_scraper_sg.py's shape) ────────

def _llm_classify_batch(texts: List[str], client: OpenAI) -> List[dict]:
    """Batch sentiment + purchase-barrier + on-topic classification for
    Facebook comments left on brand Page posts -- same prompt shape as
    the YouTube/Reddit modules' comment classifiers."""
    if not texts:
        return []
    fallback = {"sentiment": "neutral", "is_purchase_barrier_signal": False, "is_lens_relevant": True}
    numbered = "\n".join(f"{i + 1}. {t}" for i, t in enumerate(texts))
    prompt = f"""Classify these {len(texts)} Facebook comments left on contact-lens brand Page posts.
For each comment, return an object with:
- "i": the comment's number as shown below (integer)
- "sentiment": one of "positive", "negative", "neutral", "mixed"
- "is_purchase_barrier_signal": true if the comment expresses a reason for not buying/switching/registering (price, availability, discomfort/irritation, trust, prescription hassle, counterfeit concern, etc.), else false
- "is_lens_relevant": true if the comment is actually about the contact-lens product/brand, false if it's off-topic chatter (a generic emoji reaction, unrelated complaint, spam/giveaway-bait)

Return ONLY a JSON array of objects, one per comment, no other text.

Comments:
{numbered}"""
    by_index: Dict[int, dict] = {}
    try:
        resp = client.chat.completions.create(
            model="gpt-4o-mini",
            messages=[{"role": "user", "content": prompt}],
            max_tokens=3000,
        )
        cost_tracker.add(resp.usage)
        raw = resp.choices[0].message.content.strip()
        raw = re.sub(r"^```(?:json)?\s*|\s*```$", "", raw, flags=re.MULTILINE).strip()
        parsed = json.loads(raw)
        if isinstance(parsed, list):
            for p in parsed:
                idx = p.get("i")
                if isinstance(idx, int) and 1 <= idx <= len(texts):
                    by_index[idx] = {
                        "sentiment": str(p.get("sentiment", "neutral")),
                        "is_purchase_barrier_signal": bool(p.get("is_purchase_barrier_signal", False)),
                        "is_lens_relevant": bool(p.get("is_lens_relevant", True)),
                    }
        if len(by_index) != len(texts):
            log.warning(f"[LLM] Classify batch: expected {len(texts)}, got {len(by_index)} indexed")
    except Exception as e:
        log.warning(f"[LLM] Classify batch failed: {e}")

    return [by_index.get(i + 1, fallback) for i in range(len(texts))]


# ── APIFY CALLS ────────────────────────────────────────────────────────
# run_actor() is identical to every other Apify script in this repo --
# same start/poll/fetch-dataset pattern.

def run_actor(token: str, actor_id: str, run_input: dict, label: str, max_wait_attempts: int = 60) -> List[dict]:
    """Start an Apify actor run, poll until terminal, return dataset items."""
    actor_slug = actor_id.replace("/", "~")
    r = requests.post(
        f"{APIFY_BASE}/acts/{actor_slug}/runs",
        json=run_input,
        params={"token": token},
        timeout=30,
    )
    if not r.ok:
        log.error(f"[{label}] start failed {r.status_code}: {r.text[:800]}")
    r.raise_for_status()
    data = r.json()["data"]
    run_id, dataset_id = data["id"], data["defaultDatasetId"]
    log.info(f"[{label}] run started run_id={run_id}")

    status_url = f"{APIFY_BASE}/actor-runs/{run_id}"
    final = None
    for attempt in range(max_wait_attempts):
        time.sleep(10)
        final = requests.get(status_url, params={"token": token}, timeout=15).json()["data"]
        log.info(f"[{label}] status={final['status']}  (attempt {attempt + 1})")
        if final["status"] == "SUCCEEDED":
            break
        if final["status"] in ("FAILED", "ABORTED", "TIMED-OUT"):
            log.error(f"[{label}] ended with {final['status']}: {final.get('statusMessage', '')}")
            break
    else:
        raise TimeoutError(f"[{label}] run {run_id} did not finish in time")

    items_r = requests.get(
        f"{APIFY_BASE}/datasets/{dataset_id}/items",
        params={"token": token, "format": "json"},
        timeout=60,
    )
    items_r.raise_for_status()
    items = items_r.json()

    cost = final.get("usageTotalUsd") if final else None
    log.info(f"[{label}] retrieved {len(items)} items | cost: {cost}")
    return items


def build_posts_input(page: str, max_posts: int) -> dict:
    """Confirmed live 2026-09-25 against apify/facebook-posts-scraper --
    see header note."""
    return {
        "startUrls": [{"url": f"https://www.facebook.com/{page}"}],
        "resultsLimit": max_posts,
    }


def build_comments_input(post_url: str, max_comments: int) -> dict:
    """Confirmed live 2026-09-25 against apify/facebook-comments-scraper
    -- see header note. `post_url` must be a post's topLevelUrl, not its
    share-link `url` (untested against the latter)."""
    return {
        "startUrls": [{"url": post_url}],
        "resultsLimit": max_comments,
    }


def discover_posts(page: str, token: str, actor_id: str, max_posts: int) -> List[dict]:
    run_input = build_posts_input(page, max_posts)
    return run_actor(token, actor_id, run_input, f"posts:{page}")


def fetch_comments_for_post(post_url: str, token: str, actor_id: str, max_comments: int) -> List[dict]:
    run_input = build_comments_input(post_url, max_comments)
    return run_actor(token, actor_id, run_input, f"comments:{post_url}")


# ── FIELD EXTRACTION (normalizes raw actor items -- adjust to match
#    the actor's real field names once confirmed) ─────────────────────

def _pick(d: dict, *keys, default=None):
    """Fallback-key helper for unverified actor output schemas -- same
    utility every Apify script in this repo reimplements independently
    per first_scripts_summary.md's cross-cutting findings."""
    for k in keys:
        if k in d and d[k] not in (None, ""):
            return d[k]
    return default


def extract_post_fields(raw: dict, brand: str, market: str, page: str) -> Optional[dict]:
    post_id = _pick(raw, "postId", "id", "post_id")
    if not post_id:
        return None
    text = _pick(raw, "text", "message", "caption", default="")
    now = datetime.now(timezone.utc).isoformat()
    return {
        "post_id":         str(post_id),
        "brand":           brand,
        "market":          market,
        "page":            page,
        "text":            text,
        "likes_count":     _pick(raw, "likes", "likesCount", "reactionsCount", default=0),
        # Confirmed live 2026-09-25: apify/facebook-posts-scraper does NOT
        # return a comments-count field at all (checked real payload keys
        # for acuvuesg) -- left NULL (unknown) rather than defaulting to 0,
        # which would falsely claim zero comments. If a paid actor tier or
        # different actor exposes it, wire the real key name in here.
        "comments_count":  _pick(raw, "comments", "commentsCount", default=None),
        "shares_count":    _pick(raw, "shares", "sharesCount", default=0),
        "published_at":    _pick(raw, "time", "date", "timestamp", default=""),
        "url":             _pick(raw, "topLevelUrl", "url", "postUrl", default=""),
        "discovered_at":   now,
        "is_lens_relevant": int(_is_lens_relevant(text)),
    }


def extract_comment_fields(raw: dict, post_id: str, brand: str, market: str) -> Optional[dict]:
    # Confirmed live 2026-09-25 against a real coopervisionsg comment:
    # apify/facebook-comments-scraper's error rows (e.g. {"error":
    # "no_items", ...} for a post with zero comments) have no "text" key,
    # so this already falls through to the `if not text: return None`
    # guard below -- no separate error check needed.
    text = _pick(raw, "text", "message", "commentText", default="")
    if not text:
        return None
    # `profileName` is the flat display name; `author` is a nested dict
    # (author.name) on this actor -- prefer the flat field, only reach
    # into the nested one as a fallback.
    author = _pick(raw, "profileName", default="") or (raw.get("author") or {}).get("name", "")
    comment_id = _pick(raw, "commentId", "id", default="")
    raw_key = f"{post_id}|{comment_id}|{text[:80]}"
    content_hash = hashlib.md5(raw_key.encode()).hexdigest()
    return {
        "post_id":       post_id,
        "brand":         brand,
        "market":        market,
        "author":        author,
        "comment_text":  text,
        "like_count":    _pick(raw, "likesCount", "likes", default=0),
        "published_at":  _pick(raw, "date", "time", "timestamp", default=""),
        "content_hash":  content_hash,
        "scraped_at":    datetime.now(timezone.utc).isoformat(),
    }


# ── SAVE HELPERS ─────────────────────────────────────────────────────

def save_posts(conn: sqlite3.Connection, posts: List[dict]) -> int:
    inserted = 0
    for p in posts:
        try:
            cur = conn.execute(
                """INSERT OR IGNORE INTO fb_posts
                   (post_id, brand, market, page, text, likes_count, comments_count,
                    shares_count, published_at, url, discovered_at, is_lens_relevant)
                   VALUES (?,?,?,?,?,?,?,?,?,?,?,?)""",
                (
                    p["post_id"], p["brand"], p["market"], p["page"], p["text"],
                    p["likes_count"], p["comments_count"], p["shares_count"],
                    p["published_at"], p["url"], p["discovered_at"], p["is_lens_relevant"],
                ),
            )
            if cur.rowcount == 1:
                inserted += 1
        except Exception as e:
            log.warning(f"[DB] Post insert error: {e}")
    conn.commit()
    return inserted


def save_comments(conn: sqlite3.Connection, comments: List[dict]) -> int:
    inserted = 0
    for c in comments:
        try:
            cur = conn.execute(
                """INSERT OR IGNORE INTO fb_comments
                   (post_id, brand, market, author, comment_text, like_count, published_at,
                    content_hash, scraped_at, sentiment, is_purchase_barrier_signal, is_lens_relevant)
                   VALUES (?,?,?,?,?,?,?,?,?,?,?,?)""",
                (
                    c["post_id"], c["brand"], c["market"], c["author"], c["comment_text"],
                    c["like_count"], c["published_at"], c["content_hash"], c["scraped_at"],
                    c.get("sentiment"), int(c.get("is_purchase_barrier_signal", False)),
                    int(c.get("is_lens_relevant", True)),
                ),
            )
            if cur.rowcount == 1:
                inserted += 1
        except Exception as e:
            log.warning(f"[DB] Comment insert error: {e}")
    conn.commit()
    return inserted


# ── CSV EXPORT ────────────────────────────────────────────────────────

def export_csvs(db_path: str, output_dir: str) -> dict:
    conn = open_db(db_path)
    counts = {}
    ts = datetime.now().strftime("%Y%m%d_%H%M")
    exports = {
        f"facebook_sg_posts_{ts}.csv": (
            "SELECT brand, page, text, likes_count, comments_count, shares_count, "
            "published_at, url, is_lens_relevant FROM fb_posts ORDER BY brand, likes_count DESC",
        ),
        f"facebook_sg_comments_{ts}.csv": (
            "SELECT c.brand, c.author, c.comment_text, c.like_count, c.published_at, c.sentiment, "
            "c.is_purchase_barrier_signal, c.is_lens_relevant, p.text AS post_text, p.url "
            "FROM fb_comments c LEFT JOIN fb_posts p ON p.post_id = c.post_id "
            "ORDER BY c.brand, c.published_at DESC",
        ),
    }
    for filename, (query,) in exports.items():
        rows = conn.execute(query).fetchall()
        path = Path(output_dir) / filename
        with open(path, "w", newline="", encoding="utf-8-sig") as f:
            writer = csv.writer(f)
            if rows:
                writer.writerow(rows[0].keys())
                for row in rows:
                    writer.writerow(tuple(row))
        counts[filename] = len(rows)
        log.info(f"[EXPORT] {filename}: {len(rows)} rows")
    conn.close()
    return counts


# ── CLASSIFY-EXISTING BACKFILL ────────────────────────────────────────

def classify_existing(db_path: str) -> int:
    """Backfill sentiment/is_purchase_barrier_signal for comments missing
    it. Safe to re-run."""
    client = OpenAI()
    conn = open_db(db_path)
    rows = conn.execute(
        "SELECT id, comment_text FROM fb_comments WHERE sentiment IS NULL"
    ).fetchall()
    log.info(f"[CLASSIFY] {len(rows)} comments missing classification")

    classified = 0
    for start in range(0, len(rows), CLASSIFY_BATCH_SIZE):
        batch = rows[start:start + CLASSIFY_BATCH_SIZE]
        labels = _llm_classify_batch([r["comment_text"] for r in batch], client)
        for row, label in zip(batch, labels):
            conn.execute(
                """UPDATE fb_comments
                   SET sentiment = ?, is_purchase_barrier_signal = ?, is_lens_relevant = ?
                   WHERE id = ?""",
                (
                    label["sentiment"], int(label["is_purchase_barrier_signal"]),
                    int(label["is_lens_relevant"]), row["id"],
                ),
            )
            classified += 1
        conn.commit()
        log.info(f"[CLASSIFY] {classified}/{len(rows)} done")

    conn.close()
    cost_tracker.report()
    log.info(f"[CLASSIFY] Done — {classified} comments classified")
    return classified


# ── MAIN ORCHESTRATOR ─────────────────────────────────────────────────

def run(
    markets: List[str],
    brand_filter: Optional[List[str]],
    max_posts: int,
    max_comments: int,
    skip_comments: bool,
    dry_run: bool,
    force_rescrape: bool,
    posts_actor: str,
    comments_actor: str,
    db_path: str,
    output_dir: str,
    max_posts_with_comments: Optional[int] = None,
) -> None:
    token = os.getenv("APIFY_TOKEN", "").strip()
    if not token:
        log.error("[SETUP] APIFY_TOKEN not found in .env")
        raise SystemExit(1)

    client = OpenAI()
    conn = None if dry_run else open_db(db_path)
    scraped_source_keys: set = set()
    if conn and not force_rescrape:
        scraped_source_keys = get_scraped_source_keys(conn)
        if scraped_source_keys:
            log.info(f"[DISCOVER] {len(scraped_source_keys)} page(s) already scraped before -- "
                     f"skipping (use --force-rescrape to re-pull)")

    total_posts = 0
    total_comments = 0

    for market in markets:
        brands = list(PAGES.get(market, {}))
        for brand in brands:
            if brand_filter and brand.lower() not in [b.lower() for b in brand_filter]:
                continue

            pages = PAGES[market][brand]
            if not pages:
                log.info(f"[DISCOVER] Facebook | {brand}/{market}: no Page configured -- skipping")
                continue

            all_raw_posts: List[dict] = []
            for page in pages:
                source_key = (brand, market, page)
                if source_key in scraped_source_keys:
                    continue
                log.info(f"[DISCOVER] Facebook | {brand} | {market} | page:{page}")
                try:
                    raw = discover_posts(page, token, posts_actor, max_posts)
                except Exception as e:
                    log.error(f"[DISCOVER] Facebook | {brand} | {page}: {e}")
                    raw = []
                for r in raw:
                    all_raw_posts.append((r, page))
                if conn:
                    mark_source_scraped(conn, brand, market, page, len(raw))
                time.sleep(1.0)

            if dry_run:
                sample = all_raw_posts[0][0] if all_raw_posts else None
                log.info(f"[DRY-RUN] Facebook | {brand}: {len(all_raw_posts)} raw post(s) discovered, "
                         f"sample: {json.dumps(sample, default=str)[:500] if sample else '(none)'}")
                continue

            posts_by_id: Dict[str, dict] = {}
            for raw, page in all_raw_posts:
                p = extract_post_fields(raw, brand, market, page)
                if p and p["post_id"] not in posts_by_id:
                    posts_by_id[p["post_id"]] = p
            posts = list(posts_by_id.values())
            if not posts:
                log.info(f"[DISCOVER] Facebook | {brand}: 0 posts found this run")
                continue

            n_new = save_posts(conn, posts)
            total_posts += n_new
            log.info(f"[DISCOVER] Facebook | {brand}: {n_new} new posts saved ({len(posts)} discovered)")

            if skip_comments:
                continue

            # Comments cost one separate paid actor run per post, so
            # max_posts_with_comments caps total spend/time on a smoke
            # test regardless of how many posts turned up.
            posts_for_comments = posts
            if max_posts_with_comments is not None:
                posts_for_comments = posts_for_comments[:max_posts_with_comments]
            log.info(f"[COMMENTS] Facebook | {brand}: fetching comments for {len(posts_for_comments)} post(s)")
            for p in posts_for_comments:
                if not p["url"]:
                    continue
                try:
                    raw_comments = fetch_comments_for_post(p["url"], token, comments_actor, max_comments)
                except Exception as e:
                    log.error(f"[COMMENTS] Facebook | {brand} | {p['post_id']}: {e}")
                    continue
                comments = []
                for rc in raw_comments:
                    c = extract_comment_fields(rc, p["post_id"], brand, market)
                    if c:
                        comments.append(c)
                if not comments:
                    continue
                for start in range(0, len(comments), CLASSIFY_BATCH_SIZE):
                    batch = comments[start:start + CLASSIFY_BATCH_SIZE]
                    results = _llm_classify_batch([c["comment_text"] for c in batch], client)
                    for c, res in zip(batch, results):
                        c.update(res)
                    n_new_c = save_comments(conn, batch)
                    total_comments += n_new_c
                time.sleep(0.5)

    if conn:
        conn.close()

    if not dry_run:
        Path(output_dir).mkdir(parents=True, exist_ok=True)
        counts = export_csvs(db_path, output_dir)
        log.info(f"[EXPORT] {counts}")

    cost_tracker.report()
    log.info(f"\nDone. {total_posts} new posts, {total_comments} new comments saved.")


# ── CLI ────────────────────────────────────────────────────────────────

if __name__ == "__main__":
    parser = argparse.ArgumentParser(description="Facebook Social-Listening Module — MyACUVUE Singapore")
    parser.add_argument("--market", nargs="+", default=["SG"])
    parser.add_argument("--brand", nargs="+", help='e.g. --brand "MyACUVUE" "CooperVision"')
    parser.add_argument("--max-posts", type=int, default=30, help="Per-Page post cap")
    parser.add_argument("--max-comments", type=int, default=100, help="Per-post comment cap")
    parser.add_argument("--skip-comments", action="store_true", help="Discovery only, no comment fetch/classify")
    parser.add_argument("--dry-run", action="store_true", help="Discover only, print a sample, save nothing")
    parser.add_argument("--force-rescrape", action="store_true", help="Ignore fb_scraped_sources cache")
    parser.add_argument("--posts-actor", default=POSTS_ACTOR, help="Override the Apify actor slug")
    parser.add_argument("--comments-actor", default=COMMENTS_ACTOR, help="Override the Apify actor slug")
    parser.add_argument("--max-posts-with-comments", type=int, default=None,
                         help="Cap how many posts get a (paid, per-post) comments fetch -- for smoke-testing")
    parser.add_argument("--db", default="output/facebook_data_sg.db")
    parser.add_argument("--output-dir", default="output")
    parser.add_argument("--export-csv", action="store_true", help="Skip scraping; just export current DB to CSV")
    parser.add_argument("--classify-existing", action="store_true",
                         help="Backfill sentiment/purchase-barrier labels for already-saved comments, then exit")
    parser.add_argument("--debug", action="store_true")
    args = parser.parse_args()

    if args.debug:
        log.setLevel(logging.DEBUG)

    if args.export_csv:
        counts = export_csvs(args.db, args.output_dir)
        log.info(f"[EXPORT] CSV export complete: {counts}")
        raise SystemExit(0)

    if args.classify_existing:
        classify_existing(args.db)
        raise SystemExit(0)

    run(
        markets=args.market,
        brand_filter=args.brand,
        max_posts=args.max_posts,
        max_comments=args.max_comments,
        skip_comments=args.skip_comments,
        dry_run=args.dry_run,
        force_rescrape=args.force_rescrape,
        posts_actor=args.posts_actor,
        comments_actor=args.comments_actor,
        db_path=args.db,
        output_dir=args.output_dir,
        max_posts_with_comments=args.max_posts_with_comments,
    )
