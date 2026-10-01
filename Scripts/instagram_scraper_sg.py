# ==================================================================
# Instagram Social-Listening Module — MyACUVUE Singapore (standalone)
# ==================================================================
# Purpose:
#   Add Instagram as a consumer-feedback source for the MyACUVUE/J&J
#   Vision Singapore engagement (context.md — Awareness/Consideration
#   journey stages). Discovers posts via brand hashtag search on
#   Apify's apify/instagram-scraper, then pulls comments via
#   apidojo/instagram-comments-scraper. No login, no Playwright.
#
# Status: STANDALONE MODULE — own SQLite db (instagram_data_sg.db).
#   NOT wired into any pipeline or config. Review sample output first;
#   merge into any downstream analysis is a separate, explicit step.
#
# Ported from instagram_scraper_th.py (Acne-Aid Thailand project) —
#   see Scripts/scripts.md for the porting notes this follows, same
#   family as reddit_scraper_sg.py/youtube_scraper_sg.py. Changes from
#   the TH original:
#     - the whole Thai-script-detection/translation stage
#       (_is_non_english, _llm_translate_batch, TRANSLATE_BATCH_SIZE)
#       is DROPPED, not ported — SG content is expected to already be
#       in English (same call as youtube_scraper_sg.py's port), so
#       caption_en/comment_text_en are just set equal to the original
#       text at extraction time. If non-English SG content (Mandarin/
#       Malay/Tamil) turns out to be material, re-add a translation
#       pass modeled on translate_lazada_th.py instead.
#     - HASHTAGS/PROFILES/BRAND_ALIASES rebuilt for the contact-lens
#       category (MyACUVUE + Alcon/CooperVision/Bausch+Lomb/Olens),
#       kept identical to reddit_scraper_sg.py's/youtube_scraper_sg.py's
#       BRAND_ALIASES deliberately
#     - ACNE_RELEVANCE_TERMS_* replaced with LENS_RELEVANCE_TERMS_EN
#       (identical list to reddit_scraper_sg.py's), is_acne_relevant
#       column/field renamed is_lens_relevant throughout
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
# Cost model: same actors/pricing as the TH build —
#   - apify/instagram-scraper (posts)              : ~$2.30 / 1k posts (measured, not store-advertised)
#   - apidojo/instagram-comments-scraper (comments) : ~$0.50 / 1k comments
#   Budget off these measured rates, not the Apify store's advertised ones.
#
# Setup required: APIFY_TOKEN and OPENAI_API_KEY in .env for this
#   project (already populated per day_1_plan.md Phase 0).
#
# Discovery source note (same lesson as TH): hashtag search only
#   reaches whatever volume currently carries that hashtag. To reach
#   further back in time, use --source profile against known
#   official/reseller accounts (see PROFILES below).
#
# Verification status (web search, 2026-09-25) — confirm live with
#   --dry-run before a paid run, same caveat the TH file itself flags:
#   - MyACUVUE:      @acuvuesg confirmed live official SG IG account
#     (~4.9K followers); #myacuvue/#acuvue are real but global-volume
#     hashtags — expect non-SG noise.
#   - CooperVision:  @coopervisionsg confirmed live (515 followers,
#     307 posts, bio "Making and providing #contactlenses...").
#   - Bausch + Lomb: @bauschandlombsg confirmed live (527 followers,
#     215 posts), bio hashtag #seebetterlivebetter confirmed.
#   - Alcon:         no dedicated SG-specific IG account or hashtag
#     surfaced — only global/regional accounts (e.g.
#     @alcon.contactlenses, apparently Russian-market). PROFILES left
#     empty; HASHTAGS uses bare global product names (airoptix,
#     dailiestotal30) — expect heavy non-SG noise, check volume with
#     --dry-run before trusting.
#   - Olens:         no SG-specific IG account surfaced — only global
#     @olens_contactlens (128K) / @olens_official (284K). PROFILES left
#     empty deliberately (pulling the global account would mix in
#     non-SG content, defeating the point of profile mode, same
#     rationale as the TH build's La Roche-Posay exclusion). HASHTAGS
#     uses bare "olens" — high global-noise risk, verify before trust.
#
# Usage:
#   python instagram_scraper_sg.py --dry-run
#   python instagram_scraper_sg.py --brand "MyACUVUE" --market SG
#   python instagram_scraper_sg.py --max-posts 50
#   python instagram_scraper_sg.py --skip-comments
#   python instagram_scraper_sg.py --source both --max-posts 200
#   python instagram_scraper_sg.py --classify-existing
# ==================================================================

import argparse
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

# ── CONFIG: brand hashtags per market ────────────────────────────────
# See header's "Verification status" note for what's confirmed vs. a
# best-effort guess. Bare brand names deliberately used only where no
# better SG-specific tag surfaced (Alcon, Olens) — same rationale as
# the TH build's exclusion/inclusion calls; re-verify actual noise
# levels with --dry-run before trusting volume.

HASHTAGS = {
    "SG": {
        "MyACUVUE":      ["acuvuesg", "myacuvue"],
        "Alcon":         ["airoptix", "dailiestotal30"],
        "CooperVision":  ["coopervisionsg", "biofinity"],
        "Bausch + Lomb": ["bauschandlombsg", "seebetterlivebetter"],
        "Olens":         ["olens"],
    },
}

# Literal brand-name aliases — used only as a deterministic pre-check
# in check_brand_relevance() so the unambiguous case (caption/username
# literally names the brand) never depends on an LLM call-to-call
# judgment. Kept identical to reddit_scraper_sg.py's/youtube_scraper_sg.py's
# BRAND_ALIASES.
BRAND_ALIASES = {
    "MyACUVUE":      ["acuvue", "myacuvue", "acuvue oasys", "acuvue moist"],
    "Alcon":         ["alcon", "air optix", "dailies total30", "dailies", "freshlook"],
    "CooperVision":  ["coopervision", "biofinity", "clariti", "myday", "avaira"],
    "Bausch + Lomb": ["bausch lomb", "bausch + lomb", "bausch & lomb", "biotrue", "ultra contact"],
    "Olens":         ["olens", "o-lens"],
}

# ── CONFIG: known accounts to scrape directly (profile mode) ─────────
# Populated from a web-search discovery pass (2026-09-25) against each
# brand's public Instagram presence — real handles, not guessed, but
# UNVERIFIED live via Apify (a handle can be renamed/deleted since a
# search engine last indexed it). Run a small --source profile
# --dry-run pass on each before trusting volume, exactly like the TH
# PROFILES were vetted.
PROFILES = {
    "SG": {
        "MyACUVUE":      ["acuvuesg"],
        "Alcon":         [],
        # ^ left empty deliberately: no dedicated SG-specific IG account
        # was confirmed (see header note) — pulling a global/regional
        # account would mix in non-SG content, defeating the point of
        # profile mode.
        "CooperVision":  ["coopervisionsg"],
        "Bausch + Lomb": ["bauschandlombsg"],
        "Olens":         [],
        # ^ left empty deliberately: only global @olens_contactlens /
        # @olens_official accounts surfaced, not SG-specific — same
        # rationale as Alcon above.
    },
}

APIFY_BASE = "https://api.apify.com/v2"
POSTS_ACTOR = "apify/instagram-scraper"
COMMENTS_ACTOR = "apidojo/instagram-comments-scraper"

CLASSIFY_BATCH_SIZE = 20
BRAND_RELEVANCE_BATCH_SIZE = 20
MARKET_RELEVANCE_BATCH_SIZE = 20

# Source values already confirmed (2026-09-25 dry-run, see scripts.md) to
# be an official SG-specific account or its own bio hashtag -- skip the
# LLM market check for these deterministically, same reasoning as
# BRAND_ALIASES' deterministic pre-check. Everything else (bare global
# hashtags like #airoptix/#dailiestotal30/#olens/#biofinity/#myacuvue,
# and #seebetterlivebetter which is Bausch + Lomb's *global* tagline, not
# SG-specific) goes through the LLM check below -- the 2026-09-25
# dry-run confirmed these bare tags pull heavy non-SG volume (Hong Kong,
# Spain, Turkey, Japan, Korea).
KNOWN_SG_SOURCE_VALUES = {"acuvuesg", "coopervisionsg", "bauschandlombsg"}

# ── DB SCHEMA (separate db — instagram_data_sg.db) ────────────────────

SCHEMA = """
CREATE TABLE IF NOT EXISTS ig_posts (
    post_id          TEXT PRIMARY KEY,
    brand            TEXT NOT NULL,
    market           TEXT NOT NULL,
    hashtag          TEXT,
    source_type      TEXT,             -- 'hashtag' | 'profile'
    source_value     TEXT,
    caption          TEXT,
    caption_en       TEXT,
    hashtags         TEXT,             -- JSON list
    owner_username   TEXT,
    owner_full_name  TEXT,
    location_name    TEXT,
    location_id      TEXT,
    likes_count      INTEGER,
    comments_count   INTEGER,
    post_type        TEXT,
    published_at     TEXT,
    url              TEXT,
    discovered_at    TEXT,
    is_lens_relevant INTEGER,
    brand_relevant   INTEGER,
    market_relevant  INTEGER
);

CREATE TABLE IF NOT EXISTS ig_comments (
    id                        INTEGER PRIMARY KEY AUTOINCREMENT,
    post_id                   TEXT NOT NULL,
    brand                     TEXT NOT NULL,
    market                    TEXT NOT NULL,
    author                    TEXT,
    comment_text              TEXT,
    comment_text_en           TEXT,
    like_count                INTEGER,
    published_at              TEXT,
    content_hash              TEXT UNIQUE,
    scraped_at                TEXT,
    sentiment                 TEXT,
    is_purchase_barrier_signal INTEGER,
    is_lens_relevant          INTEGER,
    FOREIGN KEY(post_id) REFERENCES ig_posts(post_id)
);

-- Tracks which (brand, source) combos have already had an Apify call
-- made for them, so re-running the script doesn't re-pay for the same
-- hashtag/profile pull every time. A source stays "done" until
-- --force-rescrape is passed — same pattern as
-- reddit_scraped_sources/yt_scraped_sources in this project's other
-- SG modules.
CREATE TABLE IF NOT EXISTS ig_scraped_sources (
    brand           TEXT NOT NULL,
    market          TEXT NOT NULL,
    source_type     TEXT NOT NULL,
    source_value    TEXT NOT NULL,
    last_scraped_at TEXT NOT NULL,
    items_found     INTEGER,
    PRIMARY KEY (brand, market, source_type, source_value)
);

CREATE INDEX IF NOT EXISTS idx_ig_posts_brand    ON ig_posts(brand);
CREATE INDEX IF NOT EXISTS idx_ig_comments_brand ON ig_comments(brand);
CREATE INDEX IF NOT EXISTS idx_ig_comments_post  ON ig_comments(post_id);
"""


def _clean_count(v) -> Optional[int]:
    """Instagram returns -1 for like/comment counts the poster has hidden —
    not a real value, and would silently skew SUM() aggregations if kept.
    NULL (unknown) is more honest than 0 (which claims zero engagement)."""
    return v if isinstance(v, int) and v >= 0 else None


def open_db(path: str) -> sqlite3.Connection:
    Path(path).parent.mkdir(parents=True, exist_ok=True)
    conn = sqlite3.connect(path, timeout=60)
    conn.row_factory = sqlite3.Row
    conn.execute("PRAGMA journal_mode=WAL")
    conn.executescript(SCHEMA)
    conn.execute("UPDATE ig_posts SET likes_count = NULL WHERE likes_count < 0")
    conn.execute("UPDATE ig_posts SET comments_count = NULL WHERE comments_count < 0")
    conn.commit()
    return conn


def get_scraped_source_keys(conn: sqlite3.Connection) -> set:
    """Returns the set of (brand, market, source_type, source_value)
    tuples already pulled from Apify at least once."""
    return {
        (row["brand"], row["market"], row["source_type"], row["source_value"])
        for row in conn.execute("SELECT brand, market, source_type, source_value FROM ig_scraped_sources")
    }


def mark_source_scraped(conn: sqlite3.Connection, brand: str, market: str, source_type: str, source_value: str, items_found: int) -> None:
    conn.execute(
        """INSERT INTO ig_scraped_sources (brand, market, source_type, source_value, last_scraped_at, items_found)
           VALUES (?, ?, ?, ?, ?, ?)
           ON CONFLICT(brand, market, source_type, source_value)
           DO UPDATE SET last_scraped_at = excluded.last_scraped_at, items_found = excluded.items_found""",
        (brand, market, source_type, source_value, datetime.now(timezone.utc).isoformat(), items_found),
    )
    conn.commit()


# ── LENS/EYE-CARE-RELEVANCE WHITELIST (regex, no LLM cost) ───────────
# Identical term list to reddit_scraper_sg.py/youtube_scraper_sg.py —
# whitelist-not-blacklist: flags (does NOT drop) posts/comments with no
# explicit lens/eye-care term, so low-volume data isn't silently thrown
# away.

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


def _is_lens_relevant(caption: str) -> bool:
    return bool(_LENS_TERM_PATTERN_EN.search(caption or ""))


# ── LLM CLASSIFICATION (mirrors reddit_scraper_sg.py's shape) ─────────

def _llm_classify_batch(texts_en: List[str], client: OpenAI) -> List[dict]:
    """Batch sentiment + purchase-barrier + on-topic classification."""
    if not texts_en:
        return []
    fallback = {"sentiment": "neutral", "is_purchase_barrier_signal": False, "is_lens_relevant": True}
    numbered = "\n".join(f"{i + 1}. {t}" for i, t in enumerate(texts_en))
    prompt = f"""Classify these {len(texts_en)} Instagram comments left on contact-lens brand posts.
For each comment, return an object with:
- "i": the comment's number as shown below (integer)
- "sentiment": one of "positive", "negative", "neutral", "mixed"
- "is_purchase_barrier_signal": true if the comment expresses a reason for not buying/switching/registering (price, availability, discomfort/irritation, trust, prescription hassle, counterfeit concern, etc.), else false
- "is_lens_relevant": true if the comment is actually about the contact-lens product/brand, false if it's off-topic chatter (a generic emoji reaction, praise for an unrelated influencer, spam)

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
    discovery, not just generic lens/eye-care content or a different
    brand's product that happens to co-tag the same hashtag. Multi-brand
    resellers on SG marketplaces commonly hashtag-stuff several brand
    names onto one post regardless of which brand the product actually is.

    Each `item` is {"caption": str, "owner_username": str, "brand": str}.
    Fails open (True) on parse errors/drops — under-flagging just leaves
    the existing behavior, over-flagging silently deletes real data."""
    if not items:
        return []
    numbered = "\n".join(
        f"{i + 1}. Brand: {it['brand']} | Account: @{it['owner_username']} | Caption: {it['caption'][:300]}"
        for i, it in enumerate(items)
    )
    prompt = f"""Each of these {len(items)} Instagram posts was surfaced by a hashtag/account search for the
stated brand's contact-lens products. SG resellers commonly hashtag-stuff many brand names onto a
single post regardless of which brand the actual product is — your job is to check the post is
genuinely about the STATED brand's product, not just co-tagged with it.

Mark "is_brand_relevant": true if EITHER:
(a) the account is an official or reseller channel clearly selling that brand (account name or
    caption repeatedly names the brand as the product being sold), OR
(b) the brand name, or one of its known product lines, is named as the actual product in the caption.

Mark false if the caption is clearly about a DIFFERENT brand's product despite co-tagging the stated
brand's hashtag alongside many others — this is common hashtag-stuffing by multi-brand resellers,
not evidence of relevance.

When genuinely unsure, default to true — this check exists to catch clear mismatches, not to
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


def _normalize_for_alias_match(s: str) -> str:
    """Strips spaces, hyphens, apostrophes, and underscores before alias
    matching. Without this, an alias like "bausch lomb" never matches a
    campaign hashtag like "#BauschLombSG" — hashtags never contain
    spaces, so any multi-word brand name silently misses every hashtag
    mention of itself and falls through to the LLM. Same fix as
    reddit_scraper_sg.py/youtube_scraper_sg.py's alias matcher."""
    return re.sub(r"[\s\-'_]", "", s or "").lower()


def check_brand_relevance(items: List[dict], client: OpenAI) -> List[bool]:
    """Wraps _llm_brand_relevance_batch with a deterministic pre-check: if
    the brand's literal name already appears in the caption or account
    username (BRAND_ALIASES), mark relevant without asking the LLM at all
    — the unambiguous case. Only items where the brand name ISN'T
    literally present go to the LLM."""
    if not items:
        return []
    results: List[Optional[bool]] = [None] * len(items)
    needs_llm_idxs = []
    for i, it in enumerate(items):
        aliases = BRAND_ALIASES.get(it["brand"], [it["brand"].lower()])
        haystack = _normalize_for_alias_match(f"{it['caption']} {it['owner_username']}")
        if any(_normalize_for_alias_match(alias) in haystack for alias in aliases):
            results[i] = True
        else:
            needs_llm_idxs.append(i)

    if needs_llm_idxs:
        llm_results = _llm_brand_relevance_batch([items[i] for i in needs_llm_idxs], client)
        for i, r in zip(needs_llm_idxs, llm_results):
            results[i] = r

    return results


# ── MARKET (SINGAPORE) RELEVANCE CHECK ────────────────────────────────
# Added 2026-09-25 after the first --dry-run confirmed the bare global
# hashtags (Alcon's #airoptix/#dailiestotal30, Olens' #olens) return
# near-100% non-SG posts (Hong Kong, Spain, Turkey, Japan, Korea in the
# sample) -- brand relevance alone doesn't catch this, since those posts
# genuinely ARE about the stated brand, just not in the Singapore market
# this engagement is scoped to. Same fail-open philosophy as brand
# relevance: under-flagging leaves noise in (visible, not silently
# dropped elsewhere), over-flagging would silently delete real SG data.

def _llm_market_relevance_batch(items: List[dict], client: OpenAI) -> List[bool]:
    """Each `item` is {"caption": str, "owner_username": str,
    "location_name": str, "source_value": str}. True if the post reads as
    genuinely Singapore-market content (SG explicitly named, SGD/S$
    pricing, Singlish, local landmarks, an SG-specific account), false if
    it reads as another country's content that merely shares the same
    brand hashtag."""
    if not items:
        return []
    numbered = "\n".join(
        f"{i + 1}. Account: @{it['owner_username']} | Location: {it['location_name'] or '(none)'} | "
        f"Hashtag/source: {it['source_value']} | Caption: {it['caption'][:300]}"
        for i, it in enumerate(items)
    )
    prompt = f"""Each of these {len(items)} Instagram posts was surfaced by a hashtag/account search for a
contact-lens brand's SINGAPORE-market social listening. The brand itself may be right, but many of
these hashtags are global and pull in posts from other countries entirely.

Mark "is_sg_relevant": true if EITHER:
(a) Singapore, "SG", or a Singapore neighbourhood/landmark (e.g. Orchard, Tampines, Bugis, Jurong) is
    named in the caption, location, or account name, OR
(b) pricing is in SGD/S$, OR
(c) the caption uses Singlish (e.g. "lah", "sia", "shiok") or otherwise clearly reads as Singapore-
    directed content, OR
(d) the account is a Singapore-specific brand handle (e.g. its name ends in "sg").

Mark false if the post is clearly from or aimed at a different country -- another language
predominates (Cantonese/Spanish/Turkish/Japanese/Korean etc. with no SG signal), a different
country/city is named, or pricing is in a non-SGD currency.

When genuinely unsure (e.g. plain English caption with no geographic signal at all), default to
true -- this check exists to catch clear non-SG mismatches, not to second-guess ambiguous cases.

For each post, return an object with:
- "i": the post's number as shown below (integer)
- "is_sg_relevant": true/false

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
        raw = resp.choices[0].message.content.strip()
        raw = re.sub(r"^```(?:json)?\s*|\s*```$", "", raw, flags=re.MULTILINE).strip()
        parsed = json.loads(raw)
        if isinstance(parsed, list):
            for p in parsed:
                idx = p.get("i")
                if isinstance(idx, int) and 1 <= idx <= len(items):
                    by_index[idx] = bool(p.get("is_sg_relevant", True))
        if len(by_index) != len(items):
            log.warning(f"[LLM] Market relevance batch: expected {len(items)}, got {len(by_index)} indexed")
    except Exception as e:
        log.warning(f"[LLM] Market relevance batch failed: {e}")

    return [by_index.get(i + 1, True) for i in range(len(items))]


def check_market_relevance(items: List[dict], client: OpenAI) -> List[bool]:
    """Deterministic pre-check first: a post sourced from a
    KNOWN_SG_SOURCE_VALUES hashtag/account, or whose location_name
    literally names Singapore, is marked relevant without asking the LLM.
    Everything else (the bare global hashtags) goes to the LLM."""
    if not items:
        return []
    results: List[Optional[bool]] = [None] * len(items)
    needs_llm_idxs = []
    for i, it in enumerate(items):
        source_value = (it.get("source_value") or "").lower()
        location_name = (it.get("location_name") or "").lower()
        if source_value in KNOWN_SG_SOURCE_VALUES or "singapore" in location_name:
            results[i] = True
        else:
            needs_llm_idxs.append(i)

    if needs_llm_idxs:
        llm_results = _llm_market_relevance_batch([items[i] for i in needs_llm_idxs], client)
        for i, r in zip(needs_llm_idxs, llm_results):
            results[i] = r

    return results


# ── APIFY CALLS ────────────────────────────────────────────────────────

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


def discover_posts(hashtag: str, token: str, max_posts: int) -> List[dict]:
    run_input = {
        "directUrls": [f"https://www.instagram.com/explore/tags/{hashtag}/"],
        "resultsType": "posts",
        "resultsLimit": max_posts,
    }
    return run_actor(token, POSTS_ACTOR, run_input, f"posts:{hashtag}")


def discover_profile_posts(username: str, token: str, max_posts: int) -> List[dict]:
    """Pull an account's own post history (reverse-chronological),
    independent of hashtag volume — the way to reach further back in
    time, at the cost of pulling everything the account posted, not
    just brand-tagged content."""
    run_input = {
        "directUrls": [f"https://www.instagram.com/{username}/"],
        "resultsType": "posts",
        "resultsLimit": max_posts,
    }
    return run_actor(token, POSTS_ACTOR, run_input, f"profile:{username}")


def fetch_comments_for_posts(post_urls: List[str], token: str, max_items: int) -> List[dict]:
    if not post_urls:
        return []
    run_input = {"startUrls": post_urls, "maxItems": max_items}
    return run_actor(token, COMMENTS_ACTOR, run_input, "comments")


def extract_post_fields(post: dict, brand: str, market: str, source_type: str, source_value: str, now: str) -> Optional[dict]:
    post_id = post.get("shortCode") or post.get("id")
    if not post_id:
        return None
    caption = post.get("caption", "") or ""
    return {
        "post_id":          post_id,
        "brand":            brand,
        "market":           market,
        "hashtag":          source_value if source_type == "hashtag" else None,
        "source_type":      source_type,
        "source_value":     source_value,
        "caption":          caption,
        "caption_en":       caption,  # SG content is expected English — no translation stage
        "hashtags":         json.dumps(post.get("hashtags", []), ensure_ascii=False),
        "owner_username":   post.get("ownerUsername", ""),
        "owner_full_name":  post.get("ownerFullName", ""),
        "location_name":    post.get("locationName"),
        "location_id":      post.get("locationId"),
        "likes_count":      _clean_count(post.get("likesCount")),
        "comments_count":   _clean_count(post.get("commentsCount")),
        "post_type":        post.get("type"),
        "published_at":     post.get("timestamp", ""),
        "url":              post.get("url", ""),
        "discovered_at":    now,
        "is_lens_relevant": int(_is_lens_relevant(caption)),
        "brand_relevant":   None,  # filled in below
        "market_relevant":  None,  # filled in below
    }


def extract_comment_fields(item: dict, post_id_by_url: Dict[str, str], brand: str, market: str, now: str) -> Optional[dict]:
    if item.get("noResults"):
        return None
    input_source = item.get("inputSource", "")
    post_id = post_id_by_url.get(input_source) or item.get("postId", "")
    text = item.get("message", "") or ""
    if not text or not post_id:
        return None
    raw_key = f"{post_id}|{item.get('createdAt', '')}|{text[:50]}"
    content_hash = hashlib.md5(raw_key.encode()).hexdigest()
    return {
        "post_id":          post_id,
        "brand":            brand,
        "market":           market,
        "author":           (item.get("user") or {}).get("username", ""),
        "comment_text":     text,
        "comment_text_en":  text,  # SG content is expected English — no translation stage
        "like_count":       item.get("likeCount", 0),
        "published_at":     item.get("createdAt", ""),
        "content_hash":     content_hash,
        "scraped_at":       now,
        "sentiment":        None,
        "is_purchase_barrier_signal": None,
        "is_lens_relevant": None,
    }


# ── DISCOVERY + EXTRACTION ORCHESTRATION ──────────────────────────────

def discover_and_extract(
    market: str,
    brand: str,
    sources: List[tuple],
    token: str,
    client: OpenAI,
    max_posts: int,
    existing_post_ids: set,
    skip_comments: bool,
    conn: Optional[sqlite3.Connection] = None,
) -> tuple:
    """`sources` is a list of (source_type, source_value) pairs:
    ("hashtag", "acuvuesg") or ("profile", "coopervisionsg").
    `conn`, if provided, is used to record each source in
    ig_scraped_sources right after its Apify call succeeds — this marks
    the $ spent as "already paid for" regardless of how many posts it
    returned, so a --dry-run (conn=None) never locks in tracking state."""
    now = datetime.now(timezone.utc).isoformat()
    posts: List[dict] = []

    for source_type, source_value in sources:
        try:
            if source_type == "hashtag":
                log.info(f"[DISCOVER] Instagram | {brand} | {market} | #{source_value}")
                raw_items = discover_posts(source_value, token, max_posts)
            else:
                log.info(f"[DISCOVER] Instagram | {brand} | {market} | profile:@{source_value}")
                raw_items = discover_profile_posts(source_value, token, max_posts)
        except Exception as e:
            # One source failing (transient network/Apify error) must not
            # discard posts already collected from earlier sources in this
            # same loop — log and move to the next source instead. Also
            # deliberately NOT marked as scraped here — a failed call
            # wasn't a successful (paid-for) pull, so it should be
            # retried on the next run rather than silently skipped.
            log.error(f"[DISCOVER] {source_type}:{source_value} failed, skipping: {e}")
            continue

        if conn is not None:
            mark_source_scraped(conn, brand, market, source_type, source_value, len(raw_items))

        for item in raw_items:
            f = extract_post_fields(item, brand, market, source_type, source_value, now)
            if not f or f["post_id"] in existing_post_ids:
                continue
            posts.append(f)
            existing_post_ids.add(f["post_id"])
        time.sleep(1)

    if not posts:
        return [], []

    # Brand-relevance check — is each post actually about the brand it was
    # tagged with, not just co-tagged/hashtag-stuffed content
    for start in range(0, len(posts), BRAND_RELEVANCE_BATCH_SIZE):
        batch = posts[start:start + BRAND_RELEVANCE_BATCH_SIZE]
        items = [{"caption": p["caption_en"], "owner_username": p["owner_username"], "brand": p["brand"]} for p in batch]
        results = check_brand_relevance(items, client)
        for p, is_relevant in zip(batch, results):
            p["brand_relevant"] = is_relevant

    # Market-relevance check — is each post actually Singapore-market
    # content, not just a global/other-country post sharing the same
    # brand hashtag (see check_market_relevance()'s header note; caught
    # live in the 2026-09-25 dry-run against Alcon/Olens's bare hashtags).
    for start in range(0, len(posts), MARKET_RELEVANCE_BATCH_SIZE):
        batch = posts[start:start + MARKET_RELEVANCE_BATCH_SIZE]
        items = [
            {
                "caption": p["caption_en"], "owner_username": p["owner_username"],
                "location_name": p["location_name"], "source_value": p["source_value"],
            }
            for p in batch
        ]
        results = check_market_relevance(items, client)
        for p, is_relevant in zip(batch, results):
            p["market_relevant"] = is_relevant

    all_comments: List[dict] = []
    if not skip_comments:
        # Only fetch comments for posts that are both brand- and
        # market-relevant — avoids spending Apify credits on comment
        # threads for e.g. a Hong Kong Alcon post that happened to share
        # the #airoptix hashtag.
        comment_eligible = [p for p in posts if p["brand_relevant"] and p["market_relevant"]]
        skipped = len(posts) - len(comment_eligible)
        if skipped:
            log.info(f"[EXTRACT] {brand}/{market}: skipping comments for {skipped} non-relevant post(s)")
        post_urls = [p["url"] for p in comment_eligible if p["url"]]
        post_id_by_url = {p["url"]: p["post_id"] for p in comment_eligible if p["url"]}
        max_items = max(len(post_urls) * 20, 20)
        try:
            raw_comments = fetch_comments_for_posts(post_urls, token, max_items)
        except Exception as e:
            # A transient Apify/network failure here must not lose the
            # posts already fetched (and already paid for) above — return
            # them with no comments rather than letting the exception
            # propagate and discard everything.
            log.error(f"[EXTRACT] Comments fetch failed, continuing with posts only: {e}")
            raw_comments = []
        for item in raw_comments:
            c = extract_comment_fields(item, post_id_by_url, brand, market, now)
            if c:
                all_comments.append(c)
        log.info(f"[EXTRACT] {brand}/{market}: {len(all_comments)} comments across {len(post_urls)} posts")

        # Sentiment + purchase-barrier classification
        for start in range(0, len(all_comments), CLASSIFY_BATCH_SIZE):
            batch = all_comments[start:start + CLASSIFY_BATCH_SIZE]
            labels = _llm_classify_batch([c["comment_text_en"] for c in batch], client)
            for c, label in zip(batch, labels):
                c["sentiment"] = label["sentiment"]
                c["is_purchase_barrier_signal"] = label["is_purchase_barrier_signal"]
                c["is_lens_relevant"] = label["is_lens_relevant"]

    return posts, all_comments


def save_posts(conn: sqlite3.Connection, posts: List[dict]) -> int:
    inserted = 0
    for p in posts:
        cur = conn.execute(
            """INSERT OR IGNORE INTO ig_posts
               (post_id, brand, market, hashtag, source_type, source_value, caption, caption_en,
                hashtags, owner_username, owner_full_name, location_name, location_id,
                likes_count, comments_count, post_type, published_at, url,
                discovered_at, is_lens_relevant, brand_relevant, market_relevant)
               VALUES (?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?)""",
            (
                p["post_id"], p["brand"], p["market"], p["hashtag"], p["source_type"], p["source_value"],
                p["caption"], p["caption_en"], p["hashtags"], p["owner_username"], p["owner_full_name"],
                p["location_name"], p["location_id"], p["likes_count"], p["comments_count"],
                p["post_type"], p["published_at"], p["url"], p["discovered_at"],
                p["is_lens_relevant"],
                int(p["brand_relevant"]) if p["brand_relevant"] is not None else None,
                int(p["market_relevant"]) if p["market_relevant"] is not None else None,
            ),
        )
        if cur.rowcount == 1:
            inserted += 1
    conn.commit()
    return inserted


def save_comments(conn: sqlite3.Connection, comments: List[dict]) -> int:
    inserted = 0
    for c in comments:
        try:
            cur = conn.execute(
                """INSERT OR IGNORE INTO ig_comments
                   (post_id, brand, market, author, comment_text, comment_text_en,
                    like_count, published_at, content_hash, scraped_at,
                    sentiment, is_purchase_barrier_signal, is_lens_relevant)
                   VALUES (?,?,?,?,?,?,?,?,?,?,?,?,?)""",
                (
                    c["post_id"], c["brand"], c["market"], c["author"],
                    c["comment_text"], c["comment_text_en"], c["like_count"],
                    c["published_at"], c["content_hash"], c["scraped_at"],
                    c["sentiment"], c["is_purchase_barrier_signal"], c["is_lens_relevant"],
                ),
            )
            if cur.rowcount == 1:
                inserted += 1
        except Exception as e:
            log.warning(f"[DB] Comment insert error: {e}")
    conn.commit()
    return inserted


# ── MAIN ───────────────────────────────────────────────────────────────

def _sources_for_brand(market: str, brand: str, source_mode: str) -> List[tuple]:
    """Build the (source_type, source_value) list for one brand/market,
    per --source: 'hashtag', 'profile', or 'both'."""
    sources: List[tuple] = []
    if source_mode in ("hashtag", "both"):
        sources += [("hashtag", h) for h in HASHTAGS.get(market, {}).get(brand, [])]
    if source_mode in ("profile", "both"):
        sources += [("profile", u) for u in PROFILES.get(market, {}).get(brand, [])]
    return sources


def run(
    markets: List[str],
    brand_filter: Optional[List[str]],
    max_posts: int,
    dry_run: bool,
    skip_comments: bool,
    source_mode: str = "hashtag",
    force_rescrape: bool = False,
    db_path: str = "output/instagram_data_sg.db",
) -> None:
    token = os.getenv("APIFY_TOKEN", "").strip()
    if not token:
        log.error("[SETUP] APIFY_TOKEN not found in .env")
        raise SystemExit(1)

    client = OpenAI()
    conn = None if dry_run else open_db(db_path)
    existing_ids: set = set()
    scraped_source_keys: set = set()
    if conn:
        existing_ids = {row[0] for row in conn.execute("SELECT post_id FROM ig_posts")}
        if existing_ids:
            log.info(f"[DISCOVER] {len(existing_ids)} posts already in DB — skipping")
        if not force_rescrape:
            scraped_source_keys = get_scraped_source_keys(conn)
            if scraped_source_keys:
                log.info(f"[DISCOVER] {len(scraped_source_keys)} sources already scraped before — "
                          f"skipping (use --force-rescrape to re-pull)")

    total_posts = 0
    total_comments = 0

    for market in markets:
        brands = set(HASHTAGS.get(market, {})) | set(PROFILES.get(market, {}))
        for brand in brands:
            if brand_filter and brand.lower() not in [b.lower() for b in brand_filter]:
                continue

            all_sources = _sources_for_brand(market, brand, source_mode)
            if not force_rescrape:
                sources = [
                    s for s in all_sources
                    if (brand, market, s[0], s[1]) not in scraped_source_keys
                ]
                skipped = len(all_sources) - len(sources)
                if skipped:
                    log.info(f"[DISCOVER] {brand}/{market}: skipping {skipped} already-scraped source(s)")
            else:
                sources = all_sources
            if not sources:
                continue

            posts, comments = discover_and_extract(
                market, brand, sources, token, client, max_posts, existing_ids, skip_comments, conn
            )

            if dry_run:
                n_sg = sum(1 for p in posts if p["market_relevant"])
                print(f"\n=== {brand} / {market} — {len(posts)} posts ({n_sg} SG-relevant), {len(comments)} comments (DRY RUN) ===")
                for p in posts[:5]:
                    print(f"  sg={p['market_relevant']} | {p['caption_en'][:60]!r} | likes={p['likes_count']} | {p['url']}")
                for c in comments[:5]:
                    print(f"    comment: {c['comment_text_en'][:80]}")
                continue

            n_p = save_posts(conn, posts)
            n_c = save_comments(conn, comments)
            total_posts += n_p
            total_comments += n_c
            log.info(f"[SAVE] {brand}/{market}: +{n_p} posts, +{n_c} comments")

    if conn:
        conn.close()

    log.info(f"[DONE] Total new: {total_posts} posts, {total_comments} comments")


def classify_existing(db_path: str = "output/instagram_data_sg.db") -> int:
    """Backfill sentiment/is_purchase_barrier_signal/is_lens_relevant for
    comments missing is_lens_relevant. Safe to re-run."""
    client = OpenAI()
    conn = open_db(db_path)
    rows = conn.execute(
        "SELECT id, comment_text_en FROM ig_comments WHERE is_lens_relevant IS NULL"
    ).fetchall()
    log.info(f"[CLASSIFY] {len(rows)} comments missing classification")

    classified = 0
    for start in range(0, len(rows), CLASSIFY_BATCH_SIZE):
        batch = rows[start:start + CLASSIFY_BATCH_SIZE]
        labels = _llm_classify_batch([r["comment_text_en"] for r in batch], client)
        for row, label in zip(batch, labels):
            conn.execute(
                """UPDATE ig_comments
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
    log.info(f"[CLASSIFY] Done — {classified} comments classified")
    return classified


def backfill_brand_relevance(db_path: str = "output/instagram_data_sg.db", recheck_negatives: bool = False) -> int:
    """Backfill brand_relevant for posts saved before that check existed
    (brand_relevant IS NULL). Safe to re-run — only touches unchecked rows.

    If recheck_negatives=True, also re-checks rows already flagged
    brand_relevant=0 — needed after a change to check_brand_relevance()
    itself (e.g. the alias-normalization fix), since those rows aren't
    NULL and would otherwise never be revisited. Safe to combine with
    old data: normalization only ADDS matches it would have missed
    before, it never removes a match that already passed, so a
    previously-True row can't flip to False from this re-check."""
    client = OpenAI()
    conn = open_db(db_path)
    where_clause = "brand_relevant IS NULL" if not recheck_negatives else "brand_relevant IS NULL OR brand_relevant = 0"
    rows = conn.execute(
        f"SELECT post_id, caption_en, owner_username, brand FROM ig_posts WHERE {where_clause}"
    ).fetchall()
    log.info(f"[RELEVANCE] {len(rows)} posts to check ({'including already-flagged negatives' if recheck_negatives else 'unchecked only'})")

    checked = 0
    for start in range(0, len(rows), BRAND_RELEVANCE_BATCH_SIZE):
        batch = rows[start:start + BRAND_RELEVANCE_BATCH_SIZE]
        items = [
            {"caption": r["caption_en"] or "", "owner_username": r["owner_username"] or "", "brand": r["brand"]}
            for r in batch
        ]
        results = check_brand_relevance(items, client)
        for row, is_relevant in zip(batch, results):
            conn.execute(
                "UPDATE ig_posts SET brand_relevant = ? WHERE post_id = ?",
                (int(is_relevant), row["post_id"]),
            )
            checked += 1
        conn.commit()
        log.info(f"[RELEVANCE] {checked}/{len(rows)} done")

    conn.close()
    log.info(f"[RELEVANCE] Done — {checked} posts checked")
    return checked


def backfill_market_relevance(db_path: str = "output/instagram_data_sg.db", recheck_negatives: bool = False) -> int:
    """Backfill market_relevant for posts saved before that check existed
    (market_relevant IS NULL). Safe to re-run — only touches unchecked
    rows. Same recheck_negatives semantics as backfill_brand_relevance —
    needed after a change to check_market_relevance() itself."""
    client = OpenAI()
    conn = open_db(db_path)
    where_clause = "market_relevant IS NULL" if not recheck_negatives else "market_relevant IS NULL OR market_relevant = 0"
    rows = conn.execute(
        f"SELECT post_id, caption_en, owner_username, location_name, source_value FROM ig_posts WHERE {where_clause}"
    ).fetchall()
    log.info(f"[MARKET] {len(rows)} posts to check ({'including already-flagged negatives' if recheck_negatives else 'unchecked only'})")

    checked = 0
    for start in range(0, len(rows), MARKET_RELEVANCE_BATCH_SIZE):
        batch = rows[start:start + MARKET_RELEVANCE_BATCH_SIZE]
        items = [
            {
                "caption": r["caption_en"] or "", "owner_username": r["owner_username"] or "",
                "location_name": r["location_name"] or "", "source_value": r["source_value"] or "",
            }
            for r in batch
        ]
        results = check_market_relevance(items, client)
        for row, is_relevant in zip(batch, results):
            conn.execute(
                "UPDATE ig_posts SET market_relevant = ? WHERE post_id = ?",
                (int(is_relevant), row["post_id"]),
            )
            checked += 1
        conn.commit()
        log.info(f"[MARKET] {checked}/{len(rows)} done")

    conn.close()
    log.info(f"[MARKET] Done — {checked} posts checked")
    return checked


if __name__ == "__main__":
    parser = argparse.ArgumentParser(description="Instagram social-listening module (standalone) — MyACUVUE Singapore")
    parser.add_argument("--market", nargs="+", default=["SG"], help="e.g. --market SG")
    parser.add_argument("--brand", nargs="+", help='e.g. --brand "MyACUVUE"')
    parser.add_argument("--max-posts", type=int, default=20, help="Max posts per hashtag/profile (default 20)")
    parser.add_argument("--dry-run", action="store_true", help="Print results instead of saving to DB")
    parser.add_argument("--skip-comments", action="store_true", help="Posts only, skip the comments phase")
    parser.add_argument(
        "--source", choices=["hashtag", "profile", "both"], default="hashtag",
        help="'hashtag' (default, uses HASHTAGS config), 'profile' (uses PROFILES config, "
             "reaches further back in time per-account), or 'both'",
    )
    parser.add_argument(
        "--classify-existing", action="store_true",
        help="Backfill brand-relevance and market-relevance (posts) and "
             "sentiment/purchase-barrier labels (comments) for already-saved "
             "data, then exit",
    )
    parser.add_argument(
        "--recheck-negatives", action="store_true",
        help="Used with --classify-existing: also re-checks posts already flagged "
             "brand_relevant=0 or market_relevant=0, not just unchecked (NULL) ones. "
             "Needed after a change to check_brand_relevance()/check_market_relevance() "
             "itself (e.g. the alias-normalization fix) — otherwise already-flagged-0 "
             "rows are never revisited since they aren't NULL.",
    )
    parser.add_argument(
        "--force-rescrape", action="store_true",
        help="Re-call Apify for sources already scraped before (by default, a source "
             "with an entry in ig_scraped_sources is skipped to avoid re-paying for the "
             "same hashtag/profile pull). Use this to pick up new organic posts on a "
             "hashtag/profile you've already scraped.",
    )
    parser.add_argument("--db", default="output/instagram_data_sg.db")
    args = parser.parse_args()

    if args.classify_existing:
        backfill_brand_relevance(db_path=args.db, recheck_negatives=args.recheck_negatives)
        backfill_market_relevance(db_path=args.db, recheck_negatives=args.recheck_negatives)
        classify_existing(db_path=args.db)
    else:
        run(
            markets=args.market,
            brand_filter=args.brand,
            max_posts=args.max_posts,
            dry_run=args.dry_run,
            skip_comments=args.skip_comments,
            source_mode=args.source,
            force_rescrape=args.force_rescrape,
            db_path=args.db,
        )
