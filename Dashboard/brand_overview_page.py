"""
Brand Overview: the first tab, laid out like the HK dashboard. All brands overview (balanced-score cards, ranking and
brand-by-channel heatmap, from brand_health_page), the sources that cannot be compared across brands, and the competitors and category page below.
"""

import pandas as pd
import streamlit as st

import app_store_signals
import brand_health_page
import ebi
import market_competitors
import ui
import voice_data as vd

def _source_strip(d: pd.DataFrame) -> None:
    """The sources that cannot be compared across brands, in one line of cards: the app (Acuvue only), Google Maps (stores, not brands)."""
    app, _ = app_store_signals.load_app_reviews()
    maps = vd.raw_by_source()
    maps_n = int(maps.loc[maps["source"] == "Google Maps", "collected"].sum())
    st.caption("**Also collected, not comparable across brands**")
    c1, c2, c3 = st.container(key="src-strip").columns(3)
    n_app = len(app) if app is not None else 0
    c1.metric("MyACUVUE app (Acuvue only)", f"{app['rating'].mean():.2f} / 5" if n_app >= ebi.MIN_N else "n/a", f"{n_app} store reviews", delta_color="off", delta_arrow="off")
    c2.metric("Google Maps (store experience)", f"{maps_n:,}", "reviews of lens retailers, not of brands", delta_color="off", delta_arrow="off")
    c3.metric("Retailer pages", "3 of 5 brands", "Acuvue, Alcon, Bausch & Lomb carry 15+ ratings", delta_color="off", delta_arrow="off")


def render(products: pd.DataFrame, reviews: pd.DataFrame, d: pd.DataFrame, brands: list, weighted_rating,
           caption: str, story_frames) -> None:
    pool = vd.pool(d) if not d.empty else pd.DataFrame(columns=["brand_std", "source"])
    ui.nav(["All brands overview", "Category"], title="On this page")
    ui.part("All brands overview")
    brand_health_page.all_brands_overview(d, brands)
    _source_strip(d)
    g1, g2, g3, g4, _ = st.columns([1, 1, 1, 1, 1.5])
    with g1:
        ui.goto("Brand Health", key="bo_to_health")
    with g2:
        ui.goto("Social Signals", key="bo_to_social")
    with g3:
        ui.goto("Retail & Promotions", key="bo_to_retail")
    with g4:
        ui.goto("Journey & App", key="bo_to_app")
    ui.part("Category")
    market_competitors.render_category()

    ui.read_comments(pool[pool["brand_std"].isin(brands)], "Read the brand comments behind this page (brand pool)", key="bo_read")
