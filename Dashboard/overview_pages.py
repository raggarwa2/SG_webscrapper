"""Summary and Evidence & Stage 2 pages (Stage 1 EBI read-out; see EBI_insights_plan.md).

The snapshot and the finding cards are live (see insights.snapshot and summary_facts.build). Only two findings stay as dated text.
"""
import html

import streamlit as st

import ebi
import ui

_HYPOTHESES = [
    ("Sign-up and launch problems in the MyACUVUE app put people off registering",
     "App-store reviews (written reviews skew negative: types of friction, not prevalence)",
     "Registration funnel drop-off by step; OTP delivery logs"),
    ("The retailer or loyalty link adds friction",
     "Mostly an app-side complaint in reviews; little on Google Maps",
     "ECP notes, retailer incentives, reorder timing"),
    ("Messaging that mentions the app or points would lift registration",
     "Too few posts mention it to test",
     "Registration by campaign / WhatsApp message; A/B test"),
    ("Grey-market listings undermine the brand",
     "Listings are countable; sales and stock are not",
     "J&J authorised-seller list; sell-through data"),
    ("We are on track for 7% to 14%",
     "Not possible from EBI",
     "Registration records, CRM, locked 'eligible trial consumer' definition"),
]


_BADGE_ICON = {"Market fact": "check", "Directional": "trend-up", "Needs internal data": "lock"}
_BADGE_TONE = {"Market fact": "pos", "Directional": "warn", "Needs internal data": "neg"}
def _html(s: str) -> None:
    st.markdown(s, unsafe_allow_html=True)


def _tag(label: str) -> str:
    return f'<span class="sx-tag tone-{_BADGE_TONE[label]}">{ui.icon(_BADGE_ICON[label])}{html.escape(label)}</span>'


def _is_thin(f: dict) -> bool:
    return f["n"] is not None and ebi.is_thin(f["n"])


def _evidence(detail: list, base: str, where: str) -> None:
    with st.popover("Evidence", icon=":material/search:", type="tertiary", width="content"):
        st.markdown("\n".join(f"- {d}" for d in detail))
        st.caption(f":material/database: **Base:** {base}  ·  :material/arrow_forward: **Detail:** {where}")


def _finding_card(i: int, f: dict) -> None:
    """Compact card: icon, headline figure, one-line headline. The bullets sit behind an Evidence popover."""
    with st.container(border=True, height="stretch", gap="xsmall", key=f"sxc-{i}"):
        _html(f'<div class="sx-card tone-{f["tone"]}"><div class="top"><span class="sx-ico">{ui.icon(f["icon"])}</span>'
              f'<span class="n">{html.escape(f["base_label"])}</span>{_tag(f["label"])}</div>'
              f'<div class="stat">{html.escape(f["stat"])}</div><div class="sl">{html.escape(f["stat_label"])}</div>'
              f'<div class="hd">{html.escape(f["headline"])}</div></div>')
        _evidence(f["detail"], f["base"], f["where"])


def render_cards(findings: list, title: str = "Supporting facts") -> None:
    """The fact cards of the Answer page: three per row, evidence behind a popover. A finding with n under ebi.MIN_N stays on its
    detail page."""
    cards = [f for f in (findings or []) if not _is_thin(f)]
    key = "".join(f'<span class="sx-tag tone-{_BADGE_TONE[k]}">{ui.icon(_BADGE_ICON[k])}{k}</span><span>{t}</span>'
                  for k, t in (("Market fact", "counted directly"), ("Directional", "patterns, not prevalence")))
    ui.section(title, "Shown only where n&ge;15.")
    _html(f'<div class="sx-key">{key}</div>')
    # balanced rows (5 cards -> 3 + 2) so no row ends with an empty slot
    rows = -(-len(cards) // 3)
    sizes = [len(cards) // rows + (1 if k < len(cards) % rows else 0) for k in range(rows)] if rows else []
    start = 0
    for size in sizes:
        for col, (i, f) in zip(st.columns(size, gap="small"), list(enumerate(cards))[start:start + size]):
            with col:
                _finding_card(i, f)
        start += size


def render_evidence() -> None:
    ui.subheader("Five hypotheses need Stage 2 data that scraping cannot supply", "What the data shows, and what would test each.", "Next steps", kind="fact")
    ui.flow_rows(_HYPOTHESES, ("Hypothesis", "What the scraped data shows", "Stage 2 data that would test it"))
    st.caption("Barrier types from Barriers & journey feed the Stage 2 survey. Open J&J items: EBI_insights_plan.md.")
