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
  - contest entries (Platform.contest_from_caption, Instagram): a comment under a giveaway post answers the prize question,
    so it is flagged is_contest and excluded the same way.
Instagram posts additionally drop market_relevant == 0 (not an SG account).
"""

import palette
import os
from dataclasses import dataclass, field

import pandas as pd
import plotly.express as px
import streamlit as st

import ebi
import ui
import voice_data
from sg_common import BRAND_COLORS, PEER_GREY, SENTIMENT_COLORS, is_contest_caption, normalize_brand, read_table

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
    contest_from_caption: bool = False   # comments under a giveaway post (sg_common.is_contest_caption) are contest entries


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
        if cfg.contest_from_caption:
            cap_cols = [c for c in cfg.text_cols if c in posts.columns]
            posts["is_contest"] = [is_contest_caption(*r) for r in posts[cap_cols].itertuples(index=False)]
    if not comments.empty:
        comments["brand"] = comments["brand"].map(normalize_brand)
        comments = voice_data.unify(comments, cfg.comments_table)   # same label as the story pages
        comments["text_display"] = _coalesce(comments, cfg.comment_text_cols)
        comments["date"] = _to_dt(comments[cfg.comment_date_col])
        comments["likes_display"] = pd.to_numeric(comments.get(cfg.comment_like_col), errors="coerce").fillna(0)
        comments["post_key"] = comments[cfg.comment_post_id]
        if cfg.contest_from_caption and not posts.empty and "is_contest" in posts.columns:
            comments["is_contest"] = (comments["post_key"].map(posts.drop_duplicates("post_key").set_index("post_key")["is_contest"])
                                      .fillna(False).astype(bool))
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
    posts, comments = _load(cfg.key, cfg.db_path, os.path.getmtime(cfg.db_path) + voice_data.stamp(), cfg)
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
    """Comments about the product (is_lens_relevant != 0; NaN fails open) that are not contest entries."""
    if comments.empty:
        return comments
    keep = comments["is_lens_relevant"] != 0
    if "is_contest" in comments.columns:
        keep &= ~comments["is_contest"].fillna(False).astype(bool)
    return comments[keep]


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


def _focal_style(fig, brands: list) -> None:
    """Acuvue's label in bold and a light tint behind its column, as on every brand chart."""
    fig.update_xaxes(tickvals=brands, ticktext=[f"<b>{b}</b>" if b == voice_data.FOCAL else b for b in brands],
                     tickangle=0, tickfont=dict(size=11), title=None, automargin=True)
    if voice_data.FOCAL in brands:
        i = brands.index(voice_data.FOCAL)
        fig.add_vrect(x0=i - 0.5, x1=i + 0.5, fillcolor=palette.FOCAL_COLOR, opacity=0.07, line_width=0, layer="below")


SENT_ORDER = ["positive", "neutral", "mixed", "negative"]   # one order in every sentiment chart and legend
# Posts versus comments: two fixed neutral shades, so no brand colour doubles as a series colour.
VOICE_COLORS = {"Brand's own posts": palette.LENS_COLORS["Brand broadcast"], "Consumer comments": palette.LENS_COLORS["Consumer voice"]}
_LEGEND_TOP = dict(orientation="h", y=1.02, yanchor="bottom", x=0, title_text="")


def _counts(df, brands) -> dict:
    n = df.groupby("brand").size() if df is not None and not df.empty else {}
    return {b: int(n[b]) if b in n else 0 for b in brands}


def _strip(word: str, n: dict) -> str:
    return f"{word}: " + " \u00b7 ".join(f"{b} {v}" for b, v in n.items())


def _pos_pct(df, b) -> float:
    d = df[df["brand"] == b]
    return float((d["sentiment"] == "positive").mean() * 100)


def _tone_chart(title: str, df, brands: list, word: str, height: int, strip_word: str) -> None:
    """Share of positive / neutral / mixed / negative per brand, in % (counts mislead when the bases differ). Brands under
    ebi.MIN_N items are left out of the bars and named in a note; no brand is named as the winner."""
    st.markdown(f"**{title}**")
    n = _counts(df, brands)
    shown = [b for b in brands if n[b] >= ebi.MIN_N]
    if not shown:
        st.caption(f"No brand has {ebi.MIN_N}+ {word} yet. Counts: " + ", ".join(f"{b} {v}" for b, v in n.items()) + ".")
        return
    g = df[df["brand"].isin(shown)].groupby(["brand", "sentiment"]).size().unstack(fill_value=0).reindex(columns=SENT_ORDER, fill_value=0)
    pct = (g.div(g.sum(axis=1), axis=0) * 100).round(1).reset_index().melt(id_vars="brand", var_name="sentiment", value_name="pct")
    fig = px.bar(pct, x="brand", y="pct", color="sentiment", color_discrete_map=SENTIMENT_COLORS,
                 category_orders={"brand": shown, "sentiment": SENT_ORDER}, labels={"pct": f"% of {word}"})
    fig.update_layout(barmode="stack", yaxis_range=[0, 100], legend=_LEGEND_TOP)
    _focal_style(fig, shown)
    f = voice_data.FOCAL
    say = (f"{f}: {_pos_pct(df, f):.0f}% positive, {float((df[df['brand'] == f]['sentiment'] == 'negative').mean() * 100):.0f}% negative."
           if f in shown else f"{f} has too few {word} to read ({n.get(f, 0)}).")
    hidden = [f"{b} ({n[b]})" for b in brands if b not in shown]
    ui.plot(fig, say, "fact", (f"Not drawn, under {ebi.MIN_N}: " + ", ".join(hidden) + ".") if hidden else "", height=height,
            bases=_strip(strip_word, n))


def posts_vs_comments(posts, comments, brands: list) -> None:
    """Share positive of each brand's own posts set against the comments under them. A brand needs ebi.MIN_N of both
    to be drawn; the gap is shown, not graded (a gap claim needs the test in the reading rules)."""
    f = voice_data.FOCAL
    nc, npst = _counts(comments, brands), _counts(posts, brands)
    both = [b for b in brands if npst[b] >= ebi.MIN_N and nc[b] >= ebi.MIN_N]
    st.markdown("**Brand posts vs consumer comments: share positive**")
    if not both:
        st.caption(f"No brand has {ebi.MIN_N}+ posts and {ebi.MIN_N}+ comments to compare yet.")
        return
    rows = [{"brand": b, "voice": v, "pct": round(_pos_pct(d, b), 1)}
            for b in both for v, d in (("Brand's own posts", posts), ("Consumer comments", comments))]
    fig = px.bar(pd.DataFrame(rows), x="brand", y="pct", color="voice", barmode="group", color_discrete_map=VOICE_COLORS,
                 category_orders={"brand": both, "voice": list(VOICE_COLORS)}, labels={"pct": "% positive"})
    fig.update_layout(yaxis_range=[0, 100], legend=_LEGEND_TOP)
    fig.update_yaxes(ticksuffix="%")
    _focal_style(fig, both)
    say = (f"{f}'s own posts are {_pos_pct(posts, f):.0f}% positive; the comments on them are {_pos_pct(comments, f):.0f}%."
           if f in both else f"Too few {f} comments to set against its posts ({nc[f]}).")
    left = [b for b in brands if b not in both]
    ui.plot(fig, say, "fact", (f"Not drawn, under {ebi.MIN_N} posts or comments: " + ", ".join(left) + ".") if left else "",
            height=300, bases=_strip("Posts", npst) + "  |  " + _strip("Comments", nc))


def overview(label: str, post_word: str, posts_by_brand: dict, comments, subtitle: str, sentiment_noun: str,
             note: str = "", height: int = 260, posts=None) -> None:
    """The first view of every Social Signals tab, in plain words. With post tone (`posts`, columns brand and sentiment) the
    lead chart sets what the brand's own posts say against what consumers say; then each side's tone; posts per brand
    (activity, not a finding) sits in a closed expander. Without post tone the lead is the consumer comment tone."""
    comments = comments if comments is not None else pd.DataFrame(columns=["brand", "sentiment"])
    brands = sorted(posts_by_brand, key=lambda b: (b != voice_data.FOCAL, b))
    f = voice_data.FOCAL
    nc = _counts(comments, brands)
    if posts is not None:
        npst = _counts(posts, brands)
        both = [b for b in brands if npst[b] >= ebi.MIN_N and nc[b] >= ebi.MIN_N]
        title = f"{label}: tone of brands' posts and of the comments on them"
        ui.section(title, subtitle, label, kind="fact", first=True)
        posts_vs_comments(posts, comments, brands)
        c1, c2 = st.columns(2)
        with c1:
            _tone_chart("Brand posts: how positive", posts, brands, post_word, height, "Posts")
        with c2:
            _tone_chart("Consumer comments: how positive", comments, brands, sentiment_noun, height, "Comments")
    else:
        focal = comments[comments["brand"] == f] if not comments.empty else comments
        title = f"{label}: tone of comments about each brand"
        ui.section(title, subtitle, label, kind="fact", first=True)
        _tone_chart("Consumer comments: how positive", comments, brands, sentiment_noun, 280, "Comments")
    posts_per_brand(post_word, posts_by_brand)


def posts_per_brand(post_word: str, posts_by_brand: dict, extra=None) -> None:
    """Posts per brand is activity, not a finding: a closed expander, with an optional `extra()` drawn under the chart."""
    brands = sorted(posts_by_brand, key=lambda b: (b != voice_data.FOCAL, b))
    f = voice_data.FOCAL
    with st.expander(f"Posts per brand ({post_word}: activity, not tone)", expanded=False):
        vol = pd.DataFrame({"brand": brands, "count": [posts_by_brand[b] for b in brands]})
        fig = px.bar(vol, x="brand", y="count", color="brand", labels={"count": post_word.capitalize()},
                     color_discrete_map={b: (BRAND_COLORS["Acuvue"] if b == f else PEER_GREY) for b in brands},
                     category_orders={"brand": brands})
        fig.update_layout(showlegend=False)
        _focal_style(fig, brands)
        ui.plot(fig, "", "fact", "", height=220, bases=_strip("Posts", {b: int(posts_by_brand[b]) for b in brands}))
        if extra:
            extra()


def _caption(comments_df, on_topic_df) -> None:
    n_contest = int((comments_df["is_contest"].fillna(False).astype(bool) & (comments_df["is_lens_relevant"] != 0)).sum())         if "is_contest" in comments_df.columns and "is_lens_relevant" in comments_df.columns else 0
    n_off = len(comments_df) - len(on_topic_df) - n_contest
    st.caption(f"{len(comments_df):,} comments collected; {n_off:,} off-topic"
               + (f" and {n_contest:,} giveaway entries" if n_contest else "") + " excluded.")


PROOF_LIMIT = 5000   # the foot lists every row collected, not a sample

_REACH_COLS = {"Views": "view_count", "Video views": "video_views", "Likes": "like_count", "Likes ": "likes_count", "Score": "score",
               "Shares": "shares_count", "Comments": "comment_count", "Comments ": "comments_count", "Comments  ": "num_comments"}


def proof_foot(cfg: Platform, key_prefix: str = "") -> None:
    """The foot of a channel tab: every comment and every post or video collected, with views or reach and a link. Unlike the tagged
    items above it (on-topic only), nothing is dropped; a status column says what the metrics counted."""
    if not os.path.exists(cfg.db_path):
        return
    allp, comments = _load(cfg.key, cfg.db_path, os.path.getmtime(cfg.db_path) + voice_data.stamp(), cfg)   # raw: nothing filtered
    if allp.empty:
        return
    bad = pd.Series(False, index=allp.index)
    for col in ["brand_relevant"] + cfg.extra_post_filters:
        if col in allp.columns:
            bad |= allp[col] == 0
    allp = allp.assign(Status=bad.map({False: "In the tabs", True: "Left out: off-brand or not SG"}))
    if "is_contest" in allp.columns:
        allp.loc[allp["is_contest"].fillna(False).astype(bool), "Status"] = "Giveaway post"
    key = key_prefix or cfg.key
    p = allp.assign(Date=allp["date"].dt.strftime("%Y-%m-%d"), Brand=allp["brand"], Source=allp["channel_display"],
                    Post=allp["title_display"], Link=allp["url_display"])
    reach = {lab.strip(): c for lab, c in _REACH_COLS.items() if c in p.columns}
    p = p.sort_values("date", ascending=False)
    read_cols = {c: c for c in ["Date", "Brand", "Source", "Post"]} | reach | {"Status": "Status"}
    ui.read_proof(p, f"Read every {cfg.label} {cfg.post_word[:-1] if cfg.post_word.endswith('s') else cfg.post_word} collected, with views and links",
                  cols=read_cols, key=f"{key}_allposts", link="Link", limit=PROOF_LIMIT)
    excluded = load_data(cfg)[2]
    if not excluded.empty:
        with st.expander(f"Table: {len(excluded)} {cfg.post_word} excluded (off-brand or not SG) · {cfg.label}"):
            ex = excluded[["brand", "title_display", "channel_display", "url_display"]].rename(columns={
                "brand": "Tagged brand", "title_display": "Title", "channel_display": "Source", "url_display": "Link"})
            st.dataframe(ex, width="stretch", hide_index=True,
                         column_config={"Link": st.column_config.LinkColumn("Link", display_text="Open ↗")})
    if comments.empty:
        return
    url_of = allp.drop_duplicates("post_key").set_index("post_key")["url_display"]
    status = pd.Series("Counted", index=comments.index)
    if "is_contest" in comments.columns:
        status[comments["is_contest"].fillna(False).astype(bool)] = "Giveaway entry, not counted"
    status[comments["is_lens_relevant"] == 0] = "Off-topic, not counted"
    status[~comments["post_key"].isin(allp.loc[allp["Status"] == "In the tabs", "post_key"])] = "On a post left out, not counted"
    c = comments.assign(Date=comments["date"].dt.strftime("%Y-%m-%d"), Brand=comments["brand"], Author=comments.get("author"),
                        Comment=comments["text_display"], Likes=comments["likes_display"].astype(int), Sentiment=comments["sentiment"],
                        Status=status, Link=comments["post_key"].map(url_of)).sort_values("date", ascending=False)
    ui.read_proof(c, f"Read all {len(c):,} {cfg.label} comments collected ({int((status == 'Counted').sum()):,} counted), with links",
                  cols={k: k for k in ["Date", "Brand", "Author", "Comment", "Likes", "Sentiment", "Status"]},
                  key=f"{key}_allcomments", link="Link", limit=PROOF_LIMIT)


def render(cfg: Platform):
    if not os.path.exists(cfg.db_path):
        st.info(f"No {cfg.label} data found at `{cfg.db_path}`.")
        return
    posts, comments, excluded = load_data(cfg)
    if posts.empty:
        st.info(f"No {cfg.label} {cfg.post_word} loaded yet.")
        return

    if cfg.caveat:
        st.markdown(f'<div class="caveat-box">{ui.logo_img([cfg.label])}{cfg.caveat}</div>', unsafe_allow_html=True)

    brands = sorted(posts["brand"].dropna().unique())
    if not brands:
        st.info("No posts with a recognized brand tag yet.")
        return

    all_tab, *brand_tabs = st.tabs(["All Brands"] + brands, on_change="rerun", key=f"{cfg.key}_brand_tabs")
    if all_tab.open:
        with all_tab:
            _ot = on_topic(comments)
            overview(cfg.label, cfg.post_word, posts.groupby("brand").size().to_dict(), _ot,
                     f"SG · {len(brands)} brand(s) · off-topic comments excluded from metrics", "on-topic comments")
            _caption(comments, _ot)

    for brand, tab in zip(brands, brand_tabs):
        if tab.open:
            with tab:
                bp = posts[posts["brand"] == brand]
                bc = comments[comments["brand"] == brand] if not comments.empty else comments
                bo = on_topic(bc)
                _caption(bc, bo)

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
                    ui.tlabel(f"purchase-barrier comments · {cfg.label}")
                    st.dataframe(
                        barrier_show[list(barrier_cols)].rename(columns=barrier_cols),
                        column_config={"Comment": st.column_config.TextColumn(width="large")},
                        width="stretch", hide_index=True, height=min(420, 60 + 36 * len(barrier_show)),
                    )

                with st.expander(f"{brand}'s {cfg.post_word} by reach (sorted by the platform's main reach metric)", expanded=False, on_change="rerun", key=f"{cfg.key}_reach_{brand}") as _rx:
                    if _rx.open:
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
                        ui.tlabel(f"{cfg.post_word} · {cfg.label}")
                        st.dataframe(show, width="stretch", hide_index=True,
                                     column_config={"Link": st.column_config.LinkColumn("Link", display_text="Open ↗")})


                with st.expander("Top comments by likes (tone and objections, top 50)", expanded=False, on_change="rerun", key=f"{cfg.key}_top_{brand}") as _cx:
                    if _cx.open:
                        if bc.empty:
                            st.caption("No comments collected for this brand yet.")
                        else:
                            for _, row in bc.sort_values("likes_display", ascending=False).head(50).iterrows():
                                tag = (" · _off-topic, excluded from metrics_" if row["is_lens_relevant"] == 0
                                       else " · _giveaway entry, excluded from metrics_" if bool(row.get("is_contest", False)) else "")
                                st.markdown(f"**{row.get('author') or 'anon'}** · 👍 {int(row['likes_display'])} · sentiment: {row['sentiment']}{tag}")
                                st.write(row["text_display"])
                                st.divider()
                            if len(bc) > 50:
                                st.caption(f"Top 50 of {len(bc)} comments.")
