"""Positioning Analysis tab: renders the markdown deliverables in ../analysis/ (static, read-only).

The files are written by the triangulation analysis of Research runs 1 to 4 and the scraped data
(see analysis/00_source_log.md). Nothing here queries the databases.
"""
import re
from pathlib import Path

import streamlit as st

import ui

_DIR = Path(__file__).resolve().parent.parent / "analysis"

# (sub-tab label, file)
PAGES = [
    ("Executive brief", "1_executive_brief.md"),
    ("Hypotheses", "3_hypothesis_table.md"),
    ("Deep dive", "2_deep_dive_report.md"),
    ("Category users", "4_persona_barrier_framework.md"),
    ("Sources", "00_source_log.md"),
]


def _read(name: str) -> str | None:
    try:
        text = (_DIR / name).read_text(encoding="utf-8")
    except OSError:
        return None
    # Links to sibling files do not work inside the app; keep the label only.
    return re.sub(r"\[([^\]]+)\]\((?:[^)]*\.(?:md|svg))\)", r"\1", text)


def _render_personas(text: str) -> None:
    """Profiles, needs, language and the cross-segment summary. The barrier-by-stage view moved to Journey & barriers
    (section 4, Research check), where it sits next to the scraped comments; the source tables stay here, collapsed."""
    nl = chr(10)
    lines, buf = text.split(nl), []
    def flush():
        if buf:
            st.markdown(nl.join(buf)); buf.clear()
    st.info("Barriers by stage are charted against the scraped comments in Journey & barriers > 4 · Research check. "
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
