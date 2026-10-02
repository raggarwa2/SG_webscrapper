"""Summary and Evidence & Stage 2 pages (Stage 1 EBI read-out; see EBI_insights_plan.md).

Static text: the Summary figures are frozen cut-off values copied from the plan, not live queries.
"""
import pandas as pd
import streamlit as st

import ui

_GUIDE = [
    ("GM, Singapore", "Where do we stand against competitors, is the category growing, what are the compliance risks?",
     "Market & Channel", "Competitors, Category trade, Brand protection"),
    ("CRM owner", "Why don't people register, where is the app friction, what does the retailer link look like?",
     "Barriers", "Journey, App & friction, Retailers (Market & Channel)"),
    ("Marketing", "How loud is each brand by platform, what do people say, what are competitors posting?",
     "Social & Messaging", "All sources; Brand Health for sentiment"),
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
     "Directional", "77 written reviews", "Barriers > App & friction"),
    ("Barrier comments are spread across sources; only three have enough volume",
     ["**191** barrier-flagged comments in total (app reviews are MyACUVUE; YouTube and Reddit cover all brands)",
      "**App** 77 | **YouTube** 59 | **Reddit** 38",
      "**KiasuParents** 14 | **Lazada** 2 | **Facebook** 1 | **Instagram** 0",
      "Use as barrier types to test in Stage 2, not as how many customers hit each"],
     "Directional", "191 comments; 3 sources reach the 30 floor", "Barriers > Journey"),
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
     ["**Olens:** leads on comments and posts (338 of 873, 39%) and on Xiaohongshu likes",
      "**Alcon:** leads on YouTube views",
      "**ACUVUE:** leads on Instagram likes",
      "**Read with care:** one item can dominate. One video is 90% of ACUVUE's YouTube views; one post is 78% of Alcon's Xiaohongshu likes"],
     "Directional", "Varies by platform", "Social & Messaging"),
    ("Lenses are offered for direct online sale, illegal under the HSA",
     ["**40** distinct lens listings flagged, **7** of them ACUVUE (18%): mostly a category-wide problem, not only ours",
      "Shows an offer, not a completed sale or genuine stock",
      "Lens solution (for example RevitaLens) is outside the rule and is compared on price separately"],
     "Market fact", "40 listings", "Market & Channel > Brand protection"),
    ("Few brand posts mention the app, so pushing it cannot be tested yet",
     ["**Facebook:** 4 of 120 brand posts (3%) mention the app, registering or points",
      "**Instagram:** 31 of 158 brand posts (20%)"],
     "Directional", "278 brand posts", "Social & Messaging"),
    ("EBI cannot say if we are on track for 7% to 14%",
     ["No registration, CRM or conversion data in the scraped sources",
      "The Stage 2 bridge lists the internal data and survey that would test each hypothesis"],
     "Needs internal data", "n/a", "Evidence & Stage 2"),
]

_BADGE_COLOR = {"Market fact": "green", "Directional": "orange", "Needs internal data": "red"}


# (section title, caption, indexes into _FINDINGS)
_THEMES = [
    ("Users get stuck at sign-up and launch", "App reviews are MyACUVUE; forum and video comments cover all brands.", (0, 1, 2)),
    ("The category is likely shrinking, and lenses are listed online outside HSA rules", "Imports are down; lenses are offered online outside HSA rules.", (3, 5)),
    ("The social leader depends on the measure, and brands rarely mention registering", "Loudest brand varies by platform; brands rarely mention registering.", (4, 6)),
    ("EBI cannot test the 7% to 14% target without internal data", "Registration and CRM records are needed.", (7,)),
]

_BADGE_ICON = {"Market fact": ":material/verified:", "Directional": ":material/trending_flat:",
               "Needs internal data": ":material/lock:"}


def _finding_card(n: int, headline: str, detail: str, label: str, base: str, where: str) -> None:
    with st.container(border=True, height="stretch", gap="xsmall"):
        st.markdown(f"**{n}. {headline}**")
        st.markdown("\n".join(f"- {d}" for d in detail))
        st.badge(label, color=_BADGE_COLOR[label], icon=_BADGE_ICON[label])
        st.caption(f":material/database: **Base:** {base}  ·  :material/arrow_forward: **Detail:** {where}")


def render_summary() -> None:
    ui.subheader("The app is poorly rated, imports are down and lenses are listed online", "Stage 1 external intelligence (EBI): one snapshot, cut-off 2 Oct 2026.", "Summary", kind="fact")

    # The findings below carry every headline number once; no separate KPI tiles.

    st.markdown(
        ":green-badge[:material/verified: Market fact] counted directly &nbsp; "
        ":orange-badge[:material/trending_flat: Directional] patterns, not prevalence &nbsp; "
        ":red-badge[:material/lock: Needs internal data] not in scraped sources"
    )
    st.caption("% shown only when n\u226530. Nothing here measures registration or conversion.")

    for title, caption, idx in _THEMES:
        ui.section(title, caption)
        cols = st.columns(len(idx) if len(idx) > 1 else 1)
        for col, i in zip(cols, idx):
            with col:
                _finding_card(i + 1, *_FINDINGS[i])

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
    st.caption("Barrier types from the Barriers tab feed the Stage 2 survey. Open J&J items: EBI_insights_plan.md.")
