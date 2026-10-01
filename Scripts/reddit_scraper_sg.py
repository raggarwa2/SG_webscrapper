# ==================================================================
# Reddit Social-Listening Module — MyACUVUE Singapore (standalone)
# ==================================================================
# Purpose:
#   Add Reddit as a consumer-feedback source for the MyACUVUE/J&J
#   Vision Singapore engagement (context.md — Awareness/Consideration
#   journey stages; scripts.md's own scrapability table flags this as
#   "fragmented ... lower signal density than a single dominant forum").
#
# WHY THIS ISN'T A STRAIGHT PORT OF pipeline_th.py's Pantip FUNCTIONS:
#   Pantip is one dominant TH forum with its own direct HTTP search
#   endpoint (discover_pantip()) and a per-thread comments endpoint
#   (discover_pantip_deep()) that plain `requests` can hit with no
#   auth. Reddit has no Singapore-specific equivalent of "one dominant
#   site" (per scripts.md/day_1_plan.md, confirmed at TH->SG porting
#   time) -- discussion is scattered across r/singapore and a handful
#   of niche subs, so this module searches a curated SUBREDDITS list
#   below instead of one site.
#   Also, Reddit's own public/unauthenticated JSON endpoints
#   (reddit.com/search.json, reddit.com/comments/{id}.json) are
#   real and don't need OAuth for reading, BUT Reddit has tightened
#   anti-bot enforcement on datacenter/cloud IPs since 2023 -- plain
#   `requests` from a cloud box can get soft-blocked even with a good
#   User-Agent where Pantip's plain-HTTP approach never was. Per this
#   project's established pattern (every other social-listening module
#   -- Instagram, TikTok, XHS -- goes through an Apify actor, not raw
#   HTTP, for exactly this reason), this module goes through Apify
#   too. NOT YET LIVE-VERIFIED against the actual actor input schema --
#   see the "UNVERIFIED" flags below. Run --dry-run first and fix any
#   field-name mismatches against the actor's real Input tab on Apify
#   Console before trusting a full run, the same way Pantip's HTML
#   selectors and the TikTok SG actor's field names both needed a real
#   test pass before this project trusted them (see day_1_plan.md
#   Phase 1 notes on tiktok_pipeline_sg.py's real bugs found live).
#
# Status: STANDALONE MODULE -- own SQLite db (reddit_data_sg.db).
#   NOT wired into any pipeline. Review sample output first; merge
#   into any downstream analysis is a separate, explicit step.
#
# IMPORTANT -- project separation:
#   Keep this file and its outputs in THIS project only -- do not
#   point it at the Thailand (acne-aid) or Hong Kong (xhs) project's
#   DB/output folders, and do not import data from them. External-only
#   data, Singapore market only (per context.md's scope boundary).
#
# Competitive set (per context.md): MyACUVUE vs Alcon (Air Optix,
# Dailies, Total30), CooperVision, Bausch & Lomb, Olens.
#
# Actor choice (UNVERIFIED -- confirm before a paid run):
#   POSTS_ACTOR default is "trudax/reddit-scraper-lite", a commonly
#   used community actor that supports keyword search + subreddit
#   scoping and returns posts (title/selftext/score/permalink/etc).
#   Its exact input field names are NOT independently confirmed here
#   the way e.g. the TikTok SG actor's `min_price`/`avg_price` fields
#   were confirmed live in day_1_plan.md -- check the actor's Input
#   tab on Apify Console and adjust build_search_input()/
#   build_thread_input() below if it rejects the input or returns
#   unexpected fields. Override via --posts-actor if you pick a
#   different one.
#
# Cost model: unconfirmed for this actor -- run a small --dry-run
#   (--max-posts 10, one brand) first and check the reported
#   usageTotalUsd in the log line before committing to a full run,
#   same verification habit as every other Apify script in this repo.
#
# Setup required: APIFY_TOKEN and OPENAI_API_KEY in .env for this
#   project (already populated per day_1_plan.md Phase 0).
#
# Usage:
#   python reddit_scraper_sg.py --dry-run
#   python reddit_scraper_sg.py --brand "MyACUVUE" --market SG
#   python reddit_scraper_sg.py --max-posts 50
#   python reddit_scraper_sg.py --skip-comments
#   python reddit_scraper_sg.py --classify-existing
#   python reddit_scraper_sg.py --export-csv
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

# UNVERIFIED -- see header note. Override with --posts-actor if this
# actor slug is wrong or you prefer a different one from the store.
POSTS_ACTOR = "trudax/reddit-scraper-lite"


# ── CONFIG: brand search keywords per market ─────────────────────────
# Same brand set as youtube_scraper_sg.py/instagram's SG builds, kept
# in sync deliberately. "Singapore"/"SG" qualifier appended for terms
# used in sitewide (non-subreddit-scoped) search, same reasoning as
# the YouTube module: bare global-brand names would otherwise pull in
# huge non-SG volume. Not needed for subreddit-scoped searches, since
# SUBREDDITS below already geo-scopes those.

BRAND_KEYWORDS = {
    "SG": {
        "MyACUVUE":        ["Acuvue", "MyACUVUE"],
        "Alcon":           ["Alcon contact lens", "Air Optix", "Dailies Total30"],
        "CooperVision":    ["CooperVision", "Biofinity"],
        "Bausch + Lomb":   ["Bausch Lomb contact lens", "Biotrue"],
        "Olens":           ["Olens", "O-Lens"],
    },
}

# Literal brand-name aliases -- used only as a deterministic pre-check
# in check_brand_relevance() so the unambiguous case (title/selftext
# literally names the brand) never depends on an LLM call-to-call
# judgment. Kept identical to youtube_scraper_sg.py's BRAND_ALIASES.
BRAND_ALIASES = {
    "MyACUVUE":      ["acuvue", "myacuvue", "acuvue oasys", "acuvue moist"],
    "Alcon":         ["alcon", "air optix", "dailies total30", "dailies", "freshlook"],
    "CooperVision":  ["coopervision", "biofinity", "clariti", "myday", "avaira"],
    "Bausch + Lomb": ["bausch lomb", "bausch + lomb", "bausch & lomb", "biotrue", "ultra contact"],
    "Olens":         ["olens", "o-lens"],
}

# ── CONFIG: subreddits to search (fragmented-forum workaround) ───────
# Starting list only -- NOT empirically validated for real SG contact-
# lens discussion volume yet (unlike Pantip, which had a single
# confirmed-live search endpoint to test against). Per this project's
# own verification habit (see day_1_plan.md's "small test slice"
# approach), run --dry-run against this list first, inspect actual
# hit volume per subreddit, and prune/extend before a full run.
# r/singapore is the general-purpose catch-all; the rest are
# topic-adjacent bets, not confirmed active communities.
SUBREDDITS = [
    "singapore",
    "SingaporeRaw",
    "asksingapore",
    "contactlenses",
    "Optometry",
    "eyecare",
]

CLASSIFY_BATCH_SIZE = 20
BRAND_RELEVANCE_BATCH_SIZE = 20


# ── DB SCHEMA (separate db -- reddit_data_sg.db) ──────────────────────

SCHEMA = """
CREATE TABLE IF NOT EXISTS reddit_posts (
    post_id          TEXT PRIMARY KEY,
    brand            TEXT NOT NULL,
    market           TEXT NOT NULL,
    subreddit        TEXT,
    search_keyword   TEXT,
    title            TEXT,
    selftext         TEXT,
    author           TEXT,
    score            INTEGER,
    num_comments     INTEGER,
    created_utc      TEXT,
    permalink        TEXT,
    discovered_at    TEXT,
    is_lens_relevant INTEGER,
    brand_relevant   INTEGER
);

CREATE TABLE IF NOT EXISTS reddit_comments (
    id                         INTEGER PRIMARY KEY AUTOINCREMENT,
    post_id                    TEXT NOT NULL,
    brand                      TEXT NOT NULL,
    market                     TEXT NOT NULL,
    author                     TEXT,
    comment_text               TEXT,
    score                      INTEGER,
    created_utc                TEXT,
    content_hash               TEXT UNIQUE,
    scraped_at                 TEXT,
    sentiment                  TEXT,
    is_purchase_barrier_signal INTEGER,
    is_lens_relevant           INTEGER,
    FOREIGN KEY(post_id) REFERENCES reddit_posts(post_id)
);

-- Tracks which (brand, source) combos have already had a paid Apify
-- run made for them, so re-running the script doesn't re-spend
-- credits on the same keyword/subreddit pull every time. A source
-- stays "done" until --force-rescrape is passed. Same pattern as
-- yt_scraped_sources in youtube_scraper_sg.py.
CREATE TABLE IF NOT EXISTS reddit_scraped_sources (
    brand           TEXT NOT NULL,
    market          TEXT NOT NULL,
    source_type     TEXT NOT NULL,   -- 'keyword' | 'subreddit'
    source_value    TEXT NOT NULL,
    last_scraped_at TEXT NOT NULL,
    items_found     INTEGER,
    PRIMARY KEY (brand, market, source_type, source_value)
);

CREATE INDEX IF NOT EXISTS idx_reddit_posts_brand    ON reddit_posts(brand);
CREATE INDEX IF NOT EXISTS idx_reddit_comments_brand ON reddit_comments(brand);
CREATE INDEX IF NOT EXISTS idx_reddit_comments_post  ON reddit_comments(post_id);
"""


def open_db(path: str) -> sqlite3.Connection:
    Path(path).parent.mkdir(parents=True, exist_ok=True)
    conn = sqlite3.connect(path, timeout=60)
    conn.row_factory = sqlite3.Row
    conn.execute("PRAGMA journal_mode=WAL")
    conn.executescript(SCHEMA)
    conn.commit()
    return conn


def get_scraped_source_keys(conn: sqlite3.Connection) -> set:
    return {
        (row["brand"], row["market"], row["source_type"], row["source_value"])
        for row in conn.execute("SELECT brand, market, source_type, source_value FROM reddit_scraped_sources")
    }


def mark_source_scraped(conn: sqlite3.Connection, brand: str, market: str, source_type: str, source_value: str, items_found: int) -> None:
    conn.execute(
        """INSERT INTO reddit_scraped_sources (brand, market, source_type, source_value, last_scraped_at, items_found)
           VALUES (?, ?, ?, ?, ?, ?)
           ON CONFLICT(brand, market, source_type, source_value)
           DO UPDATE SET last_scraped_at = excluded.last_scraped_at, items_found = excluded.items_found""",
        (brand, market, source_type, source_value, datetime.now(timezone.utc).isoformat(), items_found),
    )
    conn.commit()


# ── LENS/EYE-CARE-RELEVANCE WHITELIST (regex, no LLM cost) ───────────
# Identical term list to youtube_scraper_sg.py -- whitelist-not-
# blacklist: flags (does NOT drop) posts/comments with no explicit
# lens/eye-care term, so low-volume data isn't silently thrown away.

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


def _normalize_for_alias_match(s: str) -> str:
    """Strips spaces, hyphens, apostrophes, underscores before alias
    matching -- same fix as youtube_scraper_sg.py, needed so a hashtag-
    style mention (e.g. "#AcuvueSG" in a title) still matches a
    multi-word alias."""
    return re.sub(r"[\s\-'_]", "", s or "").lower()


# ── COST TRACKER (same model/rates as pipeline_th.py) ─────────────────

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


# ── LLM CLASSIFICATION (mirrors youtube_scraper_sg.py's shape) ────────

def _llm_classify_batch(texts_en: List[str], client: OpenAI) -> List[dict]:
    """Batch sentiment + purchase-barrier + on-topic classification for
    Reddit comments -- same prompt shape as the YouTube module's
    comment classifier."""
    if not texts_en:
        return []
    fallback = {"sentiment": "neutral", "is_purchase_barrier_signal": False, "is_lens_relevant": True}
    numbered = "\n".join(f"{i + 1}. {t}" for i, t in enumerate(texts_en))
    prompt = f"""Classify these {len(texts_en)} Reddit comments left on threads about contact-lens brands.
For each comment, return an object with:
- "i": the comment's number as shown below (integer)
- "sentiment": one of "positive", "negative", "neutral", "mixed"
- "is_purchase_barrier_signal": true if the comment expresses a reason for not buying/switching/registering (price, availability, discomfort/irritation, trust, prescription hassle, counterfeit concern, etc.), else false
- "is_lens_relevant": true if the comment is actually about the contact-lens product/brand, false if it's off-topic chatter/unrelated to lenses

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
                if isinstance(idx, int) and 1 <= idx <= len(texts_en):
                    by_index[idx] = {
                        "sentiment": str(p.get("sentiment", "neutral")),
                        "is_purchase_barrier_signal": bool(p.get("is_purchase_barrier_signal", False)),
                        "is_lens_relevant": bool(p.get("is_lens_relevant", True)),
                    }
        if len(by_index) != len(texts_en):
            log.warning(f"[LLM] Classify batch: expected {len(texts_en)}, got {len(by_index)} indexed")
    except Exception as e:
        log.warning(f"[LLM] Classify batch failed: {e}")

    return [by_index.get(i + 1, fallback) for i in range(len(texts_en))]


def _llm_brand_relevance_batch(items: List[dict], client: OpenAI) -> List[bool]:
    """True if a post is actually about the brand it was tagged with at
    discovery, not just generic lens/eye-care content -- same
    reasoning/prompt shape as youtube_scraper_sg.py's video-level
    check, applied to Reddit post title+selftext instead. Fails open
    (True) on parse errors/drops."""
    if not items:
        return []
    numbered = "\n".join(
        f"{i + 1}. Brand: {it['brand']} | Subreddit: r/{it['subreddit']} | Title: {it['title'][:150]} | Body: {it['selftext'][:150]}"
        for i, it in enumerate(items)
    )
    prompt = f"""Each of these {len(items)} Reddit posts was surfaced by a keyword search for the
stated brand's contact-lens products. General "best contact lenses" threads often mention many
brands regardless of which brand the search was aimed at -- your job is to check the post is
genuinely about the STATED brand's product, not just incidentally mentioning it.

Mark "is_brand_relevant": true if EITHER:
(a) the post is a dedicated review/question/experience about that brand's product, OR
(b) the brand is a substantial, named focus of the post (not a one-line mention in a long list).

Mark false if the post is clearly about a DIFFERENT brand's product, or is a generic eye-care post
where the stated brand only appears in passing.

When genuinely unsure, default to true -- this check exists to catch clear mismatches, not to
second-guess borderline cases.

For each post, return an object with:
- "i": the post's number as shown below (integer)
- "is_brand_relevant": true/false

Return ONLY a JSON array of objects, one per post, no other text.

Posts:
{numbered}"""
    by_index: Dict[int, bool] = {}
    try:
        resp = client.chat.completions.create(
            model="gpt-4o-mini",
            messages=[{"role": "user", "content": prompt}],
            max_tokens=2000,
        )
        cost_tracker.add(resp.usage)
        raw = resp.choices[0].message.content.strip()
        raw = re.sub(r"^```(?:json)?\s*|\s*```$", "", raw, flags=re.MULTILINE).strip()
        parsed = json.loads(raw)
        if isinstance(parsed, list):
            for p in parsed:
                idx = p.get("i")
                if isinstance(idx, int) and 1 <= idx <= len(items):
                    by_index[idx] = bool(p.get("is_brand_relevant", True))
        if len(by_index) != len(items):
            log.warning(f"[LLM] Brand relevance batch: expected {len(items)}, got {len(by_index)} indexed")
    except Exception as e:
        log.warning(f"[LLM] Brand relevance batch failed: {e}")

    return [by_index.get(i + 1, True) for i in range(len(items))]


def check_brand_relevance(items: List[dict], client: OpenAI) -> List[bool]:
    """Deterministic alias pre-check first (no LLM cost for the
    unambiguous case), same pattern as youtube_scraper_sg.py."""
    if not items:
        return []
    results: List[Optional[bool]] = [None] * len(items)
    needs_llm_idxs = []
    for i, it in enumerate(items):
        aliases = BRAND_ALIASES.get(it["brand"], [it["brand"].lower()])
        haystack = _normalize_for_alias_match(f"{it['title']} {it['selftext']} r/{it['subreddit']}")
        if any(_normalize_for_alias_match(alias) in haystack for alias in aliases):
            results[i] = True
        else:
            needs_llm_idxs.append(i)

    if needs_llm_idxs:
        llm_results = _llm_brand_relevance_batch([items[i] for i in needs_llm_idxs], client)
        for i, r in zip(needs_llm_idxs, llm_results):
            results[i] = r

    return results


# ── APIFY CALLS ────────────────────────────────────────────────────────
# run_actor() is identical to instagram_scraper_th.py's helper -- same
# start/poll/fetch-dataset pattern used by every Apify script in this
# repo.

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


def build_search_input(keyword: str, subreddit: Optional[str], max_posts: int) -> dict:
    """FIXED 2026-09-24, twice:

    1. (first fix) The original version set BOTH `startUrls` (pointed at
       a bare subreddit URL) and `searches` in the same call. Confirmed
       result: the actor ignored `searches` entirely and returned the
       subreddit's own info card (dataType "community") instead of any
       Acuvue-related post -- 8 calls, ~$0.36, zero real signal.

    2. (this fix) The `subreddit:<name>` text-operator workaround from
       fix #1 turned out to be unnecessary and unreliable -- pulled the
       actor's REAL input schema for free via
       GET /v2/actor-builds/{buildId} (no run cost) instead of guessing
       further, and it has a dedicated `searchCommunityName` field for
       exactly this. Also confirmed `"type"` was never a real field on
       this actor at all -- silently ignored the whole time, in both the
       posts and comments calls. searchCommunities/searchComments/
       searchUsers/searchMedia are explicitly disabled so a bare-word
       query doesn't pull back non-post cards."""
    run_input = {
        "searches": [keyword],
        "searchPosts": True,
        "searchComments": False,
        "searchCommunities": False,
        "searchUsers": False,
        "searchMedia": False,
        "sort": "relevance",
        "maxItems": max_posts,
        "maxPostCount": max_posts,
    }
    if subreddit:
        run_input["searchCommunityName"] = subreddit
    return run_input


def build_thread_input(permalink: str, max_comments: int) -> dict:
    """FIXED 2026-09-24: confirmed via the actor's real input schema
    (see build_search_input()'s fix note) that comments come from
    pointing `startUrls` at the post's own URL with `maxComments` set --
    there is no separate "comments mode"; the old `"type": "comments"`
    field was silently ignored. `skipCommunity: True` avoids spending
    `maxItems` slots on community-info scraping we don't need here (we
    already have the post's metadata from discovery).

    STILL UNVERIFIED end-to-end: a live test against a real 18-comment
    thread with this exact `startUrls`+`maxItems` shape (before this
    fix, before `searchCommunityName` was known) returned 0 items even
    though the request was well-formed -- possibly the free/no-proxy
    "Lite" tier of this actor being soft-blocked by Reddit intermittently
    (its own schema notes proxy settings are "ignored on the Lite
    version"). Rerun this specific call after the fix and check for a
    real comment payload before trusting it; if it's still empty on a
    known-active thread, the Lite tier's reliability -- not the input
    shape -- is the likely culprit, and the paid `trudax/reddit-scraper`
    (non-lite, with proxy) may be worth switching to."""
    return {
        "startUrls": [{"url": permalink}],
        "skipComments": False,
        "skipCommunity": True,
        "maxComments": max_comments,
        "maxItems": max_comments + 1,
    }


def discover_posts(keyword: str, subreddit: Optional[str], token: str, actor_id: str, max_posts: int) -> List[dict]:
    run_input = build_search_input(keyword, subreddit, max_posts)
    label = f"posts:{subreddit or 'all'}:{keyword}"
    return run_actor(token, actor_id, run_input, label)


def fetch_comments_for_post(permalink: str, token: str, actor_id: str, max_comments: int) -> List[dict]:
    run_input = build_thread_input(permalink, max_comments)
    return run_actor(token, actor_id, run_input, f"comments:{permalink}")


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


# Non-post dataTypes seen or plausible from this actor (community/user/
# comment cards) -- added 2026-09-24 after a live run returned a
# subreddit's own info card instead of posts (see build_search_input()'s
# fix note). Catches a schema regression immediately instead of quietly
# writing garbage rows to the DB.
_NON_POST_DATA_TYPES = {"community", "subreddit", "user", "comment"}


def extract_post_fields(raw: dict, brand: str, market: str, subreddit: Optional[str], keyword: str) -> Optional[dict]:
    data_type = raw.get("dataType")
    if data_type in _NON_POST_DATA_TYPES:
        log.warning(f"[EXTRACT] Skipped a non-post item (dataType={data_type!r}, "
                    f"title={raw.get('title', '')!r}) -- actor returned the wrong result type "
                    f"for this query, see build_search_input()'s fix note.")
        return None
    post_id = _pick(raw, "id", "postId", "post_id")
    if not post_id:
        return None
    now = datetime.now(timezone.utc).isoformat()

    # Confirmed live 2026-09-24 (dry-run against real post results, not
    # the earlier community-card bug): permalink looks like
    # https://www.reddit.com/r/singapore/comments/2aybaw/... -- when the
    # actor doesn't give a `subreddit` field directly (true for sitewide
    # "all" searches, only true per-subreddit searches already know it
    # from the `subreddit` param), pull it out of that URL instead of
    # falling back to an empty string.
    permalink = _pick(raw, "url", "permalink", default="")
    url_subreddit_match = re.search(r"reddit\.com/r/([^/]+)/", permalink)
    subreddit_from_url = url_subreddit_match.group(1) if url_subreddit_match else ""

    return {
        "post_id": str(post_id),
        "brand": brand,
        "market": market,
        "subreddit": _pick(raw, "subreddit", "communityName", default=subreddit or subreddit_from_url),
        "search_keyword": keyword,
        "title": _pick(raw, "title", default=""),
        "selftext": _pick(raw, "selftext", "text", "body", default=""),
        "author": _pick(raw, "author", "username", default=""),
        "score": _pick(raw, "score", "upVotes", default=0),
        # Confirmed live 2026-09-24: actor field is `numberOfComments`,
        # not `numComments`/`num_comments` (both would silently default
        # to 0 without this alias -- caught by inspecting the real
        # sample item, not documentation).
        "num_comments": _pick(raw, "numberOfComments", "numComments", "num_comments", default=0),
        "created_utc": _pick(raw, "createdAt", "created_utc", "date", default=""),
        "permalink": permalink,
        "discovered_at": now,
    }


# Known automated/repost accounts -- added 2026-09-25 after a live test
# (--force-rescrape run against r/singapore) saved `sneakpeek_bot`
# reposting an entire news article as a "comment", and the OP's own
# auto-generated crosspost notice ("submitted by /u/x [link] [comments]")
# getting counted as if it were organic sentiment. Not an exhaustive
# list -- extend as new bot accounts turn up in real runs, same
# whitelist-not-blacklist caution as LENS_RELEVANCE_TERMS_EN (this drops
# rather than flags, since these aren't real user sentiment at all, not
# just borderline-relevant content).
_BOT_AUTHORS = {
    "automoderator", "sneakpeek_bot", "remindmebot", "b0trank",
    "totesmessenger", "wikitextbot", "haikubot-1911", "sub_doesnt_exist",
    "converter-bot", "timezone_bot",
}


def _is_bot_author(author: str) -> bool:
    a = (author or "").strip().lower()
    if not a:
        return False
    if a in _BOT_AUTHORS:
        return True
    return a.endswith("bot") or a.endswith("_bot") or a.startswith("automod")


def extract_comment_fields(raw: dict, post_id: str, brand: str, market: str) -> Optional[dict]:
    author = _pick(raw, "author", "username", default="")
    if _is_bot_author(author):
        return None
    text = _pick(raw, "text", "body", "comment", default="")
    if not text:
        return None
    # OP's own auto-generated crosspost/submission notice -- not organic
    # comment content, e.g. "submitted by /u/x [link] [comments]"
    # (confirmed live 2026-09-25: a real n00bball row in this exact
    # shape, distinct from the bot-author case above since it's posted
    # under the OP's real username, not a bot account).
    if re.match(r"^\s*(&#32;\s*)*submitted by\b", text, re.IGNORECASE):
        return None
    comment_id = _pick(raw, "id", "commentId", default="")
    raw_key = f"{post_id}|{comment_id}|{text[:80]}"
    content_hash = hashlib.md5(raw_key.encode()).hexdigest()
    return {
        "post_id": post_id,
        "brand": brand,
        "market": market,
        "author": _pick(raw, "author", "username", default=""),
        "comment_text": text,
        "score": _pick(raw, "score", "upVotes", default=0),
        "created_utc": _pick(raw, "createdAt", "created_utc", "date", default=""),
        "content_hash": content_hash,
        "scraped_at": datetime.now(timezone.utc).isoformat(),
    }


# ── SAVE HELPERS ─────────────────────────────────────────────────────

def save_posts(conn: sqlite3.Connection, posts: List[dict]) -> int:
    inserted = 0
    for p in posts:
        try:
            cur = conn.execute(
                """INSERT OR IGNORE INTO reddit_posts
                   (post_id, brand, market, subreddit, search_keyword, title, selftext,
                    author, score, num_comments, created_utc, permalink, discovered_at,
                    is_lens_relevant, brand_relevant)
                   VALUES (?,?,?,?,?,?,?,?,?,?,?,?,?,?,?)""",
                (
                    p["post_id"], p["brand"], p["market"], p["subreddit"], p["search_keyword"],
                    p["title"], p["selftext"], p["author"], p["score"], p["num_comments"],
                    p["created_utc"], p["permalink"], p["discovered_at"],
                    int(p.get("is_lens_relevant", False)), int(p.get("brand_relevant", True)),
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
                """INSERT OR IGNORE INTO reddit_comments
                   (post_id, brand, market, author, comment_text, score, created_utc,
                    content_hash, scraped_at, sentiment, is_purchase_barrier_signal, is_lens_relevant)
                   VALUES (?,?,?,?,?,?,?,?,?,?,?,?)""",
                (
                    c["post_id"], c["brand"], c["market"], c["author"], c["comment_text"],
                    c["score"], c["created_utc"], c["content_hash"], c["scraped_at"],
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
        f"reddit_sg_posts_{ts}.csv": (
            "SELECT brand, subreddit, search_keyword, title, selftext, author, score, "
            "num_comments, created_utc, permalink, is_lens_relevant, brand_relevant "
            "FROM reddit_posts ORDER BY brand, score DESC",
        ),
        f"reddit_sg_comments_{ts}.csv": (
            "SELECT c.brand, c.author, c.comment_text, c.score, c.created_utc, c.sentiment, "
            "c.is_purchase_barrier_signal, c.is_lens_relevant, p.title AS post_title, p.permalink "
            "FROM reddit_comments c LEFT JOIN reddit_posts p ON p.post_id = c.post_id "
            "ORDER BY c.brand, c.created_utc DESC",
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
    db_path: str,
    output_dir: str,
    subreddits: Optional[List[str]] = None,
    max_threads_with_comments: Optional[int] = None,
) -> None:
    subreddit_list = subreddits if subreddits is not None else SUBREDDITS
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
            log.info(f"[DISCOVER] {len(scraped_source_keys)} sources already scraped before -- "
                     f"skipping (use --force-rescrape to re-pull)")

    total_posts = 0
    total_comments = 0

    for market in markets:
        brands = list(BRAND_KEYWORDS.get(market, {}))
        for brand in brands:
            if brand_filter and brand.lower() not in [b.lower() for b in brand_filter]:
                continue

            keywords = BRAND_KEYWORDS[market][brand]
            all_raw_posts: List[dict] = []

            # Subreddit-scoped searches -- bare brand alias, no "Singapore"
            # qualifier needed since the subreddit itself geo-scopes it.
            for subreddit in subreddit_list:
                source_key = (brand, market, "subreddit", subreddit)
                if source_key in scraped_source_keys:
                    continue
                bare_keyword = BRAND_ALIASES.get(brand, [brand.lower()])[0]
                log.info(f"[DISCOVER] Reddit | {brand} | r/{subreddit} | keyword: {bare_keyword}")
                try:
                    raw = discover_posts(bare_keyword, subreddit, token, posts_actor, max_posts)
                except Exception as e:
                    log.error(f"[DISCOVER] Reddit | {brand} | r/{subreddit}: {e}")
                    raw = []
                for r in raw:
                    all_raw_posts.append((r, subreddit, bare_keyword))
                if conn:
                    mark_source_scraped(conn, brand, market, "subreddit", subreddit, len(raw))
                time.sleep(1.0)

            # Sitewide keyword searches -- "Singapore"-qualified terms
            # from BRAND_KEYWORDS, to catch discussion outside the
            # curated SUBREDDITS list.
            for keyword in keywords:
                source_key = (brand, market, "keyword", keyword)
                if source_key in scraped_source_keys:
                    continue
                log.info(f"[DISCOVER] Reddit | {brand} | sitewide | keyword: {keyword}")
                try:
                    raw = discover_posts(keyword, None, token, posts_actor, max_posts)
                except Exception as e:
                    log.error(f"[DISCOVER] Reddit | {brand} | sitewide '{keyword}': {e}")
                    raw = []
                for r in raw:
                    all_raw_posts.append((r, None, keyword))
                if conn:
                    mark_source_scraped(conn, brand, market, "keyword", keyword, len(raw))
                time.sleep(1.0)

            if dry_run:
                log.info(f"[DRY-RUN] Reddit | {brand}: {len(all_raw_posts)} raw post(s) discovered, "
                         f"sample: {json.dumps(all_raw_posts[0][0], default=str)[:500] if all_raw_posts else '(none)'}")
                continue

            # Normalize + dedupe within this brand's pull.
            posts_by_id: Dict[str, dict] = {}
            for raw, subreddit, keyword in all_raw_posts:
                p = extract_post_fields(raw, brand, market, subreddit, keyword)
                if p and p["post_id"] not in posts_by_id:
                    posts_by_id[p["post_id"]] = p
            posts = list(posts_by_id.values())
            if not posts:
                log.info(f"[DISCOVER] Reddit | {brand}: 0 posts found this run")
                continue

            for p in posts:
                p["is_lens_relevant"] = _is_lens_relevant(f"{p['title']} {p['selftext']}")
            relevance = check_brand_relevance(posts, client)
            for p, is_relevant in zip(posts, relevance):
                p["brand_relevant"] = is_relevant

            n_new = save_posts(conn, posts)
            total_posts += n_new
            log.info(f"[DISCOVER] Reddit | {brand}: {n_new} new posts saved ({len(posts)} discovered)")

            if skip_comments:
                continue

            # Only fetch comments for brand-relevant posts -- avoids
            # spending Apify credits on off-topic matches. Each post's
            # comments cost one separate paid actor run, so
            # max_threads_with_comments caps total spend/time on a
            # smoke test regardless of how many relevant posts turned up.
            relevant_posts = [p for p in posts if p["brand_relevant"]]
            if max_threads_with_comments is not None:
                relevant_posts = relevant_posts[:max_threads_with_comments]
            log.info(f"[COMMENTS] Reddit | {brand}: fetching comments for {len(relevant_posts)} relevant post(s)")
            for p in relevant_posts:
                if not p["permalink"]:
                    continue
                try:
                    raw_comments = fetch_comments_for_post(p["permalink"], token, posts_actor, max_comments)
                except Exception as e:
                    log.error(f"[COMMENTS] Reddit | {brand} | {p['post_id']}: {e}")
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
    parser = argparse.ArgumentParser(description="Reddit Social-Listening Module — MyACUVUE Singapore")
    parser.add_argument("--market", nargs="+", default=["SG"])
    parser.add_argument("--brand", nargs="+", help='e.g. --brand "MyACUVUE" "Alcon"')
    parser.add_argument("--max-posts", type=int, default=50, help="Per keyword/subreddit search cap")
    parser.add_argument("--max-comments", type=int, default=100, help="Per-thread comment cap")
    parser.add_argument("--skip-comments", action="store_true", help="Discovery only, no comment fetch/classify")
    parser.add_argument("--dry-run", action="store_true", help="Discover only, print a sample, save nothing")
    parser.add_argument("--force-rescrape", action="store_true", help="Ignore reddit_scraped_sources cache")
    parser.add_argument("--posts-actor", default=POSTS_ACTOR, help="Override the Apify actor slug")
    parser.add_argument("--subreddits", nargs="+", help="Override SUBREDDITS -- e.g. --subreddits singapore contactlenses")
    parser.add_argument("--max-threads-with-comments", type=int, default=None,
                         help="Cap how many relevant posts get a (paid, per-post) comments fetch -- for smoke-testing")
    parser.add_argument("--db", default="output/reddit_data_sg.db")
    parser.add_argument("--output-dir", default="output")
    parser.add_argument("--export-csv", action="store_true", help="Skip scraping; just export current DB to CSV")
    parser.add_argument("--debug", action="store_true")
    args = parser.parse_args()

    if args.debug:
        log.setLevel(logging.DEBUG)

    if args.export_csv:
        counts = export_csvs(args.db, args.output_dir)
        log.info(f"[EXPORT] CSV export complete: {counts}")
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
        db_path=args.db,
        output_dir=args.output_dir,
        subreddits=args.subreddits,
        max_threads_with_comments=args.max_threads_with_comments,
    )
