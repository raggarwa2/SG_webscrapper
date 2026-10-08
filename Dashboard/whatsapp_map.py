"""
WhatsApp message map: for each barrier type in the public evidence, where in the journey it shows up for
ACUVUE, how much evidence there is, whether a WhatsApp message can address it, and a draft message angle to test.

Evidence is live (journey frame + barrier labels from the shared list, model-tagged where available). The message angles and draft copy are
hypotheses written for the CRM owner, not findings: nothing scraped here measures registration or conversion.
Draft copy needs J&J brand, legal and PDPA (consent) review before use.
"""

import pandas as pd
import streamlit as st

import barrier_taxonomy
import ebi
import insights
import ui
from sg_common import JOURNEY_STAGES

# Can a WhatsApp message address it? Directly = the message itself removes the barrier; Partly = it can inform or
# route but the fix sits elsewhere (product, store, price); Not really = little a message can do.
_WEIGHT = {"Directly": 1.0, "Partly": 0.5, "Not really": 0.25}

PLAYBOOK = {
    "Registration / login friction": {
        "can": "Directly",
        "angle": "Offer to finish sign-up in chat, with a human fallback when the app or OTP fails.",
        "draft": "Trouble signing up to MyACUVUE? Reply HELP and we will walk you through it, or register right here in this chat.",
        "test": "Registration completion: chat-assisted vs app-only sign-up.",
        "guardrail": "Do not ask for NRIC or full date of birth in chat; follow PDPA.",
    },
    "App utility & support": {
        "can": "Directly",
        "angle": "Send lens-change and reorder reminders in chat, and answer 'where is my order or points' without opening the app.",
        "draft": "Time to reorder? Reply REORDER and we will send your usual lenses to your chosen store, or reply HELP to ask us anything.",
        "test": "Reorder rate among people who opt in to reminders vs those who do not.",
        "guardrail": "Opt-in only; no health or product-performance claims in reminders.",
    },
    "Loyalty & rewards": {
        "can": "Directly",
        "angle": "Explain points in plain language: balance, expiry, where they can be used.",
        "draft": "Your MyACUVUE points, simply explained: reply POINTS to see your balance and where you can use it.",
        "test": "Replies to a balance check; repeat-purchase rate among those who check.",
        "guardrail": "Only state rules that J&J has confirmed. Do not promise points moving between stores.",
    },
    "Unwanted messaging / privacy": {
        "can": "Directly",
        "angle": "Let people choose how often they hear from you before sending anything promotional.",
        "draft": "You decide how often we message you. Reply WEEKLY, MONTHLY or STOP at any time.",
        "test": "Opt-out rate by frequency choice.",
        "guardrail": "Explicit opt-in first; honour STOP at once; PDPA and Do Not Call rules apply.",
    },
    "Product experience": {
        "can": "Partly",
        "angle": "Wearing tips; route comfort complaints to an eye-care professional.",
        "draft": "Lenses feeling less comfortable than they should? Reply TIPS for a short wearing guide. If your eyes feel uncomfortable, please see your eye-care professional.",
        "test": "Tip-guide opens and replies among people who report discomfort.",
        "guardrail": "No medical advice or product-performance claims; keep the 'see your professional' line.",
    },
    "Fear / handling difficulty": {
        "can": "Partly",
        "angle": "Handling tips for new wearers: putting in, taking out, and who to ask.",
        "draft": "New to contact lenses? Reply TIPS for a short guide to putting in and taking out your lenses. If anything feels wrong, please see your eye-care professional.",
        "test": "Tip-guide opens and replies among first-time registrants.",
        "guardrail": "No medical advice; keep the 'see your professional' line.",
    },
    "Colour & look (cosmetic lenses)": {
        "can": "Partly",
        "angle": "Show colour and fit on real eyes before purchase.",
        "draft": "Not sure which shade suits you? Reply LOOK for a quick guide with real-eye photos.",
        "test": "Guide opens vs purchase of the shades shown.",
        "guardrail": "Check whether the tracked ACUVUE range includes cosmetic lenses before investing here.",
    },
    "Store service & upsell": {
        "can": "Partly",
        "angle": "Set expectations for the fitting visit and give a feedback route.",
        "draft": "Booked a fitting? Here is what to expect and what to bring. Tell us how it went by replying to this chat.",
        "test": "Post-visit feedback rate and themes.",
        "guardrail": "Retailers are separate businesses; do not criticise a named store.",
    },
    "Price & channel cost": {
        "can": "Partly",
        "angle": "Show cost per day and any real trial offer; avoid reactive discounting.",
        "draft": "Wondering about cost? Reply VALUE to see what daily lenses cost per day and any current trial offers.",
        "test": "Offer redemptions; compare with a no-offer control.",
        "guardrail": "Prices and offers must match authorised retailers; no price comparison with named rivals.",
    },
    "Authenticity & quality control": {
        "can": "Directly",
        "angle": "Make authorised-seller proof one tap away.",
        "draft": "Want to check your lenses are genuine? Reply VERIFY for a quick authenticity check and a list of authorised sellers.",
        "test": "Verify requests; reduction in authenticity questions.",
        "guardrail": "Needs a real authorised-seller list from J&J; do not name grey-market sellers.",
    },
    "Lack of professional guidance": {
        "can": "Directly",
        "angle": "Shorten the path from interest to a first fitting: find a professional, book, know what to bring.",
        "draft": "Ready to try ACUVUE? Reply FIT to find an eye-care professional near you and book a fitting.",
        "test": "Fitting bookings from chat vs other channels.",
        "guardrail": "Contact lenses need a valid prescription and fitting; never imply they can be skipped.",
    },
    "Availability & where to buy": {
        "can": "Directly",
        "angle": "Answer 'where can I buy this?' with authorised stockists, in store and online.",
        "draft": "Looking for where to buy? Reply STORE for authorised stockists near you, or ONLINE for approved online shops.",
        "test": "Store-finder use and click-through.",
        "guardrail": "List authorised sellers only.",
    },
}


def _evidence(jf_all: pd.DataFrame, focus: str, peers: list) -> tuple:
    """(rows of negative/mixed/flagged items with a barrier type per row, one frame for the focus brand and one for peers).
    The app is ACUVUE-only, so it is counted for ACUVUE (the message map is about what ACUVUE can fix) and left out of peers."""
    if jf_all is None or jf_all.empty:
        return pd.DataFrame(), pd.DataFrame()
    d = jf_all[(jf_all["sentiment"].isin(["negative", "mixed"])) | (jf_all["is_barrier"] == 1)].copy()
    d = d.drop_duplicates(["source", "brand", "text", "journey_stage"])
    d["reason"] = d["text"].map(barrier_taxonomy.classify)
    d = d.explode("reason")
    d = d[d["reason"] != barrier_taxonomy.OTHER]
    f = d[d["brand"] == focus]
    p = d[d["brand"].isin(peers) & (d["source"] != insights.APP_SOURCE)]
    return f, p


def build(jf_all: pd.DataFrame, focus: str, peers: list) -> pd.DataFrame:
    """One row per barrier type that has ACUVUE evidence, ranked by evidence x how directly WhatsApp can help."""
    f, p = _evidence(jf_all, focus, peers)
    if f.empty:
        return pd.DataFrame()
    # distinct items (an item repeats once per stage), used as the base for shares
    n_f = f.drop_duplicates(["source", "text"]).shape[0]
    n_p = p.drop_duplicates(["source", "brand", "text"]).shape[0] if not p.empty else 0
    rows = []
    for reason, pb in PLAYBOOK.items():
        fr = f[f["reason"] == reason]
        k_f = fr.drop_duplicates(["source", "text"]).shape[0]
        if k_f == 0:
            continue
        pr = p[p["reason"] == reason] if not p.empty else p
        k_p = pr.drop_duplicates(["source", "brand", "text"]).shape[0] if not pr.empty else 0
        stage_counts = fr["journey_stage"].value_counts()
        # modal stage; ties go to the earlier journey stage
        stage = min(stage_counts.index, key=lambda s: (-stage_counts[s], JOURNEY_STAGES.index(s) if s in JOURNEY_STAGES else 99))
        rows.append({
            "Barrier": reason,
            "Send at stage": stage,
            "Acuvue items": k_f,
            "of which app": int(fr[fr["source"] == insights.APP_SOURCE].drop_duplicates("text").shape[0]),
            "Acuvue share": ebi.share(k_f, n_f).split(" (")[0] if n_f >= ebi.MIN_N else f"{k_f} of {n_f}",
            "Peers share": (f"{k_p / n_p * 100:.0f}%" if n_p >= ebi.MIN_N else f"{k_p} of {n_p}"),
            "WhatsApp can help": pb["can"],
            "Message angle": pb["angle"],
            "Draft message": pb["draft"],
            "What to test": pb["test"],
            "Guardrail": pb["guardrail"],
            "_score": k_f * _WEIGHT[pb["can"]],
        })
    df = pd.DataFrame(rows).sort_values("_score", ascending=False).reset_index(drop=True)
    df.insert(0, "Priority", df.index + 1)
    df.attrs["n_focus"], df.attrs["n_peers"] = n_f, n_p
    return df.drop(columns="_score")


def render(jf_all: pd.DataFrame, brands: list) -> None:
    ui.section("WhatsApp message map",
               "Which barrier to answer, at which journey stage, and a draft message to test. Evidence is live; the messages are hypotheses.",
               "Messaging", kind="dir")
    if insights.FOCAL not in brands:
        st.info(f"Select {insights.FOCAL} in the sidebar to see the message map.")
        return
    peers = [b for b in brands if b != insights.FOCAL]
    df = build(jf_all, insights.FOCAL, peers)
    if df.empty:
        st.info("No barrier evidence for Acuvue yet.")
        return
    n_f, n_p = df.attrs["n_focus"], df.attrs["n_peers"]
    items, _ = _evidence(jf_all, insights.FOCAL, peers)

    top = df[df["WhatsApp can help"] == "Directly"].head(3)
    if not top.empty:
        st.markdown("**Start with:** " + "; ".join(f"{r['Barrier']} ({r['Send at stage']})" for _, r in top.iterrows()) + ".")
    st.caption(
        f"Priority = number of Acuvue items on that barrier, weighted by how directly a WhatsApp message can help (directly 1.0, partly 0.5). "
        f"Bases: {n_f} Acuvue negative, mixed or flagged items (app reviews included) and {n_p} peer items (app excluded). "
        f"Shares shown only at {ebi.MIN_N}+ items. Barrier types come from the shared label list (model-tagged where the text was tagged), so read as direction."
    )

    with st.expander("Show the barrier table: evidence, share against peers, message angle", expanded=False):
        st.dataframe(
            df[["Priority", "Barrier", "Send at stage", "Acuvue items", "of which app", "Acuvue share", "Peers share", "WhatsApp can help", "Message angle"]],
            hide_index=True, width="stretch",
        )

    st.markdown("**Draft messages**")
    for _, r in df.head(5).iterrows():
        with st.container(border=True, gap="xsmall"):
            st.markdown(f"**{r['Priority']}. {r['Barrier']}** · send at *{r['Send at stage']}* · WhatsApp can help: {r['WhatsApp can help'].lower()}")
            st.markdown(f"> {r['Draft message']}")
            st.caption(f":material/science: **Test:** {r['What to test']}  ·  :material/shield: **Guardrail:** {r['Guardrail']}")
            q = insights.quotes(items, insights.FOCAL, r["Barrier"], k=2)
            if not q.empty:
                with st.expander("What people said"):
                    for _, x in q.iterrows():
                        st.markdown(f"- “{str(x['text']).strip()}” ({x['source']})")
    st.badge("Directional: hypotheses to test, nothing here measures registration", color="orange", icon=":material/trending_flat:")
    st.caption("Draft copy needs J&J brand, legal and PDPA review. Barrier types with no Acuvue evidence are left out.")

    st.download_button("Download message map (CSV)", df.to_csv(index=False).encode("utf-8"),
                       file_name="whatsapp_message_map_sg.csv", mime="text/csv")
