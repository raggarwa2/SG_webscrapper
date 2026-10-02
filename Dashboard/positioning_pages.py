"""Positioning Analysis tab: renders the markdown deliverables in ../analysis/ (static, read-only).

The files are written by the triangulation analysis of Research runs 1 to 4 and the scraped data
(see analysis/00_source_log.md). Nothing here queries the databases.
"""
import re
from pathlib import Path

import plotly.graph_objects as go
import streamlit as st

import ui

_DIR = Path(__file__).resolve().parent.parent / "analysis"

# (sub-tab label, file)
PAGES = [
    ("Executive brief", "1_executive_brief.md"),
    ("Hypotheses", "3_hypothesis_table.md"),
    ("Deep dive", "2_deep_dive_report.md"),
    ("Category users & barriers", "4_persona_barrier_framework.md"),
    ("Sources", "00_source_log.md"),
]


def _read(name: str) -> str | None:
    try:
        text = (_DIR / name).read_text(encoding="utf-8")
    except OSError:
        return None
    # Links to sibling files do not work inside the app; keep the label only.
    return re.sub(r"\[([^\]]+)\]\((?:[^)]*\.(?:md|svg))\)", r"\1", text)


STAGES = ["Awareness", "Engagement", "Consideration", "Trial", "Purchase", "Repeat / Retention"]
# Category user strips: (short barrier label, level). Level = confidence that the barrier exists, taken from the
# "Barriers by stage" tables in 4_persona_barrier_framework.md: 3 High, 2 Medium, 1 Low, 0 no corroborated
# evidence, -1 not applicable. Where a cell lists several barriers, the highest behavioural confidence is used.
STRIPS = [
    [("No corroborated barrier", 0), ("OTP, login and eligibility gating", 2), ("Cross-channel price comparison", 2),
     ("No Singapore evidence", 0), ("Points only at chosen store; other buys earn nothing", 2),
     ("Dryness, store-binding, low app value", 2)],
    [("No Singapore evidence", 0), ("No evidence", 0), ("Fear of infection and lens loss", 2),
     ("Handling difficulty; thin teaching", 2), ("Own-brand price gap; reward range", 2),
     ("About 1 in 4 stop in year one (non-SG)", 2)],
    [("Few told they are candidates; provider-led info", 2), ("No evidence", 0),
     ("Fear of touching eye; easy cosmetic access; parent safety doubts", 2), ("No Singapore evidence", 0),
     ("Cosmetic buying outside the ECP channel", 1), ("Not applicable", -1)],
]
# Brand palette from colors.md: teal ramp for confidence, greys for no evidence / not applicable.
_COLORS = {-1: "#CCCCCC", 0: "#F8F8F8", 1: "#B9DBE2", 2: "#178197", 3: "#0A5F72"}
_AXIS_FONT_COLOR = "#191919"  # text black from colors.md, so axis labels stay readable


def _cell_text_color(lvl: int) -> str:
    return "#FFFFFF" if lvl >= 2 else "#191919" if lvl == 1 else "#555555"


def _strip(idx: int) -> None:
    import textwrap
    cells = STRIPS[idx]
    fig = go.Figure()
    for i, (label, lvl) in enumerate(cells):
        fig.add_shape(type="rect", x0=i + 0.03, x1=i + 0.97, y0=0, y1=1, fillcolor=_COLORS[lvl],
                      line=dict(width=0), layer="below")
        fig.add_annotation(x=i + 0.5, y=0.5, showarrow=False, align="center",
                           text="<br>".join(textwrap.wrap(label, 17)),
                           font=dict(size=12, color=_cell_text_color(lvl)))
    fig.update_xaxes(range=[0, 6], tickmode="array", tickvals=[i + 0.5 for i in range(6)], ticktext=STAGES,
                     side="top", showgrid=False, zeroline=False, tickfont=dict(size=13, color=_AXIS_FONT_COLOR))
    fig.update_yaxes(range=[0, 1], visible=False)
    fig.update_layout(height=170, margin=dict(l=0, r=0, t=34, b=0), paper_bgcolor="rgba(0,0,0,0)",
                      plot_bgcolor="rgba(0,0,0,0)")
    st.plotly_chart(fig, width="stretch", key=f"persona_strip_{idx}")
    st.caption("Darker = stronger confidence the barrier exists; grey = no evidence or n/a. Not how many people.")


def _overview() -> None:
    """One chart: barrier confidence by stage for all three category users (same data as the strips)."""
    import textwrap
    names = ["Existing wearers", "New wearers", "Active considerers"]
    fig = go.Figure()
    for r, (name, cells) in enumerate(zip(names, STRIPS)):
        y0 = 2 - r
        for i, (label, lvl) in enumerate(cells):
            fig.add_shape(type="rect", x0=i + 0.03, x1=i + 0.97, y0=y0 + 0.04, y1=y0 + 0.96,
                          fillcolor=_COLORS[lvl], line=dict(width=0), layer="below")
            fig.add_annotation(x=i + 0.5, y=y0 + 0.5, showarrow=False, align="center",
                               text="<br>".join(textwrap.wrap(label, 17)),
                               font=dict(size=11, color=_cell_text_color(lvl)))
    fig.update_xaxes(range=[0, 6], tickmode="array", tickvals=[i + 0.5 for i in range(6)], ticktext=STAGES,
                     side="top", showgrid=False, zeroline=False, tickfont=dict(size=13, color=_AXIS_FONT_COLOR))
    fig.update_yaxes(range=[0, 3], tickmode="array", tickvals=[2.5, 1.5, 0.5], ticktext=names,
                     showgrid=False, zeroline=False, tickfont=dict(size=13, color=_AXIS_FONT_COLOR))
    fig.update_layout(height=430, margin=dict(l=0, r=0, t=34, b=0), paper_bgcolor="rgba(0,0,0,0)",
                      plot_bgcolor="rgba(0,0,0,0)")
    ui.takeaway("Consideration has barrier evidence for all three users; Awareness and Trial are thin in Singapore.", "fact")
    st.plotly_chart(fig, width="stretch", key="persona_overview")
    st.caption("Darker = stronger confidence the barrier exists; grey = no evidence or n/a. Not how many people. Detail below.")


def _render_personas(text: str) -> None:
    nl = chr(10)
    lines, buf, persona = text.split(nl), [], -1
    def flush():
        if buf:
            st.markdown(nl.join(buf)); buf.clear()
    i = 0
    while i < len(lines):
        ln = lines[i]
        if ln.startswith("## Category user"):
            persona += 1
            if persona == 0:  # chart sits after the page title and intro, before the first profile
                flush()
                _overview()
        if ln.strip() == "**Barriers by stage**" and 0 <= persona < len(STRIPS):
            flush()
            ui.takeaway(
                ("Existing wearers: store-binding and low app value carry medium-confidence barriers." if persona == 0 else
                 "New wearers: handling difficulty and own-brand price gaps carry medium-confidence barriers." if persona == 1 else
                 "Considerers: provider-led info and cosmetic access carry medium-confidence barriers."), "fact")
            _strip(persona)
            i += 1
            tbl = []
            while i < len(lines) and (lines[i].startswith("|") or not lines[i].strip()):
                if lines[i].startswith("|"):
                    tbl.append(lines[i])
                i += 1
            with st.expander("Show barrier table with evidence and IDs"):
                st.markdown(nl.join(tbl))
            continue
        buf.append(ln)
        i += 1
    flush()


def _render_map() -> None:
    try:
        svg = (_DIR / "perceptual_map.svg").read_text(encoding="utf-8")
    except OSError:
        st.info("perceptual_map.svg not found in the analysis folder.")
        return
    ui.takeaway("MyACUVUE sits clinical and ECP-anchored; Olens sits at the opposite corner (estimates).", "dir")
    st.caption("Brand promise and structure, not consumer perception. Dots are estimates; dashed boxes show evidence range.")
    # st.html strips <svg>; st.image renders SVG text. Fixed light colours via the SVG's own fallbacks.
    st.image(svg, width="stretch")
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
                _render_personas(text)
            else:
                st.markdown(text)
