# ==================================================================
# google_maps_scraper_sg.py -- Optical retailer sentiment (Google Maps), SG
# ==================================================================
# Consideration-stage signal: store-level friction at optical retailers
# (fitting/queue wait times, upsell pressure such as "buy 6 get 1 free",
# staff/fitting quality) ahead of a fitting appointment.
#
# Same architecture as reddit_scraper_sg.py / instagram_scraper_sg.py:
# Apify actor -> GPT classify -> SQLite. One actor
# (compass/crawler-google-places) returns places AND their reviews.
#
# Setup: APIFY_TOKEN and OPENAI_API_KEY in .env
# Run from the project root:
#   python Scripts/google_maps_scraper_sg.py --dry-run
#   python Scripts/google_maps_scraper_sg.py --max-places 3 --max-reviews 30
# ==================================================================

import argparse
import json
import logging
import os
import re
import sqlite3
import time
from pathlib import Path
from typing import Dict, List

import requests
from dotenv import load_dotenv
from openai import OpenAI

load_dotenv()

logging.basicConfig(level=logging.INFO, format="%(asctime)s [%(levelname)s] %(message)s")
log = logging.getLogger(__name__)

APIFY_BASE = "https://api.apify.com/v2"
ACTOR = "compass/crawler-google-places"

# chain -> (Google Maps search string, name regex a returned place must match)
# Only chains confirmed to sell ACUVUE in SG (checked 2026-09-30 via their SG
# sites/search): Owndays, Better Vision, Capitol Optical, Visio Optical list
# ACUVUE products; Optical 88 participates in MyACUVUE points; Nanyang Optical
# has an ACUVUE review on its blog but no product page found (weaker evidence).
# Watsons Optical has no separate Google Maps listings (only general Watsons
# pharmacy stores), so it is excluded.
RETAILERS = {
    "Optical 88": ("Optical 88", r"optical\s*88"),
    "Owndays": ("Owndays", r"owndays"),
    "Better Vision": ("Better Vision optical", r"better\s*vision"),
    "Capitol Optical": ("Capitol Optical", r"capitol\s*optical"),
    "Visio Optical": ("Visio Optical", r"visio\s*optical"),
    "Nanyang Optical": ("Nanyang Optical", r"nanyang\s*optical"),
}

THEMES = ["wait_time", "upsell_pressure", "staff_fitting_quality", "pricing", "loyalty_points", "stock_availability"]


class CostTracker:
    INPUT_COST = 0.150 / 1_000_000
    OUTPUT_COST = 0.600 / 1_000_000

    def __init__(self):
        self.i = self.o = 0

    def add(self, usage):
        self.i += getattr(usage, "prompt_tokens", 0)
        self.o += getattr(usage, "completion_tokens", 0)

    def report(self):
        log.info(f"[COST] {self.i:,} in + {self.o:,} out = ${self.i * self.INPUT_COST + self.o * self.OUTPUT_COST:.4f}")


cost_tracker = CostTracker()


def run_actor(token: str, run_input: dict, label: str, max_wait_attempts: int = 90) -> List[dict]:
    r = requests.post(f"{APIFY_BASE}/acts/{ACTOR.replace('/', '~')}/runs",
                      json=run_input, params={"token": token}, timeout=30)
    if not r.ok:
        log.error(f"[{label}] start failed {r.status_code}: {r.text[:800]}")
    r.raise_for_status()
    data = r.json()["data"]
    run_id, dataset_id = data["id"], data["defaultDatasetId"]
    log.info(f"[{label}] run started run_id={run_id}")
    final = None
    for attempt in range(max_wait_attempts):
        time.sleep(10)
        final = requests.get(f"{APIFY_BASE}/actor-runs/{run_id}", params={"token": token}, timeout=15).json()["data"]
        log.info(f"[{label}] status={final['status']} (attempt {attempt + 1})")
        if final["status"] == "SUCCEEDED":
            break
        if final["status"] in ("FAILED", "ABORTED", "TIMED-OUT"):
            log.error(f"[{label}] ended with {final['status']}: {final.get('statusMessage', '')}")
            break
    else:
        raise TimeoutError(f"[{label}] run {run_id} did not finish in time")
    items = requests.get(f"{APIFY_BASE}/datasets/{dataset_id}/items",
                         params={"token": token, "format": "json"}, timeout=120)
    items.raise_for_status()
    items = items.json()
    log.info(f"[{label}] retrieved {len(items)} items | cost: {final.get('usageTotalUsd') if final else None}")
    return items


def open_db(path: str) -> sqlite3.Connection:
    Path(path).parent.mkdir(parents=True, exist_ok=True)
    conn = sqlite3.connect(path)
    conn.executescript("""
        CREATE TABLE IF NOT EXISTS gmaps_places (
            place_id TEXT PRIMARY KEY, chain TEXT, name TEXT, address TEXT, neighborhood TEXT,
            rating REAL, reviews_count INTEGER, category TEXT, phone TEXT, website TEXT,
            url TEXT, lat REAL, lng REAL, fetched_at TEXT DEFAULT CURRENT_TIMESTAMP
        );
        CREATE TABLE IF NOT EXISTS gmaps_reviews (
            review_id TEXT PRIMARY KEY, place_id TEXT, chain TEXT, place_name TEXT,
            rating INTEGER, text TEXT, published_at TEXT, likes INTEGER, owner_response TEXT,
            sentiment TEXT, themes TEXT, is_friction INTEGER, is_lens_related INTEGER,
            fetched_at TEXT DEFAULT CURRENT_TIMESTAMP
        );
    """)
    return conn


def classify_batch(texts: List[str], client: OpenAI) -> List[dict]:
    fallback = {"sentiment": "neutral", "themes": [], "is_friction": False, "is_lens_related": False}
    if not texts:
        return []
    numbered = "\n".join(f"{i + 1}. {t[:600]}" for i, t in enumerate(texts))
    prompt = f"""Classify these {len(texts)} Google Maps reviews of optical retail stores in Singapore.
For each return an object with:
- "i": review number (integer)
- "sentiment": "positive" | "negative" | "neutral" | "mixed"
- "themes": list drawn ONLY from {THEMES}. wait_time = queue/fitting/appointment/collection delays; upsell_pressure = hard sell, bundle/promo pushing (e.g. "buy 6 get 1 free"); staff_fitting_quality = optometrist/staff skill, rushed or thorough eye test/fitting; pricing = price/transparency; loyalty_points = membership/points/MyACUVUE redemption; stock_availability = lens/brand out of stock
- "is_friction": true ONLY if the reviewer complains about or describes a negative experience that could put a customer off a fitting/purchase. Praise is never friction, and do not assign a friction theme (wait_time, upsell_pressure, stock_availability) to a review that praises it (e.g. "fast and efficient" is NOT a wait_time issue; a salesperson who explained well is NOT upsell_pressure)
- "is_lens_related": true ONLY if the review explicitly concerns CONTACT lenses (buying, fitting, trial, eye test for contacts, contact-lens brands such as ACUVUE, solution, "contacts"). Reviews about spectacles, frames, glasses or spectacle lenses (progressive, single-vision, coatings) are false even if they mention an eye test
Return ONLY a JSON array, no other text.

Reviews:
{numbered}"""
    by_i: Dict[int, dict] = {}
    try:
        resp = client.chat.completions.create(model="gpt-4o-mini", max_tokens=3000,
                                              messages=[{"role": "user", "content": prompt}])
        cost_tracker.add(resp.usage)
        raw = re.sub(r"^```(?:json)?\s*|\s*```$", "", resp.choices[0].message.content.strip(), flags=re.M).strip()
        for o in json.loads(raw):
            by_i[int(o["i"])] = o
    except Exception as e:
        log.warning(f"[LLM] classify failed, using fallback: {e}")
    out = []
    for i in range(1, len(texts) + 1):
        o = by_i.get(i, fallback)
        out.append({
            "sentiment": o.get("sentiment", "neutral"),
            "themes": [t for t in o.get("themes", []) if t in THEMES],
            "is_friction": bool(o.get("is_friction", False)),
            "is_lens_related": bool(o.get("is_lens_related", False)),
        })
    return out


def reclassify_lens(db_path: str):
    """Re-tag is_lens_related on existing reviews with the strict contact-lens
    definition (no re-scrape, OpenAI cost only). Also stores a deterministic
    keyword flag in cl_keyword for cross-checking."""
    conn = open_db(db_path)
    cols = [r[1] for r in conn.execute("PRAGMA table_info(gmaps_reviews)")]
    if "cl_keyword" not in cols:
        conn.execute("ALTER TABLE gmaps_reviews ADD COLUMN cl_keyword INTEGER")
    client = OpenAI()
    rows = conn.execute("SELECT review_id, text FROM gmaps_reviews").fetchall()
    kw = re.compile(r"contact\s*lens|\bcontacts\b|acuvue|\bdailies\b|biofinity|air\s*optix|ortho-?k|myopia\s*control|"
                    r"\bCLs?\b|lens\s*solution|1[- ]day\b", re.I)
    for s in range(0, len(rows), 20):
        batch = rows[s:s + 20]
        cls = classify_batch([t for _, t in batch], client)
        for (rid, t), c in zip(batch, cls):
            conn.execute("UPDATE gmaps_reviews SET is_lens_related=?, cl_keyword=? WHERE review_id=?",
                         (int(c["is_lens_related"]), int(bool(kw.search(t))), rid))
        conn.commit()
        if (s // 20) % 20 == 0:
            log.info(f"[reclassify] {s + len(batch)}/{len(rows)}")
    cost_tracker.report()
    conn.close()


def run(args):
    if args.reclassify_lens:
        return reclassify_lens(args.db)
    token = os.getenv("APIFY_TOKEN", "").strip()
    if not token:
        log.error("[SETUP] APIFY_TOKEN not found in .env")
        return
    chains = {c: RETAILERS[c] for c in (args.chain or RETAILERS)}
    conn = open_db(args.db)
    client = OpenAI() if not args.dry_run else None

    for chain, (query, name_re) in chains.items():
        run_input = {
            "searchStringsArray": [query],
            "locationQuery": "Singapore",
            "countryCode": "sg",
            "language": "en",
            "maxCrawledPlacesPerSearch": args.max_places,
            "maxReviews": args.max_reviews,
            "reviewsSort": "newest",
            "scrapeReviewerName": False,
            "scrapeReviewerId": False,
            "scrapeReviewerUrl": False,
        }
        items = run_actor(token, run_input, chain)
        items = [it for it in items if re.search(name_re, it.get("title") or "", re.I)]
        log.info(f"[{chain}] {len(items)} places matched the chain name")
        if args.dry_run:
            for it in items[:3]:
                print(it.get("title"), it.get("totalScore"), it.get("reviewsCount"), len(it.get("reviews") or []))
            continue

        for it in items:
            pid = it.get("placeId")
            if not pid:
                continue
            loc = it.get("location") or {}
            conn.execute("INSERT OR REPLACE INTO gmaps_places (place_id,chain,name,address,neighborhood,rating,"
                         "reviews_count,category,phone,website,url,lat,lng) VALUES (?,?,?,?,?,?,?,?,?,?,?,?,?)",
                         (pid, chain, it.get("title"), it.get("address"), it.get("neighborhood"),
                          it.get("totalScore"), it.get("reviewsCount"), it.get("categoryName"),
                          it.get("phone"), it.get("website"), it.get("url"), loc.get("lat"), loc.get("lng")))
            revs = [r for r in (it.get("reviews") or []) if (r.get("text") or "").strip()]
            known = {r[0] for r in conn.execute("SELECT review_id FROM gmaps_reviews WHERE place_id=?", (pid,))}
            revs = [r for r in revs if (r.get("reviewId") or "") not in known and r.get("reviewId")]
            for s in range(0, len(revs), 20):
                batch = revs[s:s + 20]
                cls = classify_batch([r["text"] for r in batch], client)
                for r, c in zip(batch, cls):
                    conn.execute("INSERT OR REPLACE INTO gmaps_reviews (review_id,place_id,chain,place_name,rating,"
                                 "text,published_at,likes,owner_response,sentiment,themes,is_friction,is_lens_related) "
                                 "VALUES (?,?,?,?,?,?,?,?,?,?,?,?,?)",
                                 (r["reviewId"], pid, chain, it.get("title"), r.get("stars"), r["text"],
                                  r.get("publishedAtDate"), r.get("likesCount"), r.get("responseFromOwnerText"),
                                  c["sentiment"], ",".join(c["themes"]), int(c["is_friction"]),
                                  int(c["is_lens_related"])))
            conn.commit()
            log.info(f"[{chain}] {it.get('title')}: {len(revs)} new reviews saved")
    cost_tracker.report()
    conn.close()


if __name__ == "__main__":
    p = argparse.ArgumentParser(description="Google Maps optical-retailer sentiment -- SG")
    p.add_argument("--chain", nargs="+", choices=list(RETAILERS), help="default: all")
    p.add_argument("--max-places", type=int, default=3, help="outlets per chain")
    p.add_argument("--max-reviews", type=int, default=30, help="newest reviews per outlet")
    p.add_argument("--dry-run", action="store_true", help="scrape + print, save/classify nothing")
    p.add_argument("--reclassify-lens", action="store_true",
                   help="re-tag is_lens_related on existing reviews (strict contact-lens definition); no scraping")
    p.add_argument("--db", default=str(Path(__file__).resolve().parent / "output" / "gmaps_data_sg.db"))
    run(p.parse_args())
