"""
Shared constants/helpers for the SG dashboard: DB locations, brand
normalisation, journey-stage helpers.

The SG databases spell brands differently (products: "Acuvue" /
"Bausch & Lomb"; social DBs: "MyACUVUE" / "Bausch + Lomb"; forum_posts:
"ACUVUE") — normalize_brand() maps them all onto one set so brand filters
and colours don't silently miss rows.
"""

import logging
import os
import re
import sqlite3

import pandas as pd

log = logging.getLogger(__name__)

DASH_DIR = os.path.dirname(os.path.abspath(__file__))
DB_DIR = os.path.normpath(os.path.join(DASH_DIR, "..", "Scripts", "output"))

SG_DB = os.path.join(DB_DIR, "sg_acuvue.db")
YT_DB = os.path.join(DB_DIR, "youtube_data_sg.db")
IG_DB = os.path.join(DB_DIR, "instagram_data_sg.db")
FB_DB = os.path.join(DB_DIR, "facebook_data_sg.db")
FB_RETAIL_DB = os.path.join(DB_DIR, "facebook_retailers_sg.db")
FB_ADS_DB = os.path.join(DB_DIR, "facebook_ads_sg.db")
REDDIT_DB = os.path.join(DB_DIR, "reddit_data_sg.db")
XHS_DB = os.path.join(DB_DIR, "xhs_data_sg.db")
# MyACUVUE app-store reviews (app_reviews_extras.py).
APP_DB = os.path.join(DB_DIR, "app_data_sg.db")
# Google Maps optical-retailer reviews (google_maps_scraper_sg.py).
GMAPS_DB = os.path.join(DB_DIR, "gmaps_data_sg.db")
# Google Trends brand-term interest (google_trends_sg.py).
TRENDS_DB = os.path.join(DB_DIR, "trends_data_sg.db")

BRAND_COLORS = {
    "Acuvue": "#178197",
    "Alcon": "#0A7CC1",
    "Bausch & Lomb": "#A51890",
    "CooperVision": "#051F4A",
    "Olens": "#59A5D7",
}

# The one sentiment palette for every chart (charts.SENTIMENT_PALETTE is this dict).
SENTIMENT_COLORS = {"positive": "#168012", "neutral": "#9AA5B1", "mixed": "#59A5D7", "negative": "#DD1C14"}

# Order of the funnel in context.md
JOURNEY_STAGES = ["Awareness", "Engagement", "Consideration", "Trial", "Purchase", "Repeat/Retention"]

_BRAND_MAP = {
    "acuvue": "Acuvue",
    "myacuvue": "Acuvue",
    "bausch & lomb": "Bausch & Lomb",
    "bausch + lomb": "Bausch & Lomb",
    "bausch and lomb": "Bausch & Lomb",
    "b&l": "Bausch & Lomb",
    "alcon": "Alcon",
    "coopervision": "CooperVision",
    "cooper vision": "CooperVision",
    "olens": "Olens",
}


def normalize_brand(val):
    """Map any of the SG brand spellings onto the canonical set. Unknown
    values (e.g. "Other", "No Brand") are passed through; null stays null."""
    if val is None or (isinstance(val, float) and pd.isna(val)):
        return val
    return _BRAND_MAP.get(str(val).strip().lower(), str(val).strip())


# A giveaway's comments are entries, not opinions ("I need Oasys Max because..." is written to win). A post is a contest when its
# caption has a contest word AND asks for entries in the comments. "Win a prize by signing up for a trial" alone is not enough:
# the comments under such a post are ordinary reactions. One rule for the dashboard and Scripts/build_voice_items.py.
_CONTEST_WORD = re.compile(r"giveaway|giving away|contest|lucky (?:winner|draw)|stand (?:a )?chance to win|\bwin\b", re.I)
_ENTRY_CUE = re.compile(r"\bcomment|tell us|tag (?:a|2|two|3|your)|how to enter|\banswer", re.I)


def is_contest_caption(*texts) -> bool:
    """True when the post invites entries in its comments: a contest word and a way to enter by commenting."""
    t = " ".join(str(x) for x in texts if isinstance(x, str))
    return bool(_CONTEST_WORD.search(t) and _ENTRY_CUE.search(t))


def connect_ro(db_path: str) -> sqlite3.Connection:
    """Read-only connection — scrapers write to these DBs (WAL), the
    dashboard must never."""
    uri = "file:" + db_path.replace("\\", "/") + "?mode=ro"
    return sqlite3.connect(uri, uri=True)


def xhs_attributed(xhs: pd.DataFrame) -> pd.DataFrame:
    """Xiaohongshu posts that name one of the five tracked brands (brand_mentioned, already normalised) and were not
    judged off-brand. This is the single basis every page uses for Xiaohongshu counts, sentiment, reach and themes."""
    if xhs is None or xhs.empty:
        return xhs
    keep = xhs["brand_mentioned"].isin(list(BRAND_COLORS))
    if "brand_relevant" in xhs.columns:
        keep &= xhs["brand_relevant"] != 0
    return xhs[keep]


def read_table(db_path: str, query: str) -> pd.DataFrame:
    """Run a SELECT; empty DataFrame if the db/table doesn't exist yet.

    A missing db/table is expected while scrapers are still filling things in,
    so it returns empty quietly. Any other failure (locked db, corrupt file,
    bad schema) is logged as a warning — it still returns empty so one bad
    source can't take the whole dashboard down, but it is no longer silent."""
    if not os.path.exists(db_path):
        return pd.DataFrame()
    try:
        conn = connect_ro(db_path)
    except Exception as exc:
        log.warning("Could not open %s: %s", db_path, exc)
        return pd.DataFrame()
    try:
        return pd.read_sql_query(query, conn)
    except Exception as exc:
        if "no such table" not in str(exc).lower():
            log.warning("Query failed on %s (%s): %s", db_path, query, exc)
        return pd.DataFrame()
    finally:
        conn.close()


def split_stages(val) -> list:
    """'Awareness/Engagement/Consideration' -> ['Awareness','Engagement','Consideration'].
    Compliance rows ('Purchase (compliance flag - not funnel data)') -> [] so they
    never enter funnel counts."""
    if val is None or (isinstance(val, float) and pd.isna(val)) or not str(val).strip():
        return []
    s = str(val)
    if "compliance" in s.lower():
        return []
    # "Repeat/Retention" contains the delimiter — protect it; the DBs also
    # use the short form "Repeat".
    s = s.replace("Repeat/Retention", "Repeat|Retention")
    out = []
    for p in s.split("/"):
        p = p.strip().replace("Repeat|Retention", "Repeat/Retention")
        if p == "Repeat":
            p = "Repeat/Retention"
        if p:
            out.append(p)
    return out


def latest_mtime(*paths: str) -> float:
    return max((os.path.getmtime(p) for p in paths if os.path.exists(p)), default=0.0)
