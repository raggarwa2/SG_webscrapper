# ==================================================================
# Reddit segment study (SG) -- persona study, eight audience segments
# ==================================================================
# Standalone: own db (output/reddit_segment_study.db) and own CSV folder.
# Does NOT write to reddit_data_sg.db, voice_items or any tagger, and the
# dashboard does not read it. Posts only (comments are billed per result by
# the actor, so skipComments is on).
#
# Reuses build_search_input / extract_post_fields / run helpers from
# reddit_scraper_sg.py (same actor, trudax/reddit-scraper-lite).
# Actor price (checked 2026-10-27): $0.02 per run start + $0.004 per
# result stored. A hard spend cap is enforced here from a ledger file.
#
# Usage:
#   python reddit_segment_study.py --stage pilot
#   python reddit_segment_study.py --stage scale
#   python reddit_segment_study.py --stage export
# ==================================================================

import argparse
import csv
import json
import os
import re
import sqlite3
import time
from datetime import datetime, timedelta, timezone
from pathlib import Path

import requests
from dotenv import load_dotenv

import reddit_scraper_sg as base

ROOT = Path(__file__).resolve().parent.parent
load_dotenv(ROOT / ".env")

DB_PATH = Path(os.getenv("SEGMENT_DB") or ROOT / "Scripts" / "output" / "reddit_segment_study.db")
LEDGER = ROOT / "Scripts" / "output" / "reddit_segment_study_ledger.json"
OUT_DIR = ROOT / "Handover" / "segment_study_2026-10" / "reddit"

CAP_USD = 5.00
START_FEE, PER_RESULT = 0.02, 0.004
WINDOW_MONTHS = 24
TODAY = datetime(2026, 10, 27, tzinfo=timezone.utc)
CUTOFF_24 = TODAY - timedelta(days=730)
CUTOFF_12 = TODAY - timedelta(days=365)

SEGMENTS = {
    "glasses_only": "Glasses-only wearers who never switched",
    "dropout": "Dropouts (back to glasses)",
    "part_timer": "Part-timers (occasional use)",
    "surgery": "Surgery choosers (LASIK, SMILE, ICL)",
    "student": "Students, teens and parents",
    "over40": "Over-40s (presbyopia, multifocal)",
    "sporty": "Sporty wearers",
    "screen_pro": "Screen-heavy professionals",
    "brand_only": "Brand keywords (no segment)",
}

# (segment, keyword). Sitewide queries get " Singapore" appended; the
# subreddit-scoped queries below do not need it.
SITEWIDE = [
    ("glasses_only", "never tried contacts"), ("glasses_only", "glasses vs contacts"),
    ("dropout", "stopped wearing contacts"), ("dropout", "back to glasses"),
    ("part_timer", "wear contacts occasionally"), ("part_timer", "contacts only sometimes"),
    ("surgery", "LASIK"), ("surgery", "SMILE eye surgery"), ("surgery", "ICL implantable lens"),
    ("student", "contacts for school"), ("student", "first contacts teen"),
    ("student", "contact lenses student"),
    ("over40", "presbyopia"), ("over40", "multifocal contact lenses"),
    ("over40", "reading glasses vs contacts"),
    ("sporty", "contacts swimming"), ("sporty", "contact lenses gym"),
    ("sporty", "contacts running"), ("sporty", "badminton contacts glasses"),
    ("screen_pro", "dry eyes work"), ("screen_pro", "eye strain screen"),
    ("screen_pro", "contact lenses dry eyes computer"),
    ("brand_only", "Acuvue"), ("brand_only", "Air Optix"), ("brand_only", "Biofinity"),
    ("brand_only", "Olens"), ("brand_only", "Bausch Lomb contact lens"),
]

# Subreddit-scoped queries: (segment, keyword). Segment is "" for generic terms and then
# comes from the text match (see text_segments).
SG_SUBS = ["askSingapore", "singapore", "SingaporeRaw", "SGExams", "NationalServiceSG",
           "singaporefi", "VisionCorrectionSG", "singaporeparents", "sgmums", "SingaporeHealth",
           "nus", "NTU", "sgfitness", "SingaporeFitness", "SGBeauty", "sgcareers"]
SG_SUB_QUERIES = [
    ("", "contact lenses"), ("surgery", "LASIK"), ("surgery", "SMILE ICL"),
    ("", "glasses or contacts"), ("screen_pro", "dry eyes"), ("over40", "presbyopia"),
]
GLOBAL_SUBS = ["contactlenses", "glasses", "lasik", "eyecare", "Optometry"]
GLOBAL_SUB_QUERIES = [("", "Singapore"), ("", "SGD")]

# Pilot = this many (query index) runs, chosen to touch every segment once.
PILOT_QUERIES = 10
SG_SUBS_LOWER = {x.lower() for x in SG_SUBS}

# ── relevance / filters ──────────────────────────────────────────────
_LENS_CTX = re.compile(r"\b(wear|wearing|wore|lens|lenses|eye|eyes|sight|myopi\w*|power|degree|solution|prescription|"
                       r"optical|optician|optometr\w*|daily|monthly|acuvue|disposable|irritat\w*|dry)\b", re.I)
_CONTACTS_WORD = re.compile(r"\bcontacts\b", re.I)
_ICL_SURGERY = re.compile(r"implantable collamer|evo icl|\bicl\s+(surgery|implant|lens|op|procedure|vs|or)\b|"
                          r"(lasik|smile|relex|surgery|myopi\w*).{0,40}\bicl\b|\bicl\b.{0,40}(lasik|smile|relex|surgery|myopi\w*)", re.I)
EYE_TERMS_CORE = re.compile(
    r"contact\s*lens|colou?red lens|circle lens|daily (disposable|lens)|monthly lens|"
    r"(?<!sun)(?<!beer )(?<!wine )(?<!drinking )(?<!ar )(?<!smart )(?<!vr )(?<!3d )(?<!shot )glasses\b|spectacles|"
    r"lasik|smile (surgery|procedure|eye)|relex|"
    r"presbyop|multifocal|bifocal|progressive lens|eye\s*strain|eyestrain|dry eye|"
    r"optometr|optician|ophthalm|eye (surgery|exam|test|doctor|power|number|degree|specialist)|"
    r"myopi|short-?sighted|astigmat|acuvue|air optix|biofinity|olens|bausch|coopervision|"
    r"eye prescription|prescription (lens|glasses|contact)", re.I)


class _EyeTerms:
    """Drop-in for the old regex object: .search(text) is truthy for lens / glasses / eye-surgery text."""
    @staticmethod
    def search(text):
        text = text or ""
        m = EYE_TERMS_CORE.search(text) or _ICL_SURGERY.search(text)
        if m:
            return m
        for cm in _CONTACTS_WORD.finditer(text):
            window = text[max(0, cm.start() - 60): cm.end() + 60]
            if _LENS_CTX.search(window):
                return cm
        return None


EYE_TERMS = _EyeTerms()
SG_MARKERS = re.compile(
    r"\bsgd\b|\bs\$|\bsingapore\b|\bsg\b|\bsingaporeans?\b|\b(lah|lor|leh|sia|meh)\b|\bsnec\b|\bttsh\b|"
    r"\bnus\b|\bntu\b|\bsmu\b|\bnsf\b|\bhdb\b|\bcpf\b|\borchard\b|\bbugis\b|\bjurong\b|\btampines\b|\bclementi\b|"
    r"\bwoodlands\b|\btoa payoh\b|\bchangi\b|\bwatsons\b|\bowndays\b|\bcapitol optical\b|\bnanyang optical\b|"
    r"\bpolyclinic\b|\bite\b|\bkopitiam\b|\bhsa\b|\bcdc vouchers?\b",
    re.I)
# Subreddits that are not Singapore subs (r/glasses etc.): only unambiguous markers. No Singlish particles,
# no "HSA" (a US health savings account there), no short place names.
SG_STRICT = re.compile(
    r"\bsgd\b|\bs\$|\bsingapore\b|\bsg\b|\bsingaporeans?\b|\bsnec\b|\bttsh\b|\bcapitol optical\b|"
    r"\bnanyang optical\b|\bjohor\b|\bcdc vouchers?\b", re.I)
GENERAL_SG_SUBS = {"asksingapore", "singapore", "singaporeraw", "sgexams", "nationalservicesg", "singaporefi",
                   "nus", "ntu", "sgcareers", "singaporeparents", "sgmums", "sgbeauty", "singaporehealth"}


def sg_check(sub: str, text: str):
    """(is_sg, reason): a Singapore subreddit, or a marker found in the text (strict list outside SG subs)."""
    if (sub or "").lower() in SG_SUBS_LOWER:
        return 1, "sg_subreddit"
    m = SG_STRICT.search(text or "")
    return (1, f"marker:{m.group(0).lower()}") if m else (0, "")


def eye_post(sub: str, title: str, body: str):
    """Eye/lens relevance. In general Singapore subs a single stray word is not enough: the eye term must be
    in the title, or the body must hold two different eye terms."""
    full = f"{title} {body}"
    if not EYE_TERMS.search(full):
        return False
    if (sub or "").lower() not in GENERAL_SG_SUBS:
        return True
    if EYE_TERMS.search(title or ""):
        return True
    found = {m.group(0).lower() for m in EYE_TERMS_CORE.finditer(full)} | \
            {m.group(0).lower() for m in _CONTACTS_WORD.finditer(full) if _LENS_CTX.search(full)}
    return len(found) >= 2


SPAM = re.compile(
    r"giveaway|contest|raffle|lucky draw|promo code|referral code|affiliate|use my code|"
    r"dm me|whatsapp me|sponsored", re.I)
TEXT_SEGMENTS = {
    "glasses_only": re.compile(r"never (tried|worn|wore) (contact|lens)|only wear glasses|glasses only", re.I),
    "dropout": re.compile(r"stopped wearing|stop wearing contact|back to glasses|gave up (on )?contact|quit contact", re.I),
    "part_timer": re.compile(r"occasional|sometimes wear|once in a while|weekend|special occasion|not everyday", re.I),
    "surgery": re.compile(r"lasik|\bsmile\b surgery|\bicl\b|refractive|eye surgery|laser eye", re.I),
    "student": re.compile(r"\bstudents?\b|\bschool|\bteen|my (son|daughter|kid|child)|\bpoly\b|\bjc\b|secondary|primary school|parent", re.I),
    "over40": re.compile(r"presbyop|multifocal|reading glasses|bifocal|progressive|\b(4\d|5\d|6\d)\s?(yo|y/o|years? old)", re.I),
    "sporty": re.compile(r"swim|\bgym\b|running|badminton|football|futsal|basketball|sports?\b|workout|hiking", re.I),
    "screen_pro": re.compile(r"dry eye|eye\s*strain|eyestrain|screen|computer|desk|office|wfh|work from home", re.I),
}


def text_segments(text: str) -> list:
    return [s for s, rx in TEXT_SEGMENTS.items() if rx.search(text or "")]


def norm_title(t: str) -> str:
    return re.sub(r"\W+", "", (t or "").lower())


# ── ledger / cost cap ────────────────────────────────────────────────
def ledger_load() -> dict:
    if LEDGER.exists():
        return json.loads(LEDGER.read_text())
    # 0.116 = single probe run on 2026-10-27 (LASIK contact lenses Singapore, 20 items)
    return {"cap": CAP_USD, "spent": 0.116, "runs": [{"label": "probe", "usd": 0.116}]}


def ledger_save(led: dict) -> None:
    LEDGER.parent.mkdir(parents=True, exist_ok=True)
    LEDGER.write_text(json.dumps(led, indent=1))


def run_search(token: str, led: dict, keyword: str, subreddit, max_items: int) -> list:
    est = START_FEE + PER_RESULT * max_items
    if led["spent"] + est > led["cap"]:
        raise SystemExit(f"[CAP] stop: spent ${led['spent']:.3f} + est ${est:.3f} would exceed ${led['cap']:.2f}")
    inp = {
        "searches": [keyword], "searchPosts": True, "searchComments": False,
        "searchCommunities": False, "searchUsers": False, "searchMedia": False,
        "skipComments": True, "skipCommunity": True,
        "sort": "new", "postDateLimit": CUTOFF_24.strftime("%Y-%m-%d"),
        "maxItems": max_items, "maxPostCount": max_items,
    }
    if subreddit:
        inp["searchCommunityName"] = subreddit
    label = f"{subreddit or 'all'}:{keyword}"
    slug = base.POSTS_ACTOR.replace("/", "~")
    r = requests.post(f"{base.APIFY_BASE}/acts/{slug}/runs", json=inp,
                      params={"token": token, "maxTotalChargeUsd": round(est + 0.02, 3)}, timeout=30)
    if not r.ok:
        print(f"[FAIL] {label}: start {r.status_code} {r.text[:200]}")
        return []
    d = r.json()["data"]
    final = None
    for _ in range(40):
        time.sleep(6)
        final = requests.get(f"{base.APIFY_BASE}/actor-runs/{d['id']}", params={"token": token}, timeout=15).json()["data"]
        if final["status"] in ("SUCCEEDED", "FAILED", "ABORTED", "TIMED-OUT"):
            break
    usd = float(final.get("usageTotalUsd") or est)
    led["spent"] += usd
    led["runs"].append({"label": label, "usd": usd, "status": final["status"]})
    ledger_save(led)
    if final["status"] != "SUCCEEDED":
        print(f"[FAIL] {label}: {final['status']} {final.get('statusMessage', '')}")
    items = requests.get(f"{base.APIFY_BASE}/datasets/{d['defaultDatasetId']}/items",
                         params={"token": token, "format": "json"}, timeout=60).json()
    items = items if isinstance(items, list) else []
    print(f"[RUN] {label}: {len(items)} items ${usd:.3f} (total ${led['spent']:.3f})")
    return items


# ── db ───────────────────────────────────────────────────────────────
SCHEMA = """
CREATE TABLE IF NOT EXISTS posts (
  post_id TEXT PRIMARY KEY, segment TEXT, search_keyword TEXT, query_scope TEXT,
  subreddit TEXT, title TEXT, selftext TEXT, author TEXT, score INTEGER,
  num_comments INTEGER, created_utc TEXT, permalink TEXT, collected_at TEXT,
  text_segments TEXT, is_sg INTEGER, sg_reason TEXT, is_eye_relevant INTEGER,
  is_spam INTEGER, in_window INTEGER, in_last_12m INTEGER, dup_of TEXT, keep INTEGER);
CREATE TABLE IF NOT EXISTS done_queries (scope TEXT, keyword TEXT, n_raw INTEGER, PRIMARY KEY(scope, keyword));
"""


def open_db():
    DB_PATH.parent.mkdir(parents=True, exist_ok=True)
    c = sqlite3.connect(DB_PATH, timeout=120)
    c.row_factory = sqlite3.Row
    c.execute("PRAGMA journal_mode=WAL")
    c.execute("PRAGMA busy_timeout=120000")
    c.executescript(SCHEMA)
    have = {r[1] for r in c.execute("PRAGMA table_info(posts)")}
    for col, typ in (("source", "TEXT"), ("keywords_hit", "TEXT"), ("is_removed", "INTEGER")):
        if col not in have:
            c.execute(f"ALTER TABLE posts ADD COLUMN {col} {typ}")
    c.execute("UPDATE posts SET source='apify' WHERE source IS NULL")
    c.execute("UPDATE posts SET is_removed=0 WHERE is_removed IS NULL")
    c.commit()
    return c


def parse_dt(s: str):
    try:
        return datetime.fromisoformat((s or "").replace("Z", "+00:00"))
    except ValueError:
        return None


def ingest(c, raw_items: list, segment: str, keyword: str, scope: str, sub_scoped: bool) -> int:
    n = 0
    for raw in raw_items:
        if raw.get("dataType") != "post":
            continue
        p = base.extract_post_fields(raw, "x", "SG", None, keyword)
        if not p:
            continue
        text = f"{p['title']} {p['selftext']}"
        sub = re.sub(r"^r/", "", (p["subreddit"] or "").strip())
        sg_sub = sub.lower() in SG_SUBS_LOWER
        m = SG_MARKERS.search(text)
        is_sg = int(sg_sub or bool(m))
        reason = "sg_subreddit" if sg_sub else (f"marker:{m.group(0).lower()}" if m else "")
        dt = parse_dt(p["created_utc"])
        in_win = int(bool(dt and dt >= CUTOFF_24))
        ts = text_segments(text)
        seg = segment or (ts[0] if ts else "unassigned")
        bot = base._is_bot_author(p["author"])
        spam = int(bool(SPAM.search(text)) or bot)
        cur = c.execute(
            "INSERT OR IGNORE INTO posts VALUES (?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?)",
            (p["post_id"], seg, keyword, scope, sub, p["title"], p["selftext"], p["author"],
             p["score"], p["num_comments"], p["created_utc"], p["permalink"], p["discovered_at"],
             ",".join(ts), is_sg, reason, int(bool(EYE_TERMS.search(text))), spam, in_win,
             int(bool(dt and dt >= CUTOFF_12)), None, None))
        n += cur.rowcount
    c.commit()
    return n


def finalise(c) -> None:
    """Recompute text flags, mark duplicates (same post id, or same title+author), set keep.
    One transaction, executemany; only touches the stored (eye-relevant) rows."""
    rows = c.execute("SELECT post_id, title, selftext, author, source, collected_at, subreddit FROM posts").fetchall()
    sg = [(*sg_check(r["subreddit"], f"{r['title']} {r['selftext']}"), r["post_id"]) for r in rows]
    c.executemany("UPDATE posts SET is_sg=?, sg_reason=? WHERE post_id=?", sg)
    flags = []
    for r in rows:
        text = f"{r['title']} {r['selftext']}"
        flags.append((int(eye_post(r["subreddit"], r["title"], r["selftext"])),
                      int(bool(SPAM.search(text)) or base._is_bot_author(r["author"])),
                      ",".join(text_segments(text)), r["post_id"]))
    c.executemany("UPDATE posts SET is_eye_relevant=?, is_spam=?, text_segments=? WHERE post_id=?", flags)
    labels = []
    for r in rows:
        if r["source"] != "arctic":
            continue
        mk = sweep_keyword(f"{r['title']} {r['selftext']}")
        seg, kw = mk if mk else ("", "(no segment keyword)")
        labels.append((seg or "unassigned", kw, r["post_id"]))
    c.executemany("UPDATE posts SET segment=?, search_keyword=? WHERE post_id=?", labels)
    order = sorted(rows, key=lambda r: (r["source"] != "arctic", r["collected_at"] or "", r["post_id"]))
    seen_id, seen_key, dups = set(), {}, []
    for r in order:
        pid = r["post_id"].replace("t3_", "")
        k = (norm_title(r["title"]), (r["author"] or "").lower())
        if pid in seen_id:
            dups.append((pid, r["post_id"]))
        elif k[0] and k in seen_key:
            dups.append((seen_key[k], r["post_id"]))
        else:
            seen_id.add(pid)
            seen_key[k] = r["post_id"]
    c.execute("UPDATE posts SET dup_of=NULL")
    c.executemany("UPDATE posts SET dup_of=? WHERE post_id=?", dups)
    c.execute("""UPDATE posts SET keep = CASE WHEN is_sg=1 AND is_eye_relevant=1 AND is_spam=0
                 AND in_window=1 AND dup_of IS NULL AND COALESCE(is_removed,0)=0 THEN 1 ELSE 0 END""")
    c.commit()


def plan() -> list:
    q = [(seg, f"{kw} Singapore", None, kw) for seg, kw in SITEWIDE]
    for sub in SG_SUBS:
        q += [(seg, kw, sub, kw) for seg, kw in SG_SUB_QUERIES]
    for sub in GLOBAL_SUBS:
        q += [(seg, kw, sub, kw) for seg, kw in GLOBAL_SUB_QUERIES]
    return q


def pilot_plan() -> list:
    """One sitewide query per segment (first of each) plus two SG subreddit runs."""
    picked, seen = [], set()
    for seg, kw in SITEWIDE:
        if seg not in seen and seg != "brand_only":
            seen.add(seg)
            picked.append((seg, f"{kw} Singapore", None, kw))
    picked.append(("", "contact lenses", "askSingapore", "contact lenses"))
    picked.append(("", "glasses or contacts", "singapore", "glasses or contacts"))
    return picked[:PILOT_QUERIES]


def execute(queries: list, max_items: int) -> None:
    token = os.getenv("APIFY_TOKEN", "").strip()
    led = ledger_load()
    c = open_db()
    done = {(r["scope"], r["keyword"]) for r in c.execute("SELECT scope, keyword FROM done_queries")}
    for seg, search_kw, sub, label_kw in queries:
        scope = sub or "sitewide"
        if (scope, search_kw) in done:
            continue
        items = run_search(token, led, search_kw, sub, max_items)
        n_new = ingest(c, items, seg, search_kw, scope, bool(sub))
        c.execute("INSERT OR REPLACE INTO done_queries VALUES (?,?,?)", (scope, search_kw, len(items)))
        c.commit()
        print(f"      -> {n_new} new posts")
    finalise(c)
    print(f"[LEDGER] spent ${led['spent']:.3f} of ${led['cap']:.2f}")


def report(c) -> None:
    q = lambda sql: c.execute(sql).fetchone()[0]
    n, keep = q("SELECT count(*) FROM posts"), q("SELECT sum(keep) FROM posts") or 0
    scanned = q("SELECT COALESCE(sum(n_raw),0) FROM done_queries WHERE scope LIKE 'sweep:%'")
    print(f"posts scanned in sweeps {scanned} | stored (lens/eye-related) {n} | kept {keep}")
    for col in ("is_sg", "is_eye_relevant", "in_window"):
        print(f"  stored and pass {col}: {q(f'SELECT COALESCE(sum({col}),0) FROM posts')}")
    print(f"  spam: {q('SELECT COALESCE(sum(is_spam),0) FROM posts')} | duplicates: {q('SELECT count(*) FROM posts WHERE dup_of IS NOT NULL')}")
    print("segment: stored / kept")
    for seg, raw_n, kept in c.execute("SELECT segment, count(*), sum(keep) FROM posts GROUP BY segment ORDER BY 3 DESC"):
        print(f"  {seg}: {raw_n} / {kept}")


def export(c) -> None:
    OUT_DIR.mkdir(parents=True, exist_ok=True)
    cols = ["post_id", "segment", "search_keyword", "query_scope", "subreddit", "title", "selftext",
            "author", "score", "num_comments", "created_utc", "permalink", "text_segments",
            "sg_reason", "in_last_12m", "source"]
    rows = c.execute(f"SELECT {','.join(cols)} FROM posts WHERE keep=1 ORDER BY segment, created_utc DESC").fetchall()
    with open(OUT_DIR / "reddit_segment_posts.csv", "w", newline="", encoding="utf-8-sig") as f:
        w = csv.writer(f)
        w.writerow(cols)
        for r in rows:
            w.writerow(tuple(r))
    print(f"[EXPORT] {len(rows)} rows -> {OUT_DIR / 'reddit_segment_posts.csv'}")
    if c.execute("SELECT name FROM sqlite_master WHERE name='comments'").fetchone():
        ccols = ["comment_id", "post_id", "segment", "subreddit", "author", "body", "score", "created_utc", "permalink"]
        crows = c.execute(f"SELECT {','.join('c.' + x for x in ccols)} FROM comments c JOIN posts p ON p.post_id=c.post_id "
                          "WHERE c.keep=1 AND p.keep=1 ORDER BY c.segment, c.post_id, c.created_utc").fetchall()
        with open(OUT_DIR / "reddit_segment_comments.csv", "w", newline="", encoding="utf-8-sig") as f:
            w = csv.writer(f)
            w.writerow(ccols + ["has_eye_term"])
            for r in crows:
                w.writerow(tuple(r) + (int(bool(EYE_TERMS.search(r["body"]))),))
        print(f"[EXPORT] {len(crows)} comments -> {OUT_DIR / 'reddit_segment_comments.csv'}")


# ── Arctic Shift archive (free; replaces the paid Apify scale-up) ─────
ARCTIC = "https://arctic-shift.photon-reddit.com/api"
HDR = {"User-Agent": "segment-study-research/0.1 (non-commercial)"}

# Specific segments first, generic last: the first keyword to find a post labels its segment.
ARCHIVE_KEYWORDS = [
    ("glasses_only", "never tried contacts"), ("glasses_only", "glasses or contacts"),
    ("glasses_only", "contacts or glasses"), ("glasses_only", "glasses vs contacts"),
    ("dropout", "stopped wearing contacts"), ("dropout", "stop wearing contacts"),
    ("dropout", "back to glasses"), ("dropout", "gave up contacts"),
    ("part_timer", "contacts occasionally"), ("part_timer", "contacts sometimes"),
    ("part_timer", "contacts special occasions"),
    ("surgery", "LASIK"), ("surgery", "SMILE surgery"), ("surgery", "ICL"),
    ("surgery", "ReLEx"), ("surgery", "eye surgery"),
    ("student", "contacts school"), ("student", "contacts teen"), ("student", "first time contacts"),
    ("student", "contact lenses student"), ("student", "contacts kid"),
    ("over40", "presbyopia"), ("over40", "multifocal"), ("over40", "reading glasses"),
    ("over40", "progressive lenses"), ("over40", "bifocal"),
    ("sporty", "contacts swimming"), ("sporty", "contacts gym"), ("sporty", "contacts running"),
    ("sporty", "contacts badminton"), ("sporty", "contacts sports"),
    ("screen_pro", "dry eyes"), ("screen_pro", "eye strain"), ("screen_pro", "contacts computer"),
    ("screen_pro", "contacts office"),
    ("brand_only", "Acuvue"), ("brand_only", "Air Optix"), ("brand_only", "Biofinity"),
    ("brand_only", "Olens"), ("brand_only", "Bausch Lomb"), ("brand_only", "CooperVision"),
    ("", "contact lenses"), ("", "contact lens"), ("", "contacts"), ("", "glasses"),
]
GLOBAL_ARCHIVE_SUBS = ["contactlenses", "glasses", "lasik", "eyecare", "Optometry", "askoptometry",
                       "Presbyopia", "EyeSurgery", "Myopia"]
GLOBAL_ARCHIVE_KEYWORDS = [("", k) for k in ("Singapore", "SGD", "Singaporean", "SNEC", "S$")]
MAX_COMMENTS_PER_POST = 300


class ArchiveDown(RuntimeError):
    """Archive keeps returning 5xx / network errors: stop the run, do not split windows or mark anything done."""


def arctic_get(endpoint: str, params: dict):
    """Returns (True, data), or (False, None) when the archive timed out (caller splits the window).
    Raises ArchiveDown on persistent 5xx / network errors so an outage never looks like empty data."""
    for attempt in range(4):
        try:
            r = requests.get(f"{ARCTIC}/{endpoint}", params=params, headers=HDR, timeout=90)
        except requests.RequestException:
            time.sleep(5 * (attempt + 1))
            continue
        if r.status_code == 200:
            return True, r.json().get("data") or []
        if r.status_code == 422 and "imeout" in r.text:
            return False, None
        if r.status_code in (429, 500, 502, 503, 504):
            time.sleep(5 * (attempt + 1))
            continue
        print(f"[ARCHIVE] {endpoint} {params.get('subreddit')} HTTP {r.status_code}: {r.text[:120]}")
        return True, []
    raise ArchiveDown(f"{endpoint} {params.get('subreddit')}: still failing after retries")


def iso(dt: datetime) -> str:
    return dt.strftime("%Y-%m-%dT%H:%M:%S")


def archive_posts(sub: str, kw: str, a: datetime, b: datetime, failures: list) -> list:
    """All posts in [a, b) for sub matching kw; splits the window on timeout, pages at 100."""
    out, cur = [], a
    while cur < b:
        ok, data = arctic_get("posts/search", {"subreddit": sub, "query": kw, "after": iso(cur),
                                               "before": iso(b), "limit": 100, "sort": "asc"})
        time.sleep(0.3)
        if not ok:
            if (b - cur) <= timedelta(days=2):
                failures.append((sub, kw, iso(cur), iso(b)))
                return out
            mid = cur + (b - cur) / 2
            return out + archive_posts(sub, kw, cur, mid, failures) + archive_posts(sub, kw, mid, b, failures)
        out += data
        if len(data) < 100:
            return out
        cur = datetime.fromtimestamp(data[-1]["created_utc"], tz=timezone.utc) + timedelta(seconds=1)
    return out


def ingest_archive(c, posts: list, segment: str, kw: str) -> int:
    n = 0
    for x in posts:
        pid = str(x["id"])
        sub = x.get("subreddit") or ""
        title, body = x.get("title") or "", x.get("selftext") or ""
        removed = int(bool(x.get("removed_by_category")) or body in ("[removed]", "[deleted]")
                      or "Removed by moderator" in title)
        text = f"{title} {body}"
        if not eye_post(sub, title, body):
            continue
        ex = c.execute("SELECT post_id, search_keyword FROM posts WHERE post_id IN (?,?)", (pid, "t3_" + pid)).fetchone()
        if ex:
            c.execute("UPDATE posts SET keywords_hit = COALESCE(keywords_hit,'') || ? WHERE post_id=?",
                      (f"|{kw}", ex["post_id"]))
            continue
        created = datetime.fromtimestamp(x["created_utc"], tz=timezone.utc)
        ts = text_segments(text)
        seg = segment or (ts[0] if ts else "unassigned")
        is_sg, sg_why = sg_check(sub, text)
        cur = c.execute(
            "INSERT OR IGNORE INTO posts (post_id, segment, search_keyword, query_scope, subreddit, title, selftext, "
            "author, score, num_comments, created_utc, permalink, collected_at, text_segments, is_sg, sg_reason, "
            "is_eye_relevant, is_spam, in_window, in_last_12m, source, keywords_hit, is_removed) "
            "VALUES (?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?)",
            (pid, seg, kw, "arctic:" + sub, sub, title, body, x.get("author") or "", x.get("score") or 0,
             x.get("num_comments") or 0, created.isoformat(), "https://www.reddit.com" + (x.get("permalink") or ""),
             datetime.now(timezone.utc).isoformat(), ",".join(ts), is_sg, sg_why,
             int(eye_post(sub, title, body)), int(bool(SPAM.search(text)) or base._is_bot_author(x.get("author"))),
             int(created >= CUTOFF_24), int(created >= CUTOFF_12), "arctic", f"|{kw}", removed))
        n += cur.rowcount
    c.commit()
    return n


def run_archive_posts() -> None:
    c = open_db()
    done = {r["scope"] for r in c.execute("SELECT scope FROM done_queries")}
    failures: list = []
    jobs = [(s, ARCHIVE_KEYWORDS) for s in SG_SUBS] + [(s, GLOBAL_ARCHIVE_KEYWORDS) for s in GLOBAL_ARCHIVE_SUBS]
    for sub, kws in jobs:
        for seg, kw in kws:
            scope = f"arctic:{sub}:{kw}"
            if scope in done:
                continue
            posts = archive_posts(sub, kw, CUTOFF_24, TODAY + timedelta(days=1), failures)
            n_new = ingest_archive(c, posts, seg, kw)
            c.execute("INSERT OR REPLACE INTO done_queries VALUES (?,?,?)", (scope, kw, len(posts)))
            c.commit()
            print(f"[ARCHIVE] r/{sub} '{kw}': {len(posts)} found, {n_new} new", flush=True)
    finalise(c)
    if failures:
        print(f"[ARCHIVE] {len(failures)} window(s) failed after splitting: {failures[:10]}")
    report(c)


def run_archive_comments() -> None:
    c = open_db()
    c.execute("""CREATE TABLE IF NOT EXISTS comments (comment_id TEXT PRIMARY KEY, post_id TEXT, segment TEXT,
        subreddit TEXT, author TEXT, body TEXT, score INTEGER, created_utc TEXT, permalink TEXT, keep INTEGER)""")
    c.execute("CREATE TABLE IF NOT EXISTS comments_done (post_id TEXT PRIMARY KEY, n INTEGER)")
    posts = c.execute("SELECT post_id, segment, subreddit, permalink FROM posts WHERE keep=1 AND source='arctic' "
                      "AND num_comments>0 AND post_id NOT IN (SELECT post_id FROM comments_done)").fetchall()
    print(f"[COMMENTS] {len(posts)} kept posts to fetch")
    for i, p in enumerate(posts, 1):
        got, cur = [], CUTOFF_24 - timedelta(days=30)
        while len(got) < MAX_COMMENTS_PER_POST:
            ok, data = arctic_get("comments/search", {"link_id": p["post_id"], "limit": 100, "sort": "asc",
                                                      "after": iso(cur)})
            time.sleep(0.3)
            if not data:
                break
            got += data
            if len(data) < 100:
                break
            cur = datetime.fromtimestamp(data[-1]["created_utc"], tz=timezone.utc) + timedelta(seconds=1)
        n_ins = 0
        for x in got:
            body = x.get("body") or ""
            author = x.get("author") or ""
            bad = body in ("[removed]", "[deleted]") or author == "[deleted]" or base._is_bot_author(author) \
                or bool(SPAM.search(body))
            cur2 = c.execute("INSERT OR IGNORE INTO comments VALUES (?,?,?,?,?,?,?,?,?,?)",
                             (str(x["id"]), p["post_id"], p["segment"], p["subreddit"], author, body,
                              x.get("score") or 0,
                              datetime.fromtimestamp(x["created_utc"], tz=timezone.utc).isoformat(),
                              p["permalink"], int(not bad)))
            n_ins += cur2.rowcount
        c.execute("INSERT OR REPLACE INTO comments_done VALUES (?,?)", (p["post_id"], n_ins))
        c.commit()
        if i % 25 == 0:
            print(f"[COMMENTS] {i}/{len(posts)}", flush=True)
    kept = c.execute("SELECT segment, count(*) FROM comments WHERE keep=1 GROUP BY 1").fetchall()
    print("[COMMENTS] kept comments by segment:", [tuple(r) for r in kept])


def _kw_regex(kw: str):
    toks = [re.escape(t) for t in kw.lower().split()]
    fwd = r"\b" + r"\b.{0,15}\b".join(toks) + r"\b"
    if len(toks) == 2:
        fwd += r"|\b" + toks[1] + r"\b.{0,15}\b" + toks[0] + r"\b"
    return re.compile(fwd, re.S)


_KW_RX = None


def sweep_keyword(text: str):
    """First ARCHIVE_KEYWORDS entry found as a phrase (words in order, within 15 chars of each other). None if no hit."""
    global _KW_RX
    if _KW_RX is None:
        _KW_RX = [(seg, kw, _kw_regex(kw)) for seg, kw in ARCHIVE_KEYWORDS]
    low = (text or "").lower()
    for seg, kw, rx in _KW_RX:
        if rx.search(low):
            return seg, kw
    return None


def sweep_sub(sub: str, failures: list, a=None, b=None) -> list:
    """Every post in [a, b) for one subreddit, no keyword. A timeout halves the window (down to 1 day);
    a window that still fails is recorded in `failures`, never treated as empty."""
    a = a or CUTOFF_24
    b = b or (TODAY + timedelta(days=1))
    out, cur = [], a
    while cur < b:
        ok, data = arctic_get("posts/search", {"subreddit": sub, "after": iso(cur), "before": iso(b),
                                               "limit": 100, "sort": "asc"})
        time.sleep(0.2)
        if not ok:
            if (b - cur) <= timedelta(days=1):
                failures.append((sub, iso(cur), iso(b)))
                return out
            mid = cur + (b - cur) / 2
            return out + sweep_sub(sub, failures, cur, mid) + sweep_sub(sub, failures, mid, b)
        out += data
        if len(data) < 100:
            return out
        cur = datetime.fromtimestamp(data[-1]["created_utc"], tz=timezone.utc) + timedelta(seconds=1)
    return out


def run_archive_sweep(only=None) -> None:
    c = open_db()
    done = {r["scope"] for r in c.execute("SELECT scope FROM done_queries")}
    failures: list = []
    for sub in (only or SG_SUBS + GLOBAL_ARCHIVE_SUBS):
        scope = f"sweep:{sub}"
        if scope in done:
            continue
        sub_fail: list = []
        try:
            posts = sweep_sub(sub, sub_fail)
        except ArchiveDown as e:
            print(f"[ARCHIVE] STOPPED, archive is down ({e}). Nothing marked done for r/{sub}; rerun later.", flush=True)
            raise SystemExit(2)
        failures += sub_fail
        hit = {}
        for x in posts:
            m = sweep_keyword(f"{x.get('title') or ''} {x.get('selftext') or ''}")
            hit.setdefault(m, []).append(x)
        n_new = 0
        for m, grp in hit.items():
            seg, kw = m if m else ("", "(sweep, no segment keyword)")
            n_new += ingest_archive(c, grp, seg, kw)
        if not sub_fail:
            c.execute("INSERT OR REPLACE INTO done_queries VALUES (?,?,?)", (scope, "(sweep)", len(posts)))
        c.commit()
        print(f"[ARCHIVE] r/{sub} sweep: {len(posts)} posts in window, {n_new} new, "
              f"{len(sub_fail)} failed window(s)", flush=True)
    finalise(c)
    if failures:
        from collections import Counter
        print(f"[ARCHIVE] {len(failures)} window(s) failed, by subreddit: {dict(Counter(f[0] for f in failures))}")
    report(c)


if __name__ == "__main__":
    ap = argparse.ArgumentParser()
    ap.add_argument("--stage", choices=["pilot", "scale", "archive", "archive-comments", "sweep", "export", "report"],
                    required=True)
    ap.add_argument("--max-items", type=int, default=20)
    ap.add_argument("--subs", nargs="+", help="sweep stage: only these subreddits (testing / gap re-runs)")
    a = ap.parse_args()
    if a.stage == "pilot":
        execute(pilot_plan(), a.max_items)
    elif a.stage == "scale":
        execute(plan(), a.max_items)
    elif a.stage == "sweep":
        run_archive_sweep(a.subs)
        raise SystemExit(0)
    elif a.stage == "archive":
        run_archive_posts()
    elif a.stage == "archive-comments":
        run_archive_comments()
    conn = open_db()
    finalise(conn)
    if a.stage == "export":
        export(conn)
    report(conn)
