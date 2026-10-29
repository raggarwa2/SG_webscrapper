"""Facebook signals (SG) — fb_posts / fb_comments in facebook_data_sg.db (brand pages; no Alcon page).

The brand pages draw almost no comments (most are giveaway entries), so this tab reads what the pages post and how people react,
not tone: likes per post, posting activity, the comments funnel, and the comments that count."""

import sqlite3

import pandas as pd
import plotly.express as px
import streamlit as st

import _social
import palette
import ui
import voice_data
from sg_common import FB_DB

CFG = _social.Platform(
    key="facebook", label="Facebook", db_path=FB_DB,
    posts_table="fb_posts", comments_table="fb_comments",
    post_id="post_id",
    extra_post_filters=["market_relevant"],  # olensglobal is a global (non-SG) Page
    title_cols=["text"], text_cols=["text"],
    date_col="published_at", url_col="url", channel_col="page",
    metric_cols={"Total likes": "likes_count", "Total shares": "shares_count"},
    comment_text_cols=["comment_text"],
    comment_like_col="like_count", comment_date_col="published_at",
    caveat="Brand-page posts plus public comments (no Alcon SG page). Posts are marketing; only comments carry consumer sentiment.",
)


def load_sg_dashboard_data():
    """(posts, comments, excluded_posts) — see _social.load_data."""
    return _social.load_data(CFG)


def on_topic_comments(comments):
    return _social.on_topic(comments)


def purchase_barrier_rate(on_topic_df):
    return _social.purchase_barrier_rate(on_topic_df)


def get_monthly_comment_counts(brand):
    return _social.monthly_counts(CFG, brand)


def _order(brands) -> list:
    return sorted(brands, key=lambda b: (b != voice_data.FOCAL, b))


def _colors(brands) -> dict:
    return {b: (palette.BRAND_COLORS["Acuvue"] if b == voice_data.FOCAL else palette.PEER_GREY) for b in brands}


@st.cache_data(show_spinner=False, ttl=600, max_entries=2)
def _fb_comments(mtime: float) -> pd.DataFrame:
    """Every Facebook brand-page comment in voice_items (tagged or not), so the funnel counts what was removed too."""
    con = sqlite3.connect(f"file:{voice_data.VOICE_DB.as_posix()}?mode=ro", uri=True)
    d = pd.read_sql_query("SELECT brand_std, text_en, text_orig, date, is_contest, lens_relevant, in_pool FROM voice_items "
                          "WHERE source = 'Facebook' AND unit = 'comment' AND brand_std != 'Olens'", con)
    con.close()
    d["text"] = d["text_en"].fillna("").where(d["text_en"].fillna("").str.len() > 0, d["text_orig"].fillna(""))
    d["date"] = pd.to_datetime(d["date"], errors="coerce")
    return d


def _likes_section(posts: pd.DataFrame) -> None:
    brands = _order(posts["brand"].dropna().unique())
    likes = pd.to_numeric(posts["likes_count"], errors="coerce")
    g = posts.assign(_l=likes).groupby("brand")["_l"].agg(avg="mean", n="size", zero=lambda s: int((s == 0).sum()), top="max")
    g = g.reindex(brands)
    f = voice_data.FOCAL
    peers = [b for b in brands if b != f]
    if f in g.index and peers:
        say = (f"{f} averages {g.loc[f, 'avg']:.1f} likes per post; "
               + ", ".join(f"{b} {g.loc[b, 'avg']:.1f}" for b in peers) + f" ({int(g['n'].min())} posts each)." if g["n"].nunique() == 1 else ".")
    else:
        say = ""
    ui.section(f"{f}'s page earns about a tenth of the likes per post that its peers' pages get" if f in g.index and peers
               and g.loc[f, "avg"] * 5 < g.loc[peers, "avg"].min() else "Average likes per post, by brand page",
               "Average likes per post on each brand's own Facebook page", "Page engagement", kind="fact", logos=["Facebook"])
    d = g.reset_index().rename(columns={"index": "brand"})
    fig = px.bar(d, x="avg", y="brand", orientation="h", color="brand", color_discrete_map=_colors(brands),
                 category_orders={"brand": brands}, text=d["avg"].map(lambda v: f"{v:.1f}"),
                 labels={"avg": "Average likes per post", "brand": ""})
    fig.update_layout(showlegend=False, yaxis=dict(autorange="reversed"))
    fig.update_traces(textposition="outside", cliponaxis=False)
    fig.update_yaxes(tickvals=brands, ticktext=[f"<b>{b}</b>" if b == f else b for b in brands])
    ui.plot(fig, say, "fact", "Likes only: the scraper does not return shares or comment counts. Olens (global page) left out.",
            height=200, bases=_social._strip("Posts", {b: int(g.loc[b, "n"]) for b in brands}))
    tbl = d.assign(avg=d["avg"].round(1)).rename(columns={"brand": "Brand", "avg": "Average likes", "n": "Posts",
                                                          "zero": "Posts with 0 likes", "top": "Most likes on one post"})
    ui.show_data("Table: likes per post by brand · Facebook brand pages", tbl)


def _activity_section(posts: pd.DataFrame) -> None:
    brands = _order(posts["brand"].dropna().unique())
    f = voice_data.FOCAL
    p = posts.assign(year=posts["date"].dt.year).dropna(subset=["year"])
    p["year"] = p["year"].astype(int)
    first = int(p["year"].max()) - 3
    older = int((p["year"] < first).sum())
    p = p[p["year"] >= first]
    c = p.groupby(["year", "brand"]).size().rename("posts").reset_index()
    latest = int(p["year"].max())
    now = c[c["year"] == latest].set_index("brand")["posts"].reindex(brands).fillna(0).astype(int)
    last = p.groupby("brand")["date"].max()
    ui.section("Posting activity by year: how recent each page's last 100 posts reach",
               "Posts per year in the collected window (activity, not tone)", "Posting activity", kind="fact", logos=["Facebook"])
    quiet = [b for b in brands if now[b] <= 1]
    say = f"{f} posted {now.get(f, 0)} times in {latest}; " + ", ".join(f"{b} {now[b]}" for b in brands if b != f) + "."
    if quiet:
        say += " " + ", ".join(f"{b}'s latest post is {last[b]:%b %Y}" for b in quiet) + "."
    fig = px.bar(c, x="year", y="posts", color="brand", barmode="group", color_discrete_map=palette.BRAND_COLORS,
                 category_orders={"brand": brands, "year": list(range(first, latest + 1))}, text="posts",
                 labels={"posts": "Posts", "year": "Year"})
    fig.update_layout(legend=dict(orientation="h", y=1.02, yanchor="bottom", x=0, title_text=""))
    fig.update_xaxes(type="category")
    fig.update_traces(textposition="outside", cliponaxis=False)
    ui.plot(fig, say, "fact", (f"{older} older posts (before {first}) not drawn." if older else ""), height=280,
            bases=_social._strip("Posts", _social._counts(posts, brands)))


FUNNEL = [("Giveaway or spam, removed", palette.PEER_GREY), ("Off-topic or no brand, removed", palette.LOW_GREY),
          ("Counted", palette.CHANNEL_COLORS["Facebook"])]


def _funnel(items: pd.DataFrame, brands: list) -> pd.DataFrame:
    """Per brand: comments collected, giveaway entries, other removals, counted (the brand pool). One bucket per comment."""
    rows = []
    for b in brands:
        d = items[items["brand_std"] == b]
        contest = d["is_contest"] == 1
        pooled = d["in_pool"] == 1
        rows.append({"brand": b, "collected": len(d), FUNNEL[0][0]: int(contest.sum()),
                     FUNNEL[1][0]: int((~contest & ~pooled).sum()), FUNNEL[2][0]: int((~contest & pooled).sum())})
    return pd.DataFrame(rows)


def _comments_section(items: pd.DataFrame) -> None:
    f = voice_data.FOCAL
    if items.empty:
        return
    brands = _order(items["brand_std"].dropna().unique())
    fn = _funnel(items, brands)
    tot, kept = int(fn["collected"].sum()), int(fn[FUNNEL[2][0]].sum())
    ui.section(f"{tot} comments collected on the brand pages, {kept} left once giveaways and off-topic are removed",
               "Comments on brand posts: collected, then what was removed (one bucket per comment)", "Comments", kind="fact", logos=["Facebook"])
    long = fn.melt(id_vars=["brand", "collected"], value_vars=[n for n, _ in FUNNEL], var_name="what", value_name="n")
    fig = px.bar(long, x="n", y="brand", color="what", orientation="h", barmode="stack", color_discrete_map=dict(FUNNEL),
                 category_orders={"brand": brands, "what": [n for n, _ in FUNNEL]}, text=long["n"].map(lambda v: str(v) if v else ""),
                 labels={"n": "Comments", "brand": ""})
    fig.update_layout(legend=dict(orientation="h", y=1.02, yanchor="bottom", x=0, title_text=""), yaxis=dict(autorange="reversed"))
    fig.update_yaxes(tickvals=brands, ticktext=[f"<b>{b}</b>" if b == f else b for b in brands])
    r = fn.set_index("brand")
    biggest = r["collected"].idxmax()
    say = (f"{biggest}: {r.loc[biggest, 'collected']} collected, {r.loc[biggest, FUNNEL[0][0]]} giveaway entries, "
           f"{r.loc[biggest, FUNNEL[2][0]]} counted. {f}: {r.loc[f, FUNNEL[2][0]]} counted, under the {_social.ebi.MIN_N}-item minimum, so no tone is shown."
           if f in r.index else "")
    ui.plot(fig, say, "fact", "Counted comments are the brand pool; one Bausch & Lomb complaint appears three times in it (not de-duplicated).",
            height=240, bases=_social._strip("Collected", r["collected"].to_dict()), noun="comments")
    ui.show_data("Table: comments collected, removed and counted by brand · Facebook brand pages",
                 fn.rename(columns={"brand": "Brand", "collected": "Collected"}))


def _read_section(items: pd.DataFrame) -> None:
    items = items[(items["is_contest"] != 1) & (items["in_pool"] == 1)]
    if items.empty:
        return
    ui.section("What people wrote on the brand pages",
               "Counted comments, newest first; a comment posted more than once is shown once with its count", "Comment verbatims", kind="fact", logos=["Facebook"])
    d = items.assign(Comment=items["text"], Brand=items["brand_std"], Date=items["date"].dt.strftime("%Y-%m-%d"))
    g = (d.groupby(["Brand", "Comment"], as_index=False).agg(Date=("Date", "max"), Posted=("Date", "size"))
         .sort_values("Date", ascending=False))
    ui.tlabel("counted comments · Facebook brand pages, Singapore")
    with st.expander(f"Read the {len(g)} comments", expanded=len(g) > ui.FEW_ROWS):
        st.dataframe(g[["Date", "Brand", "Comment", "Posted"]], hide_index=True, width="stretch",
                     column_config={"Comment": st.column_config.TextColumn(width="large"),
                                    "Posted": st.column_config.NumberColumn("Times posted", width="small")})
    st.caption("Shown as written. Whether the brand replied is not captured by the scraper.")


def render():
    if not FB_DB or not _social.os.path.exists(FB_DB):
        st.info(f"No Facebook data found at `{FB_DB}`.")
        return
    posts, _comments, _excluded = _social.load_data(CFG)
    if posts.empty:
        st.info("No Facebook posts loaded yet.")
        return
    st.markdown(f'<div class="caveat-box">{CFG.caveat}</div>', unsafe_allow_html=True)
    _likes_section(posts)
    _activity_section(posts)
    if voice_data.VOICE_DB.exists():
        items = _fb_comments(voice_data.VOICE_DB.stat().st_mtime + voice_data.stamp())
        _comments_section(items)
        _read_section(items)
    ui.goto("Retail & Promotions", "Facebook ads, retailer posts and reviews: Retail & Promotions",
            key="fb_to_retail", sub="Retailers & Promotions (Facebook)", sub_key="retail_subtabs")
