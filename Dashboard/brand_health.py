"""
Brand Health: one roll-up of every consumer data point that can be compared. A data point goes in the pool only when it
(1) is attributed to one of the five brands, (2) was judged relevant (on-topic, on-brand, Singapore where the scraper can tell)
and (3) carries the same four-point sentiment label (Positive, Neutral, Mixed, Negative). That covers Lazada reviews,
KiasuParents, Xiaohongshu posts and comments, and Reddit, YouTube, Instagram and Facebook comments. Everything else stays
outside the pool and the page says why (insights.EXCLUDED): brand-owned posts, MyACUVUE app reviews, Google Maps retailer
reviews, listings and Google Trends.

Pooled figures count every data point once, so a big channel weighs more; the channel-balanced score (sqrt(n) weights) is
shown next to it as a check. Intervals are 95% Wilson intervals, and the focus-vs-peers gap is tested before the page says
there is one. All numbers come from insights.py and all charts from charts.py.

Order on the page: story -> pooled scorecard -> what is in and out of the pool -> where the data points sit ->
why feedback is negative -> owned experience -> coverage -> dig deeper.
"""

import html

import pandas as pd
import streamlit as st

import charts
import ebi
import brand_themes
import insights
import ui


def _plot(fig, say: str, note: str = "", kind: str = "fact", bases=None, noun: str = "items") -> None:
    ui.plot(fig, say=say, kind=kind, note=note, bases=bases, noun=noun)


def _prune(key: str, options) -> None:
    cur = st.session_state.get(key)
    if cur is not None and cur not in options:
        del st.session_state[key]


def _coverage_grid(cov: pd.DataFrame, brands: list, channels: list | None = None) -> pd.DataFrame:
    """Brand x source grid of 'analysed of collected', saying why a cell is empty."""
    grid = {}
    for s in channels or charts.SOURCE_ORDER:
        col = {}
        for b in brands:
            r = cov[(cov["brand"] == b) & (cov["source"] == s)].iloc[0]
            if r["collected"] == 0:
                col[b] = charts.NO_DATA
            elif r["status"] == "thin":
                col[b] = charts.thin_label(int(r["scored_n"]), int(r["collected"]))
            else:
                col[b] = f"{int(r['analysed'])} of {int(r['collected'])}"
        grid[s] = col
    return pd.DataFrame(grid).rename_axis("Brand").reset_index()


def _pct(v, n: int) -> str:
    """A percentage, or the count when the base is under ebi.MIN_N."""
    return f"{v:.0f}%" if v is not None and pd.notna(v) else f"n={n}, too few"


def _scorecard(roll: pd.DataFrame, sc: dict) -> pd.DataFrame:
    rows = []
    for r in roll.itertuples():
        n = int(r.n)
        score = sc.get(r.brand, {}).get("score")
        rows.append({
            "Brand": r.brand,
            "Data points": f"{n:,}" if n else charts.NO_DATA,
            "Channels": str(int(r.channels)) if r.channels else "-",
            "Share of voice": _pct(r.sov, n),
            "Positive": _pct(r.pct_positive, n), "Neutral": _pct(r.pct_neutral, n),
            "Mixed": _pct(r.pct_mixed, n), "Negative": _pct(r.pct_negative, n),
            "Net sentiment": (f"{r.net:+.0f} pts" if r.net is not None and pd.notna(r.net) else f"n={n}, too few"),
            "Positive or neutral (95% interval)": (f"{r.pn:.0f}% ({r.lo:.0f}-{r.hi:.0f}%)" if r.pn is not None and pd.notna(r.pn) else f"n={n}, too few"),
            "Channel-balanced score": (f"{score:.0f} ({insights.band(score).lower()})" if score is not None else "Too few to score"),
            "Biggest channel": (f"{r.top_source} {r.top_share:.0f}%" if r.top_source else "-"),
        })
    return pd.DataFrame(rows)


def _channel_gaps(pooled: pd.DataFrame, focus: str, peers: list) -> list:
    """Focus brand vs the other brands pooled, channel by channel, where both sides have at least ebi.MIN_N labelled items.
    Each row: source, f_pn, p_pn (% positive or neutral), gap (pts), dom (the one peer that is 60%+ of the peer items, else None)."""
    out = []
    for c in charts.SOURCE_ORDER:
        d = pooled[pooled["source"] == c]
        f, p = d[d["brand"] == focus], d[d["brand"].isin(peers)]
        if len(f) < ebi.MIN_N or len(p) < ebi.MIN_N:
            continue
        fp = f["sentiment"].isin(["positive", "neutral"]).mean() * 100
        pp = p["sentiment"].isin(["positive", "neutral"]).mean() * 100
        top = p["brand"].value_counts()
        dom = top.index[0] if len(peers) > 1 and top.iloc[0] / len(p) >= 0.6 else None
        out.append({"source": c, "f_pn": fp, "p_pn": pp, "gap": fp - pp, "dom": dom})
    return out


def _pts(v: float) -> str:
    return f"{v:+.0f} pt{'' if round(abs(v)) == 1 else 's'}"


def render(selected_brands: list, reviews_f: pd.DataFrame, xhs: pd.DataFrame, social: dict, jf_all: pd.DataFrame,
           extras: dict | None = None) -> None:
    brands = charts.order_brands(selected_brands)
    if not brands:
        st.info("No brands selected.")
        return

    frames = insights.build_frames(reviews_f, xhs, social)
    cov = insights.coverage(frames, brands)
    sc = insights.scores(cov)
    roll = insights.rollup(frames, brands)

    _prune("bh_focus", brands)
    default = insights.FOCAL if insights.FOCAL in brands else brands[0]
    focus = st.segmented_control("Focus brand", brands, default=default, key="bh_focus") or default
    peers = [b for b in brands if b != focus]
    fe = html.escape(focus)

    neg = insights.negative_items(frames, brands)
    why = insights.reasons(neg, focus, peers) if not neg.empty else pd.DataFrame()
    vp = insights.vs_peers(roll, focus)
    n_foc = why.attrs.get("n_focus", 0) if not why.empty else 0
    n_peer = why.attrs.get("n_peers", 0) if not why.empty else 0
    pooled = insights.pool(frames, brands)
    n_pool = len(pooled)
    n_chan = int(pooled["source"].nunique()) if n_pool else 0
    fr = roll[roll["brand"] == focus].iloc[0]
    named = why[~why["reason"].eq("Other / unclear")] if not why.empty else why
    top = named.iloc[0] if not named.empty else None
    app = insights.app_story(jf_all) if focus == insights.FOCAL else {}
    ch = _channel_gaps(pooled, focus, peers)
    lo_ch = min(ch, key=lambda x: x["gap"]) if ch else None
    hi_ch = max(ch, key=lambda x: x["gap"]) if ch else None

    # ---- The pyramid: answer, then the arguments that support it, then what to do ---------------------
    word = None
    if vp:
        word = "level with" if not vp["distinct"] else ("above" if vp["gap"] > 0 else "below")
    trails = lo_ch is not None and lo_ch["gap"] <= -5
    leads = hi_ch is not None and hi_ch["gap"] >= 5

    if vp:
        if not vp["distinct"]:
            answer = f"{fe}'s sentiment matches its peers ({vp['focus_pn']:.0f}% vs {vp['peer_pn']:.0f}%), so perception alone will not win share."
        elif vp["gap"] > 0:
            answer = f"{fe} out-scores peers on sentiment ({vp['focus_pn']:.0f}% vs {vp['peer_pn']:.0f}%), a lead worth defending."
        else:
            answer = f"{fe} trails peers on sentiment ({vp['focus_pn']:.0f}% vs {vp['peer_pn']:.0f}%), which is a share risk."
        exposure = ([lo_ch["source"]] if trails else []) + ([f"complaints about {top['reason'][0].lower() + top['reason'][1:]}"] if top is not None else [])
        if exposure:
            answer += " The exposure is " + " and ".join(html.escape(x) for x in exposure) + "."
    else:
        answer = f"{fe} has too few items ({int(fr['n'])}) for a verdict on sentiment."

    # each finding = one tile: label (matches its section), the number to read, one short claim, a tone colour
    args = []
    if vp:
        verdict = "at parity" if not vp["distinct"] else ("ahead" if vp["gap"] > 0 else "behind")
        full = {"at parity": "at parity with peers", "ahead": "ahead of peers", "behind": "behind peers"}[verdict]
        args.append({"label": "Position", "value": f"{vp['focus_pn']:.0f}% vs {vp['peer_pn']:.0f}%",
                     "text": f"Sentiment is {full} ({_pts(vp['gap'])}{'' if vp['distinct'] else ', within chance'}).",
                     "tone": "flat" if verdict == "at parity" else ("good" if verdict == "ahead" else "bad")})
    if lo_ch is not None:
        dom = f", peers mostly {html.escape(lo_ch['dom'])}" if lo_ch["dom"] else ""
        if trails:
            extra = f" Leads on {hi_ch['source']} ({hi_ch['f_pn']:.0f}% vs {hi_ch['p_pn']:.0f}%)." if leads else ""
            args.append({"label": "Channels", "value": f"{lo_ch['source']} {_pts(lo_ch['gap']).replace('-', '−')}",
                         "text": f"The gap sits in one channel ({lo_ch['f_pn']:.0f}% vs {lo_ch['p_pn']:.0f}%{dom}).{extra}", "tone": "bad"})
        elif leads:
            args.append({"label": "Channels", "value": f"{hi_ch['source']} {_pts(hi_ch['gap'])}",
                         "text": f"The strength sits in one channel ({hi_ch['f_pn']:.0f}% vs {hi_ch['p_pn']:.0f}%).", "tone": "good"})
        else:
            args.append({"label": "Channels", "value": "Within 5 pts",
                         "text": "Sentiment is consistent across channels with enough items.", "tone": "flat"})
    if top is not None:
        reason = html.escape(top["reason"][0].lower() + top["reason"][1:])
        if n_foc >= ebi.MIN_N and pd.notna(top["gap"]):
            args.append({"label": "Complaints", "value": f"{top['brand_share']:.0f}%",
                         "text": f"Complaints centre on {reason} (peers {top['peer_share']:.0f}%; {n_foc} negative or mixed items).", "tone": "watch"})
        else:
            args.append({"label": "Complaints", "value": f"{int(top['brand_k'])} of {n_foc}",
                         "text": f"Complaints centre on {reason}; too few items for rates.", "tone": "watch"})
    themes_m = brand_themes.matrix(pooled, brands) if n_pool else None
    if themes_m is not None:
        args.append(brand_themes.tile(themes_m, focus, peers))
    top_app = next(iter(app["top_reasons"]), "") if app else ""
    if app:
        issue = f", mostly {html.escape(top_app.lower())}" if top_app and top_app != "Other / unclear" else ""
        args.append({"label": "Owned experience", "value": f"{app['negative']} of {app['n']}",
                     "text": f"The app is a separate drag: reviews are negative{issue}. Kept separate (no competitor app).", "tone": "bad"})

    acts = []
    if top is not None:
        acts.append(insights.IMPLICATIONS.get(top["reason"], ""))
    if app and top_app in insights.IMPLICATIONS and top_app != (top["reason"] if top is not None else ""):
        acts.append(insights.IMPLICATIONS[top_app])
    action = " ".join(a for a in acts if a) or "Collect more items before concluding."
    if vp and not vp["distinct"]:
        action = "Compete on the complaints below, not on sentiment. " + action
    ui.pyramid(answer, args, html.escape(action))

    # ---- 1. Position ---------------------------------------------------------------------------------------
    pos_title = {"at parity": "Sentiment is at parity with peers", "ahead": "Sentiment is ahead of peers", "behind": "Sentiment is behind peers"}
    ui.section(pos_title[("at parity" if not vp["distinct"] else ("ahead" if vp["gap"] > 0 else "behind"))] if vp else f"{focus}: too few items to compare",
               f"All comparable data points pooled: {n_pool:,} items from {n_chan} channels.", "1 · Position", kind="fact")
    left, right = st.columns([3, 2])
    with left:
        ref = vp["peer_pn"] if vp else None
        scored = roll[roll["pn"].notna()]
        lead = "Too few items to compare brands."
        if len(scored):
            hi_b, lo_b = scored.loc[scored["pn"].idxmax()], scored.loc[scored["pn"].idxmin()]
            lead = (f"{hi_b['brand']} leads ({hi_b['pn']:.0f}%), {lo_b['brand']} trails ({lo_b['pn']:.0f}%); "
                    + ("the ranking is not firm (intervals overlap)." if hi_b["lo"] <= lo_b["hi"] else "the gap is real."))
        _plot(charts.ci_dots(roll, ref=ref), lead,
              note="Bar = 95% interval; overlap means the gap could be chance. Axis is zoomed.",
              bases={b: int(roll.loc[roll["brand"] == b, "n"].iloc[0]) for b in brands}, noun="pooled data points")
    with right:
        coll_by_brand = cov.groupby("brand")["collected"].sum().to_dict()
        _plot(charts.sentiment_mix(pooled, "brand", brands, collected=coll_by_brand), "Sentiment mix, all channels pooled.",
              note="Hatched = under 30 items.",
              bases=pooled.groupby("brand").size().reindex(brands, fill_value=0).astype(int).to_dict(), noun="pooled data points")
    compact = _scorecard(roll, sc)[["Brand", "Data points", "Share of voice", "Positive or neutral (95% interval)", "Net sentiment", "Channel-balanced score"]]
    st.dataframe(compact, hide_index=True, width="stretch")
    st.caption("Net sentiment = % positive minus % negative. Where the pooled share and the balanced score disagree, one channel drives the result.")
    st.caption(insights.scope_note(cov))
    rk = insights.verdict(sc, focus)
    if vp and rk.get("spread"):
        st.caption(f"Two reads, one message: the pooled share has {focus} {'level with' if not vp['distinct'] else ('above' if vp['gap'] > 0 else 'below')} its peers "
                   f"({vp['focus_pn']:.0f}% vs {vp['peer_pn']:.0f}%), and the channel-balanced scores run from {rk['spread'][0]:.0f} to {rk['spread'][1]:.0f} "
                   f"with {focus} {'inside' if rk['in_pack'] else 'outside'} that pack. Scores rest on different channels per brand and some on as few as "
                   f"{insights.MIN_SOURCE_N} items, so the order of brands is not quoted.")

    # ---- 2. Channels -----------------------------------------------------------------------------------------
    if trails:
        t2 = f"The gap sits in one channel: {lo_ch['source']}"
    elif leads:
        t2 = f"The strength sits in one channel: {hi_ch['source']}"
    else:
        t2 = "Sentiment is consistent across channels"
    ui.section(t2, "Green = more positive or neutral, red = less (neutral at 70%). No colour = under 30 items, count only.", "2 · Channels", kind="fact")
    fc = cov[(cov["brand"] == focus) & (cov["scored_n"] >= ebi.MIN_N)]
    if len(fc) >= 2:
        lo_c, hi_c = fc.loc[fc["pos_neu"].idxmin()], fc.loc[fc["pos_neu"].idxmax()]
        say = (f"{focus} is weakest on {lo_c['source']} ({lo_c['pos_neu']:.0f}%, n={int(lo_c['scored_n'])}) "
               f"and strongest on {hi_c['source']} ({hi_c['pos_neu']:.0f}%, n={int(hi_c['scored_n'])}).")
    else:
        say = f"{focus} has fewer than two channels with enough items to compare."
    _plot(charts.channel_heat(cov, brands), say,
          note="% positive or neutral, with n beneath.",
          bases={c: int(cov[cov["source"] == c]["scored_n"].sum()) for c in charts.SOURCE_ORDER}, noun="labelled items")

    # ---- 3. Complaints ---------------------------------------------------------------------------------------
    ui.section(f"Complaints centre on {top['reason'][0].lower() + top['reason'][1:]}" if top is not None else f"Why {focus} gets negative feedback",
               "What people dislike: every negative or mixed item, any topic. What stops a purchase is on Journey & barriers, so shares differ. Keyword-matched; one item can carry several reasons.",
               "3 · Complaints", kind="fact")
    if why.empty or why["brand_k"].sum() == 0:
        st.info(f"No negative or mixed items for {focus}.")
    else:
        view = why.head(8).copy()
        view["brand_share"] = view["brand_share"].fillna(0)
        view["peer_share"] = view["peer_share"].fillna(0)
        if n_foc >= ebi.MIN_N and n_peer >= ebi.MIN_N:
            t0 = view.iloc[0]
            _plot(charts.gap_bars(view, focus, n_brand=n_foc, n_peers=n_peer),
                  f"{t0['reason']} leads for {focus} ({t0['brand_share']:.0f}% vs {t0['peer_share']:.0f}% for peers).",
                  note="App reviews excluded.",
                  bases={focus: n_foc, "Peers": n_peer}, noun="negative or mixed items")
        else:
            st.dataframe(view[["reason", "brand_text", "peer_text"]].rename(columns={
                "reason": "Reason", "brand_text": f"{focus} (count of {n_foc})", "peer_text": f"Peers (count of {n_peer})"}),
                hide_index=True, width="stretch")
            ui.n_strip({focus: n_foc, "Peers": n_peer}, noun="negative or mixed items")
            st.caption(f"Under {ebi.MIN_N} items: counts only.")

        for reason in named.head(3)["reason"]:
            with st.expander(f"What people say: {reason}", expanded=False):
                q = insights.quotes(neg, focus, reason)
                if q.empty:
                    st.caption("No readable examples.")
                for r in q.itertuples():
                    link = f" [source]({r.url})" if isinstance(r.url, str) and r.url.startswith("http") else ""
                    st.markdown(f"> {str(r.text).strip()[:400]}\n\n:gray[{r.source}]{link}")
                st.caption(insights.IMPLICATIONS.get(reason, ""))

    # ---- 4. Themes: what each brand is praised and criticised for, one list of themes -------------------------
    if themes_m is not None:
        brand_themes.render(pooled, brands, focus, themes_m)

    # ---- 5. Owned experience: the MyACUVUE app ---------------------------------------------------------------
    if app and app["negative"]:
        ui.section(f"The app is a separate drag: {app['negative']} of {app['n']} reviews are negative",
                   "Outside the pool: no competitor has an app. The full read, with the reviews, is on Journey & barriers.",
                   "5 · Owned experience", kind="fact")
        top_issues = ", ".join(f"{k} ({v_})" for k, v_ in app["top_reasons"].items())
        ui.takeaway(f"Top issues: {html.escape(top_issues)}.", "fact")
        ui.n_strip({"MyACUVUE app": app["n"]}, noun="unique app reviews")

    # ---- Supporting data: everything behind the numbers above, collapsed ------------------------------------
    ui.section("Supporting data", "The pool, coverage and method behind the numbers above.", "Evidence base")

    inv = insights.inventory(frames, brands, extras)
    n_in = int((inv["Status"] == "In the pool").sum())
    n_out = int((inv["Status"] == "Kept apart").sum())
    with st.expander(f"What is in the pool: {n_in} sources pooled ({n_pool:,} data points), {n_out} kept apart", expanded=False):
        st.dataframe(inv.drop(columns=["Status"]), hide_index=True, width="stretch",
                     column_config={"Note": st.column_config.TextColumn(width="large")})
        st.caption("In the pool = brand-tagged, relevant, on the same four-point sentiment scale. "
                   "Lazada reviews use the model's label; the star rating is kept separate.")

    with st.expander("Coverage: analysed of collected, by brand and channel", expanded=False):
        ex = insights.exclusions(cov)
        ex["Removed"] = [f"{int(r.Removed):,} ({r.Removed / r.Collected:.0%})" if r.Collected else charts.NO_DATA for r in ex.itertuples()]
        ex["Collected"] = [f"{int(c):,}" if c else charts.NO_DATA for c in ex["Collected"]]
        st.markdown("**Removed before sentiment is scored, by channel**")
        st.dataframe(ex, hide_index=True, width="stretch")
        st.markdown("**By brand and channel**")
        st.dataframe(_coverage_grid(cov, brands), hide_index=True, width="stretch")
        st.caption("Off-brand, non-Singapore, off-topic and unlabelled items are removed first. "
                   f"“{charts.NO_DATA}” = nothing scraped. “Too few to score” = under {insights.MIN_SOURCE_N} labelled items, so left out of the balanced score.")

    with st.expander("Full scorecard: sentiment mix, net sentiment and interval for every brand", expanded=False):
        st.dataframe(_scorecard(roll, sc), hide_index=True, width="stretch")
        ui.n_strip({b: int(roll.loc[roll["brand"] == b, "n"].iloc[0]) for b in brands}, noun="pooled data points")

    with st.expander("How the numbers are built", expanded=False):
        st.markdown(
            "**Pool.** Each item counts once, after off-brand, non-Singapore, off-topic and unlabelled items are dropped.\n\n"
            "**Pooled share.** Positive or neutral ÷ all labelled items (mixed stays in the base). 95% Wilson interval. "
            "Focus vs peers uses a two-proportion z-test and is called real only at p < 0.05. "
            f"No percentage under {ebi.MIN_N} items.\n\n"
            f"**Balanced score (0-100).** For each channel with {insights.MIN_SOURCE_N}+ items, take the positive-or-neutral share, "
            "then average weighted by √n. Healthy 65+, mixed 45-64, at risk below 45.\n\n"
            "**Channel comparison.** Focus brand vs the other brands pooled on the same channel, shown only where both sides have 30+ items.\n\n"
            "**Limits.** Items are treated as independent, but comments under one post are not, so true uncertainty is wider. "
            "Counts are small and uneven across channels; read as direction."
        )

    with st.expander(f"{focus}: score by channel", expanded=False):
        rows = []
        for s in charts.SOURCE_ORDER:
            r = cov[(cov["brand"] == focus) & (cov["source"] == s)].iloc[0]
            rows.append({"Source": s, "pct": r["pos_neu"] if r["status"] == "ok" else 0,
                         "label": f"{r['pos_neu']:.0f}% (n={int(r['scored_n'])})" if r["status"] == "ok"
                         else charts.thin_label(int(r["scored_n"]), int(r["collected"]))})
        import plotly.express as px
        fig = px.bar(pd.DataFrame(rows), x="pct", y="Source", orientation="h", text="label",
                     category_orders={"Source": charts.SOURCE_ORDER})
        fig.update_traces(marker_color=charts.BRAND_COLORS.get(focus, "#178197"), textposition="outside", cliponaxis=False)
        fig.update_xaxes(range=[0, 130], ticksuffix="%", title="% positive or neutral")
        fig.update_yaxes(autorange="reversed", title="")
        fig.update_layout(height=340)
        per_src = {r["Source"]: int(cov[(cov["brand"] == focus) & (cov["source"] == r["Source"])].iloc[0]["scored_n"]) for r in rows}
        _plot(fig, f"{focus}'s positive-or-neutral share by channel.", note="No bar = too few items.",
              bases=per_src, noun="labelled items")

    with st.expander("Sentiment over time", expanded=False):
        trend = insights.monthly_trend(frames, brands)
        if trend.empty:
            st.info("No dated items for the selected brands.")
        else:
            _plot(charts.trend_lines(trend, brands), "Monthly % positive or neutral, √n-weighted across channels.",
                  note="Dated items only (KiasuParents and Xiaohongshu comments have no usable date). Hollow = under 30 items.",
                  bases=trend.groupby("Brand")["n"].sum().reindex([b for b in brands if b in set(trend["Brand"])]).astype(int).to_dict(),
                  noun="dated items in total")

    with st.expander(f"{focus}: comments flagged as a purchase barrier", expanded=False):
        b = jf_all[(jf_all["brand"] == focus) & (jf_all["is_barrier"] == 1)].drop_duplicates(["source", "text"]) if not jf_all.empty else pd.DataFrame()
        if b.empty:
            st.info(f"No flagged comments for {focus}.")
        else:
            st.dataframe(b[["source", "sentiment", "text"]].rename(columns={"source": "Source", "sentiment": "Sentiment", "text": "Comment"}),
                         hide_index=True, width="stretch", height=300)
