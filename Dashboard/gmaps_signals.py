"""
Google Maps reviews of optical retailers (Optical 88, Owndays, Better Vision,
Capitol Optical, Visio Optical, Nanyang Optical) from Scripts/output/gmaps_data_sg.db
(project root), written by Scripts/google_maps_scraper_sg.py.

Consideration-stage signal: store-level friction (wait times, upsell pressure,
fitting quality...) before a fitting appointment. These are retailer reviews,
not brand reviews, so the sidebar brand filter does not apply and the data is
NOT part of the journey frame (journey_signals.py) -- it is shown in its own
section of the Journey & Barriers tab.

`contact_lens` = is_lens_related AND cl_keyword: the strict contact-lens
filter (is_lens_related alone also catches some spectacle-lens reviews).
"""

import pandas as pd
import streamlit as st

from sg_common import GMAPS_DB, latest_mtime, read_table

THEME_LABELS = {
    "wait_time": "Wait times",
    "upsell_pressure": "Upsell pressure",
    "staff_fitting_quality": "Staff & fitting quality",
    "pricing": "Pricing",
    "loyalty_points": "Loyalty / points",
    "stock_availability": "Stock availability",
}


@st.cache_data(show_spinner=False, ttl=3600, max_entries=4)
def _load(mtime: float):
    rev = read_table(
        GMAPS_DB,
        "SELECT r.review_id, r.place_id, r.chain, r.place_name, r.rating, r.text, r.published_at, "
        "r.likes, r.owner_response, r.sentiment, r.themes, r.is_friction, r.is_lens_related, r.cl_keyword, "
        "p.url AS place_url FROM gmaps_reviews r LEFT JOIN gmaps_places p ON p.place_id = r.place_id",
    )
    places = read_table(GMAPS_DB, "SELECT place_id, chain, name, rating, reviews_count, url FROM gmaps_places")
    if not rev.empty:
        rev["date"] = pd.to_datetime(rev["published_at"], errors="coerce", utc=True).dt.tz_localize(None)
        rev["rating"] = pd.to_numeric(rev["rating"], errors="coerce")
        rev["is_friction"] = pd.to_numeric(rev["is_friction"], errors="coerce").fillna(0).astype(int)
        rev["contact_lens"] = (
            (pd.to_numeric(rev["is_lens_related"], errors="coerce").fillna(0) == 1)
            & (pd.to_numeric(rev["cl_keyword"], errors="coerce").fillna(0) == 1)
        ).astype(int)
        rev["theme_list"] = rev["themes"].fillna("").map(lambda s: [t for t in s.split(",") if t])
    return rev, places


def load_gmaps():
    """(reviews, places). Empty frames if the DB isn't there."""
    return _load(latest_mtime(GMAPS_DB))


def theme_counts(rev: pd.DataFrame) -> pd.DataFrame:
    """Friction reviews per theme (a review can carry several)."""
    fr = rev[rev["is_friction"] == 1]
    rows = [
        {"Theme": label, "Friction reviews": int(fr["theme_list"].map(lambda x, k=key: k in x).sum())}
        for key, label in THEME_LABELS.items()
    ]
    out = pd.DataFrame(rows)
    return out[out["Friction reviews"] > 0].sort_values("Friction reviews", ascending=False)


def chain_table(rev: pd.DataFrame) -> pd.DataFrame:
    g = rev.groupby("chain").agg(
        Outlets=("place_id", "nunique"), Reviews=("review_id", "size"),
        **{"Avg rating": ("rating", "mean")}, Friction=("is_friction", "sum"),
    ).reset_index().rename(columns={"chain": "Chain"})
    g["Friction %"] = (g["Friction"] / g["Reviews"] * 100).round(1)
    g["Avg rating"] = g["Avg rating"].round(2)
    return g.sort_values("Friction %", ascending=False)
