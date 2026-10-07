"""
Journey-stage view of the SG data (the point of departure from the HK
dashboard): unions every source that carries a journey_stage into one long
frame, one row per (content item x stage), so the funnel / barrier analysis
can slice by stage.

Compliance rows (products.compliance_flag == 1, grey-market listings) are
NOT funnel data and are returned separately by load_compliance_products();
split_stages() already yields no stages for them.
"""

import json
import re

import pandas as pd
import streamlit as st

import app_store_signals
import facebook_signals
import instagram_signals
import reddit_signals
import youtube_signals
from sg_common import SG_DB, XHS_DB, latest_mtime, normalize_brand, read_table, split_stages, xhs_attributed

COLUMNS = ["source", "brand", "journey_stage", "sentiment", "is_barrier", "date", "author", "text", "url"]


# Lazada reviews + KiasuParents posts have no LLM-scored is_purchase_barrier_signal
# (see extract_sentiment_sg.py). Proxy built from fields they do have: a barrier is
# negative/mixed text that comments on an attribute that plausibly stops a purchase.
# shipping_fulfillment / packaging / customer_service are post-purchase experience,
# not reasons not to buy, so they don't count.
BARRIER_ATTRIBUTES = {"price", "comfort_dryness", "authenticity_counterfeit", "availability"}


def derive_barrier(sentiment, attribute_tags) -> int:
    if sentiment not in ("negative", "mixed"):
        return 0
    try:
        tags = set(json.loads(attribute_tags)) if attribute_tags else set()
    except Exception:
        return 0
    return int(bool(tags & BARRIER_ATTRIBUTES))


# Lazada reviews are all tagged "Consideration/Purchase/Repeat" in the DB, so Purchase and Repeat/Retention would hold
# identical items. Every review is a purchase; it counts as Repeat/Retention only when the reviewer says they bought or
# used it before. Keyword-matched, so Repeat is a floor.
REPEAT_RE = re.compile(
    r"repeat(?:ed)? (?:purchase|order|buy|customer)|re-?purchas|re-?order|"
    r"(?:bought|ordered|purchased) (?:\w+ ){0,2}again|again and again|keep (?:buying|ordering)|"
    r"(?:second|third|2nd|3rd|\d+(?:th)?) (?:time|bottle|box|pack)|always (?:buy|order|use)|regular (?:buyer|customer|user)|"
    r"(?:been|have been|am|i'?m) (?:using|buying|wearing)|(?:using|used) (?:this|it|these)? ?(?:for )?(?:\w+ )?(?:years?|months?|a while|sometime|some time)|"
    r"long[- ]?time (?:user|customer)|loyal", re.I)


def split_lazada_stage(stage, text) -> str:
    """Replace the blanket Purchase+Repeat tag with one of the two, from the review text."""
    parts = split_stages(stage)
    if "Purchase" not in parts or "Repeat/Retention" not in parts:
        return stage
    keep = [p for p in parts if p not in ("Purchase", "Repeat/Retention")]
    keep.append("Repeat/Retention" if REPEAT_RE.search(str(text or "")) else "Purchase")
    return "/".join(p.replace("Repeat/Retention", "Repeat|Retention") for p in keep).replace("|", "/")


def _explode(df: pd.DataFrame, stage_col: str = "journey_stage") -> pd.DataFrame:
    if df.empty:
        return pd.DataFrame(columns=COLUMNS)
    d = df.copy()
    d["journey_stage"] = d[stage_col].map(split_stages)
    d = d.explode("journey_stage")
    d = d[d["journey_stage"].notna()]
    return d[COLUMNS]


def _social(source: str, module, url_from_posts: bool = True) -> pd.DataFrame:
    posts, comments, _ = module.load_sg_dashboard_data()
    ot = module.on_topic_comments(comments)
    if ot.empty:
        return pd.DataFrame(columns=COLUMNS)
    urls = posts.drop_duplicates("post_key").set_index("post_key")["url_display"] if not posts.empty else pd.Series(dtype=object)
    d = pd.DataFrame({
        "source": source,
        "brand": ot["brand"].values,
        "journey_stage": ot["journey_stage"].values if "journey_stage" in ot.columns else None,
        "sentiment": ot["sentiment"].values,
        "is_barrier": pd.to_numeric(ot["is_purchase_barrier_signal"], errors="coerce").fillna(0).astype(int).values,
        "date": ot["date"].values,
        "author": ot["author"].values if "author" in ot.columns else None,
        "text": ot["text_display"].values,
        "url": ot["post_key"].map(urls).values,
    })
    return _explode(d)


@st.cache_data(show_spinner=False, ttl=3600, max_entries=4)
def _static_sources(mtime: float) -> pd.DataFrame:
    parts = []

    xhs = read_table(XHS_DB, "SELECT brand, brand_mentioned, sentiment, publish_date, title, content_en, url, brand_relevant, journey_stage FROM xhs_posts")
    if not xhs.empty:
        # same post set as Brand Health (posts naming a tracked brand), not the search brand: counts then reconcile
        xhs["brand_mentioned"] = xhs["brand_mentioned"].map(normalize_brand)
        xhs = xhs_attributed(xhs)
        xhs = xhs[xhs["journey_stage"].notna()]
        b = xhs["brand_mentioned"]
        parts.append(_explode(pd.DataFrame({
            "source": "Xiaohongshu", "brand": b.map(normalize_brand), "journey_stage": xhs["journey_stage"],
            "sentiment": xhs["sentiment"], "is_barrier": 0,
            "date": pd.to_datetime(pd.to_numeric(xhs["publish_date"], errors="coerce"), unit="s", errors="coerce", utc=True),
            "author": None, "text": xhs["content_en"].fillna(xhs["title"]), "url": xhs["url"],
        })))

    forum = read_table(SG_DB, "SELECT brand, post_title, post_date, post_url, content_summary, topic_tags, journey_stage, sentiment, attribute_tags FROM forum_posts")
    if not forum.empty:
        def _sent(row):
            if pd.notna(row["sentiment"]):
                return row["sentiment"]
            try:
                return json.loads(row["topic_tags"]).get("sentiment")
            except Exception:
                return None
        parts.append(_explode(pd.DataFrame({
            "source": "KiasuParents", "brand": forum["brand"].map(normalize_brand), "journey_stage": forum["journey_stage"],
            "sentiment": forum.apply(_sent, axis=1),
            "is_barrier": [derive_barrier(s, t) for s, t in zip(forum.apply(_sent, axis=1), forum["attribute_tags"])],
            "date": pd.to_datetime(forum["post_date"], errors="coerce", utc=True),
            "author": None, "text": forum["content_summary"].fillna(forum["post_title"]), "url": forum["post_url"],
        })))

    rev = read_table(SG_DB, "SELECT brand, sentiment, review_date, review_text, journey_stage, store_name, attribute_tags FROM reviews")
    if not rev.empty:
        rev["sentiment"] = rev["sentiment"].where(rev["sentiment"].isin(["positive", "neutral", "negative", "mixed"]))
        parts.append(_explode(pd.DataFrame({
            "source": "Lazada reviews", "brand": rev["brand"].map(normalize_brand),
            "journey_stage": [split_lazada_stage(st_, t) for st_, t in zip(rev["journey_stage"], rev["review_text"])],
            "sentiment": rev["sentiment"],
            "is_barrier": [derive_barrier(s, t) for s, t in zip(rev["sentiment"], rev["attribute_tags"])],
            "date": pd.to_datetime(rev["review_date"], errors="coerce", utc=True),
            "author": None, "text": rev["review_text"], "url": None,
        })))
    return pd.concat(parts, ignore_index=True) if parts else pd.DataFrame(columns=COLUMNS)


def _app_reviews() -> pd.DataFrame:
    """MyACUVUE app-store reviews. Stage = the stage(s) of the complaint themes a
    review mentions (login/freeze -> Trial, points/marketing -> Repeat/Retention);
    unthemed reviews default to Trial. Barrier = a 1-2 star review."""
    rev, _ = app_store_signals.load_app_reviews()
    if rev.empty:
        return pd.DataFrame(columns=COLUMNS)

    def _stage(themes):
        stages = {app_store_signals.theme_stage(t) for t in themes} or {"Trial"}
        return "/".join(sorted(stages))

    return _explode(pd.DataFrame({
        "source": "MyACUVUE app", "brand": "Acuvue",
        "journey_stage": rev["themes"].map(_stage),
        "sentiment": rev["sentiment"], "is_barrier": rev["is_barrier"],
        "date": rev["date"], "author": None, "text": rev["full_text"], "url": None,
    }))


def load_journey_frame() -> pd.DataFrame:
    """Long frame: one row per (content item x journey stage). Columns = COLUMNS."""
    parts = [
        _static_sources(latest_mtime(SG_DB, XHS_DB)),
        _app_reviews(),
        _social("YouTube", youtube_signals),
        _social("Instagram", instagram_signals),
        _social("Facebook", facebook_signals),
        _social("Reddit", reddit_signals),
    ]
    parts = [p for p in parts if not p.empty]
    return pd.concat(parts, ignore_index=True) if parts else pd.DataFrame(columns=COLUMNS)


def load_compliance_products() -> pd.DataFrame:
    """Grey-market / compliance-flagged listings (products.compliance_flag == 1)."""
    df = read_table(SG_DB, "SELECT * FROM products WHERE compliance_flag = 1")
    if not df.empty:
        df["brand"] = df["brand"].map(normalize_brand)
    return df
