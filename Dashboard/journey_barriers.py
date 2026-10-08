"""
Journey & barriers story page: what stops people buying, where in the journey it happens, and which
parts ACUVUE can fix directly. Replaces the old Barriers > Journey sub-tab and absorbs the barrier
view from Brand Health; the detailed app and retailer read-out stays available under
"dig deeper".

Like-for-like rule: MyACUVUE app reviews exist only for ACUVUE and are all tagged to the Trial and
Retention stages, so counting them in stage rates would make those stages look like ACUVUE-only
problems. Stage and bubble views therefore exclude the app by default; the app has its own section.
Xiaohongshu has no barrier flag, so it contributes to sentiment and touchpoints but not to barrier rates.
"""

import html

import pandas as pd
import plotly.graph_objects as go
import streamlit as st

import barrier_taxonomy
import theme_tags
import barriers_friction
import charts
import ebi
import gmaps_signals
import insights
import ui
import whatsapp_map
from sg_common import JOURNEY_STAGES

NO_FLAG_SOURCES = {"Xiaohongshu"}


def _stage_order(jf: pd.DataFrame) -> list:
    present = set(jf["journey_stage"].dropna())
    return [s for s in JOURNEY_STAGES if s in present] + sorted(s for s in present if s not in JOURNEY_STAGES)


def _stage_table(view: pd.DataFrame, app_items: pd.DataFrame, stages: list) -> pd.DataFrame:
    """One row per stage: evidence volume, channels, barrier rate, share negative, top barrier type, app reviews."""
    rows = []
    flaggable = view[~view["source"].isin(NO_FLAG_SOURCES)]
    for st_ in stages:
        v = view[view["journey_stage"] == st_]
        f = flaggable[flaggable["journey_stage"] == st_]
        k, n = int(f["is_barrier"].sum()), len(f)
        flagged = f[f["is_barrier"] == 1].drop_duplicates(["source", "brand", "text"])
        top_type = ""
        if not flagged.empty:
            vc = flagged["text"].map(barrier_taxonomy.themes_of).explode().value_counts()
            top_type = vc.index[0] if len(vc) else ""
        lab = v[v["sentiment"].isin(charts.SENTIMENT_ORDER)]
        neg = ebi.share(int((lab["sentiment"] == "negative").sum()), len(lab)) if len(lab) else "no labelled items"
        chans = v["source"].value_counts().head(3)
        a = app_items[app_items["journey_stage"] == st_]
        rows.append({
            "Stage": st_,
            "Items": len(v),
            "Main channels": " · ".join(f"{s} {int(c)}" for s, c in chans.items()),
            "Barrier rate": ebi.share(k, n) if n else "no flagged sources",
            "Negative": neg,
            "Top theme": top_type or "n/a",
            "App reviews (1-2★)": int(a["is_barrier"].sum()) if not a.empty else 0,
        })
    return pd.DataFrame(rows)


def _peak_stage(view: pd.DataFrame, stages: list):
    """Stage with the highest barrier rate among stages with at least MIN_N flaggable items."""
    flaggable = view[~view["source"].isin(NO_FLAG_SOURCES)]
    best = None
    for st_ in stages:
        f = flaggable[flaggable["journey_stage"] == st_]
        if len(f) < ebi.MIN_N:
            continue
        rate = f["is_barrier"].mean() * 100
        if best is None or rate > best[1]:
            best = (st_, rate, int(f["is_barrier"].sum()), len(f))
    return best


def _bubbles(ex: pd.DataFrame, brands: list, rows: list, n_brand: pd.Series, focus: str, brands_as_rows: bool = True) -> go.Figure:
    """Barrier type x brand bubble map. One rule for size: bubble area = share of that brand's flagged comments,
    and the number inside is the count. Brands under ebi.MIN_N flags cannot carry a share, so they are drawn as
    equal-size hollow circles with the count only, and their label says "directional only". The focus brand's row or column is shaded, and barrier types are
    sorted by the focus brand. brands_as_rows=True lays brands down the side with barrier types along the bottom
    (the Hong Kong layout); False puts barrier types down the side."""
    counts = ex.groupby(["reason", "brand"]).size().reset_index(name="k")
    counts["share"] = counts["k"] / counts["brand"].map(n_brand) * 100
    thin = {b for b in brands if n_brand[b] < ebi.MIN_N}
    lbl = {b: charts.row_label(b, int(n_brand[b])) for b in brands}
    fig = go.Figure()
    if focus in brands:
        i = brands.index(focus)
        shade = dict(fillcolor="rgba(23,129,151,0.07)", line_width=0, layer="below")
        if not brands_as_rows:
            fig.add_vrect(x0=i - 0.5, x1=i + 0.5, **shade)
    for b in brands:
        sub = counts[counts["brand"] == b]
        col = charts.BRAND_COLORS.get(b, "#999999")
        if b in thin:
            marker = dict(size=26, color="rgba(255,255,255,0)", line=dict(width=2, color=col))
            tcol = "#334155"
        else:
            marker = dict(size=sub["share"], sizemode="area", sizeref=0.025 if brands_as_rows else 0.035, sizemin=15,
                          color=col, opacity=0.85, line=dict(width=0))
            tcol = "white"
        bl = [lbl[b]] * len(sub)
        x, y = (sub["reason"], bl) if brands_as_rows else (bl, sub["reason"])
        fig.add_trace(go.Scatter(
            x=x, y=y, mode="markers+text", text=sub["k"], textposition="middle center",
            textfont=dict(color=tcol, size=12), marker=marker, name=b, showlegend=False, customdata=sub[["k", "share"]],
            hovertemplate=(f"{b}<br>%{{{'x' if brands_as_rows else 'y'}}}<br>%{{customdata[0]}} flagged comments"
                           + ("" if b in thin else " (%{customdata[1]:.0f}% of brand)") + "<extra></extra>"),
        ))
    grid = dict(showgrid=True, gridcolor="rgba(128,128,128,0.15)", automargin=True, tickfont=dict(size=12))
    if brands_as_rows:
        fig.update_xaxes(categoryorder="array", categoryarray=rows, tickangle=-35, title=None, **grid)
        fig.update_yaxes(categoryorder="array", categoryarray=[lbl[b] for b in brands][::-1], title=None, **grid)
        fig.update_layout(height=max(360, 92 * len(brands) + 170))
        if focus in brands:   # shade the focus brand's row using paper-relative bands via a shape on the category axis
            j = len(brands) - 1 - brands.index(focus)
            fig.add_shape(type="rect", xref="paper", yref="y", x0=0, x1=1, y0=j - 0.5, y1=j + 0.5,
                          fillcolor="rgba(23,129,151,0.07)", line_width=0, layer="below")
    else:
        fig.update_xaxes(categoryorder="array", categoryarray=[lbl[b] for b in brands], side="top", title=None, **grid)
        fig.update_yaxes(categoryorder="array", categoryarray=rows[::-1], title=None, **grid)
        fig.update_layout(height=max(340, 50 * len(rows) + 120))
    return fig


def flagged_comments(src: pd.DataFrame, brands: list) -> pd.DataFrame:
    """The comments that give a reason not to buy: barrier-flagged, on a channel that carries a flag, one row per distinct text."""
    return src[src["brand"].isin(brands) & (src["is_barrier"] == 1) & ~src["source"].isin(NO_FLAG_SOURCES)].drop_duplicates(["source", "brand", "text"])


def _barrier_map(src: pd.DataFrame, brands: list, focus: str) -> None:
    """What stops people buying: Acuvue-vs-peers gap bars on top, full brand x barrier-type bubble map below."""
    b = flagged_comments(src, brands)
    if b.empty:
        st.info("No flagged comments for the current selection.")
        return
    srcs = sorted(b["source"].unique())
    pick = st.multiselect("Sources in the barrier view", srcs, default=srcs, key="jb_src_map")
    d = b[b["source"].isin(pick)].copy()
    if d.empty:
        st.info("No flagged comments for the selected sources.")
        return
    d["reason"] = d["text"].map(barrier_taxonomy.classify)          # barrier label: the detail in the bubble map
    ex = d.explode("reason")
    ex_t = d.assign(reason=d["text"].map(barrier_taxonomy.themes_of)).explode("reason")   # theme: the headline in the gap bars
    n_brand = d.groupby("brand").size().reindex(brands, fill_value=0)

    # 1) the story: focus brand vs peers
    peers = [x for x in brands if x != focus]
    why = insights.reasons(ex_t, focus, peers) if focus in brands else pd.DataFrame()
    if not why.empty and why["brand_k"].sum() > 0:
        nf, npeer = why.attrs["n_focus"], why.attrs["n_peers"]
        view = why.head(8).copy()
        view[["brand_share", "peer_share"]] = view[["brand_share", "peer_share"]].fillna(0)
        if nf >= ebi.MIN_N and npeer >= ebi.MIN_N:
            view = view.assign(p=[insights.two_prop_p(int(r.brand_k), nf, int(r.peer_k), npeer) for r in view.itertuples()],
                               total=view["brand_k"] + view["peer_k"])
            solid = view[view["total"] >= ebi.MIN_N]                      # 30+ comments across both sides: a theme can be compared
            named = view["reason"] != barrier_taxonomy.OTHER
            dropped = view[named & (view["total"] < ebi.MIN_COUNT)]       # under 10: not drawn, counted in the note
            thin_t = view[named & (view["total"] >= ebi.MIN_COUNT) & (view["total"] < ebi.MIN_N)]   # 10 to 29: drawn, never compared
            real = solid[solid["p"] < 0.05].sort_values("p")
            if not real.empty:
                r = real.iloc[0]
                lead = (f"“{r['reason']}” sets {focus} apart: {r['brand_share']:.0f}% of its flags vs {r['peer_share']:.0f}% for peers." if r["gap"] > 0
                        else f"{focus} is flagged less than peers on “{r['reason']}”: {r['brand_share']:.0f}% vs {r['peer_share']:.0f}% of flags.")
            else:
                top = solid.dropna(subset=["gap"]).reindex(solid["gap"].abs().sort_values(ascending=False).index).dropna(subset=["gap"])
                lead = (f"No theme with {ebi.MIN_N}+ comments sets {focus} apart from peers (largest gap: {top.iloc[0]['reason'].lower()}, "
                        f"{top.iloc[0]['brand_share']:.0f}% vs {top.iloc[0]['peer_share']:.0f}%)." if not top.empty else f"No theme has {ebi.MIN_N}+ comments to compare {focus} with peers.")
            drawn = view[view["total"] >= ebi.MIN_COUNT]
            if drawn.empty:
                ui.takeaway(lead, "fact")
                ui.n_strip({focus: nf, "Peers": npeer}, noun="flagged comments")
            else:
                ui.plot(charts.gap_bars(drawn, focus, n_brand=nf, n_peers=npeer), lead,
                        note="Themes; an item can carry several.", bases={focus: nf, "Peers": npeer}, noun="flagged comments")
            if not thin_t.empty:
                names = ", ".join(f"{r.reason} ({int(r.total)})" for r in thin_t.itertuples())
                ui.takeaway(f"Drawn but not compared ({ebi.MIN_COUNT} to {ebi.MIN_N - 1} comments across {focus} and peers, directional only): {html.escape(names)}.", "dir")
            if not dropped.empty:
                st.caption(f"Not drawn (under {ebi.MIN_COUNT} comments): " + ", ".join(f"{r.reason} ({int(r.total)})" for r in dropped.itertuples()) + ".")
            if not thin_t.empty:
                lone = thin_t[thin_t["p"] < 0.05]
                if not lone.empty:
                    r = lone.iloc[0]
                    st.caption(f"“{r['reason']}” looks {'higher' if r['gap'] > 0 else 'lower'} for {focus} ({r['brand_share']:.0f}% vs {r['peer_share']:.0f}%) "
                               f"but rests on {int(r['total'])} comments, so treat it as a pointer.")
        else:
            st.dataframe(view[["reason", "brand_text", "peer_text"]].rename(columns={
                "reason": "Theme", "brand_text": f"{focus} (count of {nf})", "peer_text": f"Peers (count of {npeer})"}),
                hide_index=True, width="stretch")
            ui.n_strip({focus: nf, "Peers": npeer}, noun="flagged comments")
            st.caption(f"Under {ebi.MIN_N} items: counts only.")

    # 2) the full comparison (the bubble map)
    present = set(ex["reason"])
    order = [t for t in list(barrier_taxonomy.TYPES) if t in present]
    focus_for_sort = focus if focus in brands else brands[0]
    themes = list(theme_tags.THEMES)
    order.sort(key=lambda t: (themes.index(barrier_taxonomy.THEME_OF[t]), -int(((ex["reason"] == t) & (ex["brand"] == focus_for_sort)).sum())))
    if barrier_taxonomy.OTHER in present:
        order.append(barrier_taxonomy.OTHER)
    top = ex[(ex["brand"] == focus_for_sort) & (ex["reason"] != barrier_taxonomy.OTHER)]["reason"].value_counts()
    say = (f"“{top.index[0]}” is {focus_for_sort}'s biggest barrier ({int(top.iloc[0])} comments)."
           if len(top) else "Barriers by brand.")
    layout = st.segmented_control("Layout", ["Brands as rows", "Barriers as rows"], default="Brands as rows", key="jb_layout") or "Brands as rows"
    ui.plot(_bubbles(ex, brands, order, n_brand, focus_for_sort, brands_as_rows=(layout == "Brands as rows")), say, key="jb_map",
            note=f"Barrier labels grouped by theme. Bubble = share of the brand's flags; number = comments. Hollow = under {ebi.MIN_N} flags (counts only).",
            bases={b: int(n_brand[b]) for b in brands}, noun="flagged comments")

    st.caption("Counts are flagged comments only. The app (toggle above) and Xiaohongshu are left out by default, "
               "so they are lower than an all-source total such as the one on Summary.")


def render(selected_brands: list, jf_all: pd.DataFrame, frames: dict | None = None) -> None:
    brands = charts.order_brands(selected_brands)
    if not brands or jf_all is None or jf_all.empty:
        st.info("No journey data for the current brand filter.")
        return

    theme_tags.queue(jf_all)
    options = ["All brands"] + brands
    default = insights.FOCAL if insights.FOCAL in brands else "All brands"
    if st.session_state.get("jb_view") not in options:
        st.session_state.pop("jb_view", None)
    pick = st.segmented_control("View", options, default=default, key="jb_view") or default
    scope = brands if pick == "All brands" else [pick]
    label = "the selected brands" if pick == "All brands" else pick

    jf = jf_all[jf_all["brand"].isin(scope)]
    app_items = jf[jf["source"] == insights.APP_SOURCE]
    view = jf[jf["source"] != insights.APP_SOURCE]          # like-for-like: app reviews shown separately
    stages = _stage_order(jf)

    # ---- Story ---------------------------------------------------------------------------------
    peak = _peak_stage(view, stages)
    flagged = view[(view["is_barrier"] == 1) & ~view["source"].isin(NO_FLAG_SOURCES)].drop_duplicates(["source", "brand", "text"])
    top_type, top_k, top_src = None, 0, ""
    if not flagged.empty:
        ft = flagged.assign(reason=flagged["text"].map(barrier_taxonomy.themes_of)).explode("reason")
        named = ft[ft["reason"] != barrier_taxonomy.OTHER]
        vc = (named if not named.empty else ft)["reason"].value_counts()
        top_type, top_k = vc.index[0], int(vc.iloc[0])
        top_src = ft[ft["reason"] == top_type]["source"].value_counts().index[0]

    app = insights.app_story(jf_all) if (pick in ("All brands", insights.FOCAL) and insights.FOCAL in scope) else {}
    implication = insights.IMPLICATIONS.get(top_type, "") if top_type else ""
    if peak and top_type:
        answer = f"{html.escape(top_type)} is the main barrier to purchase, concentrated at {peak[0]}."
    elif top_type:
        answer = f"{html.escape(top_type)} is the main barrier to purchase."
    elif peak:
        answer = f"Barriers concentrate at {peak[0]}."
    else:
        answer = "Too few flagged items to name a barrier or a stage."
    args = []
    if top_type:
        args.append({"label": "Barrier", "value": f"{top_k} of {len(flagged)}",
                     "text": f"{html.escape(top_type)} is the main barrier, mostly from {html.escape(top_src)}.", "tone": "watch"})
    if peak:
        args.append({"label": "Stage", "value": f"{peak[1]:.0f}%",
                     "text": f"Barriers concentrate at {peak[0]}: {peak[2]} of {peak[3]} items give a reason not to buy. {html.escape(label)}, app excluded.", "tone": "bad"})
    else:
        args.append({"label": "Stage", "value": "Too few",
                     "text": f"No stage has {ebi.MIN_N}+ items to rate for {html.escape(label)}; counts are in the table below.", "tone": "flat"})
    if app:
        args.append({"label": "Owned experience", "value": f"{app['negative']} of {app['n']}",
                     "text": "The app is a separate drag: MyACUVUE app reviews are negative, all at Trial and Retention.", "tone": "bad"})
    if peak and implication:
        implication = f"Focus on {peak[0]}. " + implication
    ui.pyramid(answer, args, html.escape(implication))

    # ---- What stops people buying: bubble ----------------------------------------------------------
    ui.section(f"{top_type} is the main barrier" if top_type else "What stops people buying",
               "What stops a purchase: only comments that give a reason not to buy, so shares differ from the all-complaints view on Brand Health.",
               "1 · Barrier", kind="fact")
    with_app = st.toggle("Include MyACUVUE app reviews (ACUVUE only, not like-for-like)", value=False, key="jb_with_app")
    bubble_src = jf_all if with_app else jf_all[jf_all["source"] != insights.APP_SOURCE]
    _barrier_map(bubble_src, brands, pick if pick != "All brands" else (insights.FOCAL if insights.FOCAL in brands else brands[0]))

    # ---- Where in the journey --------------------------------------------------------------------------
    ui.section(f"Barriers concentrate at {peak[0]}" if peak else "Where in the journey it happens", "An item counts in every stage it is tagged, so totals overlap.",
               "2 · Stage", kind="fact")
    tbl = _stage_table(view, app_items, stages)
    st.dataframe(tbl, hide_index=True, width="stretch")
    st.caption(f"Rates need {ebi.MIN_N}+ items. Flags: model-scored on social; negative price, comfort, fake or stock text on Lazada and KiasuParents; none on Xiaohongshu. "
               "App reviews appear in the last column only.")
    app_stage = app_items.groupby("journey_stage").size() if not app_items.empty else pd.Series(dtype=int)
    app_heavy = [s_ for s_ in stages if int(app_stage.get(s_, 0)) > len(view[view["journey_stage"] == s_])]
    if app_heavy:
        st.caption(f"{' and '.join(app_heavy)}: more app reviews than other items, and the app is kept out of the stage rates to stay "
                   "like-for-like (last column and section 3). These stages look quiet here because most of their evidence is the app.")

    lab = view[view["sentiment"].isin(charts.SENTIMENT_ORDER)].drop_duplicates(["source", "brand", "text", "journey_stage"])
    # A stage whose only evidence is the app (Trial) still gets a bar, labelled app-only, so the brand-health
    # view has no hole. Stages that other channels cover stay like-for-like (app left out).
    app_lab = app_items[app_items["sentiment"].isin(charts.SENTIMENT_ORDER)].drop_duplicates(["source", "brand", "text", "journey_stage"])
    app_only = [s_ for s_ in stages if not (view["journey_stage"] == s_).any() and (app_lab["journey_stage"] == s_).any()]
    rename = {s_: f"{s_} (app only)" for s_ in app_only}
    chart_df = pd.concat([lab, app_lab[app_lab["journey_stage"].isin(app_only)]]).assign(
        journey_stage=lambda d: d["journey_stage"].replace(rename))
    # Stages tagged to exactly the same items (Lazada reviews carry Purchase and Repeat/Retention together) would draw
    # two identical bars, so they share one row.
    items_by_stage = {g: frozenset(zip(d["source"], d["brand"], d["text"])) for g, d in chart_df.groupby("journey_stage")}
    merged: dict = {}
    for g in [rename.get(s_, s_) for s_ in stages]:
        merged.setdefault(items_by_stage.get(g, g), []).append(g)
    label_of = {g: " + ".join(gs) for gs in merged.values() for g in gs}
    shared = [gs for gs in merged.values() if len(gs) > 1]
    chart_df = chart_df.assign(journey_stage=chart_df["journey_stage"].map(label_of))
    groups = list(dict.fromkeys(label_of[rename.get(s_, s_)] for s_ in stages))
    fig = charts.sentiment_mix(chart_df.drop_duplicates(["source", "brand", "text", "journey_stage"]), "journey_stage", groups)
    neg = (lab[lab["sentiment"] == "negative"].groupby("journey_stage").size()
           / lab.groupby("journey_stage").size()).dropna() * 100
    big = chart_df.drop_duplicates(["source", "brand", "text", "journey_stage"]).groupby("journey_stage").size()
    neg = neg[lab.groupby("journey_stage").size().reindex(neg.index) >= ebi.MIN_N]
    ui.plot(fig, f"{neg.idxmax()} is the most negative stage ({neg.max():.0f}% negative)." if len(neg) else "Sentiment by journey stage.",
            note="Hatched = under 30 items." + (f" {' and '.join(app_only)}: MyACUVUE app reviews only (ACUVUE, not like-for-like); "
                                                  "see section 3 below for the app detail." if app_only else "")
                 + "".join(f" {' and '.join(gs)} are tagged to the same reviews, so they share one row." for gs in shared),
            bases={g: int(big.get(g, 0)) for g in groups}, noun="labelled items")
    n_staged = len(lab.drop_duplicates(["source", "brand", "text"]))
    if frames:
        n_pool = len(insights.pool(frames, scope))
        st.caption(f"Sentiment only: {n_staged:,} of {n_pool:,} pooled items carry a journey-stage tag; "
                   f"the other {max(n_pool - n_staged, 0):,} stay in Brand Health but cannot be placed on a stage.")
    else:
        st.caption(f"Sentiment only: {n_staged:,} labelled items carry a journey-stage tag.")
    single = [f"{s_} ({view.loc[view['journey_stage'] == s_, 'source'].iloc[0]}, {view.loc[view['journey_stage'] == s_].drop_duplicates(['source', 'brand', 'text']).shape[0]} items)"
              for s_ in stages if view.loc[view["journey_stage"] == s_, "source"].nunique() == 1]
    if single:
        st.caption("Stages tagged to one public channel only: " + "; ".join(single) + ". Read these as that channel's view, not the market's.")

    # ---- Owned experience: app + retailer ---------------------------------------------------------------
    ui.section(f"The app is a separate drag: {app['negative']} of {app['n']} reviews are negative" if app else "What ACUVUE can fix directly",
               "App and retail experience, kept apart from peers.",
               "3 · Owned experience", kind="fact")
    c1, c2 = st.columns(2)
    with c1:
        ui.takeaway("MyACUVUE app reviews", "fact")
        a_all = insights.app_story(jf_all)
        if not a_all:
            st.info("No app reviews loaded.")
        else:
            m = st.columns(2)
            m[0].metric("Negative app reviews", f"{a_all['negative']} of {a_all['n']}")
            top = ", ".join(f"{k} ({v})" for k, v in a_all["top_reasons"].items())
            m[1].metric("Top theme", next(iter(a_all["top_reasons"]), "n/a"))
            st.caption(f"Top: {top}. Stages: Trial (sign-up, login), Retention (points, marketing). "
                       "Repeated texts count once here; the app detail below counts every written review, so its total is a little higher.")
    with c2:
        ui.takeaway("Retailer reviews (Google Maps)", "fact")
        gm, _ = gmaps_signals.load_gmaps()
        if gm.empty:
            st.info("No Google Maps data.")
        else:
            fr = gm[gm["is_friction"] == 1]
            m = st.columns(2)
            m[0].metric("Reviews describing friction", ebi.share(len(fr), len(gm)).split(" (")[0])
            themes = {lbl: int(fr["theme_list"].map(lambda x, k=key: k in x).sum()) for key, lbl in gmaps_signals.THEME_LABELS.items()}
            tt = sorted(themes.items(), key=lambda kv: -kv[1])[:3]
            m[1].metric("Top theme", tt[0][0] if tt else "n/a")
            st.caption("Top: " + ", ".join(f"{k} ({v})" for k, v in tt) + ". Reviews cover retailers and skew positive.")

    # ---- WhatsApp message map ------------------------------------------------------------------------------
    whatsapp_map.render(jf_all, brands)

    # ---- Dig deeper ---------------------------------------------------------------------------------------
    if frames:
        with st.expander("How these items reconcile with Brand Health", expanded=False):
            tagged = jf[~jf["source"].isin([insights.APP_SOURCE])].drop_duplicates(["source", "brand", "text"])
            rows = []
            for s in charts.SOURCE_ORDER:
                a = frames.get(s, {}).get("analysed")
                n_an = int(a["brand"].isin(scope).sum()) if a is not None and not a.empty else 0
                n_j = int((tagged["source"] == s).sum())
                rows.append({"Channel": s, "Analysed (Brand Health)": n_an if n_an else charts.NO_DATA,
                             "Placed on the journey": n_j if n_j else ("None: no stage tags" if n_an else charts.NO_DATA),
                             "Not placed": max(n_an - n_j, 0) or "None"})
            n_app = int((jf["source"] == insights.APP_SOURCE).sum())
            if n_app:
                rows.append({"Channel": insights.APP_SOURCE, "Analysed (Brand Health)": "Not in the pool (ACUVUE only)", "Placed on the journey": n_app, "Not placed": "n/a"})
            st.dataframe(pd.DataFrame(rows).astype(str), hide_index=True, width="stretch")
            st.caption("Items without a stage tag stay in Brand Health but cannot be placed here; identical texts count once.")

    with st.expander("Flagged comments (read the evidence)", expanded=False):
        c1, c2 = st.columns(2)
        stage_pick = c1.multiselect("Stages", stages, default=stages, key="jb_stage_pick")
        srcs = sorted(view["source"].unique())
        src_pick = c2.multiselect("Sources", srcs, default=srcs, key="jb_src_pick")
        fl = view[(view["is_barrier"] == 1) & view["journey_stage"].isin(stage_pick) & view["source"].isin(src_pick)] \
            .drop_duplicates(["source", "text"])
        if fl.empty:
            st.caption("None flagged in this selection.")
        else:
            st.dataframe(
                fl[["source", "brand", "journey_stage", "sentiment", "text", "url"]].rename(columns={
                    "source": "Source", "brand": "Brand", "journey_stage": "Stage", "sentiment": "Sentiment", "text": "Comment", "url": "Link"}),
                width="stretch", hide_index=True, height=360,
                column_config={"Link": st.column_config.LinkColumn("Link", display_text="Open ↗")},
            )

    with st.expander("Full app and retailer detail", expanded=False):
        barriers_friction.render(jf_all)
