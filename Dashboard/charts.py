"""
Shared chart layer for the story pages. Every brand and every channel is drawn through
these functions so headings, category order, labels, colours, scales and small-n wording
are identical wherever a chart appears (see the consistency rules in the dashboard plan).

Rules enforced here:
  * sentiment always runs Positive, Neutral, Mixed, Negative, in the same colours,
    and every category is present even when a brand has none (axes line up);
  * brands always run in BRAND_ORDER (ACUVUE first), so panels compare at a glance;
  * a base under ebi.MIN_N shows counts, not percentages;
  * a missing cell says why (no data collected vs too few to score), never a bare 0 or "<5".
"""

import pandas as pd
import plotly.graph_objects as go

import ebi
from sg_common import BRAND_COLORS, SENTIMENT_COLORS

SENTIMENT_ORDER = ["positive", "neutral", "mixed", "negative"]
SENTIMENT_LABELS = {"positive": "Positive", "neutral": "Neutral", "mixed": "Mixed", "negative": "Negative"}
# One sentiment palette for the whole dashboard: the same dict the legacy pages use (sg_common.SENTIMENT_COLORS).
SENTIMENT_PALETTE = SENTIMENT_COLORS

BRAND_ORDER = list(BRAND_COLORS)  # Acuvue first, then Alcon, Bausch & Lomb, CooperVision, Olens
# Channel names are the same on every page (Journey, Market, Brand Health, Conversation). "Lazada reviews" are the
# SG star-rated reviews; "Xiaohongshu" counts posts, the other channels count comments.
SOURCE_ORDER = ["Lazada reviews", "KiasuParents", "Xiaohongshu", "Xiaohongshu comments", "Reddit", "YouTube", "Instagram", "Facebook"]
# Channel colours are kept apart from brand colours and from the sentiment palette so a channel is never mistaken for either.
SOURCE_COLORS = {"Lazada reviews": "#8D6E63", "KiasuParents": "#B08968", "Xiaohongshu": "#E64980", "Xiaohongshu comments": "#F783AC",
                 "Reddit": "#F59F00", "YouTube": "#495057", "Instagram": "#7048E8", "Facebook": "#5C7CFA"}

NO_DATA = "No data collected"


def order_brands(brands) -> list:
    """Selected brands in the fixed dashboard order (unknown brands last)."""
    brands = list(brands)
    return [b for b in BRAND_ORDER if b in brands] + [b for b in brands if b not in BRAND_ORDER]


AMBER = "#B7791F"
MUTED = "#64748B"


def row_label(name: str, n: int | None = None, note: str = "") -> str:
    """Axis label for a row or column: the name with its sample size underneath. A base under ebi.MIN_N is amber and
    says "directional only", so a thin bar is flagged on the axis as well as in the strip below the chart."""
    if n is None:
        return name
    if n == 0:
        sub, col = note or "no data", MUTED
    elif ebi.is_thin(n):
        sub, col = f"n={int(n):,} · directional only", AMBER
    else:
        sub, col = f"n={int(n):,}", MUTED
    return f'{name}<br><span style="font-size:10px;color:{col}">{sub}</span>'


def thin_fill(thin: list, colour_hex: str = "#FFFFFF") -> dict:
    """Plotly marker.pattern that hatches the bars flagged in `thin` (a list of booleans, one per bar) and leaves
    the rest solid, so directional bars read as different from solid ones without relying on colour alone."""
    return dict(shape=["/" if t else "" for t in thin], fillmode="overlay", fgcolor=colour_hex, size=8, solidity=0.22)


def thin_label(n_analysed: int, n_collected: int) -> str:
    """The wording for a cell that cannot carry a percentage."""
    if n_collected == 0:
        return NO_DATA
    return f"Too few to score (n={n_analysed} of {n_collected})"


def sentiment_mix(df: pd.DataFrame, by: str, groups: list, height: int = 300, collected: dict | None = None) -> go.Figure:
    """100% stacked horizontal bars of sentiment per group (brand or source).

    `df` has a `sentiment` column and the `by` column. Every group in `groups` gets a row
    (even if empty) and every sentiment appears in the legend in the fixed order. Groups
    under ebi.MIN_N are hatched and labelled "directional only" so a thin base can't read as a rate.
    `collected` ({group: items scraped}) lets an empty row say "too few to score" when items were
    collected but none survived analysis, instead of "no data collected"."""
    fig = go.Figure()
    counts = (
        df.assign(sentiment=df["sentiment"].where(df["sentiment"].isin(SENTIMENT_ORDER)))
        .dropna(subset=["sentiment"])
        .groupby([by, "sentiment"]).size().unstack(fill_value=0)
        .reindex(index=groups, columns=SENTIMENT_ORDER, fill_value=0)
    )
    totals = counts.sum(axis=1)
    for s in SENTIMENT_ORDER:
        pct = (counts[s] / totals.where(totals > 0) * 100).fillna(0)
        fig.add_trace(go.Bar(
            y=groups, x=pct, name=SENTIMENT_LABELS[s], orientation="h",
            marker=dict(color=SENTIMENT_PALETTE[s], opacity=[0.8 if ebi.is_thin(totals[g]) else 1.0 for g in groups],
                        pattern=thin_fill([ebi.is_thin(totals[g]) for g in groups])),
            text=[f"{counts.loc[g, s]}" if counts.loc[g, s] else "" for g in groups],
            textposition="inside", insidetextanchor="middle",
            customdata=counts[s].values,
            hovertemplate="%{y} · " + SENTIMENT_LABELS[s] + ": %{x:.0f}% (%{customdata} items)<extra></extra>",
        ))
    fig.update_layout(
        barmode="stack", height=height,
        xaxis=dict(range=[0, 100], ticksuffix="%", title=None),
        yaxis=dict(autorange="reversed", title=None,
                   ticktext=[row_label(g, int(totals[g]), thin_label(0, int((collected or {}).get(g, 0))).lower()) for g in groups],
                   tickvals=groups),
        legend=dict(orientation="h", y=-0.18, title_text="", traceorder="normal"),
    )
    return fig


def gap_bars(rows: pd.DataFrame, brand: str, height: int = 320, axis_title: str = "Share of negative / mixed items",
             n_brand: int | None = None, n_peers: int | None = None) -> go.Figure:
    """Reason chart: share of a brand's negative/mixed items vs the peer share, per reason.

    `rows` columns: reason, brand_share, peer_share (percent, NaN where the base is too thin).
    `n_brand` / `n_peers` put each side's sample size in the legend."""
    fig = go.Figure()
    nb = f"{brand} (n={n_brand:,})" if n_brand is not None else brand
    npr = f"Peers (n={n_peers:,})" if n_peers is not None else "Peers"
    fig.add_trace(go.Bar(y=rows["reason"], x=rows["brand_share"], name=nb, orientation="h",
                         marker_color=BRAND_COLORS.get(brand, "#178197"),
                         text=rows["brand_text"], textposition="outside", cliponaxis=False))
    fig.add_trace(go.Bar(y=rows["reason"], x=rows["peer_share"], name=npr, orientation="h",
                         marker_color="#B8C2CC", text=rows["peer_text"], textposition="outside", cliponaxis=False))
    top = float(pd.concat([rows["brand_share"], rows["peer_share"]]).max() or 0)
    fig.update_layout(
        barmode="group", height=height,
        xaxis=dict(range=[0, max(top * 1.35, 10)], ticksuffix="%", title=axis_title),
        yaxis=dict(autorange="reversed", title=None),
        legend=dict(orientation="h", y=-0.28, title_text=""),
    )
    return fig


def score_lollipop(scores: dict, height: int = 260, ns: dict | None = None) -> go.Figure:
    """Composite score per brand on one fixed 0-100 axis, in score order. Brands without a score are listed as such.
    `ns` ({brand: items behind the score}) puts the sample size on each row; a brand under ebi.MIN_N is drawn as a
    dotted stem with a hollow dot and a * on its score, the same "directional" look as a hatched bar."""
    ns = ns or {}
    scored = sorted(((b, s) for b, s in scores.items() if s is not None), key=lambda t: -t[1])
    label = {b: row_label(b, ns[b]) if b in ns else b for b in scores}
    fig = go.Figure()
    for b, s in scored:
        col = BRAND_COLORS.get(b, "#178197")
        thin = ebi.is_thin(ns.get(b, ebi.MIN_N))
        fig.add_trace(go.Scatter(x=[0, s], y=[label[b], label[b]], mode="lines",
                                 line=dict(color=col, width=3, dash="dot" if thin else "solid"),
                                 showlegend=False, hoverinfo="skip"))
        fig.add_trace(go.Scatter(x=[s], y=[label[b]], mode="markers+text", text=[f"{s:.0f}" + ("*" if thin else "")],
                                 textposition="middle right",
                                 marker=dict(size=14, color="white" if thin else col, line=dict(width=3, color=col)),
                                 showlegend=False, hovertemplate="%{y}: %{x:.0f}<extra></extra>"))
    unscored = [b for b, s in scores.items() if s is None]
    fig.update_xaxes(range=[0, 105], title="Composite score (0-100)")
    fig.update_yaxes(autorange="reversed", title="", categoryorder="array",
                     categoryarray=[label[b] for b, _ in scored] + [label[b] for b in unscored])
    fig.update_layout(height=height)
    return fig


def trend_lines(df: pd.DataFrame, brands: list, height: int = 280) -> go.Figure:
    """Monthly % not-negative per brand on a fixed 0-100 axis, brands in fixed order. df: month, Brand, pct and
    optionally n (items that month). Months under ebi.MIN_N items get a hollow marker: directional only."""
    fig = go.Figure()
    for b in brands:
        d = df[df["Brand"] == b].sort_values("month")
        if d.empty:
            continue
        col = BRAND_COLORS.get(b, "#178197")
        n = d["n"] if "n" in d.columns else pd.Series([ebi.MIN_N] * len(d), index=d.index)
        thin = [ebi.is_thin(v) for v in n]
        fig.add_trace(go.Scatter(
            x=d["month"], y=d["pct"], name=b, mode="lines+markers", line=dict(color=col),
            marker=dict(size=8, color=["white" if t else col for t in thin], line=dict(width=2, color=col)),
            customdata=n.values,
            hovertemplate="%{x} · " + b + ": %{y:.0f}% (n=%{customdata})<extra></extra>"))
    fig.update_yaxes(range=[0, 105], ticksuffix="%", title="% positive or neutral")
    fig.update_xaxes(tickangle=-45, title=None)
    fig.update_layout(height=height, legend=dict(orientation="h", y=-0.35, title_text=""))
    return fig


def share_bars(df: pd.DataFrame, channels: list, brands: list, labels: dict | None = None,
               count_text: bool = True, height: int = 300) -> go.Figure:
    """100% stacked horizontal bars: each channel's total split by brand (share of voice, or share of attention).

    `df` has `source`, `brand` and `value` (1 per post for volume, the reach metric for attention).
    Brands always stack in `brands` order with their fixed colours; a brand with nothing in a channel simply has no
    segment (say so in the note). Channels whose total is under ebi.MIN_N rows are hatched. `labels` overrides the
    channel tick text (build it with row_label so the base still shows); `count_text` prints the raw value inside each segment, otherwise the %."""
    pv = df.groupby(["source", "brand"])["value"].sum().unstack(fill_value=0).reindex(index=channels, columns=brands, fill_value=0)
    nrows = df.groupby("source").size().reindex(channels, fill_value=0)
    tot = pv.sum(axis=1)
    pct = pv.div(tot.where(tot > 0), axis=0).mul(100).fillna(0)
    fig = go.Figure()
    for b in brands:
        txt = [(f"{int(pv.loc[c, b]):,}" if count_text else f"{pct.loc[c, b]:.0f}%") if pct.loc[c, b] >= 6 else "" for c in channels]
        fig.add_trace(go.Bar(
            y=channels, x=pct[b], name=b, orientation="h", text=txt, textposition="inside", insidetextanchor="middle",
            marker=dict(color=BRAND_COLORS.get(b, "#999999"), opacity=[0.8 if ebi.is_thin(nrows[c]) else 1.0 for c in channels],
                        pattern=thin_fill([ebi.is_thin(nrows[c]) for c in channels])),
            customdata=pv[b].values,
            hovertemplate="%{y} · " + b + ": %{x:.0f}% (%{customdata:,.0f})<extra></extra>",
        ))
    ticks = [(labels or {}).get(c, row_label(c, int(nrows[c]))) for c in channels]
    fig.update_layout(
        barmode="stack", height=height,
        xaxis=dict(range=[0, 100], ticksuffix="%", title=None),
        yaxis=dict(autorange="reversed", title=None, tickvals=channels, ticktext=ticks),
        legend=dict(orientation="h", y=-0.18, title_text="", traceorder="normal"),
    )
    return fig


def ci_dots(roll: pd.DataFrame, ref: float | None = None, ref_label: str = "Peers pooled", height: int = 270) -> go.Figure:
    """Pooled % positive-or-neutral per brand with its 95% interval, on a fixed 0-100 axis in brand order. `roll` is
    insights.rollup(); a brand under ebi.MIN_N items has no interval and is listed as directional. Overlapping intervals
    mean the difference between those brands could be chance. `ref` draws a dashed line (the peers' pooled share)."""
    fig = go.Figure()
    labels = {r.brand: row_label(r.brand, int(r.n)) for r in roll.itertuples()}
    shown = roll[roll["pn"].notna()]
    # zoom: start the axis at the tens digit below the lowest interval, so the data fills the chart
    axis_lo = int(max(0, (shown["lo"].min() // 10) * 10)) if len(shown) else 0
    for r in roll.itertuples():
        col = BRAND_COLORS.get(r.brand, "#178197")
        if r.pn is None or pd.isna(r.pn):
            continue
        fig.add_trace(go.Scatter(x=[r.lo, r.hi], y=[labels[r.brand]] * 2, mode="lines", line=dict(color=col, width=7),
                                 opacity=0.35, showlegend=False, hoverinfo="skip"))
        fig.add_trace(go.Scatter(x=[r.pn], y=[labels[r.brand]], mode="markers", marker=dict(size=14, color=col), showlegend=False,
                                 hovertemplate=f"{r.brand}: %{{x:.0f}}% (95% interval {r.lo:.0f}-{r.hi:.0f}%, n={int(r.n)})<extra></extra>"))
        # the value sits to the right of the interval, clear of the dashed reference line
        fig.add_trace(go.Scatter(x=[r.hi], y=[labels[r.brand]], mode="text", text=[f"<b>{r.pn:.0f}%</b>"], textposition="middle right",
                                 textfont=dict(size=12, color="#191919"), showlegend=False, hoverinfo="skip"))
    if ref is not None:
        fig.add_vline(x=ref, line=dict(color="#64748B", width=1.5, dash="dash"))
    sub = [f"axis starts at {axis_lo}%"] + ([f"dashed line = {ref_label.lower()} ({ref:.0f}%)"] if ref is not None else [])
    fig.update_xaxes(range=[axis_lo, 107], tickvals=list(range(axis_lo, 101, 10)), ticktext=[f"{v}%" for v in range(axis_lo, 101, 10)],
                     title="% positive or neutral, all channels pooled (95% interval)"
                           f"<br><span style='font-size:11px;color:#64748B'>{' · '.join(sub)}</span>")
    fig.update_yaxes(title="", categoryorder="array", categoryarray=[labels[b] for b in roll["brand"]],
                     range=[len(roll) - 0.5, -0.5])
    fig.update_layout(height=height)
    return fig


def channel_heat(cov: pd.DataFrame, brands: list, channels: list | None = None, height: int | None = None) -> go.Figure:
    """Brand x channel grid of % positive-or-neutral on one fixed scale. A cell under ebi.MIN_N labelled items shows its count only
    (no colour); a cell with nothing says why. `cov` is insights.coverage()."""
    channels = channels or SOURCE_ORDER
    z, text = [], []
    for b in brands:
        zr, tr = [], []
        for c in channels:
            r = cov[(cov["brand"] == b) & (cov["source"] == c)]
            if r.empty or int(r.iloc[0]["collected"]) == 0:
                zr.append(None); tr.append("no data<br>collected")
            elif int(r.iloc[0]["scored_n"]) < ebi.MIN_N:
                zr.append(None); tr.append(f"n={int(r.iloc[0]['scored_n'])}<br>too few")
            else:
                zr.append(float(r.iloc[0]["pos_neu"])); tr.append(f"{r.iloc[0]['pos_neu']:.0f}%<br>n={int(r.iloc[0]['scored_n'])}")
        z.append(zr); text.append(tr)
    fig = go.Figure(go.Heatmap(z=z, x=channels, y=brands, text=text, texttemplate="%{text}", zmin=40, zmax=100,
                               colorscale=[[0, "#DD1C14"], [0.5, "#F1F5F9"], [1, "#168012"]],   # neutral grey at 70%
                               colorbar=dict(title=dict(text="% positive or neutral", side="top", font=dict(size=11)), thickness=12, len=0.75, y=0.4,
                                             tickvals=[40, 55, 70, 85, 100], ticktext=["40% or less", "55%", "70%", "85%", "100%"], tickfont=dict(size=10)),
                               xgap=3, ygap=3, showscale=True, hoverongaps=False, textfont=dict(size=11, color="#191919"),
                               hovertemplate="%{y} · %{x}<br>%{text}<extra></extra>"))
    fig.update_xaxes(side="top", tickangle=0, title=None, tickvals=channels, ticktext=[c.replace(" ", "<br>") for c in channels])
    fig.update_yaxes(autorange="reversed", title=None)
    fig.update_layout(height=height or 100 + 52 * len(brands), plot_bgcolor="#F1F5F9", margin=dict(t=60))
    return fig
