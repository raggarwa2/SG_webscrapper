"""
One theme per consumer item, so every brand is read on the same list.

The sources do not share a theme field: only Xiaohongshu, Lazada, KiasuParents and Google Maps carry a model-assigned
one, and YouTube, Reddit, Instagram and Facebook comments (about 60% of the pool) carry none. Scripts/theme_tag_sg.py
tags every pooled item once with 1 or 2 of the THEMES below and writes Scripts/output/theme_tags_sg.db. This module
reads that table and joins it to the Brand Health pool by brand + normalised text.

Until an item is tagged it falls back to a keyword draft (barrier_taxonomy.classify_b mapped through B_TO_THEME), so
the page works before the tagging run. The share of items on the fallback is reported on the page.

`queue()` writes the pool's untagged items to Scripts/output/theme_tag_queue.csv: the tagging script reads that file,
so it tags exactly the items the dashboard counts.
"""

import hashlib
import os
import sqlite3
from pathlib import Path

import pandas as pd
import streamlit as st

import barrier_taxonomy

OUT = Path(__file__).resolve().parent.parent / "Scripts" / "output"
TAG_DB = OUT / "theme_tags_sg.db"
QUEUE = OUT / "theme_tag_queue.csv"
OTHER = "Other / off-topic"

# theme -> what belongs in it (also the tagging prompt)
THEMES = {
    "Comfort & product": "how the lens feels and performs: comfort, dryness, irritation, vision quality, oxygen, durability, how long it lasts",
    "Price & value": "price, cost, discounts, value for money, cheaper elsewhere, subscription or bulk deals",
    "Look & colour": "appearance: colour, pupil size, natural or dramatic look, cosmetic or circle lenses",
    "Trust & authenticity": "genuine versus fake or grey-market, safety, eye health worries, recalls, brand trust and reputation",
    "Access & availability": "where to buy, stock, which channel or shop sells it, importing, selling or reselling lenses",
    "Fitting & guidance": "optometrist or ECP advice, eye test, prescription, trial lenses, first-time wearer handling, inserting or removing",
    "Loyalty & app": "points, rewards, vouchers, the MyACUVUE or brand app and how it works (crashes, hanging, slow, navigation, updates, date-of-birth entry), registration, login or OTP, marketing messages and unsubscribing",
    "Service": "store or customer service, staff or sales-person behaviour, delivery speed, packaging, support, wait times, returns; not problems with the app itself (those are Loyalty & app)",
}
# barrier label -> theme (the barrier list and this mapping live in barrier_taxonomy)
B_TO_THEME = barrier_taxonomy.THEME_OF
THEME_LIST = list(THEMES)

# The eight themes are the tagging layer. Headlines report at four decision groups, because only a few themes reach 15 items per
# brand group (one of eight in the Brand Health pool, three of four here). Each group has one owner and one kind of message.
GROUPS = {
    "Product & look": ["Comfort & product", "Look & colour"],
    "Price, access & trust": ["Price & value", "Access & availability", "Trust & authenticity"],
    "Guidance & service": ["Fitting & guidance", "Service"],
    "Loyalty & app": ["Loyalty & app"],
}
GROUP_OF = {t: g for g, ts in GROUPS.items() for t in ts}
GROUP_LIST = list(GROUPS)


norm = barrier_taxonomy.norm


def key(brand, text) -> str:
    return hashlib.sha1(f"{brand}|{norm(text)}".encode("utf-8")).hexdigest()[:16]


@st.cache_data(ttl=600, show_spinner=False, max_entries=2)
def _load(mtime: float) -> dict:
    if not TAG_DB.exists():
        return {}
    try:
        con = sqlite3.connect(f"file:{TAG_DB}?mode=ro", uri=True)
        rows = con.execute("SELECT key, themes FROM theme_tags").fetchall()
        con.close()
    except sqlite3.Error:
        return {}
    import json
    return {k: [t for t in json.loads(v) if t in THEMES] for k, v in rows}


def load() -> dict:
    return _load(TAG_DB.stat().st_mtime if TAG_DB.exists() else 0.0)


def attach(pooled: pd.DataFrame) -> pd.DataFrame:
    """Add `themes` (list of THEMES, empty = off-topic) and `tagged` (True = model tag, False = keyword draft)."""
    if pooled.empty:
        return pooled.assign(themes=[], tagged=[], key=[])
    tags = load()
    d = pooled.copy()
    d["key"] = [key(b, t) for b, t in zip(d["brand"], d["text"])]
    d["tagged"] = d["key"].isin(tags)
    draft = d["text"].map(lambda t: [B_TO_THEME[x] for x in barrier_taxonomy.classify_b(t) if x in B_TO_THEME])
    d["themes"] = [tags[k] if k in tags else dr for k, dr in zip(d["key"], draft)]
    return d


def queue(*frames) -> int:
    """Write the items that still need tags (no theme tag, or no barrier labels yet) for the tagging script, from any frames with
    brand, source and text columns (the Brand Health pool, the journey frame); sentiment and is_barrier ride along when present,
    because the tagger uses them as context. Set THEME_QUEUE_ALL=1 to write every item (used to re-tag). Returns how many wait."""
    cols = ["brand", "source", "text", "sentiment", "is_barrier"]
    parts = [f.reindex(columns=cols) for f in frames if f is not None and not f.empty]
    if not parts:
        return 0
    d = pd.concat(parts, ignore_index=True).dropna(subset=["text"])
    d = d[d["text"].map(lambda t: bool(norm(t)))].copy()
    d["key"] = [key(b, t) for b, t in zip(d["brand"], d["text"])]
    d = d.sort_values("is_barrier", na_position="first").drop_duplicates("key", keep="last")   # the frame that knows the flag wins
    if not os.environ.get("THEME_QUEUE_ALL"):
        d = d[~d["key"].isin(load()) | ~d["text"].map(barrier_taxonomy.is_tagged)]
    try:
        OUT.mkdir(exist_ok=True)
        d.to_csv(QUEUE, index=False, encoding="utf-8")
    except OSError:
        pass
    return len(d)
