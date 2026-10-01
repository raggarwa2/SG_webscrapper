"""
Contact Lens Market Intelligence — Singapore
Streamlit dashboard for the MyACUVUE SG project. Reads:
  Scripts/output/sg_acuvue.db        products + Lazada reviews + KiasuParents forum
  Scripts/output/xhs_data_sg.db      Xiaohongshu posts/comments
  Scripts/output/{youtube,instagram,facebook,reddit}_data_sg.db   social signals

Run with (from the Dashboard/ folder):
    streamlit run app.py

Database paths default to ../Scripts/output/ relative to this file (see
sg_common.py); the products/reviews DB can be overridden in the sidebar.
"""


import calendar
import json
import os
import re
import sqlite3
from datetime import datetime

import pandas as pd
import plotly.express as px
import plotly.graph_objects as go
from plotly.subplots import make_subplots
import streamlit as st

import app_store_signals
import barriers_friction
import brand_protection
import facebook_signals
import gmaps_signals
import instagram_signals
import journey_signals
import market_competitors
import overview_pages
import ui
import reddit_signals
import trends_signals
import youtube_signals
from sg_common import (
    BRAND_COLORS, JOURNEY_STAGES, SENTIMENT_COLORS, SG_DB, XHS_DB,
    normalize_brand, read_table,
)

# ----------------------------------------------------------------------------
# Page config + light styling
# ----------------------------------------------------------------------------

st.set_page_config(
    page_title="Contact Lens Market Intelligence — Singapore",
    page_icon="\U0001F441\uFE0F",
    layout="wide",
)

ui.inject_css()

_SITES_DISPLAY = "Lazada SG · TikTok Shop SG · Xiaohongshu · Reddit · KiasuParents · YouTube · Instagram · Facebook · App Store / Google Play · Google Maps · Google Trends"

DEFAULT_DB_PATH = SG_DB


def _prune_state(key: str, options) -> None:
    """Drop stale values from a keyed multiselect/selectbox's session state when
    its options have changed (e.g. a brand was unticked in the sidebar), so the
    widget keeps the still-valid picks instead of erroring or resetting."""
    cur = st.session_state.get(key)
    if cur is None:
        return
    if isinstance(cur, list):
        st.session_state[key] = [v for v in cur if v in options]
    elif cur not in options:
        del st.session_state[key]

# ----------------------------------------------------------------------------
# Data loading
# ----------------------------------------------------------------------------


@st.cache_data(ttl=3600, max_entries=4, show_spinner=False)
def load_data(db_path: str):
    """Load SG products/reviews (db_path = sg_acuvue.db) and XHS posts/comments
    (xhs_data_sg.db). Column names are mapped onto the names the rest of the
    app uses (name_en, total_reviews, review_text_en, product_code) and every
    brand spelling is normalised (see sg_common.normalize_brand). Cached for an
    hour rather than keyed on mtime — scrapers write to these DBs continuously.

    Returns (products, reviews, xhs, xhs_comments). `products` includes the
    compliance_flag == 1 (grey-market) rows — callers split them off."""
    products = read_table(db_path, "SELECT * FROM products")
    reviews = read_table(db_path, "SELECT * FROM reviews")
    xhs = read_table(XHS_DB, "SELECT * FROM xhs_posts")
    xhs_comments = read_table(XHS_DB, "SELECT * FROM xhs_comments")

    def parse_themes(val):
        try:
            return json.loads(val) if val else []
        except Exception:
            return []

    # A missing/unreadable table comes back as a column-less empty frame. Give
    # reviews/XHS the columns the tabs index (typed, so `.dt` etc. still work)
    # so a bad source degrades to "no data" instead of a KeyError.
    def _blank(obj=(), dates=(), nums=()):
        return pd.DataFrame({
            **{c: pd.Series(dtype="object") for c in obj},
            **{c: pd.Series(dtype="datetime64[ns]") for c in dates},
            **{c: pd.Series(dtype="float64") for c in nums},
        })

    if reviews.empty:
        reviews = _blank(
            ("id", "brand", "market", "site", "store_name", "product_code",
             "review_text", "review_text_en", "sentiment"),
            dates=("review_date",), nums=("rating",),
        )
    if xhs.empty:
        xhs = _blank(
            ("post_id", "brand", "brand_mentioned", "sentiment", "themes", "themes_list",
             "content_en", "url"),
            dates=("publish_date",), nums=("likes",),
        )
    if xhs_comments.empty:
        xhs_comments = _blank(
            ("post_id", "comment_id", "author", "sentiment", "themes", "themes_list", "content_en"),
            nums=("likes",),
        )

    # --- light cleanup ---
    if not reviews.empty:
        reviews["review_date"] = pd.to_datetime(reviews["review_date"], errors="coerce")
        reviews["brand"] = reviews["brand"].map(normalize_brand)
        reviews["review_text_en"] = reviews["review_text"]
        # same key products get (source_sku), so reviews can be joined to product names
        reviews["product_code"] = reviews["source_sku"]
        # a leftover test value from a sentiment-extraction test run
        reviews["sentiment"] = reviews["sentiment"].where(
            reviews["sentiment"].isin(["positive", "neutral", "negative", "mixed"])
        )

    if not xhs.empty:
        xhs["publish_date"] = pd.to_datetime(
            pd.to_numeric(xhs["publish_date"], errors="coerce"), unit="s", errors="coerce"
        )
        xhs["themes_list"] = xhs["themes"].apply(parse_themes)
        # brand_mentioned is only populated for posts the classifier has run on
        # (~30% of rows); "other" = a brand outside the five tracked. Spelling is
        # normalised so "MyACUVUE"/"Bausch + Lomb" match products.brand.
        xhs["brand_mentioned"] = xhs["brand_mentioned"].map(normalize_brand)
        xhs["brand"] = xhs["brand"].map(normalize_brand)

    if not xhs_comments.empty:
        xhs_comments["themes_list"] = xhs_comments["themes"].apply(parse_themes)

    if not products.empty:
        products["brand"] = products["brand"].map(normalize_brand)
        products["name_en"] = products["product_name"]
        products["total_reviews"] = pd.to_numeric(products["review_count"], errors="coerce").fillna(0)
        products["product_code"] = products["source_sku"].fillna(products["id"].astype(str))
        products["compliance_flag"] = products["compliance_flag"].fillna(0).astype(int)
        # SGD 0.01 listings are bad scrape data, not real prices (see data.md)
        products.loc[products["selling_price"] <= 0.01, "selling_price"] = float("nan")
        products["discount_pct"] = 0.0
        mask = (products["original_price"] > 0) & (
            products["original_price"] > products["selling_price"]
        )
        products.loc[mask, "discount_pct"] = (
            (products.loc[mask, "original_price"] - products.loc[mask, "selling_price"])
            / products.loc[mask, "original_price"]
            * 100
        )

    return products, reviews, xhs, xhs_comments

def weighted_rating(df: pd.DataFrame) -> float:
    """Review-volume-weighted average rating, ignoring unrated SKUs."""
    rated = df[df["total_reviews"] > 0]
    if rated.empty or rated["total_reviews"].sum() == 0:
        return float("nan")
    return (rated["avg_rating"] * rated["total_reviews"]).sum() / rated["total_reviews"].sum()


_SITE_DISPLAY_NAMES = {
    "lazada_sg":   "Lazada SG",
    "tiktok_shop": "TikTok Shop SG",
}


def _site_caption(df: pd.DataFrame, date_col: str = None, count_label: str = "items", one_line: bool = False) -> str:
    """Build a 'Site · date range · count' caption string, one line per site.

    A bare min–max range reads as if coverage were roughly even across it,
    which is misleading when a site's early months are a handful of rows
    and the real volume only shows up much later — so any site where the
    oldest 20% of rows are confined to date range materially shorter than
    the full span gets a "sparse before {date}" note calling that out."""
    if df.empty or "site" not in df.columns:
        return ""
    parts = []
    for site, grp in df.groupby("site"):
        n = len(grp)
        display = _SITE_DISPLAY_NAMES.get(site, site)
        if date_col and date_col in grp.columns:
            dates = pd.to_datetime(grp[date_col], errors="coerce").dropna().sort_values()
            if not dates.empty:
                lo = dates.min().strftime("%b %Y")
                hi = dates.max().strftime("%b %Y")
                bulk_start = dates.iloc[int(len(dates) * 0.2)]
                sparse_note = ""
                if bulk_start.to_period("M") > dates.min().to_period("M"):
                    sparse_note = f" — sparse before {bulk_start.strftime('%b %Y')}"
                if lo == hi:
                    parts.append(f"**{display}** · {lo} only · {n:,} {count_label}")
                else:
                    parts.append(f"**{display}** · {lo} – {hi} · {n:,} {count_label}{sparse_note}")
            else:
                parts.append(f"**{display}** · {n:,} {count_label}")
        else:
            parts.append(f"**{display}** · {n:,} {count_label}")
    return "   |   ".join(parts) if one_line else "  \n".join(parts)


# ----------------------------------------------------------------------------
# Sidebar — data source + filters
# ----------------------------------------------------------------------------

st.sidebar.title("Contact Lens Intelligence")
st.sidebar.caption("Singapore \u2014 Acuvue, Alcon, Bausch & Lomb, CooperVision, Olens")

db_path = st.sidebar.text_input("Products/reviews database", value=DEFAULT_DB_PATH)

if not os.path.exists(db_path):
    st.error(
        f"Can't find a database at `{db_path}`. Update the path in the "
        "sidebar \u2014 point it at Scripts/output/sg_acuvue.db."
    )
    st.stop()

mtime = os.path.getmtime(db_path)  # display only now \u2014 no longer part of load_data's cache key
products_all, reviews, xhs, xhs_comments = load_data(db_path)
if products_all.empty:
    st.error(
        f"No products could be read from `{db_path}`. The file exists, but its `products` "
        "table is missing, empty or unreadable (locked or corrupt?) — check the terminal log."
    )
    st.stop()
# compliance_flag == 1 rows are grey-market listings: kept out of every product-
# intelligence number, shown only in the Market & Channel → Brand protection sub-tab.
products = products_all[products_all["compliance_flag"] == 0]
products_compliance = products_all[products_all["compliance_flag"] == 1]
# Social platforms live in their own DBs (Scripts/output/*_data_sg.db) \u2014 see
# _social.py. *_posts_df already excludes brand/market-irrelevant posts;
# *_comments_df still includes off-topic comments (is_lens_relevant == 0) \u2014
# call <module>.on_topic_comments() before using for sentiment/barrier scoring.
youtube_videos_df, youtube_comments_df, _yt_excluded_videos = youtube_signals.load_sg_dashboard_data()
instagram_posts_df, instagram_comments_df, _ig_excluded_posts = instagram_signals.load_sg_dashboard_data()
facebook_posts_df, facebook_comments_df, _fb_excluded_posts = facebook_signals.load_sg_dashboard_data()
reddit_posts_df, reddit_comments_df, _reddit_excluded_posts = reddit_signals.load_sg_dashboard_data()
# Reddit on-topic comments, shaped like the old forum frame (one brand per row in
# mentioned_brands_list) so Brand Health/Overview can treat it like any other source.
reddit_df = reddit_signals.on_topic_comments(reddit_comments_df).copy() if not reddit_comments_df.empty else pd.DataFrame()
if not reddit_df.empty:
    reddit_df["mentioned_brands_list"] = reddit_df["brand"].apply(lambda b: [b] if pd.notna(b) else [])
_SG_PRODUCTS = products[products["market"] == "SG"]
# Brand filter = the five tracked brands that have data in ANY source (Olens, e.g.,
# has social data but only grey-market product listings, so products alone would drop it).
_seen_brands = set(_SG_PRODUCTS["brand"].dropna()) | set(reviews["brand"].dropna())
for _df in (youtube_videos_df, instagram_posts_df, facebook_posts_df, reddit_posts_df):
    if not _df.empty:
        _seen_brands |= set(_df["brand"].dropna())
all_brands = [b for b in BRAND_COLORS if b in _seen_brands]
with st.sidebar.form("sidebar_filters", border=False):
    selected_brands = st.multiselect("Brands", all_brands, default=all_brands, key="sb_brands")
    st.form_submit_button("Apply filters", icon=":material/check:", width="stretch")

st.sidebar.divider()
st.sidebar.caption(
    f"Database file updated:\n{datetime.fromtimestamp(mtime).strftime('%Y-%m-%d %H:%M')}\n\n"
    "Data is cached for up to 1 hour."
)
if st.sidebar.button("Reload data", icon=":material/refresh:", width="stretch"):
    st.cache_data.clear()
    st.rerun()
_xhs_attributed = xhs[xhs["brand_mentioned"].notna() & (xhs["brand_mentioned"] != "other")]
_youtube_on_topic_all = youtube_signals.on_topic_comments(youtube_comments_df)
_instagram_on_topic_all = instagram_signals.on_topic_comments(instagram_comments_df)
_facebook_on_topic_all = facebook_signals.on_topic_comments(facebook_comments_df)
_reddit_on_topic_all = reddit_signals.on_topic_comments(reddit_comments_df)
_app_reviews_all, _ = app_store_signals.load_app_reviews()
_gmaps_reviews_all, _ = gmaps_signals.load_gmaps()
_total_content = (
    len(reviews) + len(xhs) + len(xhs_comments) + len(_reddit_on_topic_all)
    + len(_youtube_on_topic_all) + len(_instagram_on_topic_all) + len(_facebook_on_topic_all)
    + len(_app_reviews_all) + len(_gmaps_reviews_all)
)
_trends_all = trends_signals.load()
_trends_points = len(_trends_all)
st.sidebar.markdown(f"**{_total_content + _trends_points:,} data points analyzed**")
st.sidebar.caption(
    f"{_total_content:,} pieces of consumer content"
    + (f" + {_trends_points:,} Google Trends data points (search-interest index, not content)" if _trends_points else "")
)
st.sidebar.caption(
    f"{len(products_all)} product listings: {len(products)} compliant "
    f"({int(products['brand'].isin(BRAND_COLORS).sum())} in the five tracked brands), "
    f"{len(products_compliance)} grey-market excluded \u00b7 "
    f"{len(reviews)} reviews \u00b7 "
    f"{len(xhs)} XHS posts ({len(_xhs_attributed)} brand-attributed) \u00b7 "
    f"{len(xhs_comments)} XHS comments \u00b7 {len(_reddit_on_topic_all)} Reddit comments \u00b7 "
    f"{len(_youtube_on_topic_all)} YouTube comments \u00b7 "
    f"{len(_instagram_on_topic_all)} Instagram comments \u00b7 "
    f"{len(_facebook_on_topic_all)} Facebook comments · "
    f"{len(_app_reviews_all)} app store reviews · "
    f"{len(_gmaps_reviews_all):,} Google Maps retailer reviews"
)
# Google Trends is a search-interest index, not consumer content: it is included
# in the headline "data points" total but labelled separately above.
if _trends_points:
    _trends_terms = _trends_all.loc[_trends_all["term"] != trends_signals.ANCHOR, "term"].nunique()
    st.sidebar.caption(
        f"Search demand (Google Trends index, not content): {_trends_terms} terms · "
        f"{_trends_all['date'].nunique()} weeks · {_trends_points:,} data points"
    )

products_f = products[
    products["brand"].isin(selected_brands) & (products["market"] == "SG")
]
reviews_f = reviews[
    reviews["brand"].isin(selected_brands) & (reviews["market"] == "SG")
]
# ----------------------------------------------------------------------------
# Header + top-line KPIs
# ----------------------------------------------------------------------------

_currency_sym = "S$"
_currency_lbl = "SGD"

ui.banner(
    "Contact Lens Market Intelligence \u2014 Singapore",
    eyebrow="MyACUVUE SG \u00b7 Barrier & funnel analysis",
    subtitle=_SITES_DISPLAY,
    pills=[f"{len(selected_brands)} brands", f"{len(products_f)} products tracked", "SGD"],
)

# Headline findings \u2014 live, computed from the same frames the tabs below use.
jf_all = journey_signals.load_journey_frame()
_jf = jf_all[jf_all["brand"].isin(selected_brands)] if not jf_all.empty else jf_all
_finds = []

_n_comp, _n_all = len(products_compliance), len(products_all)
if _n_all:
    _top_site = products_compliance["site"].map(lambda s: _SITE_DISPLAY_NAMES.get(s, s)).value_counts()
    _finds.append((
        f"{_n_comp / _n_all * 100:.0f}% of listings are grey-market.",
        f"<b>{_n_comp} of {_n_all}</b> product listings carry a compliance flag"
        + (f", most on <b>{_top_site.index[0]}</b>" if not _top_site.empty else "")
        + ". They are kept out of every product-intelligence number and shown in Journey &amp; Barriers.",
        "warn",
    ))

_soc = _jf[_jf["source"].isin(["YouTube", "Instagram", "Facebook", "Reddit"])] if not _jf.empty else _jf
if not _soc.empty:
    _by_stage = _soc.groupby("journey_stage").agg(n=("is_barrier", "size"), b=("is_barrier", "sum"))
    _by_stage = _by_stage[_by_stage["n"] >= 20]
    if not _by_stage.empty:
        _by_stage["rate"] = _by_stage["b"] / _by_stage["n"] * 100
        _stage = _by_stage["rate"].idxmax()
        _finds.append((
            f"Purchase barriers peak at {_stage}.",
            f"<b>{_by_stage.loc[_stage, 'rate']:.0f}%</b> of on-topic social comments at this stage flag a purchase barrier "
            f"({int(_by_stage.loc[_stage, 'b'])} of {int(_by_stage.loc[_stage, 'n'])}). Stage tags are per source, so read as directional.",
            "alert",
        ))

if not _jf.empty:
    _vol = _jf.drop_duplicates(subset=["source", "text"]).groupby("brand").size().sort_values(ascending=False)
    if not _vol.empty:
        _finds.append((
            f"{_vol.index[0]} leads the conversation.",
            f"<b>{_vol.iloc[0] / _vol.sum() * 100:.0f}%</b> of {int(_vol.sum()):,} analysed comments and posts mention {_vol.index[0]}, "
            f"across <b>{_jf['source'].nunique()}</b> sources.",
            "",
        ))
if _finds:
    ui.findings(_finds)

# \u2500\u2500 Row 1: review intelligence KPIs \u2500\u2500\u2500\u2500\u2500\u2500\u2500\u2500\u2500\u2500\u2500\u2500\u2500\u2500\u2500\u2500\u2500\u2500\u2500\u2500\u2500\u2500\u2500\u2500\u2500\u2500\u2500\u2500\u2500\u2500\u2500\u2500\u2500\u2500\u2500\u2500\u2500\u2500\u2500\u2500\u2500
ins_cols = st.columns(4)

# 1) Reviews & posts analyzed — Lazada reviews + XHS posts + on-topic Reddit /
#    YouTube / Instagram / Facebook comments, all scoped to the current brand
#    filter, so the headline number reflects everything the dashboard draws on.
_xhs_f_count = len(xhs[xhs["brand_mentioned"].isin(selected_brands)]) if not xhs.empty else 0


def _on_topic_count(module, comments_df):
    if comments_df.empty:
        return 0
    return len(module.on_topic_comments(comments_df[comments_df["brand"].isin(selected_brands)]))


_reddit_f_count = _on_topic_count(reddit_signals, reddit_comments_df)
_youtube_f_count = _on_topic_count(youtube_signals, youtube_comments_df)
_instagram_f_count = _on_topic_count(instagram_signals, instagram_comments_df)
_facebook_f_count = _on_topic_count(facebook_signals, facebook_comments_df)
_total_analyzed = (
    len(reviews_f) + _xhs_f_count + _reddit_f_count + _youtube_f_count + _instagram_f_count + _facebook_f_count
)
ins_cols[0].metric(
    "Reviews & posts analyzed", f"{_total_analyzed:,}",
    help=(
        "All review/post text analyzed for the current brand filter:\n\n"
        f"- {len(reviews_f):,} reviews (Lazada SG)\n"
        f"- {_xhs_f_count:,} Xiaohongshu (XHS) posts\n"
        f"- {_reddit_f_count:,} Reddit comments\n"
        f"- {_youtube_f_count:,} YouTube comments\n"
        f"- {_instagram_f_count:,} Instagram comments\n"
        f"- {_facebook_f_count:,} Facebook comments"
    ),
)

# 2) Positive sentiment % with 90-day trend delta
if not reviews_f.empty:
    _rated = reviews_f[reviews_f["rating"] > 0]
    _pos_pct = (_rated["rating"] >= 4).sum() / max(len(_rated), 1) * 100
    _now  = reviews_f["review_date"].dropna().max()
    _cut  = _now  - pd.DateOffset(days=90)
    _prev = _cut  - pd.DateOffset(days=90)
    _recent = reviews_f[reviews_f["review_date"] >= _cut]
    _prior  = reviews_f[(reviews_f["review_date"] >= _prev) & (reviews_f["review_date"] < _cut)]
    _r_pos  = (_recent["rating"] >= 4).mean() * 100 if len(_recent) else float("nan")
    _p_pos  = (_prior["rating"]  >= 4).mean() * 100 if len(_prior)  else float("nan")
    _delta  = round(_r_pos - _p_pos, 1) if pd.notna(_r_pos) and pd.notna(_p_pos) else None
    ins_cols[1].metric(
        "Positive sentiment",
        f"{_pos_pct:.0f}%",
        delta=f"{_delta:+.1f}pp vs prev 90d" if _delta is not None else None,
        help=(
            "% of rated reviews with rating \u2265 4 stars.\n\n"
            "Formula: (reviews with rating \u2265 4) \u00f7 (all rated reviews) \u00d7 100\n\n"
            "Trend (pp): positive % in latest 90 days minus positive % in prior 90 days."
        ),
    )
else:
    ins_cols[1].metric("Positive sentiment", "\u2014",
        help="% of rated reviews with rating \u2265 4 stars.")

# 3) Review leader \u2014 brand with the most reviews
if not reviews_f.empty:
    _brand_counts = reviews_f.groupby("brand").size().sort_values(ascending=False)
    _top_brand = _brand_counts.index[0]
    _top_count = int(_brand_counts.iloc[0])
    ins_cols[2].metric("Review leader", _top_brand, delta=f"{_top_count:,} reviews", delta_color="off",
        help="Brand with the highest review count in the current filter. Delta shows that brand's total reviews.")
else:
    ins_cols[2].metric("Review leader", "\u2014",
        help="Brand with the highest review count in the current filter.")

# 4) Data window
if not reviews_f.empty:
    _dated = reviews_f["review_date"].dropna()
    if not _dated.empty:
        _lo = _dated.min().strftime("%b %Y")
        _hi = _dated.max().strftime("%b %Y")
        ins_cols[3].metric("Data window", f"{_lo} \u2013 {_hi}",
            help=(
                "Earliest to latest review date in the current filter.\n\n"
                "Note: coverage is heavier in recent years \u2014 earlier years in this "
                "window have far fewer reviews, so any trend read from that period "
                "is based on a much smaller sample."
            ))
    else:
        ins_cols[3].metric("Data window", "\u2014",
            help="Earliest to latest review date in the current filter.")
else:
    ins_cols[3].metric("Data window", "\u2014",
        help="Earliest to latest review date in the current filter.")

# \u2500\u2500 Row 2: product / store KPIs \u2500\u2500\u2500\u2500\u2500\u2500\u2500\u2500\u2500\u2500\u2500\u2500\u2500\u2500\u2500\u2500\u2500\u2500\u2500\u2500\u2500\u2500\u2500\u2500\u2500\u2500\u2500\u2500\u2500\u2500\u2500\u2500\u2500\u2500\u2500\u2500\u2500\u2500\u2500\u2500\u2500\u2500\u2500
st.write("")
kpi_cols = st.columns(4)

kpi_cols[0].metric("Products tracked", f"{len(products_f):,}",
    help="Distinct product listings in the current filter (compliance-flagged grey-market listings excluded).")
kpi_cols[1].metric("Stores covered", f"{products_f['store_name'].nunique():,}",
    help="Number of unique store names carrying tracked products in the current filter.")
overall_rating = weighted_rating(products_f)
kpi_cols[2].metric(
    "Weighted avg. rating",
    f"{overall_rating:.2f} \u2605" if pd.notna(overall_rating) else "\u2014",
    help=(
        "Weighted mean rating across all tracked products.\n\n"
        "Formula: \u03a3(rating \u00d7 review_count) \u00f7 \u03a3(review_count)"
    ),
)
kpi_cols[3].metric(
    "Brands with reviews",
    f"{reviews_f['brand'].nunique():,}" if not reviews_f.empty else "\u2014",
    help="Number of distinct brands present in the filtered review dataset.",
)

st.divider()

# ----------------------------------------------------------------------------
# Tabs
# ----------------------------------------------------------------------------

# --- Sub-brand helpers (shared across tabs) ---
# Ordered (bucket, keywords) per brand — first matching bucket wins, so more
# specific/newer product lines are listed before broader ones (e.g. Acuvue's
# "Max" — Oasys Max 1-Day — must be checked before the generic "Oneday"
# bucket, or it folds into plain Oasys/HydraLuxe 1-day products).
_SUBBRAND_RULES = {
    "Acuvue": [
        ("1Day Max", ["max"]),
        ("Define",   ["define"]),
        ("Moist",    ["moist"]),
        ("Oneday",   ["1 day", "1-day", "oneday", "one day", "hydraluxe"]),
        # Lens-care solution, not a lens. Last so existing sub-brand colours (assigned
        # by position) don't shift; accepts the "Revita Lens" spelling some sellers use.
        ("RevitaLens", ["revitalens", "revita lens"]),
    ],
    "Alcon": [
        ("Dailies Total1",      ["dailies total", "total 1", "total1"]),
        ("Dailies AquaComfort", ["aquacomfort"]),
        ("Dailies FreshLook",   ["freshlook", "fresh look"]),
        ("Air Optix",           ["air optix", "airoptix"]),
        ("Precision1",          ["precision1", "precision 1"]),
    ],
    "Bausch & Lomb": [
        ("Lacelle", ["lacelle"]),
        ("Biotrue", ["biotrue"]),
        ("SofLens", ["soflens", "sof lens"]),
        ("Ultra",   ["ultra"]),
    ],
    "CooperVision": [
        ("Clariti",   ["clariti"]),
        ("Biomedics", ["biomedics"]),
        ("Proclear",  ["proclear"]),
        ("Biofinity", ["biofinity"]),
    ],
    "Olens": [
        ("Vivi Ring",   ["vivi ring", "viviring"]),
        ("Gold Series", ["gold series"]),
        ("O2 Edition",  ["o2 edition"]),
    ],
}
_SUBBRAND_LISTS = {brand: [s for s, _ in rules] for brand, rules in _SUBBRAND_RULES.items()}

# Fixed palette assigned by position within a brand's sub-brand list, so every
# brand gets visually distinct sub-brand colors without hand-picking each one.
_SUBBRAND_PALETTE = ["#178197", "#0A7CC1", "#A51890", "#051F4A", "#59A5D7", "#7A5C99"]
_SUBBRAND_OTHER_COLOR = "#94a3b8"


def _subbrand(brand, name):
    """Classify a product name into its brand's sub-brand bucket, or "Other"
    if the brand has no rules defined or none of its keywords match."""
    if pd.isna(name):
        return "Other"
    rules = _SUBBRAND_RULES.get(brand)
    if not rules:
        return "Other"
    n = name.lower()
    for bucket, keywords in rules:
        if any(kw in n for kw in keywords):
            return bucket
    return "Other"


def _subbrand_color(brand, sub):
    subs = _SUBBRAND_LISTS.get(brand, [])
    if sub in subs:
        return _SUBBRAND_PALETTE[subs.index(sub) % len(_SUBBRAND_PALETTE)]
    return _SUBBRAND_OTHER_COLOR

# "New wearer" = reviewer explicitly states this purchase/lens is their first
# (e.g. "first time buying", "my first purchase", "first time trying this brand").
# NEG excludes cases where "first time" refers to a problem occurring for the
# first time on an otherwise long-standing customer (e.g. "I've worn contacts
# for 10 years, this is the first time I've had one crack") — those are
# existing wearers, not new ones.
_NEW_WEARER_POS_RE = re.compile(
    r"first time (buying|using|trying|shopping|purchasing|ordering)"
    r"|my first (purchase|order|time (buying|using|trying|shopping))"
    r"|first (purchase|order)\b",
    re.I,
)
_NEW_WEARER_NEG_RE = re.compile(
    r"(not|isn.t|wasn.t) (the |my )?first"
    r"|first time (i.ve|i had|i experienced|i encountered|this happened|encountering|encountered|experienc|faced|such)"
    r"|repurchased"
    r"|for (many|over) (years|\d+\s*years)"
    r"|worn contact lenses for"
    r"|wearing contact lenses for"
    r"|many purchases"
    r"|many times"
    r"|in \d+ years",
    re.I,
)


def _is_new_wearer_review(text):
    if pd.isna(text):
        return False
    return bool(_NEW_WEARER_POS_RE.search(text)) and not _NEW_WEARER_NEG_RE.search(text)

# Six top-level tabs, one home per fact (see EBI_insights_plan.md, "Proposed restructure").
# Each old page body below is kept as is and re-homed as a sub-tab.
(t_summary, t_brand, t_barriers, t_market_channel, t_social, t_evidence) = st.tabs(
    ["Summary", "Brand Health", "Barriers", "Market & Channel", "Social & Messaging", "Evidence & Stage 2"],
    on_change="rerun",  # dynamic tabs: only the selected tab's body runs (see `.open` guards below)
    key="main_tabs",
)
with t_brand:
    tab_overview, tab_brand_health = st.tabs(["Overview", "Sentiment"], on_change="rerun", key="brand_subtabs")
with t_barriers:
    tab_journey, tab_friction = st.tabs(["Journey", "App & friction"], on_change="rerun", key="barrier_subtabs")
with t_market_channel:
    tab_market, tab_price, tab_reviews_sentiment, tab_retail, tab_protect = st.tabs(
        ["Competitors & category", "Price", "Product reviews", "Retailers", "Brand protection"],
        on_change="rerun", key="market_subtabs",
    )
tab_social_signals = t_social
with t_evidence:
    tab_stage2, tab_catalog, tab_notes = st.tabs(
        ["Stage 2 bridge", "Data explorer", "Data notes"], on_change="rerun", key="evidence_subtabs"
    )

if t_summary.open:
    with t_summary:
        overview_pages.render_summary()

if tab_stage2.open:
    with tab_stage2:
        overview_pages.render_evidence()

# ---- Stage 1 EBI read-out pages (see EBI_insights_plan.md) -------------------
if tab_protect.open:
    with tab_protect:
        brand_protection.render(products_all)

if tab_friction.open:
    with tab_friction:
        barriers_friction.render(jf_all)

if tab_market.open:
    with tab_market:
        market_competitors.render(products, jf_all, selected_brands)

# ---- Brand Overview ---------------------------------------------------------
if tab_overview.open:
    with tab_overview:
        ui.subheader("Brand health scorecard", eyebrow="Overview")
        st.caption(_site_caption(reviews_f, "review_date", "reviews"))
        st.caption(
            "Social columns: XHS posts, Reddit/YouTube/Instagram/Facebook comments "
            "(on-topic only — see Social Signals for what that excludes). "
            "See Brand Health for sentiment blended across these sources."
        )

        # Per-brand social counts — same source dataframes/helpers as the Brand
        # Health tab (on-topic filtering for YouTube/Instagram, raw mention counts
        # for XHS), just scoped to one brand at a time here.
        rows = []
        for b in selected_brands:
            bp = products_f[products_f["brand"] == b]
            br = reviews_f[reviews_f["brand"] == b]
            xhs_n = len(xhs[xhs["brand_mentioned"] == b]) if not xhs.empty else 0
            reddit_n = (
                len(reddit_signals.on_topic_comments(reddit_comments_df[reddit_comments_df["brand"] == b]))
                if not reddit_comments_df.empty else 0
            )
            youtube_n = (
                len(youtube_signals.on_topic_comments(youtube_comments_df[youtube_comments_df["brand"] == b]))
                if not youtube_comments_df.empty else 0
            )
            instagram_n = (
                len(instagram_signals.on_topic_comments(instagram_comments_df[instagram_comments_df["brand"] == b]))
                if not instagram_comments_df.empty else 0
            )
            facebook_n = (
                len(facebook_signals.on_topic_comments(facebook_comments_df[facebook_comments_df["brand"] == b]))
                if not facebook_comments_df.empty else 0
            )
            rows.append(
                {
                    "Brand": b,
                    "Products": len(bp),
                    "Stores": bp["store_name"].nunique(),
                    "Weighted rating": round(weighted_rating(bp), 2),
                    "Reviews collected": len(br),
                    "XHS posts": xhs_n,
                    "Reddit comments": reddit_n,
                    "YouTube comments": youtube_n,
                    "Instagram comments": instagram_n,
                    "Facebook comments": facebook_n,
                    "Social signals": xhs_n + reddit_n + youtube_n + instagram_n + facebook_n,
                }
            )
        scorecard = pd.DataFrame(rows, columns=["Brand", "Products", "Stores", "Weighted rating", "Reviews collected", "XHS posts", "Reddit comments", "YouTube comments", "Instagram comments", "Facebook comments", "Social signals"])

        if not scorecard.empty and scorecard["Social signals"].sum():
            _lead = scorecard.sort_values("Social signals", ascending=False).iloc[0]
            _ins = f"<b>{_lead['Brand']}</b> has the most social voice ({int(_lead['Social signals']):,} signals)"
            _rated = scorecard.dropna(subset=["Weighted rating"])
            if not _rated.empty:
                _rb = _rated.sort_values("Weighted rating", ascending=False).iloc[0]
                _ins += f"; <b>{_rb['Brand']}</b> has the highest weighted product rating ({_rb['Weighted rating']:.2f}\u2605)"
            ui.insight(_ins + ". Ratings come from Lazada/TikTok Shop only \u2014 read with the review counts.")

        with st.container(border=True):
            st.dataframe(
                scorecard,
                hide_index=True,
                width="stretch",
                column_config={
                    "Brand": st.column_config.TextColumn(pinned=True),
                    "Weighted rating": st.column_config.NumberColumn(format="%.2f \u2605"),
                    **{
                        c: st.column_config.NumberColumn(format="localized")
                        for c in scorecard.columns
                        if c not in ("Brand", "Weighted rating")
                    },
                },
            )

        c1, c2 = st.columns(2)
        with c1:
            fig = px.bar(
                scorecard,
                x="Brand",
                y="Weighted rating",
                color="Brand",
                color_discrete_map=BRAND_COLORS,
                title="Weighted average rating by brand",
                range_y=[0, 5],
            )
            fig.update_layout(showlegend=False)
            st.plotly_chart(fig, width='stretch')
        with c2:
            fig = px.bar(
                scorecard,
                x="Brand",
                y="Reviews collected",
                color="Brand",
                color_discrete_map=BRAND_COLORS,
                title="Reviews collected by brand",
            )
            fig.update_layout(showlegend=False)
            st.plotly_chart(fig, width='stretch')

# ---- Brand Health -----------------------------------------------------------
if tab_brand_health.open:
    with tab_brand_health:
        ui.subheader("Brand Health", "Composite 0-100 score across reviews, XHS and social comment sentiment.", "Sentiment")
        with st.expander("How this score is built (read before quoting)"):
            st.markdown(
            """
        <div class="caveat-box">
        <b>How this score is built:</b> each brand gets a single 0-100 composite score
        blending sentiment sources — <b>Reviews</b> (star-rating based, Lazada SG only;
        no Acuvue reviews are collected), <b>XHS</b> (LLM-labeled post sentiment, only for
        the ~30% of posts the classifier has run on), <b>Reddit</b>, <b>YouTube</b>,
        <b>Instagram</b> and <b>Facebook</b> (all LLM-labeled comment sentiment, on-topic
        comments only — see Social Signals for what "on-topic" excludes).
        Every source's "% positive" counts <b>positive+neutral</b> together (not positive
        alone) — a brand only loses points here for actual negative sentiment; hover a card
        to see its raw n. Each source is weighted by &radic;n so a
        large base doesn't drown out a thinner one, but a source with fewer than 5
        qualifying items for a brand is excluded entirely rather than let a tiny sample
        swing the score — excluded sources are shown on each card. Reddit and Facebook are
        shown only as snapshot scores, not in the monthly trend chart below. Rows
        with dirty/unparseable sentiment values, and posts/comments excluded as not actually
        brand-relevant, off-topic or not SG-relevant (see Social Signals) are excluded from
        scoring. Grey-market (compliance-flagged) listings never enter these numbers.
        SG volumes are small — treat scores as directional.
        </div>
        """,
                unsafe_allow_html=True,
            )

        MIN_N_FOR_SOURCE = 5
        _VALID_SENTIMENTS = ["positive", "neutral", "negative"]

        def _source_pos_pct(sub_df: pd.DataFrame, sentiment_col: str = "sentiment", include_neutral: bool = False):
            """(pos_pct, n) for a dataframe already filtered to one brand/source, using
        only valid sentiment labels. Returns (None, 0) if there's nothing usable.

        include_neutral=True counts neutral alongside positive in the numerator
        (still divided by the same valid n) — used for YouTube/Instagram, whose
        short unsolicited comments skew neutral far more than star-rated Reviews
        or long-form XHS posts do, so a positive-only % reads misleadingly
        low next to the Social Signals tabs' framing of "not negative" as good."""
            if sub_df.empty or sentiment_col not in sub_df.columns:
                return None, 0
            valid = sub_df[sub_df[sentiment_col].isin(_VALID_SENTIMENTS)]
            n = len(valid)
            if n == 0:
                return None, 0
            counted = ["positive", "neutral"] if include_neutral else ["positive"]
            return valid[sentiment_col].isin(counted).mean() * 100, n

        # Reviews sentiment — same rating-derived rule as the Reviews & Sentiment tab.
        rev_bh = reviews_f.dropna(subset=["rating"]).copy()
        rev_bh = rev_bh[rev_bh["rating"] > 0]
        rev_bh["sentiment"] = rev_bh["rating"].apply(
            lambda r: "positive" if r >= 4 else ("neutral" if r == 3 else "negative")
        )

        # XHS sentiment — brand-attributed posts only ("other" already excluded by isin).
        xhs_bh = xhs[xhs["brand_mentioned"].isin(selected_brands)].copy() if not xhs.empty else pd.DataFrame()

        # Reddit sentiment — on-topic comments (reddit_df built at the top of the file).
        reddit_bh = reddit_df[reddit_df["brand"].isin(selected_brands)] if not reddit_df.empty else pd.DataFrame()

        # YouTube sentiment — on-topic comments only (youtube_videos_df/youtube_comments_df
        # already exclude brand-irrelevant videos, loaded at the top of the file).
        youtube_bh = (
            youtube_signals.on_topic_comments(youtube_comments_df[youtube_comments_df["brand"].isin(selected_brands)])
            if not youtube_comments_df.empty else pd.DataFrame()
        )

        # Instagram sentiment — on-topic comments only (instagram_posts_df/instagram_comments_df
        # already exclude brand-irrelevant/off-topic posts, loaded at the top of the file).
        # Full 5th source, same treatment as YouTube — no toggle, just the same n>=5 gating.
        instagram_bh = (
            instagram_signals.on_topic_comments(instagram_comments_df[instagram_comments_df["brand"].isin(selected_brands)])
            if not instagram_comments_df.empty else pd.DataFrame()
        )

        # Facebook sentiment — on-topic comments only, same treatment as YouTube/Instagram.
        facebook_bh = (
            facebook_signals.on_topic_comments(facebook_comments_df[facebook_comments_df["brand"].isin(selected_brands)])
            if not facebook_comments_df.empty else pd.DataFrame()
        )

        def _brand_score(brand: str):
            components = []  # list of (label, pos_pct, n)
            pos, n = _source_pos_pct(rev_bh[rev_bh["brand"] == brand], include_neutral=True)
            if pos is not None and n >= MIN_N_FOR_SOURCE:
                components.append(("Reviews", pos, n))
            xb_ = xhs_bh[xhs_bh["brand_mentioned"] == brand] if not xhs_bh.empty else pd.DataFrame()
            pos, n = _source_pos_pct(xb_, include_neutral=True)
            if pos is not None and n >= MIN_N_FOR_SOURCE:
                components.append(("XHS", pos, n))
            rb_ = reddit_bh[reddit_bh["brand"] == brand] if not reddit_bh.empty else pd.DataFrame()
            pos, n = _source_pos_pct(rb_, include_neutral=True)
            if pos is not None and n >= MIN_N_FOR_SOURCE:
                components.append(("Reddit", pos, n))
            yb_ = youtube_bh[youtube_bh["brand"] == brand] if not youtube_bh.empty else pd.DataFrame()
            pos, n = _source_pos_pct(yb_, include_neutral=True)
            if pos is not None and n >= MIN_N_FOR_SOURCE:
                components.append(("YouTube", pos, n))
            ib_ = instagram_bh[instagram_bh["brand"] == brand] if not instagram_bh.empty else pd.DataFrame()
            pos, n = _source_pos_pct(ib_, include_neutral=True)
            if pos is not None and n >= MIN_N_FOR_SOURCE:
                components.append(("Instagram", pos, n))
            fb_ = facebook_bh[facebook_bh["brand"] == brand] if not facebook_bh.empty else pd.DataFrame()
            pos, n = _source_pos_pct(fb_, include_neutral=True)
            if pos is not None and n >= MIN_N_FOR_SOURCE:
                components.append(("Facebook", pos, n))

            if not components:
                return None, components
            weights = [n ** 0.5 for _, _, n in components]
            score = sum(pos * w for (_, pos, _), w in zip(components, weights)) / sum(weights)
            return score, components

        _source_labels = ("Reviews", "XHS", "Reddit", "YouTube", "Instagram", "Facebook")

        brand_scores = {
            b: dict(zip(("score", "components"), _brand_score(b)))
            for b in selected_brands
        }

        ui.subheader("Score and trend", "Composite 0-100 per brand, and the blended % positive by month.", "Sentiment")
        if not selected_brands:
            st.info("No brands selected.")
        else:
            dd_brands = selected_brands
            cols = st.columns(min(len(selected_brands), 5))
            for i, b in enumerate(selected_brands):
                info = brand_scores[b]
                with cols[i % len(cols)]:
                    if info["score"] is None:
                        with st.container(border=True, height=170):
                            st.metric(b, "—", border=False)
                            st.caption(f"Insufficient data — no source has ≥{MIN_N_FOR_SOURCE} qualifying items")
                        continue
                    score = info["score"]
                    status, status_color = (
                        ("Healthy", "green") if score >= 65 else ("Mixed", "orange") if score >= 45 else ("At risk", "red")
                    )
                    breakdown = " · ".join(f"{label} {pos:.0f}% (n={n})" for label, pos, n in info["components"])
                    present = {label for label, _, _ in info["components"]}
                    excluded = [s for s in _source_labels if s not in present]
                    with st.container(border=True, height=170):
                        st.metric(
                            b, f"{score:.0f}", delta=status, delta_color=status_color,
                            delta_arrow="off", border=False,
                        )
                        st.caption(breakdown)
                        if excluded:
                            st.caption(f":gray[excluded: {', '.join(excluded)} (n<{MIN_N_FOR_SOURCE})]")

            # Monthly blended trend (computed once; drawn beside the score plot).

            combined_frames = []
            for b in dd_brands:
                parts = []
                rb = rev_bh[rev_bh["brand"] == b].dropna(subset=["review_date"]).copy()
                if not rb.empty:
                    rb["month"] = rb["review_date"].dt.to_period("M").astype(str)
                    g = rb.groupby("month")["sentiment"].agg(
                        pos=lambda s: s.isin(["positive", "neutral"]).sum(), n="count"
                    ).reset_index()
                    parts.append(g)
                xb_b = xhs_bh[xhs_bh["brand_mentioned"] == b].dropna(subset=["publish_date"]).copy() if not xhs_bh.empty else pd.DataFrame()
                if not xb_b.empty:
                    xb_b = xb_b[xb_b["sentiment"].isin(_VALID_SENTIMENTS)]
                    xb_b["month"] = xb_b["publish_date"].dt.to_period("M").astype(str)
                    g = xb_b.groupby("month")["sentiment"].agg(
                        pos=lambda s: s.isin(["positive", "neutral"]).sum(), n="count"
                    ).reset_index()
                    parts.append(g)
                yb_b = youtube_bh[youtube_bh["brand"] == b].copy() if not youtube_bh.empty else pd.DataFrame()
                if not yb_b.empty:
                    yb_b["published_at"] = pd.to_datetime(yb_b["published_at"], errors="coerce", utc=True).dt.tz_localize(None)
                    yb_b = yb_b.dropna(subset=["published_at"])
                    yb_b = yb_b[yb_b["sentiment"].isin(_VALID_SENTIMENTS)]
                if not yb_b.empty:
                    yb_b["month"] = yb_b["published_at"].dt.to_period("M").astype(str)
                    g = yb_b.groupby("month")["sentiment"].agg(
                        pos=lambda s: s.isin(["positive", "neutral"]).sum(), n="count"
                    ).reset_index()
                    parts.append(g)
                ib_b = instagram_bh[instagram_bh["brand"] == b].copy() if not instagram_bh.empty else pd.DataFrame()
                if not ib_b.empty:
                    ib_b["published_at"] = pd.to_datetime(ib_b["published_at"], errors="coerce", utc=True).dt.tz_localize(None)
                    ib_b = ib_b.dropna(subset=["published_at"])
                    ib_b = ib_b[ib_b["sentiment"].isin(_VALID_SENTIMENTS)]
                if not ib_b.empty:
                    ib_b["month"] = ib_b["published_at"].dt.to_period("M").astype(str)
                    g = ib_b.groupby("month")["sentiment"].agg(
                        pos=lambda s: s.isin(["positive", "neutral"]).sum(), n="count"
                    ).reset_index()
                    parts.append(g)
                if not parts:
                    continue
                monthly = pd.concat(parts, ignore_index=True)

                def _blend(grp):
                    w = grp["n"] ** 0.5
                    return pd.Series({"pct": (grp["pos"] / grp["n"] * 100 * w).sum() / w.sum()})

                blended = monthly.groupby("month").apply(_blend).reset_index()
                blended["Brand"] = b
                combined_frames.append(blended)


            score_col, trend_col = st.columns([2, 3])
            with score_col:
                rank_rows = [{"Brand": b, "Score": info["score"]} for b, info in brand_scores.items() if info["score"] is not None]
                if rank_rows:
                    rank_df = pd.DataFrame(rank_rows).sort_values("Score", ascending=False)
                    fig = go.Figure()
                    for _, r in rank_df.iterrows():
                        col_ = BRAND_COLORS.get(r["Brand"], "#2563eb")
                        fig.add_trace(go.Scatter(x=[0, r["Score"]], y=[r["Brand"]] * 2, mode="lines",
                                                 line=dict(color=col_, width=3), showlegend=False, hoverinfo="skip"))
                        fig.add_trace(go.Scatter(x=[r["Score"]], y=[r["Brand"]], mode="markers+text", text=[f"{r['Score']:.0f}"],
                                                 textposition="middle right", marker=dict(size=14, color=col_),
                                                 showlegend=False, hovertemplate="%{y}: %{x:.0f}<extra></extra>"))
                    fig.update_xaxes(range=[0, 105], title="Composite score (0-100)")
                    fig.update_yaxes(autorange="reversed", title="")
                    fig.update_layout(title="Composite score", height=280, margin=dict(l=10, r=10, t=40, b=10))
                    st.plotly_chart(fig, width="stretch")
            with trend_col:
                if not combined_frames:
                    st.info("No dated Reviews, XHS, YouTube, or Instagram data for the selected brands.")
                else:
                    combined_df = pd.concat(combined_frames, ignore_index=True).sort_values("month")
                    fig = px.line(
                        combined_df, x="month", y="pct", color="Brand", markers=True,
                        color_discrete_map=BRAND_COLORS,
                        labels={"pct": "% positive", "month": ""},
                        title="% positive by month (Reviews + XHS + YouTube + Instagram, √n-weighted)",
                    )
                    fig.update_yaxes(range=[0, 105], ticksuffix="%")
                    fig.update_xaxes(tickangle=-45)
                    fig.update_layout(height=280, margin=dict(l=10, r=10, t=40, b=10),
                                      legend=dict(orientation="h", y=-0.35, title=""))
                    st.plotly_chart(fig, width="stretch")

        st.divider()


        ui.subheader("Brand deep-dive", "One brand at a time: what makes up its score, and why customers hesitate.", "Detail")
        if not selected_brands:
            st.info("No brands selected.")
        else:
            _prune_state("brand_health_focus_brand", selected_brands)
            focus_brand = st.segmented_control(
                "Focus brand", selected_brands, default=selected_brands[0], key="brand_health_focus_brand",
            ) or selected_brands[0]
            info = brand_scores.get(focus_brand, {"score": None, "components": []})

            if not info["components"]:
                st.info(f"Not enough data across any source to score {focus_brand}.")
            else:
                comp_map = {label: (pos, n) for label, pos, n in info["components"]}
                left, right = st.columns([2, 3])
                with left:
                    src_rows = [
                        {"Source": s, "pos": comp_map[s][0] if s in comp_map else 0,
                         "label": f"{comp_map[s][0]:.0f}% (n={comp_map[s][1]})" if s in comp_map else f"n/a (<{MIN_N_FOR_SOURCE})"}
                        for s in _source_labels
                    ]
                    fig = px.bar(pd.DataFrame(src_rows), x="pos", y="Source", orientation="h", text="label",
                                 title=f"{focus_brand}: % positive by source (score {info['score']:.0f})")
                    fig.update_traces(marker_color=BRAND_COLORS.get(focus_brand, "#2563eb"), textposition="outside", cliponaxis=False)
                    fig.add_vline(x=info["score"], line_dash="dot", line_color="gray")
                    fig.update_xaxes(range=[0, 125], title="% positive (neutral counted as positive)")
                    fig.update_yaxes(autorange="reversed", title="")
                    fig.update_layout(height=300, margin=dict(l=10, r=10, t=40, b=10))
                    st.plotly_chart(fig, width="stretch")
                    st.caption(f"Dotted line = composite score. Sources with fewer than {MIN_N_FOR_SOURCE} qualifying items are dropped.")

                xb = xhs_bh[xhs_bh["brand_mentioned"] == focus_brand].dropna(subset=["publish_date"]).copy() if not xhs_bh.empty else pd.DataFrame()
                if not xb.empty:
                    xb = xb[xb["sentiment"].isin(_VALID_SENTIMENTS)]

                def _flagged_comments(df, text_col="text_display"):
                    sub = df[df["brand"] == focus_brand] if not df.empty else pd.DataFrame()
                    if sub.empty:
                        return pd.DataFrame()
                    flagged = sub[pd.to_numeric(sub["is_purchase_barrier_signal"], errors="coerce").fillna(0) == 1]
                    return flagged[[text_col, "sentiment"]].rename(columns={text_col: "Comment (EN)", "sentiment": "Sentiment"})

                xb_neg = xb[xb["sentiment"] == "negative"].copy() if not xb.empty else pd.DataFrame()
                if not xb_neg.empty:
                    xb_neg["Themes"] = xb_neg["themes_list"].apply(lambda lst: ", ".join(lst) if isinstance(lst, list) else "")
                    xb_neg = xb_neg[["content_en", "Themes"]].rename(columns={"content_en": "Post (EN)"})
                hesitate = {
                    "Reddit": _flagged_comments(reddit_bh),
                    "XHS (negative posts)": xb_neg,
                    "YouTube": _flagged_comments(youtube_bh),
                    "Instagram": _flagged_comments(instagram_bh),
                    "Facebook": _flagged_comments(facebook_bh),
                }
                with right:
                    st.markdown("**Why customers hesitate** — comments flagged as a purchase-barrier signal")
                    h_tabs = st.tabs([f"{k} ({len(v)})" for k, v in hesitate.items()])
                    for h_tab, (k, v) in zip(h_tabs, hesitate.items()):
                        with h_tab:
                            if v.empty:
                                st.info(f"None found for {focus_brand} (or {k.split(' ')[0]} excluded for this brand).")
                            else:
                                st.dataframe(v, width="stretch", hide_index=True, height=260)



# ---- Price Intelligence -----------------------------------------------------
if tab_price.open:
    with tab_price:
        ui.subheader("Price distribution by brand", "Compliant listings only, SGD.", "Pricing")
        st.caption(_site_caption(products_f, count_label="products", one_line=True))
        priced_f = products_f[products_f["selling_price"].notna()]
        if not priced_f.empty:
            _med = priced_f.groupby("brand")["selling_price"].median().sort_values()
            ui.insight(
                f"Median listing price runs from <b>{_currency_sym}{_med.iloc[0]:,.0f}</b> ({_med.index[0]}) "
                f"to <b>{_currency_sym}{_med.iloc[-1]:,.0f}</b> ({_med.index[-1]}) across {len(priced_f)} priced listings."
            )

        _brands_with_subs = [b for b in selected_brands if b in _SUBBRAND_RULES]

        if _brands_with_subs:
            priced_f = priced_f.copy()
            priced_f["_sub"] = priced_f.apply(
                lambda r: _subbrand(r["brand"], r["name_en"]) if r["brand"] in _SUBBRAND_RULES else None,
                axis=1,
            )

            st.markdown("**Sub-brand breakdown**")
            _prune_state("brand_health_subbrand_choice", _brands_with_subs)
            sub_brand_choice = st.multiselect(
                "Break down these brands by sub-brand",
                _brands_with_subs,
                default=[],
                key="brand_health_subbrand_choice",
                label_visibility="collapsed",
                help="Selected brands split into their sub-brand product lines on the chart below "
                     "(e.g. Acuvue → Moist / Oneday / Define / Max).",
            )

            # Build plot dataframe: one row-set per brand, split into sub-brand
            # series only for brands the user opted into via the multiselect.
            _parts = []
            _plot_colors = dict(BRAND_COLORS)
            for _b in sorted(priced_f["brand"].unique()):
                _rows_b = priced_f[priced_f["brand"] == _b].copy()
                if _b in sub_brand_choice:
                    for _sub in _SUBBRAND_LISTS[_b] + ["Other"]:
                        _s = _rows_b[_rows_b["_sub"] == _sub].copy()
                        if _s.empty:
                            continue
                        _label = f"{_b} – {_sub}"
                        _s["_plot_brand"] = _label
                        _plot_colors[_label] = _subbrand_color(_b, _sub)
                        _parts.append(_s)
                else:
                    _rows_b["_plot_brand"] = _b
                    _parts.append(_rows_b)

            priced_f = pd.concat(_parts, ignore_index=True) if _parts else priced_f.assign(_plot_brand=priced_f["brand"])
            _plot_brand_col = "_plot_brand"
        else:
            sub_brand_choice = []
            priced_f = priced_f.copy()
            priced_f["_plot_brand"] = priced_f["brand"]
            _plot_brand_col = "_plot_brand"
            _plot_colors = BRAND_COLORS

        if priced_f.empty:
            st.info("No priced products in current filter.")
        else:
            p95 = priced_f.groupby("brand")["selling_price"].transform(
                lambda s: s.quantile(0.95)
            )
            trimmed = priced_f[priced_f["selling_price"] <= p95]
            excluded_counts = (
                priced_f[priced_f["selling_price"] > p95]
                .groupby("brand")["product_code"].count()
            )

            _sub_order = [
                f"{_b} – {_s}" for _b in sub_brand_choice for _s in _SUBBRAND_LISTS[_b] + ["Other"]
            ]
            _other_brands = [
                b for b in sorted(trimmed[_plot_brand_col].unique())
                if not any(b.startswith(f"{_sb} – ") for _sb in sub_brand_choice)
            ]
            _x_order = _sub_order + _other_brands

            fig = px.box(
                trimmed,
                x=_plot_brand_col,
                y="selling_price",
                color=_plot_brand_col,
                color_discrete_map=_plot_colors,
                points="outliers",
                category_orders={_plot_brand_col: _x_order},
                labels={"selling_price": f"Selling price ({_currency_lbl})", _plot_brand_col: "Brand"},
                title="Price distribution by brand (capped at 95th percentile per brand)",
            )
            fig.update_layout(showlegend=bool(sub_brand_choice))

            for plot_label in trimmed[_plot_brand_col].unique():
                raw_brand = plot_label
                for _sb in sub_brand_choice:
                    if plot_label.startswith(f"{_sb} – "):
                        raw_brand = _sb
                        break
                n = excluded_counts.get(raw_brand, 0)
                if n > 0:
                    fig.add_annotation(
                        x=plot_label,
                        y=trimmed["selling_price"].max() * 1.05,
                        text=f"+{n} SKUs<br>above p95<br>(not shown)",
                        showarrow=False,
                        font=dict(size=10, color="dimgray"),
                    )

            st.plotly_chart(fig, width='stretch')
            st.caption(
                "Each brand is capped at its own 95th percentile so specialty/multifocal "
                "SKUs don't dominate the scale. Excluded counts are labeled, not hidden."
            )

            ui.subheader("Discounting behaviour by store")
            store_disc = (
                priced_f.groupby(["store_name", "brand"])
                .agg(avg_price=("selling_price", "mean"), avg_discount=("discount_pct", "mean"), n=("product_code", "count"))
                .reset_index()
                .sort_values("avg_discount", ascending=False)
            )
            st.dataframe(
                store_disc.rename(
                    columns={
                        "store_name": "Store",
                        "brand": "Brand",
                        "avg_price": f"Avg. price ({_currency_lbl})",
                        "avg_discount": "Avg. discount %",
                        "n": "Products",
                    }
                ).round(1),
                width='stretch',
                hide_index=True,
                height=400,
            )
            st.caption(
                "Sorted by deepest average discount. Stores discounting heavily "
                "may be the ones drawing price-sensitive customers away from "
                "full-price listings."
            )

# ---- Reviews & Sentiment ----------------------------------------------------
if tab_reviews_sentiment.open:
    with tab_reviews_sentiment:
        sub_review_pane, sub_sentiment_pane, sub_new_wearer_pane = st.tabs(
            ["Review Intelligence", "Sentiment Intelligence", "New Wearers"],
            on_change="rerun", key="reviews_sentiment_tabs",
        )
        if sub_review_pane.open:
            with sub_review_pane:
                ui.subheader("Review volume & rating trend")
                st.caption(_site_caption(reviews_f, "review_date", "reviews"))

                _ri_dated = reviews_f.dropna(subset=["review_date"])
                _ri_years = sorted(_ri_dated["review_date"].dt.year.unique().tolist())

                with st.popover("📅 Date filters", width='stretch'):
                    fcol1, fcol2, fcol3 = st.columns(3)
                    with fcol1:
                        _prune_state("ri_year", _ri_years)
                        sel_years = st.multiselect("Year", _ri_years, default=_ri_years, key="ri_year")
                    with fcol2:
                        sel_quarters = st.multiselect(
                            "Quarter", [1, 2, 3, 4], default=[1, 2, 3, 4], key="ri_quarter",
                            format_func=lambda q: f"Q{q}",
                        )
                    with fcol3:
                        sel_months = st.multiselect(
                            "Month", list(range(1, 13)), default=list(range(1, 13)), key="ri_month",
                            format_func=lambda m: calendar.month_abbr[m],
                        )

                if not (sel_years and sel_quarters and sel_months):
                    reviews_tab_f = reviews_f.iloc[0:0]
                else:
                    reviews_tab_f = reviews_f[
                        reviews_f["review_date"].dt.year.isin(sel_years)
                        & reviews_f["review_date"].dt.quarter.isin(sel_quarters)
                        & reviews_f["review_date"].dt.month.isin(sel_months)
                    ]

                if reviews_tab_f.empty:
                    st.info("No reviews in current filter.")
                else:
                    rv = reviews_tab_f.dropna(subset=["review_date"]).copy()
                    rv["month"] = rv["review_date"].dt.to_period("M").astype(str)
                    monthly = (
                        rv.groupby(["month", "brand"])
                        .agg(reviews=("id", "count"), avg_rating=("rating", "mean"))
                        .reset_index()
                    )

                    c1, c2 = st.columns(2)
                    with c1:
                        fig = px.bar(
                            monthly,
                            x="month",
                            y="reviews",
                            color="brand",
                            color_discrete_map=BRAND_COLORS,
                            title="Review volume by month",
                            labels={"reviews": "Reviews", "month": "Month"},
                        )
                        st.plotly_chart(fig, width='stretch')
                    with c2:
                        fig = px.line(
                            monthly,
                            x="month",
                            y="avg_rating",
                            color="brand",
                            color_discrete_map=BRAND_COLORS,
                            markers=True,
                            title="Average rating by month",
                            labels={"avg_rating": "Avg. rating", "month": "Month"},
                        )
                        fig.update_yaxes(range=[0, 5])
                        st.plotly_chart(fig, width='stretch')

                    ui.subheader("Rating distribution")
                    fig = px.histogram(
                        reviews_tab_f,
                        x="rating",
                        color="brand",
                        color_discrete_map=BRAND_COLORS,
                        barmode="group",
                        nbins=5,
                    )
                    st.plotly_chart(fig, width='stretch')

                    ui.subheader("Lowest-rated reviews (translated)")
                    low = (
                        reviews_tab_f[reviews_tab_f["rating"] <= 2]
                        .sort_values("rating")
                        .loc[:, ["brand", "store_name", "review_date", "rating", "review_text_en"]]
                    )
                    st.dataframe(
                        low.rename(
                            columns={
                                "brand": "Brand",
                                "store_name": "Store",
                                "review_date": "Date",
                                "rating": "Rating",
                                "review_text_en": "Review (EN)",
                            }
                        ),
                        width='stretch',
                        hide_index=True,
                        height=300,
                    )

        if sub_sentiment_pane.open:
            with sub_sentiment_pane:
                ui.subheader("Consumer Sentiment Intelligence")
                st.caption(_site_caption(reviews_f, "review_date", "reviews"))
                st.caption("Sentiment is rule-based from rating: 4–5 stars = positive, 3 = neutral, 1–2 = negative.")

                if reviews_f.empty:
                    st.info("No reviews in current filter.")
                else:
                    sv = reviews_f.dropna(subset=["review_date", "rating"]).copy()
                    sv = sv[sv["rating"] > 0]
                    sv["sentiment"] = sv["rating"].apply(
                        lambda r: "positive" if r >= 4 else ("neutral" if r == 3 else "negative")
                    )
                    sv["month"] = sv["review_date"].dt.to_period("M").astype(str)

                    _si_years = sorted(sv["review_date"].dt.year.unique().tolist())
                    with st.popover("📅 Date filters", width='stretch'):
                        sfcol1, sfcol2, sfcol3 = st.columns(3)
                        with sfcol1:
                            _prune_state("si_year", _si_years)
                            si_sel_years = st.multiselect("Year", _si_years, default=_si_years, key="si_year")
                        with sfcol2:
                            si_sel_quarters = st.multiselect(
                                "Quarter", [1, 2, 3, 4], default=[1, 2, 3, 4], key="si_quarter",
                                format_func=lambda q: f"Q{q}",
                            )
                        with sfcol3:
                            si_sel_months = st.multiselect(
                                "Month", list(range(1, 13)), default=list(range(1, 13)), key="si_month",
                                format_func=lambda m: calendar.month_abbr[m],
                            )

                    if not (si_sel_years and si_sel_quarters and si_sel_months):
                        sv = sv.iloc[0:0]
                    else:
                        sv = sv[
                            sv["review_date"].dt.year.isin(si_sel_years)
                            & sv["review_date"].dt.quarter.isin(si_sel_quarters)
                            & sv["review_date"].dt.month.isin(si_sel_months)
                        ]

                    if sv.empty:
                        st.info("No reviews in current filter.")
                    else:
                        view = st.segmented_control(
                            "View",
                            ["overview", "deepdive", "subbrands"],
                            format_func={
                                "overview": ":material/bar_chart: All brands overview",
                                "deepdive": ":material/search: Brand deep-dive",
                                "subbrands": ":material/label: Sub-brands",
                            }.get,
                            default="overview",
                            key="si_view",
                            label_visibility="collapsed",
                        ) or "overview"

                        if view == "overview":
                            min_d = sv["review_date"].min().strftime("%b %Y").upper()
                            max_d = sv["review_date"].max().strftime("%b %Y").upper()
                            sites_label = " · ".join(
                                sorted(_SITE_DISPLAY_NAMES.get(s, s) for s in sv["site"].unique())
                            ) if "site" in sv.columns else "All sites"
                            st.caption(
                                f"{sites_label} · {min_d} – {max_d} · "
                                f"{len(sv):,} reviews across {sv['brand'].nunique()} brands"
                            )

                            grid = st.columns(2)
                            for i, brand in enumerate(sorted(sv["brand"].unique())):
                                bv = sv[sv["brand"] == brand]
                                total = len(bv)
                                pos_pct = (bv["sentiment"] == "positive").sum() / total * 100
                                neg_pct = (bv["sentiment"] == "negative").sum() / total * 100
                                # % 5-star minus % 1-2-star — a rating-based proxy, not a survey NPS
                                rating_score = round(
                                    (bv["rating"] == 5).sum() / total * 100
                                    - (bv["rating"] <= 2).sum() / total * 100
                                )

                                cutoff = bv["review_date"].max() - pd.DateOffset(months=3)
                                prior_cutoff = cutoff - pd.DateOffset(months=3)
                                recent_pos = (bv[bv["review_date"] >= cutoff]["sentiment"] == "positive").mean()
                                prior_pos = (
                                    bv[
                                        (bv["review_date"] >= prior_cutoff)
                                        & (bv["review_date"] < cutoff)
                                    ]["sentiment"]
                                    == "positive"
                                ).mean()
                                delta = (recent_pos - prior_pos) * 100 if pd.notna(recent_pos) and pd.notna(prior_pos) else 0
                                trend_color = "green" if delta > 2 else ("red" if delta < -2 else "gray")

                                with grid[i % 2]:
                                    with st.container(border=True):
                                        st.markdown(f"**{brand.upper()}** · {total:,} reviews")
                                        m_pos, m_neg = st.columns(2)
                                        m_pos.metric(
                                            "Positive", f"{pos_pct:.0f}%",
                                            delta=f"{delta:+.1f} pts vs prior 3 mo", delta_color=trend_color,
                                            border=False,
                                        )
                                        m_neg.metric("Negative", f"{neg_pct:.0f}%", border=False)
                                        st.progress(min(pos_pct / 100, 1.0))
                                        st.caption(f"Rating score {rating_score}")

                        elif view == "deepdive":
                            brands_avail = sorted(sv["brand"].unique())
                            if st.session_state.get("si_brand") not in brands_avail:
                                st.session_state.pop("si_brand", None)
                            sel_brand = st.segmented_control(
                                "Brand",
                                brands_avail,
                                default=brands_avail[0],
                                key="si_brand",
                                label_visibility="collapsed",
                            ) or brands_avail[0]

                            bv = sv[sv["brand"] == sel_brand]
                            total = len(bv)
                            pos_pct = (bv["sentiment"] == "positive").sum() / total * 100
                            neg_pct = (bv["sentiment"] == "negative").sum() / total * 100
                            rating_score = round(
                                (bv["rating"] == 5).sum() / total * 100
                                - (bv["rating"] <= 2).sum() / total * 100
                            )

                            m1, m2, m3, m4 = st.columns(4)
                            m1.metric("Total Reviews", f"{total:,}")
                            m2.metric("Avg Positive", f"{pos_pct:.1f}%")
                            m3.metric("Avg Negative", f"{neg_pct:.1f}%")
                            m4.metric(
                                "Rating score", rating_score,
                                help="% of reviews rated 5 stars minus % rated 1–2 stars. A rating-based "
                                     "proxy for advocacy — not a survey-based Net Promoter Score.",
                            )

                            monthly_sent = (
                                bv.groupby(["month", "sentiment"])
                                .size()
                                .reset_index(name="count")
                            )
                            monthly_total = bv.groupby("month").size().reset_index(name="total")
                            monthly_sent = monthly_sent.merge(monthly_total, on="month")
                            monthly_sent["pct"] = monthly_sent["count"] / monthly_sent["total"] * 100

                            SENT_COLORS = {"positive": "#16a34a", "neutral": "#94a3b8", "negative": "#dc2626"}

                            chart_type = st.segmented_control(
                                "Chart",
                                ["line", "bar"],
                                format_func={"line": ":material/show_chart: Line", "bar": ":material/bar_chart: Bar"}.get,
                                default="line",
                                key="si_chart_type",
                                label_visibility="collapsed",
                            ) or "line"
                            if chart_type == "line":
                                fig = px.line(
                                    monthly_sent,
                                    x="month", y="pct", color="sentiment",
                                    color_discrete_map=SENT_COLORS,
                                    markers=True,
                                    title=f"{sel_brand} — Monthly Sentiment Breakdown",
                                    labels={"pct": "% of reviews", "month": "", "sentiment": "Sentiment"},
                                )
                            else:
                                fig = px.bar(
                                    monthly_sent,
                                    x="month", y="pct", color="sentiment",
                                    color_discrete_map=SENT_COLORS,
                                    title=f"{sel_brand} — Monthly Sentiment Breakdown",
                                    labels={"pct": "% of reviews", "month": "", "sentiment": "Sentiment"},
                                )
                                fig.update_layout(barmode="stack")

                            fig.update_yaxes(range=[0, 105], ticksuffix="%")
                            fig.update_xaxes(tickangle=-45)
                            st.plotly_chart(fig, width='stretch')

                            ui.subheader("Critical reviews (rating ≤ 2)")
                            critical = (
                                bv[bv["rating"] <= 2]
                                .sort_values("review_date", ascending=False)
                                [["store_name", "review_date", "rating", "review_text_en"]]
                            )
                            if critical.empty:
                                st.success("No critical reviews for this brand in the current filter.")
                            else:
                                st.dataframe(
                                    critical.rename(columns={
                                        "store_name": "Store",
                                        "review_date": "Date",
                                        "rating": "Rating",
                                        "review_text_en": "Review (EN)",
                                    }),
                                    width='stretch',
                                    hide_index=True,
                                    height=300,
                                )

                        elif view == "subbrands":
                            _sub_brand_options = [b for b in selected_brands if b in _SUBBRAND_RULES]
                            if not _sub_brand_options:
                                st.info("None of the selected brands have a sub-brand breakdown defined.")
                            else:
                                sub_view_brand = st.selectbox(
                                    "Brand", _sub_brand_options, label_visibility="visible",
                                    key="sub_brand_view_pick",
                                )
                                _subs_for_brand = _SUBBRAND_LISTS[sub_view_brand] + ["Other"]

                                acv_sv = sv[sv["brand"] == sub_view_brand].copy()
                                if acv_sv.empty:
                                    st.info(f"No {sub_view_brand} reviews in current filter.")
                                else:
                                    # Join with products to get product name for sub-brand classification
                                    if "product_code" in acv_sv.columns and "product_code" in products_f.columns:
                                        _prod_names = (
                                            products_f[products_f["brand"] == sub_view_brand][["product_code", "name_en"]]
                                            .drop_duplicates("product_code")
                                        )
                                        acv_sv = acv_sv.merge(_prod_names, on="product_code", how="left")
                                        acv_sv["sub_brand"] = acv_sv["name_en"].apply(lambda n: _subbrand(sub_view_brand, n))
                                    else:
                                        acv_sv["sub_brand"] = "Unknown"

                                    # --- Overview cards for each sub-brand ---
                                    st.caption(f"{sub_view_brand} — {len(acv_sv):,} reviews broken down by sub-brand")
                                    grid_sub = st.columns(len(_subs_for_brand))
                                    for i, sub in enumerate(_subs_for_brand):
                                        bv = acv_sv[acv_sv["sub_brand"] == sub]
                                        if bv.empty:
                                            with grid_sub[i]:
                                                st.info(f"{sub}: no reviews")
                                            continue
                                        total = len(bv)
                                        pos_pct = (bv["sentiment"] == "positive").sum() / total * 100
                                        neg_pct = (bv["sentiment"] == "negative").sum() / total * 100
                                        rating_score = round(
                                            (bv["rating"] == 5).sum() / total * 100
                                            - (bv["rating"] <= 2).sum() / total * 100
                                        )
                                        bc = _subbrand_color(sub_view_brand, sub)
                                        with grid_sub[i]:
                                            with st.container(border=True):
                                                st.markdown(f"**{sub_view_brand.upper()} – {sub}** · {total:,} reviews")
                                                m_pos, m_neg = st.columns(2)
                                                m_pos.metric("Positive", f"{pos_pct:.0f}%", border=False)
                                                m_neg.metric("Negative", f"{neg_pct:.0f}%", border=False)
                                                st.progress(min(pos_pct / 100, 1.0))
                                                st.caption(f"Rating score {rating_score}")

                                    # --- Monthly sentiment trend by sub-brand ---
                                    ui.subheader("Monthly sentiment trend by sub-brand")
                                    SENT_COLORS_SUB = {"positive": "#16a34a", "neutral": "#94a3b8", "negative": "#dc2626"}
                                    sub_tabs = st.tabs(
                                        _subs_for_brand, on_change="rerun", key=f"sub_brand_tabs_{sub_view_brand}"
                                    )
                                    for sub_tab, sub in zip(sub_tabs, _subs_for_brand):
                                        if sub_tab.open:
                                            with sub_tab:
                                                bv = acv_sv[acv_sv["sub_brand"] == sub]
                                                if bv.empty:
                                                    st.info(f"No reviews for {sub_view_brand} – {sub}.")
                                                    continue
                                                ms = bv.groupby(["month", "sentiment"]).size().reset_index(name="count")
                                                mt = bv.groupby("month").size().reset_index(name="total")
                                                ms = ms.merge(mt, on="month")
                                                ms["pct"] = ms["count"] / ms["total"] * 100
                                                fig = px.bar(
                                                    ms, x="month", y="pct", color="sentiment",
                                                    color_discrete_map=SENT_COLORS_SUB,
                                                    title=f"{sub_view_brand} – {sub} · Monthly Sentiment",
                                                    labels={"pct": "% of reviews", "month": "", "sentiment": "Sentiment"},
                                                )
                                                fig.update_layout(barmode="stack")
                                                fig.update_yaxes(range=[0, 105], ticksuffix="%")
                                                fig.update_xaxes(tickangle=-45)
                                                st.plotly_chart(fig, width='stretch')

                                                st.markdown("**Critical reviews (rating ≤ 2)**")
                                                crit = (
                                                    bv[bv["rating"] <= 2]
                                                    .sort_values("review_date", ascending=False)
                                                    [["store_name", "review_date", "rating", "review_text_en"]]
                                                )
                                                if crit.empty:
                                                    st.success(f"No critical reviews for {sub_view_brand} – {sub}.")
                                                else:
                                                    st.dataframe(
                                                        crit.rename(columns={
                                                            "store_name": "Store", "review_date": "Date",
                                                            "rating": "Rating", "review_text_en": "Review (EN)",
                                                        }),
                                                        width='stretch', hide_index=True, height=280,
                                                    )

        if sub_new_wearer_pane.open:
            with sub_new_wearer_pane:
                ui.subheader("New Wearers — First-Time Buyers")
                st.caption(_site_caption(reviews_f, "review_date", "reviews"))
                st.caption(
                    "Detected from review text where the reviewer explicitly says this is "
                    "their first time buying/trying/using this brand or lens (e.g. “first "
                    "time buying”, “my first purchase”, “first time trying this "
                    "brand”). Reviews where a long-time wearer says an issue happened "
                    "“for the first time” are excluded. Rule-based text matching, not "
                    "guaranteed complete or exhaustive."
                )

                _nw_dated = reviews_f.dropna(subset=["review_date"])
                _nw_years = sorted(_nw_dated["review_date"].dt.year.unique().tolist())

                with st.popover("\U0001F4C5 Date filters", width='stretch'):
                    nwcol1, nwcol2, nwcol3 = st.columns(3)
                    with nwcol1:
                        _prune_state("nw_year", _nw_years)
                        nw_sel_years = st.multiselect("Year", _nw_years, default=_nw_years, key="nw_year")
                    with nwcol2:
                        nw_sel_quarters = st.multiselect(
                            "Quarter", [1, 2, 3, 4], default=[1, 2, 3, 4], key="nw_quarter",
                            format_func=lambda q: f"Q{q}",
                        )
                    with nwcol3:
                        nw_sel_months = st.multiselect(
                            "Month", list(range(1, 13)), default=list(range(1, 13)), key="nw_month",
                            format_func=lambda m: calendar.month_abbr[m],
                        )

                if not (nw_sel_years and nw_sel_quarters and nw_sel_months):
                    nw_f = reviews_f.iloc[0:0]
                else:
                    nw_f = reviews_f[
                        reviews_f["review_date"].dt.year.isin(nw_sel_years)
                        & reviews_f["review_date"].dt.quarter.isin(nw_sel_quarters)
                        & reviews_f["review_date"].dt.month.isin(nw_sel_months)
                    ]

                if nw_f.empty:
                    st.info("No reviews in current filter.")
                else:
                    nw = nw_f.dropna(subset=["review_date", "rating"]).copy()
                    nw = nw[nw["rating"] > 0]
                    nw["is_new_wearer"] = nw["review_text_en"].apply(_is_new_wearer_review)
                    new_wearers = nw[nw["is_new_wearer"]].copy()

                    if new_wearers.empty:
                        st.info("No first-time-buyer reviews detected in current filter.")
                    else:
                        new_wearers["sentiment"] = new_wearers["rating"].apply(
                            lambda r: "positive" if r >= 4 else ("neutral" if r == 3 else "negative")
                        )
                        total_nw = len(new_wearers)
                        pos_pct = (new_wearers["sentiment"] == "positive").sum() / total_nw * 100
                        neu_pct = (new_wearers["sentiment"] == "neutral").sum() / total_nw * 100
                        neg_pct = (new_wearers["sentiment"] == "negative").sum() / total_nw * 100

                        m1, m2, m3, m4 = st.columns(4)
                        m1.metric("First-time-buyer reviews", f"{total_nw:,}", f"{total_nw / len(nw) * 100:.1f}% of reviews")
                        m2.metric("Avg rating (new wearers)", f"{new_wearers['rating'].mean():.2f}", f"vs {nw['rating'].mean():.2f} overall")
                        m3.metric("% Positive", f"{pos_pct:.0f}%")
                        m4.metric("% Negative", f"{neg_pct:.0f}%")

                        c1, c2 = st.columns(2)
                        with c1:
                            sent_counts = (
                                new_wearers["sentiment"]
                                .value_counts()
                                .reindex(["positive", "neutral", "negative"])
                                .fillna(0)
                                .reset_index()
                            )
                            sent_counts.columns = ["sentiment", "count"]
                            fig = px.bar(
                                sent_counts,
                                x="sentiment",
                                y="count",
                                color="sentiment",
                                color_discrete_map={"positive": "#16a34a", "neutral": "#94a3b8", "negative": "#dc2626"},
                                title="New-wearer sentiment breakdown",
                            )
                            fig.update_layout(showlegend=False)
                            st.plotly_chart(fig, width='stretch')
                        with c2:
                            by_brand = new_wearers.groupby("brand").size().reset_index(name="count").sort_values("count", ascending=False)
                            fig = px.bar(
                                by_brand,
                                x="brand",
                                y="count",
                                color="brand",
                                color_discrete_map=BRAND_COLORS,
                                title="First-time-buyer reviews by brand",
                            )
                            fig.update_layout(showlegend=False)
                            st.plotly_chart(fig, width='stretch')

                        ui.subheader("Monthly first-time-buyer sentiment trend")
                        nw_monthly = new_wearers.copy()
                        nw_monthly["month"] = nw_monthly["review_date"].dt.to_period("M").astype(str)
                        monthly_sent = nw_monthly.groupby(["month", "sentiment"]).size().reset_index(name="count")
                        monthly_total = nw_monthly.groupby("month").size().reset_index(name="total")
                        monthly_sent = monthly_sent.merge(monthly_total, on="month")
                        monthly_sent["pct"] = monthly_sent["count"] / monthly_sent["total"] * 100
                        fig = px.bar(
                            monthly_sent,
                            x="month", y="pct", color="sentiment",
                            color_discrete_map={"positive": "#16a34a", "neutral": "#94a3b8", "negative": "#dc2626"},
                            title="Monthly sentiment mix among first-time buyers",
                            labels={"pct": "% of reviews", "month": "", "sentiment": "Sentiment"},
                        )
                        fig.update_layout(barmode="stack")
                        fig.update_yaxes(range=[0, 105], ticksuffix="%")
                        fig.update_xaxes(tickangle=-45)
                        st.plotly_chart(fig, width='stretch')

                        ui.subheader("First-time-buyer reviews")
                        display_cols = new_wearers.sort_values("review_date", ascending=False)[
                            ["brand", "store_name", "review_date", "rating", "sentiment", "review_text_en"]
                        ]
                        st.dataframe(
                            display_cols.rename(columns={
                                "brand": "Brand",
                                "store_name": "Store",
                                "review_date": "Date",
                                "rating": "Rating",
                                "sentiment": "Sentiment",
                                "review_text_en": "Review (EN)",
                            }),
                            width='stretch',
                            hide_index=True,
                            height=400,
                        )

# ---- Social Signals -----------------------------------------------------------
if tab_social_signals.open:
    with tab_social_signals:
        ui.insight(
            f"<b>{len(_reddit_on_topic_all) + len(_youtube_on_topic_all) + len(_instagram_on_topic_all) + len(_facebook_on_topic_all):,}</b> "
            f"on-topic social comments plus <b>{len(xhs):,}</b> Xiaohongshu posts. Comments are unsolicited reactions, "
            "not reviews \u2014 each platform tab lists what was excluded as off-topic."
        )
        sub_xhs_pane, sub_reddit_pane, sub_youtube_pane, sub_instagram_pane, sub_facebook_pane, sub_trends_pane = st.tabs(
            ["Customer Feedback (XHS)", "Customer Signals (Reddit)", "Customer Signals (YouTube)",
             "Customer Signals (Instagram)", "Customer Signals (Facebook)", "Search Demand (Google Trends)"],
            on_change="rerun", key="social_signal_tabs",
        )
        if sub_xhs_pane.open:
            with sub_xhs_pane:
                if xhs.empty:
                    st.info("No XHS data loaded.")
                else:
                    xhs_brands = sorted(
                        b for b in xhs["brand_mentioned"].dropna().unique() if b != "other"
                    )
                    xhs_filtered = xhs[xhs["brand_mentioned"].isin(xhs_brands)]

                    all_tab, *brand_tabs = st.tabs(["All Brands"] + xhs_brands, on_change="rerun", key="xhs_brand_tabs")

                    brand_post_counts = xhs_filtered.groupby("brand_mentioned").size()
                    _xhs_min = xhs_filtered["publish_date"].min()
                    _xhs_max = xhs_filtered["publish_date"].max()
                    _xhs_date_range = (
                        f"{_xhs_min.strftime('%b %Y')} – {_xhs_max.strftime('%b %Y')}"
                        if pd.notna(_xhs_min) and pd.notna(_xhs_max) else "date range unknown"
                    )
                    _xhs_summary = (
                        f"Xiaohongshu · {_xhs_date_range} · "
                        f"{len(xhs_filtered):,} posts across {len(xhs_brands)} brands"
                    )

                    if all_tab.open:
                        with all_tab:
                            st.caption(_xhs_summary)

                            c1, c2 = st.columns([1, 2])
                            with c1:
                                vol_by_brand = (
                                    xhs_filtered.groupby(["brand_mentioned", "sentiment"])
                                    .size()
                                    .reset_index(name="count")
                                )
                                fig = px.bar(
                                    vol_by_brand,
                                    x="brand_mentioned",
                                    y="count",
                                    color="sentiment",
                                    barmode="stack",
                                    color_discrete_map={"positive": "#16a34a", "neutral": "#94a3b8", "negative": "#dc2626"},
                                    title="Post volume & sentiment by brand",
                                    labels={"brand_mentioned": "Brand", "count": "Posts"},
                                )
                                st.plotly_chart(fig, width='stretch')
                            with c2:
                                sentiment_pct = (
                                    xhs_filtered.groupby(["brand_mentioned", "sentiment"])
                                    .size()
                                    .reset_index(name="count")
                                )
                                totals = sentiment_pct.groupby("brand_mentioned")["count"].transform("sum")
                                sentiment_pct["pct"] = (sentiment_pct["count"] / totals * 100).round(1)
                                fig = px.bar(
                                    sentiment_pct,
                                    x="brand_mentioned",
                                    y="pct",
                                    color="sentiment",
                                    barmode="stack",
                                    color_discrete_map={"positive": "#16a34a", "neutral": "#94a3b8", "negative": "#dc2626"},
                                    title="Sentiment share by brand (%)",
                                    labels={"brand_mentioned": "Brand", "pct": "%"},
                                )
                                fig.update_layout(yaxis_range=[0, 100])
                                st.plotly_chart(fig, width='stretch')

                            theme_brand = (
                                xhs_filtered.explode("themes_list")
                                .groupby(["brand_mentioned", "themes_list"])
                                .size()
                                .reset_index(name="count")
                            )
                            theme_order = (
                                theme_brand.groupby("themes_list")["count"].sum()
                                .sort_values(ascending=False)
                                .head(15)
                                .index
                            )
                            theme_brand = theme_brand[theme_brand["themes_list"].isin(theme_order)]
                            fig = px.bar(
                                theme_brand,
                                x="count",
                                y="themes_list",
                                color="brand_mentioned",
                                orientation="h",
                                category_orders={"themes_list": list(reversed(list(theme_order)))},
                                title="Top 15 themes across all brands",
                                labels={"themes_list": "Theme", "count": "Mentions", "brand_mentioned": "Brand"},
                            )
                            fig.update_layout(barmode="stack")
                            st.plotly_chart(fig, width='stretch')

                            # ── Insight 1: Sentiment divergence (All Brands) ──────────────────
                            if not xhs_comments.empty:
                                _cmt_branded = xhs_comments.merge(
                                    xhs_filtered[["post_id", "brand_mentioned"]].drop_duplicates(),
                                    on="post_id", how="inner",
                                )
                                _sent_colors = {"positive": "#16a34a", "neutral": "#94a3b8", "negative": "#dc2626"}

                                ui.subheader("Insight — Post vs Comment sentiment divergence")
                                st.caption(
                                    "A large gap between post positivity and comment positivity signals "
                                    "that the audience disagrees with the creator — a key authenticity flag."
                                )

                                _post_pos_pct = (
                                    xhs_filtered.groupby("brand_mentioned")
                                    .apply(lambda g: round((g["sentiment"] == "positive").mean() * 100, 1))
                                    .rename("Post positive %")
                                )
                                _cmt_pos_pct = (
                                    _cmt_branded.groupby("brand_mentioned")
                                    .apply(lambda g: round((g["sentiment"] == "positive").mean() * 100, 1))
                                    .rename("Comment positive %")
                                )
                                _div_df = pd.concat([_post_pos_pct, _cmt_pos_pct], axis=1).reset_index()
                                _div_df["Divergence (pp)"] = (
                                    _div_df["Post positive %"] - _div_df["Comment positive %"]
                                ).round(1)
                                _div_df = _div_df.sort_values("Divergence (pp)", ascending=False)

                                _div_melt = _div_df.melt(
                                    id_vars="brand_mentioned",
                                    value_vars=["Post positive %", "Comment positive %"],
                                    var_name="Source", value_name="Positive %",
                                )

                                c1, c2 = st.columns([2, 1])
                                with c1:
                                    fig = px.bar(
                                        _div_melt, x="brand_mentioned", y="Positive %", color="Source",
                                        barmode="group",
                                        color_discrete_map={"Post positive %": "#2563eb", "Comment positive %": "#f97316"},
                                        title="Positive sentiment: Posts vs Comments (%)",
                                        labels={"brand_mentioned": "Brand"},
                                    )
                                    fig.update_yaxes(range=[0, 100], ticksuffix="%")
                                    st.plotly_chart(fig, width='stretch')
                                with c2:
                                    st.markdown("**Divergence score by brand**")
                                    st.caption("Posts positive % minus Comments positive %. Red = audience more negative than posts suggest.")
                                    for _, row in _div_df.iterrows():
                                        div = row["Divergence (pp)"]
                                        with st.container(border=True):
                                            st.metric(
                                                row["brand_mentioned"], f"{div:+.1f} pp",
                                                delta="High" if div > 15 else ("Moderate" if div > 5 else "Aligned"),
                                                delta_color="red" if div > 15 else ("orange" if div > 5 else "green"),
                                                delta_arrow="off", border=False,
                                                help="Divergence between post and comment positive %",
                                            )

                                # ── Insight 3: Authenticity flags (All Brands) ────────────────
                                ui.subheader("Insight — Authenticity risk flags")
                                st.caption(
                                    "Posts with positive sentiment where ≥50% of comments are negative "
                                    "— possible sponsored content or community disagreement."
                                )

                                _neg_likes_by_post = (
                                    _cmt_branded[_cmt_branded["sentiment"] == "negative"]
                                    .groupby("post_id")["likes"].sum()
                                    .rename("neg_comment_likes")
                                )
                                _cmt_stats = (
                                    _cmt_branded.groupby(["post_id", "brand_mentioned"])
                                    .agg(total_comments=("comment_id", "count"),
                                         negative_pct=("sentiment", lambda x: round((x == "negative").mean() * 100, 1)))
                                    .reset_index()
                                    .merge(_neg_likes_by_post, on="post_id", how="left")
                                )
                                _cmt_stats["neg_comment_likes"] = _cmt_stats["neg_comment_likes"].fillna(0).astype(int)

                                _flagged = (
                                    xhs_filtered[xhs_filtered["sentiment"] == "positive"]
                                    .merge(
                                        _cmt_stats[
                                            (_cmt_stats["total_comments"] >= 2) &
                                            (_cmt_stats["negative_pct"] >= 50)
                                        ],
                                        on=["post_id", "brand_mentioned"],
                                    )
                                    .sort_values("neg_comment_likes", ascending=False)
                                )

                                if _flagged.empty:
                                    st.success("No authenticity risk flags detected across all brands.")
                                else:
                                    st.warning(f"{len(_flagged)} post(s) flagged across all brands.")
                                    st.dataframe(
                                        _flagged[[
                                            "brand_mentioned", "content_en", "likes",
                                            "total_comments", "negative_pct", "neg_comment_likes", "url",
                                        ]].rename(columns={
                                            "brand_mentioned": "Brand",
                                            "content_en": "Post content (EN)",
                                            "likes": "Post likes",
                                            "total_comments": "Comments",
                                            "negative_pct": "Neg comment %",
                                            "neg_comment_likes": "Neg comment likes",
                                            "url": "Link",
                                        }),
                                        column_config={"Link": st.column_config.LinkColumn("Link", display_text="Open ↗")},
                                        width='stretch',
                                        hide_index=True,
                                        height=350,
                                    )

                    _acuvue_subproducts = {
                        "Moist": "moist",
                        "OneDay": r"1-day|1day|one day|oneday",
                        "Define": "define",
                        "Max": "max",
                    }

                    for brand_tab, brand in zip(brand_tabs, xhs_brands):
                        if brand_tab.open:
                            with brand_tab:
                                xhs_b = xhs[xhs["brand_mentioned"] == brand]

                                if brand == "Acuvue":
                                    selected_subs = st.multiselect(
                                        "Sub-product",
                                        list(_acuvue_subproducts.keys()),
                                        placeholder="All sub-products",
                                        label_visibility="collapsed",
                                        key=f"xhs_sub_{brand}",
                                    )
                                    if selected_subs:
                                        combined_kw = "|".join(_acuvue_subproducts[s] for s in selected_subs)
                                        xhs_b = xhs_b[
                                            xhs_b["content_en"].str.contains(combined_kw, case=False, na=False, regex=True)
                                        ]

                                st.caption(f"Xiaohongshu · {_xhs_date_range} · {len(xhs_b):,} posts")

                                c1, c2 = st.columns([1, 2])
                                with c1:
                                    sent_counts = xhs_b["sentiment"].value_counts().reset_index()
                                    sent_counts.columns = ["sentiment", "count"]
                                    fig = px.pie(
                                        sent_counts,
                                        names="sentiment",
                                        values="count",
                                        title=f"Sentiment breakdown ({brand})",
                                        color="sentiment",
                                        color_discrete_map={"positive": "#16a34a", "neutral": "#94a3b8", "negative": "#dc2626"},
                                    )
                                    st.plotly_chart(fig, width='stretch')
                                with c2:
                                    theme_sentiment = (
                                        xhs_b.explode("themes_list")
                                        .groupby(["themes_list", "sentiment"])
                                        .size()
                                        .reset_index(name="count")
                                    )
                                    theme_order = (
                                        theme_sentiment.groupby("themes_list")["count"].sum()
                                        .sort_values()
                                        .index
                                    )
                                    fig = px.bar(
                                        theme_sentiment,
                                        x="count",
                                        y="themes_list",
                                        color="sentiment",
                                        orientation="h",
                                        category_orders={"themes_list": list(theme_order)},
                                        color_discrete_map={
                                            "positive": "#16a34a",
                                            "neutral": "#94a3b8",
                                            "negative": "#dc2626",
                                        },
                                        title="Most discussed themes, by sentiment",
                                        labels={"themes_list": "Theme", "count": "Mentions"},
                                    )
                                    fig.update_layout(barmode="stack")
                                    st.plotly_chart(fig, width='stretch')

                                ui.subheader("Most-engaged posts")
                                top_posts = xhs_b.sort_values("likes", ascending=False).head(10)
                                st.dataframe(
                                    top_posts.loc[:, ["sentiment", "themes", "content_en", "likes", "publish_date"]].rename(
                                        columns={
                                            "sentiment": "Sentiment",
                                            "themes": "Themes",
                                            "content_en": "Content (EN)",
                                            "likes": "Likes",
                                            "publish_date": "Date",
                                        }
                                    ),
                                    width='stretch',
                                    hide_index=True,
                                    height=350,
                                )


                                # \u2500\u2500 Comments section \u2500\u2500\u2500\u2500\u2500\u2500\u2500\u2500\u2500\u2500\u2500\u2500\u2500\u2500\u2500\u2500\u2500\u2500\u2500\u2500\u2500\u2500\u2500\u2500\u2500\u2500\u2500\u2500\u2500\u2500\u2500\u2500\u2500\u2500\u2500\u2500\u2500\u2500\u2500\u2500\u2500\u2500
                                ui.subheader("Comments")
                                _cmt_b = (
                                    xhs_comments[xhs_comments["post_id"].isin(xhs_b["post_id"])]
                                    if not xhs_comments.empty else pd.DataFrame()
                                )
                                if _cmt_b.empty:
                                    st.caption("No comments collected yet for this brand.")
                                else:
                                    st.caption(f"{len(_cmt_b):,} comments collected across {_cmt_b['post_id'].nunique():,} posts")
                                    _sent_colors = {"positive": "#16a34a", "neutral": "#94a3b8", "negative": "#dc2626"}

                                    ca, cb = st.columns(2)
                                    with ca:
                                        _cs = _cmt_b["sentiment"].value_counts().reset_index()
                                        _cs.columns = ["sentiment", "count"]
                                        fig = px.pie(
                                            _cs, names="sentiment", values="count",
                                            title="Comment sentiment",
                                            color="sentiment", color_discrete_map=_sent_colors,
                                        )
                                        st.plotly_chart(fig, width='stretch')
                                    with cb:
                                        _ct = (
                                            _cmt_b.explode("themes_list")
                                            .groupby(["themes_list", "sentiment"])
                                            .size().reset_index(name="count")
                                        )
                                        _ct_order = (
                                            _ct.groupby("themes_list")["count"].sum()
                                            .sort_values().index
                                        )
                                        fig = px.bar(
                                            _ct, x="count", y="themes_list", color="sentiment",
                                            orientation="h",
                                            category_orders={"themes_list": list(_ct_order)},
                                            color_discrete_map=_sent_colors,
                                            title="Comment themes by sentiment",
                                            labels={"themes_list": "Theme", "count": "Comments"},
                                        )
                                        fig.update_layout(barmode="stack")
                                        st.plotly_chart(fig, width='stretch')

                                    # ── Divergence metric (per brand) ────────────────────────
                                    _b_post_pos = round((xhs_b["sentiment"] == "positive").mean() * 100, 1)
                                    _b_cmt_pos  = round((_cmt_b["sentiment"] == "positive").mean() * 100, 1)
                                    _b_div      = round(_b_post_pos - _b_cmt_pos, 1)
                                    _b_icon     = "⚠️ High divergence" if _b_div > 15 else ("△ Moderate" if _b_div > 5 else "✓ Aligned")
                                    d1, d2, d3 = st.columns(3)
                                    d1.metric("Post positive %", f"{_b_post_pos:.1f}%")
                                    d2.metric("Comment positive %", f"{_b_cmt_pos:.1f}%")
                                    d3.metric("Divergence", f"{_b_div:+.1f} pp", help="Post positive % minus comment positive %. Large positive gap = audience more negative than posts suggest.")
                                    _b_flag = st.error if _b_div > 15 else (st.warning if _b_div > 5 else st.success)
                                    _b_flag(_b_icon.replace("⚠️ ", "").replace("△ ", "").replace("✓ ", ""),
                                            icon=":material/warning:" if _b_div > 5 else ":material/check_circle:")

                                    # ── Authenticity flags (per brand) ───────────────────────
                                    _b_neg_likes = (
                                        _cmt_b[_cmt_b["sentiment"] == "negative"]
                                        .groupby("post_id")["likes"].sum()
                                        .rename("neg_comment_likes")
                                    )
                                    _b_cmt_stats = (
                                        _cmt_b.groupby("post_id")
                                        .agg(total_comments=("comment_id", "count"),
                                             negative_pct=("sentiment", lambda x: round((x == "negative").mean() * 100, 1)))
                                        .reset_index()
                                        .merge(_b_neg_likes, on="post_id", how="left")
                                    )
                                    _b_cmt_stats["neg_comment_likes"] = _b_cmt_stats["neg_comment_likes"].fillna(0).astype(int)
                                    _b_flagged = (
                                        xhs_b[xhs_b["sentiment"] == "positive"]
                                        .merge(
                                            _b_cmt_stats[
                                                (_b_cmt_stats["total_comments"] >= 2) &
                                                (_b_cmt_stats["negative_pct"] >= 50)
                                            ],
                                            on="post_id",
                                        )
                                        .sort_values("neg_comment_likes", ascending=False)
                                    )
                                    if not _b_flagged.empty:
                                        st.markdown(f"**⚠️ Authenticity risk flags — {len(_b_flagged)} post(s)**")
                                        st.caption("Positive posts where ≥50% of comments are negative.")
                                        st.dataframe(
                                            _b_flagged[[
                                                "content_en", "likes", "total_comments",
                                                "negative_pct", "neg_comment_likes", "url",
                                            ]].rename(columns={
                                                "content_en": "Post content (EN)",
                                                "likes": "Post likes",
                                                "total_comments": "Comments",
                                                "negative_pct": "Neg comment %",
                                                "neg_comment_likes": "Neg comment likes",
                                                "url": "Link",
                                            }),
                                            column_config={"Link": st.column_config.LinkColumn("Link", display_text="Open ↗")},
                                            width='stretch', hide_index=True, height=250,
                                        )

                                    st.markdown("**Most-liked comments**")
                                    st.dataframe(
                                        _cmt_b.sort_values("likes", ascending=False)
                                        .head(20)
                                        [["author", "content_en", "sentiment", "themes", "likes"]]
                                        .rename(columns={
                                            "author": "Author",
                                            "content_en": "Comment (EN)",
                                            "sentiment": "Sentiment",
                                            "themes": "Themes",
                                            "likes": "Likes",
                                        }),
                                        width='stretch',
                                        hide_index=True,
                                        height=350,
                                    )

                                    st.markdown("**Negative comments**")
                                    _neg_cmt = _cmt_b[_cmt_b["sentiment"] == "negative"].sort_values("likes", ascending=False)
                                    if _neg_cmt.empty:
                                        st.caption("No negative comments found.")
                                    else:
                                        st.dataframe(
                                            _neg_cmt.head(20)
                                            [["author", "content_en", "themes", "likes"]]
                                            .rename(columns={
                                                "author": "Author",
                                                "content_en": "Comment (EN)",
                                                "themes": "Themes",
                                                "likes": "Likes",
                                            }),
                                            width='stretch',
                                            hide_index=True,
                                            height=280,
                                        )

                                ui.subheader("Negative-sentiment posts")
                                neg = xhs_b[xhs_b["sentiment"] == "negative"]
                                if neg.empty:
                                    st.caption("No negative-sentiment posts found in current data.")
                                else:
                                    # One table instead of four Streamlit calls per post, so a
                                    # brand with hundreds of negative posts doesn't flood the page.
                                    neg_show = neg.sort_values("likes", ascending=False).copy()
                                    neg_show["themes_joined"] = neg_show["themes_list"].apply(
                                        lambda lst: ", ".join(lst) if isinstance(lst, list) else ""
                                    )
                                    st.caption(f"{len(neg_show):,} negative posts, most-liked first.")
                                    st.dataframe(
                                        neg_show[["content_en", "themes_joined", "likes", "publish_date"]].rename(
                                            columns={
                                                "content_en": "Post (EN)",
                                                "themes_joined": "Themes",
                                                "likes": "Likes",
                                                "publish_date": "Date",
                                            }
                                        ),
                                        column_config={"Post (EN)": st.column_config.TextColumn(width="large")},
                                        width="stretch",
                                        hide_index=True,
                                        height=420,
                                    )

        if sub_reddit_pane.open:
            with sub_reddit_pane:
                reddit_signals.render()

        if sub_youtube_pane.open:
            with sub_youtube_pane:
                youtube_signals.render()

        if sub_instagram_pane.open:
            with sub_instagram_pane:
                instagram_signals.render()

        if sub_facebook_pane.open:
            with sub_facebook_pane:
                facebook_signals.render()

        if sub_trends_pane.open:
            with sub_trends_pane:
                trends_signals.render()

# ---- Catalog Explorer ----------------------------------------------------------
if tab_catalog.open:
    with tab_catalog:
        sub_stores_pane, sub_explorer_pane = st.tabs(
            ["Store Ranking", "Product Explorer"], on_change="rerun", key="catalog_tabs"
        )
        if sub_stores_pane.open:
            with sub_stores_pane:
                ui.subheader("Store ranking by brand")
                st.caption(_site_caption(products_f, count_label="products"))
                st.caption("Ranked by review-volume-weighted average rating. Stores with fewer than 5 reviews are flagged as low-confidence.")

                rated = products_f[products_f["total_reviews"] > 0].copy()
                if rated.empty:
                    st.info("No rated products in current filter.")
                else:
                    store_rank = (
                        rated.groupby(["store_name", "brand"])
                        .apply(
                            lambda g: pd.Series(
                                {
                                    "products": len(g),
                                    "total_reviews": g["total_reviews"].sum(),
                                    "weighted_rating": (g["avg_rating"] * g["total_reviews"]).sum()
                                    / g["total_reviews"].sum(),
                                }
                            )
                        )
                        .reset_index()
                        .sort_values(["brand", "weighted_rating"], ascending=[True, False])
                    )
                    store_rank["confidence"] = store_rank["total_reviews"].apply(
                        lambda n: "Low (<5 reviews)" if n < 5 else "OK"
                    )

                    for b in selected_brands:
                        st.markdown(f"**{b}**")
                        bsr = store_rank[store_rank["brand"] == b].drop(columns=["brand"])
                        st.dataframe(
                            bsr.rename(
                                columns={
                                    "store_name": "Store",
                                    "products": "Products",
                                    "total_reviews": "Reviews",
                                    "weighted_rating": "Weighted rating",
                                    "confidence": "Confidence",
                                }
                            ).round(2),
                            width='stretch',
                            hide_index=True,
                        )

                    st.divider()
                    ui.subheader("Stores common across brands")
                    st.caption(
                        "Stores carrying 2+ of the currently selected brands, compared by review volume "
                        "per brand — useful for spotting which multi-brand retailers over- or under-index "
                        "on a given brand."
                    )
                    _brands_per_store = store_rank.groupby("store_name")["brand"].nunique()
                    _common_stores = _brands_per_store[_brands_per_store >= 2].index.tolist()
                    if not _common_stores:
                        st.info("No stores carry 2+ of the currently selected brands.")
                    else:
                        common_rank = store_rank[store_rank["store_name"].isin(_common_stores)]
                        _store_order = (
                            common_rank.groupby("store_name")["total_reviews"].sum()
                            .sort_values(ascending=False).index.tolist()
                        )
                        fig_common = px.bar(
                            common_rank,
                            x="total_reviews", y="store_name", color="brand",
                            color_discrete_map=BRAND_COLORS,
                            orientation="h", barmode="group",
                            category_orders={"store_name": _store_order},
                            labels={"total_reviews": "Reviews", "store_name": "Store", "brand": "Brand"},
                        )
                        fig_common.update_layout(
                            height=max(320, 32 * len(_common_stores)),
                            yaxis={"categoryorder": "array", "categoryarray": list(reversed(_store_order))},
                            legend_title_text="Brand",
                        )
                        st.plotly_chart(fig_common, width="stretch")

                        st.dataframe(
                            common_rank.pivot_table(
                                index="store_name", columns="brand", values="total_reviews", fill_value=0
                            )
                            .astype(int)
                            .loc[_store_order]
                            .rename_axis("Store")
                            .reset_index(),
                            width="stretch",
                            hide_index=True,
                        )

        if sub_explorer_pane.open:
            with sub_explorer_pane:
                ui.subheader("Product Explorer")
                st.caption(_site_caption(products_f, count_label="products"))

                _CAT_TABS = ["All"] + sorted(products_f["category"].dropna().unique().tolist())
                cat_tabs = st.tabs(_CAT_TABS, on_change="rerun", key="catalog_category_tabs")

                search = st.text_input("Search brand or product", "", key="catalog_search")
                sort_choice = st.selectbox(
                    "Sort by", ["Rating", "Reviews", "Price: low to high", "Price: high to low"],
                    key="catalog_sort",
                )

                explorer_df = products_f.copy()
                if search:
                    mask = (
                        explorer_df["name_en"].str.contains(search, case=False, na=False)
                        | explorer_df["brand"].str.contains(search, case=False, na=False)
                    )
                    explorer_df = explorer_df[mask]

                sort_map = {
                    "Rating": ("avg_rating", False),
                    "Reviews": ("total_reviews", False),
                    "Price: low to high": ("selling_price", True),
                    "Price: high to low": ("selling_price", False),
                }
                field, asc = sort_map[sort_choice]
                explorer_df = explorer_df.sort_values(field, ascending=asc, na_position="last")
                # discount_pct comes from load_data(), which guards against a missing/zero
                # original_price and a price above the original (0 = no discount) — don't
                # recompute it here or those rows show inf / negative discounts.
                # Unknown original price -> blank, not 0 (0 would claim "no discount").
                explorer_df["discount_pct"] = explorer_df["discount_pct"].where(explorer_df["original_price"] > 0)

                _DISPLAY_COLS = {
                    "name_en": "Product",
                    "brand": "Brand",
                    "category": "Category",
                    "store_name": "Store",
                    "avg_rating": "Rating",
                    "total_reviews": "Reviews",
                    "selling_price": "Price (SGD)",
                    "discount_pct": "Discount %",
                    "url": "Link",
                }

                _COL_CONFIG = {
                    "Link": st.column_config.LinkColumn("Link", display_text="Open ↗"),
                }

                for _tab_widget, _cat_label in zip(cat_tabs, _CAT_TABS):
                    if _tab_widget.open:
                        with _tab_widget:
                            if _cat_label == "All":
                                _view = explorer_df
                            else:
                                _view = explorer_df[explorer_df["category"] == _cat_label]
                            st.dataframe(
                                _view[list(_DISPLAY_COLS.keys())].rename(columns=_DISPLAY_COLS).round(1),
                                column_config=_COL_CONFIG,
                                width='stretch',
                                hide_index=True,
                                height=600,
                            )

# ---- Journey & Barriers -------------------------------------------------------
if tab_journey.open:
    with tab_journey:
        ui.section("Customer journey & barriers", eyebrow="Journey stage view")
        st.markdown(
            '<div class="caveat-box">Journey stage is tagged per <b>source</b>, not per row, and an item '
            'tagged with several stages is counted in each \u2014 stage counts overlap and are not additive. '
            'Grey-market (compliance-flagged) listings are not funnel data; see Market &amp; Channel → Brand protection. App-store reviews are on the App &amp; friction sub-tab.</div>',
            unsafe_allow_html=True,
        )
        jf = jf_all[jf_all["brand"].isin(selected_brands)] if not jf_all.empty else jf_all
        if jf.empty:
            st.info("No journey-stage data for the current brand filter.")
        else:
            _stage_order = [s for s in JOURNEY_STAGES if s in set(jf["journey_stage"])] + sorted(
                s for s in set(jf["journey_stage"]) if s not in JOURNEY_STAGES
            )
            jc1, jc2 = st.columns(2)
            stage_pick = jc1.multiselect("Journey stages", _stage_order, default=_stage_order, key="journey_stage_pick")
            src_pick = jc2.multiselect(
                "Sources", sorted(jf["source"].unique()), default=sorted(jf["source"].unique()), key="journey_src_pick"
            )
            jv = jf[jf["journey_stage"].isin(stage_pick) & jf["source"].isin(src_pick)]

            if jv.empty:
                st.info("Nothing matches the current stage/source selection.")
            else:
                ui.section("Coverage: stage \u00d7 source", "Items available to speak to each funnel stage, by source.", "Funnel")
                cover = (
                    jv.groupby(["journey_stage", "source"]).size().unstack(fill_value=0)
                    .reindex([s for s in _stage_order if s in set(jv["journey_stage"])])
                )
                fig = px.imshow(
                    cover, text_auto=True, aspect="auto", color_continuous_scale="Blues",
                    labels={"x": "Source", "y": "Journey stage", "color": "Items"},
                )
                st.plotly_chart(fig, width="stretch")

                ui.section("Sentiment by stage", eyebrow="Funnel")
                sent = jv[jv["sentiment"].isin(SENTIMENT_COLORS)]
                if sent.empty:
                    st.info("No sentiment-labelled items in this selection.")
                else:
                    sg = sent.groupby(["journey_stage", "sentiment"]).size().reset_index(name="count")
                    fig = px.bar(
                        sg, x="journey_stage", y="count", color="sentiment", barmode="stack",
                        category_orders={"journey_stage": _stage_order},
                        color_discrete_map=SENTIMENT_COLORS,
                        labels={"journey_stage": "Journey stage", "count": "Items"},
                    )
                    st.plotly_chart(fig, width="stretch")

                ui.section("Purchase-barrier signals by stage", "Share of items flagged as a reason not to buy / a friction point.", "Barriers")
                st.caption(
                    "Social comments: LLM-scored flag. Lazada reviews & KiasuParents: derived — negative/mixed text "
                    "commenting on price, comfort, counterfeit or availability. MyACUVUE app: any 1–2★ review. "
                    "Xiaohongshu carries no barrier flag and is excluded."
                )
                bar_src = jv[jv["source"] != "Xiaohongshu"]
                if bar_src.empty:
                    st.info("No barrier-flagged sources in this selection.")
                else:
                    br = (
                        bar_src.groupby(["journey_stage", "brand"])
                        .agg(items=("is_barrier", "size"), barriers=("is_barrier", "sum")).reset_index()
                    )
                    br["barrier_rate"] = (br["barriers"] / br["items"] * 100).round(1)
                    bc1, bc2 = st.columns(2)
                    with bc1:
                        fig = px.bar(
                            br, x="journey_stage", y="barrier_rate", color="brand", barmode="group",
                            category_orders={"journey_stage": _stage_order},
                            color_discrete_map=BRAND_COLORS,
                            labels={"journey_stage": "Journey stage", "barrier_rate": "% flagged as barrier"},
                            title="Barrier rate (% of items, all flagged sources)",
                        )
                        st.plotly_chart(fig, width="stretch")
                    with bc2:
                        st.dataframe(
                            br.rename(columns={"journey_stage": "Stage", "brand": "Brand", "items": "Comments",
                                               "barriers": "Barrier-flagged", "barrier_rate": "Rate %"}),
                            width="stretch", hide_index=True, height=350,
                        )

                    st.markdown("**Barrier-flagged comments**")
                    flagged = bar_src[bar_src["is_barrier"] == 1].drop_duplicates(subset=["source", "text"])
                    if flagged.empty:
                        st.caption("None flagged in this selection.")
                    else:
                        show = flagged[["source", "brand", "journey_stage", "sentiment", "text", "url"]].rename(columns={
                            "source": "Source", "brand": "Brand", "journey_stage": "Stage",
                            "sentiment": "Sentiment", "text": "Comment", "url": "Link"})
                        st.dataframe(
                            show, width="stretch", hide_index=True, height=400,
                            column_config={"Link": st.column_config.LinkColumn("Link", display_text="Open \u2197")},
                        )

if tab_retail.open:
    with tab_retail:
        ui.section(
            "Optical retailers \u2014 Google Maps reviews",
            "Store-level friction at ACUVUE-selling optical chains, ahead of a fitting appointment.",
            "Consideration",
        )
        gm_rev, gm_places = gmaps_signals.load_gmaps()
        if gm_rev.empty:
            st.info("No Google Maps data found (expected Scripts/output/gmaps_data_sg.db \u2192 gmaps_reviews).")
        else:
            st.caption(
                "Retailer reviews, not brand reviews, so the sidebar brand filter does not apply. The 100 newest "
                "reviews per outlet skew positive (avg ~4.8\u2605), so friction rates understate dissatisfaction. "
                "Friction and theme tags are LLM-scored. Contact-lens-only = the strict contact-lens tag AND a "
                "contact-lens keyword; it is a small sample, so read per-chain rates as rough. Raw text is for "
                "internal analysis only \u2014 do not republish."
            )
            gc1, gc2 = st.columns([3, 1])
            gm_chains = gc1.multiselect(
                "Chains", sorted(gm_rev["chain"].unique()), default=sorted(gm_rev["chain"].unique()), key="gmaps_chain_pick"
            )
            gm_cl_only = gc2.toggle("Contact-lens reviews only", value=True, key="gmaps_cl_only")
            gmv = gm_rev[gm_rev["chain"].isin(gm_chains)]
            if gm_cl_only:
                gmv = gmv[gmv["contact_lens"] == 1]
            if gmv.empty:
                st.info("No reviews match this selection.")
            else:
                gm_m = st.columns(4)
                gm_m[0].metric("Reviews", f"{len(gmv):,}")
                gm_m[1].metric("Outlets", f"{gmv['place_id'].nunique():,}")
                gm_m[2].metric("Avg rating", f"{gmv['rating'].mean():.2f}")
                gm_m[3].metric("Friction share", f"{gmv['is_friction'].mean() * 100:.1f}%",
                               help="Reviews where the reviewer describes a negative experience (praise never counts).")

                gg1, gg2 = st.columns(2)
                with gg1:
                    gt = gmaps_signals.theme_counts(gmv)
                    if gt.empty:
                        st.info("No friction themes in this selection.")
                    else:
                        fig = px.bar(gt, x="Friction reviews", y="Theme", orientation="h", title="Friction themes")
                        fig.update_layout(yaxis={"categoryorder": "total ascending"})
                        st.plotly_chart(fig, width="stretch")
                with gg2:
                    ct = gmaps_signals.chain_table(gmv)
                    fig = px.bar(ct, x="Chain", y="Friction %", text="Reviews", title="Friction % by chain (label = # reviews)")
                    st.plotly_chart(fig, width="stretch")
                st.dataframe(ct, width="stretch", hide_index=True)

                st.markdown("**Outlets with the most friction reviews**")
                ot = (
                    gmv.groupby(["chain", "place_name"]).agg(Reviews=("review_id", "size"), Friction=("is_friction", "sum"))
                    .reset_index().sort_values(["Friction", "Reviews"], ascending=False).head(15)
                    .rename(columns={"chain": "Chain", "place_name": "Outlet"})
                )
                st.dataframe(ot[ot["Friction"] > 0], width="stretch", hide_index=True)

                st.markdown("**Friction reviews**")
                gf = gmv[gmv["is_friction"] == 1].sort_values("date", ascending=False)
                if gf.empty:
                    st.caption("None flagged in this selection.")
                else:
                    gshow = gf[["date", "chain", "place_name", "rating", "theme_list", "text", "place_url"]].copy()
                    gshow["theme_list"] = gshow["theme_list"].map(
                        lambda ts: ", ".join(gmaps_signals.THEME_LABELS.get(t, t) for t in ts))
                    st.dataframe(
                        gshow.rename(columns={"date": "Date", "chain": "Chain", "place_name": "Outlet", "rating": "\u2605",
                                              "theme_list": "Themes", "text": "Review", "place_url": "Link"}),
                        width="stretch", hide_index=True, height=400,
                        column_config={"Link": st.column_config.LinkColumn("Link", display_text="Open \u2197")},
                    )

# ---- Data Notes ------------------------------------------------------------
if tab_notes.open:
    with tab_notes:
        ui.subheader("Data coverage & known limitations", "What each source can and cannot tell you.", "Read before quoting")
        st.markdown(
            """
**Products & reviews (Lazada SG + TikTok Shop SG)**
- **Grey-market / compliance listings are excluded** from every product-intelligence
  number (`compliance_flag = 1`, 51 of 143 listings). They appear only in the
  Market & Channel → Brand protection sub-tab.
- **TikTok Shop listings mostly have no rating or review count**, so weighted
  ratings and store rankings effectively reflect Lazada only.
- **Reviews are Lazada only and cover Alcon and Bausch & Lomb only** — there are
  no Acuvue reviews in the review table, so the Reviews & Sentiment tab
  cannot say anything about Acuvue. Review sentiment labels have not been
  populated yet, so sentiment there is rating-derived.
- **Prices**: SGD 0.01 listings are treated as bad scrape data and dropped from
  price charts.
- **Brand spellings** differ across the SG databases (MyACUVUE / ACUVUE / Acuvue,
  Bausch + Lomb / Bausch & Lomb); all are normalised to one set on load.

**Customer feedback (XHS)**
- **Only ~30% of XHS posts have brand_mentioned / sentiment populated**; the
  rest are unclassified and are not counted as brand-attributed.

**Customer signals (Reddit, YouTube, Instagram, Facebook)**
- **Volume is small and uneven across brands.** Facebook has no Alcon page;
  Instagram comments are dominated by MyACUVUE; Reddit threads are mostly
  r/singapore and many are years old.
- **Relevance layers are LLM-scored, not human-reviewed.** A keyword or hashtag
  search can surface posts that aren't about the tagged brand (`brand_relevant`,
  `market_relevant`), and individual comments can drift off-topic
  (`is_lens_relevant`). Both are excluded from scoring but listed in an
  expander on each Social Signals pane, not silently dropped.
- **Comments are unsolicited reactions, not product reviews**, and Facebook/
  Instagram brand-page posts are marketing content, not consumer opinion.

**Journey & Barriers**
- **`journey_stage` is assigned per source, not per row** (e.g. every YouTube
  item is "Awareness/Engagement/Consideration"). An item tagged with three
  stages is counted once in each, so stage totals are not additive. The
  view shows where each source *can* speak to the funnel, not a measured
  per-customer path.
- **`is_purchase_barrier_signal`** exists only on social comments (YouTube,
  Instagram, Facebook, Reddit); XHS, KiasuParents and Lazada reviews carry no
  barrier flag, so barrier rates are social-only.

**Optical retailers (Google Maps)**
- **Retailer reviews, not brand reviews** (Optical 88, Owndays, Better Vision,
  Capitol Optical, Visio Optical, Nanyang Optical), shown in Market & Channel → Retailers
  as Consideration-stage signal. They are not in the journey frame and the brand
  filter does not apply.
- **Only the 100 newest reviews per outlet** were pulled and they skew positive
  (avg ~4.8★), so friction rates understate dissatisfaction. Only ~200 of the
  4,771 reviews are clearly about contact lenses (the default view), so per-chain
  rates are rough. Optical 88 returned 8 outlets and Visio 1 — coverage of
  those chains is partial. Nanyang Optical is included on weak evidence that it
  sells ACUVUE; Watsons Optical has no separate Maps listings.
- Friction, themes and the contact-lens tag are LLM-scored, not human-reviewed.

**Search demand (Google Trends)**
- **A normalized 0-100 interest index, not search volume.** 100 is the peak for the
  terms in one request, so terms are only comparable within a batch; every batch
  carries "contact lens" as an anchor for the relative view.
- Branded Singapore terms are low volume: weekly values are noisy, and terms with
  under 30 non-zero weeks (e.g. Biotrue, Dailies Total30) are not charted.
- Search interest is a directional awareness signal, not registrations or sales.

**Sources not collected**
- **TikTok Commercial Content Library**: EU/EEA/UK ads only, so no Singapore ads
  exist there. Dropped, with no workaround.
- **HardwareZone**: excluded from automated collection (Terms restrict scraping).
- **Meta Ad Library and Watsons Singapore**: assessed, `blocked_pending_review`
  (see Logs/summary.md); no data from either is shown.

**General**
- **Dates** vary by source — Lazada reviews and YouTube go back to 2019-2020; see each tab for its range.
- **Currency**: all prices are in SGD, captured at scrape time.

This page exists so nothing here gets overstated to a client. Update it
as each gap gets closed.
        """
        )
        st.caption(f"Dashboard built from: {os.path.abspath(db_path)} + the social/XHS DBs in the same folder")
