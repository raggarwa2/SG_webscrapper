"""
Source ledger: every body of data the dashboard reads, counted live from its own file.

One row per lens. The pool lenses come from voice_items_sg.db and make the headline total; the reference voice (segment study),
the AI answers and the search interest are read apart and are never in that total. Each row carries the newest data date, when the
file was built, and a status that says so when an upstream file is newer than the build. Used by the sidebar and Data Notes.
"""

import sqlite3
from datetime import date, datetime
from pathlib import Path

import pandas as pd
import streamlit as st

import segment_data
import trends_signals
import voice_data

OUT = Path(__file__).resolve().parent.parent / "Scripts" / "output"
HANDOVER = Path(__file__).resolve().parent.parent / "Handover" / "segment_study_2026-10"
LENS_LABEL = {
    "consumer_voice": "Consumer comments, posts and reviews",
    "retail_experience": "Retailer reviews",
    "brand_broadcast": "Brand posts and ads",
    "owned_experience": "App reviews",
}
# Raw table behind each source_table in voice_items (Scripts/build_voice_items.py reads each whole, one row per item).
# A lens is out of date when a raw table holds a different number of rows than voice_items holds from it.
RAW_TABLES = {
    "yt_videos": "youtube_data_sg.db", "yt_comments": "youtube_data_sg.db", "ig_posts": "instagram_data_sg.db",
    "ig_comments": "instagram_data_sg.db", "fb_posts": "facebook_data_sg.db", "fb_comments": "facebook_data_sg.db",
    "reddit_posts": "reddit_data_sg.db", "reddit_comments": "reddit_data_sg.db", "xhs_posts": "xhs_data_sg.db",
    "xhs_comments": "xhs_data_sg.db", "forum_posts": "sg_acuvue.db", "reviews": "sg_acuvue.db", "gmaps_reviews": "gmaps_data_sg.db",
    "fb_retailer_posts": "facebook_retailers_sg.db", "fb_retailer_reviews": "facebook_retailers_sg.db", "fb_ads": "facebook_ads_sg.db",
    "app_reviews": "app_data_sg.db",
}
REFERENCE_SOURCES = [HANDOVER / "reddit" / "reddit_segment_posts.csv", HANDOVER / "consumer_intel" / "social_comments.csv",
                     HANDOVER / "consumer_intel" / "social_posts.csv"]


def _mtime(p) -> float:
    p = Path(p)
    return p.stat().st_mtime if p.exists() else 0.0


def _stamp(ts: float) -> str:
    return datetime.fromtimestamp(ts).strftime("%Y-%m-%d %H:%M") if ts else ""


def _newer(built: float, sources: list[Path]) -> list[str]:
    """Names of source files written after the build (a minute of slack)."""
    return [p.name for p in sources if _mtime(p) > built + 60]


def _status(newer: list[str]) -> str:
    return "Rebuild needed: " + ", ".join(newer) + " newer" if newer else "Current"


def _pool_gaps(con: sqlite3.Connection) -> dict:
    """Per lens, the raw tables whose row count differs from voice_items (a table can feed two lenses), e.g. 'reddit_posts 60 vs 57'."""
    held = con.execute("SELECT lens, source_table, COUNT(*) FROM voice_items GROUP BY 1, 2").fetchall()
    total: dict = {}
    for _, table, n in held:
        total[table] = total.get(table, 0) + n
    off = {}
    for table, n in total.items():
        db = OUT / RAW_TABLES.get(table, "")
        if table not in RAW_TABLES or not db.exists():
            continue
        raw = sqlite3.connect(f"file:{db.as_posix()}?mode=ro", uri=True)
        try:
            r = raw.execute(f"SELECT COUNT(*) FROM {table}").fetchone()[0]
        finally:
            raw.close()
        if r != n:
            off[table] = f"{table} {r:,} vs {n:,}"
    gaps: dict = {}
    for lens, table, _ in held:
        if table in off:
            gaps.setdefault(lens, []).append(off[table])
    return gaps


def _latest(con: sqlite3.Connection, sql: str) -> str:
    v = con.execute(sql).fetchone()[0]
    return str(v)[:10] if v else ""


@st.cache_data(ttl=600, show_spinner=False)
def ledger() -> pd.DataFrame:
    """Columns: Source, Items, Added today, Latest data, Built, Status. Added today is None where the source stores no collected-at date."""
    rows = []
    today = date.today().isoformat()
    if voice_data.available():
        built = max(_mtime(voice_data.VOICE_DB), _mtime(voice_data.TAG_DB))
        con = sqlite3.connect(f"file:{voice_data.VOICE_DB.as_posix()}?mode=ro", uri=True)
        gaps = _pool_gaps(con)
        for lens, n, last in con.execute("SELECT lens, COUNT(*), MAX(date) FROM voice_items GROUP BY lens ORDER BY COUNT(*) DESC").fetchall():
            rows.append({"Source": LENS_LABEL.get(lens, lens), "Items": int(n), "Added today": None, "Latest data": str(last or "")[:10],
                         "Built": _stamp(built), "Status": "Rebuild needed: " + ", ".join(gaps[lens]) if lens in gaps else "Current"})
        con.close()
    if segment_data.reference_available():
        built = max(_mtime(segment_data.ITEMS_DB), _mtime(segment_data.TAGS_DB))
        con = sqlite3.connect(f"file:{segment_data.ITEMS_DB.as_posix()}?mode=ro", uri=True)
        n, last = con.execute("SELECT COUNT(*), MAX(date) FROM voice_items").fetchone()
        con.close()
        con = sqlite3.connect(f"file:{segment_data.TAGS_DB.as_posix()}?mode=ro", uri=True)
        tagged = con.execute("SELECT COUNT(DISTINCT item_id) FROM voice_tags").fetchone()[0]
        con.close()
        con = sqlite3.connect(f"file:{segment_data.ITEMS_DB.as_posix()}?mode=ro", uri=True)
        cols = [r[1] for r in con.execute("PRAGMA table_info(voice_items)")]
        added = con.execute("SELECT COUNT(*) FROM voice_items WHERE substr(added_at, 1, 10) = ?", (today,)).fetchone()[0] if "added_at" in cols else None
        con.close()
        status = _status(_newer(built, REFERENCE_SOURCES))
        if n != tagged:
            status = f"Tagging needed: {int(n) - int(tagged):,} items not tagged" + ("" if status == "Current" else "; " + status)
        rows.append({"Source": "Reference voice (segment study, YouTube, TikTok, Reddit)", "Items": int(tagged), "Added today": added,
                     "Latest data": str(last or "")[:10], "Built": _stamp(built), "Status": status})
    ai = HANDOVER / "consumer_intel" / "ai_search.csv"
    if ai.exists():
        a = pd.read_csv(ai, dtype=str, encoding="utf-8-sig", usecols=["captured_at_utc"])
        local = pd.to_datetime(a["captured_at_utc"], utc=True, errors="coerce").dt.tz_convert(datetime.now().astimezone().tzinfo).dt.strftime("%Y-%m-%d")
        rows.append({"Source": "AI answers (ChatGPT, Perplexity)", "Items": len(a), "Added today": int((local == today).sum()),
                     "Latest data": str(a["captured_at_utc"].max())[:10], "Built": _stamp(_mtime(ai)), "Status": "Current"})
    t = trends_signals.load()
    if len(t):
        rows.append({"Source": "Search interest (Google Trends weekly points)", "Items": len(t), "Added today": int((t["pulled_at"].astype(str).str[:10] == today).sum()),
                     "Latest data": str(t["date"].max())[:10], "Built": _stamp(_mtime(trends_signals.TRENDS_DB)), "Status": "Current"})
    return pd.DataFrame(rows, columns=["Source", "Items", "Added today", "Latest data", "Built", "Status"])


def items(led: pd.DataFrame) -> pd.DataFrame:
    """Rows that count written items (everything but the weekly search-interest index points)."""
    return led[~led["Source"].str.startswith("Search interest")] if len(led) else led


def stale(led: pd.DataFrame) -> pd.DataFrame:
    return led[led["Status"] != "Current"] if len(led) else led


def freshest(led: pd.DataFrame) -> str:
    """Newest file build across every source, for the sidebar stamp."""
    return max(led["Built"]) if len(led) else ""
