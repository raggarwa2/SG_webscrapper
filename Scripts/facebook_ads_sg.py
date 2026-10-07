# ==================================================================
# Meta Ad Library Module — MyACUVUE Singapore (standalone)
# ==================================================================
# Purpose: pull competitor ADS (creative copy, run dates, platforms)
#   for the SG contact-lens competitive set from the public Meta Ad
#   Library. Singapore only: every Ad Library URL is built with
#   country=SG, and rows whose page/ad text is clearly another market
#   can be filtered downstream via the stored `page_name`.
#
# Why keyword search, not page IDs: we only have one verified page ID
#   (Bausch + Lomb). Keyword search per brand name catches the brand's
#   own page AND resellers/retailers advertising the brand in SG, which
#   is useful signal; `page_name` is stored so the two can be split.
#   Alcon has no SG organic page, but ads for "Air Optix"/"Dailies"
#   served to SG users still appear here.
#
# Own SQLite db (facebook_ads_sg.db), separate from facebook_data_sg.db.
# Not wired into any pipeline.
#
# Usage:
#   python facebook_ads_sg.py --dry-run          # 1 brand, 5 ads, print sample
#   python facebook_ads_sg.py                    # all brands
#   python facebook_ads_sg.py --brand "Alcon" --max-ads 100
#   python facebook_ads_sg.py --export-csv
# ==================================================================

import argparse
import csv
import hashlib
import json
import logging
import os
import sqlite3
import time
from datetime import datetime, timezone
from pathlib import Path
from typing import List, Optional
from urllib.parse import quote_plus

import requests
from dotenv import load_dotenv

load_dotenv()
logging.basicConfig(level=logging.INFO, format="%(asctime)s [%(levelname)s] %(message)s")
log = logging.getLogger(__name__)

APIFY_BASE = "https://api.apify.com/v2"
ADS_ACTOR = "apify/facebook-ads-scraper"
COUNTRY = "SG"  # hard-coded: Singapore only

# brand -> Ad Library keyword queries
QUERIES = {
    "MyACUVUE":      ["acuvue", "myacuvue"],
    "Alcon":         ["air optix", "alcon contact lens", "dailies total1"],
    "CooperVision":  ["coopervision", "myday contact lens", "biofinity"],
    "Bausch + Lomb": ["bausch lomb contact lens", "biotrue oneday", "lacelle"],
}

# The Ad Library returns ads that reach SG, but this actor exposes no
# advertiser-country field, so foreign advertisers (BR, GR, UA, HK...)
# come through. sg_verified is set ONLY for pages confirmed as SG
# entities; everything else stays 0 until a human verifies it.
SG_VERIFIED_PAGES = {"acuvue sg", "bausch and lomb singapore"}

BRAND_TERMS = ["acuvue", "alcon", "air optix", "dailies total", "dailies aqua", "total30", "coopervision", "myday ",
               "biofinity", "clariti", "bausch", "lomb", "biotrue", "lacelle", "contact lens", "contact lenses"]


SCHEMA = """
CREATE TABLE IF NOT EXISTS fb_ads (
    ad_key        TEXT PRIMARY KEY,
    brand         TEXT NOT NULL,
    query         TEXT,
    ad_id         TEXT,
    page_name     TEXT,
    page_id       TEXT,
    ad_text       TEXT,
    headline      TEXT,
    cta           TEXT,
    link_url      TEXT,
    is_active     INTEGER,
    start_date    TEXT,
    end_date      TEXT,
    platforms     TEXT,
    ad_library_url TEXT,
    raw_json      TEXT,
    scraped_at    TEXT,
    sg_verified   INTEGER DEFAULT 0,
    brand_relevant INTEGER DEFAULT 0
);
CREATE INDEX IF NOT EXISTS idx_fb_ads_brand ON fb_ads(brand);
"""


def open_db(path: str) -> sqlite3.Connection:
    Path(path).parent.mkdir(parents=True, exist_ok=True)
    conn = sqlite3.connect(path, timeout=60)
    conn.row_factory = sqlite3.Row
    conn.executescript(SCHEMA)
    conn.commit()
    return conn


def run_actor(token: str, actor_id: str, run_input: dict, label: str, max_wait_attempts: int = 60) -> List[dict]:
    slug = actor_id.replace("/", "~")
    r = requests.post(f"{APIFY_BASE}/acts/{slug}/runs", json=run_input, params={"token": token}, timeout=30)
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
        if final["status"] == "SUCCEEDED":
            break
        if final["status"] in ("FAILED", "ABORTED", "TIMED-OUT"):
            log.error(f"[{label}] ended with {final['status']}: {final.get('statusMessage', '')}")
            break
    else:
        raise TimeoutError(f"[{label}] run {run_id} did not finish in time")
    items = requests.get(f"{APIFY_BASE}/datasets/{dataset_id}/items",
                         params={"token": token, "format": "json"}, timeout=60).json()
    log.info(f"[{label}] retrieved {len(items)} items | cost: {final.get('usageTotalUsd') if final else None}")
    return items


def ad_library_url(query: str, active_status: str = "all") -> str:
    return (
        "https://www.facebook.com/ads/library/?"
        f"active_status={active_status}&ad_type=all&country={COUNTRY}"
        f"&q={quote_plus(query)}&search_type=keyword_unordered&media_type=all"
    )


def _pick(d: dict, *keys, default=None):
    for k in keys:
        if isinstance(d, dict) and d.get(k) not in (None, ""):
            return d[k]
    return default


def extract_ad(raw: dict, brand: str, query: str) -> Optional[dict]:
    snap = raw.get("snapshot") or {}
    body = snap.get("body")
    ad_text = body.get("text") if isinstance(body, dict) else (body or _pick(raw, "adText", "text", default=""))
    ad_id = _pick(raw, "adArchiveID", "ad_archive_id", "adArchiveId", "id", default="")
    page_name = _pick(snap, "pageName", "page_name") or _pick(raw, "pageName", "page_name", default="")
    page_id = _pick(raw, "pageID", "page_id", "pageId", default="") or snap.get("pageId", "")
    if not ad_id and not ad_text:
        return None
    key = hashlib.md5(f"{ad_id}|{page_id}|{(ad_text or '')[:80]}".encode()).hexdigest()
    plats = _pick(raw, "publisherPlatform", "publisher_platform", default=[])
    return {
        "ad_key": key, "brand": brand, "query": query, "ad_id": str(ad_id),
        "page_name": page_name, "page_id": str(page_id), "ad_text": ad_text or "",
        "headline": _pick(snap, "title", "linkDescription", "link_description", default=""),
        "cta": _pick(snap, "ctaText", "cta_text", default=""),
        "link_url": _pick(snap, "linkUrl", "link_url", default=""),
        "is_active": int(bool(_pick(raw, "isActive", "is_active", default=False))),
        "start_date": str(_pick(raw, "startDateFormatted", "startDate", "start_date", default="")),
        "end_date": str(_pick(raw, "endDateFormatted", "endDate", "end_date", default="")),
        "platforms": ",".join(plats) if isinstance(plats, list) else str(plats),
        "ad_library_url": _pick(raw, "adLibraryUrl", "url", default=""),
        "raw_json": json.dumps(raw, default=str)[:20000],
        "scraped_at": datetime.now(timezone.utc).isoformat(),
        "sg_verified": int((page_name or "").strip().lower() in SG_VERIFIED_PAGES),
        "brand_relevant": int(any(t in f"{ad_text} {page_name}".lower() for t in BRAND_TERMS)),
    }


def save_ads(conn: sqlite3.Connection, ads: List[dict]) -> int:
    n = 0
    for a in ads:
        cur = conn.execute(
            """INSERT OR IGNORE INTO fb_ads (ad_key, brand, query, ad_id, page_name, page_id, ad_text,
               headline, cta, link_url, is_active, start_date, end_date, platforms, ad_library_url,
               raw_json, scraped_at, sg_verified, brand_relevant) VALUES (:ad_key,:brand,:query,:ad_id,:page_name,:page_id,:ad_text,
               :headline,:cta,:link_url,:is_active,:start_date,:end_date,:platforms,:ad_library_url,
               :raw_json,:scraped_at,:sg_verified,:brand_relevant)""", a)
        n += cur.rowcount
    conn.commit()
    return n


def export_csv(db_path: str, output_dir: str) -> None:
    conn = open_db(db_path)
    rows = conn.execute(
        "SELECT brand, query, page_name, ad_text, headline, cta, link_url, is_active, start_date, "
        "end_date, platforms, ad_library_url, sg_verified, brand_relevant FROM fb_ads ORDER BY brand, start_date DESC").fetchall()
    path = Path(output_dir) / f"facebook_ads_sg_{datetime.now():%Y%m%d_%H%M}.csv"
    with open(path, "w", newline="", encoding="utf-8-sig") as f:
        w = csv.writer(f)
        if rows:
            w.writerow(rows[0].keys())
            w.writerows(tuple(r) for r in rows)
    log.info(f"[EXPORT] {path.name}: {len(rows)} rows")


if __name__ == "__main__":
    p = argparse.ArgumentParser(description="Meta Ad Library (Singapore only)")
    p.add_argument("--brand", nargs="+")
    p.add_argument("--max-ads", type=int, default=50, help="Per-query ad cap")
    p.add_argument("--dry-run", action="store_true", help="First query only, 5 ads, print sample, save nothing")
    p.add_argument("--actor", default=ADS_ACTOR)
    p.add_argument("--db", default="output/facebook_ads_sg.db")
    p.add_argument("--output-dir", default="output")
    p.add_argument("--export-csv", action="store_true")
    a = p.parse_args()

    if a.export_csv:
        export_csv(a.db, a.output_dir)
        raise SystemExit(0)

    token = os.getenv("APIFY_TOKEN", "").strip()
    if not token:
        log.error("[SETUP] APIFY_TOKEN not found in .env")
        raise SystemExit(1)

    conn = None if a.dry_run else open_db(a.db)
    total = 0
    for brand, queries in QUERIES.items():
        if a.brand and brand.lower() not in [b.lower() for b in a.brand]:
            continue
        for q in queries:
            limit = 5 if a.dry_run else a.max_ads
            try:
                raw = run_actor(token, a.actor,
                                {"startUrls": [{"url": ad_library_url(q)}], "resultsLimit": limit},
                                f"ads:{brand}:{q}")
            except Exception as e:
                log.error(f"[ADS] {brand} | {q}: {e}")
                continue
            if a.dry_run:
                log.info(f"[DRY-RUN] {brand} | {q}: {len(raw)} ads; sample keys="
                         f"{list(raw[0].keys()) if raw else '(none)'}")
                if raw:
                    log.info(json.dumps(raw[0], default=str)[:1500])
                raise SystemExit(0)
            ads = [x for x in (extract_ad(r, brand, q) for r in raw) if x]
            n = save_ads(conn, ads)
            total += n
            log.info(f"[ADS] {brand} | {q}: {n} new ({len(ads)} parsed)")
            time.sleep(1.0)
    if conn:
        conn.close()
        export_csv(a.db, a.output_dir)
    log.info(f"Done. {total} new ads saved.")
