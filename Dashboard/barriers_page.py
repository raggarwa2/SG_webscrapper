"""
Journey & App: where does the friction happen, how does the MyACUVUE app lose people, and which message goes where?

The tab keeps 1 Journey (where the friction happens), 2 App reviews and 3 Message (the WhatsApp map). The framework Barrier read lives
in Research & Triangulation (`render_barrier`) beside the desk research it checks, and the store-review topics sit under Retail &
Promotions (`render_retail`). A complaint has one definition everywhere: an item that is negative or mixed on a theme group. The
consumer-voice lens (compared with peers), the MyACUVUE app (Acuvue only) and retail reviews (about the shop) are never pooled.

Charts are shown; tables and reviews sit behind a click.
"""


import pandas as pd
import plotly.express as px
import plotly.graph_objects as go
import streamlit as st

import app_store_signals
import barrier_taxonomy
import barriers_friction
import charts
import ebi
import ui
import voice_data as vd
import whatsapp_map
from sg_common import BRAND_COLORS, JOURNEY_STAGES, SENTIMENT_COLORS

FOCAL = vd.FOCAL
STORE_NAMES = {"app_store": "Apple App Store", "play_store": "Google Play"}
LENS_COLORS = {"Consumer voice": BRAND_COLORS[FOCAL], "MyACUVUE app": "#7048E8", "Retail reviews": "#C98B2B"}
STAGE_FIX = {"Repeat": "Repeat/Retention"}
# Section 2 reads the framework barrier labels (the desk-research list, as on Triangulation), not the four decision groups. Product &
# look is left out: it is already the top complaint in the headline strip, and it is not a barrier a WhatsApp message can move.
BARRIERS = ["Price & channel cost", "Loyalty & rewards", "Registration / login friction", "App utility & support",
            "Unwanted messaging / privacy", "Fear / handling difficulty", "Lack of professional guidance"]


def _barrier_complaints(d: pd.DataFrame) -> pd.DataFrame:
    """Complaint items (the shared definition) labelled with the framework barriers: one row per item and barrier."""
    ids = set(vd.complaints(d)["item_id"]) if len(d) else set()
    rows = [(r.item_id, b) for r in d[d["item_id"].isin(ids)].itertuples() for b in barrier_taxonomy.classify(r.text) if b in BARRIERS]
    return pd.DataFrame(rows, columns=["item_id", "group"]).drop_duplicates()


def _complaint_items(d: pd.DataFrame) -> pd.DataFrame:
    """Complaint rows (one per item and group) joined to the item text for the click-through."""
    c = vd.complaints(d)
    return c.merge(d[["item_id"]], on="item_id")


def _rate_rows(p: pd.DataFrame) -> list:
    """[(group, label, complaints_f, rate_f, complaints_p, rate_p, n_f, n_p)]: share of each side's items that carry a complaint on the group."""
    f, o = p[p["brand_std"] == FOCAL], p[p["brand_std"] != FOCAL]
    cf, co = vd.complaints(f), vd.complaints(o)
    rows = []
    for g in vd.GROUP_LIST:
        kf, ko = cf.loc[cf["group"] == g, "item_id"].nunique(), co.loc[co["group"] == g, "item_id"].nunique()
        pv = vd.two_prop_p(kf, len(f), ko, len(o))
        testable = kf + ko >= ebi.MIN_N
        higher = bool(testable and pv is not None and pv < 0.05 and kf / max(len(f), 1) > ko / max(len(o), 1))
        where = []
        if higher:     # corroboration: channels with 15+ items on both sides that show the same higher rate on their own (p < 0.05)
            for c in vd.CHANNELS:
                fc, oc = f[f["source"] == c], o[o["source"] == c]
                if len(fc) >= ebi.MIN_N and len(oc) >= ebi.MIN_N:
                    k1 = cf[cf["item_id"].isin(fc["item_id"]) & (cf["group"] == g)]["item_id"].nunique()
                    k2 = co[co["item_id"].isin(oc["item_id"]) & (co["group"] == g)]["item_id"].nunique()
                    pc = vd.two_prop_p(k1, len(fc), k2, len(oc))
                    if pc is not None and pc < 0.05 and k1 / len(fc) > k2 / len(oc):
                        where.append(c)
        grade = ("Not tested" if not testable else ("No gap" if not higher else ("A · corroborated" if len(where) >= 2 else "B · one channel")))
        rows.append({"group": g, "kf": kf, "ko": ko, "rf": kf / len(f) * 100 if len(f) else None, "ro": ko / len(o) * 100 if len(o) else None,
                     "n_f": len(f), "n_p": len(o), "p": pv, "testable": testable, "grade": grade, "where": where})
    return pd.DataFrame(rows)


@st.cache_data(ttl=600, show_spinner=False, max_entries=2)
def _facts(m_items: float, m_tags: float, m_stage: float) -> dict:
    return _build_facts(vd.load())


def facts(d: pd.DataFrame) -> dict:
    """Numbers shared by the page and the Answer card (cached on the table timestamps)."""
    stage = vd.STAGE_DB.stat().st_mtime if vd.STAGE_DB.exists() else 0.0
    return _facts(vd.VOICE_DB.stat().st_mtime, vd.TAG_DB.stat().st_mtime, stage) if len(d) else _build_facts(d)


def _build_facts(d: pd.DataFrame) -> dict:
    p, a, m = vd.pool(d), vd.app(d), vd.maps(d)
    out = {"pool": p, "app": a, "maps": m, "rates": _rate_rows(p), "eras": vd.app_eras(a) if len(a) else pd.DataFrame()}
    r = out["rates"]
    cf = vd.complaints(p[p["brand_std"] == FOCAL])
    out["n_complaints_f"] = cf["item_id"].nunique()
    sig = r[r["grade"].isin(["B · one channel", "A · corroborated"])]     # complaints above peers, with the channel check applied
    out["sig"] = sig
    out["top"] = r.sort_values("kf", ascending=False).iloc[0] if len(r) and r["kf"].max() else None
    out["journey"] = _journey_facts(d)
    return out


def _stage_counts(fr: pd.DataFrame):
    """Complaint items by stage and source type; the peak stage among those with 15+ items (None when none reaches it)."""
    cols = vd.STAGE_LIST + [vd.NO_STAGE]
    ct = pd.crosstab(fr["stage"], fr["lens"]).reindex(index=cols, columns=vd.FRICTION_LENS, fill_value=0)
    tot = ct.sum(axis=1)
    staged = tot[vd.STAGE_LIST]
    ok = staged[staged >= ebi.MIN_N]
    return ct, tot, ok, (ok.idxmax() if len(ok) else None)


def _journey_facts(d: pd.DataFrame) -> dict | None:
    """The journey numbers the tile here and on Key findings both read, on Acuvue's complaints only (consumers who name it, and its app),
    the same brand base as the Barrier tile. The app is placed at Trial by what it is, so `top_app` says how
    much of the peak it supplies, and `own_top` is the peak among Acuvue-named consumer comments alone, where no channel decides the stage."""
    fr = vd.friction(d)
    if fr.empty or not len(vd.stage_table()):
        return None
    own_mask = (fr["lens"] == "Consumer, brand-named") & (fr["brand_std"] == FOCAL)
    ct, tot, ok, top = _stage_counts(fr[own_mask | (fr["lens"] == "App")])   # Acuvue's own complaints: consumers who name it, and its app
    own = fr[own_mask]
    own_ct = own[own["stage"].isin(vd.STAGE_LIST)]["stage"].value_counts()
    own_top = own_ct.idxmax() if int(own_ct.sum()) >= ebi.MIN_N else None
    return {"top": top, "top_n": int(ok[top]) if top else 0, "top_app": int(ct.loc[top, "App"]) if top else 0,
            "n_staged": int(tot[vd.STAGE_LIST].sum()), "n": int(tot.sum()),
            "own_top": own_top, "own_top_n": int(own_ct[own_top]) if own_top else 0, "own_staged": int(own_ct.sum())}


def _peer_mix(p: pd.DataFrame, channel: str) -> str:
    """Who the 'peers' are on one channel, e.g. '97% Olens': a gap there is Acuvue against that brand, not against the field."""
    o = p[(p["source"] == channel) & (p["brand_std"] != FOCAL)]["brand_std"].value_counts()
    return f"{o.iloc[0] / o.sum() * 100:.0f}% {o.index[0]}" if len(o) else ""


def _where(sig: pd.DataFrame, p: pd.DataFrame | None = None) -> str:
    ch = sorted({c for w in sig["where"] for c in w})
    if len(ch) == 1:
        mix = _peer_mix(p, ch[0]) if p is not None else ""
        return ch[0] + " only" + (f" (peers there are {mix})" if mix else "")
    return " and ".join(ch) if ch else "one channel"


def _vs_peers(r, short: bool = False) -> str:
    """How a group's complaint rate compares with peers, with the channel check applied."""
    if r["grade"] in ("B · one channel", "A · corroborated"):
        where = ", ".join(r["where"]) or "one channel"
        return (f"; above peers on {where}" if short else f", above peers ({r['rf']:.0f}% vs {r['ro']:.0f}% of items) on {where}"
                + (" only" if r["grade"].startswith("B") and "," not in where else ""))
    return "; level with peers" if short else ", level with peers"


def _rate_note(rates: pd.DataFrame) -> str:
    s = rates[rates["grade"].isin(["B · one channel", "A · corroborated"])]
    return "" if s.empty else "Above peers: " + "; ".join(f"{r.group} ({r.grade.split(' ·')[0]}, {', '.join(r.where) or 'one channel'})" for r in s.itertuples()) + "."


def wa_frame(d: pd.DataFrame) -> pd.DataFrame:
    """The WhatsApp map's evidence on the shared labels: brand-pool items plus the app reviews (Acuvue), one row per journey stage the
    channel is built to evidence (context.md), with the tagger's sentiment. The per-source barrier flag is retired: a complaint is a
    negative or mixed item, the same definition as the rest of the page."""
    x = pd.concat([vd.pool(d), vd.app(d).assign(brand_std=FOCAL)], ignore_index=True)
    rows = []
    for r in x.itertuples():
        stages = [STAGE_FIX.get(s.strip(), s.strip()) for s in vd.CHANNEL_ROLE.get(r.source, ("",))[0].split(",") if s.strip()]
        for stg in stages or ["Awareness"]:
            rows.append((r.source, r.brand_std, stg, r.sentiment, 0, r.date, r.text, r.url))
    return pd.DataFrame(rows, columns=["source", "brand", "journey_stage", "sentiment", "is_barrier", "date", "text", "url"])


def render_barrier(d: pd.DataFrame) -> None:
    """Framework barriers read on Acuvue's complaint items (consumers who name it, and its app), with retail reviews beside them.
    Homed in Research & Triangulation: the same desk-research labels the Barrier Matches check uses."""
    if d.empty:
        st.info("Run Scripts/build_voice_items.py and Scripts/tag_voice_items.py to build the tables this page reads.")
        return
    F = facts(d)
    p, a, m = F["pool"], F["app"], F["maps"]
    pf = p[p["brand_std"] == FOCAL]
    cf, ca, cm = (_barrier_complaints(x) for x in (pf, a, m))
    n_cf, n_ca, n_cm = (int(vd.complaints(x)["item_id"].nunique()) if len(x) else 0 for x in (pf, a, m))
    n_prod = int(vd.complaints(pf).query("group == 'Product & look'")["item_id"].nunique()) if len(pf) else 0

    own = pd.concat([cf, ca], ignore_index=True)        # Acuvue's own complaints: consumers who name it, and its app
    n_own = n_cf + n_ca
    cnt = own.groupby("group")["item_id"].nunique().reindex(BARRIERS).fillna(0).astype(int)
    t1 = (f"{cnt.idxmax()} leads {FOCAL}'s own complaints on the framework barriers ({int(cnt.max())} of {n_own} complaint items)"
          if n_own >= ebi.MIN_N and cnt.max() >= ebi.MIN_COUNT else "Framework barriers in complaint items")
    ui.section(t1, "The desk-research framework barriers, read on complaint items (negative or mixed). An item can carry several. "
                   f"Product & look complaints ({n_prod} consumer items) are the headline-strip figure and are not charted. "
                   "Peers are not compared: too few Acuvue consumer complaints sit on these barriers.",
               "Barrier", kind="fact")
    c1, c2 = st.columns(2)
    with c1:
        ks = [int(cnt[b]) for b in BARRIERS]
        drawn = [k >= ebi.MIN_COUNT for k in ks]
        fig = go.Figure(go.Bar(
            y=BARRIERS, x=[k / n_own * 100 if ok else None for k, ok in zip(ks, drawn)], orientation="h", marker_color=BRAND_COLORS[FOCAL],
            marker_pattern_shape=["/" if ebi.is_thin(k) else "" for k in ks],
            text=[f"{k} ({k / n_own * 100:.0f}%)" if ok else "" for k, ok in zip(ks, drawn)], textposition="outside", cliponaxis=False,
            customdata=[[b, "own"] for b in BARRIERS], hovertemplate="%{y}: %{x:.0f}% of complaint items<extra></extra>"))
        fig.update_xaxes(range=[0, max([k / n_own * 100 for k in ks] + [1]) * 1.35], ticksuffix="%", title=f"% of {FOCAL}'s complaint items")
        fig.update_yaxes(autorange="reversed", title=None)
        fig.update_layout(height=130 + 60 * len(BARRIERS), showlegend=False)
        under = [f"{b} {k}" for b, k, ok in zip(BARRIERS, ks, drawn) if not ok and k]
        ev = ui.plot(fig, f"Share of {FOCAL}'s own complaint items on each framework barrier.", key="bp_rates", select=True,
                     note="Hatched under 15 items; not drawn under 10" + (f" (counts: {', '.join(under)})" if under else "") + ". Click a bar for the items.",
                     bases={"Consumer, brand-named": n_cf, "App": n_ca}, noun="complaint items")
    with c2:
        lens_n = {"Consumer voice": n_cf, "MyACUVUE app": n_ca, "Retail reviews": n_cm}
        lens_c = {"Consumer voice": cf, "MyACUVUE app": ca, "Retail reviews": cm}
        cells = []
        for lens, c in lens_c.items():
            for g in BARRIERS:
                k = c.loc[c["group"] == g, "item_id"].nunique()
                cells.append((lens, g, k, k / lens_n[lens] * 100 if lens_n[lens] >= ebi.MIN_N else None))
        top_share = max([s_ for *_, s_ in cells if s_ is not None] + [1])
        fig2 = go.Figure()
        solid = [x for x in cells if x[2] >= ebi.MIN_COUNT and x[3] is not None]
        thin = [x for x in cells if not (x[2] >= ebi.MIN_COUNT and x[3] is not None)]
        fig2.add_scatter(x=[x[0] for x in solid], y=[x[1] for x in solid], mode="markers+text", showlegend=False,
                         marker=dict(symbol="square", size=58, color=[x[3] for x in solid], cmin=0, cmax=top_share,
                                     colorscale=[[0, "#EEF3F7"], [0.5, "#E9C877"], [1, "#B42318"]], line=dict(width=0)),
                         text=[f"<b>{x[3]:.0f}%</b><br>{x[2]}" for x in solid], textfont=dict(size=11, color="#191919"),
                         customdata=[[x[1], x[0]] for x in solid],
                         hovertemplate="%{customdata[0]} in %{customdata[1]}: %{text}<extra></extra>")
        fig2.add_scatter(x=[x[0] for x in thin], y=[x[1] for x in thin], mode="markers+text", showlegend=False,
                         marker=dict(symbol="square", size=58, color="#FFFFFF", line=dict(width=1.5, color="#94A3B8")),
                         text=[str(x[2]) if x[2] else "0" for x in thin], textfont=dict(size=11, color="#64748B"),
                         customdata=[[x[1], x[0]] for x in thin],
                         hovertemplate="%{customdata[0]} in %{customdata[1]}: %{text} complaint items (under 10, not rated)<extra></extra>")
        fig2.update_xaxes(categoryorder="array", categoryarray=list(lens_n), side="top", range=[-0.5, len(lens_n) - 0.5], showgrid=False, title=None)
        fig2.update_yaxes(autorange="reversed", showgrid=False, title=None, categoryorder="array", categoryarray=BARRIERS)
        fig2.update_layout(height=130 + 60 * len(BARRIERS))
        _lead = {lens: max(BARRIERS, key=lambda g, c=lens_c[lens]: c.loc[c["group"] == g, "item_id"].nunique()) for lens in lens_n if lens_n[lens] >= ebi.MIN_N}
        _say = ("Where each barrier is voiced: " + "; ".join(f"{k.lower()}: {v}" for k, v in _lead.items()) + ".") if _lead else "Where each barrier is voiced."
        ev2 = ui.plot(fig2, _say, key="bp_lens", select=True,
                      note=f"Cell = % of that lens's complaint items on the barrier, then the item count. Hollow = under 10, count only. "
                           f"Consumer voice = {FOCAL} only; retail reviews are about the shop. Click a cell for the items.",
                      bases={"Consumer voice": n_cf, "App reviews": n_ca, "Retail reviews": n_cm}, noun="complaint items")
    pk, pk2 = ui.picked(ev), ui.picked(ev2)
    if pk:
        grp = pk[0][0]
        both = pd.concat([pf, a], ignore_index=True)
        ids = set(own.query("group == @grp")["item_id"])
        ui.items_panel(vd.view(both[both["item_id"].isin(ids)]), f"{grp}: {FOCAL} complaints (consumers and app)")
    elif pk2:
        grp, lens = pk2[0]
        src = {"Consumer voice": pf, "MyACUVUE app": a, "Retail reviews": m}[lens]
        ids = set(lens_c[lens].query("group == @grp")["item_id"])
        if len(src):
            ui.items_panel(vd.view(src[src["item_id"].isin(ids)]), f"{grp}: {lens.lower()} complaints")
    tr = pd.DataFrame({"Barrier": BARRIERS,
                       f"{FOCAL} consumer complaint items": [int(cf.loc[cf["group"] == b, "item_id"].nunique()) for b in BARRIERS],
                       "App": [int(ca.loc[ca["group"] == b, "item_id"].nunique()) for b in BARRIERS],
                       "Retail": [int(cm.loc[cm["group"] == b, "item_id"].nunique()) for b in BARRIERS]})
    ui.show_data("Show the barrier table", tr, "Labels: model tags where tagged, keywords otherwise. Product experience and Colour & look are left out by design; "
                 "availability, authenticity and store service are not framework barriers.")
    _own = pd.concat([pf, a], ignore_index=True)
    ui.read_comments(_own[_own["item_id"].isin(set(vd.complaints(_own)["item_id"]))], f"Read the {FOCAL} complaints behind this page (consumers and app)", key="bar_read")


def render_retail(d: pd.DataFrame) -> None:
    """Google Maps contact-lens reviews on the shared labels: which topics draw complaints. Sits under Retail & Promotions."""
    if d.empty:
        return
    F = facts(d)
    a, m = F["app"], F["maps"]
    ca = _barrier_complaints(a)
    mc = pd.DataFrame(columns=["group", "positive", "mixed", "negative", "neutral", "total"])
    if len(m):
        mr = [(g, pol) for gp in m["gpol"] for g, pol in gp.items()]
        mc = pd.DataFrame(mr, columns=["group", "pol"]).groupby(["group", "pol"]).size().unstack(fill_value=0)
        for c in ("positive", "mixed", "negative", "neutral"):
            if c not in mc.columns:
                mc[c] = 0
        mc["total"] = mc[["positive", "mixed", "negative", "neutral"]].sum(axis=1)
        mc = mc.reset_index()
    m_pos = (m["sentiment"] == "positive").mean() * 100 if len(m) >= ebi.MIN_N else None
    m_acu = int(m["text"].str.contains("acuvue", case=False, na=False).sum()) if len(m) else 0

    ui.section(f"Store reviews are {m_pos:.0f}% positive; complaints sit on service and guidance" if m_pos is not None else "Retail experience",
               "Google Maps reviews about contact lenses. About the shop, not the brand; skews positive.",
               "Store reviews", kind="fact")
    shown = mc[mc["total"] >= ebi.MIN_COUNT].sort_values("total", ascending=False) if len(mc) else mc
    if len(shown):
        fm = go.Figure()
        for pol in ("positive", "mixed", "negative"):
            fm.add_bar(y=shown["group"], x=shown[pol], orientation="h", name=charts.SENTIMENT_LABELS[pol], marker_color=SENTIMENT_COLORS[pol],
                       customdata=[[g, pol] for g in shown["group"]], hovertemplate="%{y} · " + pol + ": %{x}<extra></extra>")
        fm.update_layout(barmode="stack", height=90 + 56 * len(shown), legend=dict(orientation="h", y=-0.14, traceorder="normal"), xaxis_title="Topic tags on store reviews")
        fm.update_yaxes(autorange="reversed", title=None)
        topneg = shown.sort_values("negative", ascending=False).iloc[0]
        ev4 = ui.plot(fm, f"{topneg['group']} draws the most complaints ({int(topneg['negative'])} of {int(topneg['total'])} tags).", key="bp_maps", select=True,
                      note=f"Only {m_acu} of {len(m)} name Acuvue; {int((m['retailer'] == 'Owndays').sum())} are Owndays (own-brand lenses). Click a bar for the reviews.",
                      bases={"Google Maps": len(m)}, noun="contact-lens reviews")
        small = mc[mc["total"] < ebi.MIN_COUNT]
        if len(small):
            st.caption("Not drawn (under 10 tags): " + "; ".join(f"{r.group} {int(r.total)}" for r in small.itertuples()) + ".")
        pk4 = ui.picked(ev4)
        if pk4:
            grp, pol = pk4[0]
            sel = m[m["gpol"].map(lambda gp: gp.get(grp) == pol)]
            ui.items_panel(vd.view(sel), f"Store reviews: {grp}, {pol}")
    chains = m.groupby("retailer").agg(n=("item_id", "size"), net=("sentiment", lambda s: (s == "positive").mean() * 100 - (s == "negative").mean() * 100),
                                       acuvue=("text", lambda s: int(s.str.contains("acuvue", case=False, na=False).sum()))).sort_values("n", ascending=False) if len(m) else pd.DataFrame()
    if len(chains):
        ct = pd.DataFrame({"Chain": chains.index, "Contact-lens reviews": chains["n"].values,
                           "Net sentiment": [f"{ebi.sgn(v)}" if n >= ebi.MIN_N else f"n={n}" for v, n in zip(chains["net"], chains["n"])],
                           "Reviews naming Acuvue": chains["acuvue"].values})
        ui.show_data("Show the chain table", ct, "Net sentiment shown only for chains with 15+ reviews.")
    loy_m = int(mc.loc[mc["group"] == "Loyalty & app", "total"].sum()) if len(mc) and "Loyalty & app" in set(mc["group"]) else 0
    loy_a = int(ca["item_id"].nunique()) if len(a) else 0
    st.caption(f"Loyalty & app: {loy_m} tags in {len(m)} store reviews vs {loy_a} complaint items in {len(a)} app reviews. The retailer link comes up in the app, rarely in store.")
    ui.goto("Journey & App", key="rt_to_journey_app")
    ui.read_comments(m, "Read the store reviews behind this page (Google Maps, contact lenses)", key="ret_read")


def render(d: pd.DataFrame, brands: list) -> None:
    if d.empty:
        st.info("Run Scripts/build_voice_items.py and Scripts/tag_voice_items.py to build the tables this page reads.")
        return
    F = facts(d)
    a, eras = F["app"], F["eras"]
    last = eras.iloc[-1] if len(eras) else None
    app_ok = last is not None and last["n"] >= ebi.MIN_N
    jf_new = wa_frame(d)

    ui.nav(["1 · Journey", "2 · App reviews", "3 · Message"])
    t_jour, t_app, t_msg = (st.container() for _ in range(3))

    with t_jour:
        _journey_section(d)


    # ---- 3. App ---------------------------------------------------------------------------------------------------
    with t_app:
        ui.section(f"The app is where registration breaks: {last['neg']:.0f}% of {int(last['n'])} written {last['era']} reviews are negative" if app_ok else "The MyACUVUE app",
                   "Apple App Store and Google Play. Written reviews skew negative; the star ratings below are milder. Acuvue only; kept out of brand comparisons.", "2 · App reviews", kind="fact")
        rev, hist = app_store_signals.load_app_reviews()
        if not hist.empty:
            h = barriers_friction._star_table(hist)
            cols = st.columns(4)
            for i, (store, gg) in enumerate(h.groupby("Store")):
                n = int(gg["count"].sum())
                cols[i * 2].metric(f"{store}: average", f"{(gg['stars'] * gg['count']).sum() / n:.2f} ★", help=f"From the star histogram, n={n:,} ratings.")
                one = int(gg.loc[gg["stars"] == 1, "count"].sum())
                cols[i * 2 + 1].metric(f"{store}: 1★ share", ebi.share(one, n).split(" (")[0], help=f"{one:,} of {n:,} ratings are 1 star.")
        c1, c2 = st.columns(2)
        with c1:
            if not hist.empty:
                fig = px.bar(h, x="stars", y="share", color="Store", barmode="group", labels={"stars": "Stars", "share": "% of ratings"})
                fig.update_xaxes(dtick=1)
                fig.update_layout(legend_title_text="")
                ui.plot(fig, "Both stores are polarised: most raters give 5★ or 1★.", key="bp_stars",
                        note="Ratings include people who never wrote a review.", bases=h.groupby("Store")["count"].sum().astype(int).to_dict(), noun="star ratings")
        with c2:
            if len(eras) and eras["n"].sum():
                fa = go.Figure(go.Bar(x=[charts.row_label(e, int(n)) for e, n in zip(eras["era"], eras["n"])],
                                      y=[v if (pd.notna(v) and n >= ebi.MIN_N) else None for v, n in zip(eras["neg"], eras["n"])],
                                      marker=dict(color=SENTIMENT_COLORS["negative"], pattern=charts.thin_fill([ebi.is_thin(n) for n in eras["n"]])),
                                      text=[f"{v:.0f}%" if (pd.notna(v) and n >= ebi.MIN_N) else f"n={int(n)}" for v, n in zip(eras["neg"], eras["n"])],
                                      textposition="outside"))
                fa.update_layout(height=300, yaxis=dict(range=[0, 110], title="% of written reviews negative"), xaxis_title=None)
                ui.plot(fa, (f"{eras.iloc[0]['neg']:.0f}% of early reviews were negative, {last['neg']:.0f}% in {last['era']}."
                             if eras.iloc[0]["n"] >= ebi.MIN_N and app_ok else "Share of app reviews that are negative, by period."),
                        key="bp_era", note="Written reviews read by the same tagger as every other channel.",
                        bases={r.era: int(r.n) for r in eras.itertuples()}, noun="written reviews")
        # what the negative reviews are about: the 12 barrier labels (detail under the Loyalty & app group)
        neg = a[a["sentiment"] == "negative"].copy() if len(a) else a
        if len(neg):
            neg["labels"] = neg["text"].map(barrier_taxonomy.classify)
            ex = neg.explode("labels")
            cnt = ex[ex["labels"] != barrier_taxonomy.OTHER]["labels"].value_counts()
            other = int((ex["labels"] == barrier_taxonomy.OTHER).sum())
            if len(cnt):
                fi = go.Figure(go.Bar(y=list(cnt.index), x=cnt.values, orientation="h", marker_color=LENS_COLORS["MyACUVUE app"], text=cnt.values,
                                      textposition="outside", cliponaxis=False, customdata=[[k] for k in cnt.index]))
                fi.update_layout(height=90 + 46 * len(cnt), xaxis_title="Negative app reviews", margin=dict(r=40))
                fi.update_yaxes(autorange="reversed", title=None)
                ev3 = ui.plot(fi, f"{cnt.index[0]} is the top issue ({int(cnt.iloc[0])} of {len(neg)} negative reviews).", key="bp_issues", select=True,
                              note=f"A review can carry several labels; {other} carry none. Click a bar for the reviews.",
                              bases=len(neg), noun="negative app reviews")
                pk3 = ui.picked(ev3)
                if pk3:
                    lab = pk3[0][0] if isinstance(pk3[0], tuple) else pk3[0]
                    ui.items_panel(vd.view(neg[neg["labels"].map(lambda ls: lab in ls)]), f"App reviews: {lab}")
        if len(a):
            srt = a.sort_values("date", ascending=False, na_position="last").head(500)
            allrev = vd.view(a, limit=500).drop(columns=["Brand", "Link"])
            allrev.insert(2, "Store", srt["retailer"].map(STORE_NAMES).fillna(srt["retailer"]).values)
            allrev.insert(3, "Stars", srt["rating_native"].values)
            ui.show_data("Show all written app reviews", allrev, "Newest first. 'Sentiment' is the tagger's reading of the words, not the star rating.",
                         column_config={"Text": st.column_config.TextColumn("Text", width="large")})
            by = a.groupby("retailer").agg(n=("item_id", "size"), neg=("sentiment", lambda x: (x == "negative").mean() * 100),
                                           stars=("rating_native", "mean"))
            sp = pd.DataFrame({"Store": [STORE_NAMES.get(k, k) for k in by.index], "Written reviews": by["n"].values,
                               "Negative": [f"{v:.0f}%" if n >= ebi.MIN_N else "-" for v, n in zip(by["neg"], by["n"])],
                               "Average stars": by["stars"].round(2).values})
            ui.show_data("Show the split by store", sp, "A rate is shown only with 15+ written reviews. Apple has few (24), so read its rate as directional. "
                         "Google Play carries most of the written reviews, so the pooled figures above mostly describe Google Play.")
        if not rev.empty:
            with st.expander("Retailer link: the app against the shops that sell it", expanded=False, on_change="rerun", key="bp_app_retailer") as ex:
                if ex.open:
                    barriers_friction._retailer_link_section(rev.assign(themes=rev["full_text"].map(barriers_friction._themes)))
            with st.expander("What the store listings say the app collects", expanded=False, on_change="rerun", key="bp_app_privacy") as ex:
                if ex.open:
                    barriers_friction._privacy_section()
        st.caption("Developer replies were not scraped.")

    # ---- 5. Message: stage, barrier, draft message (the WhatsApp map) ----------------------------------------------
    with t_msg:
        ui.section("Registration help is the one message WhatsApp can answer directly",
                   "Stage, barrier, then a draft message to test.", "3 · Message", kind="dir")
        whatsapp_map.render(jf_new, brands, heading=False)

    _p = F["pool"]
    _own = pd.concat([_p[_p["brand_std"] == FOCAL], a], ignore_index=True)
    ui.read_comments(_own[_own["item_id"].isin(set(vd.complaints(_own)["item_id"]))], f"Read the {FOCAL} complaints behind this page (consumers and app)", key="bp_read")


JOURNEY_COLORS = {"Consumer, brand-named": "#178197", "Consumer, no brand": "#8CC4CF", "App": "#7048E8", "Retail reviews": "#C98B2B"}


def _journey_section(d: pd.DataFrame) -> None:
    """1 · Journey: at each stage of the consumer journey, where is the friction? Every complaint item from consumer comments, the app
    and store reviews on one axis, stacked by source type (counts: the sources are never pooled into a rate). A second grid says what
    the friction at each stage is about. The stage is where the problem happens, read by the model from the text and the source."""
    fr = vd.friction(d)
    if fr.empty or not len(vd.stage_table()):
        ui.section("Where in the journey the friction happens", "The stage table has not been built.", "1 · Journey", kind="fact")
        st.info("Not run yet: python tag_journey_stage.py --mode full --confirm (from the Scripts folder).")
        return
    scopes = ["All sources", f"{FOCAL} only", f"{FOCAL} consumers only"]
    scope = st.segmented_control("Show", scopes, default=scopes[2], key="bp_jscope") or scopes[2]
    own = (fr["lens"] == "Consumer, brand-named") & (fr["brand_std"] == FOCAL)   # Acuvue's own words: consumers who name Acuvue; store reviews and category comments are not about the brand
    if scope == scopes[1]:
        fr = fr[own | (fr["lens"] == "App")]
    elif scope == scopes[2]:   # no channel decides the stage here: the peak is read from the comment alone
        fr = fr[own]
    cols = vd.STAGE_LIST + [vd.NO_STAGE]
    ct, tot, ok, top = _stage_counts(fr)
    n_all, n_staged = int(tot.sum()), int(tot[vd.STAGE_LIST].sum())
    top_lens = ct.loc[top].idxmax() if top else None
    who = {scopes[0]: "complaints across all sources", scopes[1]: f"{FOCAL} complaints", scopes[2]: f"{FOCAL} consumer complaints"}[scope]
    title = (f"Friction is heaviest at {top}: {int(ok[top])} of {n_staged} {who} that name a stage" if top
             else "Too few complaints at any one stage to name a peak")
    ui.section(title, "Where the problem happens, read from each complaint. Shown for Acuvue consumers alone, where the comment decides the stage; the app view places sign-in and registration at Trial by design, so switch to it to see the app's share.",
               "1 · Journey", kind="fact")

    thin = [bool(0 < tot[c] < ebi.MIN_N) for c in cols]
    fig = go.Figure()
    for lens in [x for x in vd.FRICTION_LENS if ct[x].sum() > 0]:
        fig.add_bar(x=cols, y=ct[lens].values, name=lens, marker=dict(color=JOURNEY_COLORS[lens], pattern=charts.thin_fill(thin)),
                    text=[str(v) if v >= ebi.MIN_COUNT else "" for v in ct[lens].values], textposition="inside", insidetextanchor="middle",
                    textfont=dict(color="#191919" if lens == "Consumer, no brand" else "#FFFFFF", size=11),
                    customdata=[[c, lens] for c in cols], hovertemplate="%{x} · " + lens + ": %{y} complaints<extra></extra>")
    fig.update_layout(barmode="stack", height=340, yaxis_title="Complaint items", legend=dict(orientation="h", y=-0.2, title_text=""),
                      xaxis=dict(categoryorder="array", categoryarray=cols))
    say = (f"{top} draws the most friction, mostly from {top_lens.lower()} ({int(ct.loc[top, top_lens])} of {int(ok[top])})."
           if top else "Friction by journey stage.")
    ev = ui.plot(fig, say, key="bp_journey", select=True,
                 note=f"Counts, not rates: the sources differ in size and tone, so they are stacked, never pooled. Hatched = under {ebi.MIN_N} complaints at that stage. "
                      f"{int(tot[vd.NO_STAGE])} of {n_all} complaints name no stage. Click a bar for the items.",
                 bases={k: int(v) for k, v in ct.sum().items() if v}, noun="complaint items")

    # what the friction at each stage is about
    cells = [(c, g, int(((fr["stage"] == c) & fr["cgroups"].map(lambda gs, g=g: g in gs)).sum())) for g in vd.GROUP_LIST for c in cols]
    top_cell = max((x for x in cells if x[0] != vd.NO_STAGE), key=lambda x: x[2])
    top_cnt = max(x[2] for x in cells) or 1
    solid, hollow = [x for x in cells if x[2] >= ebi.MIN_COUNT], [x for x in cells if x[2] < ebi.MIN_COUNT]
    fg = go.Figure()
    fg.add_scatter(x=[x[0] for x in solid], y=[x[1] for x in solid], mode="markers+text", showlegend=False,
                   marker=dict(symbol="square", size=54, color=[x[2] for x in solid], cmin=0, cmax=top_cnt,
                               colorscale=[[0, "#EEF3F7"], [0.5, "#E9C877"], [1, "#B42318"]], line=dict(width=0)),
                   text=[f"<b>{x[2]}</b>" for x in solid], textfont=dict(size=12, color="#191919"),
                   customdata=[[x[0], x[1]] for x in solid], hovertemplate="%{customdata[1]} at %{customdata[0]}: %{text} complaints<extra></extra>")
    fg.add_scatter(x=[x[0] for x in hollow], y=[x[1] for x in hollow], mode="markers+text", showlegend=False,
                   marker=dict(symbol="square", size=54, color="#FFFFFF", line=dict(width=1.5, color="#94A3B8")),
                   text=[str(x[2]) for x in hollow], textfont=dict(size=11, color="#64748B"),
                   customdata=[[x[0], x[1]] for x in hollow],
                   hovertemplate="%{customdata[1]} at %{customdata[0]}: %{text} complaints (under 10, count only)<extra></extra>")
    fg.update_xaxes(categoryorder="array", categoryarray=cols, side="top", showgrid=False, title=None, range=[-0.5, len(cols) - 0.5])
    fg.update_yaxes(autorange="reversed", showgrid=False, title=None, categoryorder="array", categoryarray=vd.GROUP_LIST)
    fg.update_layout(height=130 + 62 * len(vd.GROUP_LIST))
    grid_say = (f"At {top_cell[0]}, {top_cell[1]} is the biggest source of friction ({top_cell[2]} complaints)." if top_cell[2] >= ebi.MIN_COUNT
                else "Friction by stage and topic group.")
    ev2 = ui.plot(fg, grid_say, key="bp_journey_grid", select=True,
                  note="Cell = complaint items on the topic group at that stage; an item can carry two groups. Hollow = under 10, count only. Click a cell for the items.",
                  bases={"Complaint items": n_all}, noun="items")

    pk, pk2 = ui.picked(ev), ui.picked(ev2)
    if pk:
        stg, lens = pk[0]
        ui.items_panel(vd.view(fr[(fr["stage"] == stg) & (fr["lens"] == lens)]), f"{stg}: {lens.lower()} complaints")
    elif pk2:
        stg, grp = pk2[0]
        ui.items_panel(vd.view(fr[(fr["stage"] == stg) & fr["cgroups"].map(lambda gs: grp in gs)]), f"{stg}: {grp} complaints")
    conf = fr[fr["stage"] != vd.NO_STAGE]["stage_conf"].value_counts(normalize=True)
    tbl = ct.assign(All=tot).reset_index().rename(columns={"stage": "Stage"})
    ui.show_data("Show the stage table", tbl,
                 f"Complaint items per stage and source type. {conf.get('high', 0) * 100:.0f}% of staged complaints were read with high confidence; "
                 "the rest are inferred from the source or the topic. Read a stage as accurate to about one step, most of all for store reviews. "
                 "Stage comes from Scripts/tag_journey_stage.py (gpt-4o, checked by hand on a 150-item pilot).")
    with st.expander("Which stages each channel is built to evidence", expanded=False, on_change="rerun", key="bp_role_map") as ex:
        if ex.open:
            ui.plot(_stage_map(d), "Each channel is placed on the stages it is built to evidence.", key="bp_stage",
                    note="This is the channel's role (context.md), set before any comment is read; the chart above is where each complaint was placed from its own text.",
                    bases="Tagged items per channel; the app is Acuvue only")


def _stage_map(d: pd.DataFrame) -> go.Figure:
    """Channel x journey-stage grid: a cell is filled where the channel is built to evidence that stage (context.md) and shows how many
    tagged items it holds."""
    chans = list(vd.CHANNEL_ROLE)
    z, txt = [], []
    for c in chans:
        stages = {STAGE_FIX.get(s.strip(), s.strip()) for s in vd.CHANNEL_ROLE[c][0].split(",")}
        s = d[(d["source"] == c) & ((d["in_pool"] == 1) | (d["source"].isin([vd.APP, vd.MAPS, "Facebook retailer reviews"])))]
        if c in (vd.MAPS, "Facebook retailer reviews"):
            s = s[s["lens_relevant"] == 1]
        n = len(s)
        z.append([n if st_ in stages else None for st_ in JOURNEY_STAGES])
        txt.append([f"{n}" if st_ in stages else "" for st_ in JOURNEY_STAGES])
    fig = go.Figure(go.Heatmap(z=z, x=JOURNEY_STAGES, y=chans, text=txt, texttemplate="%{text}", colorscale=[[0, "#E8F3F5"], [1, "#5FB0C0"]],
                               zmin=0, zmax=300, xgap=3, ygap=3, showscale=False, hoverongaps=False,
                               hovertemplate="%{y} · %{x}: %{text} tagged items<extra></extra>", textfont=dict(size=11, color="#191919")))
    fig.update_xaxes(side="top", tickangle=0, title=None)
    fig.update_yaxes(autorange="reversed", title=None)
    fig.update_layout(height=110 + 34 * len(chans), plot_bgcolor="#F8FAFC", margin=dict(t=50, l=10, r=10, b=10))
    return fig
