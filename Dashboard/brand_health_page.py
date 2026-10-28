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
from sg_common import BRAND_COLORS, PEER_GREY

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


GRAINS = ["Rolling 3 months", "Quarter", "Year"]


def trend_table(p: pd.DataFrame, brands: list, grain: str) -> pd.DataFrame:
    """Composite per brand and period: % positive or neutral per social channel, blended by sqrt(n); columns Brand, month, pct, n.
    "Rolling 3 months": one point per month the brand has items, pooling that month and the two before it."""
    p = p[p["channel"].isin(SCORE_CHANNELS) & p["brand_std"].isin(brands)].dropna(subset=["date"]).copy()
    rows = []
    if grain == "Rolling 3 months":
        p["m"] = p["date"].dt.to_period("M")
        for b, gb in p.groupby("brand_std"):
            for m in sorted(gb["m"].unique()):
                g = gb[(gb["m"] <= m) & (gb["m"] >= m - 2)]
                parts = [(_pos_neu(c["sentiment"]), len(c)) for _, c in g.groupby("channel")]
                rows.append({"Brand": b, "month": str(m), "pct": _blend(parts), "n": len(g)})
        return pd.DataFrame(rows, columns=["Brand", "month", "pct", "n"])
    p["period"] = {"Quarter": p["date"].dt.to_period("Q"), "Year": p["date"].dt.to_period("Y")}[grain].astype(str)
    for (b, per), g in p.groupby(["brand_std", "period"]):
        parts = [(_pos_neu(c["sentiment"]), len(c)) for _, c in g.groupby("channel")]
        rows.append({"Brand": b, "month": per, "pct": _blend(parts), "n": len(g)})
    return pd.DataFrame(rows, columns=["Brand", "month", "pct", "n"])


def _trend(p: pd.DataFrame, brands: list) -> None:
    grain = st.radio("Group by", GRAINS, index=1, horizontal=True, key="brand_health_trend_grain")
    t = trend_table(p, brands, grain)
    if t.empty:
        st.info("No dated items for the selected brands.")
        return
    thin = int(t["n"].map(ebi.is_thin).sum())
    unit = "month (3-month window)" if grain == "Rolling 3 months" else grain.lower()
    fig = charts.trend_lines(t, charts.order_brands(t["Brand"].unique()), height=340)
    fig.update_layout(title=f"Brand comparison: % positive or neutral by {unit}")
    st.plotly_chart(fig, width="stretch")
    ui.n_strip(dict(p[p["channel"].isin(SCORE_CHANNELS) & p["date"].notna()].groupby("brand_std").size().reindex(
        charts.order_brands(t["Brand"].unique())).fillna(0).astype(int)), "dated items", attached=True)
    window = "the month and the two before it" if grain == "Rolling 3 months" else f"the {grain.lower()}"
    st.caption(f"Each point blends the channels with dated items in {window}, weighted by √n. **Exception to the 15-item rule, this chart only:** "
               f"points under {MIN_CH} items are kept and drawn hollow ({thin} of {len(t)}); read them as direction, since one comment can swing "
               "a small point to 0% or 100%. Only the social channels are in the trend; Lazada, KiasuParents and undated Xiaohongshu comments are not.")


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
    names = list(rank["Brand"])
    fig.add_vrect(x0=65, x1=100, fillcolor="#64748B", opacity=0.07, line_width=0, layer="below")   # one neutral band; the thresholds are dotted lines
    for x in (45, 65):
        fig.add_vline(x=x, line=dict(color="#94A3B8", width=1, dash="dot"), layer="below")
    for x, lab in ((82.5, "Healthy (65+)"), (55, "Mixed (45-64)")):
        fig.add_annotation(x=x, y=1.0, yref="paper", text=lab, showarrow=False, yanchor="top", font=dict(size=12, color="#475569"))
    colors = [BRAND_COLORS.get(b, "#178197") if b == "Acuvue" else PEER_GREY for b in names]
    if "Acuvue" in names:   # focal brand: tinted row, bold label and score, brand colour on the dot
        i = names.index("Acuvue")
        fig.add_hrect(y0=i - 0.5, y1=i + 0.5, fillcolor=BRAND_COLORS.get("Acuvue", "#2563eb"), opacity=0.12, line_width=0, layer="below")
    for b, v in zip(rank["Brand"], rank["Balanced score"]):   # the stem from the axis to each dot
        fig.add_shape(type="line", x0=40, x1=v, y0=b, y1=b, line=dict(color="#cbd5e1", width=2), layer="below")
    fig.add_trace(go.Scatter(
        x=rank["Balanced score"], y=rank["Brand"], mode="markers+text", text=[f"<b>{v:.0f}</b>" if b == "Acuvue" else f"{v:.0f}" for b, v in zip(rank["Brand"], rank["Balanced score"])], textposition="middle right",
        textfont=dict(size=16), cliponaxis=False, marker=dict(size=22, color=colors, line=dict(width=2, color="white")),
        hovertemplate="%{y}: balanced score %{x:.0f}<extra></extra>", showlegend=False))
    fig.update_layout(height=48 * len(rank) + 150)
    fig.update_xaxes(range=[40, 100], title="Balanced score (0-100)", showgrid=False)
    fig.update_yaxes(title=None, tickfont=dict(size=14), tickmode="array", tickvals=names, ticktext=[f"<b>{b}</b>" if b == "Acuvue" else b for b in names],
                     range=[-0.5, len(names) - 0.4])   # an empty top slot keeps the zone labels clear of the first dot
    ui.plot(fig, say=title, key="bh_ranking", bases={b: scores[b]["n"] for b in names}, noun="pooled items")
    ui.show_data("Table: balanced score by brand", rank.sort_values("Balanced score", ascending=False).assign(**{"Pooled items": [scores[b]["n"] for b in rank.sort_values("Balanced score", ascending=False)["Brand"]]}).round({"Balanced score": 0}))


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
            tr.append((f"<i>{v:.0f}%</i><br>n={n} (thin)" if n < 30 else f"<b>{v:.0f}%</b><br>n={n}") if v is not None else (f"n={n}" if n else ""))
        z.append(zr)
        txt.append(tr)
    fig = go.Figure(go.Heatmap(z=z, x=labels, y=brands, text=txt, texttemplate="%{text}", zmin=40, zmax=100, xgap=3, ygap=3,
                               colorscale=[[0, "#F1F5F9"], [1, "#5FB0C0"]], showscale=False, textfont=dict(size=12, color="#191919"),
                               hovertemplate="%{y} on %{x}<extra></extra>"))
    if "Acuvue" in brands:   # focal brand: outlined row and bold label
        i = brands.index("Acuvue")
        fig.add_shape(type="rect", xref="paper", yref="y", x0=0, x1=1, y0=i - 0.5, y1=i + 0.5, line=dict(color=BRAND_COLORS.get("Acuvue", "#178197"), width=2), fillcolor="rgba(0,0,0,0)")
    fig.update_layout(height=46 * len(brands) + 90)
    fig.update_xaxes(side="top", showgrid=False, ticktext=labels[:len(SCORE_CHANNELS)] + [f"{c} (not in score)" for c in REFERENCE_CHANNELS], tickvals=labels)
    fig.update_yaxes(autorange="reversed", showgrid=False, tickmode="array", tickvals=brands, ticktext=[f"<b>{b}</b>" if b == "Acuvue" else b for b in brands])
    ui.plot(fig, say="Where each score comes from: % positive or neutral by brand and channel, darker is more positive", key="bh_heatmap",
            bases="Items per cell are printed in it; italic = 15 to 29 items, directional; under 15 shows the count only")
    cell = lambda t: t.replace("<i>", "").replace("</i>", "").replace("<b>", "").replace("</b>", "").replace("<br>", ", ")
    ui.show_data("Table: % positive or neutral and items by brand and channel",
                 pd.DataFrame([[b] + [cell(t) for t in row] for b, row in zip(brands, txt)], columns=["Brand"] + labels))
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
    if not rows:
        st.info("No channel has 15+ items for Acuvue and for peers.")
        return
    t = pd.DataFrame(rows)
    fig = go.Figure()
    fig.add_trace(go.Bar(name="Peers", x=t["Channel"], y=t["Peers"], marker_color=PEER_GREY, text=[f"{v:+.0f}" for v in t["Peers"]], textposition="outside"))
    fig.add_trace(go.Bar(name="Acuvue", x=t["Channel"], y=t["Acuvue"], marker_color=BRAND_COLORS.get("Acuvue", "#2563eb"),
                         text=[f"<b>{v:+.0f}</b>" for v in t["Acuvue"]], textposition="outside"))
    fig.update_layout(barmode="group", height=310, yaxis_title="Net sentiment (% positive minus % negative)", margin=dict(t=30),
                      legend=dict(orientation="h", y=1.1))
    _gap = {c: g for c, g, rg in zip(t["Channel"], t["Gap"], t["Real gap"]) if rg == "yes"}
    fig.update_xaxes(ticktext=[(c if c in SCORE_CHANNELS else f"{c} (not in score)") + (f"<br><b>gap {ebi.pts(_gap[c])}</b>" if c in _gap else "") for c in t["Channel"]],
                     tickvals=t["Channel"])
    soc = t[t["Channel"].isin(SCORE_CHANNELS)]
    best, worst = soc.loc[soc["Acuvue"].idxmax()], soc.loc[soc["Acuvue"].idxmin()]
    real = t[t["Real gap"] == "yes"]
    say = (f"Acuvue's net sentiment runs from {worst['Acuvue']:+.0f} on {worst['Channel']} to {best['Acuvue']:+.0f} on {best['Channel']} (social channels); "
           + (f"a tested gap to peers is marked on {len(real)} channel{'s' if len(real) > 1 else ''}." if len(real) else "no channel differs from peers."))
    ui.plot(fig, say=say, kind="dir", bases="Acuvue / peer items: " + " · ".join(f"{r.Channel} {r.n_a} / {r.n_p}" for r in t.itertuples()), key="brand_health_channel_read")
    _cap, _go = st.columns([4, 1], vertical_alignment="center")
    _cap.caption("Reading: Acuvue scores higher where creators promote or review it (Xiaohongshu, Instagram, Lazada) than where people describe their own use "
                 "(Reddit, KiasuParents). The YouTube gap is mostly Olens, a colour-lens brand with large channels: read it as category, not lens quality. "
                 "The app is rated separately, since it is Acuvue-only.")
    with _go:
        ui.goto("Journey & App", "App reviews", key="bh_to_journey_app")
    ui.show_data("Table: Acuvue vs peers by channel", t.assign(**{c: t[c].round(0) for c in ["Acuvue", "Peers", "Gap", "Low", "High"]})
                 .rename(columns={"Low": "Gap low (95%)", "High": "Gap high (95%)", "n_a": "Acuvue n", "n_p": "Peer n"}))


def _health_title(bm: dict) -> str:
    """One claim built from the tested numbers: the pooled gap with its interval, then the channels where a gap passes the checks, and the peer behind it."""
    g, cg = bm["read"], bm["channels"]
    if not g:
        return f"{vd.FOCAL} cannot yet be separated from its peers"
    gap = ebi.pts(g["gap"])
    lead = (f"{vd.FOCAL} is not measurably different from peers overall ({gap})" if bm["verdict"] == "level with peers"
            else f"{vd.FOCAL} is {bm['verdict']} overall ({gap})")
    clear = cg[cg["ok"] & cg["lo"].notna() & ((cg["lo"] > 0) | (cg["hi"] < 0))] if len(cg) else cg
    if not len(clear):
        return lead + "; no single channel shows a tested gap"
    r = clear.sort_values("gap").iloc[0]
    who = f", where the peers are mostly {r.peer_top}" if r.peer_top_share >= 60 else ""
    behind = clear[clear["gap"] < 0].sort_values("gap")
    _lead = behind[behind["peer_top_share"] >= 60]
    who = f", mostly against {_lead.iloc[0].peer_top}" if len(_lead) else ""
    if not len(behind):
        return lead + "; where a channel differs, Acuvue is ahead"
    names = " and ".join([", ".join(behind["channel"].iloc[:-1]), behind["channel"].iloc[-1]] if len(behind) > 1 else [behind["channel"].iloc[0]])
    return f"{lead}, but trails on {names}"


def render(d: pd.DataFrame, brands: list) -> None:
    if d.empty:
        st.subheader("Brand Health")
        st.info("Run Scripts/build_voice_items.py and Scripts/tag_voice_items.py to build the tables this page reads.")
        return
    st.info(
        "**How this score is built:** each brand gets one **balanced score (0-100)**. For each social channel (Xiaohongshu, Reddit, YouTube, "
        "Instagram, Facebook) take the share of comments, posts and reviews that name the brand and are "
        "about lenses and are positive or neutral (mixed and negative stay in the base), then average the channels weighted by √n. "
        f"A channel counts once it has **{MIN_CH}+ items**; under that it shows the count only. Healthy 65+, mixed 45-64, "
        "at risk below 45. Lazada reviews and KiasuParents are shown beside the score, not in it. Every channel is read by the same model tagger. Giveaway entries are removed. The tested channel gaps at the top "
        "use net sentiment (% positive minus % negative), so their numbers differ from this score by design."
    )
    p = _prep(d, brands)
    if p.empty:
        st.info("No brand-named items for the selected brands.")
        return

    _bm = brand_market_page.facts(d)
    st.subheader(_health_title(_bm))
    _channel_read(p)
    st.divider()

    st.markdown("#### What Acuvue posts vs what consumers raise")
    brand_market_page.render(d)
    st.divider()

    scores = {b: _scores(p, b) for b in brands if b in set(p["brand_std"])}
    with st.expander("Balanced score by brand (detail: healthy brands score close together, so the score does not separate them)", expanded=False, on_change="rerun", key="bh_score_exp") as _sx:
        if _sx.open:
            cols = st.columns(min(max(len(scores), 1), 5))
            for i, (b, sc) in enumerate(scores.items()):
                with cols[i % len(cols)]:
                    st.markdown(_card(b, sc), unsafe_allow_html=True)
            rank = pd.DataFrame([{"Brand": b, "Balanced score": s["score"]} for b, s in scores.items() if s["score"] is not None])
            if not rank.empty:
                _ranking(rank, scores, p)
                _channel_heatmap(rank, scores)

    st.divider()
    st.markdown("#### Brand Deep-Dive")
    dd = st.multiselect("Brands to compare", list(scores), default=list(scores), key="brand_health_deep_dive_compare")
    if not dd:
        st.info("Select at least one brand to plot.")
        return
    with st.expander("Composite sentiment trend (% positive or neutral; direction only)", expanded=False, on_change="rerun", key="bh_trend_exp") as _tx:
        if _tx.open:
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
    with st.container(key="bh-tiles"):
        for i in range(0, len(tiles), per_row):
            for col, (label, value, hint) in zip(st.columns(per_row), tiles[i:i + per_row]):
                col.metric(label, value, help=hint, border=True)
    st.caption(f"Each figure is for **{focus} only**: the score is a 0-100 balance, the channel figures are % positive or neutral. The Social "
               "Signals tabs pool all brands on their All Brands view, so a different denominator.")
    _hesitate(p, focus)

    st.caption("Search interest is category-level, not per brand.")
    ui.goto("Trends & Demand", key="bh_to_trends")

    st.divider()
    _pool = vd.pool(d)
    ui.read_comments(_pool[_pool["brand_std"].isin(brands)], "Read the brand comments behind this page (brand pool)", key="bh_read")
