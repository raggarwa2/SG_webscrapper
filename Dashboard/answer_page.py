"""
Answer: the top of the pyramid. One bottom line, four findings that support it (each opens its own tab), the implication for the
WhatsApp and registration goal in context.md, and how sure we are of each finding. Every number is computed by the same code
as the page it points to (brand_market_page.facts, barriers_page.facts, summary_facts), so the Answer cannot disagree with them.
"""

import pandas as pd
import streamlit as st

import barriers_page
import brand_market_page
import ebi
import market_competitors
import overview_pages
import summary_facts
import trends_signals
import ui
import voice_data as vd

FOCAL = vd.FOCAL

_WHERE = [
    ("Where do we stand against peers? Is the category growing?", "Brand & market"),
    ("What do people talk about, and what do brands post?", "Brand & market"),
    ("What stops people registering, and where does the app lose them?", "Barriers & journey"),
    ("Which WhatsApp message goes at which stage?", "Barriers & journey"),
    ("How do prices, listings and compliance compare?", "Market & channel"),
    ("What does the desk research claim, and does the data confirm it?", "Category users & hypotheses"),
    ("How many items sit behind a number, and how were they labelled?", "Data & method"),
]


def header_metrics(d: pd.DataFrame) -> list:
    """The six numbers in the strip under the banner: (label, value, delta or None, help). Computed from the shared facts."""
    if d.empty:
        return []
    bm, bp = brand_market_page.facts(d), barriers_page.facts(d)
    g, eras, tf = bm["read"], bp["eras"], trends_signals.facts()
    pool = bm["pool"]
    raw = vd.raw_counts()
    out = [("Data points", f"{sum(v['collected'] for v in raw.values()):,}", None, "Everything collected: consumer comments, posts and reviews, retailer reviews, "
            "app reviews, and brand posts and ads. Brands are compared on the consumer items that name a brand.")]
    out.append(("Net sentiment", f"{g['net_f']:+.0f} vs {g['net_p']:+.0f}" if g else "-", f"vs peers: {bm['verdict'].replace(' with peers', '')}" if g else None,
                "% positive minus % negative, re-weighted to one channel mix where possible. The label says whether the gap is more than chance."))
    top = bp["top"]
    out.append(("Top complaint", top["group"] if top is not None else "-", f"{int(top['kf'])} items" if top is not None else None,
                "The topic group with the most negative or mixed consumer items about Acuvue."))
    if len(eras) and eras.iloc[-1]["n"] >= ebi.MIN_N:
        e = eras.iloc[-1]
        out.append(("App reviews", f"{e['neg']:.0f}% negative", f"{e['era']}, n={int(e['n'])}", "Share of written app reviews the tagger reads as negative, latest period."))
    else:
        out.append(("App reviews", "-", None, None))
    out.append(("Search interest", f"{tf['idx_chg']:+.0f}%" if tf else "-", f"Acuvue vs {tf['prev']}" if tf else None,
                "Google Trends index, Jan to the latest complete week against the same days last year."))
    dd = pool["date"].dropna()
    out.append(("Data window", f"{dd.min():%b %Y} to {dd.max():%b %Y}" if len(dd) else "-", None,
                "Earliest to latest dated item in the brand pool. Xiaohongshu comments and KiasuParents carry no usable date."))
    return out


@st.cache_data(ttl=600, show_spinner=False, max_entries=2)
def _header(m_items: float, m_tags: float) -> list:
    return header_metrics(vd.load())


def header() -> list:
    """header_metrics, cached on the table timestamps so the strip does not recompute on every rerun."""
    if not vd.available():
        return []
    return _header(vd.VOICE_DB.stat().st_mtime, vd.TAG_DB.stat().st_mtime)


def _evidence_rows(bm: dict, bp: dict, tf: dict, mf: dict, d: pd.DataFrame) -> pd.DataFrame:
    g, cg, gt = bm["read"], bm["channels"], bm["groups"]
    clear = cg[cg["ok"] & cg["lo"].notna() & ((cg["lo"] > 0) | (cg["hi"] < 0))] if len(cg) else cg
    a, m = vd.app(d), vd.maps(d)
    eras = bp["eras"]
    rows = []
    if g:
        std = bm["std"]
        rows.append((f"{FOCAL} sentiment is {bm['verdict']}", "Level" if bm["verdict"] == "level with peers" else "B · one channel",
                     f"{bm['n_f']} vs {bm['n_p']} items" + (f"; {len(std['channels'])} channels" if std else ""), "Brand & market > Position"))
    for r in clear.sort_values("gap").itertuples():
        rows.append((f"{FOCAL} {'trails' if r.gap < 0 else 'leads'} on {r.channel} ({r.gap:+.0f})", "B · one channel",
                     f"{r.n_f} vs {r.n_p} items; peers are {r.peer_top_share:.0f}% {r.peer_top}", "Brand & market > Channels"))
    sg = bp["sig"]
    for r in sg.itertuples():
        rows.append((f"{FOCAL} draws more {r.group} complaints than peers", r.grade, f"{r.kf} vs {r.ko} complaints; {', '.join(r.where) or 'one channel'} only",
                     "Barriers & journey > Barrier"))
    top = gt.sort_values("share_f", ascending=False).iloc[0] if len(gt) and gt["share_f"].notna().any() else None
    if top is not None:
        rows.append((f"{top['group']} is the main topic", "Directional", f"{int(top['n_f'])} {FOCAL} items; {top['grade'].split(' ·')[0].lower()} vs peers", "Brand & market > Themes"))
    if len(eras) and eras.iloc[-1]["n"] >= ebi.MIN_N:
        e = eras.iloc[-1]
        rows.append((f"The app is the clearest barrier ({e['neg']:.0f}% negative, {e['era']})", "Market fact", f"{len(a)} written reviews; Acuvue only, skews negative",
                     "Barriers & journey > App"))
    if len(m) >= ebi.MIN_N:
        rows.append(("Store reviews are positive and about the shop", "Directional", f"{len(m)} contact-lens reviews; skews positive", "Barriers & journey > Retail"))
    if tf:
        rows.append(("Search interest is up while imports are down" if mf and tf["idx_chg"] > 0 > mf["units"] else "Demand signals", "Directional",
                     f"Google Trends index, {tf['weeks']} weeks" + (f"; imports {mf['first']} to {mf['last']}" if mf else ""), "Brand & market > Demand"))
    rows.append(("Registration drop-off and the 7% to 14% path", "Needs internal data", "No registration or CRM data in scraped sources", "Category users & hypotheses > Stage 2 bridge"))
    return pd.DataFrame(rows, columns=["Finding", "Evidence", "Base", "Where"])


def render(d: pd.DataFrame, products_all: pd.DataFrame) -> None:
    if d.empty:
        st.info("Run Scripts/build_voice_items.py and Scripts/tag_voice_items.py to build the tables this page reads.")
        return
    bm, bp = brand_market_page.facts(d), barriers_page.facts(d)
    tf, mf = trends_signals.facts(), market_competitors.trade_facts()
    g, eras, top = bm["read"], bp["eras"], bp["top"]
    last = eras.iloc[-1] if len(eras) else None
    app_ok = last is not None and last["n"] >= ebi.MIN_N

    if g and app_ok:
        bottom = (f"{FOCAL} is {bm['verdict']} on sentiment, so the barrier is not the brand. It is the MyACUVUE app: "
                  f"{last['neg']:.0f}% of reviews negative in {last['era']} (n={int(last['n'])}).")
    elif g:
        bottom = f"{FOCAL}'s brand sentiment is {bm['verdict']}."
    else:
        bottom = "The scraped data cannot yet separate Acuvue from its peers."
    tiles = []
    if g:
        tiles.append({"label": "Position", "msg": f"{FOCAL} is {bm['verdict']} on sentiment", "value": f"{g['net_f']:+.0f} vs {g['net_p']:+.0f}",
                      "tone": "flat" if bm["verdict"] == "level with peers" else ("good" if g["gap"] > 0 else "bad"),
                      "stat": f"Net sentiment, {FOCAL} vs peers", "text": f"Interval {g['lo']:+.0f} to {g['hi']:+.0f}"})
    if top is not None:
        tiles.append({"label": "Barrier", "msg": f"{top['group']} draws the most complaints" + barriers_page._vs_peers(top, short=True).replace(";", ",", 1),
                      "value": f"{int(top['kf'])} complaints", "tone": "watch", "stat": f"{FOCAL} items negative or mixed on {top['group']}"})
    if app_ok:
        tiles.append({"label": "App reviews", "msg": "The app loses people at sign-in, registration and points", "value": f"{last['neg']:.0f}% negative", "tone": "bad",
                      "stat": f"Written app reviews that are negative, {last['era']}", "text": f"n={int(last['n'])}"})
    if tf:
        agree = mf is None or (tf["idx_chg"] > 0) == (mf["units"] > 0)
        tiles.append({"label": "Demand", "msg": ("Search interest and lens imports point in opposite directions" if not agree else
                                                "Search interest in Acuvue is " + ("rising" if tf["idx_chg"] > 0 else "falling")),
                      "value": f"{tf['idx_chg']:+.0f}% searches", "tone": "flat" if agree else "watch",
                      "stat": f"Change in {FOCAL} search interest vs {tf['prev']}", "text": (f"Lens imports {mf['units']:+.0f}% in units, {mf['first']} to {mf['last']}" if mf else "Google Trends index")})
    implication = ("Lead WhatsApp with sign-in, OTP and date-of-birth help at Trial, then comfort proof and first-fitting guidance. "
                   "Size registration drop-off with Stage 2 data before setting the 7% to 14% path.")
    ui.pyramid(bottom, tiles, implication)

    ui.section("How sure we are of each finding", "Fact = counted. Directional = small or skewed sample. Level, B, A = strength of a brand gap.",
               "Evidence", kind="fact")
    ui.evidence_list(list(_evidence_rows(bm, bp, tf, mf, d).itertuples(index=False, name=None)))

    overview_pages.render_cards(summary_facts.build(d, products_all), "Supporting facts")

    with st.expander("What the scraped data cannot answer", expanded=False):
        overview_pages.render_evidence()
    with st.expander("Which tab answers my question?", expanded=False):
        ui.route_list(_WHERE)
