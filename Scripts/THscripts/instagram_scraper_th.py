# ==================================================================
# Instagram Social-Listening Module — Acne-Aid Thailand (standalone)
# ==================================================================
# Purpose:
#   Add Instagram as a consumer-feedback source for the Acne-Aid
#   Thailand pricing/brand-feedback engagement. Discovers posts via
#   brand hashtag search on Apify's apify/instagram-scraper, then
#   pulls comments via apidojo/instagram-comments-scraper. No login,
#   no Playwright.
#
# Status: STANDALONE MODULE — own SQLite db (instagram_data_th.db).
#   NOT wired into any pricing pipeline or config_th.yaml. Review
#   sample output first; merge is a separate, explicit step.
#
# IMPORTANT — project separation:
#   This is adapted from the architecture of a script built for a
#   different, unrelated engagement (HK contact lenses). It is a
#   fresh file, own config, own database. Do NOT point this at that
#   project's DB/output folders, and do NOT import data from it.
#   Per Acne-Aid Context.md: external-only data, Thailand market only.
#
# Scope of this build (first pass, mirrors the HK Phase-0 approach):
#   brand hashtag only, Thailand market only. Bare brand names are
#   deliberately excluded from HASHTAGS below where they'd collide
#   with unrelated global content (see BRAND_ALIASES note) — add
#   confirmed local hashtags after a quick Phase-0 volume check, the
#   same way #acuvuehk was validated before being trusted on the HK
#   project.
#
# Competitive set (per Context.md): Acne-Aid vs CeraVe, Cetaphil,
# Neutrogena, La Roche-Posay, Eucerin, Smooth E (local insurgent,
# actively gaining share — treat as the priority benchmark), plus
# Clean & Clear and Oxe'Cure per the broader ~229-SKU competitive set
# used on the pricing side of this engagement.
#
# Cost model: same actors/pricing as the HK build —
#   - apify/instagram-scraper (posts)              : ~$2.30 / 1k posts (measured, not store-advertised)
#   - apidojo/instagram-comments-scraper (comments) : ~$0.50 / 1k comments
#   Budget off these measured rates, not the Apify store's advertised ones.
#
# Setup required: APIFY_TOKEN and OPENAI_API_KEY in .env for this
#   project (separate .env from the HK project if they're ever on
#   the same machine).
#
# Usage:
#   python instagram_scraper_th.py --dry-run
#   python instagram_scraper_th.py --brand "Acne-Aid" --market TH
#   python instagram_scraper_th.py --max-posts 50
#   python instagram_scraper_th.py --skip-comments
#   python instagram_scraper_th.py --source both --max-posts 200
#   python instagram_scraper_th.py --classify-existing
#
# Discovery source note (same lesson as HK): hashtag search only
#   reaches whatever volume currently carries that hashtag. To reach
#   further back in time, use --source profile against known
#   official/reseller accounts once identified (see PROFILES below —
#   populate after a Phase-0 discovery pass; left empty here since no
#   verified TH accounts have been confirmed yet).
# ==================================================================

import argparse
import hashlib
import json
import logging
import re
import sqlite3
import time
from datetime import datetime, timezone
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
# Deliberately brand-hashtag-only for this first build (see header).
# Thai-script hashtags included where the brand has a distinct local
# name; English hashtags included since skincare brand names on Thai
# social/marketplace platforms are usually kept in Latin script (same
# pattern observed on Boots.co.th during the pricing-side work).

HASHTAGS = {
    "TH": {
        # Verified via web search (2026-07-27) against each brand's
        # actual TH-market Instagram/X presence — not guessed. Confidence
        # varies by brand; see notes inline. Re-verify with --dry-run
        # before trusting volume, same as the HK #acuvuehk validation.
        "Acne-Aid":       ["acneaidthailand", "AcneAidคลีนผิวจบปัญหาสิวรีเทิร์น"],
        # ^ confirmed live on FB/X; no distinct confirmed IG-specific
        # hashtag beyond these two — brand's own IG handle itself
        # wasn't cleanly confirmed either (see PROFILES note below).
        "CeraVe":         ["CeraVeThailand"],
        # ^ confirmed: official IG @ceravethailand's own bio hashtag.
        "Cetaphil":       ["cetaphil"],
        # ^ no distinct TH-local hashtag surfaced; bare brand name only
        # (global "cetaphil" volume risk — check noise with --dry-run).
        "Neutrogena":     ["NeutrogenaTh", "นูโทรจีนา"],
        # ^ confirmed via official TH X bio; official TH IG
        # (@neutrogena_th) has low follower/post count (~2.5K/142) —
        # expect thin volume.
        "La Roche-Posay": ["LaRochePosayTH", "ลาโรชโพเซย์", "larocheposaythailand"],
        # ^ confirmed via TH X account bio + hashtag research sites; no
        # dedicated TH Instagram account was confirmed (only the 5M-
        # follower global @larocheposay) — expect these hashtags to
        # surface a mix of TH and non-TH posts, filter accordingly.
        "Eucerin":        ["eucerinthailand"],
        # ^ confirmed: official IG @eucerin.thailand's own handle/tag.
        "Smooth E":       ["smoothe"],
        # ^ no distinct confirmed local hashtag; brand is more active on
        # TikTok/Facebook than Instagram per search results — treat IG
        # volume expectations accordingly.
        "Clean & Clear":  ["Cleanandclearthailand", "เจลส้มคุมมันในตำนาน"],
        # ^ confirmed: official IG @cleanandclearthailand's own bio tags.
        "Oxe'Cure":       ["Oxecure", "Oxecurethailand", "อ๊อกซีเคียว"],
        # ^ confirmed: official IG @oxecureofficial + X bio hashtags.
    },
}
# Bare brand names deliberately excluded where testing would likely
# show collision risk (e.g. generic English words, or global non-TH
# volume swamping local content) — same rationale as the HK build's
# exclusion of bare "alcon"/"coopervision". Confirm actual noise
# levels with a --dry-run pass per hashtag before trusting volume.

# Literal brand-name aliases — used only as a deterministic pre-check
# in check_brand_relevance() so the unambiguous case (caption/username
# literally names the brand) never depends on an LLM call-to-call
# judgment. Mirrors the HK build's BRAND_ALIASES pattern.
BRAND_ALIASES = {
    "Acne-Aid":       ["acne-aid", "acne aid", "acneaid", "แอคเนเอด"],
    "CeraVe":         ["cerave"],
    "Cetaphil":       ["cetaphil"],
    "Neutrogena":     ["neutrogena"],
    "La Roche-Posay": ["la roche-posay", "la roche posay", "laroche posay", "lrp"],
    "Eucerin":        ["eucerin"],
    "Smooth E":       ["smooth e", "smoothe", "สมูทอี"],
    "Clean & Clear":  ["clean & clear", "clean and clear"],
    "Oxe'Cure":       ["oxe'cure", "oxecure", "oxe cure"],
}

# ── CONFIG: known accounts to scrape directly (profile mode) ─────────
# Populated from a web-search discovery pass (2026-07-27) against each
# brand's public Instagram presence — real handles, not guessed. Each
# entry is the account whose bio/branding most clearly matched "the
# official TH IG account" in search results. IMPORTANT: unlike
# HASHTAGS above, these have NOT been verified live via Apify — a
# handle can be renamed/deleted since a search engine last indexed it.
# Run a small --source profile --dry-run pass on each before trusting
# volume, exactly like the HK PROFILES were vetted.
PROFILES = {
    "TH": {
        "Acne-Aid":       [],
        # ^ left empty deliberately: search surfaced a Facebook page
        # (acneaidthailand) and a TikTok handle (acneaid.th) but no IG
        # account confirmed distinctly enough to trust here — priority
        # follow-up given this is the brand under study.
        "CeraVe":         ["ceravethailand"],
        "Cetaphil":       ["cetaphil_th"],
        "Neutrogena":     ["neutrogena_th"],
        # ^ low follower/post count (~2.5K followers, 142 posts) —
        # expect thin volume from hashtag mode too.
        "La Roche-Posay": [],
        # ^ left empty: only the global @larocheposay account (5M
        # followers, not TH-specific) was confirmed — pulling its
        # profile would mix in non-TH content, defeating the point of
        # profile mode. Revisit if a dedicated TH IG account surfaces.
        "Eucerin":        ["eucerin.thailand"],
        "Smooth E":       ["smooth.e.life"],
        # ^ alt candidate seen in search: smooth_e_official (mainly
        # TikTok-first per search results) — worth a --dry-run check too.
        "Clean & Clear":  ["cleanandclearthailand"],
        "Oxe'Cure":       ["oxecureofficial"],
    },
}

APIFY_BASE = "https://api.apify.com/v2"
POSTS_ACTOR = "apify/instagram-scraper"
COMMENTS_ACTOR = "apidojo/instagram-comments-scraper"

TRANSLATE_BATCH_SIZE = 20
CLASSIFY_BATCH_SIZE = 20
BRAND_RELEVANCE_BATCH_SIZE = 20

# ── DB SCHEMA (separate db — instagram_data_th.db) ────────────────────

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
    is_acne_relevant INTEGER,
    brand_relevant   INTEGER
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
    is_acne_relevant          INTEGER,
    FOREIGN KEY(post_id) REFERENCES ig_posts(post_id)
);

-- Tracks which (brand, source) combos have already had an Apify call
-- made for them, so re-running the script doesn't re-pay for the same
-- hashtag/profile pull every time. A source stays "done" until
-- --force-rescrape is passed — this trades off catching brand-new
-- organic posts on a re-run against not re-billing Apify for the same
-- pull, which is the right default for a cost-metered actor.
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


# ── ACNE/SKINCARE-RELEVANCE WHITELIST (regex, no LLM cost) ────────────
# Whitelist-not-blacklist philosophy: a hashtag can be stuffed onto
# unrelated content — this flags (does NOT drop) posts whose caption
# carries no explicit skincare/acne term, so low-volume data isn't
# silently thrown away, but noise is still visible downstream.

ACNE_RELEVANCE_TERMS_EN = [
    "acne", "cleanser", "facial wash", "face wash", "moisturizer",
    "skincare", "breakout", "pimple", "blemish", "oily skin",
    "sensitive skin", "facial foam", "sunscreen", "toner",
]
ACNE_RELEVANCE_TERMS_TH = [
    "สิว", "ล้างหน้า", "ผิวมัน", "ผิวแพ้ง่าย", "ครีม", "บำรุงผิว", "โฟมล้างหน้า",
]
_ACNE_TERM_PATTERN_TH = re.compile("|".join(ACNE_RELEVANCE_TERMS_TH))
_ACNE_TERM_PATTERN_EN = re.compile(
    "|".join(t.replace(" ", r"\s*") for t in ACNE_RELEVANCE_TERMS_EN),
    re.IGNORECASE,
)


def _is_acne_relevant(caption: str) -> bool:
    return bool(_ACNE_TERM_PATTERN_TH.search(caption) or _ACNE_TERM_PATTERN_EN.search(caption))


# ── LANGUAGE DETECTION + TRANSLATION ──────────────────────────────────

def _is_non_english(text: str) -> bool:
    if not text or len(text) < 3:
        return False
    thai = sum(1 for c in text if "\u0e00" <= c <= "\u0e7f")
    return thai / len(text) > 0.15


def _llm_translate_batch(texts: List[str], client: OpenAI) -> List[str]:
    """Batch-translate non-English (Thai) captions/comments to English.
    Index-tagged response mapping (not array position) — source text
    with embedded newlines can make the model split/merge items,
    silently misaligning a plain ordered array."""
    if not texts:
        return []
    numbered = "\n".join(f"{i + 1}. {t}" for i, t in enumerate(texts))
    prompt = f"""Translate these {len(texts)} Thai-language skincare/Instagram posts or comments to English.
For each one, return an object with:
- "i": the item's number as shown below (integer)
- "t": the English translation (natural, concise)

Return ONLY a JSON array of objects, one per item, no other text.

Items:
{numbered}"""
    by_index: Dict[int, str] = {}
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
                if isinstance(idx, int) and 1 <= idx <= len(texts):
                    by_index[idx] = str(p.get("t", texts[idx - 1]))
        if len(by_index) != len(texts):
            log.warning(f"[LLM] Translate batch: expected {len(texts)}, got {len(by_index)} indexed")
    except Exception as e:
        log.warning(f"[LLM] Translate batch failed: {e}")

    return [by_index.get(i + 1, texts[i]) for i in range(len(texts))]


def _llm_classify_batch(texts_en: List[str], client: OpenAI) -> List[dict]:
    """Batch sentiment + purchase-barrier + on-topic classification."""
    if not texts_en:
        return []
    fallback = {"sentiment": "neutral", "is_purchase_barrier_signal": False, "is_acne_relevant": True}
    numbered = "\n".join(f"{i + 1}. {t}" for i, t in enumerate(texts_en))
    prompt = f"""Classify these {len(texts_en)} Instagram comments left on acne/skincare brand posts.
For each comment, return an object with:
- "i": the comment's number as shown below (integer)
- "sentiment": one of "positive", "negative", "neutral", "mixed"
- "is_purchase_barrier_signal": true if the comment expresses a reason for not buying/switching (price, availability, breakouts/irritation, trust, counterfeit concern, etc.), else false
- "is_acne_relevant": true if the comment is actually about the skincare product/brand, false if it's off-topic chatter (a generic emoji reaction, praise for an unrelated influencer, spam)

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
                        "is_acne_relevant": bool(p.get("is_acne_relevant", True)),
                    }
        if len(by_index) != len(texts_en):
            log.warning(f"[LLM] Classify batch: expected {len(texts_en)}, got {len(by_index)} indexed")
    except Exception as e:
        log.warning(f"[LLM] Classify batch failed: {e}")

    return [by_index.get(i + 1, fallback) for i in range(len(texts_en))]


def _llm_brand_relevance_batch(items: List[dict], client: OpenAI) -> List[bool]:
    """True if a post is actually about the brand it was tagged with at
    discovery, not just generic skincare content or a different brand's
    product that happens to co-tag the same hashtag. Multi-brand
    resellers on TH marketplaces commonly hashtag-stuff several brand
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
stated brand's acne/skincare products. TH resellers commonly hashtag-stuff many brand names onto a
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
    matching. Without this, an alias like "clean and clear" never matches
    a campaign hashtag like "#CleanandClearxProxie" — hashtags never
    contain spaces, so any multi-word brand name silently misses every
    hashtag mention of itself and falls through to the LLM (which may
    also miss it, as observed on real Clean & Clear data: two genuine
    #CleanandClearxProxie posts were wrongly flagged not-brand-relevant
    before this fix)."""
    return re.sub(r"[\s\-'_]", "", s).lower()


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
        "caption_en":       caption,  # placeholder, overwritten below if non-English
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
        "is_acne_relevant": int(_is_acne_relevant(caption)),
        "brand_relevant":   None,  # filled in below
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
        "comment_text_en":  text,  # placeholder, overwritten below if non-English
        "like_count":       item.get("likeCount", 0),
        "published_at":     item.get("createdAt", ""),
        "content_hash":     content_hash,
        "scraped_at":       now,
        "sentiment":        None,
        "is_purchase_barrier_signal": None,
        "is_acne_relevant": None,
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
    ("hashtag", "acneaid") or ("profile", "official_account_th").
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

    # Translate non-English captions
    non_en_idxs = [i for i, p in enumerate(posts) if _is_non_english(p["caption"])]
    for start in range(0, len(non_en_idxs), TRANSLATE_BATCH_SIZE):
        batch_idxs = non_en_idxs[start:start + TRANSLATE_BATCH_SIZE]
        translations = _llm_translate_batch([posts[i]["caption"] for i in batch_idxs], client)
        for idx, translation in zip(batch_idxs, translations):
            posts[idx]["caption_en"] = translation

    # Brand-relevance check — is each post actually about the brand it was
    # tagged with, not just co-tagged/hashtag-stuffed content
    for start in range(0, len(posts), BRAND_RELEVANCE_BATCH_SIZE):
        batch = posts[start:start + BRAND_RELEVANCE_BATCH_SIZE]
        items = [{"caption": p["caption_en"], "owner_username": p["owner_username"], "brand": p["brand"]} for p in batch]
        results = check_brand_relevance(items, client)
        for p, is_relevant in zip(batch, results):
            p["brand_relevant"] = is_relevant

    all_comments: List[dict] = []
    if not skip_comments:
        post_urls = [p["url"] for p in posts if p["url"]]
        post_id_by_url = {p["url"]: p["post_id"] for p in posts if p["url"]}
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

        # Translate non-English comments
        non_en_c_idxs = [i for i, c in enumerate(all_comments) if _is_non_english(c["comment_text"])]
        for start in range(0, len(non_en_c_idxs), TRANSLATE_BATCH_SIZE):
            batch_idxs = non_en_c_idxs[start:start + TRANSLATE_BATCH_SIZE]
            translations = _llm_translate_batch([all_comments[i]["comment_text"] for i in batch_idxs], client)
            for idx, translation in zip(batch_idxs, translations):
                all_comments[idx]["comment_text_en"] = translation

        # Sentiment + purchase-barrier classification
        for start in range(0, len(all_comments), CLASSIFY_BATCH_SIZE):
            batch = all_comments[start:start + CLASSIFY_BATCH_SIZE]
            labels = _llm_classify_batch([c["comment_text_en"] for c in batch], client)
            for c, label in zip(batch, labels):
                c["sentiment"] = label["sentiment"]
                c["is_purchase_barrier_signal"] = label["is_purchase_barrier_signal"]
                c["is_acne_relevant"] = label["is_acne_relevant"]

    return posts, all_comments


def save_posts(conn: sqlite3.Connection, posts: List[dict]) -> int:
    inserted = 0
    for p in posts:
        cur = conn.execute(
            """INSERT OR IGNORE INTO ig_posts
               (post_id, brand, market, hashtag, source_type, source_value, caption, caption_en,
                hashtags, owner_username, owner_full_name, location_name, location_id,
                likes_count, comments_count, post_type, published_at, url,
                discovered_at, is_acne_relevant, brand_relevant)
               VALUES (?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?)""",
            (
                p["post_id"], p["brand"], p["market"], p["hashtag"], p["source_type"], p["source_value"],
                p["caption"], p["caption_en"], p["hashtags"], p["owner_username"], p["owner_full_name"],
                p["location_name"], p["location_id"], p["likes_count"], p["comments_count"],
                p["post_type"], p["published_at"], p["url"], p["discovered_at"],
                p["is_acne_relevant"],
                int(p["brand_relevant"]) if p["brand_relevant"] is not None else None,
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
                    sentiment, is_purchase_barrier_signal, is_acne_relevant)
                   VALUES (?,?,?,?,?,?,?,?,?,?,?,?,?)""",
                (
                    c["post_id"], c["brand"], c["market"], c["author"],
                    c["comment_text"], c["comment_text_en"], c["like_count"],
                    c["published_at"], c["content_hash"], c["scraped_at"],
                    c["sentiment"], c["is_purchase_barrier_signal"], c["is_acne_relevant"],
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
    db_path: str = "output/instagram_data_th.db",
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
                print(f"\n=== {brand} / {market} — {len(posts)} posts, {len(comments)} comments (DRY RUN) ===")
                for p in posts[:5]:
                    print(f"  {p['caption_en'][:60]!r} | likes={p['likes_count']} | {p['url']}")
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


def classify_existing(db_path: str = "output/instagram_data_th.db") -> int:
    """Backfill sentiment/is_purchase_barrier_signal/is_acne_relevant for
    comments missing is_acne_relevant. Safe to re-run."""
    client = OpenAI()
    conn = open_db(db_path)
    rows = conn.execute(
        "SELECT id, comment_text_en FROM ig_comments WHERE is_acne_relevant IS NULL"
    ).fetchall()
    log.info(f"[CLASSIFY] {len(rows)} comments missing classification")

    classified = 0
    for start in range(0, len(rows), CLASSIFY_BATCH_SIZE):
        batch = rows[start:start + CLASSIFY_BATCH_SIZE]
        labels = _llm_classify_batch([r["comment_text_en"] for r in batch], client)
        for row, label in zip(batch, labels):
            conn.execute(
                """UPDATE ig_comments
                   SET sentiment = ?, is_purchase_barrier_signal = ?, is_acne_relevant = ?
                   WHERE id = ?""",
                (
                    label["sentiment"], int(label["is_purchase_barrier_signal"]),
                    int(label["is_acne_relevant"]), row["id"],
                ),
            )
            classified += 1
        conn.commit()
        log.info(f"[CLASSIFY] {classified}/{len(rows)} done")

    conn.close()
    log.info(f"[CLASSIFY] Done — {classified} comments classified")
    return classified


def backfill_brand_relevance(db_path: str = "output/instagram_data_th.db", recheck_negatives: bool = False) -> int:
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


if __name__ == "__main__":
    parser = argparse.ArgumentParser(description="Instagram social-listening module (standalone) — Acne-Aid Thailand")
    parser.add_argument("--market", nargs="+", default=["TH"], help="e.g. --market TH")
    parser.add_argument("--brand", nargs="+", help='e.g. --brand "Acne-Aid"')
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
        help="Backfill brand-relevance (posts) and sentiment/purchase-barrier labels "
             "(comments) for already-saved data, then exit",
    )
    parser.add_argument(
        "--recheck-negatives", action="store_true",
        help="Used with --classify-existing: also re-checks posts already flagged "
             "brand_relevant=0, not just unchecked (NULL) ones. Needed after a change "
             "to check_brand_relevance() itself (e.g. the alias-normalization fix) — "
             "otherwise already-flagged-0 rows are never revisited since they aren't NULL.",
    )
    parser.add_argument(
        "--force-rescrape", action="store_true",
        help="Re-call Apify for sources already scraped before (by default, a source "
             "with an entry in ig_scraped_sources is skipped to avoid re-paying for the "
             "same hashtag/profile pull). Use this to pick up new organic posts on a "
             "hashtag/profile you've already scraped.",
    )
    args = parser.parse_args()

    if args.classify_existing:
        backfill_brand_relevance(recheck_negatives=args.recheck_negatives)
        classify_existing()
    else:
        run(
            markets=args.market,
            brand_filter=args.brand,
            max_posts=args.max_posts,
            dry_run=args.dry_run,
            skip_comments=args.skip_comments,
            source_mode=args.source,
            force_rescrape=args.force_rescrape,
        )
