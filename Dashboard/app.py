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
from datetime import datetime

import pandas as pd
import plotly.express as px
import plotly.graph_objects as go
import streamlit as st

import answer_page
import barriers_page
import brand_health_page
import brand_market_page
import brand_overview_page
import research_extra_pages
import trends_demand_page
import charts
import data_ledger
import insights
import ebi
import brand_protection
import facebook_signals
import facebook_retailers
import gmaps_signals
import instagram_signals
import journey_signals
import market_competitors
import method_page
import overview_pages
import positioning_pages
import segment_views
import triangulation_pages
import ui
import voice_data
import reddit_signals
import trends_signals
import _social
import youtube_signals

import sys
from pathlib import Path
# Add project root (one level up from Dashboard/) to Python path
sys.path.append(str(Path(__file__).parent.parent))


from sg_common import (
    BRAND_COLORS, SENTIMENT_COLORS, SG_DB, XHS_DB,
    normalize_brand, read_table, xhs_attributed,
)

# ----------------------------------------------------------------------------
# Page config + light styling
# ----------------------------------------------------------------------------

st.set_page_config(
    page_title="Contact Lens Market Intelligence — Singapore",
    page_icon=str(Path(__file__).parent / "assets" / "myacuvue_logo.png"),
    layout="wide",
)

ui.inject_css()

_SITES_DISPLAY = "Lazada · TikTok Shop · Xiaohongshu · Reddit · KiasuParents · YouTube · Instagram · Facebook · App stores · Google Maps · Trends · AI search (ChatGPT, Perplexity)"

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

    # The same sentiment label on every page: the unified tag, matched to each scraper row by its own id.
    reviews = voice_data.unify(reviews, "reviews")
    xhs = voice_data.unify(xhs, "xhs_posts", "post_id")
    xhs_comments = voice_data.unify(xhs_comments, "xhs_comments")
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
# intelligence number, no longer shown on any tab.
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

ui.sample_key()
st.sidebar.divider()
_ledger = data_ledger.ledger()
_fresh = data_ledger.freshest(_ledger) or datetime.fromtimestamp(mtime).strftime('%Y-%m-%d %H:%M')
st.sidebar.caption(f"Newest build {_fresh} · cached up to 1 hour")
if st.sidebar.button("Reload data", icon=":material/refresh:", width="stretch"):
    st.cache_data.clear()
    st.rerun()
_xhs_attributed = xhs_attributed(xhs)
_voice = voice_data.load()
_raw = voice_data.raw_counts() if voice_data.available() else {}
_trends_all = trends_signals.load()
_trends_points = len(_trends_all)
if _raw:
    _f = voice_data.consumer_funnel()
    _items = data_ledger.items(_ledger)
    _total = int(_items["Items"].sum())
    st.sidebar.markdown(f"**{_total:,} data points collected**")
    _short = {"Consumer": "consumer comments, posts and reviews", "Retailer": "retailer reviews", "Brand": "brand posts and ads",
              "App": "app reviews", "Reference": "reference comments", "AI": "AI answers"}
    st.sidebar.caption(" · ".join(f"{int(n):,} " + next(v for k, v in _short.items() if src.startswith(k))
                                       for src, n in zip(_items["Source"], _items["Items"])))
    _pts = _ledger[~_ledger["Source"].isin(_items["Source"])]
    if len(_pts):
        st.sidebar.caption(f"Plus {int(_pts['Items'].sum()):,} weekly search-interest points (index values, not written items)")
    _new = _ledger[_ledger["Added today"].fillna(0) > 0]
    if len(_new):
        st.sidebar.caption("Added today: " + " · ".join(f"+{int(n):,} {src.split(' (')[0].lower()}" for src, n in zip(_new["Source"], _new["Added today"])))
    _stale = data_ledger.stale(_ledger)
    if len(_stale):
        st.sidebar.warning("Out of date: " + ", ".join(_stale["Source"].str.split(" (", regex=False).str[0]) + ". Details on Data Notes.", icon=":material/sync_problem:")
    with st.sidebar.expander(f"Why {_f['pool']:,} of {_f['collected']:,} consumer items compare brands"):
        for _line in (
            f"**{_f['pool']:,}** name a brand and are about lenses: the brand comparison",
            f"**{_f['off_topic']:,}** are not about contact lenses (mostly YouTube and Instagram comments)",
            f"**{_f['no_brand']:,}** talk about lenses but name no brand: read as category voice",
            f"**{_f['giveaway']:,}** are giveaway entries, written to win",
            f"**{_f['posts']:,}** are the post or video text people comment under",
            f"**{_f['other']:,}** are Xiaohongshu or Facebook items with no tracked brand or sentiment label",
        ):
            st.markdown(f"- {_line}")
st.sidebar.caption(f"{len(products_all)} product listings: {len(products)} compliant, {len(products_compliance)} grey-market excluded")

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
ui.brand_card(
    voice_data.FOCAL, "MyACUVUE",
    "Alcon, Bausch & Lomb, CooperVision and Olens", "7%", "14%",
)

# The story pages (Key findings, Brand & market, Journey & App) read only voice_data. The per-channel frames below belong to the
# Market & channel tab and the desk-research check, so they are built when one of those tabs is opened, not on every rerun.
def _jf_all():
    return journey_signals.load_journey_frame()


def _story_frames():
    return insights.build_frames(
        reviews[reviews["market"] == "SG"], xhs,
        {
            "Reddit": (reddit_comments_df, reddit_signals),
            "YouTube": (youtube_comments_df, youtube_signals),
            "Instagram": (instagram_comments_df, instagram_signals),
            "Facebook": (facebook_comments_df, facebook_signals),
        },
    )


# ---- Headline strip: six trust cards (volume, coverage, comparison base, time span); the findings sit in the Executive read. -----------------------------------
if _voice.empty:
    st.warning("The analysis tables are missing: run Scripts/build_voice_items.py and Scripts/tag_voice_items.py.")
else:
    st.caption("How much data stands behind this read. The findings are in the Executive read below.")
    _hm = answer_page.header()
    _gm_rev, _gm_places = gmaps_signals.load_gmaps()
    _priced = products_f[products_f["selling_price"].notna()]
    _card = dict(_hm)
    _card["Brands compared"] = (f"{len(selected_brands):,}", f"{selected_brands[0]} + {len(selected_brands) - 1} peers" if selected_brands else None, "Brands in the current filter (Acuvue and its peers).")
    _card["Stores covered"] = (f"{products_f['store_name'].nunique() + len(_gm_places):,}", f"{len(_gm_places):,} mapped outlets",
                               "Online stores carrying tracked listings plus the optician and retailer outlets whose Google Maps reviews were read.")
    _card["Products tracked"] = (f"{len(products_f):,}", f"{len(_priced):,} with a price",
                                 "Distinct compliant Singapore lens listings in the current brand filter. Online lens sales are not approved in Singapore, so this is a small part of the data.")
    for _key, _row in (("hl-strip", ("Items analysed", "Channels read", "Brands compared")),
                       ("hl-strip2", ("Data window", "Stores covered", "Products tracked"))):
        if _key == "hl-strip2":
            st.write("")
        for _col, _label in zip(st.container(key=_key).columns(3), _row):
            if _label in _card:
                _v, _d, _h = _card[_label]
                _col.metric(_label, _v, delta=_d, delta_color="off", delta_arrow="off", help=_h)
    answer_page.exec_read()   # the answer first: bottom line, what is new, what to send (the GM reads this before any tab)

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


# Wider phrases for store reviews, videos and posts, where people write "my first pair", "never tried contacts", "beginner".
_NEW_WEARER_VOICE_RE = re.compile(
    r"first time (buying|using|trying|wearing|ordering|getting|purchasing|wearer|user|buyer)|first[- ]time (wearer|user|buyer|contact)"
    r"|my first (pair|contact|lens|time)|new to (contact|lens)|never (worn|tried|used) (contact|lens)|beginners?\b|newbie"
    r"|just started (wearing|using)|first contact lens|first lens", re.I)


def _is_new_wearer_review(text):
    if pd.isna(text):
        return False
    return bool(_NEW_WEARER_POS_RE.search(text)) and not _NEW_WEARER_NEG_RE.search(text)

# Eleven top-level tabs in the order the data tells the story (same order as the HK dashboard), plus two SG-only tabs
# (Journey & App, Retail & promotions). Key findings is the last sub-tab of Research & triangulation: the conclusion
# comes after the evidence. Nested tabs only run when their parent is selected.
(t_overview, t_health, t_social, t_price, t_barriers, t_retail, t_research, t_trends, t_ai, t_notes) = st.tabs(
    ["Brand Overview", "Brand Health", "Social Signals", "Price Intelligence", "Journey & App",
     "Retail & Promotions", "Research & Triangulation", "Demand Trends", "AI Engines Discovery", "Data Notes"],
    on_change="rerun",  # dynamic tabs: only the selected tab's body runs (see `.open` guards below)
    key="main_tabs",
)


def _subparts(labels, key):
    """Nested sub-tabs under a top tab (HK layout). Returns one tab per label; fill each with `with tab:`."""
    return st.tabs(labels, on_change="rerun", key=key)


def _channel_roles():
    """Channel roles: which journey stage each channel evidences (home: Research & Triangulation > Social Analysis)."""
    if not _voice.empty:   # one cross-channel read before the five channel pages: who talks, at which stage, how much we hold
        _cn = voice_data.pool(_voice)["source"].value_counts()
        _map = pd.DataFrame([{"Channel": c, "Journey stage it evidences": r[0], "What people do there": r[1], "Brand-named items": int(_cn.get(c, 0))}
                             for c, r in voice_data.CHANNEL_ROLE.items() if c in set(_cn.index)]).sort_values("Brand-named items", ascending=False)
        ui.subheader("Each channel evidences a different stage, so no single channel speaks for the customer",
                     "Pick the channel by the stage of the journey you want to read. Counts are brand-named items in the pool.", "Channel roles", kind="fact")
        _stages = ["Awareness", "Engagement", "Consideration", "Trial", "Purchase", "Repeat"]
        _in = lambda v, s: s in [x.strip() for x in v.split(",")]
        _tot = [int(_map[_map["Journey stage it evidences"].map(lambda v, s=s: _in(v, s))]["Brand-named items"].sum()) for s in _stages]
        _pal = ["#178197", "#5FB0C0", "#B7791F", "#64748B", "#7C5CBF", "#2F855A", "#C05621", "#94A3B8"]
        _figm = go.Figure()
        for k_, r_ in enumerate(_map.itertuples()):   # largest channel first, at the foot of each column
            _hit = [s for s in _stages if _in(r_._2, s)]
            _figm.add_bar(name=r_.Channel, x=_hit, y=[int(r_._4)] * len(_hit), marker_color=_pal[k_ % len(_pal)],
                          text=[f"{r_.Channel} {int(r_._4)}" if int(r_._4) >= 40 else ""] * len(_hit), textposition="inside", insidetextanchor="middle",
                          textfont=dict(color="#FFFFFF", size=12), constraintext="none",
                          customdata=[r_._3] * len(_hit), hovertemplate="%{x}: " + r_.Channel + " %{y} items<br>%{customdata}<extra></extra>")
        _figm.update_xaxes(categoryorder="array", categoryarray=_stages, title=None)
        _figm.update_layout(barmode="stack", height=380, yaxis_title="Brand-named items", legend=dict(orientation="h", y=-0.2, traceorder="normal"))
        _plot(_figm, "", say=("Most of the brand-named items sit at Awareness and Engagement; "
                              + (f"no channel in the pool evidences {', '.join(s for s, n_ in zip(_stages, _tot) if n_ == 0)}. " if 0 in _tot else "")
                              + "A channel counts at every stage it evidences, so stages overlap and the columns do not add up to the pool total."),
              bases={r_["Channel"]: int(r_["Brand-named items"]) for _, r_ in _map.iterrows()}, noun="brand-named items")
        ui.show_data("Show the channel-role table", _map)


if t_research.open:
    with t_research:
        # Key findings, Research Findings, Distribution Gap and Attribute Quadrant are off the display (code kept: answer_page, positioning_pages,
        # research_extra_pages). The barrier-to-message chart moved to Journey & App > Message, AI answers to the AI Engines Discovery tab.
        _RESEARCH_SECTIONS = ["Barriers", "Social Analysis", "Share of Voice & Reach"]
        st.session_state.setdefault("triangulation_section_pills", _RESEARCH_SECTIONS[0])   # set first so a link from another tab can pick a section
        if st.session_state["triangulation_section_pills"] not in _RESEARCH_SECTIONS:
            st.session_state["triangulation_section_pills"] = _RESEARCH_SECTIONS[0]
        _section = st.pills("Section", _RESEARCH_SECTIONS, key="triangulation_section_pills") or _RESEARCH_SECTIONS[0]
        if _section == "Social Analysis":
            _channel_roles()
            st.divider()
            brand_health_page.channel_gap(_voice, selected_brands)
            st.divider()
            st.markdown("#### What Acuvue posts vs what consumers raise")
            brand_market_page.render(_voice)
        elif _section == "Share of Voice & Reach":
            market_competitors.render_voice_reach(_story_frames(), selected_brands)
        elif _section == "Barriers":
            ui.nav(["Category", "Barriers in complaints"])
            barriers_page.render_category(_voice, selected_brands)
            barriers_page.render_barrier(_voice)
            st.divider()
            answer_page.barrier_to_message(_voice)
            with st.expander("Same barriers across the whole brand pool (desk-research match)", expanded=False, on_change="rerun", key="bm_pool") as _bmx:
                if _bmx.open:
                    triangulation_pages.render_part("barriers", selected_brands, _voice)
                    _bm = _voice[_voice["brand_std"].isin(selected_brands) & _voice["in_pool"]]
                    ui.read_comments(_bm[_bm["item_id"].isin(set(voice_data.complaints(_bm)["item_id"]))], "Read the complaint items behind these barrier counts (brand pool)", key="bm_read")

# ---- Stage 1 EBI read-out pages (see EBI_insights_plan.md) -------------------
if t_overview.open:
    with t_overview:
        brand_overview_page.render(products_f, reviews_f, _voice, selected_brands, weighted_rating,
                                   _site_caption(reviews_f, "review_date", "reviews"), _story_frames)

# ---- Brand & market (story page: see brand_market_page.py) --------------------------------------------------
if t_health.open:
    with t_health:
        brand_health_page.render(_voice, selected_brands)


# ---- Channel detail: the per-channel pages (XHS, Reddit, YouTube, Instagram, Facebook, search demand) under Market & channel ----
if t_social.open:
    with t_social:
        sub_xhs_pane, sub_reddit_pane, sub_youtube_pane, sub_instagram_pane, sub_facebook_pane, sub_new_wearer_pane = _subparts(
            ["Customer Feedback (XHS)", "Customer Signals (Reddit)", "Customer Signals (YouTube)", "Customer Signals (Instagram)", "Customer Signals (Facebook)", "New Wearers"],
            "social_subtabs")
        with sub_xhs_pane:
            if xhs.empty:
                st.info("No XHS data loaded.")
            else:
                xhs_brands = sorted(
                    b for b in xhs["brand_mentioned"].dropna().unique() if b != "other"
                )
                xhs_filtered = xhs_attributed(xhs)

                st.markdown('<div class="caveat-box">Creator posts and comments on Xiaohongshu, translated to English; not verified purchasers.</div>', unsafe_allow_html=True)

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

                _cmt_branded = (xhs_comments.merge(xhs_filtered[["post_id", "brand_mentioned"]].drop_duplicates(), on="post_id", how="inner")
                                if not xhs_comments.empty else pd.DataFrame(columns=["post_id", "brand_mentioned", "sentiment"]))

                def _xhs_theme_heatmap(df, brands, note):
                    """Share of each brand's own posts that raise each theme. A cell needs 10+ posts to be drawn; brands are
                    compared on shares, so the different post counts do not tilt it. Acuvue's label is bold."""
                    ex = df.explode("themes_list").dropna(subset=["themes_list"])
                    cnt = ex.groupby(["themes_list", "brand_mentioned"]).size().unstack(fill_value=0).reindex(columns=brands, fill_value=0)
                    n = df.groupby("brand_mentioned").size().reindex(brands).fillna(0).astype(int)
                    keep = cnt[(cnt >= ebi.MIN_COUNT).any(axis=1)]
                    keep = keep.loc[keep.sum(axis=1).sort_values(ascending=False).index]
                    st.markdown("**Share of each brand's posts that raise the theme**")
                    if keep.empty:
                        st.caption(f"No theme reaches {ebi.MIN_COUNT} posts for any brand.")
                        return
                    pct = keep.div(n, axis=1) * 100
                    shown = pct.where(keep >= ebi.MIN_COUNT)
                    fig = go.Figure(go.Heatmap(
                        z=shown.values, x=[f"<b>{b}</b>" if b == voice_data.FOCAL else b for b in brands], y=list(shown.index),
                        text=[["" if pd.isna(v) else f"{v:.0f}%" for v in row] for row in shown.values], texttemplate="%{text}",
                        customdata=keep.values, hovertemplate="%{y} · %{x}<br>%{customdata} posts<extra></extra>",
                        colorscale=[[0, "#EEF5F7"], [1, "#178197"]], zmin=0, zmax=max(60, float(shown.max().max())), showscale=False,
                        xgap=2, ygap=2))
                    fig.update_yaxes(autorange="reversed", title=None)
                    fig.update_xaxes(side="top", tickangle=0, title=None)
                    f = voice_data.FOCAL
                    top = keep.index[0]
                    peers = [pct.loc[top, b] for b in brands if b != f and keep.loc[top, b] >= ebi.MIN_COUNT]
                    say = (f"{top}: {pct.loc[top, f]:.0f}% of {f} posts, " + (f"{min(peers):.0f}–{max(peers):.0f}% of peer posts." if peers else "too few peer posts to compare.")
                           if f in brands and keep.loc[top, f] >= ebi.MIN_COUNT else f"{top} is the most raised theme overall.")
                    _plot(fig, f"Cells under {ebi.MIN_COUNT} posts are left blank.", height=60 + 34 * len(keep) + 40, say=say,
                          bases=_by(df, "brand_mentioned"), noun="XHS posts")


                def _xhs_themes_chart(df, brand, note):
                    """One brand's posts: the themes they raise (10+ posts), each stacked by tone in the fixed order."""
                    th = (df.explode("themes_list").dropna(subset=["themes_list"])
                          .groupby(["themes_list", "sentiment"]).size().reset_index(name="count"))
                    tt = th.groupby("themes_list")["count"].sum()
                    show = tt[tt >= ebi.MIN_COUNT].sort_values(ascending=False)
                    st.markdown(f"**{brand} posts: what they are about, and how positive**")
                    if not len(show):
                        st.caption(f"{len(df)} {brand} posts; no theme reaches {ebi.MIN_COUNT} posts.")
                        return
                    fig = px.bar(th[th["themes_list"].isin(show.index)], x="count", y="themes_list", color="sentiment",
                                 orientation="h", color_discrete_map=SENTIMENT_COLORS,
                                 category_orders={"themes_list": list(show.index[::-1]), "sentiment": _social.SENT_ORDER},
                                 labels={"themes_list": "Theme", "count": "Posts"})
                    fig.update_layout(barmode="stack", legend=_social._LEGEND_TOP)
                    top = show.index[0]
                    pos = th[(th["themes_list"] == top) & (th["sentiment"] == "positive")]["count"].sum() / show.iloc[0] * 100
                    skipped = tt[tt < ebi.MIN_COUNT]
                    _plot(fig, (f"Not drawn, under {ebi.MIN_COUNT} posts: " + ", ".join(f"{k} {int(v)}" for k, v in skipped.sort_values(ascending=False).items()) + ".")
                          if len(skipped) else "", height=300,
                          say=f"{top}: {int(show.iloc[0])} of {len(df)} {brand} posts, {pos:.0f}% of them positive.",
                          bases=len(df), noun=f"{brand} XHS posts")


                if all_tab.open:
                    with all_tab:
                        _cb = _cmt_branded[["brand_mentioned", "sentiment"]].rename(columns={"brand_mentioned": "brand"})
                        _xb = sorted(xhs_filtered["brand_mentioned"].unique(), key=lambda b: (b != voice_data.FOCAL, b))
                        _hm = (xhs_filtered.explode("themes_list").dropna(subset=["themes_list"])
                               .groupby(["brand_mentioned", "themes_list"]).size().unstack(fill_value=0))
                        _hm_top = _hm.sum().sort_values(ascending=False)
                        ui.section((f"“{_hm_top.index[0]}” is the theme Xiaohongshu posts raise most, for {voice_data.FOCAL} and its peers"
                                    if len(_hm_top) and _hm_top.iloc[0] >= ebi.MIN_COUNT else "Xiaohongshu: too few themed posts to compare brands"),
                                   _xhs_summary, "Xiaohongshu", kind="fact")
                        _xc1, _xc2 = st.columns(2)
                        with _xc1:
                            _xhs_theme_heatmap(xhs_filtered, _xb, _xhs_summary)
                        with _xc2:
                            _social._tone_chart("Consumer comments: how positive", _cb, _xb, "brand-named comments", 300, "Comments")


                        def _xhs_detail():
                            _rows = []
                            for _b in _xb:
                                _p = xhs_filtered[xhs_filtered["brand_mentioned"] == _b]["sentiment"]
                                _c = _cb[_cb["brand"] == _b]["sentiment"]
                                _rows.append({"Brand": _b, "Creator posts": len(_p),
                                              "Posts positive": f"{(_p == 'positive').mean() * 100:.0f}%" if len(_p) >= ebi.MIN_N else "–",
                                              "Comments": len(_c),
                                              "Comments positive": f"{(_c == 'positive').mean() * 100:.0f}%" if len(_c) >= ebi.MIN_N else "–"})
                            st.caption("Creator posts against the comments under them; a rate only where a side has 15+ items.")
                            st.dataframe(pd.DataFrame(_rows), hide_index=True, width="stretch")
                        _social.posts_per_brand("posts", xhs_filtered.groupby("brand_mentioned").size().to_dict(), extra=_xhs_detail)

                        if not xhs_comments.empty:
                            # ── Insight 3: Authenticity flags (All Brands) ────────────────
                            ui.subheader("Every post with its comment sentiment", "All posts for the selected brands; comment columns are blank where a post has no brand-named comments.", "Authenticity", kind="fact")

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

                            _all_posts = (
                                xhs_filtered.merge(_cmt_stats, on=["post_id", "brand_mentioned"], how="left")
                                .sort_values(["negative_pct", "total_comments"], ascending=False, na_position="last")
                            )

                            st.caption(f"{len(_all_posts):,} posts; {int(_all_posts['total_comments'].notna().sum()):,} have brand-named comments. Sorted by share of negative comments.")
                            ui.text_table(
                                _all_posts[[
                                    "brand_mentioned", "content_en", "sentiment", "likes",
                                    "total_comments", "negative_pct", "neg_comment_likes", "url",
                                ]].rename(columns={
                                    "brand_mentioned": "Brand",
                                    "content_en": "Post content (EN)",
                                    "sentiment": "Post sentiment",
                                    "likes": "Post likes",
                                    "total_comments": "Comments",
                                    "negative_pct": "Neg comment %",
                                    "neg_comment_likes": "Neg comment likes",
                                    "url": "Link",
                                }), "Post content (EN)", key="xhs_flag_all",
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

                            _bcb = (_cmt_branded[_cmt_branded["post_id"].isin(xhs_b["post_id"])][["brand_mentioned", "sentiment"]]
                                    .rename(columns={"brand_mentioned": "brand"}))
                            _bc1, _bc2 = st.columns(2)
                            with _bc1:
                                _xhs_themes_chart(xhs_b, brand, _xhs_summary)
                            with _bc2:
                                _social._tone_chart("Consumer comments: how positive", _bcb, [brand], "brand-named comments", 300, "Comments")


                            ui.subheader(f"{brand}'s 10 most-liked XHS posts", "", "XHS", kind="fact")
                            top_posts = xhs_b.sort_values("likes", ascending=False).head(10)
                            ui.text_table(
                                top_posts.loc[:, ["sentiment", "themes", "content_en", "likes", "publish_date"]].rename(
                                    columns={
                                        "sentiment": "Sentiment",
                                        "themes": "Themes",
                                        "content_en": "Content (EN)",
                                        "likes": "Likes",
                                        "publish_date": "Date",
                                    }
                                ), "Content (EN)", key=f"xhs_top_{brand}",
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
                                d1.metric("Posts that are positive", f"{_b_post_pos:.1f}%")
                                d2.metric("Comments that are positive", f"{_b_cmt_pos:.1f}%")
                                d3.metric("Post minus comment positive share", ebi.pts(_b_div), help="Post positive % minus comment positive %. Large positive gap = audience more negative than posts suggest.")
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
                                    ui.text_table(
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
                                        }), "Post content (EN)", key=f"xhs_flag_{brand}",
                                        column_config={"Link": st.column_config.LinkColumn("Link", display_text="Open ↗")},
                                        width='stretch', hide_index=True, height=250,
                                    )

                                ui.takeaway("Most-liked comments show what the audience cares about.", "fact")
                                ui.text_table(
                                    _cmt_b.sort_values("likes", ascending=False)
                                    .head(20)
                                    [["author", "content_en", "sentiment", "themes", "likes"]]
                                    .rename(columns={
                                        "author": "Author",
                                        "content_en": "Comment (EN)",
                                        "sentiment": "Sentiment",
                                        "themes": "Themes",
                                        "likes": "Likes",
                                    }), "Comment (EN)", key=f"xhs_cmt_{brand}",
                                    width='stretch',
                                    hide_index=True,
                                    height=350,
                                )

                                ui.takeaway("Negative comments, most-liked first.", "fact")
                                _neg_cmt = _cmt_b[_cmt_b["sentiment"] == "negative"].sort_values("likes", ascending=False)
                                if _neg_cmt.empty:
                                    st.caption("No negative comments found.")
                                else:
                                    ui.text_table(
                                        _neg_cmt.head(20)
                                        [["author", "content_en", "themes", "likes"]]
                                        .rename(columns={
                                            "author": "Author",
                                            "content_en": "Comment (EN)",
                                            "themes": "Themes",
                                            "likes": "Likes",
                                        }), "Comment (EN)", key=f"xhs_negc_{brand}",
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
                                ui.text_table(
                                    neg_show[["content_en", "themes_joined", "likes", "publish_date"]].rename(
                                        columns={
                                            "content_en": "Post (EN)",
                                            "themes_joined": "Themes",
                                            "likes": "Likes",
                                            "publish_date": "Date",
                                        }
                                    ), "Post (EN)", key=f"xhs_negp_{brand}",
                                    column_config={"Post (EN)": st.column_config.TextColumn(width="large")},
                                    width="stretch",
                                    hide_index=True,
                                    height=420,
                                )

            ui.read_comments(_voice[_voice["source"].isin(["Xiaohongshu", "Xiaohongshu comments"])], "Read the Xiaohongshu posts and comments behind this tab (tagged)", key="xhs_read")
            if not xhs.empty:
                ui.read_proof(xhs_attributed(xhs), "Read the Xiaohongshu posts, with links", key="xhs_proof",
                              cols={'Date': 'publish_date', 'Brand': 'brand_mentioned', 'Author': 'author', 'Post': 'content_en', 'Likes': 'likes', 'Comments': 'comments'}, link="url")

        with sub_reddit_pane:
            reddit_signals.render()
            ui.read_comments(_voice[_voice["source"].isin(["Reddit", "KiasuParents"])], "Read the Reddit and KiasuParents items behind this tab (tagged)", key="reddit_read")
            ui.read_proof(reddit_signals.load_sg_dashboard_data()[0], "Read the Reddit and KiasuParents posts and videos, with links", key="reddit_proof",
                          cols={'Date': 'date', 'Subreddit': 'subreddit', 'Title': 'title', 'Post': 'selftext', 'Score': 'score', 'Comments': 'num_comments'}, link="permalink")

        with sub_youtube_pane:
            youtube_signals.render()
            ui.read_comments(_voice[_voice["source"].isin(["YouTube"])], "Read the YouTube items behind this tab (tagged)", key="youtube_read")
            ui.read_proof(youtube_signals.load_sg_dashboard_data()[0], "Read the YouTube posts and videos, with links", key="youtube_proof",
                          cols={'Date': 'date', 'Channel': 'channel_title', 'Title': 'title_en', 'Views': 'view_count', 'Likes': 'like_count', 'Comments': 'comment_count'}, link="url")

        with sub_instagram_pane:
            instagram_signals.render()
            ui.read_comments(_voice[_voice["source"].isin(["Instagram"])], "Read the Instagram items behind this tab (tagged)", key="instagram_read")
            ui.read_proof(instagram_signals.load_sg_dashboard_data()[0], "Read the Instagram posts and videos, with links", key="instagram_proof",
                          cols={'Date': 'published_at', 'Account': 'owner_username', 'Caption': 'caption_en', 'Likes': 'likes_count', 'Comments': 'comments_count'}, link="url")

        with sub_facebook_pane:
            facebook_signals.render()
            ui.read_comments(_voice[_voice["source"].isin(["Facebook", "Facebook ads"])], "Read the Facebook items behind this tab (tagged)", key="facebook_read")
            ui.read_proof(facebook_signals.load_sg_dashboard_data()[0], "Read the Facebook posts and videos, with links", key="facebook_proof",
                          cols={'Date': 'date', 'Page': 'page', 'Post': 'text', 'Likes': 'likes_count', 'Comments': 'comments_count'}, link="url")

        with sub_new_wearer_pane:
            # First-time wearers in the other channels: a text match on the tagged items, one lens at a time (never pooled).
            _vnw = voice_data.load()
            if not _vnw.empty:
                _vnw = _vnw[_vnw["lens"].isin(["consumer_voice", "retail_experience"]) & (_vnw["is_contest"] != 1)
                            & _vnw["text"].str.contains(r"contact|lens", case=False, regex=True)
                            & _vnw["text"].apply(lambda s: bool(_NEW_WEARER_VOICE_RE.search(s)) and not _NEW_WEARER_NEG_RE.search(s))
                            & (_vnw["source"] != "Lazada reviews")]
                _vnw_n = _vnw.groupby(["lens", "source"]).size().reset_index(name="count")
                ui.subheader("First-time wearers show up mostly in store reviews, with videos and posts behind them",
                             "Same text match on the other channels; consumer voice and retail experience are kept apart.", "New wearers", kind="fact")
                if _vnw_n.empty:
                    st.info("No first-time-wearer mentions in the other channels.")
                else:
                    _vnw_n["lens"] = _vnw_n["lens"].map({"consumer_voice": "Consumer voice", "retail_experience": "Retail experience"})
                    _vnw_n = _vnw_n.sort_values("count", ascending=False)
                    fig = px.bar(_vnw_n, x="count", y="source", color="lens", orientation="h",
                                 labels={"count": "First-time-wearer items", "source": "", "lens": ""})
                    fig.update_yaxes(autorange="reversed")
                    _gs = "Guidance & service"
                    _gs_n = int(_vnw["groups"].map(lambda g: _gs in g).sum())
                    _gs_pos = int(_vnw["gpol"].map(lambda g: g.get(_gs) == "positive").sum())
                    _tot = int(_vnw_n["count"].sum())
                    _plot(fig, "Tagged items in the SG voice table; text match, not exhaustive.",
                          say=(f"{_tot} items say it is their first time with contact lenses; {_gs_n} of them talk about guidance and service, "
                               f"{_gs_pos} with praise (staff walking them through the first fit)."),
                          bases={f"{r.source} ({r.lens})": int(r.count) for r in _vnw_n.itertuples()}, noun="first-time-wearer items")
                    ui.show_data("Counts behind the chart", _vnw_n.rename(columns={"lens": "Lens", "source": "Channel", "count": "Items"}))
                    ui.read_comments(_vnw, "Read the first-time-wearer items behind this section (tagged)", key="nw_voice_read")

            _nwc1, _nwc2 = st.columns(2)
            with _nwc1:
                ui.goto("Demand Trends", "Search direction for new-wearer segments", key="nw_to_search")
            with _nwc2:
                ui.goto("AI Engines Discovery", "How AI engines describe each segment", key="nw_to_ai")

            ui.subheader("Lazada first-time buyers are thin: a few reviews say it is their first purchase", "Text match on Lazada reviews only; not exhaustive.", "New wearers", kind="fact")

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
                    thin_nw = total_nw < ebi.MIN_N
                    if thin_nw:
                        m3.metric("Positive new-wearer reviews", f"{int((new_wearers['sentiment'] == 'positive').sum())}")
                        m4.metric("Negative new-wearer reviews", f"{int((new_wearers['sentiment'] == 'negative').sum())}")
                        st.caption(f"Only {total_nw} first-time-buyer reviews, under {ebi.MIN_N}: counts shown, no percentages.")
                    else:
                        m3.metric("Positive new-wearer reviews", f"{pos_pct:.0f}%")
                        m4.metric("Negative new-wearer reviews", f"{neg_pct:.0f}%")

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
                              say=(f"{int((new_wearers['sentiment'] == 'neutral').sum())} of {total_nw} first-time-buyer reviews are neutral."
                                   if thin_nw else f"{neu_pct:.0f}% of first-time-buyer reviews are neutral."))
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

                    if thin_nw:
                        st.caption(f"Monthly sentiment mix not drawn: {total_nw} first-time-buyer reviews, under {ebi.MIN_N}.")
                    else:
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
                        fig.update_xaxes(tickangle=-45, type="category")
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


            segment_views.reference_voice()


# ---- Price Intelligence -----------------------------------------------------
if t_price.open:
    with t_price:
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

        st.caption("Limits: there is no price vs. sentiment view for SG, unlike HK. Online lens sales are not approved in Singapore, so only "
                   "92 reviews (Lazada; Acuvue, Alcon, Bausch & Lomb) match a priced listing, almost all 4 to 5 stars. Split by price tier, "
                   "every cell falls under the 15-review minimum.")

        ui.read_proof(priced_f, "Read the listings behind these prices", key="pr_proof",
                      cols={"Product": "name_en", "Brand": "brand", "Store": "store_name", "Price": "selling_price", "Was": "original_price",
                            "Discount %": "discount_pct", "Rating": "avg_rating"})

# ---- Reviews & Sentiment ----------------------------------------------------

# ---- Journey & App (story page: see barriers_page.py) ---------------------------------------------------
if t_barriers.open:
    with t_barriers:
        barriers_page.render(_voice, selected_brands)

if t_retail.open:
    with t_retail:
        tab_retail, tab_fb_retail = _subparts(["Retailers (Google Maps)", "Retailers & Promotions (Facebook)"], "retail_subtabs")
        with tab_fb_retail:
            facebook_retailers.render()

if t_retail.open:
    with tab_retail:
        barriers_page.render_retail(_voice)   # the finding first: shops are praised, Acuvue is rarely named in them
        st.divider()
        ui.section(
            "Where store friction sits, by chain and outlet",
            "",
            "Retailers",
            kind="fact",
        )
        gm_rev, gm_places = gmaps_signals.load_gmaps()
        if gm_rev.empty:
            st.info("No Google Maps data found (expected Scripts/output/gmaps_data_sg.db \u2192 gmaps_reviews).")
        else:
            st.caption(
                "Google Maps reviews of optical chains, not brand reviews (the brand filter does not apply). Maps reviews skew positive (~4.8\u2605), so friction is understated. The contact-lens view is a keyword search of those reviews, "
                "LLM-scored; outside Owndays it is a small sample. Internal use only."
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
                gm_m[0].metric("Google Maps reviews", f"{len(gmv):,}")
                gm_m[1].metric("Outlets covered", f"{gmv['place_id'].nunique():,}")
                gm_m[2].metric("Average star rating", f"{gmv['rating'].mean():.2f}")
                gm_m[3].metric("Reviews describing friction", f"{gmv['is_friction'].mean() * 100:.1f}%",
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
if t_trends.open:
    with t_trends:
        trends_demand_page.render(_voice, selected_brands, _subparts(["Demand Signals", "Monthly Trends"], "trends_subtabs"))

if t_ai.open:
    with t_ai:
        segment_views.ai_answers()

if t_notes.open:
    with t_notes:
        st.subheader("Data coverage & known limitations")
        st.markdown(
            """
**Products & reviews (Lazada SG + TikTok Shop SG)**
- **Grey-market / compliance listings are excluded** from every product-intelligence
  number (`compliance_flag = 1`, 51 of 143 listings). They appear only in the
  Catalog Explorer → Brand protection sub-tab.
- **TikTok Shop listings mostly have no rating or review count**, so weighted
  ratings and store rankings effectively reflect Lazada only.
- **Reviews are Lazada only and cover Alcon (38), Bausch & Lomb (30) and Acuvue (24)**
  only; CooperVision and Olens have none. All 92 sit in the brand pool and are
  read by the shared tagger, like every other channel.
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

**Journey & App**
- **Journey stage has two sources.** The journey chart (first section) places each *complaint* at the stage where the problem
  happens, read from its text and source by `Scripts/tag_journey_stage.py` (stage-v4; most complaints are staged, about nine in ten at
  high confidence). The app is placed at Trial and Repeat by what it is, so it drives the Trial bar: the Acuvue-consumers-only view
  reads the stage from the comment alone. Items other than complaints are not staged this way: the main tagger names a stage for only
  about 40% of pool items, and the channel-role map (from context.md) shows where each channel can speak to the funnel.
- **A complaint has one definition on every page:** an item that is negative or
  mixed on a topic group, from the shared tagger. The per-source barrier flags
  (`is_purchase_barrier_signal` and the Facebook and Lazada derived tags) are
  retired from the story pages; the 12 barrier labels remain as detail under
  Loyalty & app on the app reviews and in the WhatsApp map.

**Optical retailers (Google Maps)**
- **Retailer reviews, not brand reviews** (Optical 88, Owndays, Better Vision,
  Capitol Optical, Visio Optical, Nanyang Optical), shown in Retail & Promotions → Retailers
  (topics on the shared labels, below the Maps view) as Consideration-stage signal. They are never
  pooled with the brand comparison and the brand filter does not apply.
- **Mostly the newest reviews per outlet** were pulled (plus a Google keyword
  search for contact-lens terms) and they skew positive (avg ~4.8★), so friction
  rates understate dissatisfaction. 862 of the 5,578 reviews are clearly about
  contact lenses (the default view), 535 of them Owndays, so per-chain rates
  outside Owndays are rough. Optical 88 returned 8 outlets and Visio 1 — coverage of
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
        st.divider()
        st.markdown("#### Coverage & method")
        method_page.render(_voice)
