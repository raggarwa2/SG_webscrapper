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
import brand_health
import conversation_content
import charts
import insights
import journey_barriers
import ebi
import brand_protection
import facebook_signals
import facebook_retailers
import gmaps_signals
import instagram_signals
import journey_signals
import market_competitors
import overview_pages
import positioning_pages
import ui
import reddit_signals
import trends_signals
import youtube_signals

import sys
from pathlib import Path
# Add project root (one level up from Dashboard/) to Python path
sys.path.append(str(Path(__file__).parent.parent))


from sg_common import (
    BRAND_COLORS, JOURNEY_STAGES, SENTIMENT_COLORS, SG_DB, XHS_DB,
    normalize_brand, read_table, xhs_attributed,
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

_SITES_DISPLAY = "Lazada · TikTok Shop · Xiaohongshu · Reddit · KiasuParents · YouTube · Instagram · Facebook · App stores · Google Maps · Trends"

DEFAULT_DB_PATH = SG_DB


def _by(df, col: str = "brand") -> dict:
    """{brand: rows} in the dashboard's fixed brand order, for the sample-size strip under a chart."""
    c = df.groupby(col).size()
    return {b: int(c[b]) for b in charts.order_brands(c.index)}


def _plot(fig, note: str = "", height: int = 300, say: str = "", kind: str = "fact", bases=None, noun: str = "items") -> None:
    """Render a plotly figure at a compact default height unless the caller set one,
    with a one-line data footnote (source, date range, n) underneath. `say` is the chart's
    lead sentence (an insight, kind="fact", or an action, kind="dir"); it replaces the in-chart title."""
    if say:
        ui.takeaway(say, kind)
        fig.update_layout(title_text=None)
    if fig.layout.height is None:
        fig.update_layout(height=height, margin=dict(l=10, r=10, t=36 if say else 40, b=10))
    elif say:
        fig.update_layout(margin=dict(l=10, r=10, t=36, b=10))
    st.plotly_chart(fig, width="stretch")
    ui.n_strip(bases, noun, attached=True)
    if note:
        st.caption(note)


def _note(df, source: str, date_col: str = None, noun: str = "items") -> str:
    """'Source · Mon YYYY – Mon YYYY · N noun' footnote for a chart's underlying rows."""
    if df is None or len(df) == 0:
        return ""
    parts = [source]
    if date_col and date_col in df.columns:
        d = pd.to_datetime(df[date_col], errors="coerce", utc=True).dropna()
        if not d.empty:
            lo, hi = d.min().strftime("%b %Y"), d.max().strftime("%b %Y")
            parts.append(lo if lo == hi else f"{lo} – {hi}")
    parts.append(ebi.count(len(df), noun))
    return " · ".join(parts)


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
_xhs_attributed = xhs_attributed(xhs)
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
    pills=[f"{len(selected_brands)} brands", "Singapore"],
)

ui.sample_key()

# Journey frame feeds Brand Health and Barriers. The old headline cards and KPI tiles that sat here were
# removed: each page now opens with its own what-it-shows / why / insight read instead of a shared strip.
jf_all = journey_signals.load_journey_frame()
# One analysed-items basis for every page that counts items per brand and channel (Brand Health, Market & Channel,
# Journey reconciliation): the same frames Brand Health and the Summary build.
_story_frames = insights.build_frames(
    reviews[reviews["market"] == "SG"], xhs,
    {
        "Reddit": (reddit_comments_df, reddit_signals),
        "YouTube": (youtube_comments_df, youtube_signals),
        "Instagram": (instagram_comments_df, instagram_signals),
        "Facebook": (facebook_comments_df, facebook_signals),
    },
)

# ---- Headline strip (same six tiles as the Hong Kong header) ------------------------------------------------------------
# Built from the same pool as Brand Health (brand-attributed, relevant, four-point sentiment), so these numbers match it.
_pool = insights.pool(_story_frames, selected_brands)
_pool_lab = _pool[_pool["sentiment"].isin(insights.VALID)]
_hl = st.columns(6)

_hl[0].metric("Data points analysed", f"{len(_pool):,}",
              help="Brand-attributed, relevant, sentiment-labelled items across all channels for the current brand filter "
                   "(the Brand Health pool). Excludes brand-owned posts, app reviews, Google Maps reviews, listings and Google Trends.")

if len(_pool_lab) >= ebi.MIN_N:
    _pn = _pool_lab["sentiment"].isin(["positive", "neutral"])
    _delta_txt = None
    _dated = _pool_lab.assign(_pn=_pn).dropna(subset=["date"])
    if not _dated.empty:
        _cut = _dated["date"].max() - pd.DateOffset(days=90)
        _recent = _dated[_dated["date"] >= _cut]
        _prior = _dated[(_dated["date"] >= _cut - pd.DateOffset(days=90)) & (_dated["date"] < _cut)]
        if len(_recent) >= ebi.MIN_N and len(_prior) >= ebi.MIN_N:
            _delta_txt = f"{(_recent['_pn'].mean() - _prior['_pn'].mean()) * 100:+.1f}pp vs prev 90d"
    _hl[1].metric("Positive or neutral", f"{_pn.mean() * 100:.0f}%", delta=_delta_txt,
                  help="Positive or neutral share of all labelled items (mixed stays in the base). The change compares the latest "
                       f"90 days of dated items with the 90 days before, shown only when both have {ebi.MIN_N}+ items.")
else:
    _hl[1].metric("Positive or neutral", "—", help=f"Needs {ebi.MIN_N}+ labelled items.")

_lead = _pool.groupby("brand").size().sort_values(ascending=False)
if len(_lead):
    _hl[2].metric("Voice leader", str(_lead.index[0]), delta=f"{int(_lead.iloc[0]):,} items", delta_color="off",
                  help="Brand with the most items in the pool for the current filter. Delta is that brand's item count.")
else:
    _hl[2].metric("Voice leader", "—")

_dd = _pool["date"].dropna()
if not _dd.empty:
    _hl[3].metric("Data window", f"{_dd.min().strftime('%b %Y')} – {_dd.max().strftime('%b %Y')}",
                  help="Earliest to latest dated item in the pool. KiasuParents and Xiaohongshu comments carry no usable date, "
                       "and the early years are thin: most of the pool is from 2023 onward, with only a few older Reddit and YouTube comments.")
else:
    _hl[3].metric("Data window", "—")

_hl[4].metric("Products tracked", f"{len(products_f):,}",
              help="Distinct compliant product listings for the current brand filter (grey-market listings excluded).")
_hl[5].metric("Brands monitored", f"{len(selected_brands)}",
              help="Brands in the current filter.")

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
_SUBBRAND_PALETTE = ["#178197", "#0A7CC1", "#A51890", "#051F4A", "#59A5D7", "#555555"]
_SUBBRAND_OTHER_COLOR = "#999999"


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
(t_summary, t_brand, t_barriers, t_market_channel, t_social, t_evidence, t_positioning) = st.tabs(
    ["Summary", "Brand Health", "Journey & barriers", "Market & Channel", "Conversation & content", "Evidence & Stage 2",
     "Positioning Analysis"],
    on_change="rerun",  # dynamic tabs: only the selected tab's body runs (see `.open` guards below)
    key="main_tabs",
)
with t_market_channel:
    tab_market, tab_retail, tab_protect = st.tabs(
        ["Competitors & category", "Retailers", "Brand protection"],
        on_change="rerun", key="market_subtabs",
    )
tab_social_signals = t_social
with t_evidence:
    tab_stage2, tab_catalog, tab_notes, tab_price, tab_reviews_sentiment = st.tabs(
        ["Stage 2 bridge", "Data explorer", "Data notes", "Price (limited coverage)", "Product reviews (limited coverage)"],
        on_change="rerun", key="evidence_subtabs",
    )

if t_summary.open:
    with t_summary:
        _summary_frames = insights.build_frames(
            reviews, xhs,
            {
                "Reddit": (reddit_comments_df, reddit_signals),
                "YouTube": (youtube_comments_df, youtube_signals),
                "Instagram": (instagram_comments_df, instagram_signals),
                "Facebook": (facebook_comments_df, facebook_signals),
            },
        )
        overview_pages.render_summary(insights.snapshot(_summary_frames, charts.BRAND_ORDER, jf_all, products))

if t_positioning.open:
    with t_positioning:
        positioning_pages.render()

if tab_stage2.open:
    with tab_stage2:
        overview_pages.render_evidence()

# ---- Stage 1 EBI read-out pages (see EBI_insights_plan.md) -------------------
if tab_protect.open:
    with tab_protect:
        brand_protection.render(products_all)

if tab_market.open:
    with tab_market:
        market_competitors.render(products, _story_frames, selected_brands)

# ---- Brand Health (story page: see brand_health.py) -------------------------
if t_brand.open:
    with t_brand:
        brand_health.render(
            selected_brands, reviews_f, xhs,
            {
                "Reddit": (reddit_comments_df, reddit_signals),
                "YouTube": (youtube_comments_df, youtube_signals),
                "Instagram": (instagram_comments_df, instagram_signals),
                "Facebook": (facebook_comments_df, facebook_signals),
            },
            jf_all,
            extras={
                "Posts, videos and threads": len(youtube_videos_df) + len(instagram_posts_df) + len(facebook_posts_df) + len(reddit_posts_df),
                "MyACUVUE app reviews": len(_app_reviews_all),
                "Google Maps retailer reviews": len(_gmaps_reviews_all),
                "Product listings and prices": len(products_all),
                "Google Trends": _trends_points,
            },
        )


# ---- Price Intelligence -----------------------------------------------------
if tab_price.open:
    with tab_price:
        ebi.limits(["Limited coverage: marketplace data is Lazada and TikTok Shop only (no Shopee), so prices and reviews here are thin and not a full market view. Kept as reference, not as part of the brand story."])
        priced_f = products_f[products_f["selling_price"].notna()]
        if not priced_f.empty:
            _med = priced_f.groupby("brand")["selling_price"].median().sort_values()
            ui.subheader(
                f"Median price runs from {_currency_sym}{_med.iloc[0]:,.0f} ({_med.index[0]}) to {_currency_sym}{_med.iloc[-1]:,.0f} ({_med.index[-1]})",
                f"{len(priced_f)} priced compliant listings, SGD.", "Pricing", kind="fact")

        _brands_with_subs = [b for b in selected_brands if b in _SUBBRAND_RULES]

        if _brands_with_subs:
            priced_f = priced_f.copy()
            priced_f["_sub"] = priced_f.apply(
                lambda r: _subbrand(r["brand"], r["name_en"]) if r["brand"] in _SUBBRAND_RULES else None,
                axis=1,
            )

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

            _plot(fig, _site_caption(products_f, count_label="products", one_line=True) + " · Capped at each brand's p95; excluded SKUs labelled.",
                  bases={k: int(v) for k, v in trimmed.groupby(_plot_brand_col).size().items()}, noun="priced products",
                  say=(lambda _w: f"{_w.idxmax()} has the widest price range (S${priced_f[priced_f['brand'] == _w.idxmax()]['selling_price'].min():,.0f} to S${priced_f[priced_f['brand'] == _w.idxmax()]['selling_price'].max():,.0f}).")(priced_f.groupby("brand")["selling_price"].agg(lambda s: s.max() - s.min())))

            ui.subheader("Average discount differs by store and brand", "Deepest first.", "Pricing", kind="fact")
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
            st.caption("Sorted by deepest average discount.")

# ---- Reviews & Sentiment ----------------------------------------------------
if tab_reviews_sentiment.open:
    with tab_reviews_sentiment:
        ebi.limits(["Limited coverage: marketplace data is Lazada and TikTok Shop only (no Shopee), so prices and reviews here are thin and not a full market view. Kept as reference, not as part of the brand story."])
        sub_review_pane, sub_sentiment_pane, sub_new_wearer_pane = st.tabs(
            ["Review Intelligence", "Sentiment Intelligence", "New Wearers"],
            on_change="rerun", key="reviews_sentiment_tabs",
        )
        if sub_review_pane.open:
            with sub_review_pane:
                ui.subheader("Review volume and average rating by month", _site_caption(reviews_f, "review_date", "reviews", one_line=True), "Reviews", kind="fact")

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
                            labels={"reviews": "Reviews", "month": "Month"},
                        )
                        _pk = monthly.groupby("month")["reviews"].sum()
                        _plot(fig, bases=_by(rv), noun="reviews", say=f"Reviews peaked in {_pk.idxmax()} ({int(_pk.max()):,}).")
                    with c2:
                        fig = px.line(
                            monthly,
                            x="month",
                            y="avg_rating",
                            color="brand",
                            color_discrete_map=BRAND_COLORS,
                            markers=True,
                            labels={"avg_rating": "Avg. rating", "month": "Month"},
                        )
                        fig.update_yaxes(range=[0, 5])
                        _plot(fig, bases=_by(rv), noun="reviews", say=f"Average rating is {rv['rating'].mean():.1f}★ across all reviews.")

                    _lowshare = (reviews_tab_f["rating"] <= 2).mean() * 100
                    ui.subheader(f"{_lowshare:.0f}% of reviews are 1-2★", "", "Reviews", kind="fact")
                    fig = px.histogram(
                        reviews_tab_f,
                        x="rating",
                        color="brand",
                        color_discrete_map=BRAND_COLORS,
                        barmode="group",
                        nbins=5,
                    )
                    _plot(fig, _site_caption(reviews_tab_f, "review_date", "reviews", one_line=True), bases=_by(reviews_tab_f), noun="reviews")

                    ui.subheader("Reviews rated 1\u20132\u2605, lowest first", "Translated.", "Reviews", kind="fact")
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
                ui.subheader("Share of positive, neutral and negative reviews by brand", _site_caption(reviews_f, "review_date", "reviews", one_line=True) + " · 4–5★ positive, 3★ neutral, 1–2★ negative.", "Sentiment", kind="fact")

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
                            _ps = sv.groupby("brand")["sentiment"].apply(lambda s: (s == "positive").mean() * 100)
                            ui.takeaway(
                                f"<b>{_ps.idxmax()}</b> is most positive ({_ps.max():.0f}%); <b>{_ps.idxmin()}</b> least ({_ps.min():.0f}%). "
                                f"<span style='font-weight:400;color:#64748B'>{min_d.title()} – {max_d.title()} · {len(sv):,} reviews</span>")

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

                            SENT_COLORS = SENTIMENT_COLORS

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
                                    labels={"pct": "% of reviews", "month": "", "sentiment": "Sentiment"},
                                )
                            else:
                                fig = px.bar(
                                    monthly_sent,
                                    x="month", y="pct", color="sentiment",
                                    color_discrete_map=SENT_COLORS,
                                    labels={"pct": "% of reviews", "month": "", "sentiment": "Sentiment"},
                                )
                                fig.update_layout(barmode="stack")

                            fig.update_yaxes(range=[0, 105], ticksuffix="%")
                            fig.update_xaxes(tickangle=-45)
                            _plot(fig, _site_caption(reviews_f, "review_date", "reviews", one_line=True),
                                  bases=len(bv), noun=f"{sel_brand} reviews",
                                  say=(lambda _p: f"In {_p.iloc[-1]['month']}, {_p.iloc[-1]['pct']:.0f}% of {sel_brand} reviews are positive." if len(_p) else f"No monthly data for {sel_brand}.")(monthly_sent[monthly_sent["sentiment"] == "positive"].sort_values("month")))

                            ui.subheader(f"{int((bv['rating'] <= 2).sum())} reviews rate {sel_brand} 1–2★", "Newest first.", "Reviews", kind="fact")
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
                                    ui.takeaway(f"{sub_view_brand} has {len(acv_sv):,} reviews across {len(_subs_for_brand)} sub-brands: compare the cards.", "fact")
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
                                    ui.subheader("Monthly sentiment differs by sub-brand", "", "Sub-brands", kind="fact")
                                    SENT_COLORS_SUB = SENTIMENT_COLORS
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
                                                    labels={"pct": "% of reviews", "month": "", "sentiment": "Sentiment"},
                                                )
                                                fig.update_layout(barmode="stack")
                                                fig.update_yaxes(range=[0, 105], ticksuffix="%")
                                                fig.update_xaxes(tickangle=-45)
                                                _plot(fig, _site_caption(reviews_f, "review_date", "reviews", one_line=True),
                                                      bases=len(bv), noun=f"{sub} reviews",
                                                      say=f"{sub}: {(bv['sentiment'] == 'positive').mean() * 100:.0f}% positive across {len(bv):,} reviews.")

                                                ui.takeaway(f"{int((bv['rating'] <= 2).sum())} reviews rate {sub} 1\u20132\u2605.", "fact")
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
                ui.subheader("First-time buyers are found where reviewers say it is their first purchase", "Text match; not exhaustive.", "New wearers", kind="fact")

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
                                color_discrete_map=SENTIMENT_COLORS,
                            )
                            fig.update_layout(showlegend=False)
                            _plot(fig, _note(new_wearers, "Lazada first-time buyers", "review_date", "reviews"),
                                  bases=len(new_wearers), noun="first-time-buyer reviews",
                                  say=f"{neu_pct:.0f}% of first-time-buyer reviews are neutral.")
                        with c2:
                            by_brand = new_wearers.groupby("brand").size().reset_index(name="count").sort_values("count", ascending=False)
                            fig = px.bar(
                                by_brand,
                                x="brand",
                                y="count",
                                color="brand",
                                color_discrete_map=BRAND_COLORS,
                            )
                            fig.update_layout(showlegend=False)
                            _plot(fig, _note(new_wearers, "Lazada first-time buyers", "review_date", "reviews"),
                                  bases=_by(new_wearers), noun="first-time-buyer reviews",
                                  say=f"{by_brand.iloc[0]['brand']} wins the most first-time buyers ({int(by_brand.iloc[0]['count'])}).")

                        nw_monthly = new_wearers.copy()
                        nw_monthly["month"] = nw_monthly["review_date"].dt.to_period("M").astype(str)
                        monthly_sent = nw_monthly.groupby(["month", "sentiment"]).size().reset_index(name="count")
                        monthly_total = nw_monthly.groupby("month").size().reset_index(name="total")
                        monthly_sent = monthly_sent.merge(monthly_total, on="month")
                        monthly_sent["pct"] = monthly_sent["count"] / monthly_sent["total"] * 100
                        fig = px.bar(
                            monthly_sent,
                            x="month", y="pct", color="sentiment",
                            color_discrete_map=SENTIMENT_COLORS,
                            labels={"pct": "% of reviews", "month": "", "sentiment": "Sentiment"},
                        )
                        fig.update_layout(barmode="stack")
                        fig.update_yaxes(range=[0, 105], ticksuffix="%")
                        fig.update_xaxes(tickangle=-45)
                        _plot(fig, _note(new_wearers, "Lazada first-time buyers", "review_date", "reviews"),
                              say="First-time-buyer sentiment mix shifts month to month.", bases=len(new_wearers), noun="first-time-buyer reviews")

                        ui.subheader("First-time-buyer reviews, newest first", "", "New wearers", kind="fact")
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

# ---- Conversation & content (story page: see conversation_content.py) --------
if tab_social_signals.open:
    with tab_social_signals:
        conversation_content.render(
            selected_brands, xhs,
            {
                "YouTube": youtube_videos_df, "Instagram": instagram_posts_df,
                "Facebook": facebook_posts_df, "Reddit": reddit_posts_df,
            },
            {
                "Reddit": (reddit_comments_df, reddit_signals),
                "YouTube": (youtube_comments_df, youtube_signals),
                "Instagram": (instagram_comments_df, instagram_signals),
                "Facebook": (facebook_comments_df, facebook_signals),
            },
        )
        with st.expander("Channel detail: per-channel pages and search demand", expanded=False, on_change="rerun", key="social_detail") as _social_detail:
            if _social_detail.open:
                sub_xhs_pane, sub_reddit_pane, sub_youtube_pane, sub_instagram_pane, sub_facebook_pane, sub_fb_retail_pane, sub_trends_pane = st.tabs(
                    ["Customer Feedback (XHS)", "Customer Signals (Reddit)", "Customer Signals (YouTube)",
                     "Customer Signals (Instagram)", "Customer Signals (Facebook)", "Retailers & Promotions (Facebook)",
                     "Search Demand (Google Trends)"],
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
                            xhs_filtered = xhs_attributed(xhs)

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
                                            color_discrete_map=SENTIMENT_COLORS,
                                            labels={"brand_mentioned": "Brand", "count": "Posts"},
                                        )
                                        _vb = vol_by_brand.groupby("brand_mentioned")["count"].sum()
                                        _plot(fig, _xhs_summary, bases=_by(xhs_filtered, "brand_mentioned"), noun="XHS posts", say=f"{_vb.idxmax()} gets the most XHS posts ({int(_vb.max()):,}).")
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
                                            color_discrete_map=SENTIMENT_COLORS,
                                            labels={"brand_mentioned": "Brand", "pct": "%"},
                                        )
                                        fig.update_layout(yaxis_range=[0, 100])
                                        _neg = sentiment_pct[sentiment_pct["sentiment"] == "negative"]
                                        _plot(fig, _xhs_summary, say=(
                                            f"{_neg.loc[_neg['pct'].idxmax(), 'brand_mentioned']} has the highest negative share ({_neg['pct'].max():.0f}%)."
                                            if not _neg.empty else "No negative posts found."), bases=_by(xhs_filtered, "brand_mentioned"), noun="XHS posts")

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
                                        labels={"themes_list": "Theme", "count": "Mentions", "brand_mentioned": "Brand"},
                                    )
                                    fig.update_layout(barmode="stack")
                                    _plot(fig, _xhs_summary, height=380, bases=_by(xhs_filtered, "brand_mentioned"), noun="XHS posts",
                                          say=f"“{list(theme_order)[0]}” is the most mentioned theme." if len(theme_order) else "No themes found.")

                                    # ── Insight 1: Sentiment divergence (All Brands) ──────────────────
                                    if not xhs_comments.empty:
                                        _cmt_branded = xhs_comments.merge(
                                            xhs_filtered[["post_id", "brand_mentioned"]].drop_duplicates(),
                                            on="post_id", how="inner",
                                        )
                                        _sent_colors = SENTIMENT_COLORS


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
                                                color_discrete_map={"Post positive %": "#178197", "Comment positive %": "#A51890"},
                                                labels={"brand_mentioned": "Brand"},
                                            )
                                            fig.update_yaxes(range=[0, 100], ticksuffix="%")
                                            _d0 = _div_df.iloc[0]
                                            _plot(fig, _xhs_summary, say=(
                                                f"Commenters are {_d0['Divergence (pp)']:.0f} pts less positive than {_d0['brand_mentioned']} posts."
                                                if _d0["Divergence (pp)"] > 5 else "Comments broadly agree with posts."),
                                                bases={**_by(xhs_filtered, "brand_mentioned"),
                                                       **{f"{k} comments": v for k, v in _by(_cmt_branded, "brand_mentioned").items()}},
                                                noun="XHS posts",
                                                kind="fact")
                                        with c2:
                                            st.caption("Posts positive % minus comments positive %. Red = audience more negative.")
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
                                        ui.subheader("Some positive posts draw mostly negative comments", "Positive post with \u226550% negative comments: possibly sponsored or contested.", "Authenticity", kind="fact")

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
                                            st.success("No authenticity flags in any brand.")
                                        else:
                                            st.warning(f"{len(_flagged)} post(s) flagged.")
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
                                        xhs_b = xhs_filtered[xhs_filtered["brand_mentioned"] == brand]

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

                                        c1, c2 = st.columns([1, 2])
                                        with c1:
                                            sent_counts = xhs_b["sentiment"].value_counts().reset_index()
                                            sent_counts.columns = ["sentiment", "count"]
                                            fig = px.pie(
                                                sent_counts,
                                                names="sentiment",
                                                values="count",
                                                color="sentiment",
                                                color_discrete_map=SENTIMENT_COLORS,
                                            )
                                            _plot(fig, f"Xiaohongshu · {_xhs_date_range} · {ebi.count(len(xhs_b), 'posts')}",
                                                  say=f"{(xhs_b['sentiment'] == 'positive').mean() * 100:.0f}% of {brand} posts are positive." if len(xhs_b) else f"No {brand} posts.", bases=len(xhs_b), noun="XHS posts")
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
                                                color_discrete_map=SENTIMENT_COLORS,
                                                labels={"themes_list": "Theme", "count": "Mentions"},
                                            )
                                            fig.update_layout(barmode="stack")
                                            _tt = theme_sentiment.groupby("themes_list")["count"].sum()
                                            _plot(fig, f"Xiaohongshu · {_xhs_date_range} · {ebi.count(len(xhs_b), 'posts')}",
                                                  say=f"“{_tt.idxmax()}” is the most discussed theme for {brand}." if len(_tt) else "No themes found.", bases=len(xhs_b), noun="XHS posts")

                                        ui.subheader(f"{brand}'s 10 most-liked XHS posts", "", "XHS", kind="fact")
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
                                        ui.subheader(f"Audience reaction in comments on {brand} posts", "", "XHS", kind="fact")
                                        _cmt_b = (
                                            xhs_comments[xhs_comments["post_id"].isin(xhs_b["post_id"])]
                                            if not xhs_comments.empty else pd.DataFrame()
                                        )
                                        if _cmt_b.empty:
                                            st.caption("No comments collected yet for this brand.")
                                        else:
                                            _sent_colors = SENTIMENT_COLORS

                                            ca, cb = st.columns(2)
                                            with ca:
                                                _cs = _cmt_b["sentiment"].value_counts().reset_index()
                                                _cs.columns = ["sentiment", "count"]
                                                fig = px.pie(
                                                    _cs, names="sentiment", values="count",
                                                    color="sentiment", color_discrete_map=_sent_colors,
                                                )
                                                _plot(fig, f"Xiaohongshu · {ebi.count(len(_cmt_b), 'comments')}, {ebi.count(_cmt_b['post_id'].nunique(), 'posts')}",
                                                      say=f"{(_cmt_b['sentiment'] == 'negative').mean() * 100:.0f}% of {brand} comments are negative.", bases=len(_cmt_b), noun="XHS comments")
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
                                                    labels={"themes_list": "Theme", "count": "Comments"},
                                                )
                                                fig.update_layout(barmode="stack")
                                                _ctn = _ct[_ct["sentiment"] == "negative"].groupby("themes_list")["count"].sum()
                                                _plot(fig, f"Xiaohongshu · {ebi.count(len(_cmt_b), 'comments')}, {ebi.count(_cmt_b['post_id'].nunique(), 'posts')}",
                                                      say=(f"“{_ctn.idxmax()}” draws the most negative comments." if len(_ctn) else "No negative comment themes."), bases=len(_cmt_b), noun="XHS comments")

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
                                                ui.takeaway(f"{len(_b_flagged)} positive post(s) have \u226550% negative comments.", "fact")
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

                                            ui.takeaway("Most-liked comments show what the audience cares about.", "fact")
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

                                            ui.takeaway("Negative comments, most-liked first.", "fact")
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

                                        ui.subheader(f"{int((xhs_b['sentiment'] == 'negative').sum())} of {len(xhs_b)} {brand} posts are negative", "", "XHS", kind="fact")
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

                if sub_fb_retail_pane.open:
                    with sub_fb_retail_pane:
                        facebook_retailers.render()

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
                ui.subheader("Stores ranked by review-weighted rating; under 5 reviews is low confidence", "" + _site_caption(products_f, count_label="products", one_line=True), "Stores", kind="fact")

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
                        lambda n: f"Directional only ({int(n)} reviews)" if ebi.is_thin(n) else "OK"
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
                    ui.subheader("Multi-brand stores differ in review volume per brand", "Stores carrying 2+ selected brands.", "Stores", kind="fact")
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
                        _plot(fig_common, _site_caption(products_f, count_label="products", one_line=True),
                              bases={b: int(v) for b, v in common_rank.groupby("brand")["total_reviews"].sum().reindex(charts.order_brands(common_rank["brand"].unique())).items()},
                              noun="product reviews", say=f"{_store_order[0]} has the most reviews across brands.")

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
                ui.subheader("Every tracked listing with its price, rating and discount", _site_caption(products_f, count_label="products", one_line=True), "Products", kind="fact")

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

# ---- Journey & barriers (story page: see journey_barriers.py) ---------------
if t_barriers.open:
    with t_barriers:
        journey_barriers.render(selected_brands, jf_all, _story_frames)

if tab_retail.open:
    with tab_retail:
        ui.section(
            "Store friction shows up in Google Maps reviews of optical chains",
            "Retailer reviews, not brand reviews: the brand filter does not apply.",
            "Retailers",
            kind="fact",
        )
        gm_rev, gm_places = gmaps_signals.load_gmaps()
        if gm_rev.empty:
            st.info("No Google Maps data found (expected Scripts/output/gmaps_data_sg.db \u2192 gmaps_reviews).")
        else:
            st.caption(
                "Newest 100 reviews per outlet skew positive (~4.8\u2605): friction is understated. Tags are LLM-scored; "
                "contact-lens-only is a small sample. Internal use only."
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
                        fig = px.bar(gt, x="Friction reviews", y="Theme", orientation="h")
                        fig.update_layout(yaxis={"categoryorder": "total ascending"})
                        _g0 = gt.sort_values("Friction reviews", ascending=False).iloc[0]
                        _plot(fig, _note(gmv, "Google Maps", "date", f"reviews, {gmv['place_id'].nunique():,} outlets"),
                              say=f"\u201c{_g0['Theme']}\u201d is the top friction theme ({int(_g0['Friction reviews'])} reviews).",
                              bases=int(gmv["is_friction"].sum()), noun="friction reviews")
                with gg2:
                    ct = gmaps_signals.chain_table(gmv)
                    fig = px.bar(ct, x="Chain", y="Friction %", text="Reviews")
                    _c0 = ct.sort_values("Friction %", ascending=False).iloc[0]
                    _plot(fig, _note(gmv, "Google Maps", "date", f"reviews, {gmv['place_id'].nunique():,} outlets") + " · label = # reviews",
                          say=f"{_c0['Chain']} has the highest friction ({_c0['Friction %']:.0f}%): rough, small samples.",
                          bases={r_["Chain"]: int(r_["Reviews"]) for _, r_ in ct.iterrows()}, noun="reviews")
                st.dataframe(ct, width="stretch", hide_index=True)

                ui.takeaway("Outlets with the most friction reviews.", "fact")
                ot = (
                    gmv.groupby(["chain", "place_name"]).agg(Reviews=("review_id", "size"), Friction=("is_friction", "sum"))
                    .reset_index().sort_values(["Friction", "Reviews"], ascending=False).head(15)
                    .rename(columns={"chain": "Chain", "place_name": "Outlet"})
                )
                st.dataframe(ot[ot["Friction"] > 0], width="stretch", hide_index=True)

                ui.takeaway("Friction reviews, newest first.", "fact")
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
        ui.subheader("Each source has coverage limits that decide what can be quoted", "What each source can and cannot tell you.", "Data notes", kind="fact")
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
  Instagram comments are dominated by MyACUVUE (and Alcon's come mostly from one
  giveaway post; its SG account has not posted since Sept 2023); Reddit threads
  are mostly r/singapore and many are years old.
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
        st.caption(f"Built from {os.path.abspath(db_path)} + the social/XHS DBs beside it.")
