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
import plotly.graph_objects as go
import streamlit as st

import re

import app_store_signals
import barrier_taxonomy
import charts
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
        )
        fig.update_xaxes(dtick=1)
        ui.plot(fig, "Both stores are polarised: most raters give 5★ or 1★.", "fact",
                f"{' + '.join(sorted(h['Store'].unique()))} · {ebi.count(int(h['count'].sum()), 'ratings')}. "
                "Ratings include non-reviewers: read the reviews below for the why.",
                bases=h.groupby("Store")["count"].sum().astype(int).to_dict(), noun="star ratings")

    # ---- written reviews ----
    if rev.empty:
        st.info("No written app reviews found.")
        return
    neg = rev[rev["rating"] <= 2]
    pos = rev[rev["rating"] >= 4]
    ui.section(
        f"{len(neg)} of {len(rev)} written reviews are 1–2★",
        f"{int((rev['store'] == 'app_store').sum())} Apple, {int((rev['store'] == 'play_store').sum())} Google Play. "
        "Keyword themes; a review can carry several.",
        "App", kind="fact",
    )

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
        fig = px.bar(tt, x="1–2★ reviews", y="Theme", orientation="h", color="Stage")
        fig.update_layout(yaxis={"categoryorder": "total ascending"})
        ui.plot(fig, f"\u201c{tt.iloc[0]['Theme']}\u201d is the top complaint ({int(tt.iloc[0]['1–2★ reviews'])} of {len(neg)} reviews).", "fact",
                ebi.note(neg, "MyACUVUE app, 1–2★ reviews", "date", "reviews"), bases=len(neg), noun="1–2★ app reviews")
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
        "Registration: OTP not arriving, slow date-of-birth entry, freezes, update loops. "
        "Loyalty: points locked to one retailer, unsubscribe and privacy complaints.",
        kind="fact",
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
                 )
    _yp = yr.loc[yr["negative"].idxmax()]
    ui.plot(fig, f"1–2★ reviews peaked in {int(_yp['year'])} ({int(_yp['negative'])}): ", "fact",
            ebi.note(rev, "MyACUVUE app", "date", "reviews") + " · Counts only: yearly bases are too small for %.",
            bases={str(int(y)): int(n) for y, n in zip(yr["year"], yr["reviews"])}, noun="written reviews")

    # ---- top complaints, quoted ----
    ui.takeaway("Most-endorsed 1–2★ complaints, by thumbs-up.", "fact")
    top = neg.sort_values("thumbs_up", ascending=False).head(10)
    top = top.assign(Themes=top["themes"].map(", ".join))
    st.dataframe(
        top[["date", "store", "app_version", "rating", "thumbs_up", "full_text", "Themes"]].rename(columns={
            "date": "Date", "store": "Store", "app_version": "Version", "rating": "★",
            "thumbs_up": "Thumbs-up", "full_text": "Review"}),
        hide_index=True, width="stretch",
    )

    # ---- developer replies ----
    st.caption(f"No developer replies in the scrape (0 of {len(rev)}): a scrape limit, not proof J&J never replies.")


def _retailer_link_section(app_rev: pd.DataFrame) -> None:
    ui.section(
        "The retailer link is raised in app reviews, rarely in store reviews",
        "MyACUVUE app reviews beside Google Maps reviews of the chains that sell it.",
        "Retailer link", kind="dir",
    )
    gm, _ = gmaps_signals.load_gmaps()
    neg = app_rev[app_rev["rating"] <= 2] if not app_rev.empty else app_rev
    left, right = st.columns(2)

    k_lock = k_pts = 0
    with left:
        ui.takeaway("In the app, 1–2★ reviews name the retailer lock.", "fact")
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
        ui.takeaway("At the retailer, friction is about staff, waits and stock.", "fact")
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
            fig = px.bar(tdf, x="Friction reviews", y="Theme", orientation="h")
            fig.update_layout(yaxis={"categoryorder": "total ascending"})
            ui.plot(fig, f"Loyalty/points shows in only {lp} of {len(fr)} retailer friction reviews.", "fact",
                    ebi.note(gm, "Google Maps", "date", "reviews"), bases=len(fr), noun="friction reviews")

    if not fr.empty and not neg.empty:
        top = tdf.head(3)["Theme"].str.lower().tolist()
        ui.insight(
            f"Retailers are mostly marked down for {', '.join(top)}, not for points or lock-in.",
            kind="fact",
        )
    st.caption("Maps reviews are about retailers (newest reviews per outlet, plus a Google keyword search for contact-lens terms; skew positive). Different people: shows where each side complains, not cause.")


def render_barrier_bubble(jf: pd.DataFrame, brands=None, key: str = "friction_bubble") -> None:
    """Barrier type x brand bubble map. Size = share of that brand's flagged comments;
    the number inside is the raw count. Brands under the MIN_N floor are faded and marked thin."""
    if jf.empty:
        return
    b = jf[jf["is_barrier"] == 1].drop_duplicates(subset=["source", "brand", "text"])
    if brands is not None:
        b = b[b["brand"].isin(brands)]
    if b.empty:
        return
    srcs = sorted(b["source"].dropna().unique())
    pick = st.multiselect("Sources in the barrier map", srcs, default=srcs, key=f"{key}_src")
    d = b[b["source"].isin(pick)].copy()
    if d.empty:
        st.info("No flagged comments for the selected sources.")
        return
    d["types"] = d["text"].map(barrier_taxonomy.classify)
    n_brand = d.groupby("brand").size()
    n_brand = n_brand.reindex(charts.order_brands(n_brand.index))   # same brand order as every other chart
    g = d.explode("types").groupby(["brand", "types"]).size().reset_index(name="k")
    g["share"] = g["k"] / g["brand"].map(n_brand) * 100
    thin = {br for br, n in n_brand.items() if n < ebi.MIN_N}
    lbl = {br: f"{br}<br>n={int(n)}" + (" (thin)" if br in thin else "") for br, n in n_brand.items()}
    g["brand_lbl"] = g["brand"].map(lbl)
    g["thin"] = g["brand"].isin(thin)
    present = set(g["types"])
    order = [t for t in list(barrier_taxonomy.TYPES) + [barrier_taxonomy.OTHER] if t in present]
    fig = go.Figure()
    for br in n_brand.index:
        sub = g[g["brand"] == br]
        fig.add_trace(go.Scatter(
            x=sub["brand_lbl"], y=sub["types"], mode="markers+text", text=sub["k"], textposition="middle center",
            textfont=dict(color="#191919" if br in thin else "white", size=12),
            marker=dict(
                size=sub["share"], sizemode="area", sizeref=0.035, sizemin=15,
                color=BRAND_COLORS.get(br, "#999999"), opacity=0.4 if br in thin else 0.9, line=dict(width=0),
            ),
            customdata=sub[["k", "share"]], name=br, showlegend=False,
            hovertemplate=f"{br}<br>%{{y}}<br>%{{customdata[0]}} comments (%{{customdata[1]:.0f}}% of brand)<extra></extra>",
        ))
    fig.update_layout(
        height=max(420, 58 * len(order) + 110),
        xaxis=dict(categoryorder="array", categoryarray=[lbl[br] for br in n_brand.index], automargin=True,
                   tickfont=dict(size=13), showgrid=True, gridcolor="rgba(128,128,128,0.15)"),
        yaxis=dict(categoryorder="array", categoryarray=order[::-1], title=None, automargin=True,
                   tickfont=dict(size=13), showgrid=True, gridcolor="rgba(128,128,128,0.12)"),
    )
    _gt = g.loc[g["k"].idxmax()]
    ui.plot(fig, f"\u201c{_gt['types']}\u201d is the biggest barrier for {_gt['brand']} ({int(_gt['k'])} comments).", "fact",
            f"{ebi.count(int(n_brand.sum()), 'flagged comments')}. Bubble = share of brand's flags; number = comments. "
            f"Hollow = under {ebi.MIN_N} (read as counts). Keyword-matched.",
            bases={br: int(n) for br, n in n_brand.items()}, noun="flagged comments")


def _barrier_types_section(jf: pd.DataFrame) -> None:
    ui.section(
        "Barrier comments sort into one set of types across all sources",
        "Flagged comments from every source, sorted into one set of types.",
        "Barrier types", kind="fact",
    )
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
    st.caption("Flagged per source: " + ", ".join(f"{s} {int(n)}" for s, n in n_src.items()) + ". Several types per comment, so columns exceed totals.")

    big = [s for s, n in n_src.items() if n >= ebi.MIN_N]
    if big:
        long = ex[ex["source"].isin(big)].groupby(["source", "types"]).size().reset_index(name="k")
        long["share"] = long.apply(lambda r: r["k"] / n_src[r["source"]] * 100, axis=1)
        fig = px.bar(long, x="share", y="types", color="source", barmode="group", orientation="h",
                     color_discrete_map={**charts.SOURCE_COLORS, "MyACUVUE app": "#2B2D42", "KiasuParents": "#B08968"},
                     labels={"share": "% of flagged comments", "types": "", "source": "Source"},
                     category_orders={"types": order})
        fig.update_layout(yaxis={"autorange": "reversed"})
        _tp = long.loc[long["share"].idxmax()]
        small = [f"{s} ({int(n)})" for s, n in n_src.items() if n < ebi.MIN_N]
        ui.plot(fig, f"\u201c{_tp['types']}\u201d is {_tp['share']:.0f}% of {_tp['source']} flags.", "fact",
                f"{', '.join(big)} · {ebi.count(int(sum(n_src[s] for s in big)), 'flagged comments')}. "
                f"Shares only where n\u2265{ebi.MIN_N}" + (f"; counts only for {', '.join(small)}." if small else "."),
                height=360, bases={s: int(n) for s, n in n_src.items()}, noun="flagged comments")
    else:
        ui.n_strip({s: int(n) for s, n in n_src.items()}, noun="flagged comments")
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
        "Types are keyword-assigned; unmatched text is \"Other / unclear\". Hand-check of 40: 31 fully right, 4 right main type. "
        "Instagram has no flagged comments. Cosmetic-lens look complaints are mostly YouTube beauty videos."
    )


def _privacy_section() -> None:
    priv = read_table(APP_DB, "SELECT store, section, category, data_type FROM app_privacy")
    if priv.empty:
        return
    ui.section("The listings declare what the app collects", "As stated by the publisher on each store listing.", "Privacy", kind="fact")
    priv = priv.assign(Store=priv["store"].map(_STORE_NAMES).fillna(priv["store"]))
    priv["Item"] = priv["data_type"].fillna(priv["category"])
    st.dataframe(
        priv[["Store", "section", "category", "Item"]].rename(columns={"section": "Label section", "category": "Category"}),
        hide_index=True, width="stretch",
    )
    st.caption("Reviews raise unsubscribe and NRIC/FIN complaints; this is what listings declare, not what the app does.")


def _barrier_section(jf: pd.DataFrame) -> None:
    ui.section(
        "Barrier-flag rates by brand and source; % shown only where n \u2265 30",
        "On-topic YouTube, Instagram, Facebook and Reddit comments flagged as a reason not to buy.",
        "Barrier flags", kind="fact",
    )
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
    st.caption(f"% shown only at n\u2265{ebi.MIN_N}, else the count. Model-scored; market chatter, not a funnel rate.")

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
        "Where do users get stuck registering or using the app, and what stops purchase?",
        ["fact", "dir"],
        "Ratings and listings are fact; review themes and barrier flags are directional.",
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
        "<b>Which barrier stops a given customer</b>, and category-user profiles: needs the barrier-attribution survey and WhatsApp logs.",
        "Written reviews are a small, self-selected slice and skew negative; they show the <i>types</i> of friction, not how common each is.",
        "Barrier flags are per source and model-scored. They are directional until per-comment stage tagging is built.",
        "Retailer-side friction (Google Maps) is not on this page; see the Journey &amp; Barriers tab for now.",
    ])


def app_facts() -> dict:
    """Live MyACUVUE app figures for the Summary cards, computed with the same theme rules and filters as this page:
    store ratings from the star histogram, and counts over the written 1-2 star reviews."""
    rev, hist = app_store_signals.load_app_reviews()
    out = {"stores": {}, "written": 0, "neg": 0, "on_path": 0, "after_update": 0, "points_or_lock": 0}
    if not hist.empty:
        for store, g in _star_table(hist).groupby("Store"):
            n = int(g["count"].sum())
            out["stores"][store] = {"n": n, "mean": float((g["stars"] * g["count"]).sum() / n),
                                    "one": int(g.loc[g["stars"] == 1, "count"].sum())}
    if not rev.empty:
        rev = rev.assign(themes=rev["full_text"].map(_themes))
        neg = rev[rev["rating"] <= 2]
        out["written"], out["neg"] = len(rev), len(neg)
        out["on_path"] = int(neg["themes"].map(lambda x: bool(_TRIAL_THEMES & set(x))).sum())
        out["after_update"] = int(neg["full_text"].str.contains(_AFTER_UPDATE, case=False, regex=True, na=False).sum())
        out["points_or_lock"] = int(neg["themes"].map(lambda x: "Points / rewards" in x or "Locked to one retailer" in x).sum())
    return out
