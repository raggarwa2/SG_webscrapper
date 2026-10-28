"""
Trends & Demand, laid out like the HK dashboard's three sub-tabs:
  Demand Signals    one brand's Google Trends search index against the number of items people posted about it, by month,
                    with divergence alerts; then the category search page (trends_signals.render).
  Monthly Trends    how many brand-named items each channel and each brand collected, by month.
  Anomaly Explorer  months whose volume stands out, and the items behind each one.
Volumes are counts of the brand pool (voice_data), so they match every other page. Counts are shown at any size; sentiment is
not computed by month because a single month rarely holds 15 items for a brand.
"""

import os

import pandas as pd
import plotly.express as px
import plotly.graph_objects as go
import streamlit as st

import charts
import ebi
import market_competitors
import segment_views
import trends_signals
import ui
import voice_data as vd
from sg_common import BRAND_COLORS, DB_DIR, TRENDS_DB, read_table

# The Google Trends term that stands for each brand's own name. A term is read only when it has MIN_N active weeks (the same
# floor trends_signals applies); brands whose terms fall under it are listed with the terms tried, not charted.
BRAND_TERM = {"Acuvue": "Acuvue", "Olens": "Olens", "Bausch & Lomb": "Bausch Lomb", "Alcon": "Alcon"}
# Terms whose searches are not only about lenses; the page says so wherever the line is drawn.
TERM_CAVEAT = {"Alcon": "Alcon is searched as a company: the top related queries are Alcon Singapore, Alcon tears and Alcon eye drops as well as Alcon lens, "
                        "so this line is company-level interest, not contact-lens demand."}
TERMS_TRIED = {"Alcon": ["Air Optix", "Dailies Total30"], "CooperVision": ["CooperVision", "Biofinity"]}
ALL_BRANDS = "All brands"
DEMAND_BRANDS = ["Acuvue", "Alcon", "Bausch & Lomb", "CooperVision", "Olens"]
SINGLE_CHANNEL = 0.8   # share of a quarter's items from one channel above which the quarter reads that channel, not the brand


def _pool(d: pd.DataFrame, brands: list) -> pd.DataFrame:
    p = vd.pool(d)
    p = p[p["brand_std"].isin(brands) & p["date"].notna()].copy()
    p["month"] = p["date"].dt.to_period("M").dt.to_timestamp()
    p["channel"] = p["source"].replace({"Xiaohongshu comments": "Xiaohongshu"})
    return p


def _monthly_search(term: str) -> pd.DataFrame:
    t = trends_signals.load()
    t = t[(t["term"] == term) & (t["is_partial"] == 0)].copy()
    if t.empty:
        return t
    t["month"] = t["date"].dt.to_period("M").dt.to_timestamp()
    return t.groupby("month", as_index=False)["value"].mean().rename(columns={"value": "index"})


def _active_weeks(term: str) -> int:
    t = trends_signals.load()
    if t.empty:
        return 0
    t = t[(t["term"] == term) & (t["is_partial"] == 0)]
    return int((t["value"] > 0).sum())


def _range(p: pd.DataFrame) -> pd.DataFrame:
    """Year and month filters, as on the HK page."""
    years = sorted(p["month"].dt.year.unique().tolist())
    with st.popover("Date filters", width="stretch"):
        sel = st.multiselect("Year", years, default=years[-5:], key="tdp_year")
    return p[p["month"].dt.year.isin(sel)] if sel else p


def _all_brands_chart(d: pd.DataFrame, brands: list) -> None:
    """Every brand on one chart: monthly search interest as a share of the 'contact lens' searches in the same request (the only
    scale that is comparable across terms, since Google scales each request to its own peak) against items collected per month."""
    t = trends_signals.load()
    if t.empty:
        return
    rel = trends_signals._relative(t[t["is_partial"] == 0])
    rel["month"] = rel["date"].dt.to_period("M").dt.to_timestamp()
    pool = vd.pool(d)
    pool = pool[pool["brand_std"].isin(brands) & pool["date"].notna()].copy()
    pool["month"] = pool["date"].dt.to_period("M").dt.to_timestamp()
    fig = go.Figure()
    start = None
    recent, drawn = {}, []
    for b in charts.order_brands([x for x in DEMAND_BRANDS if x in brands]):
        term = BRAND_TERM.get(b)
        if not term or _active_weeks(term) < ebi.MIN_N:
            continue
        m = rel[rel["term"] == term].groupby("month", as_index=False)["share"].mean()
        start = m["month"].min() if start is None else min(start, m["month"].min())
        weeks = _active_weeks(term)
        focal = b == vd.FOCAL
        name = f"{b} (company-level)" if b in TERM_CAVEAT else b
        fig.add_scatter(x=m["month"], y=m["share"], name=f"<b>{name}</b>" if focal else name, mode="lines",
                        line=dict(color=BRAND_COLORS.get(b, "#64748B"), width=4 if focal else 2,
                                  dash="dot" if weeks < 2 * ebi.MIN_N else ("dash" if b in TERM_CAVEAT else "solid")),
                        hovertemplate="%{y:.0f}% of 'contact lens' searches<extra>" + name + "</extra>")
        recent[b] = float(m.tail(12)["share"].mean())
        drawn.append(b)
    if not drawn:
        return
    c = pool[pool["month"] >= start].groupby("month").size().rename("items").reset_index()
    fig.add_bar(x=c["month"], y=c["items"], name="Items collected (all brands)", marker_color="#CBD5E1", yaxis="y2")
    fig.data = fig.data[-1:] + fig.data[:-1]   # bars first, so the lines draw on top
    fig.update_layout(height=340, margin=dict(l=10, r=10, t=30, b=10), legend=dict(orientation="h", y=1.1, x=0), hovermode="x unified",
                      yaxis=dict(title="Search interest, % of 'contact lens'", ticksuffix="%", rangemode="tozero"),
                      yaxis2=dict(title="Items per month", overlaying="y", side="right", showgrid=False))
    top = sorted(recent, key=recent.get, reverse=True)
    say = (f"{top[0]} and {top[1]} draw the most search interest of the brands with a readable line; the grey bars are the items collected each month." if len(top) > 1
           else f"{top[0]} is the only brand with a readable search line.")
    skipped = [b for b in DEMAND_BRANDS if b in brands and b not in drawn]
    ui.plot(fig, say, "fact",
            "Search interest = the term's weekly index divided by the 'contact lens' index in the same Google request, monthly average; Google scales each "
            "request to its own peak, so raw indexes are not comparable across terms. "
            + ("Dotted = searched in under 30 weeks (directional). " if any(_active_weeks(BRAND_TERM[b]) < 2 * ebi.MIN_N for b in drawn) else "")
            + ("Dashed = company-level interest, includes eye drops. " if any(b in TERM_CAVEAT for b in drawn) else "")
            + (f"Not drawn, searched in under {ebi.MIN_N} weeks: {', '.join(skipped)}." if skipped else ""),
            bases={b: int((pool["brand_std"] == b).sum()) for b in charts.order_brands(brands) if b in DEMAND_BRANDS}, noun="dated items", key="demand_all_brands")


def _summary_table(d: pd.DataFrame, brands: list) -> None:
    """All brands in one view: which search term each is read on, how many weeks it was searched, whether it is charted below,
    its same-name status and its items in the brand pool. No index values here (they sit in the charts and cards below)."""
    t = trends_signals.load()
    t = t[(t["is_partial"] == 0) & (t["term"] != trends_signals.ANCHOR)] if not t.empty else t
    n_weeks = int(t["date"].nunique()) if not t.empty else 0
    rel = read_table(TRENDS_DB, "SELECT term, kind, related_query FROM trends_related")
    rel = rel if not rel.empty else pd.DataFrame(columns=["term", "kind", "related_query"])
    pool = vd.pool(d)
    rows = []
    for b in [x for x in DEMAND_BRANDS if x in brands] or DEMAND_BRANDS:
        terms = [BRAND_TERM[b]] if b in BRAND_TERM else TERMS_TRIED.get(b, [b])
        weeks = [_active_weeks(x) for x in terms]
        charted = b in BRAND_TERM and weeks[0] >= ebi.MIN_N
        status = collision_status(terms[0], rel)[0] if charted or len(terms) == 1 or terms[0] in _hand_checks() else "-"
        if not charted and status == "Not checked":
            status = "-"
        rows.append({"Brand": b, "Search terms": ", ".join(terms) + (" (company-level)" if b in TERM_CAVEAT else ""), f"Weeks searched (of {n_weeks})": " / ".join(str(w) for w in weeks),
                     "Charted below": ("Yes, directional" if weeks[0] < 2 * ebi.MIN_N else "Yes") if charted else f"No (under {ebi.MIN_N} weeks)",
                     "Same-name check": status, "Items in brand pool": int((pool["brand_std"] == b).sum())})
    st.markdown("**All brands: is there a search line to read?**")
    st.dataframe(pd.DataFrame(rows), hide_index=True, width="stretch")
    st.caption("A search term is charted only with searches in 15+ weeks. The same-name check is shown where it matters (a charted term) or where it was read by hand. "
               "Index values are in the charts below; items are the brand pool, as on every other page.")


def _demand(d: pd.DataFrame, brands: list) -> None:
    _tf, _mf = trends_signals.facts(), market_competitors.trade_facts()
    st.subheader(f"Search interest in Acuvue is {ebi.pct(_tf['idx_chg'])} while category imports fell {abs(_mf['units']):.0f}% in units" if _tf and _mf and _tf["idx_chg"] > 0 > _mf["units"]
                 else "Demand Signals: search interest vs. scraped activity")
    _hc = _hand_checks()
    _all = [t for b in DEMAND_BRANDS for t in _terms_of(b)]
    st.caption(f"Read as interest, not sales. Same-name check: {sum(t in _hc for t in _all)} of {len(_all)} brand search terms have been read by hand "
               f"({', '.join(t for t, (s, _) in _hc.items() if s == 'Clean' and t in _all) or 'none'} clean"
               + "".join(f"; {t} to check" for t, (s, _) in _hc.items() if s == "Check" and t in _all) + "); the rest are not yet checked, so their index could include other uses of the name.")
    st.caption("Google Trends search index (Singapore, 0 to 100, not a search count) against the number of brand-named lens items "
               "collected each month. Counts are items per month in the brand pool; the index is the monthly average of weekly values.")
    _summary_table(d, brands)
    options = [b for b in DEMAND_BRANDS if b in brands] or DEMAND_BRANDS
    brand = st.selectbox("Brand", [ALL_BRANDS] + options, key="demand_signals_brand_pick")
    if brand == ALL_BRANDS:
        _all_brands_chart(d, brands)
        _collision_note(terms=[BRAND_TERM[b] for b in DEMAND_BRANDS if b in brands and b in BRAND_TERM and _active_weeks(BRAND_TERM[b]) >= ebi.MIN_N])
    else:
        term = BRAND_TERM.get(brand)
        s = _monthly_search(term) if term else pd.DataFrame()
        p = _pool(d, [brand])
        if not term or s.empty:
            weeks = ", ".join(f"{t} ({_active_weeks(t)} weeks)" for t in TERMS_TRIED.get(brand, [brand]))
            st.info(f"No readable Google Trends term for {brand}: the terms tried have searches in under {ebi.MIN_N} weeks ({weeks}). "
                    "Search interest is shown for the brands whose own name is searched often enough in Singapore.")
        else:
            weeks = _active_weeks(term)
            if brand in TERM_CAVEAT:
                st.warning(TERM_CAVEAT[brand])
            if weeks < 2 * ebi.MIN_N:
                st.caption(f"Directional: \u201c{term}\u201d has searches in only {weeks} of the weeks since 2021.")
            m = p.groupby("month").size().rename("items").reset_index()
            t = s.merge(m, on="month", how="outer").sort_values("month")
            t["items"] = t["items"].fillna(0)
            t = t[t["month"] >= s["month"].min()]
            fig = go.Figure()
            fig.add_bar(x=t["month"], y=t["items"], name="Items collected", marker_color="#CBD5E1", yaxis="y2")
            fig.add_scatter(x=t["month"], y=t["index"], name="Search index", mode="lines", line=dict(color=BRAND_COLORS.get(brand, "#178197"), width=2))
            fig.update_layout(height=340, margin=dict(l=10, r=10, t=30, b=10), legend=dict(orientation="h", y=1.1, x=0),
                              yaxis=dict(title="Search index (0-100)", range=[0, 105]),
                              yaxis2=dict(title="Items per month", overlaying="y", side="right", showgrid=False))
            st.plotly_chart(fig, width="stretch")
            ui.n_strip({brand: len(p)}, "dated items", attached=True)
            alerts = _divergence(t)
            st.markdown("**Divergence alerts**")
            if not alerts:
                st.info("No month where search interest and collected items moved in clearly opposite directions.")
            for a in alerts[-3:]:
                st.warning(a)
        if term and not s.empty:   # a term that is not drawn has no chart to qualify; the box above already says why
            _collision_note(brand)
    st.divider()
    st.markdown("#### Search interest against the category")
    trends_signals.render()
    _collision_note(terms=["Acuvue", "Olens", "Acuvue Oasys"])
    segment_views.search_direction()


# Same-name check, the SG counterpart of HK's demand_signals.classify_trend_reliability: a search term is clean when 90%+ of
# its top related queries are about lenses or eye care (HK's rule, applied by keyword: a draft until the queries are read).
LENS_WORDS = ("lens", "contact", "acuvue", "oasys", "myacuvue", "olens", "o-lens", "air optix", "dailies", "biofinity", "biotrue",
              "coopervision", "bausch", "lomb", "alcon", "clariti", "myday", "total30", "colour", "color", "circle", "eye", "optical",
              "optic", "optometr", "vision", "toric", "astigmatism", "daily", "monthly", "disposable", "solution", "mpt")
CLEAN_SHARE = 0.9


def _terms_of(brand: str) -> list:
    own = {"Bausch & Lomb": ["Bausch Lomb", "Biotrue"], "CooperVision": ["CooperVision", "Biofinity"], "Alcon": ["Alcon"],
           "Acuvue": ["Acuvue"], "Olens": ["Olens"]}
    return own.get(brand, [brand])


CHECKS_CSV = os.path.normpath(os.path.join(DB_DIR, "..", "data", "research", "trends_term_checks.csv"))


def _hand_checks() -> dict:
    """Terms read by hand on trends.google.com (the scripted pull returns empty lists for most terms): {term: (status, detail)}."""
    if not os.path.exists(CHECKS_CSV):
        return {}
    c = pd.read_csv(CHECKS_CSV)
    return {r.term: (r.status, f"read by hand {r.checked_on}, {r.list_read}: {r.evidence}") for r in c.itertuples()}


def collision_status(term: str, related: pd.DataFrame) -> tuple:
    """(status, detail) for one search term: a hand check if recorded, else the stored 'top' related queries: Clean, Check, or Not checked."""
    if term in _hand_checks():
        return _hand_checks()[term]
    q = related[(related["term"] == term) & (related["kind"] == "top")]["related_query"].astype(str).str.lower()
    q = q.drop_duplicates()
    if len(q) < 3:
        return "Not checked", f"{len(q)} related queries stored" if len(q) else "no related queries stored yet"
    off = [x for x in q if not any(w in x for w in LENS_WORDS)]
    share = 1 - len(off) / len(q)
    if share >= CLEAN_SHARE:
        return "Clean", f"{share:.0%} of {len(q)} top related queries are about lenses or eye care"
    return "Check", f"{share:.0%} of {len(q)} top related queries are about lenses; read: " + ", ".join(off[:5])


def _collision_note(brand: str | None = None, terms: list | None = None) -> None:
    """The same-name line: for one brand's terms under the Demand Signals chart, or (terms=) for the terms drawn in the category
    search charts, so every chart that plots a search term carries the status of that term."""
    rel = read_table(TRENDS_DB, "SELECT term, kind, related_query FROM trends_related")
    rel = rel if not rel.empty else pd.DataFrame(columns=["term", "kind", "related_query"])
    rows = [(t, *collision_status(t, rel)) for t in (terms or _terms_of(brand))]
    icon = {"Clean": "✅", "Check": "⚠️", "Not checked": "➖"}
    st.caption("**Same-name check** (a term that is also an ordinary word or another company's name would inflate the index). "
               + " · ".join(f"{icon[s]} “{t}” {s.lower()}: {d}" for t, s, d in rows)
               + ". Rule: clean when 90%+ of top related queries are about lenses; a keyword draft until the queries are read. "
                 "The scripted pull returns empty lists for most terms, so checks are read by hand on trends.google.com "
                 "(Scripts/data/research/trends_term_checks.csv).")


def _divergence(t: pd.DataFrame) -> list:
    """Months where the search index moved 25%+ one way and items the other way, on at least 5 items in the month."""
    out = []
    t = t.reset_index(drop=True)
    for i in range(1, len(t)):
        a, b = t.iloc[i - 1], t.iloc[i]
        if pd.isna(a["index"]) or pd.isna(b["index"]) or a["index"] <= 0 or max(a["items"], b["items"]) < 5:
            continue
        si = b["index"] / a["index"] - 1
        sn = (b["items"] - a["items"]) / a["items"] if a["items"] else None
        if sn is not None and abs(si) >= 0.25 and abs(sn) >= 0.25 and si * sn < 0:
            out.append(f"{b['month']:%b %Y}: search index {si:+.0%} vs the month before while items collected moved {sn:+.0%} "
                       f"({int(a['items'])} to {int(b['items'])}).")
    return out


def _monthly(d: pd.DataFrame, brands: list) -> None:
    st.subheader("Monthly Trends: brand-named activity over time")
    p = _pool(d, brands)
    if p.empty:
        st.info("No dated items for the selected brands.")
        return
    p = _range(p)
    st.caption("Items per month that name a selected brand and are about lenses. Counts only: a month rarely holds 15 items for one brand, "
               "so sentiment is read by quarter below, and by year on Brand Health.")
    ui.goto("Brand Health", key="td_to_brand_health")
    by_ch = p.groupby(["month", "channel"]).size().rename("items").reset_index()
    fig = px.bar(by_ch, x="month", y="items", color="channel", title="Items collected per month, by channel")
    fig.update_layout(height=330, margin=dict(l=10, r=10, t=40, b=10), legend_title_text="", xaxis_title="", yaxis_title="Items")
    st.plotly_chart(fig, width="stretch")
    ui.n_strip(dict(p.groupby("channel").size().sort_values(ascending=False)), "dated items", attached=True)
    by_b = p.groupby(["month", "brand_std"]).size().rename("items").reset_index()
    fig = px.line(by_b, x="month", y="items", color="brand_std", markers=True, color_discrete_map=BRAND_COLORS,
                  title="Items collected per month, by brand")
    fig.update_layout(height=330, margin=dict(l=10, r=10, t=40, b=10), legend_title_text="", xaxis_title="", yaxis_title="Items")
    st.plotly_chart(fig, width="stretch")
    ui.n_strip({b: int(n) for b, n in p.groupby("brand_std").size().reindex(charts.order_brands(p["brand_std"].unique())).items()},
               "dated items", attached=True)
    ui.show_data("Show the monthly counts", by_ch.pivot_table(index="month", columns="channel", values="items", fill_value=0)
                 .sort_index(ascending=False).astype(int))
    st.divider()
    _quarterly(p)


def _quarterly(p: pd.DataFrame) -> None:
    """Net sentiment per brand per quarter, drawn only where the brand has MIN_N items in the quarter. A quarter where one
    channel supplies more than SINGLE_CHANNEL of the items is drawn hollow: it reads that channel, not the brand."""
    st.markdown("#### Net sentiment by quarter")
    q = p.assign(quarter=p["date"].dt.to_period("Q"))
    rows = []
    for (b, qt), g in q.groupby(["brand_std", "quarter"]):
        r = vd.net(g["sentiment"])
        top = g["channel"].value_counts()
        rows.append({"brand": b, "quarter": qt, "n": r[2], "net": r[0], "se": r[1], "top": top.index[0], "top_share": top.iloc[0] / r[2]})
    t = pd.DataFrame(rows)
    if t.empty:
        st.info("No dated, labelled items for the selected brands.")
        return
    ok = t[t["n"] >= ebi.MIN_N]
    st.caption(f"Net sentiment = % positive minus % negative, drawn only for a brand-quarter with {ebi.MIN_N}+ items; bars are the 95% interval. "
               f"A hollow marker means one channel supplies over {SINGLE_CHANNEL:.0%} of that quarter's items. Quarters under the floor are not drawn. "
               "Brand Health's trend plots a different measure (the 0-100 balanced score), so the same brand-quarter reads differently there.")
    if ok.empty:
        st.info(f"No brand reaches {ebi.MIN_N} items in any quarter.")
    else:
        span = pd.period_range(q["quarter"].min(), q["quarter"].max(), freq="Q")
        fig = go.Figure()
        for b in charts.order_brands(ok["brand"].unique()):
            s = ok[ok["brand"] == b].set_index("quarter").reindex(span)
            col = BRAND_COLORS.get(b, "#64748B")
            hollow = (s["top_share"] > SINGLE_CHANNEL).tolist()
            fig.add_scatter(x=[str(x) for x in span], y=s["net"], name=b, mode="lines+markers", connectgaps=False,
                            line=dict(color=col, width=2),
                            marker=dict(size=9, color=col, symbol=["circle-open" if h else "circle" for h in hollow], line=dict(width=2, color=col)),
                            error_y=dict(type="data", array=(1.96 * s["se"]).fillna(0).tolist(), thickness=1, width=3),
                            customdata=s[["n", "top", "top_share"]].fillna(0).values,
                            hovertemplate="%{x}: net %{y:+.0f} · n=%{customdata[0]:.0f} · mostly %{customdata[1]} (%{customdata[2]:.0%})<extra>" + b + "</extra>")
        fig.add_hline(y=0, line=dict(color="#94A3B8", width=1))
        fig.update_layout(height=340, margin=dict(l=10, r=10, t=10, b=10), legend=dict(orientation="h", y=1.1, x=0),
                          yaxis=dict(title="Net sentiment (points)", zeroline=False), xaxis=dict(title="", type="category"))
        both = ok.groupby("quarter")["brand"].nunique()
        multi = [str(x) for x in both[both >= 2].index]
        acu = ok[ok["brand"] == "Acuvue"].sort_values("quarter")
        if len(acu) >= 2:
            say = (f"Acuvue net sentiment moved from {ebi.sgn(acu.iloc[0]['net'])} in {acu.iloc[0]['quarter']} "
                   f"to {ebi.sgn(acu.iloc[-1]['net'])} in {acu.iloc[-1]['quarter']}.")
        else:
            say = f"Only {len(ok)} of {len(t)} brand-quarters reach {ebi.MIN_N} items."
        ui.plot(fig, say, "fact",
                (f"Quarters where two or more brands are readable: {', '.join(multi)}." if multi else "No quarter has two readable brands."),
                height=340, key="qtr_net", bases={b: int(ok.loc[ok["brand"] == b, "n"].sum()) for b in charts.order_brands(ok["brand"].unique())},
                noun="items in drawn quarters")
    shown = pd.DataFrame({"Brand": t["brand"], "Quarter": t["quarter"].astype(str), "Items": t["n"],
                          "Net": [ebi.sgn(n) if k >= ebi.MIN_N else "-" for n, k in zip(t["net"], t["n"])],
                          "Main channel": [f"{c} ({s:.0%})" for c, s in zip(t["top"], t["top_share"])]})
    ui.show_data("Show every brand-quarter", shown.sort_values(["Brand", "Quarter"], ascending=[True, False]),
                 caption=f"{len(ok)} of {len(t)} brand-quarters have {ebi.MIN_N}+ items.")


def _anomalies(d: pd.DataFrame, brands: list) -> None:
    st.subheader("Anomaly Explorer")
    p = _pool(d, brands)
    if p.empty:
        st.info("No dated items for the selected brands.")
        return
    m = p.groupby("month").size().rename("items").reset_index()
    full = pd.DataFrame({"month": pd.date_range(m["month"].min(), m["month"].max(), freq="MS")}).merge(m, how="left").fillna({"items": 0})
    mu, sd = full["items"].mean(), full["items"].std()
    full["z"] = (full["items"] - mu) / sd if sd else 0.0
    flagged = full[(full["z"] >= 2) & (full["items"] >= ebi.MIN_COUNT)].sort_values("month", ascending=False)
    st.caption(f"A month is flagged when its item count is 2+ standard deviations above the average month ({mu:.1f} items) and "
               f"holds at least {ebi.MIN_COUNT} items. Volume spikes, not sentiment.")
    fig = go.Figure()
    fig.add_bar(x=full["month"], y=full["items"], marker_color=["#E8A33D" if z >= 2 else "#CBD5E1" for z in full["z"]], name="Items")
    fig.add_hline(y=mu + 2 * sd, line=dict(color="#64748B", dash="dash"))
    fig.update_layout(height=300, margin=dict(l=10, r=10, t=20, b=10), showlegend=False, yaxis_title="Items per month")
    st.plotly_chart(fig, width="stretch")
    ui.n_strip({"all selected brands": len(p)}, "dated items", attached=True)
    if flagged.empty:
        st.info("No month stands out.")
        return
    labels = [f"{r.month:%b %Y}: {int(r.items)} items" for r in flagged.itertuples()]
    pick = st.selectbox("Flagged month", labels, key="ae_event_choice")
    month = flagged.iloc[labels.index(pick)]["month"]
    sub = p[p["month"] == month]
    c1, c2 = st.columns(2)
    c1.markdown("**By channel**")
    c1.dataframe(sub.groupby("channel").size().rename("Items").reset_index().rename(columns={"channel": "Channel"}), hide_index=True, width="stretch")
    c2.markdown("**By brand**")
    c2.dataframe(sub.groupby("brand_std").size().rename("Items").reset_index().rename(columns={"brand_std": "Brand"}), hide_index=True, width="stretch")
    ui.items_panel(vd.view(sub))


def render(d: pd.DataFrame, brands: list, tabs) -> None:
    """`tabs` are the three sub-tab containers, in order: Demand Signals, Monthly Trends, Anomaly Explorer."""
    if d.empty:
        st.info("Run Scripts/build_voice_items.py and Scripts/tag_voice_items.py to build the tables this page reads.")
        return
    t_demand, t_month, t_anom = tabs
    with t_demand:
        _demand(d, brands)
    with t_month:
        _monthly(d, brands)
    with t_anom:
        _anomalies(d, brands)
    _b = d[d["brand_std"].isin(brands) & d["in_pool"]]
    ui.read_comments(_b, "Read the brand-named items behind these counts (brand pool)", key="tr_read")
