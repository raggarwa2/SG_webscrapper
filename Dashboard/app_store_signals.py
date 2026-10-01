"""
MyACUVUE app-store reviews (Apple App Store + Google Play, SG storefront) from
Scripts/output/app_data_sg.db. Feeds the Journey & Barriers tab: these are
users who actually tried the app, so they speak to registration/Trial friction
and Repeat (points/rewards) â€” not to Awareness or Consideration.

Themes are keyword-tagged (a review can carry several) rather than LLM-labelled;
the vocabulary comes from the complaint clusters in Logs/summary.md.
"""

import re

import pandas as pd
import streamlit as st

from sg_common import APP_DB, latest_mtime, read_table

# theme -> (regex, journey stage the theme speaks to)
THEMES = {
    "App freezes / won't open": (r"freez|frozen|stuck|hang|won'?t open|not open|cannot open|can'?t open|crash|welcome screen|loading|blank|white screen|not working|doesn'?t work|does not work|lag", "Trial"),
    "Login / OTP / registration": (r"otp|log ?in|sign ?in|password|verif|register|registration|sign ?up|account|locked out|sms code|code", "Trial"),
    "Points / rewards": (r"point|reward|redeem|redemption|voucher|coupon|lifestyle|reset", "Repeat/Retention"),
    "Marketing / privacy": (r"unsubscribe|spam|advert|\bads?\b|marketing|privacy|nric|data|sms", "Repeat/Retention"),
    "Usability": (r"button|search|log ?out|complicated|confus|interface|\bui\b|hard to|difficult|design|navigation|music|slow", "Trial"),
}
_THEME_RE = {k: re.compile(v[0], re.I) for k, v in THEMES.items()}


def _themes(text: str) -> list:
    return [k for k, rx in _THEME_RE.items() if rx.search(text or "")]


@st.cache_data(show_spinner=False, ttl=3600, max_entries=4)
def _load(mtime: float):
    rev = read_table(APP_DB, "SELECT store, platform, source, rating, title, text, date, app_version, thumbs_up FROM app_reviews")
    meta = read_table(APP_DB, "SELECT store, stars, count FROM app_rating_histogram")
    if not rev.empty:
        rev["date"] = pd.to_datetime(rev["date"], errors="coerce", utc=True).dt.tz_localize(None)
        rev["rating"] = pd.to_numeric(rev["rating"], errors="coerce")
        rev["thumbs_up"] = pd.to_numeric(rev["thumbs_up"], errors="coerce").fillna(0).astype(int)
        rev["full_text"] = (rev["title"].fillna("").where(rev["title"].fillna("") != rev["text"].fillna(""), "") + " " + rev["text"].fillna("")).str.strip()
        rev["themes"] = rev["full_text"].map(_themes)
        # a low rating is the barrier signal here: the user tried it and it failed them
        rev["is_barrier"] = (rev["rating"] <= 2).astype(int)
        rev["sentiment"] = rev["rating"].map(lambda r: "positive" if r >= 4 else "neutral" if r == 3 else "negative")
    return rev, meta


def load_app_reviews():
    """(reviews, rating_histogram). Empty frames if the DB isn't there."""
    return _load(latest_mtime(APP_DB))


def theme_stage(theme: str) -> str:
    return THEMES[theme][1]


def theme_table(rev: pd.DataFrame) -> pd.DataFrame:
    """One row per theme: reviews mentioning it, avg rating, thumbs-up, stage."""
    rows = []
    for t in THEMES:
        sub = rev[rev["themes"].map(lambda x: t in x)]
        if sub.empty:
            continue
        rows.append({"Theme": t, "Stage": THEMES[t][1], "Reviews": len(sub),
                     "Avg rating": round(sub["rating"].mean(), 2), "Thumbs-up": int(sub["thumbs_up"].sum())})
    return pd.DataFrame(rows).sort_values("Reviews", ascending=False) if rows else pd.DataFrame()
