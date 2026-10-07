# ==================================================================
# Facebook Retailer Module — MyACUVUE Singapore (standalone)
# ==================================================================
# Purpose: pull consumer REVIEWS (Facebook "Recommendations") and recent
#   POSTS from Singapore contact-lens retailers' official Pages, so
#   purchase-channel friction (price, service, fitting, stock, loyalty)
#   can be read at the retailer level. Singapore only.
#
# Handles below were found via web search 2026-10-07 and are the
#   Singapore Pages only (e.g. owndays.sg, not owndays global; Better
#   Vision = bettervisionsg, not the MY page). Re-verify with --dry-run.
#   Google Maps retailer data is handled elsewhere -- NOT in this module.
#
# Reviews are kept whole, then flagged is_lens_related by regex (flag,
#   not drop), same whitelist approach as facebook_scraper_sg.py.
#   Big pages (Watsons ~14M, Guardian ~2.5M followers) get the same
#   per-page cap, so lens relevance matters more there.
#
# Own db: facebook_retailers_sg.db. Not wired into any pipeline.
#
# Usage:
#   python facebook_retailers_sg.py --dry-run --retailer "Better Vision"
#   python facebook_retailers_sg.py --max-reviews 100 --max-posts 50
#   python facebook_retailers_sg.py --export-csv
# ==================================================================

import argparse
import csv
import hashlib
import json
import logging
import os
import re
import sqlite3
import time
from datetime import datetime, timezone
from pathlib import Path
from typing import List, Optional

import requests
from dotenv import load_dotenv

load_dotenv()
logging.basicConfig(level=logging.INFO, format="%(asctime)s [%(levelname)s] %(message)s")
log = logging.getLogger(__name__)

APIFY_BASE = "https://api.apify.com/v2"
REVIEWS_ACTOR = "apify/facebook-reviews-scraper"
POSTS_ACTOR = "apify/facebook-posts-scraper"

# retailer -> (type, SG page handle)
RETAILERS = {
    "Owndays":        ("Optical chain",       "owndays.sg"),
    "Better Vision":  ("Optical chain",       "bettervisionsg"),
    "Capitol Optical": ("Optical chain",      "capitolopticalsg"),
    "Nanyang Optical": ("Optical chain",      "NanyangOptical"),
    "Optical 88":     ("Optical chain",       "OPTICAL88SG"),
    "Visio Optical":  ("Optical independent", "visiooptical"),
    "Zoff":           ("Optical chain",       "zoffsg"),
    "Lenskart SG":    ("Online/optical",      "lenskartsg"),
    "Watsons SG":     ("Drugstore",           "watsons.sg"),
    "Guardian SG":    ("Drugstore",           "guardiansg"),
    "Unity Pharmacy": ("Drugstore",           "UnityPharmacySG"),
}

LENS_TERMS = [
    "contact lens", "contact lenses", "contacts", "lens", "lenses", "daily disposable",
    "acuvue", "air optix", "dailies", "coopervision", "biofinity", "myday", "bausch",
    "biotrue", "ortho-k", "myopia control", "astigmatism", "toric", "solution",
    "隐形", "隱形",
]
_LENS_RE = re.compile("|".join(re.escape(t) for t in LENS_TERMS), re.IGNORECASE)

FRICTION_TERMS = [
    "expensive", "price", "overpriced", "cost", "rude", "wait", "waiting", "queue", "refund",
    "out of stock", "no stock", "unavailable", "pushy", "hard sell", "prescription", "points",
    "membership", "voucher", "warranty", "wrong", "mistake", "irritat", "pain", "uncomfortable",
    "dry", "slow", "disappoint", "complain",
]
_FRICTION_RE = re.compile("|".join(re.escape(t) for t in FRICTION_TERMS), re.IGNORECASE)

SCHEMA = """
CREATE TABLE IF NOT EXISTS fb_retailer_reviews (
    review_key    TEXT PRIMARY KEY,
    retailer      TEXT NOT NULL,
    retailer_type TEXT,
    page          TEXT,
    reviewer      TEXT,
    recommended   INTEGER,
    text          TEXT,
    likes         INTEGER,
    published_at  TEXT,
    is_lens_related INTEGER,
    has_friction_term INTEGER,
    scraped_at    TEXT
);
CREATE TABLE IF NOT EXISTS fb_retailer_posts (
    post_id       TEXT PRIMARY KEY,
    retailer      TEXT NOT NULL,
    retailer_type TEXT,
    page          TEXT,
    text          TEXT,
    likes_count   INTEGER,
    shares_count  INTEGER,
    published_at  TEXT,
    url           TEXT,
    is_lens_related INTEGER,
    scraped_at    TEXT
);
CREATE TABLE IF NOT EXISTS fb_retailer_sources (
    retailer TEXT, kind TEXT, page TEXT, last_scraped_at TEXT, items_found INTEGER,
    PRIMARY KEY (retailer, kind)
);
"""


def open_db(path: str) -> sqlite3.Connection:
    Path(path).parent.mkdir(parents=True, exist_ok=True)
    conn = sqlite3.connect(path, timeout=60)
    conn.row_factory = sqlite3.Row
    conn.executescript(SCHEMA)
    conn.commit()
    return conn


def run_actor(token: str, actor_id: str, run_input: dict, label: str, max_wait_attempts: int = 90) -> List[dict]:
    slug = actor_id.replace("/", "~")
    r = requests.post(f"{APIFY_BASE}/acts/{slug}/runs", json=run_input, params={"token": token}, timeout=30)
    if not r.ok:
        log.error(f"[{label}] start failed {r.status_code}: {r.text[:800]}")
    r.raise_for_status()
    data = r.json()["data"]
    run_id, dataset_id = data["id"], data["defaultDatasetId"]
    log.info(f"[{label}] run started run_id={run_id}")
    final = None
    for _ in range(max_wait_attempts):
        time.sleep(10)
        final = requests.get(f"{APIFY_BASE}/actor-runs/{run_id}", params={"token": token}, timeout=15).json()["data"]
        if final["status"] == "SUCCEEDED":
            break
        if final["status"] in ("FAILED", "ABORTED", "TIMED-OUT"):
            log.error(f"[{label}] ended with {final['status']}: {final.get('statusMessage', '')}")
            break
    else:
        raise TimeoutError(f"[{label}] run {run_id} did not finish in time")
    items = requests.get(f"{APIFY_BASE}/datasets/{dataset_id}/items",
                         params={"token": token, "format": "json"}, timeout=120).json()
    log.info(f"[{label}] retrieved {len(items)} items | cost: {final.get('usageTotalUsd') if final else None}")
    return items


def _pick(d, *keys, default=None):
    for k in keys:
        if isinstance(d, dict) and d.get(k) not in (None, ""):
            return d[k]
    return default


def extract_review(raw: dict, retailer: str, rtype: str, page: str) -> Optional[dict]:
    text = _pick(raw, "text", "reviewText", "message", default="")
    if not text:
        return None
    user = raw.get("user") if isinstance(raw.get("user"), dict) else {}
    reviewer = _pick(user, "name") or _pick(raw, "profileName", "userName", "author", default="")
    rid = _pick(raw, "id", "reviewId", "url", default="")
    rec = _pick(raw, "isRecommended", "recommended", "recommendationType", default=None)
    if isinstance(rec, str):
        rec = 1 if rec.lower() in ("positive", "recommended", "true", "yes") else 0
    elif rec is not None:
        rec = int(bool(rec))
    return {
        "review_key": hashlib.md5(f"{page}|{rid}|{text[:80]}".encode()).hexdigest(),
        "retailer": retailer, "retailer_type": rtype, "page": page, "reviewer": reviewer,
        "recommended": rec, "text": text,
        "likes": _pick(raw, "likesCount", "likes", default=0),
        "published_at": str(_pick(raw, "date", "time", "timestamp", "creation_time", default="")),
        "is_lens_related": int(bool(_LENS_RE.search(text))),
        "has_friction_term": int(bool(_FRICTION_RE.search(text))),
        "scraped_at": datetime.now(timezone.utc).isoformat(),
    }


def extract_post(raw: dict, retailer: str, rtype: str, page: str) -> Optional[dict]:
    pid = _pick(raw, "postId", "id", "post_id")
    if not pid:
        return None
    text = _pick(raw, "text", "message", "caption", default="")
    return {
        "post_id": str(pid), "retailer": retailer, "retailer_type": rtype, "page": page, "text": text,
        "likes_count": _pick(raw, "likes", "likesCount", "reactionsCount", default=0),
        "shares_count": _pick(raw, "shares", "sharesCount", default=0),
        "published_at": _pick(raw, "time", "date", "timestamp", default=""),
        "url": _pick(raw, "topLevelUrl", "url", "postUrl", default=""),
        "is_lens_related": int(bool(_LENS_RE.search(text or ""))),
        "scraped_at": datetime.now(timezone.utc).isoformat(),
    }


def _save(conn, table: str, rows: List[dict], key: str) -> int:
    n = 0
    for r in rows:
        cols = ",".join(r)
        ph = ",".join(f":{c}" for c in r)
        n += conn.execute(f"INSERT OR IGNORE INTO {table} ({cols}) VALUES ({ph})", r).rowcount
    conn.commit()
    return n


def export_csvs(db_path: str, output_dir: str) -> None:
    conn = open_db(db_path)
    ts = datetime.now().strftime("%Y%m%d_%H%M")
    for name, q in {
        f"facebook_retailer_reviews_sg_{ts}.csv":
            "SELECT retailer, retailer_type, reviewer, recommended, text, likes, published_at, "
            "is_lens_related, has_friction_term FROM fb_retailer_reviews ORDER BY retailer, published_at DESC",
        f"facebook_retailer_posts_sg_{ts}.csv":
            "SELECT retailer, retailer_type, text, likes_count, shares_count, published_at, url, "
            "is_lens_related FROM fb_retailer_posts ORDER BY retailer, published_at DESC",
    }.items():
        rows = conn.execute(q).fetchall()
        with open(Path(output_dir) / name, "w", newline="", encoding="utf-8-sig") as f:
            w = csv.writer(f)
            if rows:
                w.writerow(rows[0].keys())
                w.writerows(tuple(r) for r in rows)
        log.info(f"[EXPORT] {name}: {len(rows)} rows")


if __name__ == "__main__":
    p = argparse.ArgumentParser(description="Facebook retailer reviews/posts (Singapore only)")
    p.add_argument("--retailer", nargs="+")
    p.add_argument("--max-reviews", type=int, default=100)
    p.add_argument("--max-posts", type=int, default=50)
    p.add_argument("--skip-posts", action="store_true")
    p.add_argument("--skip-reviews", action="store_true")
    p.add_argument("--dry-run", action="store_true", help="5 reviews + 3 posts per selected retailer, print sample, save nothing")
    p.add_argument("--force-rescrape", action="store_true")
    p.add_argument("--db", default="output/facebook_retailers_sg.db")
    p.add_argument("--output-dir", default="output")
    p.add_argument("--export-csv", action="store_true")
    a = p.parse_args()

    if a.export_csv:
        export_csvs(a.db, a.output_dir)
        raise SystemExit(0)

    token = os.getenv("APIFY_TOKEN", "").strip()
    if not token:
        log.error("[SETUP] APIFY_TOKEN not found in .env")
        raise SystemExit(1)

    conn = None if a.dry_run else open_db(a.db)
    done = set()
    if conn and not a.force_rescrape:
        done = {(r["retailer"], r["kind"]) for r in conn.execute("SELECT retailer, kind FROM fb_retailer_sources")}

    tot_r = tot_p = 0
    for retailer, (rtype, page) in RETAILERS.items():
        if a.retailer and retailer.lower() not in [x.lower() for x in a.retailer]:
            continue
        url = f"https://www.facebook.com/{page}"
        if not a.skip_reviews and (retailer, "reviews") not in done:
            lim = 5 if a.dry_run else a.max_reviews
            try:
                raw = run_actor(token, REVIEWS_ACTOR, {"startUrls": [{"url": url}], "resultsLimit": lim},
                                f"reviews:{retailer}")
            except Exception as e:
                log.error(f"[REVIEWS] {retailer}: {e}")
                raw = []
            if a.dry_run:
                log.info(f"[DRY-RUN] {retailer} reviews: {len(raw)}; keys={list(raw[0].keys()) if raw else '(none)'}")
                if raw:
                    log.info(json.dumps(raw[0], default=str)[:700])
            else:
                rows = [x for x in (extract_review(r, retailer, rtype, page) for r in raw) if x]
                n = _save(conn, "fb_retailer_reviews", rows, "review_key")
                tot_r += n
                conn.execute("INSERT OR REPLACE INTO fb_retailer_sources VALUES (?,?,?,?,?)",
                             (retailer, "reviews", page, datetime.now(timezone.utc).isoformat(), len(raw)))
                conn.commit()
                log.info(f"[REVIEWS] {retailer}: {n} new ({len(rows)} with text, {len(raw)} raw)")
        if not a.skip_posts and (retailer, "posts") not in done:
            lim = 3 if a.dry_run else a.max_posts
            try:
                raw = run_actor(token, POSTS_ACTOR, {"startUrls": [{"url": url}], "resultsLimit": lim},
                                f"posts:{retailer}")
            except Exception as e:
                log.error(f"[POSTS] {retailer}: {e}")
                raw = []
            if a.dry_run:
                log.info(f"[DRY-RUN] {retailer} posts: {len(raw)}")
            else:
                rows = [x for x in (extract_post(r, retailer, rtype, page) for r in raw) if x]
                n = _save(conn, "fb_retailer_posts", rows, "post_id")
                tot_p += n
                conn.execute("INSERT OR REPLACE INTO fb_retailer_sources VALUES (?,?,?,?,?)",
                             (retailer, "posts", page, datetime.now(timezone.utc).isoformat(), len(raw)))
                conn.commit()
                log.info(f"[POSTS] {retailer}: {n} new ({len(raw)} raw)")
        time.sleep(1.0)

    if conn:
        conn.close()
        Path(a.output_dir).mkdir(parents=True, exist_ok=True)
        export_csvs(a.db, a.output_dir)
    log.info(f"Done. {tot_r} new reviews, {tot_p} new posts saved.")
