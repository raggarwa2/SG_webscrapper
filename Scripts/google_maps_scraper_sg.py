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
#
# Deeper pulls over outlets already in gmaps_places (by placeId, no new discovery):
#   python Scripts/google_maps_scraper_sg.py --deep --cl-search --plan     # sizes only, no calls
#   python Scripts/google_maps_scraper_sg.py --cl-search                   # Google review keyword filter per CL term
#   python Scripts/google_maps_scraper_sg.py --deep --deep-reviews 300     # more newest reviews per outlet
# --cl-search is the efficient route: Google returns only reviews matching the term,
# so a 3,500-review Owndays outlet costs the same as a small one.
# ==================================================================

import argparse
import hashlib
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
    # Added 2026-10-07 as coverage gaps (no Google Maps data yet). Not yet checked
    # against their SG sites for ACUVUE stock like the chains above. Guardian and
    # Unity are pharmacies, so most of their reviews are not about contact lenses:
    # after discovery, --cl-search picks the contact-lens ones out.
    "Guardian": ("Guardian pharmacy", r"guardian"),
    "Unity": ("Unity pharmacy", r"unity"),
    "Zoff": ("Zoff", r"zoff"),
}

THEMES = ["wait_time", "upsell_pressure", "staff_fitting_quality", "pricing", "loyalty_points", "stock_availability"]

# Terms for --cl-search, passed one per run as the actor's reviewsFilterString
# (Google's own "search reviews" box; one term per run, no OR syntax assumed).
# Each term is a full pass over all outlets, and a review matched by several
# terms is saved once, so terms are grouped by how contact-lens-specific they are.
CL_TERMS_CORE = [
    # generic wording
    "contact lens", "contact lenses", "contacts", "contact lense", "CL",
    "first time contact lens", "contact lens fitting", "contact lens trial", "trial lenses",
    # lens types
    "daily disposable", "dailies", "1 day", "monthly lenses", "monthlies", "2 weekly", "disposable lenses",
    "toric", "astigmatism lenses", "multifocal contact", "silicone hydrogel", "soft lens", "hard lens",
    "RGP", "scleral", "extended wear", "overnight lens",
    # cosmetic / colour
    "colour lens", "color lens", "coloured contact", "circle lens", "cosmetic lens", "beauty lens", "big eyes lens",
    # myopia control / ortho-k
    "ortho-k", "orthokeratology", "myopia control", "MiSight", "Defocus",
    # brands and product lines
    "acuvue", "myacuvue", "oasys", "biofinity", "air optix",
    # ACUVUE sub-brands, incl. reviewers dropping the "acuvue" word and the 1-day spelling variants
    "1-day acuvue moist", "acuvue define", "1 day moist", "1 day define", "1 day max", "1day", "1-day", "oneday", "one-day",
    "oasys max", "oasys 1-day", "oasys for astigmatism", "oasys for presbyopia", "oasys transitions", "hydraclear",
    "trueye", "acuvue vita", "acuvue advance", "abiliti", "moist for astigmatism",
    "dailies total1", "proclear", "clariti", "biotrue", "soflens", "bausch", "alcon", "coopervision",
    "freshlook", "lacelle", "olens", "menicon", "pegavision", "clalen", "hapa kristin", "eyecloud",
    # solution and accessories
    "lens solution", "multipurpose solution", "saline", "lens case", "opti-free", "renu", "rewetting drops",
]
# Broader terms: mostly surface spectacle reviews, so expect a low contact-lens
# yield. is_lens_related + cl_keyword still keep the strict filter honest.
CL_TERMS_BROAD = [
    # symptoms / problems when wearing
    "dry eyes", "irritation", "red eyes", "discomfort", "blurry", "allergic", "infection", "cornea",
    "lens fell out", "torn lens", "lost lens", "wrong lens", "wrong power",
    # wearing / handling
    "wear contacts", "wearing contacts", "put on contacts", "remove contacts", "insert", "taught me how", "teach me how",
    # purchase and process friction
    "buy 6 get 1", "box of lenses", "boxes", "prescription", "eye test", "fitting", "trial", "free trial", "sample",
    "refit", "reorder", "repeat purchase", "regular customer", "not allowed to buy", "must do eye test",
    "bundle", "package", "promo", "subscription", "delivery", "online order",
    # loyalty / app / stock
    "moist", "define", "max", "one day",  # bare sub-brand words / spelling: very ambiguous ("one day I went")
    "johnson", "seed", "member", "points", "rebate", "redeem", "register", "app", "out of stock", "no stock", "order in", "waiting time",
    # pricing
    "price", "expensive", "cheaper", "discount",
]
CL_TERMS = CL_TERMS_CORE  # default; --cl-tier all adds CL_TERMS_BROAD

# Same keyword flag reclassify_lens()/--rekeyword write to cl_keyword; the
# dashboard's strict `contact_lens` = is_lens_related AND cl_keyword.
CL_KW = re.compile(
    r"contact\s*lens|contact\s*lense|\bcontacts\b|\bcontact\b.{0,25}\b(?:wear|wearer|fitting|trial|solution)|"
    r"acuvue|\boneday\b|\bone-day\b|\b1day\b|trueye|true\s*eye\s*lens|hydraclear|\bdailies\b|\bmonthlies\b|biofinity|air\s*optix|oasys|proclear|clariti|biotrue|soflens|freshlook|lacelle|"
    r"olens|menicon|pegavision|clalen|hapa\s*kristin|eyecloud|misight|ortho-?k|orthokeratology|myopia\s*control|"
    r"\bCLs?\b|lens\s*solution|multi-?purpose\s*solution|opti-?free|\brenu\b|lens\s*case|rewetting|"
    r"circle\s*lens|colou?red?\s*lens|cosmetic\s*lens|beauty\s*lens|big\s*eyes?\s*lens|\btoric\b|scleral|\bRGP\b|"
    r"silicone\s*hydrogel|1[- ]day\b|daily\s*disposable|disposable\s*lens", re.I)



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
        CREATE TABLE IF NOT EXISTS gmaps_search_log (
            pass_key TEXT PRIMARY KEY, term TEXT, max_reviews INTEGER, n_places INTEGER,
            items_returned INTEGER, reviews_returned INTEGER, new_saved INTEGER,
            done_at TEXT DEFAULT CURRENT_TIMESTAMP
        );
        CREATE TABLE IF NOT EXISTS gmaps_reviews (
            review_id TEXT PRIMARY KEY, place_id TEXT, chain TEXT, place_name TEXT,
            rating INTEGER, text TEXT, published_at TEXT, likes INTEGER, owner_response TEXT,
            sentiment TEXT, themes TEXT, is_friction INTEGER, is_lens_related INTEGER,
            fetched_at TEXT DEFAULT CURRENT_TIMESTAMP
        );
    """)
    cols = {r[1] for r in conn.execute("PRAGMA table_info(gmaps_reviews)")}
    for col in ("cl_keyword INTEGER", "search_term TEXT"):  # search_term: --cl-search term that surfaced the review
        if col.split()[0] not in cols:
            conn.execute(f"ALTER TABLE gmaps_reviews ADD COLUMN {col}")
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
    for s in range(0, len(rows), 20):
        batch = rows[s:s + 20]
        cls = classify_batch([t for _, t in batch], client)
        for (rid, t), c in zip(batch, cls):
            conn.execute("UPDATE gmaps_reviews SET is_lens_related=?, cl_keyword=? WHERE review_id=?",
                         (int(c["is_lens_related"]), int(bool(CL_KW.search(t))), rid))
        conn.commit()
        if (s // 20) % 20 == 0:
            log.info(f"[reclassify] {s + len(batch)}/{len(rows)}")
    cost_tracker.report()
    conn.close()


def rekeyword(db_path: str):
    conn = open_db(db_path)
    rows = conn.execute("SELECT review_id, text, cl_keyword FROM gmaps_reviews").fetchall()
    new = [(int(bool(CL_KW.search(t or ""))), rid) for rid, t, _ in rows]
    changed = sum(1 for (n, _), (_, _, old) in zip(new, rows) if n != (old or 0))
    conn.executemany("UPDATE gmaps_reviews SET cl_keyword=? WHERE review_id=?", new)
    conn.commit()
    log.info(f"[rekeyword] {len(rows)} reviews, {changed} changed, {sum(n for n, _ in new)} flagged")
    conn.close()


def run(args):
    if args.reclassify_lens:
        return reclassify_lens(args.db)
    if args.rekeyword:
        return rekeyword(args.db)
    token = os.getenv("APIFY_TOKEN", "").strip()
    if not token and not args.plan:
        log.error("[SETUP] APIFY_TOKEN not found in .env")
        return
    chains = {c: RETAILERS[c] for c in (args.chain or RETAILERS)}
    conn = open_db(args.db)
    client = OpenAI() if not (args.dry_run or args.plan) else None

    if args.deep or args.cl_search:
        run_known_places(args, conn, client, token, list(chains))
        cost_tracker.report()
        conn.close()
        return

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
            n = save_reviews(conn, client, chain, pid, it.get("title"), it.get("reviews") or [])
            log.info(f"[{chain}] {it.get('title')}: {n} new reviews saved")
    cost_tracker.report()
    conn.close()


def save_reviews(conn: sqlite3.Connection, client: OpenAI, chain: str, pid: str, title: str,
                 reviews: List[dict], term: str = None) -> int:
    """Classify and insert reviews not already in the DB (by review_id, across all
    places, so a review found by several --cl-search terms is saved once)."""
    revs, seen = [], set()
    for r in reviews:
        rid = r.get("reviewId")
        if not rid or rid in seen or not (r.get("text") or "").strip():
            continue
        seen.add(rid)
        revs.append(r)
    if revs:
        q = ",".join("?" * len(revs))
        known = {x[0] for x in conn.execute(f"SELECT review_id FROM gmaps_reviews WHERE review_id IN ({q})",
                                            [r["reviewId"] for r in revs])}
        revs = [r for r in revs if r["reviewId"] not in known]
    for s in range(0, len(revs), 20):
        batch = revs[s:s + 20]
        cls = classify_batch([r["text"] for r in batch], client)
        for r, c in zip(batch, cls):
            conn.execute("INSERT OR REPLACE INTO gmaps_reviews (review_id,place_id,chain,place_name,rating,"
                         "text,published_at,likes,owner_response,sentiment,themes,is_friction,is_lens_related,"
                         "cl_keyword,search_term) VALUES (?,?,?,?,?,?,?,?,?,?,?,?,?,?,?)",
                         (r["reviewId"], pid, chain, title, r.get("stars"), r["text"],
                          r.get("publishedAtDate"), r.get("likesCount"), r.get("responseFromOwnerText"),
                          c["sentiment"], ",".join(c["themes"]), int(c["is_friction"]),
                          int(c["is_lens_related"]), int(bool(CL_KW.search(r["text"]))), term))
    conn.commit()
    return len(revs)


def known_places(conn: sqlite3.Connection, chains: List[str], min_reviews: int) -> List[tuple]:
    """(place_id, chain, name) of outlets already discovered, biggest first."""
    q = ",".join("?" * len(chains))
    return conn.execute(f"SELECT place_id, chain, name FROM gmaps_places WHERE chain IN ({q}) "
                        "AND COALESCE(reviews_count,0) >= ? ORDER BY reviews_count DESC",
                        [*chains, min_reviews]).fetchall()


def run_known_places(args, conn: sqlite3.Connection, client: OpenAI, token: str, chains: List[str]):
    """--deep / --cl-search: re-visit outlets already in gmaps_places by placeId (no new
    discovery search). --deep pulls up to --deep-reviews newest reviews per outlet;
    --cl-search runs one pass per CL_TERMS term with reviewsFilterString, so Google
    returns only the matching reviews (up to --cl-reviews per outlet per term)."""
    places = known_places(conn, chains, args.min_reviews)
    chain_of = {pid: ch for pid, ch, _ in places}
    # (label, term, per-outlet cap)
    passes = [("deep", None, args.deep_reviews)] if args.deep else []
    if args.cl_search:
        terms = args.cl_terms or (CL_TERMS_CORE + CL_TERMS_BROAD if args.cl_tier == "all" else CL_TERMS_CORE)
        passes += [(f"cl:{t}", t, args.cl_reviews) for t in dict.fromkeys(terms)]
    n = args.places_per_run
    chunks = [places[i:i + n] for i in range(0, len(places), n)]

    if args.plan:
        todo = 0
        for label, term, cap in passes:
            n_done = 0
            for chunk in chunks:
                k = f"{term or 'deep'}|{cap}|" + hashlib.md5(",".join(sorted(pid for pid, _, _ in chunk)).encode()).hexdigest()[:12]
                n_done += bool(conn.execute("SELECT 1 FROM gmaps_search_log WHERE pass_key=?", (k,)).fetchone())
            todo += len(chunks) - n_done
            print(f"{label:<24} {len(places)} outlets in {len(chunks)} runs ({n_done} already done), up to {cap} reviews/outlet "
                  f"= at most {len(places) * cap:,} reviews")
        print(f"Runs still to do: {todo} of {len(passes) * len(chunks)}. Outlets: "
              + ", ".join(f"{c} {sum(1 for _, ch, _ in places if ch == c)}" for c in chains))
        return

    for label, term, cap in passes:
        for ci, chunk in enumerate(chunks, 1):
            run_input = {
                "placeIds": [pid for pid, _, _ in chunk],
                "language": "en",
                "maxReviews": cap,
                "reviewsSort": "newest",
                "scrapeReviewerName": False,
                "scrapeReviewerId": False,
                "scrapeReviewerUrl": False,
            }
            if term:
                run_input["reviewsFilterString"] = term
            tag = f"{label} {ci}/{len(chunks)}"
            key = f"{term or 'deep'}|{cap}|" + hashlib.md5(",".join(sorted(pid for pid, _, _ in chunk)).encode()).hexdigest()[:12]
            if not args.rerun and conn.execute("SELECT 1 FROM gmaps_search_log WHERE pass_key=?", (key,)).fetchone():
                log.info(f"[{tag}] already done, skipping (use --rerun to repeat)")
                continue
            items = run_actor(token, run_input, tag, max_wait_attempts=360)
            if args.dry_run:
                for it in items[:5]:
                    print(it.get("title"), it.get("reviewsCount"), len(it.get("reviews") or []))
                continue
            total = returned = 0
            for it in items:
                pid = it.get("placeId")
                if pid not in chain_of:
                    continue
                returned += len(it.get("reviews") or [])
                total += save_reviews(conn, client, chain_of[pid], pid, it.get("title"),
                                      it.get("reviews") or [], term)
            conn.execute("INSERT OR REPLACE INTO gmaps_search_log (pass_key,term,max_reviews,n_places,items_returned,"
                         "reviews_returned,new_saved) VALUES (?,?,?,?,?,?,?)",
                         (key, term, cap, len(chunk), len(items), returned, total))
            conn.commit()
            log.info(f"[{tag}] {returned} reviews returned, {total} new saved")


if __name__ == "__main__":
    p = argparse.ArgumentParser(description="Google Maps optical-retailer sentiment -- SG")
    p.add_argument("--chain", nargs="+", choices=list(RETAILERS), help="default: all")
    p.add_argument("--max-places", type=int, default=3, help="outlets per chain")
    p.add_argument("--max-reviews", type=int, default=30, help="newest reviews per outlet")
    p.add_argument("--dry-run", action="store_true", help="scrape + print, save/classify nothing")
    p.add_argument("--deep", action="store_true",
                   help="re-visit outlets already in the DB and pull up to --deep-reviews newest reviews each")
    p.add_argument("--deep-reviews", type=int, default=300, help="--deep: reviews per outlet")
    p.add_argument("--cl-search", action="store_true",
                   help="re-visit outlets already in the DB, one pass per contact-lens term, "
                        "using Google's review keyword filter (reviewsFilterString)")
    p.add_argument("--cl-reviews", type=int, default=200, help="--cl-search: matching reviews per outlet per term")
    p.add_argument("--cl-tier", choices=["core", "all"], default="core",
                   help=f"--cl-search term list: core ({len(CL_TERMS_CORE)} contact-lens-specific terms, default) "
                        f"or all (+{len(CL_TERMS_BROAD)} broad terms that mostly surface spectacle reviews)")
    p.add_argument("--cl-terms", nargs="+", help="--cl-search: explicit terms, overrides --cl-tier")
    p.add_argument("--rekeyword", action="store_true",
                   help="recompute cl_keyword on existing reviews with the current CL_KW regex; no scraping, no LLM cost")
    p.add_argument("--min-reviews", type=int, default=0,
                   help="--deep/--cl-search: skip outlets whose Google review count is below this")
    p.add_argument("--places-per-run", type=int, default=45,
                   help="--deep/--cl-search: outlets per Apify run (use ~20 for --deep, whose runs are much longer)")
    p.add_argument("--rerun", action="store_true",
                   help="--deep/--cl-search: repeat passes already recorded in gmaps_search_log (default: skip them)")
    p.add_argument("--plan", action="store_true",
                   help="--deep/--cl-search: print runs and review ceilings, no Apify/OpenAI calls")
    p.add_argument("--reclassify-lens", action="store_true",
                   help="re-tag is_lens_related on existing reviews (strict contact-lens definition); no scraping")
    p.add_argument("--db", default=str(Path(__file__).resolve().parent / "output" / "gmaps_data_sg.db"))
    run(p.parse_args())
