"""Positioning Analysis tab: renders the markdown deliverables in ../analysis/ (static, read-only).

The files are written by the triangulation analysis of Research runs 1 to 4 and the scraped data
(see analysis/00_source_log.md). Nothing here queries the databases.
"""
import re
from pathlib import Path

import plotly.graph_objects as go
import streamlit as st

import ui
from sg_common import BRAND_COLORS

_DIR = Path(__file__).resolve().parent.parent / "analysis"

# (sub-tab label, file)
PAGES = [
    ("Executive brief", "1_executive_brief.md"),
    ("Hypotheses", "3_hypothesis_table.md"),
    ("Deep dive", "2_deep_dive_report.md"),
    ("Category users", "4_category_user_barrier_framework.md"),
    ("Sources", "00_source_log.md"),
]


def _read(name: str) -> str | None:
    try:
        text = (_DIR / name).read_text(encoding="utf-8")
    except OSError:
        return None
    # Links to sibling files do not work inside the app; keep the label only.
    return re.sub(r"\[([^\]]+)\]\((?:[^)]*\.(?:md|svg))\)", r"\1", text)


def _render_category_users(text: str) -> None:
    """Profiles, needs, language and the cross-segment summary. The barrier-by-stage view moved to Journey & barriers
    (section 4, Research check), where it sits next to the scraped comments; the source tables stay here, collapsed."""
    nl = chr(10)
    lines, buf = text.split(nl), []
    def flush():
        if buf:
            st.markdown(nl.join(buf)); buf.clear()
    st.info("Each barrier is now a marker on its theme in Brand Health > 4 · Themes, next to what reviews say. "
            "The source tables stay here, collapsed.")
    i = 0
    while i < len(lines):
        ln = lines[i]
        if ln.strip() == "**Barriers by stage**":
            flush()
            i += 1
            tbl = []
            while i < len(lines) and (lines[i].startswith("|") or not lines[i].strip()):
                if lines[i].startswith("|"):
                    tbl.append(lines[i])
                i += 1
            with st.expander("Barriers by stage: table with evidence and IDs"):
                st.markdown(nl.join(tbl))
            continue
        buf.append(ln)
        i += 1
    flush()


# (label, colour key, x, x range, y, y range, confidence x, confidence y). X: clinical (0) to appearance (10). Y: open market (0) to ECP-anchored (10).
# Same estimates as analysis/perceptual_map.svg and the table below the map.
_MAP = [
    ("MyACUVUE", "Acuvue", 2, (1, 4), 8, (7, 9), "Medium", "Medium"),
    ("CooperVision", "CooperVision", 1, (0, 2), 6, (4, 8), "Medium", "Low"),
    ("Alcon", "Alcon", 3, (2, 4), 7, (5, 8), "Low", "Low"),
    ("Bausch + Lomb", "Bausch & Lomb", 3, (2, 5), 4, (2, 6), "Low", "Low"),
    ("Olens", "Olens", 9, (8, 10), 2, (1, 4), "Medium", "Low"),
]


def _rgba(hex_colour: str, alpha: float) -> str:
    h = hex_colour.lstrip("#")
    return f"rgba({int(h[0:2], 16)},{int(h[2:4], 16)},{int(h[4:6], 16)},{alpha})"


def _map_figure() -> go.Figure:
    fig = go.Figure()
    for name, key, x, xr, y, yr, cx, cy in _MAP:
        col = BRAND_COLORS.get(key, "#6B7A90")
        fig.add_shape(type="rect", x0=xr[0], x1=xr[1], y0=yr[0], y1=yr[1], line=dict(color=col, width=1.5, dash="dash"), fillcolor=_rgba(col, 0.12), layer="below")
        fig.add_scatter(x=[x], y=[y], mode="markers+text", text=[f"<b>{name}</b>"], textposition="top right", showlegend=False, textfont=dict(size=12, color="#191919"),
                        marker=dict(size=16, color=col, line=dict(width=2, color="#fff")),
                        hovertemplate=f"<b>{name}</b><br>Clinical to appearance: {x} (range {xr[0]} to {xr[1]}, {cx} confidence)"
                                      f"<br>Open market to ECP-anchored: {y} (range {yr[0]} to {yr[1]}, {cy} confidence)<extra></extra>")
    for txt, x, y, anc in (("CLINICAL, ECP-ANCHORED", 0.1, 9.85, "left"), ("FASHION, ECP-ANCHORED", 9.9, 9.85, "right"),
                           ("CLINICAL, OPEN MARKET", 0.1, 0.15, "left"), ("FASHION, OPEN MARKET", 9.9, 0.15, "right")):
        fig.add_annotation(x=x, y=y, text=txt, showarrow=False, xanchor=anc, font=dict(size=10, color="#94A3B8"))
    fig.add_vline(x=5, line=dict(color="#CBD5E1", width=1))
    fig.add_hline(y=5, line=dict(color="#CBD5E1", width=1))
    fig.update_xaxes(range=[0, 10], dtick=1, title="Eye-health and clinical promise (0) to appearance and fashion promise (10)", showgrid=False)
    fig.update_yaxes(range=[0, 10], dtick=1, title="Open market (0) to ECP-anchored (10)", showgrid=False)
    fig.update_layout(height=520)
    return fig


def _render_map() -> None:
    ui.plot(_map_figure(), "MyACUVUE sits clinical and ECP-anchored; Olens sits at the opposite corner (estimates).", "dir",
            "Brand promise and structure, not consumer perception. Dot = estimate; dashed box = evidence range. Hover for confidence.",
            bases="Desk-research estimates (Research runs 1 to 4), not a sample")
    with st.expander("Show the scores behind the map", expanded=False):
        st.markdown(
            """
| Brand | X: clinical (0) to appearance (10) | Y: open market (0) to ECP-anchored (10) | Confidence X / Y |
|---|---|---|---|
| MyACUVUE | 2 (range 1 to 4) | 8 (range 7 to 9) | Medium / Medium |
| CooperVision | 1 (0 to 2) | 6 (4 to 8) | Medium / Low |
| Alcon | 3 (2 to 4) | 7 (5 to 8) | Low / Low |
| Bausch + Lomb | 3 (2 to 5) | 4 (2 to 6) | Low |
| Olens | 9 (8 to 10) | 2 (1 to 4) | Medium / Low |

Evidence notes and axis rationale: **Deep dive** tab, section 9a.
"""
        )


def render() -> None:
    st.caption("Four Research runs triangulated with scraped data, at 1 Oct 2026. Static; source IDs in Sources.")
    names = ["Map"] + [label for label, _ in PAGES]
    tabs = st.tabs(names, on_change="rerun", key="positioning_subtabs")
    with tabs[0]:
        if tabs[0].open:
            _render_map()
    for tab, (label, fname) in zip(tabs[1:], PAGES):
        with tab:
            if not tab.open:
                continue
            text = _read(fname)
            if text is None:
                st.info(f"{fname} not found in the analysis folder.")
            elif fname.startswith("4_"):
                _render_category_users(text)
            else:
                st.markdown(text)
