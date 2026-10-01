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
    ("Sign-up and launch problems in the app put people off registering",
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
    ("The MyACUVUE app is poorly rated and most written complaints are about sign-up and launch",
     "Apple 2.36 stars (70 ratings, 51% 1-star); Google Play 3.32 stars (about 1,100 ratings, 32% 1-star). "
     "Of 77 written 1-2 star reviews, 47 are about sign-up or launch (OTP not arriving, slow date-of-birth entry, "
     "freezes, forced-update loop) and 13 say it broke after an update.",
     "Directional", "77 written reviews", "Barriers > App & friction"),
    ("Barrier comments exist, but only three sources have enough volume to read",
     "191 barrier-flagged comments: app 77, YouTube 59, Reddit 38, KiasuParents 14, Lazada 2, Facebook 1, Instagram 0. "
     "These are types of barrier, not how many customers hit each one.",
     "Directional", "191 comments; 3 sources reach the 30 floor", "Barriers > Journey"),
    ("The retailer link is an app complaint, not a store complaint",
     "Loyalty or points appears in 1 of 262 Google Maps friction reviews, but points and retailer lock-in appear in "
     "21 mentions across the 77 low-rated app reviews. Stores draw complaints on staff and fitting, waits, upsell and stock.",
     "Directional", "262 Maps friction reviews; 77 app reviews", "Market & Channel > Retailers"),
    ("The contact lens category is shrinking",
     "Imports of HS 9001.30 fell 25% in units and 23% in value from 2023 to 2025, with unit price flat. "
     "Trade data is the only source; SingStat has nothing at this product level.",
     "Market fact", "UN Comtrade, 3 years", "Market & Channel > Competitors & category"),
    ("Who is loudest online depends on the measure, and one item often drives it",
     "Olens leads on comments and posts (338 of 873) and Xiaohongshu likes; Alcon leads on YouTube views; ACUVUE leads on "
     "Instagram likes. One video is 90% of ACUVUE's YouTube views; one post is 78% of Alcon's Xiaohongshu likes.",
     "Directional", "Varies by platform", "Social & Messaging"),
    ("Contact lenses are offered for direct online sale, which is illegal in Singapore under the HSA",
     "40 distinct lens listings are flagged, 7 of them ACUVUE. This shows an offer, not a completed sale or genuine stock. "
     "Lens solution (for example RevitaLens) is outside the rule and is compared on price separately.",
     "Market fact", "40 listings", "Market & Channel > Brand protection"),
    ("Brand messaging is too thin to test whether pushing the app works",
     "Only 4 of 120 Facebook and 31 of 158 Instagram brand posts mention the app, registering or points.",
     "Directional", "278 brand posts", "Social & Messaging"),
    ("EBI cannot say whether we are on track for 7% to 14%",
     "There is no registration, CRM or conversion data in the scraped sources. The Stage 2 bridge lists the internal "
     "data and survey that would test each hypothesis.",
     "Needs internal data", "n/a", "Evidence & Stage 2"),
]

_BADGE_COLOR = {"Market fact": "green", "Directional": "orange", "Needs internal data": "red"}


def render_summary() -> None:
    ui.subheader("Summary", "Stage 1 external business intelligence (EBI): a one-time snapshot, data cut-off 2 Oct 2026.", "Start here")
    st.caption(
        "Eight findings. Each says how far to trust it and where the detail lives. A percentage is shown only when its "
        "base is at least 30. Nothing here says anything about registration or conversion."
    )
    for i, (headline, detail, label, base, where) in enumerate(_FINDINGS, 1):
        with st.container(border=True):
            st.markdown(f"**{i}. {headline}**")
            st.write(detail)
            st.badge(label, color=_BADGE_COLOR[label])
            st.caption(f"Base: {base}  ·  Detail: {where}")
    with st.expander("Which tab answers my question?"):
        st.dataframe(
            pd.DataFrame(_GUIDE, columns=["Reader", "Typical question", "Start in", "Then look at"]),
            hide_index=True, width="stretch",
        )


def render_evidence() -> None:
    ui.subheader("Evidence & Stage 2", "What EBI cannot say, and what would test each hypothesis.", "Next steps")
    st.dataframe(
        pd.DataFrame(_HYPOTHESES, columns=["Hypothesis", "What EBI shows", "Stage 2 data that would test it"]),
        hide_index=True, width="stretch",
    )
    st.caption(
        "Barrier types from the Barriers tab are proposed as options for the Stage 2 barrier-attribution survey. "
        "Open items needing J&J are listed in EBI_insights_plan.md."
    )
