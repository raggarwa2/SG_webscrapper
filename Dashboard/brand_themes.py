"""
Brand Health, section 4: what each brand is praised and criticised for, on one list of themes.

Every pooled item (the same items as the rest of Brand Health) carries 1 or 2 themes (theme_tags.py): a model tag once
Scripts/theme_tag_sg.py has run, a keyword draft until then. The grid is theme x brand. Each cell is the net sentiment of the
items on that theme (% positive minus % negative, mixed and neutral stay in the base) with its item count. A cell needs
ebi.MIN_N items; under that it is a dash, and a theme no brand reaches that many on is left out and counted in a note.
The right-hand column carries the desk-research framework (framework_check.py) as a marker on the theme, so research and
data sit on one grid.
"""

import html

import pandas as pd
import plotly.graph_objects as go
import streamlit as st

import charts
import ebi
import framework_check
import insights
import theme_tags
import ui

INK = "#051F4A"
NEG, POS = (180, 35, 24), (15, 118, 110)       # ui tokens --neg and --pos
NET_FULL = 60.0                                  # net sentiment at which the colour is fully saturated


def _themed(pooled: pd.DataFrame) -> pd.DataFrame:
    """One row per item x theme, labelled items only. Items with no theme are dropped here and counted by the caller."""
    d = theme_tags.attach(pooled[pooled["sentiment"].isin(insights.VALID)])
    return d.explode("themes").dropna(subset=["themes"]).rename(columns={"themes": "theme"}).reset_index(drop=True)


def _net(sub: pd.DataFrame):
    n = len(sub)
    if n < ebi.MIN_N:
        return None, n
    vc = sub["sentiment"].value_counts()
    return (vc.get("positive", 0) - vc.get("negative", 0)) / n * 100, n


def _shade(net: float) -> tuple:
    f = max(-1.0, min(1.0, net / NET_FULL))
    end = POS if f >= 0 else NEG
    rgb = tuple(round(255 + (c - 255) * abs(f) * 0.85) for c in end)
    return f"rgb{rgb}", ("white" if abs(f) > 0.65 else "#191919")


def matrix(pooled: pd.DataFrame, brands: list) -> dict:
    """{"cells": {(theme, brand): (net, n)}, "all": {theme: (net, n)}, "themes": [kept themes], "dropped": [...], "coverage": {...}}"""
    base = theme_tags.attach(pooled[pooled["sentiment"].isin(insights.VALID)])
    ex = _themed(pooled)
    cells, allb, kept, dropped = {}, {}, [], []
    for t in theme_tags.THEME_LIST:
        sub = ex[ex["theme"] == t]
        row = {b: _net(sub[sub["brand"] == b]) for b in brands}
        if not any(v[0] is not None for v in row.values()):
            dropped.append(t)
            continue
        kept.append(t)
        for b, v in row.items():
            cells[(t, b)] = v
        allb[t] = _net(sub)
    n_items = ex.groupby("brand")["key"].nunique()
    return {"cells": cells, "all": allb, "themes": kept, "dropped": dropped, "ex": ex, "n_items": {b: int(n_items.get(b, 0)) for b in brands},
            "coverage": {"items": len(base), "model": int(base["tagged"].sum()), "no_theme": int((base["themes"].map(len) == 0).sum())}}


def focus_gaps(m: dict, focus: str, peers: list) -> list:
    """Themes where the focus brand and the other brands pooled both have 30+ items: net on each side, the gap, and whether the
    positive-or-neutral share differs beyond chance (two-proportion test)."""
    ex = m["ex"]
    out = []
    for t in m["themes"]:
        f, p = ex[(ex["theme"] == t) & (ex["brand"] == focus)], ex[(ex["theme"] == t) & ex["brand"].isin(peers)]
        nf, npr = _net(f), _net(p)
        if nf[0] is None or npr[0] is None:
            continue
        pn = lambda d: int(d["sentiment"].isin(["positive", "neutral"]).sum())
        pv = insights.two_prop_p(pn(f), len(f), pn(p), len(p))
        out.append({"theme": t, "f_net": nf[0], "p_net": npr[0], "gap": nf[0] - npr[0], "f_n": nf[1], "p_n": npr[1],
                    "real": pv is not None and pv < 0.05})
    return out


def _grid(m: dict, brands: list, focus: str, research: dict) -> go.Figure:
    themes = m["themes"]
    cols = ["Theme", *brands, "All brands", "Research names"]
    edges = [0, 3.4] + [3.4 + 2.0 * (i + 1) for i in range(len(brands))]
    edges += [edges[-1] + 2.2, edges[-1] + 2.2 + 4.2]
    total = len(themes)
    fig = go.Figure()

    def box(c, y0, fill, label, color, size=11):
        fig.add_shape(type="rect", x0=edges[c] + 0.04, x1=edges[c + 1] - 0.04, y0=y0 - 0.46, y1=y0 + 0.46, fillcolor=fill, line_width=0, layer="below")
        fig.add_annotation(x=(edges[c] + edges[c + 1]) / 2, y=y0, text=label, showarrow=False, font=dict(size=size, color=color))

    def cell(c, y0, v):
        net, n = v
        if net is None:
            box(c, y0, "#F4F6F9", "–" if n == 0 else f"n={n}", "#B8C2CC", size=10)
        else:
            fill, col = _shade(net)
            box(c, y0, fill, f"<b>{ebi.sgn(net)}</b><br><span style='font-size:9px'>n={n}</span>", col)

    for i, t in enumerate(themes):
        y0 = total - i - 0.5
        fig.add_annotation(x=edges[0] + 0.1, y=y0, xanchor="left", showarrow=False, text=f"<b>{t}</b>", font=dict(size=12, color="#191919"))
        for j, b in enumerate(brands, start=1):
            cell(j, y0, m["cells"][(t, b)])
        cell(len(brands) + 1, y0, m["all"][t])
        r = research.get(t)
        if r:
            box(len(brands) + 2, y0, "#E8F3F5", f"{r['claims']} claim{'s' if r['claims'] != 1 else ''} · up to {framework_check.LEVEL[r['level']]}<br><span style='font-size:9px'>{', '.join(s.replace('Repeat/Retention', 'Retention') for s in r['stages'])}</span>", "#0B3556")
        else:
            box(len(brands) + 2, y0, "#F4F6F9", "–", "#B8C2CC")
    for c, h in enumerate(cols):
        fig.add_annotation(x=(edges[c] + edges[c + 1]) / 2, y=total + 0.4, text=f"<b>{h}</b>", showarrow=False,
                           font=dict(size=12, color=INK if h != focus else "#178197"))
    fig.update_xaxes(range=[edges[0], edges[-1]], visible=False, fixedrange=True)
    fig.update_yaxes(range=[-0.1, total + 0.95], visible=False, fixedrange=True)
    fig.update_layout(height=int(46 * total + 80), showlegend=False)
    return fig


def pick(gaps: list):
    """The theme gap to headline: the weakest if the focus brand trails there (and it is real or the largest gap), else the strongest."""
    worst = min(gaps, key=lambda g: g["gap"])
    best = max(gaps, key=lambda g: g["gap"])
    return worst if worst["gap"] < 0 and (worst["real"] or abs(worst["gap"]) >= abs(best["gap"])) else best


def claim(g: dict, focus: str) -> str:
    word = "trails" if g["gap"] < 0 else "leads"
    return f"{focus} {word} peers on {g['theme'].lower()}"


def tile(m: dict, focus: str, peers: list) -> dict:
    """The pyramid tile for this section."""
    gaps = focus_gaps(m, focus, peers)
    if not gaps:
        return {"label": "Themes", "value": "Too few", "text": f"No theme has {ebi.MIN_N}+ items for {html.escape(focus)} and for peers, so themes are not compared.", "tone": "flat"}
    g = pick(gaps)
    caveat = "" if g["real"] else " (within chance)"
    return {"label": "Themes", "value": ebi.pts(g['gap']),
            "text": f"{html.escape(claim(g, focus))}: net {ebi.sgn(g['f_net'])} vs {ebi.sgn(g['p_net'])}{caveat}.",
            "tone": ("bad" if g["gap"] < 0 else "good") if g["real"] else "flat"}


def render(pooled: pd.DataFrame, brands: list, focus: str, m: dict | None = None, jf_all: pd.DataFrame | None = None) -> None:
    peers = [b for b in brands if b != focus]
    m = m or matrix(pooled, brands)
    cov = m["coverage"]
    waiting = theme_tags.queue(pooled, jf_all)
    gaps = focus_gaps(m, focus, peers)
    g = pick(gaps) if gaps else None
    title = f"{claim(g, focus)}: net {ebi.sgn(g['f_net'])} vs {ebi.sgn(g['p_net'])}" if g else "Net sentiment by theme and brand"
    ui.section(title, "Each item is tagged with 1 or 2 themes; a cell is the net sentiment of the items on that theme.", "4 · Themes", kind="fact")
    if not m["themes"]:
        st.info(f"No theme has {ebi.MIN_N}+ items for any brand yet.")
        return
    ui.plot(_grid(m, brands, focus, framework_check.by_theme()), "", key="bh_themes",
            note=(f"Cell = % positive minus % negative of the items on that theme (neutral and mixed stay in the base); green above zero, red below. "
                  f"A dash or n= = under {ebi.MIN_N} items. Research names = claims from the desk-research framework that map to the theme "
                  "(stages in grey; by category user in the table below)."),
            bases=m["n_items"], noun="themed items")
    notes = []
    if m["dropped"]:
        notes.append(f"{len(m['dropped'])} theme{'s' if len(m['dropped']) != 1 else ''} left out: no brand has {ebi.MIN_N}+ items on {', '.join(m['dropped'])}.")
    if cov["no_theme"]:
        notes.append(f"{cov['no_theme']:,} of {cov['items']:,} items have no theme.")
    if cov["model"] < cov["items"]:
        notes.append(f"Themes: {cov['model']:,} of {cov['items']:,} items are model-tagged, the rest are a keyword draft. "
                     + (f"{waiting:,} wait for the tagging run (Scripts/theme_tag_sg.py)." if waiting else ""))
    if notes:
        st.caption(" ".join(notes))

    res = framework_check.by_theme()
    if res:
        with st.expander("What the research says on each theme (source IDs)", expanded=False):
            rows = []
            for u, s_, b, lvl, note, ids in framework_check.RESEARCH:
                rows.append({"Theme": theme_tags.B_TO_THEME.get(b, "–"), "Category user": u, "Stage": s_, "Barrier": b,
                             "Confidence": framework_check.LEVEL[lvl], "Claim": note, "Source IDs": ids})
            st.dataframe(pd.DataFrame(rows).sort_values(["Theme", "Stage"]), hide_index=True, width="stretch")
            st.caption("Source IDs resolve in Positioning > Sources. Profiles, needs and language: Positioning > Category users.")
