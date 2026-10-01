"""
App & Barriers page (Stage 1 EBI read-out, plan step 4).

Question: where do users get stuck registering or using the MyACUVUE app, and
what purchase barriers show up in market chatter? Sources: Apple App Store +
Google Play (SG) reviews and rating histograms, store-listing privacy labels, and
the LLM barrier flag on on-topic YouTube / Instagram / Facebook / Reddit comments.

The barrier section is preliminary: journey stage is still tagged per source,
not per comment (evidence-table step not done yet), so it reports flag rates by
brand and source rather than by stage.
"""

import pandas as pd
import plotly.express as px
import streamlit as st

import re

import app_store_signals
import barrier_taxonomy
import ebi
import gmaps_signals
import ui
from sg_common import APP_DB, BRAND_COLORS, read_table

# This page's own theme set (theme -> (regex, stage)). Tightened and extended after a hand-check of all
# 119 reviews against the shared set in app_store_signals.py (bare "point", "code", "account", "data" and
# "notification" misfired; date-of-birth entry, forced-update loops and the single-retailer lock were
# untagged). The shared set is left as it was so the existing Journey tab is unchanged.
THEMES = {
    "App freezes / won't open": (r"freez|frozen|stuck|\bhang|won'?t open|not open|cannot open|can'?t open|couldn'?t be launched|crash|welcome screen|blank|white screen|not working|stopped working|not functioning|doesn'?t work|does not work|app dead|\blagg?(y|ing)\b|server (connection )?error|trouble downloading", "Trial"),
    "Forced-update loop": (r"update.{0,60}(loop|looping|prompt|keeps? (telling|asking|stated))|keeps? (telling|prompting).{0,40}update|(loop|looping) back to app ?store|require me to update", "Trial"),
    "Login / OTP / registration": (r"\botp\b|log ?in|log ?on|sign ?in|password|verif|registrat|register\b|registar|sign ?up|locked out|sms code", "Trial"),
    "Date-of-birth entry": (r"\bdob\b|birth|year of birth|date of birth", "Trial"),
    "Usability": (r"button|search function|log ?out|complicated|confus|interface|\bui\b|hard to|difficult|design|navigation|music|\bslow\b", "Trial"),
    "Points / rewards": (r"\bpoints?\b(?! of)|point system|reward|redeem|redemption|voucher|coupon|\btoken", "Repeat/Retention"),
    "Locked to one retailer": (r"one vendor|change stores?|different store|another place|other retailer|not allowed to use|optical retailer|appointment|preferred registered", "Repeat/Retention"),
    "Marketing / privacy": (r"unsubscribe|spam|advert|\bads?\b|marketing|privacy|nric|fin number|promoting|push notif|notifications on", "Repeat/Retention"),
}
_THEME_RE = {k: re.compile(v[0], re.I) for k, v in THEMES.items()}


def _themes(text) -> list:
    return [k for k, rx in _THEME_RE.items() if rx.search(text if isinstance(text, str) else "")]


_TRIAL_THEMES = {"App freezes / won't open", "Forced-update loop", "Login / OTP / registration",
                 "Date-of-birth entry", "Usability"}
_AFTER_UPDATE = r"after.{0,15}updat|after.{0,15}upgrad|latest update|latest release|you updated|updated the app"
_STORE_NAMES = {"app_store": "Apple App Store", "play_store": "Google Play"}
_SOCIAL = ["YouTube", "Instagram", "Facebook", "Reddit"]


def _star_table(hist: pd.DataFrame) -> pd.DataFrame:
    h = hist.copy()
    h["Store"] = h["store"].map(_STORE_NAMES).fillna(h["store"])
    h["total"] = h.groupby("Store")["count"].transform("sum")
    h["share"] = h["count"] / h["total"] * 100
    return h


def _app_section(rev: pd.DataFrame, hist: pd.DataFrame) -> None:
    ui.section("Store ratings", "Everyone who rated the MyACUVUE app in Singapore, not just those who wrote a review.", "Market fact")
    st.markdown(ebi.tag("fact"), unsafe_allow_html=True)
    if hist.empty:
        st.info("No rating histogram found.")
    else:
        h = _star_table(hist)
        cols = st.columns(4)
        for i, (store, g) in enumerate(h.groupby("Store")):
            n = int(g["count"].sum())
            mean = (g["stars"] * g["count"]).sum() / n
            one = int(g.loc[g["stars"] == 1, "count"].sum())
            cols[i * 2].metric(f"{store}: average", f"{mean:.2f} ★", help=f"From the star histogram, n={n:,} ratings.")
            cols[i * 2 + 1].metric(f"{store}: 1★ share", ebi.share(one, n).split(" (")[0],
                                   help=f"{one:,} of {n:,} ratings are 1 star.")
        fig = px.bar(
            h, x="stars", y="share", color="Store", barmode="group",
            labels={"stars": "Stars", "share": "% of ratings"},
            title="Rating distribution by store (% of all ratings)",
        )
        fig.update_xaxes(dtick=1)
        st.plotly_chart(fig, width="stretch")
        st.caption(
            "Both stores are polarised: most ratings are 5★ or 1★, few in between. Ratings are a mix of people who "
            "never reached registration and people who use the app happily, so read the written reviews below for the why."
        )

    # ---- written reviews ----
    if rev.empty:
        st.info("No written app reviews found.")
        return
    neg = rev[rev["rating"] <= 2]
    pos = rev[rev["rating"] >= 4]
    ui.section(
        "What written reviews complain about",
        f"{len(rev)} written reviews ({int((rev['store'] == 'app_store').sum())} App Store, {int((rev['store'] == 'play_store').sum())} Google Play); "
        f"{len(neg)} are 1–2★. Themes are keyword-tagged and a review can carry several.",
        "Directional",
    )
    st.markdown(ebi.tag("dir"), unsafe_allow_html=True)

    rows = []
    for t, (_, stage) in THEMES.items():
        hit = neg["themes"].map(lambda x, t=t: t in x)
        pos_hit = pos["themes"].map(lambda x, t=t: t in x)
        rows.append({
            "Theme": t, "Stage": stage,
            "1–2★ reviews": int(hit.sum()),
            "Share of 1–2★": ebi.share(int(hit.sum()), len(neg)),
            "In 4–5★ reviews": int(pos_hit.sum()),
        })
    tt = pd.DataFrame(rows).sort_values("1–2★ reviews", ascending=False)
    c1, c2 = st.columns([3, 2])
    with c1:
        fig = px.bar(tt, x="1–2★ reviews", y="Theme", orientation="h", color="Stage",
                     title="Themes in 1–2★ reviews")
        fig.update_layout(yaxis={"categoryorder": "total ascending"})
        st.plotly_chart(fig, width="stretch")
    with c2:
        st.dataframe(tt, hide_index=True, width="stretch")

    on_path = neg["themes"].map(lambda x: bool(_TRIAL_THEMES & set(x)))
    after_upd = neg["full_text"].str.contains(_AFTER_UPDATE, case=False, regex=True, na=False)
    untagged = neg[neg["themes"].map(len) == 0]
    m = st.columns(3)
    m[0].metric("1–2★ reviews on the sign-up / launch path", f"{int(on_path.sum())} of {len(neg)}",
                help="Freezes, forced-update loop, login/OTP/registration, date-of-birth entry or usability themes (Trial stage).")
    m[1].metric("Say it broke after an update", f"{int(after_upd.sum())} of {len(neg)}",
                help="1–2★ reviews matching 'after the update', 'latest update', 'you updated the app' and similar.")
    m[2].metric("1–2★ reviews with no theme", f"{len(untagged)} of {len(neg)}",
                help="Mostly one-liners ('Bad', 'Doesn't work') or non-English text. Listed below so nothing is hidden.")
    ui.insight(
        "The strongest <b>registration</b> signals are OTP not arriving, date-of-birth entry that reviewers call very slow, "
        "and apps that stop opening or loop back to the App Store after an update. "
        "The loyalty signals are points being locked to one retailer and unsubscribe/privacy complaints.",
    )

    with st.expander(f"1–2★ reviews with no theme ({len(untagged)})"):
        st.dataframe(
            untagged[["date", "store", "rating", "full_text"]].rename(
                columns={"date": "Date", "store": "Store", "rating": "★", "full_text": "Review"}),
            hide_index=True, width="stretch",
        )

    # ---- by year ----
    yr = rev.dropna(subset=["date"]).assign(year=lambda d: d["date"].dt.year).groupby("year").agg(
        reviews=("rating", "size"), negative=("rating", lambda s: int((s <= 2).sum()))).reset_index()
    fig = px.bar(yr, x="year", y=["reviews", "negative"], barmode="group",
                 labels={"value": "Written reviews", "year": "", "variable": ""},
                 title="Written reviews per year (all vs 1–2★)")
    st.plotly_chart(fig, width="stretch")
    st.caption("Counts only: yearly bases are too small to show as percentages.")

    # ---- top complaints, quoted ----
    st.markdown("**Most-endorsed complaints** (by thumbs-up)")
    top = neg.sort_values("thumbs_up", ascending=False).head(10)
    top = top.assign(Themes=top["themes"].map(", ".join))
    st.dataframe(
        top[["date", "store", "app_version", "rating", "thumbs_up", "full_text", "Themes"]].rename(columns={
            "date": "Date", "store": "Store", "app_version": "Version", "rating": "★",
            "thumbs_up": "Thumbs-up", "full_text": "Review"}),
        hide_index=True, width="stretch",
    )

    # ---- developer replies ----
    st.caption(
        "Developer replies: none are present in the scrape (0 of "
        f"{len(rev)} reviews). That may be a scrape limitation, so it does not show that J&J never replies."
    )


def _retailer_link_section(app_rev: pd.DataFrame) -> None:
    ui.section(
        "The retailer link: what app users and retailer reviewers each complain about",
        "App reviews of MyACUVUE next to Google Maps reviews of the optical chains that sell it.",
        "Directional",
    )
    st.markdown(ebi.tag("dir"), unsafe_allow_html=True)
    gm, _ = gmaps_signals.load_gmaps()
    neg = app_rev[app_rev["rating"] <= 2] if not app_rev.empty else app_rev
    left, right = st.columns(2)

    k_lock = k_pts = 0
    with left:
        st.markdown("**In the app (1–2★ reviews)**")
        if neg.empty:
            st.info("No app reviews.")
        else:
            k_lock = int(neg["themes"].map(lambda x: "Locked to one retailer" in x).sum())
            k_pts = int(neg["themes"].map(lambda x: "Points / rewards" in x).sum())
            c = st.columns(2)
            c[0].metric("Locked to one retailer / store", f"{k_lock} of {len(neg)}")
            c[1].metric("Points / rewards", f"{k_pts} of {len(neg)}")
            q = app_rev[app_rev["themes"].map(lambda x: "Locked to one retailer" in x)]
            st.dataframe(
                q[["date", "store", "rating", "full_text"]].rename(
                    columns={"date": "Date", "store": "Store", "rating": "★", "full_text": "Review"}),
                hide_index=True, width="stretch", height=260,
            )

    fr = pd.DataFrame()
    lp = 0
    with right:
        st.markdown("**At the retailer (Google Maps friction reviews)**")
        if gm.empty:
            st.info("No Google Maps data.")
        else:
            fr = gm[gm["is_friction"] == 1]
            lp = int(fr["theme_list"].map(lambda x: "loyalty_points" in x).sum())
            cl = gm[gm["contact_lens"] == 1]
            cl_fr = int(cl["is_friction"].sum())
            c = st.columns(2)
            c[0].metric("Friction reviews, all", ebi.share(len(fr), len(gm)).split(" (")[0],
                        help=f"{len(fr):,} of {len(gm):,} reviews describe a negative experience.")
            c[1].metric("Friction, contact-lens reviews", ebi.share(cl_fr, len(cl)).split(" (")[0],
                        help=f"{cl_fr} of {len(cl)} contact-lens reviews (strict filter: lens-related and a contact-lens keyword).")
            themes = {label: int(fr["theme_list"].map(lambda x, k=key: k in x).sum())
                      for key, label in gmaps_signals.THEME_LABELS.items()}
            tdf = pd.DataFrame({"Theme": list(themes), "Friction reviews": list(themes.values())}).sort_values(
                "Friction reviews", ascending=False)
            fig = px.bar(tdf, x="Friction reviews", y="Theme", orientation="h", title="Retailer friction themes (all reviews)")
            fig.update_layout(yaxis={"categoryorder": "total ascending"})
            st.plotly_chart(fig, width="stretch")

    if not fr.empty and not neg.empty:
        top = tdf.head(3)["Theme"].str.lower().tolist()
        ui.insight(
            f"Loyalty/points comes up in <b>{lp}</b> of {len(fr)} retailer friction reviews, but points and retailer lock-in "
            f"come up in <b>{k_pts + k_lock}</b> mentions across {len(neg)} 1–2★ app reviews. Retailer reviewers mostly "
            f"complain about {', '.join(top)}. The retailer link shows up as an app-side complaint, not a retailer-side one."
        )
    st.caption(
        "Maps reviews are about the retailer, not about ACUVUE or the app, and only the 100 newest per outlet were pulled "
        "(they skew positive). The two sets are different people, so this shows where each side complains, not that one "
        "causes the other."
    )


def _barrier_types_section(jf: pd.DataFrame) -> None:
    ui.section(
        "What kind of barrier: one list across every source",
        "Flagged barrier comments from the app, YouTube, Reddit, KiasuParents, Lazada and Facebook sorted into the same types.",
        "Directional",
    )
    st.markdown(ebi.tag("dir"), unsafe_allow_html=True)
    if jf.empty:
        st.info("No journey data loaded.")
        return
    b = jf[jf["is_barrier"] == 1].drop_duplicates(subset=["source", "brand", "text"]).copy()
    if b.empty:
        st.info("No barrier-flagged comments.")
        return
    brands = sorted(b["brand"].dropna().unique())
    pick = st.selectbox("Brand", ["All brands"] + brands, key="friction_types_brand")
    if pick != "All brands":
        b = b[b["brand"] == pick]
    if b.empty:
        st.info("No barrier-flagged comments for this brand.")
        return
    b["types"] = b["text"].map(barrier_taxonomy.classify)
    ex = b.explode("types")
    n_src = b.groupby("source").size()
    order = list(barrier_taxonomy.TYPES) + [barrier_taxonomy.OTHER]
    tab = ex.groupby(["types", "source"]).size().unstack(fill_value=0)
    tab = tab.reindex([t for t in order if t in tab.index])
    tab["All sources"] = tab.sum(axis=1)
    st.dataframe(tab.reset_index().rename(columns={"types": "Barrier type"}), hide_index=True, width="stretch")
    st.caption(
        "Flagged comments per source: " + ", ".join(f"{s} {int(n)}" for s, n in n_src.items())
        + f". A comment can carry several types, so columns add to more than the comment count."
    )

    big = [s for s, n in n_src.items() if n >= ebi.MIN_N]
    if big:
        long = ex[ex["source"].isin(big)].groupby(["source", "types"]).size().reset_index(name="k")
        long["share"] = long.apply(lambda r: r["k"] / n_src[r["source"]] * 100, axis=1)
        fig = px.bar(long, x="share", y="types", color="source", barmode="group", orientation="h",
                     labels={"share": "% of flagged comments", "types": "", "source": "Source"},
                     category_orders={"types": order},
                     title="Share of each source's flagged comments, by barrier type")
        fig.update_layout(yaxis={"autorange": "reversed"})
        st.plotly_chart(fig, width="stretch")
        small = [f"{s} ({int(n)})" for s, n in n_src.items() if n < ebi.MIN_N]
        st.caption(
            f"Shares are shown only for sources with at least {ebi.MIN_N} flagged comments"
            + (f"; counts only for {', '.join(small)}." if small else ".")
        )
    else:
        st.caption(f"No source has {ebi.MIN_N} flagged comments for this brand, so only counts are shown.")

    present = [t for t in order if t in set(ex["types"])]
    t_pick = st.selectbox("Read the comments behind a type", present, key="friction_types_pick")
    rows = b[b["types"].map(lambda ts: t_pick in ts)]
    st.dataframe(
        rows[["source", "brand", "sentiment", "text", "url"]].rename(
            columns={"source": "Source", "brand": "Brand", "sentiment": "Sentiment", "text": "Comment", "url": "Link"}),
        hide_index=True, width="stretch", height=300,
        column_config={"Link": st.column_config.LinkColumn("Link", display_text="Open")},
    )
    st.caption(
        "Types are assigned by keyword, not by a person or a model, and unmatched text goes to \"Other / unclear\". "
        "In a hand-check of 40 comments, 31 were labelled fully right and 4 more had the right main type plus a stray extra; "
        "a few keyword fixes were made afterwards and not re-scored. Instagram has no flagged comments. "
        "Cosmetic-lens colour and look complaints come almost entirely from YouTube beauty videos."
    )


def _privacy_section() -> None:
    priv = read_table(APP_DB, "SELECT store, section, category, data_type FROM app_privacy")
    if priv.empty:
        return
    ui.section("What the store listings say the app collects", "As declared by the publisher on each store listing.", "Market fact")
    st.markdown(ebi.tag("fact"), unsafe_allow_html=True)
    priv = priv.assign(Store=priv["store"].map(_STORE_NAMES).fillna(priv["store"]))
    priv["Item"] = priv["data_type"].fillna(priv["category"])
    st.dataframe(
        priv[["Store", "section", "category", "Item"]].rename(columns={"section": "Label section", "category": "Category"}),
        hide_index=True, width="stretch",
    )
    st.caption(
        "Reviews raise unsubscribe and NRIC/FIN collection complaints; this table is what the listings themselves declare. "
        "It does not show what the app does in practice."
    )


def _barrier_section(jf: pd.DataFrame) -> None:
    ui.section(
        "Purchase-barrier flags in public chatter, by brand and source",
        "On-topic YouTube, Instagram, Facebook and Reddit comments the model flagged as a reason not to buy.",
        "Directional · preliminary",
    )
    st.markdown(ebi.tag("dir"), unsafe_allow_html=True)
    if jf.empty:
        st.info("No journey data loaded.")
        return
    soc = jf[jf["source"].isin(_SOCIAL)].drop_duplicates(subset=["source", "brand", "text"])
    if soc.empty:
        st.info("No on-topic social comments.")
        return
    g = soc.groupby(["brand", "source"]).agg(n=("is_barrier", "size"), k=("is_barrier", "sum")).reset_index()
    g["Barrier-flagged"] = [ebi.share(int(k), int(n)) for k, n in zip(g["k"], g["n"])]
    g = g.rename(columns={"brand": "Brand", "source": "Source", "n": "On-topic comments"}).drop(columns="k")
    st.dataframe(g.sort_values(["Brand", "Source"]), hide_index=True, width="stretch")
    st.caption(
        f"A percentage appears only where the base is at least {ebi.MIN_N} comments; below that the count is shown. "
        "Flags are model-scored, not human-reviewed. They are market chatter, not a funnel rate: stage is still tagged per "
        "source rather than per comment."
    )

    brands = sorted(soc["brand"].dropna().unique())
    default = brands.index("Acuvue") if "Acuvue" in brands else 0
    pick = st.selectbox("Show flagged comments for", brands, index=default, key="friction_brand_pick")
    flagged = soc[(soc["brand"] == pick) & (soc["is_barrier"] == 1)]
    if flagged.empty:
        st.caption("No flagged comments for this brand.")
    else:
        st.dataframe(
            flagged[["source", "sentiment", "text", "url"]].rename(
                columns={"source": "Source", "sentiment": "Sentiment", "text": "Comment", "url": "Link"}),
            hide_index=True, width="stretch", height=320,
            column_config={"Link": st.column_config.LinkColumn("Link", display_text="Open")},
        )


def render(jf: pd.DataFrame) -> None:
    ebi.page_header(
        "Where do users get stuck registering or using the MyACUVUE app, and what purchase barriers show up in the market?",
        ["fact", "dir"],
        "App-store ratings and listings are market facts; review themes and barrier flags are directional.",
    )
    rev, hist = app_store_signals.load_app_reviews()
    if not rev.empty:
        rev = rev.assign(themes=rev["full_text"].map(_themes))  # this page's themes, not the shared set
    _app_section(rev, hist)
    _retailer_link_section(rev)
    _privacy_section()
    _barrier_section(jf)
    _barrier_types_section(jf)
    ebi.limits([
        "How many people <b>start but fail to finish registering</b>, or how that moves the 7%&rarr;14% goal: needs registration records.",
        "<b>Which barrier stops a given customer</b>, and personas: needs the barrier-attribution survey and WhatsApp logs.",
        "Written reviews are a small, self-selected slice and skew negative; they show the <i>types</i> of friction, not how common each is.",
        "Barrier flags are per source and model-scored. They are directional until per-comment stage tagging is built.",
        "Retailer-side friction (Google Maps) is not on this page; see the Journey &amp; Barriers tab for now.",
    ])
