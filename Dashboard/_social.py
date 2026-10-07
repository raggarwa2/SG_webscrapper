"""
Generic loader/renderer for the SG social platforms (YouTube, Instagram,
Facebook, Reddit). Every platform has the same shape — a posts table and a
comments table carrying sentiment / is_purchase_barrier_signal /
is_lens_relevant — so one parameterised implementation replaces the four
near-identical HK modules. youtube_signals.py etc. are thin wrappers.

Read-only. Two relevance layers (from the scrapers), flagged not dropped:
  - post-level brand_relevant == 0 -> post (and its comments) excluded,
    listed in an expander for transparency.
  - comment-level is_lens_relevant == 0 -> excluded from sentiment/barrier
    metrics, still shown in the raw comment browser.
Instagram posts additionally drop market_relevant == 0 (not an SG account).
"""

import os
from dataclasses import dataclass, field

import pandas as pd
import plotly.express as px
import streamlit as st

import ui
from sg_common import BRAND_COLORS, SENTIMENT_COLORS, normalize_brand, read_table

EMPTY_MONTHLY = ["month", "count"]


@dataclass
class Platform:
    key: str                      # "youtube"
    label: str                    # "YouTube"
    db_path: str
    posts_table: str
    comments_table: str
    post_id: str                  # key col in posts table
    title_cols: list              # first non-null wins
    text_cols: list               # body text (posts)
    date_col: str
    url_col: str
    channel_col: str
    metric_cols: dict             # {display label: column}
    comment_text_cols: list       # first non-null wins
    comment_like_col: str
    comment_date_col: str
    post_word: str = "posts"
    comment_post_id: str = "post_id"   # FK col in comments table (video_id for YT)
    extra_post_filters: list = field(default_factory=list)  # boolean cols that must be != 0
    caveat: str = ""


def _coalesce(df: pd.DataFrame, cols: list) -> pd.Series:
    out = pd.Series([None] * len(df), index=df.index, dtype=object)
    for c in cols:
        if c in df.columns:
            out = out.where(out.notna() & (out.astype(str).str.strip() != ""), df[c])
    return out


def _to_dt(s: pd.Series) -> pd.Series:
    return pd.to_datetime(s, errors="coerce", utc=True)


@st.cache_data(show_spinner=False, ttl=3600, max_entries=16)
def _load(cfg_key: str, db_path: str, mtime: float, _cfg: Platform):
    cfg = _cfg
    posts = read_table(db_path, f"SELECT * FROM {cfg.posts_table}")
    comments = read_table(db_path, f"SELECT * FROM {cfg.comments_table}")

    if not posts.empty:
        posts["brand"] = posts["brand"].map(normalize_brand)
        posts["title_display"] = _coalesce(posts, cfg.title_cols)
        posts["text_display"] = _coalesce(posts, cfg.text_cols)
        posts["date"] = _to_dt(posts[cfg.date_col])
        posts["url_display"] = posts[cfg.url_col] if cfg.url_col in posts.columns else None
        posts["channel_display"] = posts[cfg.channel_col] if cfg.channel_col in posts.columns else None
        posts["post_key"] = posts[cfg.post_id]
    if not comments.empty:
        comments["brand"] = comments["brand"].map(normalize_brand)
        comments["text_display"] = _coalesce(comments, cfg.comment_text_cols)
        comments["date"] = _to_dt(comments[cfg.comment_date_col])
        comments["likes_display"] = pd.to_numeric(comments.get(cfg.comment_like_col), errors="coerce").fillna(0)
        comments["post_key"] = comments[cfg.comment_post_id]
        for col in ("is_purchase_barrier_signal", "is_lens_relevant"):
            if col not in comments.columns:
                comments[col] = pd.NA
        if not posts.empty and "journey_stage" in posts.columns:
            comments = comments.merge(
                posts[["post_key", "journey_stage"]].drop_duplicates("post_key"), on="post_key", how="left"
            )
    return posts, comments


def load_data(cfg: Platform):
    """(posts, comments, excluded_posts). Posts already exclude
    brand_relevant == 0 / market_relevant == 0; comments are restricted to
    the surviving posts but still include off-topic ones (see on_topic())."""
    if not os.path.exists(cfg.db_path):
        e = pd.DataFrame()
        return e, e, e
    posts, comments = _load(cfg.key, cfg.db_path, os.path.getmtime(cfg.db_path), cfg)
    if posts.empty:
        return posts, comments, pd.DataFrame()
    bad = pd.Series(False, index=posts.index)
    for col in ["brand_relevant"] + cfg.extra_post_filters:
        if col in posts.columns:
            bad |= posts[col] == 0
    excluded = posts[bad]
    posts = posts[~bad]
    if not comments.empty:
        comments = comments[comments["post_key"].isin(posts["post_key"])]
    return posts, comments, excluded


def on_topic(comments: pd.DataFrame) -> pd.DataFrame:
    """Comments about the product (is_lens_relevant != 0; NaN fails open)."""
    if comments.empty:
        return comments
    return comments[comments["is_lens_relevant"] != 0]


def purchase_barrier_rate(on_topic_df: pd.DataFrame) -> pd.DataFrame:
    if on_topic_df.empty:
        return pd.DataFrame(columns=["brand", "post_count", "barrier_count", "barrier_rate"])
    d = on_topic_df.assign(_b=pd.to_numeric(on_topic_df["is_purchase_barrier_signal"], errors="coerce").fillna(0))
    g = d.groupby("brand").agg(post_count=("_b", "count"), barrier_count=("_b", "sum"))
    g["barrier_rate"] = (g["barrier_count"] / g["post_count"] * 100).round(1)
    return g.reset_index()


def monthly_counts(cfg: Platform, brand: str) -> pd.DataFrame:
    _, comments, _ = load_data(cfg)
    if comments.empty:
        return pd.DataFrame(columns=["month", f"{cfg.key}_count"])
    b = on_topic(comments[comments["brand"] == brand])
    months = b["date"].dt.strftime("%Y-%m").dropna()
    if months.empty:
        return pd.DataFrame(columns=["month", f"{cfg.key}_count"])
    return (months.value_counts().rename_axis("month").reset_index(name=f"{cfg.key}_count")
            .sort_values("month").reset_index(drop=True))


def _summary_metrics(cfg: Platform, posts_df, comments_df, on_topic_df) -> None:
    r1 = st.columns(2 + len(cfg.metric_cols))
    r1[0].metric(cfg.label + " " + cfg.post_word, len(posts_df))
    for i, (label, col) in enumerate(cfg.metric_cols.items(), start=1):
        total = pd.to_numeric(posts_df[col], errors="coerce").sum() if col in posts_df.columns else 0
        r1[i].metric(label, f"{int(total):,}")
    r1[-1].metric("Comments analyzed", len(on_topic_df))

    sc = on_topic_df["sentiment"].value_counts() if not on_topic_df.empty else pd.Series(dtype=int)
    barrier_n = int(pd.to_numeric(on_topic_df["is_purchase_barrier_signal"], errors="coerce").fillna(0).sum()) if not on_topic_df.empty else 0
    r2 = st.columns(5)
    r2[0].metric("Positive", int(sc.get("positive", 0)))
    r2[1].metric("Neutral", int(sc.get("neutral", 0)))
    r2[2].metric("Negative", int(sc.get("negative", 0)))
    r2[3].metric("Mixed", int(sc.get("mixed", 0)))
    r2[4].metric(
        "Purchase-barrier", barrier_n,
        delta=f"{barrier_n / len(on_topic_df) * 100:.0f}% of on-topic" if len(on_topic_df) else None,
        delta_color="off",
    )
    st.caption(f"{len(comments_df):,} comments collected; {len(comments_df) - len(on_topic_df):,} off-topic excluded.")


def render(cfg: Platform):
    if not os.path.exists(cfg.db_path):
        st.info(f"No {cfg.label} data found at `{cfg.db_path}`.")
        return
    posts, comments, excluded = load_data(cfg)
    if posts.empty:
        st.info(f"No {cfg.label} {cfg.post_word} loaded yet.")
        return

    if cfg.caveat:
        st.markdown(f'<div class="caveat-box">{cfg.caveat}</div>', unsafe_allow_html=True)

    if not excluded.empty:
        with st.expander(f"{len(excluded)} {cfg.post_word} excluded: off-brand or not SG"):
            ex = excluded[["brand", "title_display", "channel_display", "url_display"]].rename(columns={
                "brand": "Tagged brand", "title_display": "Title", "channel_display": "Source", "url_display": "Link"})
            st.dataframe(ex, width="stretch", hide_index=True,
                         column_config={"Link": st.column_config.LinkColumn("Link", display_text="Open ↗")})

    brands = sorted(posts["brand"].dropna().unique())
    if not brands:
        st.info("No posts with a recognized brand tag yet.")
        return

    all_tab, *brand_tabs = st.tabs(["All Brands"] + brands, on_change="rerun", key=f"{cfg.key}_brand_tabs")
    if all_tab.open:
        with all_tab:
            ui.section(
                f"{cfg.label}: compare brands on posts and comment tone",
                f"SG \u00b7 {len(brands)} brand(s) \u00b7 off-topic comments excluded from metrics",
                cfg.label, kind="fact")
            _summary_metrics(cfg, posts, comments, on_topic(comments))
            c1, c2 = st.columns(2)
            with c1:
                vol = posts.groupby("brand").size().reset_index(name="count")
                fig = px.bar(vol, x="brand", y="count", color="brand", color_discrete_map=BRAND_COLORS)
                fig.update_layout(showlegend=False)
                _v = vol.sort_values("count", ascending=False).iloc[0]
                ui.plot(fig, f"{_v['brand']} has the most {cfg.post_word} ({int(_v['count']):,}).", "fact",
                        cfg.label, height=240, bases={r["brand"]: int(r["count"]) for _, r in vol.iterrows()}, noun=cfg.post_word)
            with c2:
                ot = on_topic(comments)
                if not ot.empty:
                    sb = ot.groupby(["brand", "sentiment"]).size().reset_index(name="count")
                    fig = px.bar(sb, x="brand", y="count", color="sentiment", color_discrete_map=SENTIMENT_COLORS)
                    fig.update_layout(barmode="stack")
                    _n = sb[sb["sentiment"] == "negative"]
                    ui.plot(fig, (f"{_n.loc[_n['count'].idxmax(), 'brand']} draws the most negative comments ({int(_n['count'].max())})."
                                  if not _n.empty else "No negative on-topic comments."), "fact",
                            f"{cfg.label} \u00b7 off-topic comments excluded", height=240,
                            bases=ot.groupby("brand").size().astype(int).to_dict(), noun="on-topic comments")
                else:
                    st.caption("No on-topic comments to chart.")

    for brand, tab in zip(brands, brand_tabs):
        if tab.open:
            with tab:
                bp = posts[posts["brand"] == brand]
                bc = comments[comments["brand"] == brand] if not comments.empty else comments
                bo = on_topic(bc)
                _summary_metrics(cfg, bp, bc, bo)

                barrier = bo[pd.to_numeric(bo["is_purchase_barrier_signal"], errors="coerce").fillna(0) == 1] if not bo.empty else bo
                if barrier.empty:
                    ui.section(f"No purchase barriers flagged for {brand} here", "", cfg.label, kind="fact")
                else:
                    ui.section(f"Purchase-barrier comments for {brand}", "Most-liked first.", cfg.label, kind="fact")
                    # One table instead of three Streamlit calls per comment (this list is uncapped).
                    barrier_show = barrier.sort_values("likes_display", ascending=False).copy()
                    if "author" in barrier_show.columns:
                        barrier_show["author"] = barrier_show["author"].fillna("anon")
                    barrier_cols = {"author": "Author", "likes_display": "Likes",
                                    "sentiment": "Sentiment", "text_display": "Comment"}
                    barrier_cols = {c: label for c, label in barrier_cols.items() if c in barrier_show.columns}
                    st.dataframe(
                        barrier_show[list(barrier_cols)].rename(columns=barrier_cols),
                        column_config={"Comment": st.column_config.TextColumn(width="large")},
                        width="stretch", hide_index=True, height=min(420, 60 + 36 * len(barrier_show)),
                    )

                ui.section(f"{brand}'s {cfg.post_word} by reach", "Sorted by the platform's main reach metric.", cfg.label, kind="fact")
                cols = {"title_display": "Title", "channel_display": "Source", "date": "Published"}
                for label, col in cfg.metric_cols.items():
                    cols[col] = label
                cols["url_display"] = "Link"
                show = bp[[c for c in cols if c in bp.columns]].rename(columns=cols)
                if "Published" in show.columns:
                    show["Published"] = show["Published"].dt.strftime("%Y-%m-%d")
                sort_col = next(iter(cfg.metric_cols), None)
                if sort_col and sort_col in show.columns:
                    show = show.sort_values(sort_col, ascending=False)
                st.dataframe(show, width="stretch", hide_index=True,
                             column_config={"Link": st.column_config.LinkColumn("Link", display_text="Open ↗")})

                ui.section("Top comments by likes show tone and objections", "Top 50.", cfg.label, kind="fact")
                if bc.empty:
                    st.caption("No comments collected for this brand yet.")
                else:
                    for _, row in bc.sort_values("likes_display", ascending=False).head(50).iterrows():
                        tag = " · _off-topic, excluded from metrics_" if row["is_lens_relevant"] == 0 else ""
                        st.markdown(f"**{row.get('author') or 'anon'}** · 👍 {int(row['likes_display'])} · sentiment: {row['sentiment']}{tag}")
                        st.write(row["text_display"])
                        st.divider()
                    if len(bc) > 50:
                        st.caption(f"Top 50 of {len(bc)} comments.")
