"""
Journey & App: where does the friction happen, how does the MyACUVUE app lose people, and which message goes where?

The tab keeps 1 App reviews, 2 Journey (where the friction happens) and 3 Message (the WhatsApp map). The framework Barrier read lives
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
import theme_tags
import ui
import voice_data as vd
import whatsapp_map
import palette
from sg_common import BRAND_COLORS, JOURNEY_STAGES, SENTIMENT_COLORS

FOCAL = vd.FOCAL
STORE_NAMES = {"app_store": "Apple App Store", "play_store": "Google Play"}
LENS_COLORS = palette.LENS_COLORS
STAGE_FIX = {"Repeat": "Repeat/Retention"}
# Section 2 reads the framework barrier labels (the desk-research list, as on Triangulation), not the four decision groups. Product &
# look is left out: it is not a barrier a WhatsApp message can move, and it is no longer reported on any page.
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


POS_COLOR, NEG_COLOR, LOW_GREY = palette.POS_COLOR, palette.NEG_COLOR, palette.LOW_GREY   # colourblind-safe pair; grey marks a low sample (under 10 mentions)
POS_LIGHT, NEG_LIGHT = palette.POS_LIGHT, palette.NEG_LIGHT   # lighter shade of each, for a side under 10 mentions in the theme charts
LOW = 10


def _theme_split(f: pd.DataFrame) -> list:
    """[{theme, n, pos, neg, oth}] sorted by mentions: every item that touches the theme, split by the polarity the model gave it."""
    rows = []
    for t in theme_tags.THEMES:
        pols = pd.Series([pl[t] for th, pl in zip(f["themes"], f["pol"]) if t in th], dtype=object)
        rows.append({"theme": t, "n": len(pols), "pos": int((pols == "positive").sum()), "neg": int((pols == "negative").sum()),
                     "oth": int(pols.isin(["neutral", "mixed"]).sum())})
    return sorted(rows, key=lambda r: -r["n"])


def _source_line(f: pd.DataFrame, extra: str = "") -> str:
    names = ", ".join(f["source"].replace(CHANNEL_NAME).value_counts().index)
    return f"Source: {names}, {f['date'].min():%b %Y} to {f['date'].max():%b %Y}. Total items: {len(f)}.{extra}"


def _theme_chart(f: pd.DataFrame, key: str, who: str, order: list | None = None):
    """One diverging chart: the eight themes, negative mentions left of the centre line and positive right, sorted by mentions. Each label is the
    count and its share of that theme's mentions; a side under 10 mentions is lighter and says so. Returns the click event."""
    rows = _theme_split(f)
    if order:   # the same row order in every chart (set by the all-brands chart), so a row does not move when the brand changes
        rows = sorted(rows, key=lambda r: order.index(r["theme"]))
    top = max(max(r["pos"], r["neg"]) for r in rows) or 1
    names = [f"{r['theme'].replace(' & ', ' and ')}  ({r['n']})" for r in rows]
    fig = go.Figure()
    for side, sign, col, light in (("neg", -1, NEG_COLOR, NEG_LIGHT), ("pos", 1, POS_COLOR, POS_LIGHT)):
        vals = [r[side] for r in rows]
        fig.add_bar(y=names, x=[sign * v for v in vals], orientation="h", showlegend=False, marker_color=[light if v < LOW else col for v in vals],
                    text=[(f"{v} ({v / r['n'] * 100:.0f}%)" + ("<br>low sample" if v < LOW else "")) if v else "" for v, r in zip(vals, rows)],
                    textposition="outside", cliponaxis=False, textfont=dict(size=11, color=palette.TEXT),
                    customdata=[[r["theme"], side] for r in rows], hoverinfo="text",
                    hovertext=[f"{r['theme']}: {v} {'negative' if side == 'neg' else 'positive'} of {r['n']} mentions" for v, r in zip(vals, rows)])
    fig.add_annotation(x=-top * 0.7, y=1, yref="paper", yshift=14, text="<b>Negative mentions</b>", showarrow=False, font=dict(size=13, color=NEG_COLOR))
    fig.add_annotation(x=top * 0.7, y=1, yref="paper", yshift=14, text="<b>Positive mentions</b>", showarrow=False, font=dict(size=13, color=POS_COLOR))
    fig.update_xaxes(range=[-top * 1.75, top * 1.75], visible=False)
    fig.update_yaxes(autorange="reversed", title=None, tickfont=dict(size=12), automargin=True)
    fig.update_layout(barmode="overlay", height=90 + 46 * len(rows), margin=dict(l=10, r=10, t=40, b=10),
                      shapes=[dict(type="line", xref="x", yref="paper", x0=0, x1=0, y0=0, y1=1, line=dict(color=palette.RULE, width=1))])
    return ui.plot(fig, "", key=key, select=True, bases=len(f), noun=who)


def render_split_brands(d: pd.DataFrame, brands: list) -> None:
    """Category level beside one brand: all selected brands together on the left, Acuvue on the right with a toggle for any other brand."""
    if d.empty:
        return
    p = vd.pool(d)
    p = p[p["brand_std"].isin(brands)] if brands else p
    if p.empty:
        st.info("No brand-named comments to show.")
        return
    names = list(charts.order_brands(p["brand_std"].unique()))
    app_rows = vd.app(d)
    choices = list(names)   # the app sits next to Acuvue (its own app); it is not a brand in the pool
    if len(app_rows):
        choices.insert(choices.index(FOCAL) + 1 if FOCAL in choices else 0, vd.APP)
    order = [r["theme"] for r in _theme_split(p)]   # themes sorted by mentions across all brands; both charts keep this order
    left, right = st.columns(2)
    with left:
        st.segmented_control("Panel", ["All brands"], default="All brands", disabled=True, key="bp_split_all_tab", label_visibility="collapsed")   # same height as the brand picker, so both charts line up
        ev_l = _theme_chart(p, "bp_split_all", "brand-named items", order)
    with right:
        pick = st.segmented_control("Brand", choices, default=FOCAL if FOCAL in names else choices[0], key="bp_split_brand", label_visibility="collapsed") \
            or (FOCAL if FOCAL in names else choices[0])
        fb = app_rows if pick == vd.APP else p[p["brand_std"] == pick]
        ev_r = _theme_chart(fb, "bp_split_one", f"{pick} items", order)
        if pick == vd.APP:
            st.caption("App-store reviews of Acuvue's own app, not brand-named comments: not comparable with the brand panels or the all-brands chart.")
    st.caption(_source_line(p) + " Percentages are the share of that theme's mentions. "
               "Lighter bars = low sample (under 10). A comment can mention more than one theme.")
    for ev, f, nm in ((ev_l, p, "All brands"), (ev_r, fb, pick)):
        pk = ui.picked(ev)
        if pk:
            theme, side = pk[0]
            pol = "negative" if side == "neg" else "positive"
            hit = f[[(theme in th and pl.get(theme) == pol) for th, pl in zip(f["themes"], f["pol"])]]
            ui.items_panel(vd.view(hit), f"{nm}, {theme.lower()}: {pol} mentions")
    rows = []
    for nm, f in [("All brands", p)] + [(b, p[p["brand_std"] == b]) for b in names] + ([(vd.APP, app_rows)] if len(app_rows) else []):
        rows += [{"Panel": nm, "Theme": r["theme"], "All mentions": r["n"], "Negative": r["neg"], "Positive": r["pos"], "Neutral or mixed": r["oth"]} for r in _theme_split(f)]
    ui.show_data("Show the table (all brands, each brand, the app)", pd.DataFrame(rows))


CATEGORY_VIEWS = ["Bars: all brands and one brand", "Heatmap: sources and brands"]


def render_category(d: pd.DataFrame, brands: list) -> None:
    """Category: what customers mention, by theme. One section, two views of the same eight themes: bars (all brands beside one brand, with positive and
    negative side by side) or the heatmap of sources and brands."""
    if d.empty:
        return
    p, a, m = vd.pool(d), vd.app(d), vd.maps(d)
    pf = p[p["brand_std"] == FOCAL]
    n_ca, n_cm = (int(vd.complaints(x)["item_id"].nunique()) if len(x) else 0 for x in (a, m))
    ui.section("What customers mention, by theme", "The eight shared themes, model-tagged; an item can touch two. Below this: what Acuvue's customers complain about, by framework barrier.", "Category")
    st.caption(f"Bases: {len(p)} brand-named comments ({len(pf)} about {FOCAL}); {len(a)} MyACUVUE app reviews ({n_ca} complaints); retail reviews, {n_cm} complaints. "
               "Each group is read on its own and never added to another.")
    view = st.segmented_control("View", CATEGORY_VIEWS, default=CATEGORY_VIEWS[0], key="bp_cat_view") or CATEGORY_VIEWS[0]
    if view == CATEGORY_VIEWS[0]:
        render_split_brands(d, brands)
    else:
        render_theme_bubble(d, brands)
    _sel = p[p["brand_std"].isin(brands)] if brands else p
    ui.read_comments(pd.concat([_sel, a], ignore_index=True), "Read the comments behind the Category charts (brand-named comments and app reviews)", key="bp_cat_read")


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
    _short = {"App utility & support": "App use", "Registration / login friction": "Sign-in"}
    _rank = cnt.sort_values(ascending=False)
    _t1, _t2 = _rank.index[0], _rank.index[1]
    t1 = (f"{_short.get(_t1, _t1)} and {_short.get(_t2, _t2).lower()} are the two largest barriers: {int(_rank.iloc[0])} and {int(_rank.iloc[1])} of {n_own} {FOCAL} complaints"
          if n_own and int(_rank.iloc[1]) >= ebi.MIN_COUNT else f"Framework barriers in complaints: {FOCAL} consumers, the MyACUVUE app and retail reviews")
    ui.section(t1, "The desk-research framework barriers, read on complaint items (negative or mixed). An item can carry several. "
                   f"{n_prod} Product & look complaints (consumer items) are set aside: no WhatsApp message moves them. "
                   "Peers are not compared: too few Acuvue consumer complaints sit on these barriers.",
               "Barriers in complaints", kind="fact")
    c1, c2 = st.columns(2)
    with c1:
        ks = [int(cnt[b]) for b in BARRIERS]
        drawn = [k >= ebi.MIN_COUNT for k in ks]
        fig = go.Figure(go.Bar(
            y=BARRIERS, x=[k / n_own * 100 if ok else None for k, ok in zip(ks, drawn)], orientation="h", marker_color=[palette.APP_COLOR if b in _short else palette.PEER_GREY for b in BARRIERS],
            marker_pattern_shape=["/" if ebi.is_thin(k) else "" for k in ks],
            text=[f"{k} ({k / n_own * 100:.0f}%)" if ok else "" for k, ok in zip(ks, drawn)], textposition="outside", cliponaxis=False,
            customdata=[[b, "own"] for b in BARRIERS], hovertemplate="%{y}: %{x:.0f}% of complaint items<extra></extra>"))
        fig.update_xaxes(range=[0, max([k / n_own * 100 for k in ks] + [1]) * 1.35], ticksuffix="%", title=f"% of {FOCAL}'s complaint items")
        fig.update_yaxes(autorange="reversed", title=None)
        fig.update_layout(height=130 + 60 * len(BARRIERS), showlegend=False)
        under = [f"{b} {k}" for b, k, ok in zip(BARRIERS, ks, drawn) if not ok and k]
        _app_n = int(own[own["group"].isin(_short)]["item_id"].nunique())
        ev = ui.plot(fig, f"{_app_n} of {n_own} {FOCAL} complaints touch app use or sign-in. Open the WhatsApp message with help signing in and using the app." if n_own else "",
                     "dir", key="bp_rates", select=True,
                     note="Blue = app use and sign-in. Hatched under 15 items; not drawn under 10" + (f" (counts: {', '.join(under)})" if under else "") + ". Click a bar for the items.",
                     bases={"Consumer, brand-named": n_cf, "App": n_ca}, noun="complaint items")
    with c2:
        lens_n = {"Consumer voice": n_cf, "MyACUVUE app": n_ca, "Retail reviews": n_cm}
        lens_c = {"Consumer voice": cf, "MyACUVUE app": ca, "Retail reviews": cm}
        cnts = {lens: {g: int(c.loc[c["group"] == g, "item_id"].nunique()) for g in BARRIERS} for lens, c in lens_c.items()}
        order = sorted(BARRIERS, key=lambda g: -sum(cnts[l][g] for l in cnts))
        pal = LENS_COLORS
        fig2 = go.Figure()
        for lens in lens_c:
            ks2 = [cnts[lens][g] for g in order]
            fig2.add_bar(y=order, x=[k or None for k in ks2], orientation="h", name=f"{lens} (n={lens_n[lens]})", marker_color=pal[lens],
                         marker_pattern_shape=["/" if 0 < k < ebi.MIN_COUNT else "" for k in ks2],
                         text=[str(k) if k else "" for k in ks2], textposition="inside", textfont=dict(color=palette.WHITE, size=12),
                         customdata=[[g, lens] for g in order], hovertemplate="%{y} in " + lens + ": %{x} complaint items<extra></extra>")
        tots = {g: sum(cnts[l][g] for l in cnts) for g in order}
        for g in order:
            fig2.add_annotation(x=tots[g], y=g, text=f"<b>{tots[g]}</b>", showarrow=False, xanchor="left", xshift=6, font=dict(size=12))
        fig2.update_xaxes(title="Complaint items", range=[0, max(tots.values()) * 1.15 + 1])
        fig2.update_yaxes(autorange="reversed", title=None, categoryorder="array", categoryarray=order)
        fig2.update_layout(barmode="stack", height=130 + 60 * len(BARRIERS), legend=dict(orientation="h", y=-0.22, traceorder="normal"))
        _top = {lens: max(order, key=lambda g, l=lens: cnts[l][g]) for lens in lens_n if lens_n[lens] >= ebi.MIN_N and max(cnts[lens].values()) >= ebi.MIN_COUNT}
        _say = "Complaints by framework barrier, split by source."
        ev2 = ui.plot(fig2, _say, key="bp_lens", select=True,
                      note=f"Counts of complaint items, not rates: the three sources have different bases. Hatched = under 10 items, read as direction only. "
                           f"Consumer voice = {FOCAL} only; retail reviews are about the shop. Click a segment for the items.",
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
    _own = pd.concat([pf, a, m], ignore_index=True)
    ui.read_comments(_own[_own["item_id"].isin(set(vd.complaints(_own)["item_id"]))], f"Read the complaints behind this page ({FOCAL} consumers, the app and retail reviews)", key="bar_read")
    ui.goto("Journey & App", "Which message goes with each barrier: Journey & App", key="bar_to_message")

CHANNEL_NAME = {"Xiaohongshu comments": "Xiaohongshu", "Facebook": "Facebook comments"}
LENS_OF = {"consumer_voice": "Consumer voice", "owned_experience": "MyACUVUE app", "retail_experience": "Retail reviews"}
NET_SCALE = palette.NET_SCALE
HEAD_SRC = "BY SOURCE TYPE: who is talking"
HEAD_BRAND = "BY BRAND: brand-named items only"
OTHER = "Other themes"
FOLD_UNDER = 40        # a theme no row reaches this many items on is folded into "Other themes" (when two or more qualify)


def _net(pols) -> float | None:
    """Net sentiment of the polarity the model gave a theme: % positive minus % negative (neutral and mixed stay in the base)."""
    pols = list(pols)
    return (sum(x == "positive" for x in pols) - sum(x == "negative" for x in pols)) / len(pols) * 100 if pols else None


def _theme_rows(d: pd.DataFrame, brands: list) -> list:
    """[(label, frame, colour or None)] for the category theme map. Colour None = coloured by net sentiment. Rows are never added together."""
    x = d[d["lens"].isin(LENS_OF) & (d["is_contest"] != 1)]
    cons, app, shop = (x[x["lens"] == l] for l in LENS_OF)
    src = [("Consumer voice", cons, None), ("MyACUVUE app", app, None), ("Retail reviews (about the shop)", shop, None)]
    pool = cons[cons["in_pool"] == 1]
    pool = pool[pool["brand_std"].isin(brands)] if brands else pool
    bra = [(br, pool[pool["brand_std"] == br], BRAND_COLORS.get(br, palette.RULE)) for br in charts.order_brands(pool["brand_std"].unique())]
    return [(HEAD_SRC, None, None)] + src + [(HEAD_BRAND, None, None)] + bra


def _cells(data: list) -> tuple:
    """({(row, theme): items}, {(row, theme): net or None}, {(row, theme): (frame, ids)}) for the eight themes, read on every row."""
    cell, nets, ids = {}, {}, {}
    for lab, f, _ in data:
        for t in theme_tags.THEMES:
            hit = [(i, pl[t]) for i, th, pl in zip(f["item_id"], f["themes"], f["pol"]) if t in th]
            cell[(lab, t)], ids[(lab, t)] = len(hit), (f, {i for i, _ in hit})
            nets[(lab, t)] = _net(p for _, p in hit) if len(hit) >= ebi.MIN_N else None
    return cell, nets, ids


def _fold(data: list, cell: dict, nets: dict, ids: dict) -> list:
    """Fold the themes no row reaches FOLD_UNDER on into one 'Other themes' column (an item counts once, with the polarity of its first
    folded theme). Returns the folded theme names (empty when fewer than two qualify)."""
    small = [t for t in theme_tags.THEMES if max(cell[(r[0], t)] for r in data) < FOLD_UNDER]
    if len(small) < 2:
        return []
    for lab, f, _ in data:
        hit = []
        for i, th, pl in zip(f["item_id"], f["themes"], f["pol"]):
            got = [pl[t] for t in small if t in th]
            if got:
                hit.append((i, got[0]))
        cell[(lab, OTHER)], ids[(lab, OTHER)] = len(hit), (f, {i for i, _ in hit})
        nets[(lab, OTHER)] = _net(p for _, p in hit) if len(hit) >= ebi.MIN_N else None
    return small


def render_theme_bubble(d: pd.DataFrame, brands: list) -> None:
    """Category themes (HK's Barrier Matches layout). Columns: the eight shared themes (themes no row reaches FOLD_UNDER items on are folded
    into one). Rows: the three source types (consumer voice, app, retail reviews) with the five brands stacked below. Shown as bubbles
    (size = items) or a heatmap (colour = net sentiment, number = items). Rows are never added together (brand rows are part of consumer
    voice). Acuvue is highlighted. This is the brand read, not the WhatsApp one."""
    if d.empty:
        return
    st.caption("Colour: green mostly positive, red mostly negative, pale grey too few to judge.")
    style = st.segmented_control("Show as", ["Heatmap", "Bubbles"], default="Heatmap", key="tb_style") or "Heatmap"
    rows = _theme_rows(d, brands)
    data = [r for r in rows if r[1] is not None and len(r[1])]
    axis = [r for r in rows if r[1] is None or len(r[1])]       # data rows plus the two block banners
    heads = {r[0] for r in axis if r[1] is None}
    alabels = [r[0] for r in axis]
    if not data:
        return
    cell, nets, ids = _cells(data)
    folded = _fold(data, cell, nets, ids)
    main = [t for t in theme_tags.THEMES if t not in folded]
    cols = sorted(main, key=lambda t: -sum(cell[(r[0], t)] for r in data)) + ([OTHER] if folded else [])
    labels = [r[0] for r in data]
    shown = [(lab, t) for lab in labels for t in cols if cell[(lab, t)] >= ebi.MIN_COUNT]
    heat = style == "Heatmap"

    def hover(k):
        n = nets[k]
        return (f"{k[0]}<br>{k[1]}<br>{cell[k]} items"
                + (f", net sentiment {n:+.0f}" if n is not None else f", net sentiment not read (under {ebi.MIN_N} items)") + "<extra></extra>")

    fig = go.Figure()
    if heat:
        row_px = 38
        z = [[None if lab in heads else (nets[(lab, t)] if cell[(lab, t)] >= ebi.MIN_COUNT else None) for t in cols] for lab in alabels]
        thin = [[None if lab in heads else (1 if (nets[(lab, t)] is None and cell[(lab, t)] >= ebi.MIN_COUNT) else None) for t in cols] for lab in alabels]
        txt = [["" if lab in heads else (str(cell[(lab, t)]) if cell[(lab, t)] >= ebi.MIN_COUNT else "") for t in cols] for lab in alabels]
        common = dict(x=cols, y=alabels, text=txt, texttemplate="%{text}", xgap=3, ygap=3, hoverongaps=False)
        fig.add_trace(go.Heatmap(z=thin, colorscale=[[0, palette.BAND], [1, palette.BAND]], showscale=False, hoverinfo="skip", **common))
        fig.add_trace(go.Heatmap(z=z, colorscale=NET_SCALE, zmin=-100, zmax=100, hovertemplate="%{y}<br>%{x}<br>%{text} items, net %{z:+.0f}<extra></extra>",
                                 colorbar=dict(title="Net", thickness=10, len=0.9, tickvals=[-100, 0, 100]), **common))
        fig.update_yaxes(autorange="reversed", title=None, tickvals=alabels,
                         ticktext=["" if x in heads else (f"<b>{x}</b>" if x == FOCAL else x) for x in alabels])
        fig.update_xaxes(tickangle=-35, title=None, side="bottom", automargin=True)
        if FOCAL in alabels:
            i = alabels.index(FOCAL)
            fig.add_shape(type="rect", x0=-0.5, x1=len(cols) - 0.5, y0=i - 0.5, y1=i + 0.5, line=dict(color=BRAND_COLORS[FOCAL], width=2.5), layer="above")
        for i, lab in enumerate(alabels):
            if lab in heads:
                banner(fig, lab, i)
        fig.update_layout(height=60 + row_px * len(alabels) + 80, showlegend=False)
    else:
        row_px = 42
        ypos = {lab: len(alabels) - 1 - i for i, lab in enumerate(alabels)}
        top = max(cell[k] for k in cell if k[1] in cols) or 1
        sz = dict(sizemode="area", sizeref=2 * top / ((row_px * 0.92) ** 2), sizemin=6)
        colour = {r[0]: r[2] for r in data}

        def trace(sel, line=None, **mk):
            return go.Scatter(x=[k[1] for k in sel], y=[ypos[k[0]] for k in sel], mode="markers", showlegend=False,
                              marker=dict(size=[cell[k] for k in sel], opacity=0.85, line=line or dict(width=0), **sz, **mk),
                              customdata=[list(k) for k in sel], hovertemplate=[hover(k) for k in sel])
        by_net = [k for k in shown if colour[k[0]] is None]
        read = [k for k in by_net if nets[k] is not None]
        if read:
            fig.add_trace(trace(read, color=[nets[k] for k in read], colorscale=NET_SCALE, cmin=-100, cmax=100,
                                colorbar=dict(title="Net", thickness=10, len=0.9, tickvals=[-100, 0, 100])))
        if [k for k in by_net if nets[k] is None]:
            fig.add_trace(trace([k for k in by_net if nets[k] is None], color=palette.RULE))
        for lab in labels:
            if colour[lab] is not None:
                focal = lab == FOCAL
                fig.add_trace(trace([k for k in shown if k[0] == lab], color=colour[lab],
                                    line=dict(width=1.5, color=palette.TEXT) if focal else None))
        if FOCAL in ypos:
            fig.add_hrect(y0=ypos[FOCAL] - 0.5, y1=ypos[FOCAL] + 0.5, fillcolor=BRAND_COLORS[FOCAL], opacity=0.09, line_width=0, layer="below")
        fig.update_xaxes(categoryorder="array", categoryarray=cols, tickangle=-35, title=None, automargin=True,
                         showgrid=True, gridcolor="rgba(128,128,128,0.15)")
        fig.update_yaxes(tickvals=[ypos[lab] for lab in alabels],
                         ticktext=["" if x in heads else (f"<b>{x}</b>" if x == FOCAL else x) for x in alabels],
                         range=[-0.5, len(alabels) - 0.5], title=None, showgrid=True, gridcolor="rgba(128,128,128,0.12)")
        for lab in alabels:
            if lab in heads:
                banner(fig, lab, ypos[lab])
        fig.update_layout(height=70 + row_px * len(alabels) + 80, showlegend=False)
    src_rows = {r_[0] for r_ in data if r_[2] is None}
    ok = [k for k in shown if nets[k] is not None and k[1] != OTHER]
    low = [k for k in ok if k[0] in src_rows and nets[k] < 0]
    foc = [k for k in ok if k[0] == FOCAL and nets[k] < 0]
    bits = []
    if low:
        k = min(low, key=lambda k: nets[k])
        bits.append(f"The clearest problem is {k[1]} in {k[0].split(' (')[0]} ({nets[k]:+.0f} net, {cell[k]} items)")
    if foc:
        k = min(foc, key=lambda k: nets[k])
        bits.append(f"{FOCAL}'s weakest theme is {k[1]} ({nets[k]:+.0f} net, {cell[k]} items)")
    say = ("; ".join(bits) + ".") if bits else "Most themes read positive across sources and brands."
    size_how = "Model-tagged; one comment can touch two themes. " + ("Cell number = comments on the theme" if heat else "Bubble size = comments on the theme")
    colour_how = (f"colour = net sentiment (% positive minus % negative; grey under {ebi.MIN_N} items)" if heat
                  else "source-type rows coloured by net sentiment, brand rows in the HK colours (net on hover)")
    fold_note = f" {OTHER} = {', '.join(folded)} (no row reaches {FOLD_UNDER} items)." if folded else ""
    ev = ui.plot(fig, say, key="tb_bubble", select=not heat,
                 note=f"{size_how}; {colour_how}. Not drawn under {ebi.MIN_COUNT} (counts in the table).{fold_note}"
                      + (" Switch to Bubbles to open the items." if heat else " Click a bubble for the items."),
                 bases={r[0]: len(r[1]) for r in data}, noun="tagged items")
    pk = ui.picked(ev) if not heat else []
    if pk:
        lab, t = pk[0]
        f, hit = ids[(lab, t)]
        ui.items_panel(vd.view(f[f["item_id"].isin(hit)]), f"{lab}: {t}")
    ui.show_data("Show the theme table", pd.DataFrame([{"Row": r[0], **{t: cell[(r[0], t)] for t in theme_tags.THEMES}, "Items": len(r[1])} for r in data]),
                 "Items per row and theme (all eight themes, nothing folded). Brand rows are the brand pool (items that name a brand); the other rows read every tagged item of that type.")
    x = d[d["lens"].isin(LENS_OF) & (d["is_contest"] != 1)].copy()
    x["Channel"] = x["source"].replace(CHANNEL_NAME)
    x["Source type"] = x["lens"].map(LENS_OF)
    tb = []
    for (st_, ch), f in x.groupby(["Source type", "Channel"]):
        if len(f) < ebi.MIN_N:
            continue
        row = {"Source type": st_, "Channel": ch, "Tagged items": len(f)}
        for t in theme_tags.THEMES:
            pl = [pl_[t] for th, pl_ in zip(f["themes"], f["pol"]) if t in th]
            n = _net(pl) if len(pl) >= ebi.MIN_N else None
            row[t] = f"{len(pl)}" + (f" ({n:+.0f})" if n is not None else "")
        tb.append(row)
    ui.show_data("Show the channel detail", pd.DataFrame(tb),
                 f"Items touching each theme per channel, with net sentiment in brackets where there are {ebi.MIN_N} or more. Channels with under {ebi.MIN_N} tagged items "
                 "are left out. Channels differ in size and in how many items name a brand (YouTube 46%, Instagram 59%, Reddit 71%, Xiaohongshu 79%).")


def banner(fig, text: str, y) -> None:
    """A grey strip across the plot with the block's name on it: it tells the top block (sources) from the bottom block (brands)."""
    fig.add_shape(type="rect", xref="paper", x0=0, x1=1, yref="y", y0=y - 0.5, y1=y + 0.5, fillcolor=palette.BAND, opacity=0.75, line_width=0, layer="below")
    fig.add_annotation(xref="paper", x=0.004, yref="y", y=y, text=f"<b>{text}</b>", showarrow=False, xanchor="left", yanchor="middle",
                       font=dict(size=12, color=palette.TEXT_MUTED))


def colour_of(rows: list, label: str):
    """The fixed colour of a row (None when it is coloured by net sentiment)."""
    return next((r[2] for r in rows if r[0] == label), None)


def render_retail(d: pd.DataFrame) -> None:
    """Google Maps contact-lens reviews on the shared labels: which topics draw complaints. Sits under Retail & Promotions."""
    if d.empty:
        return
    F = facts(d)
    a, m = F["app"], F["maps"]
    ca = _barrier_complaints(a)
    mc = pd.DataFrame(columns=["group", "positive", "mixed", "negative", "neutral", "total"])
    if len(m):
        mr = [(t, pol) for pp in m["pol"] for t, pol in pp.items()]
        mc = pd.DataFrame(mr, columns=["group", "pol"]).groupby(["group", "pol"]).size().unstack(fill_value=0)
        for c in ("positive", "mixed", "negative", "neutral"):
            if c not in mc.columns:
                mc[c] = 0
        mc["total"] = mc[["positive", "mixed", "negative", "neutral"]].sum(axis=1)
        mc = mc.reset_index()
    m_pos = (m["sentiment"] == "positive").mean() * 100 if len(m) >= ebi.MIN_N else None
    m_acu = int(m["text"].str.contains("acuvue", case=False, na=False).sum()) if len(m) else 0

    ui.section(f"Shops earn praise: {m_pos:.0f}% of {len(m)} store reviews are positive, and {m_acu} name Acuvue" if m_pos is not None else "Retail experience",
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
                      note=f"{int((m['retailer'] == 'Owndays').sum())} are Owndays (own-brand lenses). Click a bar for the reviews.",
                      bases={"Google Maps": len(m)}, noun="contact-lens reviews")
        small = mc[mc["total"] < ebi.MIN_COUNT]
        if len(small):
            st.caption("Not drawn (under 10 tags): " + "; ".join(f"{r.group} {int(r.total)}" for r in small.itertuples()) + ".")
        pk4 = ui.picked(ev4)
        if pk4:
            grp, pol = pk4[0]
            sel = m[m["pol"].map(lambda pp: pp.get(grp) == pol)]
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

    ui.nav(["Journey", "App reviews", "Message"])   # the "Show" toggle opens the page; the menu says there are three sections
    t_jour, t_app, t_msg = (st.container() for _ in range(3))

    with t_jour:
        _journey_section(d)


    # ---- 3. App ---------------------------------------------------------------------------------------------------
    with t_app:
        rev, hist = app_store_signals.load_app_reviews()
        _avg = {}
        if not hist.empty:
            for _st, _g in barriers_friction._star_table(hist).groupby("Store"):
                _avg[_st] = (_g["stars"] * _g["count"]).sum() / _g["count"].sum()
        _hi, _lo = (max(_avg, key=_avg.get), min(_avg, key=_avg.get)) if len(_avg) == 2 else (None, None)
        _title = (f"{_hi} users rate the app {_avg[_hi]:.2f}, against {_avg[_lo]:.2f} on {_lo}" if _hi and _avg[_hi] - _avg[_lo] >= 0.2
                  else "MyACUVUE app ratings in both stores")
        ui.section(_title,
                   "Apple App Store and Google Play. Written reviews skew negative; the star ratings below are milder. Acuvue only; kept out of brand comparisons.", "App reviews", kind="fact")
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
        ui.section("Message by stage and barrier", "Stage, barrier, then a draft message to test.", "Message", kind="dir")
        whatsapp_map.render(jf_new, brands, heading=False)

    _p = F["pool"]
    _own = pd.concat([_p[_p["brand_std"] == FOCAL], a], ignore_index=True)
    ui.read_comments(_own[_own["item_id"].isin(set(vd.complaints(_own)["item_id"]))], f"Read the {FOCAL} complaints behind this page (consumers and app)", key="bp_read")


JOURNEY_COLORS = {k: palette.LENS_COLORS[k] for k in ("Consumer, brand-named", "Consumer, no brand", "App", "Retail reviews")}


def _journey_section(d: pd.DataFrame) -> None:
    """Journey: at each stage of the consumer journey, where is the friction? Every complaint item from consumer comments, the app
    and store reviews on one axis, stacked by source type (counts: the sources are never pooled into a rate). A second grid says what
    the friction at each stage is about. The stage is where the problem happens, read by the model from the text and the source."""
    fr = vd.friction(d)
    if fr.empty or not len(vd.stage_table()):
        ui.section("Where in the journey the friction happens", "The stage table has not been built.", "Journey", kind="fact")
        st.info("Not run yet: python tag_journey_stage.py --mode full --confirm (from the Scripts folder).")
        return
    scopes = ["All sources", f"{FOCAL} only", f"{FOCAL} consumers only"]
    scope = st.segmented_control("Show", scopes, default=scopes[0], key="bp_jscope") or scopes[0]
    own = (fr["lens"] == "Consumer, brand-named") & (fr["brand_std"] == FOCAL)   # Acuvue's own words: consumers who name Acuvue; store reviews and category comments are not about the brand
    if scope == scopes[1]:
        fr = fr[own | (fr["lens"] == "App")]
    elif scope == scopes[2]:   # no channel decides the stage here: the peak is read from the comment alone
        fr = fr[own]
    cols = vd.STAGE_LIST + [vd.NO_STAGE]
    ct, tot, ok, top = _stage_counts(fr)
    n_all, n_staged = int(tot.sum()), int(tot[vd.STAGE_LIST].sum())
    top_lens = ct.loc[top].idxmax() if top else None
    who = {scopes[0]: "Complaints across all sources", scopes[1]: f"{FOCAL} complaints (consumers and app)", scopes[2]: f"{FOCAL} consumers' complaints"}[scope]
    app_at_top = int(ct.loc[top, "App"]) if top else 0
    title = (f"Repeat wearers speak up most: {int(ok[top])} of {n_staged} staged {who.lower()}" if top == "Repeat/Retention" and scope == scopes[2] else
             f"{who} peak at {top} ({int(ok[top])} of {n_staged} that name a stage)"
             + (f", but {app_at_top} of them are the app, which is placed at Trial by design" if top == "Trial" and app_at_top else "") if top
             else "Too few complaints at any one stage to name a peak")
    ui.section(title, "Where the problem happens, read from each complaint. The app is placed at Trial and Repeat by what it is (sign-in and registration at Trial), so a Trial peak is partly the app; "
               f"switch to \"{scopes[2]}\" to read the stage from the comment alone.",
               "Journey", kind="fact")

    thin = [bool(0 < tot[c] < ebi.MIN_N) for c in cols]
    fig = go.Figure()
    for lens in [x for x in vd.FRICTION_LENS if ct[x].sum() > 0]:
        fig.add_bar(x=cols, y=ct[lens].values, name=lens, marker=dict(color=JOURNEY_COLORS[lens], pattern=charts.thin_fill(thin), opacity=[1.0 if (not top or c == top) else 0.4 for c in cols]),
                    text=[(f"{lens} {v}" if v >= 25 else str(v)) if v >= ebi.MIN_COUNT else "" for v in ct[lens].values], textposition="inside", insidetextanchor="middle",
                    textfont=dict(color=palette.TEXT if lens == "Consumer, no brand" else palette.WHITE, size=11),
                    customdata=[[c, lens] for c in cols], hovertemplate="%{x} · " + lens + ": %{y} complaints<extra></extra>")
    for c, t_ in zip(cols, tot[cols].values):   # stack totals, as on the theme chart below
        if t_:
            fig.add_annotation(x=c, y=int(t_), text=f"<b>{int(t_)}</b>", showarrow=False, yanchor="bottom", yshift=3, font=dict(size=12))

    # what the friction at each stage is about
    cells = [(c, g, int(((fr["stage"] == c) & fr["cthemes"].map(lambda ts, g=g: g in ts)).sum())) for g in theme_tags.THEME_LIST for c in cols]
    top_cell = max((x for x in cells if x[0] != vd.NO_STAGE), key=lambda x: x[2])
    fg = go.Figure()
    for k_, g in enumerate(theme_tags.THEME_LIST):
        ks2 = [x[2] for c in cols for x in cells if x[0] == c and x[1] == g]
        fg.add_bar(x=cols, y=[k or None for k in ks2], name=g, marker_color=palette.THEME_COLORS.get(g, palette.OTHER_THEME),
                   marker_pattern_shape=["/" if 0 < k < ebi.MIN_COUNT else "" for k in ks2],
                   text=[str(k) if k >= ebi.MIN_COUNT else "" for k in ks2], textposition="inside", insidetextanchor="middle", textfont=dict(color=palette.WHITE, size=11),
                   customdata=[[c, g] for c in cols], hovertemplate="%{x} · " + g + ": %{y} complaints<extra></extra>")
    for c in cols:
        t_ = sum(x[2] for x in cells if x[0] == c)
        if t_:
            fg.add_annotation(x=c, y=t_, text=f"<b>{t_}</b>", showarrow=False, yanchor="bottom", yshift=3, font=dict(size=12))
    stage_tot = [sum(x[2] for x in cells if x[0] == c) for c in cols]
    # the two charts are read one under the other: same stage columns, height, margins and y-axis max, so a stage lines up and a bar's height means the same
    ymax = max(max(stage_tot), int(tot[cols].max())) * 1.12
    # legend above the plot: a legend below the axis is pushed down by ui._patch_plotly_chart in proportion to the plot height, which left a blank band
    for f_ in (fig, fg):
        f_.update_xaxes(categoryorder="array", categoryarray=cols, title=None)
        f_.update_yaxes(title="Complaint items", range=[0, ymax], automargin=True)
        f_.update_layout(barmode="stack", height=420, uniformtext=dict(minsize=11, mode="hide"), margin=dict(t=70, l=70, r=20),
                         legend=dict(orientation="h", y=1.0, yanchor="bottom", x=0, xanchor="left", title_text=""))
    fig.update_layout(showlegend=True)
    ev = ui.plot(fig, ("Repeat is the moment for a lens-care and reorder message." if top == "Repeat/Retention" and scope == scopes[2] else ""),
                 "dir", key="bp_journey", select=True,
                 note=f"The peak stage is drawn solid, the others lighter. Counts, not rates: the sources differ in size and tone, so they are stacked, never pooled. Hatched = under {ebi.MIN_N} complaints at that stage. "
                      f"{int(tot[vd.NO_STAGE])} of {n_all} complaints name no stage. Click a bar for the items.",
                 bases={k: int(v) for k, v in ct.sum().items() if v}, noun="complaint items")
    grid_say = (f"At {top_cell[0]}, {top_cell[1]} is the biggest source of friction ({top_cell[2]} complaints)." if top_cell[2] >= ebi.MIN_COUNT
                else "Friction by stage and theme.")
    ev2 = ui.plot(fg, grid_say, key="bp_journey_grid", select=True,
                  note="Counts: complaint items on each theme at that stage; an item can carry two themes, so a stack can exceed the items at that stage. "
                       "Hatched = under 10, read as direction only. Click a segment for the items.",
                  bases={"Complaint items": n_all}, noun="items")

    pk, pk2 = ui.picked(ev), ui.picked(ev2)
    if pk:
        stg, lens = pk[0]
        ui.items_panel(vd.view(fr[(fr["stage"] == stg) & (fr["lens"] == lens)]), f"{stg}: {lens.lower()} complaints")
    elif pk2:
        stg, grp = pk2[0]
        ui.items_panel(vd.view(fr[(fr["stage"] == stg) & fr["cthemes"].map(lambda ts: grp in ts)]), f"{stg}: {grp} complaints")
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
    fig = go.Figure(go.Heatmap(z=z, x=JOURNEY_STAGES, y=chans, text=txt, texttemplate="%{text}", colorscale=palette.SEQ_SCALE,
                               zmin=0, zmax=300, xgap=3, ygap=3, showscale=False, hoverongaps=False,
                               hovertemplate="%{y} · %{x}: %{text} tagged items<extra></extra>", textfont=dict(size=11, color=palette.TEXT)))
    fig.update_xaxes(side="top", tickangle=0, title=None)
    fig.update_yaxes(autorange="reversed", title=None)
    fig.update_layout(height=110 + 34 * len(chans), plot_bgcolor=palette.GRID, margin=dict(t=50, l=10, r=10, b=10))
    return fig
