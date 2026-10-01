"""
KiasuParents Singapore — Contact Lens Intelligence Scraper
Standalone script reusing the `pipeline_th.py` architecture (SQLite WAL, 
single-writer queue, Pydantic LLM extraction).
"""

import hashlib
import json
import logging
import queue
import sqlite3
import threading
import time
import urllib.parse
from concurrent.futures import ThreadPoolExecutor, as_completed
from datetime import datetime, timezone
from pathlib import Path
from typing import List, Optional

import requests
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

# ── DATABASE SCHEMA ──────────────────────────────────────────────────────
SCHEMA = """
CREATE TABLE IF NOT EXISTS forum_posts (
    id INTEGER PRIMARY KEY AUTOINCREMENT,
    brand TEXT NOT NULL,
    site TEXT NOT NULL,
    post_title TEXT,
    post_date TEXT,
    post_url TEXT,
    content_summary TEXT,
    topic_tags TEXT,
    content_hash TEXT UNIQUE,
    scraped_at TEXT
);
CREATE INDEX IF NOT EXISTS idx_posts_brand ON forum_posts(brand);
"""

def open_db(path: str) -> sqlite3.Connection:
    conn = sqlite3.connect(path, check_same_thread=False, timeout=60)
    conn.row_factory = sqlite3.Row
    conn.execute("PRAGMA journal_mode=WAL")
    conn.execute("PRAGMA synchronous=NORMAL")
    conn.executescript(SCHEMA)
    conn.commit()
    return conn

def _db_writer(path: str, write_q: queue.Queue, done: threading.Event) -> None:
    conn = sqlite3.connect(path, timeout=60)
    conn.execute("PRAGMA journal_mode=WAL")
    
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
            
        rows = item
        for r in rows:
            try:
                conn.execute(
                    """INSERT OR IGNORE INTO forum_posts 
                    (brand, site, post_title, post_date, post_url, 
                    content_summary, topic_tags, content_hash, scraped_at) 
                    VALUES (?,?,?,?,?,?,?,?,?)""",
                    (
                        r["brand"], r["site"], r["post_title"], r["post_date"], 
                        r["post_url"], r["content_summary"], r.get("topic_tags"), 
                        r["content_hash"], r["scraped_at"],
                    ),
                )
            except Exception as e:
                log.warning(f"[DB] Insert error: {e}")
        conn.commit()
        write_q.task_done()
    conn.close()

# ── LLM EXTRACTION MODELS ────────────────────────────────────────────────
class ForumPost(BaseModel):
    post_title: str = Field(description="Thread or post title")
    post_date: str = Field(description="Date if visible, else empty string")
    content_summary: str = Field(description="A 1-3 sentence faithful paraphrase of the discussion regarding contact lenses (e.g., Acuvue).")
    sentiment: str = Field(description="One of: positive, negative, mixed, neutral")
    topics: List[str] = Field(description="Tags like 'pricing', 'comfort', 'astigmatism', 'myopia control', 'optometrist recommendation'")

class ForumPostPage(BaseModel):
    posts: List[ForumPost] = Field(description="Relevant discussion threads found on the page")

def _llm_extract(text_blob: str, brand_name: str, client: OpenAI) -> List[ForumPost]:
    if not text_blob.strip():
        return []
    prompt = f"""The text below is from KiasuParents.com (a Singaporean parenting forum) discussing "{brand_name}".
Identify distinct threads or posts actually discussing this brand of contact lenses.
For each relevant item, extract: post_title, post_date, a faithful paraphrase (do not quote verbatim), sentiment, and topic tags.
Ignore navigation, ads, and unrelated discussions.

TEXT:
{text_blob}"""
    try:
        resp = client.beta.chat.completions.parse(
            model="gpt-4o-mini",
            messages=[{"role": "user", "content": prompt}],
            response_format=ForumPostPage,
            max_tokens=2000,
        )
        return resp.choices[0].message.parsed.posts or []
    except Exception as e:
        log.warning(f"[LLM] Extraction failed: {e}")
        return []

# ── KIASUPARENTS SCRAPER ─────────────────────────────────────────────────
# Pagination confirmed working (2026-09-24, live test): appending &page=2
# etc. to the search URL returns a genuinely different NodeBB results page
# (not a repeat of page 1). Same for-loop-with-break pattern as
# discover_boots_th() in pipeline_th.py: cap at _MAX_PAGES, stop early as
# soon as a page yields zero relevant posts from the LLM.
_KIASUPARENTS_MAX_PAGES = 10

def discover_kiasuparents(brands: List[str], client: OpenAI, write_q: queue.Queue) -> int:
    headers = {
        "User-Agent": "Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 (KHTML, like Gecko) Chrome/124.0.0.0 Safari/537.36"
    }
    now = datetime.now(timezone.utc).isoformat()
    total_extracted = 0

    for brand in brands:
        # KiasuParents uses NodeBB/standard forum search parameters
        keyword = urllib.parse.quote(brand)
        brand_extracted = 0
        prev_text_hash = None

        for page in range(1, _KIASUPARENTS_MAX_PAGES + 1):
            search_url = f"https://forum.kiasuparents.com/search?term={keyword}&in=titlesposts"
            if page > 1:
                search_url += f"&page={page}"
            log.info(f"[DISCOVER] KiasuParents | {brand} | page {page} | URL: {search_url}")

            try:
                resp = requests.get(search_url, headers=headers, timeout=20)
                resp.raise_for_status()
            except Exception as e:
                log.warning(f"[DISCOVER] Request failed for {brand} page {page}: {e}")
                break

            soup = BeautifulSoup(resp.text, "html.parser")
            for tag in soup(["script", "style", "nav", "footer"]):
                tag.decompose()

            # Take the first 15k characters of visible text to fit into the LLM context window
            text_blob = soup.get_text(" ", strip=True)[:15_000]

            # NodeBB search runs out of real results well before page 10 for
            # some keywords (observed 2026-09-24: Acuvue and Alcon both hit
            # the page cap without ever returning 0 posts) and starts
            # repeating the last real page verbatim -- the LLM then
            # "re-extracts" the same threads as new results each time,
            # burning API calls without adding data (content_hash dedup on
            # insert kept the DB correct, but the run wasted ~3-4 LLM calls
            # per brand). Hash the visible text and stop BEFORE calling the
            # LLM if it's identical to the previous page.
            text_hash = hashlib.md5(text_blob.encode()).hexdigest()
            if text_hash == prev_text_hash:
                log.info(f"[DISCOVER] KiasuParents | {brand} | page {page}: identical to previous page, stopping pagination.")
                break
            prev_text_hash = text_hash

            extracted = _llm_extract(text_blob, brand, client)
            if not extracted:
                log.info(f"[DISCOVER] KiasuParents | {brand} | page {page}: 0 relevant posts, stopping pagination.")
                break

            batch = []
            for p in extracted:
                raw_key = f"{brand}|kiasuparents|{p.post_title}|{p.content_summary[:50]}"
                c_hash = hashlib.md5(raw_key.encode()).hexdigest()
                batch.append({
                    "brand": brand,
                    "site": "kiasuparents",
                    "post_title": p.post_title,
                    "post_date": p.post_date,
                    "post_url": search_url,
                    "content_summary": p.content_summary,
                    "topic_tags": json.dumps({"sentiment": p.sentiment, "topics": p.topics}),
                    "content_hash": c_hash,
                    "scraped_at": now,
                })

            if batch:
                write_q.put(batch)
                brand_extracted += len(batch)

            log.info(f"[DISCOVER] KiasuParents | {brand} | page {page}: {len(batch)} relevant posts extracted.")
            time.sleep(3.0)

        total_extracted += brand_extracted
        log.info(f"[DISCOVER] KiasuParents | {brand}: {brand_extracted} relevant posts extracted total.")

    return total_extracted


# ── HARDWAREZONE FORUMS (confirmed blocked -- login-gated search) ────────
# CONFIRMED NOT WORKING (2026-09-24, live test): forums.hardwarezone.com.sg
# is a XenForo forum. Its homepage loads fine anonymously (HTTP 200), but
# the search endpoint (/search/?q={keyword}) returns HTTP 403 with
# data-template="login" / data-logged-in="false" in the response body --
# i.e. XenForo redirects unauthenticated search requests to the login page
# rather than serving results. No page-parameter loop can get past this;
# it's an auth gate, not a pagination or bot-fingerprint issue (same
# category of dead end as discover_watsons_th() in pipeline_th.py, for a
# different underlying reason). Would need a logged-in session (cookies
# from a real account) or an Apify/browser-automation actor that can log
# in -- not a plain `requests` scrape. Kept as an interface stub so it can
# be swapped later without changing how the orchestrator calls it.

def discover_hardwarezone_sg(brands: List[str], client: OpenAI, write_q: queue.Queue) -> int:
    """CONFIRMED NOT WORKING (tested 2026-09-24): see module notes above.
    Currently always returns 0 without making any request."""
    log.warning("[DISCOVER] HardwareZone: SKIPPED -- confirmed login-gated search "
                "(XenForo /search/ returns the login page to anonymous requests). "
                "Needs an authenticated session or browser automation, not a plain scrape.")
    return 0

# ── ORCHESTRATOR ─────────────────────────────────────────────────────────
if __name__ == "__main__":
    db_path = "sg_acuvue.db"
    open_db(db_path)
    
    client = OpenAI()
    write_q = queue.Queue()
    done_evt = threading.Event()
    
    writer = threading.Thread(target=_db_writer, args=(db_path, write_q, done_evt))
    writer.start()

    # Matches sku_query_master_sg.csv's canonical brand list/casing (minus
    # "Mixed", the grey-market generic-listing sweep category -- not a real
    # brand name, so not meaningful to search for on a parenting forum).
    brands_to_track = ["ACUVUE", "Alcon", "CooperVision", "Bausch & Lomb", "Olens"]
    
    log.info("Starting KiasuParents extraction pipeline...")
    extracted_count = discover_kiasuparents(brands_to_track, client, write_q)

    # Confirmed blocked (login-gated search) -- always returns 0, see
    # discover_hardwarezone_sg() docstring. Called here so it shows up in
    # the run log rather than being silently absent from the pipeline.
    extracted_count += discover_hardwarezone_sg(brands_to_track, client, write_q)

    done_evt.set()
    write_q.put(None)
    writer.join()
    
    log.info(f"Pipeline complete. {extracted_count} posts saved to {db_path}.")