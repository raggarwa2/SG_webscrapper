"""Summary and Evidence & Stage 2 pages (Stage 1 EBI read-out; see EBI_insights_plan.md).

Static text: the Summary figures are frozen cut-off values copied from the plan, not live queries.
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


# (headline, detail, evidence label, base, where). Figures are the frozen 2 Oct 2026 cut-off values
# from EBI_insights_plan.md section 2; each is owned by the tab named in `where`.
_FINDINGS = [
    ("The app is poorly rated; most complaints are sign-up and launch",
     ["**Apple:** 2.36 stars (70 ratings, 51% 1-star): half of raters gave the lowest score",
      "**Google Play:** 3.32 stars (about 1,100 ratings, 32% 1-star): better, but still weak",
      "**Sign-up or launch:** 47 of 77 written 1-2 star reviews, 61% (OTP not arriving, slow date-of-birth entry, freezes, forced-update loop)",
      "**Broke after an update:** 13 of 77"],
     "Directional", "77 written reviews", "Journey & barriers > full app detail"),
    ("Barrier comments are spread across sources; only three have enough volume",
     ["**222** barrier-flagged comments in total, 202 without one Instagram post (app reviews are MyACUVUE; YouTube, Reddit and Instagram cover several brands)",
      "**App** 77 | **YouTube** 59 | **Reddit** 38 | **Instagram** 31",
      "**KiasuParents** 14 | **Lazada** 2 | **Facebook** 1",
      "Instagram was 0 at the 2 Oct cut-off (total 191). The 7 Oct refresh added 31, but 20 are replies to a 2021 Alcon Systane eye-drop giveaway where people list symptoms, not purchase barriers; without that post Instagram has 11, under the floor",
      "Use as barrier types to test in Stage 2, not as how many customers hit each"],
     "Directional", "222 comments (202 without one giveaway post); 3 sources reach the 30 floor", "Journey & barriers"),
    ("The retailer link is an app complaint, not a store complaint",
     ["**Google Maps:** loyalty or points in 1 of 262 friction reviews",
      "**App reviews:** points and retailer lock-in in 21 mentions across 77 low-rated reviews: the retailer link is felt in the app, not in store",
      "**Store complaints** are about staff and fitting, waits, upsell and stock"],
     "Directional", "262 Maps friction reviews; 77 app reviews", "Market & Channel > Retailers"),
    ("Lens imports fell about a quarter in 2023-25: the category is likely shrinking",
     ["**Units:** imports of HS 9001.30 down 25%, 2023 to 2025",
      "**Value:** down 23%, with unit price flat: the fall is in volume, not price",
      "**Caveat:** imports are a proxy for demand (Singapore also re-exports); trade data is the only source, SingStat has nothing at this product level"],
     "Market fact", "UN Comtrade, 3 years", "Market & Channel > Competitors & category"),
    ("Who is loudest depends on the measure, and one item often drives it",
     ["**Olens and Acuvue:** level on analysed comments and posts (324 and 321 of 1,112, 29% each, live count on Competitors & category); Olens leads on Xiaohongshu likes",
      "**Alcon:** leads on YouTube views",
      "**ACUVUE:** leads on Instagram likes (157k), but the typical ACUVUE post gets 19 likes against Alcon's 10 (Instagram refreshed 7 Oct)",
      "**Read with care:** one item can dominate. One video is 90% of ACUVUE's YouTube views; one post is 78% of Alcon's Xiaohongshu likes; the 5 biggest posts are 72% of ACUVUE's Instagram likes (ambassador campaign)"],
     "Directional", "Varies by platform", "Conversation & content"),
    ("Lenses are offered for direct online sale, illegal under the HSA",
     ["**40** distinct lens listings flagged, **7** of them ACUVUE (18%): mostly a category-wide problem, not only ours",
      "Shows an offer, not a completed sale or genuine stock",
      "Lens solution (for example RevitaLens) is outside the rule and is compared on price separately"],
     "Market fact", "40 listings", "Market & Channel > Brand protection"),
    ("Few brand posts mention the app, so pushing it cannot be tested yet",
     ["**Facebook:** 4 of 120 brand posts (3%) mention the app, registering or points",
      "**Instagram:** 31 of 158 collected posts (20%) at the 2 Oct cut-off",
      "**Refreshed 7 Oct, not recounted:** Facebook now 330 posts (was 120); Instagram now 518 collected, 414 kept after removing off-brand and non-Singapore posts (the 158 counted every post collected; only 65 of them were kept)"],
     "Directional", "278 collected posts at 2 Oct (Facebook 120 + Instagram 158)", "Conversation & content"),
    ("EBI cannot say if we are on track for 7% to 14%",
     ["No registration, CRM or conversion data in the scraped sources",
      "The Stage 2 bridge lists the internal data and survey that would test each hypothesis"],
     "Needs internal data", "n/a", "Evidence & Stage 2"),
]

# Per finding, in _FINDINGS order: (icon, headline figure, what the figure counts, tone, base label, n). The figures repeat
# the frozen cut-off values quoted in the finding's own bullets. n is the count the figure rests on; None for official
# statistics or a limitation (no sample). A finding with n under ebi.MIN_N is left off the Summary (it stays on its detail
# tab); a "Needs internal data" finding is a limitation, not a card (it is covered on Evidence & Stage 2).
_CARD_META = [
    ("phone", "61%", "of 77 low-rated app reviews cite sign-up or launch", "neg", "n=77 app reviews", 77),
    ("ban", "222", "barrier comments; only 3 sources reach n=30", "warn", "n=222 comments", 222),
    ("cart", "1 vs 21", "loyalty mentions: Maps friction reviews vs app reviews", "info", "n=262 Maps reviews", 262),
    ("trend-down", "-25%", "lens imports in units, 2023 to 2025", "neg", "UN Comtrade", None),
    ("megaphone", "29% each", "share of voice, Olens and Acuvue; one item often drives it", "info", "n=1,112 items", 1112),
    ("shield", "40", "lens listings offered online, 7 of them ACUVUE", "neg", "n=40 listings", 40),
    ("message", "3%", "of Facebook brand posts mention the app (4 of 120)", "warn", "n=4 posts", 4),
    ("lock", "Not testable", "7% to 14% target needs internal data", "info", "no data", None),
]

_BADGE_ICON = {"Market fact": "check", "Directional": "trend-up", "Needs internal data": "lock"}
_BADGE_TONE = {"Market fact": "pos", "Directional": "warn", "Needs internal data": "neg"}
_TAKE_STYLE = {"Where Acuvue stands": ("flag", "info"), "Biggest gap to fix": ("wrench", "warn"),
               "Link to registration": ("link", "neg"), "What to test": ("flask", "info")}


def _html(s: str) -> None:
    st.markdown(s, unsafe_allow_html=True)


def _tag(label: str) -> str:
    return f'<span class="sx-tag tone-{_BADGE_TONE[label]}">{ui.icon(_BADGE_ICON[label])}{html.escape(label)}</span>'


def _is_thin(i: int) -> bool:
    n = _CARD_META[i][5]
    return n is not None and ebi.is_thin(n)


def _evidence(detail: list, base: str, where: str) -> None:
    with st.popover("Evidence", icon=":material/search:", type="tertiary", width="content"):
        st.markdown("\n".join(f"- {d}" for d in detail))
        st.caption(f":material/database: **Base:** {base}  ·  :material/arrow_forward: **Detail:** {where}")


def _finding_card(i: int) -> None:
    """Compact card: icon, headline figure, one-line headline. The bullets sit behind an Evidence popover."""
    headline, detail, label, base, where = _FINDINGS[i]
    icon, stat, stat_label, tone, base_label, _ = _CARD_META[i]
    with st.container(border=True, height="stretch", gap="xsmall", key=f"sxc-{i}"):
        _html(f'<div class="sx-card tone-{tone}"><div class="top"><span class="sx-ico">{ui.icon(icon)}</span>'
              f'<span class="n">{html.escape(base_label)}</span>{_tag(label)}</div>'
              f'<div class="stat">{html.escape(stat)}</div><div class="sl">{html.escape(stat_label)}</div>'
              f'<div class="hd">{html.escape(headline)}</div></div>')
        _evidence(detail, base, where)


def _kpi(icon: str, label: str, value: str, sub: str, tone: str, sub_icon: str = "", sub_tone: bool = False) -> str:
    small = " sm" if len(value) > 14 else ""
    sub_html = (f'<div class="s{" t" if sub_tone else ""}">{ui.icon(sub_icon)}{html.escape(sub)}</div>' if sub else "")
    return (f'<div class="sx-kpi tone-{tone}"><span class="sx-ico">{ui.icon(icon)}</span><div class="tx">'
            f'<div class="l">{html.escape(label)}</div><div class="v{small}">{html.escape(value)}</div>{sub_html}</div></div>')


def _render_snapshot(snap: dict) -> None:
    """Acuvue-first executive snapshot: six tiles, then the brand comparison beside three takeaways."""
    v, tr, app, top = snap["verdict"], snap["trend"], snap["app"], snap["top_reason"]
    n_ok = len(snap["table"].dropna(subset=["Health score"]))
    score, rank = snap["score"], v.get("rank")

    delta = tr["delta"]
    health_tone = {"Healthy": "pos", "Mixed": "warn", "At risk": "neg"}.get(snap["band"], "info")
    rank_tone = "pos" if rank and rank <= 2 else "warn" if rank else "info"
    app_share = app["negative"] / app["n"] * 100 if app else 0
    tiles = [
        _kpi("heart", "Brand health", f"{score:.0f}" if score is not None else "n/a", snap["band"], health_tone, sub_tone=True),
        _kpi("trophy", "Rank among brands", f"#{rank} of {v['scored']}" if rank else "n/a", f"{n_ok} brands scored", rank_tone),
        _kpi("trend-up" if (delta or 0) >= 0 else "trend-down", "Sentiment, last 90 days",
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


def render_summary(snap: dict | None = None) -> None:
    thin = ('<div class="sx-meta"><span class="sx-pill warn">' + ui.icon("alert") + 'Directional: thin Acuvue base</span></div>'
            if snap and snap["thin"] else "")
    _html('<div class="sx-head"><div class="eb">Summary</div>'
          f'<h2>{ui.chip("fact")}The app is poorly rated, imports are down and lenses are listed online</h2>{thin}</div>')

    if snap:
        _render_snapshot(snap)

    idx = [i for i in range(len(_FINDINGS)) if not _is_thin(i)]
    cards = [i for i in idx if _FINDINGS[i][2] != "Needs internal data"]   # limitations stay on Evidence & Stage 2

    key = "".join(f'<span class="sx-tag tone-{_BADGE_TONE[k]}">{ui.icon(_BADGE_ICON[k])}{k}</span><span>{t}</span>'
                  for k, t in (("Market fact", "counted directly"), ("Directional", "patterns, not prevalence")))
    ui.section(f"{len(cards)} findings from Stage 1", "Percentages shown only when n&ge;30. Nothing here measures registration or conversion.")
    _html(f'<div class="sx-key">{key}</div>')

    for r in range(0, len(cards), 3):
        for col, i in zip(st.columns(3, gap="small"), cards[r:r + 3]):
            with col:
                _finding_card(i)

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
