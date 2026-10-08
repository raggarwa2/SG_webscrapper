"""
Barriers & journey: what stops registration and purchase, and which message goes where?

One page for the old Journey & barriers, the app detail and the retailer view. A complaint has one definition everywhere: an item
that is negative or mixed on a theme group. The consumer-voice lens (compared with peers), the MyACUVUE app (Acuvue only) and
retail reviews (about the shop) are drawn side by side and never pooled.

Order (Pyramid Principle): the answer card, then 1 Journey (where the friction happens, the frame for the rest), 2 Barrier (what it
is about), 3 App, 4 Retail, 5 Message (the WhatsApp map), then collapsed supporting data. Charts are shown; tables and reviews sit behind a click.
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
        grade = ("Not tested" if not testable else ("Level" if not higher else ("A · corroborated" if len(where) >= 2 else "B · one channel")))
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


def render(d: pd.DataFrame, brands: list) -> None:
    if d.empty:
        st.info("Run Scripts/build_voice_items.py and Scripts/tag_voice_items.py to build the tables this page reads.")
        return
    F = facts(d)
    p, a, m, rates, eras = F["pool"], F["app"], F["maps"], F["rates"], F["eras"]
    n_f, n_p = int((p["brand_std"] == FOCAL).sum()), int((p["brand_std"] != FOCAL).sum())
    last = eras.iloc[-1] if len(eras) else None
    app_ok = last is not None and last["n"] >= ebi.MIN_N
    top, sig = F["top"], F["sig"]
    peers = [b for b in brands if b != FOCAL]
    jf_new = wa_frame(d)
    wa = whatsapp_map.build(jf_new, FOCAL, peers) if FOCAL in brands else pd.DataFrame()
    wa_top = wa[wa["WhatsApp can help"] == "Directly"].head(1) if len(wa) else wa

    # ---- retail numbers
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

    # ---- answer card ----------------------------------------------------------------------------------------------
    # The bottom line gives the verdicts only. The tiles carry the figures the headline strip does not (journey, retail, message); the
    # complaint topic and the app figure are in the strip, so their sections have no tile.
    bottom = "The app is the clearest barrier." if app_ok else "The app reviews are too few to read by period."
    if top is not None and F["n_complaints_f"] >= ebi.MIN_N:
        top_gap = top["grade"] in ("B · one channel", "A · corroborated")
        bottom += f" Beyond it, {top['group']} leads the complaints" + (f", above peers on {', '.join(top['where']) or 'one channel'}" if top_gap else ", level with peers") + "."
        extra = sig[sig["group"] != top["group"]]
        if len(extra):
            bottom += f" {extra.iloc[0]['group']} runs above peers on {_where(extra, p)}."
    tiles = []
    jf = F["journey"]
    if jf and jf["top"]:
        tiles.append({"label": "Journey", "n": 1, "msg": f"Friction peaks at {jf['top']}; the app supplies {jf['top_app']} of its {jf['top_n']}", "value": f"{jf['top_n']} complaints",
                      "tone": "watch", "stat": f"Acuvue complaint items (consumer comments and app reviews) placed at {jf['top']}, of {jf['n_staged']} that name a stage",
                      "text": (f"Acuvue-named consumers alone peak at {jf['own_top']} ({jf['own_top_n']} of {jf['own_staged']})" if jf["own_top"] else "")})
    if m_pos is not None:
        tiles.append({"label": "Retail", "n": 4, "msg": "Store reviews are about the shop, not the brand", "value": f"{m_pos:.0f}% positive", "tone": "flat",
                      "stat": "Contact-lens store reviews that are positive", "text": f"n={len(m)}; only {m_acu} name Acuvue"})
    if len(wa_top):
        r0 = wa_top.iloc[0]
        tiles.append({"label": "Message", "n": 5, "msg": f"WhatsApp can help most directly with {r0['Barrier']}", "value": f"Send at {r0['Send at stage']}", "tone": "good",
                      "stat": "Journey stage for the first message"})
    implication = "Start WhatsApp with sign-in, OTP and date-of-birth help where people first meet the app, then comfort proof and first-fitting guidance."
    ui.pyramid(bottom, tiles, implication)

    cf = vd.complaints(p[p["brand_std"] == FOCAL])
    ca = vd.complaints(a) if len(a) else pd.DataFrame(columns=["item_id", "group", "pol"])
    cm = vd.complaints(m) if len(m) else pd.DataFrame(columns=["item_id", "group", "pol"])

    ui.nav(["1 · Journey", "2 · Barrier", "3 · App reviews", "4 · Retail", "5 · Message"])
    t_jour, t_bar, t_app, t_ret, t_msg = (st.container() for _ in range(5))

    # ---- 2. Barrier -----------------------------------------------------------------------------------------------
    with t_bar:
        t1 = (f"Complaints about {FOCAL} centre on {top['group']}; no group differs from peers" if top is not None and not len(sig)
              else (f"{FOCAL} draws more complaints than peers on {', '.join(sig['group'])}, on {_where(sig, p)}" if len(sig) else "Complaints by topic"))
        ui.section(t1, "Complaint = a negative or mixed item on a topic group. Same rule on every channel.",
                   "2 · Barrier", kind="fact")
        c1, c2 = st.columns(2)
        with c1:
            rows = [(r.group, f"{r.group}<br><span style='font-size:10px;color:{charts.MUTED if min(r.kf, r.ko) >= ebi.MIN_N else charts.AMBER}'>{r.kf} vs {r.ko} complaints</span>",
                     r.kf, r.rf, r.ko, r.ro) for r in rates.itertuples()]
            fig = charts.pair_bars(rows, "% of each side's items that carry a complaint on the group", focus=FOCAL)
            fig.update_layout(height=130 + 60 * len(vd.GROUP_LIST))
            ev = ui.plot(fig, "Share of items that complain, by topic group.", key="bp_rates", select=True,
                         note="Hatched under 15 complaints; not drawn under 10. " + _rate_note(rates) + " Click a bar for the items.",
                         bases={FOCAL: n_f, "Peers": n_p}, noun="consumer items")
        with c2:
            lens_n = {"Consumer voice": n_f, "MyACUVUE app": len(a), "Retail reviews": len(m)}
            lens_c = {"Consumer voice": cf, "MyACUVUE app": ca, "Retail reviews": cm}
            cells = []
            for lens, c in lens_c.items():
                for g in vd.GROUP_LIST:
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
            fig2.update_yaxes(autorange="reversed", showgrid=False, title=None, categoryorder="array", categoryarray=vd.GROUP_LIST)
            fig2.update_layout(height=130 + 60 * len(vd.GROUP_LIST))
            ev2 = ui.plot(fig2, "Product complaints sit in consumer voice; loyalty and registration complaints sit in the app.", key="bp_lens", select=True,
                          note=f"Cell = % of that lens's items with a complaint on the group, then the item count. Hollow = under 10 complaints, count only. "
                               f"Consumer voice = {FOCAL} only; retail reviews are about the shop. Click a cell for the items.",
                          bases={"Consumer voice": n_f, "App reviews": len(a), "Retail reviews": len(m)}, noun="items")
        pk, pk2 = ui.picked(ev), ui.picked(ev2)
        if pk:
            grp, side = pk[0]
            pool_side = p[(p["brand_std"] == FOCAL) if side == "focus" else (p["brand_std"] != FOCAL)]
            ids = set(vd.complaints(pool_side).query("group == @grp")["item_id"])
            ui.items_panel(vd.view(pool_side[pool_side["item_id"].isin(ids)]), f"{grp}: {FOCAL if side == 'focus' else 'peer'} complaints")
        elif pk2:
            grp, lens = pk2[0]
            src = {"Consumer voice": p[p["brand_std"] == FOCAL], "MyACUVUE app": a, "Retail reviews": m}[lens]
            ids = set(vd.complaints(src).query("group == @grp")["item_id"]) if len(src) else set()
            ui.items_panel(vd.view(src[src["item_id"].isin(ids)]), f"{grp}: {lens.lower()} complaints")
        tr = pd.DataFrame({"Group": rates["group"], f"{FOCAL} complaints": rates["kf"], f"{FOCAL} % of items": rates["rf"].round(1),
                           "Peer complaints": rates["ko"], "Peers % of items": rates["ro"].round(1),
                           "Test": [("p=%.3f" % pv if t and pv is not None else "under 15 complaints, not tested") for pv, t in zip(rates["p"], rates["testable"])],
                           "Evidence": rates["grade"], "Seen in": [", ".join(w) or "-" for w in rates["where"]]})
        ui.show_data("Show the complaint table", tr, "A difference is only called real with 15+ complaints across both groups and p<0.05 (two-proportion test). "
                      "Four groups are tested at once, so a p near 0.05 is weak on its own: the channel check says whether it shows beyond one channel.")

    # ---- 1. Journey: where the friction happens -------------------------------------------------------------------
    with t_jour:
        _journey_section(d)

    # ---- 3. App ---------------------------------------------------------------------------------------------------
    with t_app:
        ui.section(f"The app is where registration breaks: {last['neg']:.0f}% of {last['era']} reviews are negative" if app_ok else "The MyACUVUE app",
                   "Apple App Store and Google Play. Acuvue only; kept out of brand comparisons.", "3 · App reviews", kind="fact")
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

    # ---- 4. Retail ------------------------------------------------------------------------------------------------
    with t_ret:
        ui.section(f"Store reviews are {m_pos:.0f}% positive; complaints sit on service and guidance" if m_pos is not None else "Retail experience",
                   "Google Maps reviews about contact lenses. About the shop, not the brand; skews positive.",
                   "4 · Retail", kind="fact")
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

    # ---- 5. Message: stage, barrier, draft message (the WhatsApp map) ----------------------------------------------
    with t_msg:
        ui.section("Registration help is the one message WhatsApp can answer directly",
                   "Stage, barrier, then a draft message to test.", "5 · Message", kind="dir")
        whatsapp_map.render(jf_new, brands, heading=False)

    ebi.limits([
        "<b>Which barrier stops a given customer</b>: needs the survey and WhatsApp logs.",
        "Written reviews are self-selected and skew negative: they show types of friction, not how common each is.",
        "Store reviews are about retailers (mostly Owndays) and skew positive.",
    ])


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
    scope = st.segmented_control("Show", scopes, default=scopes[1], key="bp_jscope") or scopes[1]
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
    ui.section(title, "Where the problem happens, read from each complaint and its source. App sign-in and registration are placed at Trial, so the app drives that bar; the Acuvue-consumers view shows comments alone.",
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
