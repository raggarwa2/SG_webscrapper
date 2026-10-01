# ==================================================================
# YouTube Social-Listening Module — MyACUVUE Singapore (standalone)
# ==================================================================
# Purpose:
#   Add YouTube as a consumer-feedback source for the MyACUVUE/J&J
#   Vision Singapore engagement (see context.md — Awareness/
#   Engagement/Consideration journey stages). Discovers videos via
#   brand keyword search on the YouTube Data API (search.list), then
#   pulls top-level comments via commentThreads.list. No scraping/
#   Playwright — first-party API, quota-metered.
#
# Status: STANDALONE MODULE — own SQLite db (youtube_data_sg.db).
#   Review sample output first; merge into any downstream analysis is
#   a separate, explicit step.
#
# Ported from youtube_scraper_th.py (Acne-Aid Thailand project) — see
#   Scripts/scripts.md for the porting notes this follows. Changes
#   from the TH original:
#     - regionCode TH -> SG
#     - relevanceLanguage dropped entirely (SG is majority English —
#       the TH original biased results toward Thai-language video via
#       relevanceLanguage="th"; no equivalent bias needed here)
#     - the whole Thai-script-detection/translation stage (_is_non_english,
#       _llm_translate_batch, TRANSLATE_BATCH_SIZE) is DROPPED, not
#       ported — SG content is expected to already be in English, so
#       title_en/description_en/comment_text_en are just set equal to
#       the original text at extraction time. If non-English SG content
#       (e.g. Mandarin/Malay/Tamil) turns out to be material, re-add a
#       translation pass modeled on translate_lazada_th.py instead.
#     - BRAND_KEYWORDS/BRAND_ALIASES/CHANNELS rebuilt for the contact-lens
#       category (MyACUVUE + Alcon/CooperVision/Bausch+Lomb/Olens)
#     - ACNE_RELEVANCE_TERMS_* replaced with lens/eye-care vocabulary
#
# IMPORTANT — project separation:
#   Keep this file and its outputs in THIS project only — do not point
#   it at the Thailand (acne-aid) or Hong Kong (xhs) project's DB/output
#   folders, and do not import data from them. External-only data,
#   Singapore market only (see plan's scope boundary: no CRM/
#   registration/WhatsApp data in scope yet).
#
# Competitive set (per context.md): MyACUVUE vs Alcon (Air Optix,
# Dailies, Total30), CooperVision, Bausch & Lomb, Olens.
#
# Cost model: YouTube Data API v3 quota — search.list costs 100 units,
#   commentThreads.list costs 1 unit per call (up to 100 comments per
#   call). Default daily quota is 10,000 units — budget ~1 search per
#   brand/keyword combination per run to stay well inside that.
#
# Setup required: YOUTUBE_API_KEY and OPENAI_API_KEY in .env for this
#   project (separate .env from the TH/HK projects if ever on the same
#   machine — this project's .env already has both keys populated).
#
# Usage:
#   python youtube_scraper_sg.py --dry-run
#   python youtube_scraper_sg.py --brand "MyACUVUE" --market SG
#   python youtube_scraper_sg.py --max-videos 25
#   python youtube_scraper_sg.py --skip-comments
#   python youtube_scraper_sg.py --classify-existing
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

# ── CONFIG: brand search keywords per market ─────────────────────────
# English-only keywords -- SG is majority English (per scripts.md's own
# note on this port), unlike the TH original which paired every brand
# with a Thai qualifier. A "Singapore"/"SG" qualifier is still appended
# to bias results toward local video content, the same way the TH
# original used a Thai qualifier for the same purpose.

BRAND_KEYWORDS = {
    "SG": {
        "MyACUVUE":        ["Acuvue review Singapore", "MyACUVUE Singapore"],
        "Alcon":           ["Alcon contact lens Singapore", "Air Optix Singapore", "Dailies Total30 Singapore"],
        "CooperVision":    ["CooperVision Singapore", "Biofinity Singapore"],
        "Bausch + Lomb":   ["Bausch Lomb contact lens Singapore", "Biotrue Singapore"],
        "Olens":           ["Olens Singapore", "O-Lens review Singapore"],
    },
}
# Bare brand names deliberately paired with a "Singapore" qualifier --
# these are global brands with huge non-SG video volume that would swamp
# local results if searched bare. Confirm actual signal/noise with a
# --dry-run pass before trusting volume (same caveat the TH project
# flagged for its own keyword set).

# Literal brand-name aliases — used only as a deterministic pre-check in
# check_brand_relevance() so the unambiguous case (title/description
# literally names the brand) never depends on an LLM call-to-call
# judgment.
BRAND_ALIASES = {
    "MyACUVUE":      ["acuvue", "myacuvue", "acuvue oasys", "acuvue moist"],
    "Alcon":         ["alcon", "air optix", "dailies total30", "dailies", "freshlook"],
    "CooperVision":  ["coopervision", "biofinity", "clariti", "myday", "avaira"],
    "Bausch + Lomb": ["bausch lomb", "bausch + lomb", "bausch & lomb", "biotrue", "ultra contact"],
    "Olens":         ["olens", "o-lens"],
}

# ── CONFIG: known official channels per market (channel mode) ────────
# Mostly NOT YET POPULATED for SG -- unlike the TH original, which had
# verified channel IDs from a live web-search pass, no equivalent SG-market
# channel research has been done for most brands yet. Channel mode
# (--source channel) will simply find nothing for those until real,
# verified channel IDs/handles are added (see resolve_channel_id() below
# for how an @handle gets resolved). Keyword mode (--source keyword, the
# default) does not depend on this.
CHANNELS = {
    "SG": {
        # Confirmed live 2026-09-23 via a --source keyword run: surfaced
        # directly (channel_title "ACUVUE Singapore"), not guessed --
        # posts MyACUVUE app/rewards promos and SG-specific product
        # launches (e.g. OASYS MAX 1-Day for Astigmatism).
        "MyACUVUE":      ["UCH8FFDRgoEtYGm00oqIADUQ"],
        "Alcon":         [],
        "CooperVision":  [],
        "Bausch + Lomb": [],
        "Olens":         [],
    },
}

YOUTUBE_API_BASE = "https://www.googleapis.com/youtube/v3"

CLASSIFY_BATCH_SIZE = 20
BRAND_RELEVANCE_BATCH_SIZE = 20

# ── DB SCHEMA (separate db — youtube_data_sg.db) ──────────────────────

SCHEMA = """
CREATE TABLE IF NOT EXISTS yt_videos (
    video_id         TEXT PRIMARY KEY,
    brand            TEXT NOT NULL,
    market           TEXT NOT NULL,
    source_type      TEXT,             -- 'keyword' | 'channel'
    search_keyword   TEXT,             -- populated when source_type='keyword'
    source_value     TEXT,             -- keyword string, or channel id/handle
    channel_title    TEXT,
    channel_id       TEXT,
    title            TEXT,
    title_en         TEXT,
    description      TEXT,
    description_en   TEXT,
    view_count       INTEGER,
    like_count       INTEGER,
    comment_count    INTEGER,
    published_at     TEXT,
    url              TEXT,
    discovered_at    TEXT,
    is_lens_relevant INTEGER,
    brand_relevant   INTEGER
);

CREATE TABLE IF NOT EXISTS yt_comments (
    id                        INTEGER PRIMARY KEY AUTOINCREMENT,
    video_id                  TEXT NOT NULL,
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
    FOREIGN KEY(video_id) REFERENCES yt_videos(video_id)
);

-- Tracks which (brand, source) combos have already had a quota-metered
-- API call made for them (search.list = 100 units, playlistItems.list =
-- 1 unit/page), so re-running the script doesn't re-spend quota on the
-- same keyword/channel pull every time. A source stays "done" until
-- --force-rescrape is passed.
CREATE TABLE IF NOT EXISTS yt_scraped_sources (
    brand           TEXT NOT NULL,
    market          TEXT NOT NULL,
    source_type     TEXT NOT NULL,
    source_value    TEXT NOT NULL,
    last_scraped_at TEXT NOT NULL,
    items_found     INTEGER,
    PRIMARY KEY (brand, market, source_type, source_value)
);

CREATE INDEX IF NOT EXISTS idx_yt_videos_brand   ON yt_videos(brand);
CREATE INDEX IF NOT EXISTS idx_yt_comments_brand ON yt_comments(brand);
CREATE INDEX IF NOT EXISTS idx_yt_comments_video ON yt_comments(video_id);
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
    """Returns the set of (brand, market, source_type, source_value)
    tuples already pulled from the YouTube API at least once."""
    return {
        (row["brand"], row["market"], row["source_type"], row["source_value"])
        for row in conn.execute("SELECT brand, market, source_type, source_value FROM yt_scraped_sources")
    }


def mark_source_scraped(conn: sqlite3.Connection, brand: str, market: str, source_type: str, source_value: str, items_found: int) -> None:
    conn.execute(
        """INSERT INTO yt_scraped_sources (brand, market, source_type, source_value, last_scraped_at, items_found)
           VALUES (?, ?, ?, ?, ?, ?)
           ON CONFLICT(brand, market, source_type, source_value)
           DO UPDATE SET last_scraped_at = excluded.last_scraped_at, items_found = excluded.items_found""",
        (brand, market, source_type, source_value, datetime.now(timezone.utc).isoformat(), items_found),
    )
    conn.commit()


# ── LENS/EYE-CARE-RELEVANCE WHITELIST (regex, no LLM cost) ────────────
# Whitelist-not-blacklist philosophy carried over from the TH project:
# flags (does NOT drop) videos whose title/description carries no
# explicit lens/eye-care term, so low-volume data isn't silently thrown
# away, but noise stays visible downstream.

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
    return bool(_LENS_TERM_PATTERN_EN.search(text))


# ── LLM CLASSIFICATION (mirrors instagram_scraper_th.py's shape) ──────
# No translation stage here -- SG content is assumed English already
# (see header note). If that assumption turns out wrong for a material
# share of results, add a translation pass modeled on
# translate_lazada_th.py rather than reviving the TH Thai-script logic.

def _llm_classify_batch(texts_en: List[str], client: OpenAI) -> List[dict]:
    """Batch sentiment + purchase-barrier + on-topic classification."""
    if not texts_en:
        return []
    fallback = {"sentiment": "neutral", "is_purchase_barrier_signal": False, "is_lens_relevant": True}
    numbered = "\n".join(f"{i + 1}. {t}" for i, t in enumerate(texts_en))
    prompt = f"""Classify these {len(texts_en)} YouTube comments left on contact-lens brand videos.
For each comment, return an object with:
- "i": the comment's number as shown below (integer)
- "sentiment": one of "positive", "negative", "neutral", "mixed"
- "is_purchase_barrier_signal": true if the comment expresses a reason for not buying/switching/registering (price, availability, discomfort/irritation, trust, prescription hassle, counterfeit concern, etc.), else false
- "is_lens_relevant": true if the comment is actually about the contact-lens product/brand, false if it's off-topic chatter (generic emoji reaction, praise for an unrelated influencer, spam)

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
    """True if a video is actually about the brand it was tagged with at
    discovery, not just generic lens/eye-care content or a different
    brand's product that happens to surface on the same keyword search
    (common with "best contact lenses Singapore"-style comparison/
    roundup videos that mention many brands).

    Each `item` is {"title": str, "description": str, "channel_title": str, "brand": str}.
    Fails open (True) on parse errors/drops — under-flagging just leaves
    the existing behavior, over-flagging silently deletes real data."""
    if not items:
        return []
    numbered = "\n".join(
        f"{i + 1}. Brand: {it['brand']} | Channel: {it['channel_title']} | Title: {it['title'][:150]} | Desc: {it['description'][:150]}"
        for i, it in enumerate(items)
    )
    prompt = f"""Each of these {len(items)} YouTube videos was surfaced by a keyword search for the
stated brand's contact-lens products. Comparison/roundup videos ("best contact lenses Singapore")
often mention many brands in one video regardless of which brand the search was aimed at — your
job is to check the video is genuinely about the STATED brand's product, not just incidentally
mentioning it.

Mark "is_brand_relevant": true if EITHER:
(a) the video is a dedicated review/unboxing/routine feature of that brand's product, OR
(b) the brand is a substantial, named focus of the video (not a one-line mention in a long list).

Mark false if the video is clearly about a DIFFERENT brand's product, or is a generic eye-care
video where the stated brand only appears in passing (e.g. buried in a "top 10" list) — this is
common on broad-keyword searches, not evidence of relevance.

When genuinely unsure, default to true — this check exists to catch clear mismatches, not to
second-guess borderline cases.

For each video, return an object with:
- "i": the video's number as shown below (integer)
- "is_brand_relevant": true/false

Return ONLY a JSON array of objects, one per video, no other text.

Videos:
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
    campaign hashtag like "#BauschLombSG" in a video title or
    description — hashtags never contain spaces, so any multi-word brand
    name silently misses every hashtag mention and falls through to the
    LLM (confirmed as a real bug in the TH project's Instagram data using
    the same alias-matching logic; carried the fix forward here)."""
    return re.sub(r"[\s\-'_]", "", s).lower()


def check_brand_relevance(items: List[dict], client: OpenAI) -> List[bool]:
    """Wraps _llm_brand_relevance_batch with a deterministic pre-check: if
    the brand's literal name already appears in the title/description/
    channel name (BRAND_ALIASES), mark relevant without asking the LLM at
    all — the unambiguous case. Only items where the brand name ISN'T
    literally present go to the LLM."""
    if not items:
        return []
    results: List[Optional[bool]] = [None] * len(items)
    needs_llm_idxs = []
    for i, it in enumerate(items):
        aliases = BRAND_ALIASES.get(it["brand"], [it["brand"].lower()])
        haystack = _normalize_for_alias_match(f"{it['title']} {it['description']} {it['channel_title']}")
        if any(_normalize_for_alias_match(alias) in haystack for alias in aliases):
            results[i] = True
        else:
            needs_llm_idxs.append(i)

    if needs_llm_idxs:
        llm_results = _llm_brand_relevance_batch([items[i] for i in needs_llm_idxs], client)
        for i, r in zip(needs_llm_idxs, llm_results):
            results[i] = r

    return results


# ── YOUTUBE DATA API CALLS ─────────────────────────────────────────────

def search_videos(keyword: str, api_key: str, max_results: int, region_code: str = "SG") -> List[dict]:
    """search.list — costs 100 quota units per call. Returns up to
    max_results video stubs (id + snippet only; stats fetched separately
    via videos.list, which is much cheaper). No relevanceLanguage param
    (dropped -- SG is majority English, unlike the TH original which
    biased toward Thai-language results)."""
    params = {
        "part": "snippet",
        "q": keyword,
        "type": "video",
        "maxResults": min(max_results, 50),
        "regionCode": region_code,
        "key": api_key,
    }
    r = requests.get(f"{YOUTUBE_API_BASE}/search", params=params, timeout=30)
    if not r.ok:
        log.error(f"[SEARCH] {keyword} failed {r.status_code}: {r.text[:500]}")
        r.raise_for_status()
    return r.json().get("items", [])


def resolve_channel_id(channel_id_or_handle: str, api_key: str) -> Optional[str]:
    """CHANNELS entries may be a resolved channel ID (starts with 'UC')
    or an unresolved @handle — resolve the latter via channels.list
    (1 quota unit) before it can be used to derive an uploads playlist."""
    if channel_id_or_handle.startswith("UC"):
        return channel_id_or_handle
    handle = channel_id_or_handle.lstrip("@")
    params = {"part": "id", "forHandle": handle, "key": api_key}
    r = requests.get(f"{YOUTUBE_API_BASE}/channels", params=params, timeout=30)
    if not r.ok:
        log.error(f"[RESOLVE] handle @{handle} failed {r.status_code}: {r.text[:500]}")
        return None
    items = r.json().get("items", [])
    if not items:
        log.warning(f"[RESOLVE] handle @{handle} not found")
        return None
    return items[0]["id"]


def fetch_channel_uploads(channel_id: str, api_key: str, max_results: int) -> List[dict]:
    """playlistItems.list against the channel's uploads playlist — 1
    quota unit per page (up to 50 items/page), vs 100 units for a single
    search.list call. Returns items normalized to the same shape
    search_videos() returns ({"id": {"videoId": ...}, "snippet": {...}})
    so extract_video_fields() can treat both sources identically."""
    uploads_playlist_id = "UU" + channel_id[2:]  # standard YouTube convention
    items: List[dict] = []
    page_token = None
    while len(items) < max_results:
        params = {
            "part": "snippet",
            "playlistId": uploads_playlist_id,
            "maxResults": min(50, max_results - len(items)),
            "key": api_key,
        }
        if page_token:
            params["pageToken"] = page_token
        r = requests.get(f"{YOUTUBE_API_BASE}/playlistItems", params=params, timeout=30)
        if not r.ok:
            log.error(f"[CHANNEL] {channel_id} failed {r.status_code}: {r.text[:500]}")
            break
        data = r.json()
        for raw in data.get("items", []):
            snippet = raw.get("snippet", {})
            video_id = snippet.get("resourceId", {}).get("videoId")
            if not video_id:
                continue
            items.append({
                "id": {"videoId": video_id},
                "snippet": {
                    "title": snippet.get("title", ""),
                    "description": snippet.get("description", ""),
                    "channelTitle": snippet.get("videoOwnerChannelTitle", snippet.get("channelTitle", "")),
                    "channelId": snippet.get("videoOwnerChannelId", channel_id),
                    "publishedAt": snippet.get("publishedAt", ""),
                },
            })
        page_token = data.get("nextPageToken")
        if not page_token:
            break
        time.sleep(0.2)
    return items


def fetch_video_stats(video_ids: List[str], api_key: str) -> Dict[str, dict]:
    """videos.list — 1 quota unit per call, up to 50 ids per call.
    Returns view/like/comment counts keyed by video id."""
    stats: Dict[str, dict] = {}
    for start in range(0, len(video_ids), 50):
        batch = video_ids[start:start + 50]
        params = {"part": "statistics", "id": ",".join(batch), "key": api_key}
        r = requests.get(f"{YOUTUBE_API_BASE}/videos", params=params, timeout=30)
        if not r.ok:
            log.error(f"[STATS] batch failed {r.status_code}: {r.text[:500]}")
            continue
        for item in r.json().get("items", []):
            stats[item["id"]] = item.get("statistics", {})
        time.sleep(0.2)
    return stats


def fetch_comments_for_video(video_id: str, api_key: str, max_comments: int) -> List[dict]:
    """commentThreads.list — 1 quota unit per call, up to 100 comments per
    call. Skips videos with comments disabled rather than raising, since
    that's an expected, non-error case."""
    comments: List[dict] = []
    page_token = None
    while len(comments) < max_comments:
        params = {
            "part": "snippet",
            "videoId": video_id,
            "maxResults": min(100, max_comments - len(comments)),
            "order": "relevance",
            "key": api_key,
        }
        if page_token:
            params["pageToken"] = page_token
        r = requests.get(f"{YOUTUBE_API_BASE}/commentThreads", params=params, timeout=30)
        if r.status_code == 403:
            reason = ""
            try:
                reason = r.json().get("error", {}).get("errors", [{}])[0].get("reason", "")
            except Exception:
                pass
            if reason == "commentsDisabled":
                log.info(f"[COMMENTS] {video_id}: comments disabled, skipping")
                break
            # Any other 403 reason (quotaExceeded, keyInvalid, forbidden from
            # API key restrictions, etc.) is a real failure, not an expected
            # "no comments" case -- surface it instead of silently returning
            # zero comments as if the video had none.
            log.error(f"[COMMENTS] {video_id} failed 403 (reason={reason or 'unknown'}): {r.text[:500]}")
            raise RuntimeError(f"commentThreads.list 403 reason={reason or 'unknown'}: {r.text[:300]}")
        if not r.ok:
            log.error(f"[COMMENTS] {video_id} failed {r.status_code}: {r.text[:500]}")
            break
        data = r.json()
        comments.extend(data.get("items", []))
        page_token = data.get("nextPageToken")
        if not page_token:
            break
        time.sleep(0.2)
    return comments


def extract_video_fields(item: dict, stats: dict, brand: str, market: str, source_type: str, source_value: str, now: str) -> Optional[dict]:
    video_id = item.get("id", {}).get("videoId")
    if not video_id:
        return None
    snippet = item.get("snippet", {})
    title = snippet.get("title", "") or ""
    description = snippet.get("description", "") or ""
    combined = f"{title} {description}"
    return {
        "video_id":         video_id,
        "brand":            brand,
        "market":           market,
        "source_type":      source_type,   # 'keyword' | 'channel'
        "search_keyword":   source_value if source_type == "keyword" else None,
        "source_value":     source_value,
        "channel_title":    snippet.get("channelTitle", ""),
        "channel_id":       snippet.get("channelId", ""),
        "title":            title,
        "title_en":         title,  # no translation stage -- SG content assumed English
        "description":      description,
        "description_en":   description,  # no translation stage -- SG content assumed English
        "view_count":       int(stats.get("viewCount", 0)) if stats.get("viewCount") else None,
        "like_count":       int(stats.get("likeCount", 0)) if stats.get("likeCount") else None,
        "comment_count":    int(stats.get("commentCount", 0)) if stats.get("commentCount") else None,
        "published_at":     snippet.get("publishedAt", ""),
        "url":              f"https://www.youtube.com/watch?v={video_id}",
        "discovered_at":    now,
        "is_lens_relevant": int(_is_lens_relevant(combined)),
        "brand_relevant":   None,  # filled in below
    }


def extract_comment_fields(item: dict, video_id: str, brand: str, market: str, now: str) -> Optional[dict]:
    top = item.get("snippet", {}).get("topLevelComment", {}).get("snippet", {})
    text = top.get("textOriginal", "") or ""
    if not text:
        return None
    raw_key = f"{video_id}|{top.get('publishedAt', '')}|{text[:50]}"
    content_hash = hashlib.md5(raw_key.encode()).hexdigest()
    return {
        "video_id":         video_id,
        "brand":            brand,
        "market":           market,
        "author":           top.get("authorDisplayName", ""),
        "comment_text":     text,
        "comment_text_en":  text,  # no translation stage -- SG content assumed English
        "like_count":       top.get("likeCount", 0),
        "published_at":     top.get("publishedAt", ""),
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
    api_key: str,
    client: OpenAI,
    max_videos: int,
    existing_video_ids: set,
    skip_comments: bool,
    max_comments_per_video: int,
    conn: Optional[sqlite3.Connection] = None,
) -> tuple:
    """`sources` is a list of (source_type, source_value) pairs:
    ("keyword", "Acuvue review Singapore") or ("channel", "UC...").
    `conn`, if provided, is used to record each source in
    yt_scraped_sources right after its API call succeeds — marks the
    quota as "already spent" regardless of how many videos it returned,
    so a --dry-run (conn=None) never locks in tracking state.

    When conn is provided, videos and comments are also SAVED to the DB
    incrementally (per brand-relevance batch, per comment-classify batch)
    rather than only at the very end of the whole brand -- bounds data
    loss on a crash/interrupt to at most one batch (<=20 items), instead
    of losing an entire brand's worth of videos/comments. The function
    still returns the full (videos, comments) lists either way, since
    --dry-run (conn=None) needs them for the preview print."""
    now = datetime.now(timezone.utc).isoformat()
    videos: List[dict] = []

    for source_type, source_value in sources:
        try:
            if source_type == "keyword":
                log.info(f"[DISCOVER] YouTube | {brand} | {market} | \"{source_value}\"")
                raw_items = search_videos(source_value, api_key, max_videos)
            else:
                resolved_id = resolve_channel_id(source_value, api_key)
                if not resolved_id:
                    continue
                log.info(f"[DISCOVER] YouTube | {brand} | {market} | channel:{source_value}")
                raw_items = fetch_channel_uploads(resolved_id, api_key, max_videos)
        except Exception as e:
            # One source failing (transient network/API error) must not
            # discard videos already collected from earlier sources in
            # this same loop — log and move to the next source instead.
            # Also deliberately NOT marked as scraped here — a failed
            # call didn't spend quota successfully, so it should be
            # retried on the next run rather than silently skipped.
            log.error(f"[DISCOVER] {source_type}:{source_value} failed, skipping: {e}")
            continue

        if conn is not None:
            mark_source_scraped(conn, brand, market, source_type, source_value, len(raw_items))

        video_ids = [it.get("id", {}).get("videoId") for it in raw_items if it.get("id", {}).get("videoId")]
        stats_by_id = fetch_video_stats(video_ids, api_key) if video_ids else {}

        for item in raw_items:
            vid = item.get("id", {}).get("videoId")
            f = extract_video_fields(item, stats_by_id.get(vid, {}), brand, market, source_type, source_value, now)
            if not f or f["video_id"] in existing_video_ids:
                continue
            videos.append(f)
            existing_video_ids.add(f["video_id"])
        time.sleep(0.5)

    if not videos:
        return [], []

    # Brand-relevance check + incremental video save, one batch at a time.
    for start in range(0, len(videos), BRAND_RELEVANCE_BATCH_SIZE):
        batch = videos[start:start + BRAND_RELEVANCE_BATCH_SIZE]
        items = [
            {"title": v["title_en"], "description": v["description"], "channel_title": v["channel_title"], "brand": v["brand"]}
            for v in batch
        ]
        results = check_brand_relevance(items, client)
        for v, is_relevant in zip(batch, results):
            v["brand_relevant"] = is_relevant
        if conn is not None:
            n_v = save_videos(conn, batch)
            log.info(f"[SAVE] {brand}/{market}: +{n_v} videos (batch of {len(batch)})")

    all_comments: List[dict] = []
    if not skip_comments:
        pending: List[dict] = []  # comments collected but not yet classified+saved

        def _flush(batch: List[dict]) -> None:
            if not batch:
                return
            labels = _llm_classify_batch([c["comment_text_en"] for c in batch], client)
            for c, label in zip(batch, labels):
                c["sentiment"] = label["sentiment"]
                c["is_purchase_barrier_signal"] = label["is_purchase_barrier_signal"]
                c["is_lens_relevant"] = label["is_lens_relevant"]
            all_comments.extend(batch)
            if conn is not None:
                n_c = save_comments(conn, batch)
                log.info(f"[SAVE] {brand}/{market}: +{n_c} comments (batch of {len(batch)})")

        for v in videos:
            try:
                raw_comments = fetch_comments_for_video(v["video_id"], api_key, max_comments_per_video)
            except Exception as e:
                # A transient API failure here must not lose the videos
                # already fetched above — continue with the next video
                # rather than letting the exception propagate.
                log.error(f"[EXTRACT] Comments fetch failed for {v['video_id']}, continuing: {e}")
                raw_comments = []
            for item in raw_comments:
                c = extract_comment_fields(item, v["video_id"], brand, market, now)
                if c:
                    pending.append(c)
            # Classify+save as soon as a full batch is ready, rather than
            # waiting for every video in the brand to finish fetching.
            while len(pending) >= CLASSIFY_BATCH_SIZE:
                _flush(pending[:CLASSIFY_BATCH_SIZE])
                pending = pending[CLASSIFY_BATCH_SIZE:]
            time.sleep(0.2)

        _flush(pending)  # remainder smaller than one full batch
        log.info(f"[EXTRACT] {brand}/{market}: {len(all_comments)} comments across {len(videos)} videos")

    return videos, all_comments


def save_videos(conn: sqlite3.Connection, videos: List[dict]) -> int:
    inserted = 0
    for v in videos:
        cur = conn.execute(
            """INSERT OR IGNORE INTO yt_videos
               (video_id, brand, market, source_type, search_keyword, source_value, channel_title, channel_id,
                title, title_en, description, description_en, view_count, like_count,
                comment_count, published_at, url, discovered_at, is_lens_relevant, brand_relevant)
               VALUES (?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?)""",
            (
                v["video_id"], v["brand"], v["market"], v["source_type"], v["search_keyword"], v["source_value"],
                v["channel_title"], v["channel_id"],
                v["title"], v["title_en"], v["description"], v["description_en"], v["view_count"], v["like_count"],
                v["comment_count"], v["published_at"], v["url"], v["discovered_at"], v["is_lens_relevant"],
                int(v["brand_relevant"]) if v["brand_relevant"] is not None else None,
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
                """INSERT OR IGNORE INTO yt_comments
                   (video_id, brand, market, author, comment_text, comment_text_en,
                    like_count, published_at, content_hash, scraped_at,
                    sentiment, is_purchase_barrier_signal, is_lens_relevant)
                   VALUES (?,?,?,?,?,?,?,?,?,?,?,?,?)""",
                (
                    c["video_id"], c["brand"], c["market"], c["author"],
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
    per --source: 'keyword', 'channel', or 'both'."""
    sources: List[tuple] = []
    if source_mode in ("keyword", "both"):
        sources += [("keyword", k) for k in BRAND_KEYWORDS.get(market, {}).get(brand, [])]
    if source_mode in ("channel", "both"):
        sources += [("channel", c) for c in CHANNELS.get(market, {}).get(brand, [])]
    return sources


def run(
    markets: List[str],
    brand_filter: Optional[List[str]],
    max_videos: int,
    max_comments_per_video: int,
    dry_run: bool,
    skip_comments: bool,
    source_mode: str = "keyword",
    force_rescrape: bool = False,
    db_path: str = "output/youtube_data_sg.db",
) -> None:
    api_key = os.getenv("YOUTUBE_API_KEY", "").strip()
    if not api_key:
        log.error("[SETUP] YOUTUBE_API_KEY not found in .env")
        raise SystemExit(1)

    client = OpenAI()
    conn = None if dry_run else open_db(db_path)
    existing_ids: set = set()
    scraped_source_keys: set = set()
    if conn:
        existing_ids = {row[0] for row in conn.execute("SELECT video_id FROM yt_videos")}
        if existing_ids:
            log.info(f"[DISCOVER] {len(existing_ids)} videos already in DB — skipping")
        if not force_rescrape:
            scraped_source_keys = get_scraped_source_keys(conn)
            if scraped_source_keys:
                log.info(f"[DISCOVER] {len(scraped_source_keys)} sources already scraped before — "
                          f"skipping (use --force-rescrape to re-pull)")

    total_videos = 0
    total_comments = 0

    for market in markets:
        brands = set(BRAND_KEYWORDS.get(market, {})) | set(CHANNELS.get(market, {}))
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

            videos, comments = discover_and_extract(
                market, brand, sources, api_key, client, max_videos, existing_ids,
                skip_comments, max_comments_per_video, conn,
            )

            if dry_run:
                print(f"\n=== {brand} / {market} — {len(videos)} videos, {len(comments)} comments (DRY RUN) ===")
                for v in videos[:5]:
                    print(f"  {v['title_en'][:60]!r} | views={v['view_count']} | {v['url']}")
                for c in comments[:5]:
                    print(f"    comment: {c['comment_text_en'][:80]}")
                continue

            # Already saved incrementally inside discover_and_extract (per
            # brand-relevance batch for videos, per classify batch for
            # comments) -- just tally totals for the run summary here.
            total_videos += len(videos)
            total_comments += len(comments)

    if conn:
        conn.close()

    # Note: these are videos/comments processed this run, not strictly
    # newly-inserted rows (the incremental per-batch saves inside
    # discover_and_extract use INSERT OR IGNORE, so a rare duplicate
    # content_hash could be silently deduped there) -- see each
    # "[SAVE] ... +N" log line above for the actual per-batch insert counts.
    log.info(f"[DONE] Total processed this run: {total_videos} videos, {total_comments} comments")


def classify_existing(db_path: str = "output/youtube_data_sg.db") -> int:
    """Backfill sentiment/is_purchase_barrier_signal/is_lens_relevant for
    comments missing is_lens_relevant. Safe to re-run."""
    client = OpenAI()
    conn = open_db(db_path)
    rows = conn.execute(
        "SELECT id, comment_text_en FROM yt_comments WHERE is_lens_relevant IS NULL"
    ).fetchall()
    log.info(f"[CLASSIFY] {len(rows)} comments missing classification")

    classified = 0
    for start in range(0, len(rows), CLASSIFY_BATCH_SIZE):
        batch = rows[start:start + CLASSIFY_BATCH_SIZE]
        labels = _llm_classify_batch([r["comment_text_en"] for r in batch], client)
        for row, label in zip(batch, labels):
            conn.execute(
                """UPDATE yt_comments
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


def backfill_brand_relevance(db_path: str = "output/youtube_data_sg.db", recheck_negatives: bool = False) -> int:
    """Backfill brand_relevant for videos saved before that check existed
    (brand_relevant IS NULL). Safe to re-run — only touches unchecked rows.

    If recheck_negatives=True, also re-checks rows already flagged
    brand_relevant=0 — needed after a change to check_brand_relevance()
    itself, since those rows aren't NULL and would otherwise never be
    revisited."""
    client = OpenAI()
    conn = open_db(db_path)
    where_clause = "brand_relevant IS NULL" if not recheck_negatives else "brand_relevant IS NULL OR brand_relevant = 0"
    rows = conn.execute(
        f"SELECT video_id, title_en, description, channel_title, brand FROM yt_videos WHERE {where_clause}"
    ).fetchall()
    log.info(f"[RELEVANCE] {len(rows)} videos to check ({'including already-flagged negatives' if recheck_negatives else 'unchecked only'})")

    checked = 0
    for start in range(0, len(rows), BRAND_RELEVANCE_BATCH_SIZE):
        batch = rows[start:start + BRAND_RELEVANCE_BATCH_SIZE]
        items = [
            {
                "title": r["title_en"] or "", "description": r["description"] or "",
                "channel_title": r["channel_title"] or "", "brand": r["brand"],
            }
            for r in batch
        ]
        results = check_brand_relevance(items, client)
        for row, is_relevant in zip(batch, results):
            conn.execute(
                "UPDATE yt_videos SET brand_relevant = ? WHERE video_id = ?",
                (int(is_relevant), row["video_id"]),
            )
            checked += 1
        conn.commit()
        log.info(f"[RELEVANCE] {checked}/{len(rows)} done")

    conn.close()
    log.info(f"[RELEVANCE] Done — {checked} videos checked")
    return checked


def backfill_comments(db_path: str = "output/youtube_data_sg.db", max_comments_per_video: int = 50) -> int:
    """Fetch comments for any video that has zero rows in yt_comments yet.
    Covers videos whose comments phase never completed -- e.g. a run
    interrupted (Ctrl+C, crash) mid-way through the comments loop in
    discover_and_extract(), which only fetches comments for videos
    collected THIS run and skips anything already in yt_videos on a
    later run. Safe to re-run: a video with comments genuinely disabled,
    or genuinely zero comments, has no cheap way to be distinguished
    from "never tried" here, so it gets a harmless retry (one 403) each
    time this is run rather than being silently skipped forever."""
    api_key = os.getenv("YOUTUBE_API_KEY", "").strip()
    if not api_key:
        log.error("[SETUP] YOUTUBE_API_KEY not found in .env")
        raise SystemExit(1)
    client = OpenAI()
    conn = open_db(db_path)
    rows = conn.execute("""
        SELECT v.video_id, v.brand, v.market
        FROM yt_videos v
        LEFT JOIN yt_comments c ON v.video_id = c.video_id
        WHERE c.id IS NULL
    """).fetchall()
    log.info(f"[BACKFILL-COMMENTS] {len(rows)} videos with no comments saved yet")

    now = datetime.now(timezone.utc).isoformat()
    total_saved = 0
    for row in rows:
        video_id, brand, market = row["video_id"], row["brand"], row["market"]
        try:
            raw_comments = fetch_comments_for_video(video_id, api_key, max_comments_per_video)
        except Exception as e:
            log.error(f"[BACKFILL-COMMENTS] {video_id} failed, skipping: {e}")
            continue
        extracted = [
            c for c in (extract_comment_fields(item, video_id, brand, market, now) for item in raw_comments)
            if c
        ]
        if not extracted:
            continue
        for start in range(0, len(extracted), CLASSIFY_BATCH_SIZE):
            batch = extracted[start:start + CLASSIFY_BATCH_SIZE]
            labels = _llm_classify_batch([c["comment_text_en"] for c in batch], client)
            for c, label in zip(batch, labels):
                c["sentiment"] = label["sentiment"]
                c["is_purchase_barrier_signal"] = label["is_purchase_barrier_signal"]
                c["is_lens_relevant"] = label["is_lens_relevant"]
            n = save_comments(conn, batch)
            total_saved += n
        log.info(f"[BACKFILL-COMMENTS] {video_id}: +{len(extracted)} comments")
        time.sleep(0.2)

    conn.close()
    log.info(f"[BACKFILL-COMMENTS] Done — {total_saved} comments saved across {len(rows)} candidate videos")
    return total_saved


def export_csv(db_path: str = "output/youtube_data_sg.db") -> tuple:
    """Dumps yt_videos and yt_comments to two CSVs next to the DB -- for
    handing this data off to someone who isn't going to open SQLite.
    Always exports the full current DB state (not just one run's worth),
    so it's safe to run any time and reflects every pull to date."""
    conn = open_db(db_path)
    db_dir = Path(db_path).parent

    videos_path = db_dir / "youtube_videos_sg.csv"
    video_rows = conn.execute("SELECT * FROM yt_videos").fetchall()
    with videos_path.open("w", encoding="utf-8-sig", newline="") as f:
        if video_rows:
            writer = csv.DictWriter(f, fieldnames=video_rows[0].keys())
            writer.writeheader()
            for row in video_rows:
                writer.writerow(dict(row))
    log.info(f"[EXPORT] {len(video_rows)} videos -> {videos_path}")

    comments_path = db_dir / "youtube_comments_sg.csv"
    comment_rows = conn.execute("SELECT * FROM yt_comments").fetchall()
    with comments_path.open("w", encoding="utf-8-sig", newline="") as f:
        if comment_rows:
            writer = csv.DictWriter(f, fieldnames=comment_rows[0].keys())
            writer.writeheader()
            for row in comment_rows:
                writer.writerow(dict(row))
    log.info(f"[EXPORT] {len(comment_rows)} comments -> {comments_path}")

    conn.close()
    return videos_path, comments_path


def print_coverage(markets: List[str], db_path: str = "output/youtube_data_sg.db") -> None:
    """Compares BRAND_KEYWORDS/CHANNELS (what SHOULD be scraped) against
    yt_scraped_sources (what actually HAS been pulled for real) and
    prints any gap. A --dry-run never writes to yt_scraped_sources, so it
    never counts as coverage here -- same mistake this caught on the
    TikTok side (MyACUVUE never got a real run, only dry-runs)."""
    if not os.path.exists(db_path):
        log.warning(f"No {db_path} yet -- nothing has been scraped for real (a --dry-run does not count)")
        return
    conn = open_db(db_path)
    missing_total = 0
    configured_total = 0
    for market in markets:
        scraped = get_scraped_source_keys(conn)
        configured = set()
        for brand in set(BRAND_KEYWORDS.get(market, {})) | set(CHANNELS.get(market, {})):
            configured |= {(brand, market, "keyword", k) for k in BRAND_KEYWORDS.get(market, {}).get(brand, [])}
            configured |= {(brand, market, "channel", c) for c in CHANNELS.get(market, {}).get(brand, [])}
        missing = configured - scraped
        configured_total += len(configured)
        missing_total += len(missing)
        if missing:
            log.warning(f"[COVERAGE] {market}: {len(missing)}/{len(configured)} configured source(s) "
                         f"never scraped for real:")
            for brand, mkt, source_type, source_value in sorted(missing):
                log.warning(f"  MISSING: brand='{brand}' {source_type}='{source_value}'")
    conn.close()
    if missing_total == 0:
        log.info(f"[COVERAGE] All {configured_total} configured source(s) across {markets} have been scraped at least once.")


if __name__ == "__main__":
    parser = argparse.ArgumentParser(description="YouTube social-listening module (standalone) — MyACUVUE Singapore")
    parser.add_argument("--market", nargs="+", default=["SG"], help="e.g. --market SG")
    parser.add_argument("--brand", nargs="+", help='e.g. --brand "MyACUVUE"')
    parser.add_argument("--max-videos", type=int, default=20, help="Max videos per keyword (default 20)")
    parser.add_argument("--max-comments-per-video", type=int, default=50, help="Max comments per video (default 50)")
    parser.add_argument("--dry-run", action="store_true", help="Print results instead of saving to DB")
    parser.add_argument("--skip-comments", action="store_true", help="Videos only, skip the comments phase")
    parser.add_argument(
        "--source", choices=["keyword", "channel", "both"], default="keyword",
        help="'keyword' (default, uses BRAND_KEYWORDS + search.list), 'channel' (uses "
             "CHANNELS + each channel's uploads playlist, cheaper in quota and reaches "
             "full upload history -- currently empty for SG, needs channel research "
             "first), or 'both'",
    )
    parser.add_argument(
        "--classify-existing", action="store_true",
        help="Backfill brand-relevance (videos) and sentiment/purchase-barrier labels "
             "(comments) for already-saved data, then exit",
    )
    parser.add_argument(
        "--recheck-negatives", action="store_true",
        help="Used with --classify-existing: also re-checks videos already flagged "
             "brand_relevant=0, not just unchecked (NULL) ones.",
    )
    parser.add_argument(
        "--force-rescrape", action="store_true",
        help="Re-call the YouTube API for sources already scraped before (by default, a "
             "source with an entry in yt_scraped_sources is skipped to avoid re-spending "
             "quota on the same keyword/channel pull). Use this to pick up new videos on "
             "a keyword/channel you've already scraped.",
    )
    parser.add_argument(
        "--export-csv", action="store_true",
        help="Export the full yt_videos/yt_comments DB state to "
             "output/youtube_videos_sg.csv and output/youtube_comments_sg.csv, then exit "
             "-- does not scrape.",
    )
    parser.add_argument(
        "--backfill-comments", action="store_true",
        help="Fetch comments for any video already in the DB that has zero comments "
             "saved yet (e.g. left over from a run interrupted mid-comments-phase), "
             "then exit -- does not search for new videos.",
    )
    parser.add_argument(
        "--coverage", action="store_true",
        help="Print which configured BRAND_KEYWORDS/CHANNELS sources have never been "
             "scraped for real (a --dry-run does not count), then exit -- does not scrape.",
    )
    args = parser.parse_args()

    if args.coverage:
        print_coverage(markets=args.market)
    elif args.export_csv:
        export_csv()
    elif args.classify_existing:
        backfill_brand_relevance(recheck_negatives=args.recheck_negatives)
        classify_existing()
    elif args.backfill_comments:
        backfill_comments(max_comments_per_video=args.max_comments_per_video)
    else:
        run(
            markets=args.market,
            brand_filter=args.brand,
            max_videos=args.max_videos,
            max_comments_per_video=args.max_comments_per_video,
            dry_run=args.dry_run,
            skip_comments=args.skip_comments,
            source_mode=args.source,
            force_rescrape=args.force_rescrape,
        )
