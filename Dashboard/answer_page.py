"""
Answer: the top of the pyramid. One bottom line (the headline cards above it carry the numbers), the implication for the
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


# fact cards whose figure is already in the headline strip, so the supporting cards do not show it twice
_IN_STRIP = {"Barriers & journey > App", "Brand & market > Demand"}


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
    out.append(("Net sentiment", f"{ebi.sgn(g['net_f'])} vs {ebi.sgn(g['net_p'])}" if g else "-", f"vs peers: {bm['verdict'].replace(' with peers', '')}" if g else None,
                "% positive minus % negative, re-weighted to one channel mix where possible. The label says whether the gap is more than chance."))
    top = bp["top"]
    out.append(("Top complaint", top["group"] if top is not None else "-", f"{int(top['kf'])} items" if top is not None else None,
                "The topic group with the most negative or mixed consumer items about Acuvue."))
    if len(eras) and eras.iloc[-1]["n"] >= ebi.MIN_N:
        e = eras.iloc[-1]
        out.append(("App reviews", f"{e['neg']:.0f}% negative", f"{e['era']}, n={int(e['n'])}", "Share of written app reviews the tagger reads as negative, latest period."))
    else:
        out.append(("App reviews", "-", None, None))
    out.append(("Search interest", f"{ebi.pct(tf['idx_chg'])}" if tf else "-", f"Acuvue vs {tf['prev']}" if tf else None,
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
        tone = {"level with peers": "flat", "ahead of peers": "good", "behind peers": "bad"}.get(bm["verdict"])
        rows.append((f"{FOCAL} sentiment is {'{' + tone + ':' + bm['verdict'] + '}' if tone else bm['verdict']}", "Level" if bm["verdict"] == "level with peers" else "B · one channel",
                     f"n={bm['n_f']} vs {bm['n_p']} items" + (f"; {len(std['channels'])} channels" if std else ""), "Brand & market > Position"))
    for r in clear.sort_values("gap").itertuples():
        tone = "bad" if r.gap < 0 else "good"
        rows.append((f"{FOCAL} {{{tone}:{'trails' if r.gap < 0 else 'leads'}}} on **{r.channel}** {{{tone}:{ebi.pts(r.gap)}}}", "B · one channel",
                     f"Net sentiment {ebi.sgn(r.net_f)} vs {ebi.sgn(r.net_p)} (n={r.n_f} vs {r.n_p}); peers are {r.peer_top_share:.0f}% {r.peer_top}", "Brand & market > Channels"))
    sg = bp["sig"]
    for r in sg.itertuples():
        rows.append((f"{FOCAL} draws {{bad:more {r.group} complaints}} than peers", r.grade, f"n={r.kf} vs {r.ko} complaints; {', '.join(r.where) or 'one channel'} only",
                     "Barriers & journey > Barrier"))
    top = gt.sort_values("share_f", ascending=False).iloc[0] if len(gt) and gt["share_f"].notna().any() else None
    if top is not None:
        rows.append((f"**{top['group']}** is the main topic", "Directional", f"n={int(top['n_f'])} {FOCAL} items; {top['grade'].split(' ·')[0].lower()} vs peers", "Brand & market > Themes"))
    if len(eras) and eras.iloc[-1]["n"] >= ebi.MIN_N:
        e = eras.iloc[-1]
        rows.append((f"The **app** is the clearest barrier ({{bad:{e['neg']:.0f}% negative}}, {e['era']})", "Market fact", f"n={len(a)} written reviews; Acuvue only, skews negative",
                     "Barriers & journey > App"))
    if len(m) >= ebi.MIN_N:
        rows.append(("Store reviews are {good:positive} and about the **shop**", "Directional", f"n={len(m)} contact-lens reviews; skews positive", "Barriers & journey > Retail"))
    if tf:
        rows.append(("Search interest is up while imports are down" if mf and tf["idx_chg"] > 0 > mf["units"] else "Demand signals", "Directional",
                     f"Google Trends index, {tf['weeks']} weeks" + (f"; imports {mf['first']} to {mf['last']}" if mf else ""), "Brand & market > Demand"))
    return pd.DataFrame(rows, columns=["Finding", "Evidence", "Base", "Where"])


def render(d: pd.DataFrame, products_all: pd.DataFrame) -> None:
    if d.empty:
        st.info("Run Scripts/build_voice_items.py and Scripts/tag_voice_items.py to build the tables this page reads.")
        return
    bm, bp = brand_market_page.facts(d), barriers_page.facts(d)
    tf, mf = trends_signals.facts(), market_competitors.trade_facts()
    g, eras = bm["read"], bp["eras"]
    last = eras.iloc[-1] if len(eras) else None
    app_ok = last is not None and last["n"] >= ebi.MIN_N

    if g and app_ok:
        bottom = (f"{FOCAL} is {bm['verdict']} on sentiment, so the barrier is not the brand. It is the MyACUVUE app: "
                  f"{last['neg']:.0f}% of reviews negative in {last['era']} (n={int(last['n'])}).")
    elif g:
        bottom = f"{FOCAL}'s brand sentiment is {bm['verdict']}."
    else:
        bottom = "The scraped data cannot yet separate Acuvue from its peers."
    implication = "Lead WhatsApp with sign-in, OTP and date-of-birth help at Trial, then comfort proof and first-fitting guidance."
    ui.pyramid(bottom, [], implication)   # no tiles: the headline cards above carry the numbers, each tab's own page the detail

    ui.section("How sure we are of each finding", "Net sentiment = % positive minus % negative (−100 to +100). A gap in pts = Acuvue net minus peers net. Fact = counted; Directional = small or skewed sample; Level, B, A = strength of a brand gap.",
               "Evidence", kind="fact")
    ui.evidence_list(list(_evidence_rows(bm, bp, tf, mf, d).itertuples(index=False, name=None)))

    overview_pages.render_cards([c for c in summary_facts.build(d, products_all) if c["where"] not in _IN_STRIP], "Supporting facts")

    with st.expander("Which tab answers my question?", expanded=False):
        ui.route_list(_WHERE)
