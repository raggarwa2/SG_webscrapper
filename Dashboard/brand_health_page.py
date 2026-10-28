"""
Brand Health, laid out like the HK dashboard: a method box, "All Brands Overview" (one card per brand and a ranking chart),
then "Brand Deep-Dive" (a trend, one focus brand's score by channel, why its customers hesitate, demand). The score is
HK's balanced composite on SG's one tagged pool: per channel, % positive or neutral (mixed stays in the base); then the mean
over the social channels with 15+ items (ebi.MIN_N), weighted by sqrt(n); 0-100, healthy 65+, mixed 45-64, at risk below 45.
Lazada reviews (three brands only, near-uniformly positive) and KiasuParents (2023) are shown beside the score, not in it.
No rank is claimed: the "Acuvue by channel" read and the tested gaps below carry the evidence, on net sentiment.
"""

import pandas as pd
import plotly.graph_objects as go
import streamlit as st

import brand_market_page
import charts
import ebi
import insights
import ui
import voice_data as vd
from sg_common import BRAND_COLORS

CHANNEL_GROUP = {"Xiaohongshu comments": "Xiaohongshu"}   # posts and comments of one channel read as one column
HESITATE_CHANNELS = ["Xiaohongshu", "Reddit", "YouTube", "Instagram"]
SCORE_CHANNELS = ["Xiaohongshu", "Reddit", "YouTube", "Instagram", "Facebook"]   # like-for-like across brands; the score blends only these
REFERENCE_CHANNELS = ["Lazada reviews", "KiasuParents"]   # shown beside the score: retail on 3 brands, and 2023 forum data
MIN_CH = ebi.MIN_N


def _prep(d: pd.DataFrame, brands: list) -> pd.DataFrame:
    p = vd.pool(d)
    p = p[p["brand_std"].isin(brands)].copy()
    p["channel"] = p["source"].replace(CHANNEL_GROUP)
    return p


def _pos_neu(s: pd.Series) -> float:
    """% of labelled items that are positive or neutral (mixed and negative stay in the base)."""
    return float(s.isin(["positive", "neutral"]).mean() * 100)


def _blend(parts: list) -> float | None:
    """sqrt(n)-weighted mean of [(pct, n)]; None when empty."""
    if not parts:
        return None
    w = [n ** 0.5 for _, n in parts]
    return sum(pct * wi for (pct, _), wi in zip(parts, w)) / sum(w)


def _scores(p: pd.DataFrame, brand: str) -> dict:
    """HK's balanced score: channels under 15 items are shown with their count only; reference channels are shown but not blended."""
    pb = p[p["brand_std"] == brand]
    chans = []
    for ch in [c for c in dict.fromkeys(p["channel"]) if c in set(pb["channel"])]:
        s = pb.loc[pb["channel"] == ch, "sentiment"]
        chans.append((ch, _pos_neu(s) if len(s) >= MIN_CH else None, len(s)))
    return {"score": _blend([(v, n) for c, v, n in chans if v is not None and c in SCORE_CHANNELS]), "n": len(pb), "channels": chans}


def _card(brand: str, sc: dict) -> str:
    col = BRAND_COLORS.get(brand, "#2563eb")
    head = f'<div style="color:{col};font-weight:700;font-size:0.85rem;letter-spacing:0.07em;text-transform:uppercase;">{brand}</div>'
    if sc["score"] is None:
        body = (f'<div style="color:#888;font-size:0.82rem;margin-top:10px;">Too few items to score: {sc["n"]} brand-named, '
                f'no social channel with {MIN_CH}+</div>')
    else:
        score = sc["score"]
        tone = "#16a34a" if score >= 65 else ("#e8a33d" if score >= 45 else "#dc2626")
        shown = " · ".join(f"{ch} {v:.0f}% (n={n})" for ch, v, n in sc["channels"] if v is not None and ch in SCORE_CHANNELS)
        thin = ", ".join(ch for ch, v, _ in sc["channels"] if v is None and ch in SCORE_CHANNELS)
        body = (f'<div style="font-size:2rem;font-weight:800;color:{tone};margin:6px 0;">{score:.0f}'
                f'<span style="font-size:0.8rem;font-weight:600;margin-left:8px;">{insights.band(score)}</span></div>'
                f'<div style="color:#555;font-size:0.78rem;">{shown}</div>'
                f'<div style="color:#aaa;font-size:0.72rem;margin-top:4px;">{"under " + str(MIN_CH) + ": " + thin if thin else "&nbsp;"}</div>')
    return (f'<div style="background:#f8f9fb;border:1px solid #e6e6e6;border-radius:12px;padding:16px 20px;margin-bottom:14px;'
            f'min-height:150px;">{head}{body}</div>')


def trend_table(p: pd.DataFrame, brands: list, grain: str) -> pd.DataFrame:
    """Composite per brand and period: % positive or neutral per social channel, blended by sqrt(n); columns Brand, month, pct, n."""
    p = p[p["channel"].isin(SCORE_CHANNELS)].dropna(subset=["date"]).copy()
    p["period"] = {"Month": p["date"].dt.to_period("M"), "Quarter": p["date"].dt.to_period("Q"), "Year": p["date"].dt.to_period("Y")}[grain].astype(str)
    rows = []
    for (b, per), g in p[p["brand_std"].isin(brands)].groupby(["brand_std", "period"]):
        parts = [(_pos_neu(c["sentiment"]), len(c)) for _, c in g.groupby("channel")]
        rows.append({"Brand": b, "month": per, "pct": _blend(parts), "n": len(g)})
    return pd.DataFrame(rows, columns=["Brand", "month", "pct", "n"])


def _trend(p: pd.DataFrame, brands: list) -> None:
    grain = st.radio("Group by", ["Month", "Quarter", "Year"], index=2, horizontal=True, key="brand_health_trend_grain")
    t = trend_table(p, brands, grain)
    dropped = int((t["n"] < MIN_CH).sum())
    t = t[t["n"] >= MIN_CH]
    if t.empty:
        st.info(f"No {grain.lower()} has {MIN_CH}+ dated items for the selected brands. Try a longer period.")
        return
    fig = charts.trend_lines(t, charts.order_brands(t["Brand"].unique()), height=340)
    fig.update_layout(title=f"Brand comparison: % positive or neutral by {grain.lower()}")
    st.plotly_chart(fig, width="stretch")
    ui.n_strip({b: int(t.loc[t["Brand"] == b, "n"].sum()) for b in charts.order_brands(t["Brand"].unique())}, "dated items", attached=True)
    st.caption(f"Each point blends the channels with dated items that {grain.lower()}, weighted by √n. A {grain.lower()} is drawn only with {MIN_CH}+ "
               f"dated items ({dropped} thinner ones are left out), because a single comment can swing a small point to 0% or 100%. Only the social "
               "channels are in the trend; Lazada, KiasuParents and undated Xiaohongshu comments are not.")


def _hesitate(p: pd.DataFrame, brand: str) -> None:
    comp = vd.complaints(p[p["brand_std"] == brand])
    st.markdown("**Why customers hesitate: complaints by channel**")
    if comp.empty:
        st.info(f"No complaints (negative or mixed on a theme) found for {brand}.")
        return
    pb = p[p["item_id"].isin(comp["item_id"])]
    cols = st.columns(len(HESITATE_CHANNELS))
    for col, ch in zip(cols, HESITATE_CHANNELS):
        with col:
            sub = pb[pb["channel"] == ch]
            st.caption(f"{ch}: negative or mixed on a theme ({len(sub)})")
            if sub.empty:
                st.info("None found.")
                continue
            v = vd.view(sub)[["Date", "Themes", "Text", "Link"]]
            st.dataframe(v, hide_index=True, width="stretch", height=250, column_config=vd.LINK_CFG)
    others = int((~pb["channel"].isin(HESITATE_CHANNELS)).sum())
    if others:
        st.caption(f"{others} more complaints sit on other channels (Lazada reviews, KiasuParents, Facebook); see the Data explorer.")


def _ranking(rank: pd.DataFrame, scores: dict, p: pd.DataFrame) -> None:
    """One dot per brand on a 0-100 scale: the focal brand in colour, peers in grey, the title says what the chart shows."""
    rank = rank.sort_values("Balanced score", ascending=True)   # plotly draws bottom-up: best brand on top
    lo, hi = rank["Balanced score"].min(), rank["Balanced score"].max()
    healthy = bool((rank["Balanced score"] >= 65).all())
    title = (f"All brands read healthy: scores span {lo:.0f} to {hi:.0f}" if healthy else f"Balanced scores span {lo:.0f} to {hi:.0f}")
    g = vd.standardised(p[p["channel"].isin(SCORE_CHANNELS)].assign(source=lambda x: x["channel"]), min_n=MIN_CH)
    if g:   # the rank is not claimed: say what the tested, channel-weighted gap supports
        verdict = ("level with peers" if g["lo"] <= 0 <= g["hi"] else ("ahead of peers" if g["gap"] > 0 else "behind peers"))
        title += f"; Acuvue is {verdict} on net sentiment ({ebi.sgn(g['gap'])} pts, interval {ebi.sgn(g['lo'])} to {ebi.sgn(g['hi'])})"
    fig = go.Figure()
    fig.add_vrect(x0=65, x1=100, fillcolor="#16a34a", opacity=0.08, line_width=0, layer="below")
    fig.add_vrect(x0=45, x1=65, fillcolor="#f59e0b", opacity=0.08, line_width=0, layer="below")
    fig.add_annotation(x=82.5, y=1.0, yref="paper", text="Healthy (65+)", showarrow=False, yanchor="bottom", font=dict(size=12, color="#15803d"))
    fig.add_annotation(x=55, y=1.0, yref="paper", text="Mixed (45-64)", showarrow=False, yanchor="bottom", font=dict(size=12, color="#b45309"))
    colors = [BRAND_COLORS.get(b, "#2563eb") if b == "Acuvue" else "#94a3b8" for b in rank["Brand"]]
    names = list(rank["Brand"])
    if "Acuvue" in names:   # focal brand: tinted row, bold label and score, brand colour on the dot
        i = names.index("Acuvue")
        fig.add_hrect(y0=i - 0.5, y1=i + 0.5, fillcolor=BRAND_COLORS.get("Acuvue", "#2563eb"), opacity=0.12, line_width=0, layer="below")
    for b, v in zip(rank["Brand"], rank["Balanced score"]):   # the stem from the axis to each dot
        fig.add_shape(type="line", x0=40, x1=v, y0=b, y1=b, line=dict(color="#cbd5e1", width=2), layer="below")
    fig.add_trace(go.Scatter(
        x=rank["Balanced score"], y=rank["Brand"], mode="markers+text", text=[f"<b>{v:.0f}</b>" if b == "Acuvue" else f"{v:.0f}" for b, v in zip(rank["Brand"], rank["Balanced score"])], textposition="middle right",
        textfont=dict(size=16), cliponaxis=False, marker=dict(size=22, color=colors, line=dict(width=2, color="white")),
        hovertemplate="%{y}: balanced score %{x:.0f}<extra></extra>", showlegend=False))
    fig.update_layout(title=dict(text=title, font=dict(size=18)), height=48 * len(rank) + 130, margin=dict(l=10, r=30, t=80, b=10))
    fig.update_xaxes(range=[40, 100], title="Balanced score (0-100)", showgrid=False)
    fig.update_yaxes(title=None, tickfont=dict(size=14), tickmode="array", tickvals=names, ticktext=[f"<b>{b}</b>" if b == "Acuvue" else b for b in names])
    st.plotly_chart(fig, width="stretch")


def _channel_heatmap(rank: pd.DataFrame, scores: dict) -> None:
    """Where each score comes from: % positive or neutral per brand and channel, with the item count in each cell."""
    labels = SCORE_CHANNELS + REFERENCE_CHANNELS
    brands = list(rank.sort_values("Balanced score", ascending=False)["Brand"])
    z, txt = [], []
    for b in brands:
        ch = {c: (v, n) for c, v, n in scores[b]["channels"]}
        zr, tr = [], []
        for c in labels:
            v, n = ch.get(c, (None, 0))
            zr.append(v)
            tr.append(f"{v:.0f}%<br><span style='font-size:10px'>n={n}</span>" if v is not None else (f"n={n}" if n else ""))
        z.append(zr)
        txt.append(tr)
    fig = go.Figure(go.Heatmap(z=z, x=labels, y=brands, text=txt, texttemplate="%{text}", zmin=40, zmax=100, xgap=3, ygap=3,
                               colorscale=[[0, "#fca5a5"], [0.5, "#fde68a"], [1, "#86efac"]], showscale=False,
                               hovertemplate="%{y} on %{x}<extra></extra>"))
    fig.update_layout(title=dict(text="Where each score comes from: % positive or neutral by channel", font=dict(size=15)),
                      height=46 * len(brands) + 110, margin=dict(l=10, r=10, t=60, b=10), plot_bgcolor="rgba(0,0,0,0)")
    fig.update_xaxes(side="top", showgrid=False, ticktext=labels[:len(SCORE_CHANNELS)] + [f"{c} (not in score)" for c in REFERENCE_CHANNELS], tickvals=labels)
    fig.update_yaxes(autorange="reversed", showgrid=False)
    st.plotly_chart(fig, width="stretch")
    st.caption(f"Blank cells: the brand has no items there. Cells showing only a count have under {MIN_CH} items, so no percentage "
               "is shown. Lazada reviews cover three brands and are near-uniformly positive, and KiasuParents is 2023 forum data, so both sit "
               "beside the score, not in it.")


def _channel_read(p: pd.DataFrame) -> None:
    """Acuvue's net sentiment against all peers, channel by channel, where both sides have 15+ items; the reading of the score."""
    rows = []
    for ch in SCORE_CHANNELS + REFERENCE_CHANNELS:
        a, o = p[(p["channel"] == ch) & (p["brand_std"] == vd.FOCAL)], p[(p["channel"] == ch) & (p["brand_std"] != vd.FOCAL)]
        if len(a) < MIN_CH or len(o) < MIN_CH:
            continue
        g = vd.gap(a["sentiment"], o["sentiment"])
        top = o["brand_std"].value_counts()
        rows.append({"Channel": ch, "Acuvue": g["net_f"], "Peers": g["net_p"], "Gap": g["gap"], "Low": g["lo"], "High": g["hi"], "n_a": g["n_f"], "n_p": g["n_p"],
                     "Main peer": f"{top.index[0]} ({top.iloc[0] / len(o) * 100:.0f}% of peer items)", "Real gap": "no" if g["lo"] <= 0 <= g["hi"] else "yes"})
    st.markdown("#### Acuvue by channel: where the sentiment holds and where it does not")
    if not rows:
        st.info("No channel has 15+ items for Acuvue and for peers.")
        return
    t = pd.DataFrame(rows)
    fig = go.Figure()
    fig.add_trace(go.Bar(name="Peers", x=t["Channel"], y=t["Peers"], marker_color="#94a3b8", text=[f"{v:+.0f}" for v in t["Peers"]], textposition="outside"))
    fig.add_trace(go.Bar(name="Acuvue", x=t["Channel"], y=t["Acuvue"], marker_color=BRAND_COLORS.get("Acuvue", "#2563eb"),
                         text=[f"<b>{v:+.0f}</b>" for v in t["Acuvue"]], textposition="outside"))
    fig.update_layout(barmode="group", height=340, yaxis_title="Net sentiment (% positive minus % negative)", margin=dict(t=30),
                      legend=dict(orientation="h", y=1.1))
    fig.update_xaxes(ticktext=[c if c in SCORE_CHANNELS else f"{c} (not in score)" for c in t["Channel"]], tickvals=t["Channel"])
    soc = t[t["Channel"].isin(SCORE_CHANNELS)]
    best, worst = soc.loc[soc["Acuvue"].idxmax()], soc.loc[soc["Acuvue"].idxmin()]
    real = t[t["Real gap"] == "yes"]
    where = ", ".join(f"{r.Channel} ({'behind' if r.Gap < 0 else 'ahead'} by {abs(r.Gap):.0f} pts)" for r in real.itertuples())
    say = (f"Acuvue's net sentiment runs from {worst['Acuvue']:+.0f} on {worst['Channel']} to {best['Acuvue']:+.0f} on {best['Channel']} (social channels); "
           + (f"it differs from peers only on {where}" if len(real) else "it does not differ from peers on any channel") + ".")
    ui.plot(fig, say=say, kind="dir", bases="Acuvue / peer items: " + " · ".join(f"{r.Channel} {r.n_a} / {r.n_p}" for r in t.itertuples()), key="brand_health_channel_read")
    st.caption("Reading: the same brand scores higher where content is promoted or reviewed by creators (Xiaohongshu, Instagram, Lazada) than where people "
               "talk about their own use (Reddit, KiasuParents). That is a within-Acuvue contrast, so it needs no peer test. A YouTube gap is "
               "mostly Olens, a colour-lens brand with large channels, so read it as category, not as a lens-quality gap.")
    st.caption("The MyACUVUE app is rated separately, since it is Acuvue-only:")
    ui.goto("Journey & App", key="bh_to_journey_app")
    ui.show_data("Table: Acuvue vs peers by channel", t.assign(**{c: t[c].round(0) for c in ["Acuvue", "Peers", "Gap", "Low", "High"]})
                 .rename(columns={"Low": "Gap low (95%)", "High": "Gap high (95%)", "n_a": "Acuvue n", "n_p": "Peer n"}))


def render(d: pd.DataFrame, brands: list) -> None:
    st.subheader("Brand Health: balanced sentiment across reviews and social channels")
    if d.empty:
        st.info("Run Scripts/build_voice_items.py and Scripts/tag_voice_items.py to build the tables this page reads.")
        return
    st.info(
        "**How this score is built:** each brand gets one **balanced score (0-100)**. For each social channel (Xiaohongshu, Reddit, YouTube, "
        "Instagram, Facebook) take the share of comments, posts and reviews that name the brand and are "
        "about lenses and are positive or neutral (mixed and negative stay in the base), then average the channels weighted by √n. "
        f"A channel counts once it has **{MIN_CH}+ items**; under that it shows the count only. Healthy 65+, mixed 45-64, "
        "at risk below 45. Lazada reviews and KiasuParents are shown beside the score, not in it. Every channel is read by the same model tagger. Giveaway entries are removed. The tested gaps at the bottom "
        "use net sentiment (% positive minus % negative), so their numbers differ from this score by design."
    )
    p = _prep(d, brands)
    if p.empty:
        st.info("No brand-named items for the selected brands.")
        return

    st.markdown("#### All Brands Overview")
    scores = {b: _scores(p, b) for b in brands if b in set(p["brand_std"])}
    cols = st.columns(min(max(len(scores), 1), 5))
    for i, (b, sc) in enumerate(scores.items()):
        with cols[i % len(cols)]:
            st.markdown(_card(b, sc), unsafe_allow_html=True)
    rank = pd.DataFrame([{"Brand": b, "Balanced score": s["score"]} for b, s in scores.items() if s["score"] is not None])
    if not rank.empty:
        _ranking(rank, scores, p)
        _channel_heatmap(rank, scores)
        ui.n_strip({b: s["n"] for b, s in scores.items() if s["score"] is not None}, "pooled items", attached=True)
    _channel_read(p)

    st.divider()
    st.markdown("#### Brand Deep-Dive")
    dd = st.multiselect("Brands to compare", list(scores), default=list(scores), key="brand_health_deep_dive_compare")
    st.markdown("**Composite sentiment trend** (% positive or neutral)")
    if not dd:
        st.info("Select at least one brand to plot.")
        return
    _trend(p, dd)
    st.divider()

    focus = st.selectbox("Focus brand (for detail below)", dd, key="brand_health_focus_brand")
    sc = scores[focus]
    chans = {ch: (v, n) for ch, v, n in sc["channels"]}
    labels = SCORE_CHANNELS + REFERENCE_CHANNELS
    tiles = [("Balanced score", f"{sc['score']:.0f}" if sc["score"] is not None else f"n={sc['n']}",
              f"Channels with {insights.MIN_SOURCE_N}+ items blended by √n, n={sc['n']}.")]
    for ch in labels:
        v, n = chans.get(ch, (None, 0))
        tiles.append((ch, f"{v:.0f}%" if v is not None else "n/a",
                      f"% positive or neutral, n={n}" + ("" if v is not None else f" (under {insights.MIN_SOURCE_N})")))
    per_row = 4   # 8 tiles in one row cut the labels off; two rows of four keep them whole
    for i in range(0, len(tiles), per_row):
        for col, (label, value, hint) in zip(st.columns(per_row), tiles[i:i + per_row]):
            col.metric(label, value, help=hint, border=True)
    st.caption(f"Each figure is for **{focus} only**: the score is a 0-100 balance, the channel figures are % positive or neutral. The Social "
               "Signals tabs pool all brands on their All Brands view, so a different denominator.")
    _hesitate(p, focus)

    st.caption("Search interest is category-level, not per brand.")
    ui.goto("Trends & Demand", key="bh_to_trends")

    st.divider()
    st.markdown("#### Acuvue vs peers: tested gaps")
    brand_market_page.render(d)
    _pool = vd.pool(d)
    ui.read_comments(_pool[_pool["brand_std"].isin(brands)], "Read the brand comments behind this page (brand pool)", key="bh_read")
