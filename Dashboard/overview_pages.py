"""Summary and Evidence & Stage 2 pages (Stage 1 EBI read-out; see EBI_insights_plan.md).

The snapshot and the finding cards are live (see insights.snapshot and summary_facts.build). Only two findings stay as dated text.
"""
import html

import pandas as pd
import streamlit as st

import ebi
import ui

_GUIDE = [
    ("GM, Singapore", "Where do we stand against competitors, is the category growing, what are the compliance risks?",
     "Market & Channel", "Competitors, Category trade, Brand protection"),
    ("CRM owner", "Why don't people register, where is the app friction, what does the retailer link look like?",
     "Journey & barriers", "Journey & barriers, Retailers (Market & Channel)"),
    ("Marketing", "How loud is each brand by platform, what do people say, what are competitors posting?",
     "Conversation & content", "All sources; Brand Health for sentiment"),
    ("Anyone", "How is ACUVUE doing against the other brands overall?",
     "Brand Health", "Overview, Sentiment"),
]

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
_TAKE_STYLE = {"Where Acuvue stands": ("flag", "info"), "Biggest gap to fix": ("wrench", "warn"),
               "Link to registration": ("link", "neg"), "What to test": ("flask", "info")}


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


def _kpi(icon: str, label: str, value: str, sub: str, tone: str, sub_icon: str = "", sub_tone: bool = False) -> str:
    small = " sm" if len(value) > 14 else ""
    sub_html = (f'<div class="s{" t" if sub_tone else ""}">{ui.icon(sub_icon)}{html.escape(sub)}</div>' if sub else "")
    return (f'<div class="sx-kpi tone-{tone}"><span class="sx-ico">{ui.icon(icon)}</span><div class="tx">'
            f'<div class="l">{html.escape(label)}</div><div class="v{small}">{html.escape(value)}</div>{sub_html}</div></div>')


def _render_snapshot(snap: dict) -> None:
    """Acuvue-first executive snapshot: six tiles, then the brand comparison beside three takeaways."""
    tr, app, top, vp = snap["trend"], snap["app"], snap["top_reason"], snap["vs_peers"]
    score = snap["score"]

    delta = tr["delta"]
    health_tone = {"Healthy": "pos", "Mixed": "warn", "At risk": "neg"}.get(snap["band"], "info")
    app_share = app["negative"] / app["n"] * 100 if app else 0
    tiles = [
        _kpi("heart", "Brand health", f"{score:.0f}" if score is not None else "n/a", snap["band"], health_tone, sub_tone=True),
        _kpi("trophy", "Pooled sentiment vs peers",
             f"{vp['focus_pn']:.0f}% vs {vp['peer_pn']:.0f}%" if vp else "n/a",
             ("level with peers, within chance" if not vp["distinct"] else ("ahead of peers" if vp["gap"] > 0 else "behind peers")) if vp else "too few items",
             "info" if not vp or not vp["distinct"] else ("pos" if vp["gap"] > 0 else "neg")),
        _kpi("trend-up" if (delta or 0) >= 0 else "trend-down", "Acuvue sentiment, last 90 days",
             f"{tr['recent']:.0f}%" if delta is not None else "Too few",
             f"{delta:+.1f}pp vs prev 90d" if delta is not None else f"n={tr['n_recent']} / {tr['n_prev']}, need {ebi.MIN_N}",
             "info" if delta is None else "pos" if delta >= 0 else "neg", sub_tone=delta is not None),
        _kpi("pie", "Share of voice", f"{snap['sov']:.0f}%", "of analysed brand items", "info"),
        _kpi("alert", "Top complaint", top["reason"] if top is not None else "n/a",
             f"{int(top['brand_k'])} of {snap['n_focus_neg']} negative items" if top is not None else "", "warn"),
        _kpi("phone", "MyACUVUE app", f"{app_share:.0f}% negative" if app else "n/a",
             f"{app['negative']} of {app['n']} reviews" if app else "", "neg" if app_share >= 50 else "warn"),
    ]
    _html(f'<div class="sx-kw"><div class="sx-kpis">{"".join(tiles)}</div></div>')

    left, right = st.columns([3, 2], gap="medium")
    with left:
        st.dataframe(
            snap["table"], hide_index=True, width="stretch",
            column_config={
                "Health score": st.column_config.ProgressColumn("Health score", min_value=0, max_value=100, format="%.0f"),
                "Share of voice %": st.column_config.NumberColumn("Share of voice", format="%.0f%%"),
                "Median price (SGD)": st.column_config.NumberColumn("Median price", format="S$%.0f"),
                "Price vs Acuvue %": st.column_config.NumberColumn("Price vs Acuvue", format="%+.0f%%"),
            },
        )
        st.caption(f"Health = % positive or neutral, sqrt(n)-weighted over sources with 5+ items. Price = compliant, de-duplicated listings. "
                   f"Directional where an Acuvue base is under {ebi.MIN_N}.")
    with right:
        cards = ""
        for head, lines in snap["takeaways"]:
            icon, tone = _TAKE_STYLE.get(head, ("target", "info"))
            cards += (f'<div class="sx-take tone-{tone}"><span class="sx-ico">{ui.icon(icon)}</span><div>'
                      f'<div class="h">{html.escape(head)}</div><div class="b">{html.escape(" ".join(lines))}</div></div></div>')
        _html(cards)


def render_summary(snap: dict | None = None, findings: list | None = None) -> None:
    thin = ('<div class="sx-meta"><span class="sx-pill warn">' + ui.icon("alert") + 'Directional: thin Acuvue base</span></div>'
            if snap and snap["thin"] else "")
    _html('<div class="sx-head"><div class="eb">Summary</div>'
          f'<h2>{ui.chip("fact")}The app is poorly rated, imports are down and lenses are listed online</h2>{thin}</div>')

    if snap:
        _render_snapshot(snap)

    # a finding with n under ebi.MIN_N stays on its detail tab; limitations stay on Evidence & Stage 2
    cards = [f for f in (findings or []) if not _is_thin(f) and f["label"] != "Needs internal data"]

    key = "".join(f'<span class="sx-tag tone-{_BADGE_TONE[k]}">{ui.icon(_BADGE_ICON[k])}{k}</span><span>{t}</span>'
                  for k, t in (("Market fact", "counted directly"), ("Directional", "patterns, not prevalence")))
    ui.section(f"{len(cards)} findings from Stage 1", "Percentages shown only when n&ge;30. Nothing here measures registration or conversion.")
    _html(f'<div class="sx-key">{key}</div>')

    for r in range(0, len(cards), 3):
        for col, (i, f) in zip(st.columns(3, gap="small"), list(enumerate(cards))[r:r + 3]):
            with col:
                _finding_card(i, f)

    with st.expander(":material/help: Which tab answers my question?"):
        st.dataframe(
            pd.DataFrame(_GUIDE, columns=["Reader", "Typical question", "Start in", "Then look at"]),
            hide_index=True, width="stretch",
        )


def render_evidence() -> None:
    ui.subheader("Five hypotheses need Stage 2 data that EBI cannot supply", "What EBI shows, and what would test each.", "Next steps", kind="fact")
    st.dataframe(
        pd.DataFrame(_HYPOTHESES, columns=["Hypothesis", "What EBI shows", "Stage 2 data that would test it"]),
        hide_index=True, width="stretch",
    )
    st.caption("Barrier types from the Journey & barriers tab feed the Stage 2 survey. Open J&J items: EBI_insights_plan.md.")
