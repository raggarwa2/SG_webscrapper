#!/usr/bin/env python3
# ==================================================================
# Xiaohongshu (RedNote / 小红书) Social-Listening Module — MyACUVUE
# Singapore (standalone)
# ==================================================================
# Purpose:
#   Add Xiaohongshu as a consumer-feedback source for the MyACUVUE/J&J
#   Vision Singapore engagement (context.md — Awareness/Consideration
#   journey stages), same slot as instagram_scraper_sg.py/
#   reddit_scraper_sg.py.
#
# Status: STANDALONE MODULE — own SQLite db (xhs_data_sg.db). NOT
#   wired into any pipeline or config. Review sample output first;
#   merge into any downstream analysis is a separate, explicit step.
#
# Ported from xhs_scraper_v2.py (HK contact-lens project) per
# day_1_plan.md Phase 3 — flagged there as the closest starting point
# of any template (already shaped for the same lens-brand set), not
# a TH skincare port like the other SG modules. Changes from the HK
# original:
#   - Dropped config.yaml entirely (no config.yaml exists in this
#     project) — brand/keyword config is a hardcoded KEYWORDS dict at
#     module level, matching instagram_scraper_sg.py's HASHTAGS/
#     PROFILES pattern instead of the HK version's markets.HK.brands
#     schema.
#   - Own db (xhs_data_sg.db), own log prefix (xhs_sg_*.log).
#   - Brand enum swapped to MyACUVUE/Alcon/CooperVision/
#     Bausch + Lomb/Olens (context.md's competitor set) from HK's
#     Acuvue/Alcon/Bausch & Lomb/OLENS/REVIA/CooperVision.
#   - KEPT the Chinese→English translation stage (content_en via
#     GPT-4o-mini), unlike instagram_scraper_sg.py/reddit_scraper_sg.py
#     which dropped translation on the assumption SG content is
#     English-majority. XHS content is written in Chinese script
#     regardless of the poster's market, so that assumption does not
#     hold here.
#   - Added brand_relevant + market_relevant LLM gates (mirroring
#     instagram_scraper_sg.py's check_brand_relevance/
#     check_market_relevance) BEFORE the existing per-post GPT
#     sentiment/theme call. XHS keyword search has no geo scoping at
#     all (unlike Instagram's hashtag-follows-account-locale weak
#     signal), so a bare brand-name keyword search is expected to
#     return overwhelmingly Mainland Chinese content — the same
#     failure mode the 2026-09-25 Instagram dry-run already confirmed
#     for bare global hashtags (near-100% non-SG for Alcon/Olens),
#     just worse here since there's no hashtag/account-locale signal
#     at all to lean on. Comments are only fetched for posts that pass
#     both gates, same cost-control reasoning as Instagram's build.
#   - Added an xhs_scraped_sources table (same shape as
#     ig_scraped_sources/reddit's equivalent) so re-running the script
#     doesn't re-pay Apify for the same keyword pull; a keyword stays
#     "done" until --force-rescrape.
#   - Added --dry-run (prints instead of saving), matching the other
#     SG modules' CLI shape — the HK original had no dry-run mode.
#
# IMPORTANT — project separation: keep this file and its outputs in
#   THIS project only — do not point it at the Thailand (acne-aid) or
#   Hong Kong (xhs) project's DB/output folders, and do not import
#   data from them. External-only data, Singapore market only (per
#   context.md's scope boundary).
#
# Competitive set (per context.md): MyACUVUE vs Alcon (Air Optix,
# Dailies, Total30), CooperVision, Bausch & Lomb, Olens.
#
# Apify actors (same as HK build — UNVERIFIED input/output schema
# assumptions carried over, re-confirm with --dry-run before a paid
# run):
#   - zen-studio/rednote-search-scraper   (posts, by keyword)
#   - epctex/xiaohongshu-scraper          (comments, mode=comments)
#
# Setup required: APIFY_TOKEN and OPENAI_API_KEY in .env for this
#   project (already present, confirmed 2026-09-29).
#
# Usage:
#   python xhs_scraper_sg.py --dry-run
#   python xhs_scraper_sg.py --brand "MyACUVUE"
#   python xhs_scraper_sg.py --max-items 50
#   python xhs_scraper_sg.py --skip-comments
#   python xhs_scraper_sg.py --comments-only
#   python xhs_scraper_sg.py --classify-existing
# ==================================================================

import argparse
import hashlib
import json
import logging
import os
import re
import sqlite3
import sys
import time
from datetime import datetime, timezone
from pathlib import Path
from typing import Dict, List, Optional

import requests
from dotenv import load_dotenv
from openai import OpenAI
from pydantic import BaseModel

load_dotenv()

APIFY_BASE = "https://api.apify.com/v2"
POSTS_ACTOR = "zen-studio/rednote-search-scraper"
# epctex/xiaohongshu-scraper (the HK build's comments actor) no longer
# exists on Apify -- confirmed via a live 404 on 2026-09-29's first real
# run. Swapped to zen-studio/rednote-comments-scraper (same publisher as
# the posts actor). Input/output schema verified live 2026-09-29 via a
# direct probe run, NOT just docs: input is {noteUrls, maxCommentsPerNote,
# maxRepliesPerComment, includeReplies} (not {mode, postUrls, maxComments}),
# and each dataset item is a TOP-LEVEL comment with a nested replies[]
# array (not a flat per-comment row) -- see extract_comments_from_item().
COMMENTS_ACTOR = "zen-studio/rednote-comments-scraper"
MAX_REPLIES_PER_COMMENT = 5

LOG_PATH = f"output/xhs_sg_{datetime.now().strftime('%Y%m%d_%H%M')}.log"
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

BRAND_RELEVANCE_BATCH_SIZE = 20
MARKET_RELEVANCE_BATCH_SIZE = 20
ANALYSIS_BATCH_SIZE = 1  # post/comment GPT calls are single-item, same as HK build

# ── CONFIG: brand keywords for XHS search (Chinese + English) ────────
# XHS is a Chinese-script platform regardless of poster market, so
# keywords are bilingual: the brand's Chinese product name/transliteration
# plus the bare English name. Each brand also gets explicit SG-qualified
# variants ("{brand} 新加坡" / "{brand} singapore") -- added 2026-09-29
# after the first real run showed bare brand-name keywords return
# overwhelmingly Mainland content (166 posts, only 13 market_relevant
# across all 5 brands; CooperVision's all-bare keyword list scored
# 0/39). MyACUVUE's one pre-existing SG-qualified keyword ("acuvue 新加坡")
# was the standout at 8/30 relevant -- direct evidence that qualifying
# the search term itself works better than relying on the post-hoc
# market_relevant LLM gate alone to find SG content in bare-keyword noise.
KEYWORDS = {
    "MyACUVUE":      ["acuvue", "强生亮眼", "acuvue 新加坡", "acuvue singapore", "新加坡 隐形眼镜"],
    "Alcon":         ["alcon", "爱尔康", "air optix", "dailies total30", "alcon 新加坡", "爱尔康 新加坡"],
    "CooperVision":  ["coopervision", "库柏", "biofinity", "clariti", "coopervision 新加坡", "库柏 新加坡"],
    "Bausch + Lomb": ["bausch lomb", "博士伦", "bausch + lomb", "博士伦 新加坡", "bausch lomb singapore"],
    "Olens":         ["olens", "o-lens", "欧蕾", "olens 新加坡", "欧蕾 新加坡"],
}

# Literal brand-name aliases — deterministic pre-check for brand
# relevance (unambiguous case: keyword or literal brand name already
# present), same role as instagram_scraper_sg.py's/reddit_scraper_sg.py's
# BRAND_ALIASES. Includes both English and Chinese forms since XHS
# content is Chinese-script.
BRAND_ALIASES = {
    "MyACUVUE":      ["acuvue", "myacuvue", "强生", "亮眼", "acuvue oasys", "acuvue moist"],
    "Alcon":         ["alcon", "爱尔康", "air optix", "dailies total30", "dailies", "freshlook"],
    "CooperVision":  ["coopervision", "库柏", "biofinity", "clariti", "myday", "avaira"],
    "Bausch + Lomb": ["bausch lomb", "bausch + lomb", "bausch & lomb", "博士伦", "biotrue"],
    "Olens":         ["olens", "o-lens", "欧蕾", "欧棱"],
}

# Deterministic SG market signals — a keyword search matching any of
# these in the post/author text skips the LLM market check entirely.
KNOWN_SG_TERMS = ["singapore", "新加坡", "sgd", "s$", "狮城", "shiok", "sinkie"]

VALID_THEMES = [
    "comfort", "dryness", "colour", "price", "value",
    "packaging", "delivery", "authenticity", "brand_comparison",
    "recommendation", "warning", "vision_clarity",
]


class XHSPostAnalysis(BaseModel):
    content_en:      str
    sentiment:       str        # positive | neutral | negative
    themes:          list[str]  # 1-4 items from VALID_THEMES
    brand_mentioned: str        # MyACUVUE | Alcon | Bausch + Lomb | Olens | CooperVision | other


class XHSCommentAnalysis(BaseModel):
    content_en: str       # concise English translation (max 60 words)
    sentiment:  str       # positive | neutral | negative
    themes:     list[str] # 1-3 items from VALID_THEMES


SYSTEM_PROMPT = f"""You analyse Xiaohongshu (RedNote) posts about contact lenses, written for a
Singapore market social-listening project. Respond ONLY with valid JSON matching the required
schema. No markdown, no preamble.

Rules:
- content_en : concise English translation of title + body (max 150 words)
- sentiment  : exactly one of: positive | neutral | negative
- themes     : 1-4 items chosen from {VALID_THEMES}
- brand_mentioned : exactly one of: MyACUVUE | Alcon | Bausch + Lomb | Olens | CooperVision | other
"""

COMMENT_SYSTEM_PROMPT = f"""You analyse individual comments on Xiaohongshu contact lens posts.
Respond ONLY with valid JSON. No markdown, no preamble.

Rules:
- content_en : concise English translation of the comment (max 60 words)
- sentiment  : exactly one of: positive | neutral | negative
- themes     : 1-3 items chosen from {VALID_THEMES}
"""

# ── DB SCHEMA (own db — xhs_data_sg.db) ───────────────────────────────

SCHEMA = """
CREATE TABLE IF NOT EXISTS xhs_posts (
    id              INTEGER PRIMARY KEY AUTOINCREMENT,
    post_id         TEXT    UNIQUE NOT NULL,
    brand           TEXT    NOT NULL,
    keyword         TEXT,
    title           TEXT,
    content_zh      TEXT,
    content_en      TEXT,
    sentiment       TEXT,
    themes          TEXT,           -- JSON list
    brand_mentioned TEXT,
    author          TEXT,
    likes           INTEGER DEFAULT 0,
    collects        INTEGER DEFAULT 0,
    comments        INTEGER DEFAULT 0,
    publish_date    TEXT,
    url             TEXT,
    brand_relevant  INTEGER,
    market_relevant INTEGER,
    scraped_at      TEXT    NOT NULL
);
CREATE INDEX IF NOT EXISTS idx_xhs_sg_brand     ON xhs_posts(brand);
CREATE INDEX IF NOT EXISTS idx_xhs_sg_sentiment ON xhs_posts(sentiment);
CREATE INDEX IF NOT EXISTS idx_xhs_sg_date      ON xhs_posts(publish_date);

CREATE TABLE IF NOT EXISTS xhs_comments (
    id          INTEGER PRIMARY KEY AUTOINCREMENT,
    post_id     TEXT    NOT NULL,
    comment_id  TEXT    UNIQUE,
    author      TEXT,
    content_zh  TEXT,
    content_en  TEXT,
    sentiment   TEXT,
    themes      TEXT,           -- JSON list
    likes       INTEGER DEFAULT 0,
    scraped_at  TEXT    NOT NULL,
    FOREIGN KEY (post_id) REFERENCES xhs_posts(post_id)
);
CREATE INDEX IF NOT EXISTS idx_xhs_sg_comments_post ON xhs_comments(post_id);

-- Tracks which (brand, keyword) combos already had an Apify posts-search
-- call made, so re-running the script doesn't re-pay for the same
-- keyword pull. Same pattern as ig_scraped_sources/reddit's equivalent
-- in this project's other SG modules.
CREATE TABLE IF NOT EXISTS xhs_scraped_sources (
    brand           TEXT NOT NULL,
    keyword         TEXT NOT NULL,
    last_scraped_at TEXT NOT NULL,
    items_found     INTEGER,
    PRIMARY KEY (brand, keyword)
);
"""


def open_db(path: str) -> sqlite3.Connection:
    Path(path).parent.mkdir(parents=True, exist_ok=True)
    conn = sqlite3.connect(path, timeout=60)
    conn.row_factory = sqlite3.Row
    conn.execute("PRAGMA journal_mode=WAL")
    conn.execute("PRAGMA busy_timeout=60000")
    conn.execute("PRAGMA synchronous=NORMAL")
    conn.executescript(SCHEMA)
    conn.commit()
    return conn


def get_scraped_source_keys(conn: sqlite3.Connection) -> set:
    return {
        (row["brand"], row["keyword"])
        for row in conn.execute("SELECT brand, keyword FROM xhs_scraped_sources")
    }


def mark_source_scraped(conn: sqlite3.Connection, brand: str, keyword: str, items_found: int) -> None:
    conn.execute(
        """INSERT INTO xhs_scraped_sources (brand, keyword, last_scraped_at, items_found)
           VALUES (?, ?, ?, ?)
           ON CONFLICT(brand, keyword)
           DO UPDATE SET last_scraped_at = excluded.last_scraped_at, items_found = excluded.items_found""",
        (brand, keyword, datetime.now(timezone.utc).isoformat(), items_found),
    )
    conn.commit()


# ── Field extraction helpers (same fallback-key pattern as HK build) ──

def _pick(d: dict, *keys: str, default="") -> str:
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
    raw_url = _pick(post, "url", "postUrl", "shareUrl")
    post_id = ""
    if "/item/" in raw_url:
        post_id = raw_url.split("/item/")[1].split("?")[0]
    if not post_id:
        post_id = _pick(post, "postId", "id", "noteId")

    eng = post.get("engagement", {}) if isinstance(post.get("engagement"), dict) else {}

    return {
        "post_id":  post_id[:64],
        "title":    _pick(post, "title", "name")[:500],
        "content":  _pick(post, "desc", "content", "body", "description")[:5000],
        "author":   _pick(post, "author.nickname", "user.nickname", "nickname", "author")[:200],
        "likes":    int(eng.get("liked_count") or _pick(post, "likes", "likedCount") or 0),
        "collects": int(eng.get("collected_count") or _pick(post, "collects") or 0),
        "comments": int(eng.get("comments_count") or _pick(post, "comments") or 0),
        "date":     _pick(post, "scrapedAt", "time", "createTime", "publishTime", "timestamp")[:50],
        "url":      raw_url[:500],
    }


def _comment_row(node: dict) -> Optional[dict]:
    post_id = str(node.get("note_id") or "")[:64]
    content = str(node.get("content") or "")[:2000]
    if not post_id or not content:
        return None
    user = node.get("user") or {}
    author = str(user.get("nickname") or user.get("original_name") or "")[:200]
    comment_id = str(node.get("id") or "")[:64]
    if not comment_id:
        comment_id = hashlib.md5(f"{post_id}:{author}:{content}".encode()).hexdigest()[:24]
    return {
        "post_id":    post_id,
        "comment_id": comment_id,
        "author":     author,
        "content":    content,
        "likes":      int(node.get("like_count") or 0),
    }


def extract_comments_from_item(item: dict) -> List[dict]:
    """One dataset item from zen-studio/rednote-comments-scraper is a
    top-level comment carrying a nested replies[] array (verified via a
    live probe run 2026-09-29 -- see xhs_scraper_sg.py's header note on
    the epctex actor's disappearance). Flattens top-level + replies into
    individual comment rows, since xhs_comments stores one row per
    comment regardless of thread depth."""
    rows: List[dict] = []
    top = _comment_row(item)
    if top:
        rows.append(top)
    for reply in item.get("replies") or []:
        r = _comment_row(reply)
        if r:
            rows.append(r)
    return rows


# ── LLM: brand relevance / market relevance gates ─────────────────────
# Mirrors instagram_scraper_sg.py's check_brand_relevance/
# check_market_relevance exactly in shape. Needed here even more than
# for Instagram: XHS keyword search has no geo-scoping signal at all
# (no hashtag-locale, no account-locale heuristic), so a bare brand
# keyword is expected to skew heavily Mainland Chinese. Fails open
# (True) on parse errors/drops -- under-flagging just leaves noise
# visible, over-flagging silently deletes real data.

def _normalize_for_alias_match(s: str) -> str:
    return re.sub(r"[\s\-'_]", "", s or "").lower()


def _llm_brand_relevance_batch(items: List[dict], client: OpenAI) -> List[bool]:
    if not items:
        return []
    numbered = "\n".join(
        f"{i + 1}. Brand: {it['brand']} | Author: {it['author']} | Title/body: {it['text'][:300]}"
        for i, it in enumerate(items)
    )
    prompt = f"""Each of these {len(items)} Xiaohongshu (RedNote) posts was surfaced by a keyword search
for the stated brand's contact-lens products. Resellers commonly stuff many brand names into a post
regardless of which brand the actual product is -- your job is to check the post is genuinely about
the STATED brand's product, not just incidentally mentioning it.

Mark "is_brand_relevant": true if the brand name, or one of its known product lines, is named as the
actual product being discussed. Mark false if the post is clearly about a DIFFERENT brand's product
that merely co-mentions the stated brand (e.g. a comparison post whose main subject is a competitor).

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
    """items: [{"brand", "author", "text"}]. Deterministic alias pre-check
    first, LLM only for ambiguous cases -- same shape as instagram_scraper_sg.py."""
    if not items:
        return []
    results: List[Optional[bool]] = [None] * len(items)
    needs_llm_idxs = []
    for i, it in enumerate(items):
        aliases = BRAND_ALIASES.get(it["brand"], [it["brand"].lower()])
        haystack = _normalize_for_alias_match(f"{it['text']} {it['author']}")
        if any(_normalize_for_alias_match(alias) in haystack for alias in aliases):
            results[i] = True
        else:
            needs_llm_idxs.append(i)

    if needs_llm_idxs:
        llm_results = _llm_brand_relevance_batch([items[i] for i in needs_llm_idxs], client)
        for i, r in zip(needs_llm_idxs, llm_results):
            results[i] = r

    return results


def _llm_market_relevance_batch(items: List[dict], client: OpenAI) -> List[bool]:
    if not items:
        return []
    numbered = "\n".join(
        f"{i + 1}. Author: {it['author']} | Title/body: {it['text'][:300]}"
        for i, it in enumerate(items)
    )
    prompt = f"""Each of these {len(items)} Xiaohongshu (RedNote) posts was surfaced by a brand-keyword
search for a SINGAPORE-market contact-lens social-listening project. Xiaohongshu's user base is
overwhelmingly Mainland Chinese, so most keyword hits are expected to be Mainland content that
happens to mention the same brand, not Singapore content.

Mark "is_sg_relevant": true if EITHER:
(a) Singapore, "SG", or a Singapore neighbourhood/landmark (e.g. Orchard, Tampines, Bugis, Jurong,
    Sentosa) is named, OR
(b) pricing is in SGD/S$, OR
(c) the post uses Singlish (e.g. "lah", "sia", "shiok", "sinkie") or otherwise clearly reads as
    Singapore-directed content, OR
(d) the author's profile/bio explicitly states a Singapore location.

Mark false if the post reads as Mainland China / Hong Kong / Taiwan content with no Singapore signal
-- e.g. pricing in RMB/HKD/TWD, Mainland city names, or generic Mainland retail context (Tmall,
Douyin, JD.com mentions).

When genuinely unsure (plain product post with no geographic signal at all), default to false --
unlike the brand-relevance check, XHS's Mainland-dominant user base means "no signal" should be
treated as "probably not Singapore," not "probably fine." This is the opposite default from
instagram_scraper_sg.py's equivalent check, deliberately, because Instagram hashtags carry at least
a weak locale signal that XHS keyword search has none of.

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
                    by_index[idx] = bool(p.get("is_sg_relevant", False))
        if len(by_index) != len(items):
            log.warning(f"[LLM] Market relevance batch: expected {len(items)}, got {len(by_index)} indexed")
    except Exception as e:
        log.warning(f"[LLM] Market relevance batch failed: {e}")

    return [by_index.get(i + 1, False) for i in range(len(items))]


def check_market_relevance(items: List[dict], client: OpenAI) -> List[bool]:
    """items: [{"author", "text"}]. Deterministic KNOWN_SG_TERMS pre-check
    first (fail open to true), LLM otherwise (fails closed to false --
    see _llm_market_relevance_batch's note on why the default flips here)."""
    if not items:
        return []
    results: List[Optional[bool]] = [None] * len(items)
    needs_llm_idxs = []
    for i, it in enumerate(items):
        haystack = (it["text"] + " " + it["author"]).lower()
        if any(term in haystack for term in KNOWN_SG_TERMS):
            results[i] = True
        else:
            needs_llm_idxs.append(i)

    if needs_llm_idxs:
        llm_results = _llm_market_relevance_batch([items[i] for i in needs_llm_idxs], client)
        for i, r in zip(needs_llm_idxs, llm_results):
            results[i] = r

    return results


# ── GPT — post / comment sentiment+theme analysis (same as HK build) ──

def analyse_post(client: OpenAI, title: str, content: str) -> Optional[XHSPostAnalysis]:
    text = f"Title: {title}\n\n{content}".strip()
    if len(text) < 10:
        return None
    try:
        resp = client.beta.chat.completions.parse(
            model="gpt-4o-mini",
            messages=[
                {"role": "system", "content": SYSTEM_PROMPT},
                {"role": "user", "content": text},
            ],
            response_format=XHSPostAnalysis,
            max_tokens=400,
        )
        return resp.choices[0].message.parsed
    except Exception as e:
        log.warning(f"GPT post-analysis failed: {e}")
        return None


def analyse_comment(client: OpenAI, content: str) -> Optional[XHSCommentAnalysis]:
    if len(content.strip()) < 5:
        return None
    try:
        resp = client.beta.chat.completions.parse(
            model="gpt-4o-mini",
            messages=[
                {"role": "system", "content": COMMENT_SYSTEM_PROMPT},
                {"role": "user", "content": content},
            ],
            response_format=XHSCommentAnalysis,
            max_tokens=250,
        )
        return resp.choices[0].message.parsed
    except Exception as e:
        log.warning(f"GPT comment-analysis failed: {e}")
        return None


# ── Apify — posts search ───────────────────────────────────────────────

def apify_run_posts(token: str, keyword: str, max_items: int) -> List[dict]:
    """Run posts actor for ONE keyword, poll until SUCCEEDED, return dataset items."""
    actor_slug = POSTS_ACTOR.replace("/", "~")
    r = requests.post(
        f"{APIFY_BASE}/acts/{actor_slug}/runs",
        json={"keywords": [keyword], "limit": max_items},
        params={"token": token},
        timeout=30,
    )
    if not r.ok:
        log.error(f"  Apify posts 400: {r.text[:500]}")
    r.raise_for_status()
    run_info = r.json()["data"]
    run_id, dataset_id = run_info["id"], run_info["defaultDatasetId"]
    log.info(f"  [posts:{keyword}] run started run_id={run_id}")

    for attempt in range(90):
        time.sleep(10)
        status = requests.get(
            f"{APIFY_BASE}/actor-runs/{run_id}", params={"token": token}, timeout=15
        ).json()["data"]["status"]
        log.info(f"  [posts:{keyword}] status={status} (attempt {attempt + 1})")
        if status == "SUCCEEDED":
            break
        if status in ("FAILED", "ABORTED", "TIMED-OUT"):
            raise RuntimeError(f"Apify run {run_id} ended with: {status}")
    else:
        raise TimeoutError(f"Apify run {run_id} did not finish in 15 minutes")

    items_r = requests.get(
        f"{APIFY_BASE}/datasets/{dataset_id}/items",
        params={"token": token, "format": "json", "limit": max_items},
        timeout=60,
    )
    items_r.raise_for_status()
    posts = items_r.json()
    log.info(f"  [posts:{keyword}] retrieved {len(posts)} posts")
    return posts


def apify_fetch_comments_batch(token: str, urls: List[str], max_comments: int) -> List[dict]:
    actor_slug = COMMENTS_ACTOR.replace("/", "~")
    r = requests.post(
        f"{APIFY_BASE}/acts/{actor_slug}/runs",
        json={
            "noteUrls": urls,
            "maxCommentsPerNote": max_comments,
            "maxRepliesPerComment": MAX_REPLIES_PER_COMMENT,
            "includeReplies": True,
        },
        params={"token": token},
        timeout=30,
    )
    if not r.ok:
        log.error(f"  Apify comments 400: {r.text[:500]}")
    r.raise_for_status()
    run_info = r.json()["data"]
    run_id, dataset_id = run_info["id"], run_info["defaultDatasetId"]
    log.info(f"  [comments] run started run_id={run_id} ({len(urls)} URLs)")

    for attempt in range(90):
        time.sleep(10)
        status = requests.get(
            f"{APIFY_BASE}/actor-runs/{run_id}", params={"token": token}, timeout=15
        ).json()["data"]["status"]
        log.info(f"  [comments] status={status} (attempt {attempt + 1})")
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
    log.info(f"  [comments] retrieved {len(items)} items")
    return items


# ── DB write ────────────────────────────────────────────────────────────

def save_post(conn: sqlite3.Connection, brand: str, keyword: str, f: dict,
              a: Optional[XHSPostAnalysis], brand_relevant: bool, market_relevant: bool) -> bool:
    try:
        cur = conn.execute(
            """INSERT OR IGNORE INTO xhs_posts
               (post_id, brand, keyword, title, content_zh, content_en,
                sentiment, themes, brand_mentioned, author,
                likes, collects, comments, publish_date, url,
                brand_relevant, market_relevant, scraped_at)
               VALUES (?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?)""",
            (
                f["post_id"], brand, keyword, f["title"], f["content"],
                a.content_en if a else None,
                a.sentiment if a else None,
                json.dumps(a.themes, ensure_ascii=False) if a else None,
                a.brand_mentioned if a else None,
                f["author"], f["likes"], f["collects"], f["comments"],
                f["date"], f["url"],
                int(brand_relevant), int(market_relevant),
                datetime.now().isoformat(),
            ),
        )
        conn.commit()
        return cur.rowcount > 0
    except sqlite3.Error as e:
        log.warning(f"DB write failed for {f['post_id']}: {e}")
        return False


def save_comment(conn: sqlite3.Connection, post_id: str, cf: dict, a: Optional[XHSCommentAnalysis]) -> bool:
    try:
        cur = conn.execute(
            """INSERT OR IGNORE INTO xhs_comments
               (post_id, comment_id, author, content_zh, content_en, sentiment, themes, likes, scraped_at)
               VALUES (?,?,?,?,?,?,?,?,?)""",
            (
                post_id, cf["comment_id"] or None, cf["author"], cf["content"],
                a.content_en if a else None,
                a.sentiment if a else None,
                json.dumps(a.themes, ensure_ascii=False) if a else None,
                cf["likes"], datetime.now().isoformat(),
            ),
        )
        conn.commit()
        return cur.rowcount > 0
    except sqlite3.Error as e:
        log.warning(f"Comment save failed ({post_id}): {e}")
        return False


# ── Orchestration ──────────────────────────────────────────────────────

def discover_and_extract(
    brand: str,
    keywords: List[str],
    token: str,
    client: OpenAI,
    max_items: int,
    existing_ids: set,
    conn: Optional[sqlite3.Connection],
) -> List[dict]:
    """Returns list of post dicts with 'brand_relevant'/'market_relevant' filled in.
    conn=None means --dry-run: no source-tracking writes."""
    posts: List[dict] = []
    per_kw = max(10, max_items // max(len(keywords), 1))

    for kw in keywords:
        try:
            raw_items = apify_run_posts(token, kw, per_kw)
        except Exception as e:
            log.warning(f"  Keyword '{kw}' failed, skipping: {e}")
            continue

        if conn is not None:
            mark_source_scraped(conn, brand, kw, len(raw_items))

        for item in raw_items:
            f = extract_fields(item)
            if not f["post_id"] or f["post_id"] in existing_ids:
                continue
            if not f["title"] and not f["content"]:
                continue
            f["brand"] = brand
            f["keyword"] = kw
            posts.append(f)
            existing_ids.add(f["post_id"])
        time.sleep(2)

    if not posts:
        return []

    for start in range(0, len(posts), BRAND_RELEVANCE_BATCH_SIZE):
        batch = posts[start:start + BRAND_RELEVANCE_BATCH_SIZE]
        items = [{"brand": p["brand"], "author": p["author"], "text": f"{p['title']} {p['content']}"} for p in batch]
        results = check_brand_relevance(items, client)
        for p, r in zip(batch, results):
            p["brand_relevant"] = r

    for start in range(0, len(posts), MARKET_RELEVANCE_BATCH_SIZE):
        batch = posts[start:start + MARKET_RELEVANCE_BATCH_SIZE]
        items = [{"author": p["author"], "text": f"{p['title']} {p['content']}"} for p in batch]
        results = check_market_relevance(items, client)
        for p, r in zip(batch, results):
            p["market_relevant"] = r

    return posts


def run_comments_phase(conn: sqlite3.Connection, token: str, client: OpenAI,
                        max_comments: int, batch_size: int) -> int:
    """Fetch + analyse comments for posts that are brand- AND market-relevant
    and not yet covered in xhs_comments -- avoids paying for comment threads
    on Mainland-China noise that passed the posts phase."""
    rows = conn.execute("""
        SELECT p.post_id, p.url
        FROM xhs_posts p
        LEFT JOIN xhs_comments c ON p.post_id = c.post_id
        WHERE c.post_id IS NULL
          AND p.url IS NOT NULL AND p.url != ''
          AND p.brand_relevant = 1 AND p.market_relevant = 1
    """).fetchall()
    if not rows:
        log.info("Comments: no brand+market-relevant posts need comments.")
        return 0

    log.info(f"Comments: {len(rows)} relevant posts need comments ({batch_size} URLs/batch)")
    total_saved = 0
    consecutive_failures = 0

    for start in range(0, len(rows), batch_size):
        batch = rows[start:start + batch_size]
        urls = [row["url"] for row in batch]
        log.info(f"  Batch {start // batch_size + 1}: {len(urls)} URLs")
        try:
            items = apify_fetch_comments_batch(token, urls, max_comments)
            consecutive_failures = 0
        except Exception as e:
            log.error(f"  Comments batch failed: {e}")
            consecutive_failures += 1
            if consecutive_failures >= 3 or "403" in str(e):
                log.error("  Stopping comments phase -- likely out of Apify credits. Top up and re-run --comments-only.")
                break
            time.sleep(5)
            continue

        batch_saved = 0
        for item in items:
            for cf in extract_comments_from_item(item):
                a = analyse_comment(client, cf["content"])
                if save_comment(conn, cf["post_id"], cf, a):
                    batch_saved += 1

        log.info(f"  -> {batch_saved} comments saved this batch")
        total_saved += batch_saved
        time.sleep(3)

    log.info(f"Comments phase done -- {total_saved} total comments saved")
    return total_saved


def run(
    brand_filter: Optional[str],
    max_items: int,
    dry_run: bool,
    skip_comments: bool,
    comments_only: bool,
    max_comments: int,
    comment_batch: int,
    force_rescrape: bool,
    db_path: str,
) -> None:
    token = os.getenv("APIFY_TOKEN", "").strip()
    if not token:
        sys.exit("ERROR: APIFY_TOKEN not set in .env")

    client = OpenAI()
    conn = None if dry_run else open_db(db_path)

    existing_ids: set = set()
    scraped_keys: set = set()
    if conn:
        existing_ids = {row[0] for row in conn.execute("SELECT post_id FROM xhs_posts")}
        if existing_ids:
            log.info(f"Already in DB: {len(existing_ids)} posts")
        if not force_rescrape:
            scraped_keys = get_scraped_source_keys(conn)
            if scraped_keys:
                log.info(f"{len(scraped_keys)} (brand, keyword) sources already scraped -- skipping (use --force-rescrape)")

    brands = list(KEYWORDS.keys())
    if brand_filter:
        brands = [b for b in brands if b.lower() == brand_filter.lower()]
        if not brands:
            sys.exit(f"Brand '{brand_filter}' not found in KEYWORDS config")

    total_posts_saved = 0
    total_comments_saved = 0
    start_time = time.time()

    if comments_only:
        log.info("--comments-only: skipping posts phase")
    else:
        for brand in brands:
            all_keywords = KEYWORDS[brand]
            keywords = all_keywords if force_rescrape else [
                kw for kw in all_keywords if (brand, kw) not in scraped_keys
            ]
            skipped = len(all_keywords) - len(keywords)
            if skipped:
                log.info(f"{brand}: skipping {skipped} already-scraped keyword(s)")
            if not keywords:
                continue

            log.info(f"{'-' * 60}")
            log.info(f"Brand: {brand}  |  keywords: {keywords}  |  max_items: {max_items}")

            posts = discover_and_extract(brand, keywords, token, client, max_items, existing_ids, conn)

            if dry_run:
                n_brand = sum(1 for p in posts if p["brand_relevant"])
                n_sg = sum(1 for p in posts if p["brand_relevant"] and p["market_relevant"])
                print(f"\n=== {brand} -- {len(posts)} posts ({n_brand} brand-relevant, {n_sg} also SG-relevant) (DRY RUN) ===")
                for p in posts[:5]:
                    print(f"  brand={p['brand_relevant']} sg={p['market_relevant']} | {p['title'][:60]!r} | likes={p['likes']} | {p['url']}")
                continue

            brand_saved = 0
            analysed = 0
            for f in posts:
                # Full GPT sentiment/theme analysis only for posts that pass
                # both relevance gates -- skips paying for analysis on the
                # ~90%+ Mainland-noise majority a bare/SG-qualified keyword
                # still pulls in. Non-relevant posts are still saved (raw
                # content_zh + both relevance flags) so the noise rate stays
                # visible, just without the extra GPT call.
                if f["brand_relevant"] and f["market_relevant"]:
                    a = analyse_post(client, f["title"], f["content"])
                    analysed += 1
                else:
                    a = None
                if save_post(conn, brand, f["keyword"], f, a, f["brand_relevant"], f["market_relevant"]):
                    brand_saved += 1

            log.info(f"  -> {brand_saved} new posts saved, {analysed} fully analysed ({len(posts)} retrieved)")
            total_posts_saved += brand_saved
            time.sleep(3)

    elapsed = round(time.time() - start_time)
    log.info(f"{'-' * 60}")
    log.info(f"Posts done -- {total_posts_saved} saved  |  {elapsed}s")

    if dry_run:
        log.info("Dry run -- comments phase skipped.")
        return

    if skip_comments:
        log.info("Comments phase skipped (--skip-comments)")
    else:
        log.info(f"{'-' * 60}")
        log.info(f"Starting comments phase  |  max/post: {max_comments}")
        total_comments_saved = run_comments_phase(conn, token, client, max_comments, comment_batch)

    conn.close()
    log.info(f"{'-' * 60}")
    log.info(f"All done  |  DB: {db_path}  |  Log: {LOG_PATH}  |  "
              f"{total_posts_saved} posts, {total_comments_saved} comments")


def classify_existing(db_path: str) -> None:
    """Backfill brand_relevant/market_relevant for posts saved before those
    checks existed, and content_en for comments missing translation. Safe
    to re-run -- only touches unchecked/untranslated rows."""
    client = OpenAI()
    conn = open_db(db_path)

    rows = conn.execute(
        "SELECT post_id, brand, author, title, content_zh FROM xhs_posts "
        "WHERE brand_relevant IS NULL OR market_relevant IS NULL"
    ).fetchall()
    log.info(f"[RELEVANCE] {len(rows)} posts to (re)check")
    for start in range(0, len(rows), BRAND_RELEVANCE_BATCH_SIZE):
        batch = rows[start:start + BRAND_RELEVANCE_BATCH_SIZE]
        brand_items = [{"brand": r["brand"], "author": r["author"] or "", "text": f"{r['title']} {r['content_zh']}"} for r in batch]
        brand_results = check_brand_relevance(brand_items, client)
        market_items = [{"author": r["author"] or "", "text": f"{r['title']} {r['content_zh']}"} for r in batch]
        market_results = check_market_relevance(market_items, client)
        for row, br, mr in zip(batch, brand_results, market_results):
            conn.execute(
                "UPDATE xhs_posts SET brand_relevant = ?, market_relevant = ? WHERE post_id = ?",
                (int(br), int(mr), row["post_id"]),
            )
        conn.commit()
        log.info(f"[RELEVANCE] {min(start + BRAND_RELEVANCE_BATCH_SIZE, len(rows))}/{len(rows)} done")

    comment_rows = conn.execute(
        "SELECT id, content_zh FROM xhs_comments WHERE content_en IS NULL AND content_zh IS NOT NULL"
    ).fetchall()
    log.info(f"[TRANSLATE] {len(comment_rows)} comments missing content_en")
    for row in comment_rows:
        a = analyse_comment(client, row["content_zh"])
        if a:
            conn.execute(
                "UPDATE xhs_comments SET content_en=?, sentiment=?, themes=? WHERE id=?",
                (a.content_en, a.sentiment, json.dumps(a.themes, ensure_ascii=False), row["id"]),
            )
            conn.commit()

    conn.close()
    log.info("[CLASSIFY] Done.")


if __name__ == "__main__":
    ap = argparse.ArgumentParser(
        description="Scrape Xiaohongshu posts via Apify (Singapore MyACUVUE engagement) and store in xhs_data_sg.db"
    )
    ap.add_argument("--brand", type=str, default=None, help="Single brand name to scrape (default: all brands in KEYWORDS)")
    ap.add_argument("--max-items", type=int, default=50, help="Max posts per keyword set (default: 50; lower for cheap test runs)")
    ap.add_argument("--max-comments", type=int, default=5, help="Max comments per post (default: 5)")
    ap.add_argument("--comment-batch-size", type=int, default=50, help="Post URLs per comments Apify call (default: 50)")
    ap.add_argument("--dry-run", action="store_true", help="Print results instead of saving to DB (no Apify source-tracking writes)")
    ap.add_argument("--skip-comments", action="store_true", help="Posts only, skip the comments phase")
    ap.add_argument("--comments-only", action="store_true", help="Skip post scraping; only fetch comments for posts already in DB")
    ap.add_argument("--force-rescrape", action="store_true", help="Re-call Apify for (brand, keyword) pairs already scraped before")
    ap.add_argument("--classify-existing", action="store_true", help="Backfill brand/market relevance and comment translations for existing rows, then exit")
    ap.add_argument("--db", default="output/xhs_data_sg.db")
    args = ap.parse_args()

    if args.classify_existing:
        classify_existing(db_path=args.db)
    else:
        run(
            brand_filter=args.brand,
            max_items=args.max_items,
            dry_run=args.dry_run,
            skip_comments=args.skip_comments,
            comments_only=args.comments_only,
            max_comments=args.max_comments,
            comment_batch=args.comment_batch_size,
            force_rescrape=args.force_rescrape,
            db_path=args.db,
        )
