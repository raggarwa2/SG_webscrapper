"""
Brand & market: how does Acuvue stand against its peers, and what is the market talking about?

Now only the Brand voice section is rendered (inside Brand Health); position, channels and demand live elsewhere. One page for what used to be Brand Health, Conversation & content and Themes & channels. Everything reads voice_data (one item
table, one tagger), so every channel is on the same scale. Only the consumer-voice lens compares brands; category voice, brands'
own posts and search demand are read beside it, never pooled with it.

Order (Pyramid Principle): the answer card, then 1 Position, 2 Channels, 3 Themes, 4 Brand voice, 5 Demand, then collapsed
supporting data. Charts are shown; tables and verbatims sit behind a click.
"""


import pandas as pd
import plotly.graph_objects as go
import streamlit as st

import charts
import ebi
import theme_tags
import ui
import voice_data as vd
from sg_common import BRAND_COLORS

FOCAL = vd.FOCAL
PEER_GREY = "#9AA5B1"
CAT_COLOR = "#6B7A90"
CONTENT_ORDER = ["promo", "education_news", "giveaway_spam", "experience", "opinion", "question", "other"]
CONTENT_LABEL = {"promo": "Promotion", "education_news": "Education / news", "giveaway_spam": "Giveaway / spam",
                 "experience": "Own experience", "opinion": "Opinion", "question": "Question", "other": "Other"}
CONTENT_COLOR = {"promo": "#B7791F", "education_news": "#59A5D7", "giveaway_spam": "#9AA5B1", "experience": "#168012",
                 "opinion": "#0B3556", "question": "#7048E8", "other": "#D5DBE1"}


def _theme_share(d: pd.DataFrame) -> dict:
    """{theme or NO_THEME: % of the rows that carry it}; an item with two themes counts under both."""
    n = len(d)
    out = {t: d["themes"].map(lambda ts: t in ts).mean() * 100 for t in theme_tags.THEMES}
    out[vd.NO_THEME] = d["themes"].map(len).eq(0).mean() * 100 if n else None
    return out


def _pts(v) -> str:
    return f"{ebi.sgn(v)}"


@st.cache_data(ttl=600, show_spinner=False, max_entries=2)
def _facts(m_items: float, m_tags: float) -> dict:
    return _build_facts(vd.load())


def facts(d: pd.DataFrame) -> dict:
    """Numbers the page, the Answer card and the header strip share, so they can never disagree (cached on the table timestamps)."""
    return _facts(vd.VOICE_DB.stat().st_mtime, vd.TAG_DB.stat().st_mtime) if len(d) else _build_facts(d)


def _build_facts(d: pd.DataFrame) -> dict:
    p = vd.pool(d)
    f_all, o_all = p[p["brand_std"] == FOCAL], p[p["brand_std"] != FOCAL]
    out = {"pool": p, "n_f": len(f_all), "n_p": len(o_all)}
    out["pooled_gap"] = vd.gap(f_all["sentiment"], o_all["sentiment"]) if len(f_all) and len(o_all) else {}
    out["std"] = vd.standardised(p)
    g = out["std"] or out["pooled_gap"]
    out["read"] = g
    if g:
        out["verdict"] = "level with peers" if g["lo"] <= 0 <= g["hi"] else ("ahead of peers" if g["gap"] > 0 else "behind peers")
    else:
        out["verdict"] = "not readable"
    out["channels"] = vd.channel_gaps(p)
    out["groups"] = vd.group_table(p)
    out["category"] = vd.category(d)
    out["own"] = vd.own_posts(d)
    return out


def _net_dots(bn: pd.DataFrame, ref: float | None) -> go.Figure:
    fig = go.Figure()
    labels = {r.brand: charts.row_label(r.brand, int(r.n)) for r in bn.itertuples()}
    for r in bn.itertuples():
        col = BRAND_COLORS.get(r.brand, "#178197")
        if r.net is None or pd.isna(r.net):
            continue
        fig.add_trace(go.Scatter(x=[r.lo, r.hi], y=[labels[r.brand]] * 2, mode="lines", line=dict(color=col, width=7), opacity=0.35,
                                 showlegend=False, hoverinfo="skip"))
        fig.add_trace(go.Scatter(x=[r.net], y=[labels[r.brand]], mode="markers", marker=dict(size=14, color=col), showlegend=False,
                                 customdata=[[r.brand]],
                                 hovertemplate=f"{r.brand}: net %{{x:+.0f}} (95% interval {ebi.sgn(r.lo)} to {ebi.sgn(r.hi)}, n={int(r.n)})<extra></extra>"))
        fig.add_trace(go.Scatter(x=[r.hi], y=[labels[r.brand]], mode="text", text=[f"<b>{ebi.sgn(r.net)}</b>"], textposition="middle right",
                                 textfont=dict(size=12, color="#191919"), showlegend=False, hoverinfo="skip"))
    if ref is not None:
        fig.add_vline(x=ref, line=dict(color="#64748B", width=1.5, dash="dash"))
    fig.update_xaxes(zeroline=True, zerolinecolor="#CBD5E1", range=[min(-5, bn["lo"].min() - 8 if bn["lo"].notna().any() else -5), 100],
                     title="Net sentiment (% positive minus % negative), all channels pooled, 95% interval"
                           + (f"<br><span style='font-size:11px;color:#64748B'>dashed line = peers pooled ({ebi.sgn(ref)})</span>" if ref is not None else ""))
    fig.update_yaxes(title="", categoryorder="array", categoryarray=[labels[b] for b in bn["brand"]], range=[len(bn) - 0.5, -0.5])
    fig.update_layout(height=120 + 52 * len(bn))
    return fig


def channel_phrase(clear: pd.DataFrame) -> str:
    """Every channel whose gap passes the checks, behind first: 'behind on KiasuParents (−48 pts) and YouTube (−36 pts), ahead on Xiaohongshu comments (+31 pts)'."""
    def names(df):
        items = [f"{r.channel} ({ebi.pts(r.gap)})" for r in df.sort_values("gap").itertuples()]
        return items[0] if len(items) == 1 else ", ".join(items[:-1]) + " and " + items[-1]
    behind, ahead = clear[clear["gap"] < 0], clear[clear["gap"] > 0]
    parts = ([f"behind on {names(behind)}"] if len(behind) else []) + ([f"ahead on {names(ahead)}"] if len(ahead) else [])
    return ", ".join(parts)


def render(d: pd.DataFrame) -> None:
    """Brand voice only: what brands post. Position, channel gaps and demand sit on their own pages."""
    if d.empty:
        st.info("Run Scripts/build_voice_items.py and Scripts/tag_voice_items.py to build the tables this page reads.")
        return
    own = facts(d)["own"]
    own_f = own[own["owner_brand"] == FOCAL]
    brands_own = [b for b in charts.BRAND_ORDER if (own["owner_brand"] == b).sum() >= ebi.MIN_N]
    share = {b: (own[own["owner_brand"] == b]["content_type"] == "promo").mean() * 100 for b in brands_own}
    promo = share.get(FOCAL)
    peers = {b: v for b, v in share.items() if b != FOCAL}

    p = facts(d)["pool"]
    cons_f = p[p["brand_std"] == FOCAL]
    can_cmp = len(own_f) >= ebi.MIN_N and len(cons_f) >= ebi.MIN_N
    os_, cs_ = (_theme_share(own_f), _theme_share(cons_f)) if can_cmp else ({}, {})
    themes = sorted(theme_tags.THEMES, key=lambda k: -cs_[k]) if can_cmp else []
    top = themes[0] if themes else None
    if promo is None:
        title, claim = "What brands post", "Content type of brands' own posts."
    else:
        lo, hi = (min(peers.values()), max(peers.values())) if peers else (None, None)
        rank = (f"the most promotional of the brands read (peers {lo:.0f}% to {hi:.0f}%)" if peers and promo > hi else
                f"the least promotional of the brands read (peers {lo:.0f}% to {hi:.0f}%)" if peers and promo < lo else
                f"in line with peers ({lo:.0f}% to {hi:.0f}%)" if peers else "")
        title = f"{FOCAL}'s own posts are {promo:.0f}% promotion" + (f"; consumers talk about {top.lower()}" if top else "")
        claim = f"{promo:.0f}% of {FOCAL}'s own posts are promotions" + (f"; {rank}." if rank else ".")
    ui.section(title, "Own posts by content type, and the topics posted vs the topics consumers raise.", "Brand voice", kind="fact")
    c1, c2 = st.columns(2)
    with c1:
        if brands_own:
            fv = go.Figure()
            for ct in CONTENT_ORDER:
                fv.add_bar(y=[charts.row_label(b, int((own["owner_brand"] == b).sum())) for b in brands_own],
                           x=[(own[own["owner_brand"] == b]["content_type"] == ct).mean() * 100 for b in brands_own], orientation="h",
                           name=CONTENT_LABEL[ct], marker_color=CONTENT_COLOR[ct])
            fv.update_layout(barmode="stack", height=90 + 60 * len(brands_own), legend=dict(orientation="h", y=-0.35, traceorder="normal"),
                             xaxis=dict(range=[0, 100], title="% of posts"))
            fv.update_yaxes(autorange="reversed")
            small = [b for b in charts.BRAND_ORDER if 0 < (own["owner_brand"] == b).sum() < ebi.MIN_N]
            ui.plot(fv, claim, key="bm_voice",
                    note=("Under 15 posts, left out: " + ", ".join(f"{b} ({int((own['owner_brand'] == b).sum())})" for b in small) + ".") if small else "",
                    bases={b: int((own["owner_brand"] == b).sum()) for b in brands_own}, noun="own posts")
        else:
            st.caption("No brand has 15+ own posts.")
    with c2:
        if can_cmp:
            keys = themes + [vd.NO_THEME]
            fm = go.Figure()
            fm.add_bar(y=keys, x=[os_[k] for k in keys], orientation="h", name=f"{FOCAL} own posts", marker_color="#B7791F",
                       text=[f"{os_[k]:.0f}%" for k in keys], textposition="outside", cliponaxis=False)
            fm.add_bar(y=keys, x=[cs_[k] for k in keys], orientation="h", name=f"Consumers on {FOCAL}", marker_color=BRAND_COLORS[FOCAL],
                       text=[f"{cs_[k]:.0f}%" for k in keys], textposition="outside", cliponaxis=False)
            fm.update_layout(barmode="group", height=350, xaxis_title="% of items that touch the theme", legend=dict(orientation="h", y=-0.3, traceorder="normal"))
            fm.update_xaxes(range=[0, max(max(os_[k] for k in keys), max(cs_[k] for k in keys)) * 1.25])
            fm.update_yaxes(autorange="reversed")
            ui.plot(fm, f"Consumers raise {top} in {cs_[top]:.0f}% of their items; {FOCAL} posts about it in {os_[top]:.0f}% of its posts.", key="bm_gap",
                    note="Promo posts carry no theme: this shows what is posted, not a missed message.",
                    bases={f"{FOCAL} own posts": len(own_f), f"Consumers on {FOCAL}": len(cons_f)}, noun="items")
