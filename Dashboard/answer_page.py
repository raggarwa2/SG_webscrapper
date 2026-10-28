"""
Answer: the top of the pyramid. One bottom line (the headline cards above it carry the numbers), the next step for the
WhatsApp and registration goal in context.md, and how sure we are of each finding. Every number is computed by the same code
as the page it points to (brand_market_page.facts, barriers_page.facts, summary_facts), so the Answer cannot disagree with them.
"""

import re
from pathlib import Path

import pandas as pd
import plotly.graph_objects as go
import streamlit as st

import barriers_page
import brand_market_page
import ebi
import market_competitors
import overview_pages
import segment_data as sd
import summary_facts
import trends_signals
import ui
import voice_data as vd
import whatsapp_map

FOCAL = vd.FOCAL

# question -> [(button label, tab, section pill or None)]
_WHERE = [
    ("Where do we stand against peers? Is the category growing?", [("Brand Health", "Brand Health", None)]),
    ("What do people talk about, and what do brands post?", [("Brand Health", "Brand Health", None)]),
    ("What stops people registering, and where does the app lose them?", [("Journey & App", "Journey & App", None), ("Barriers", "Research & Triangulation", "Barriers")]),
    ("Which WhatsApp message goes at which stage?", [("Journey & App", "Journey & App", None)]),
    ("How do stores compare?", [("Retail & Promotions", "Retail & Promotions", None)]),
    ("What does the desk research claim, and does the data confirm it?", [("Research & Triangulation", "Research & Triangulation", None)]),
    ("How many items sit behind a number, and how were they labelled?", [("Data Notes", "Data Notes", None)]),
]


# fact cards whose figure is already in the headline strip, so the supporting cards do not show it twice
_IN_STRIP = {"Journey & App > App", "Trends & Demand > Demand Signals"}


def header_metrics(d: pd.DataFrame) -> list:
    """The six numbers in the strip under the banner: (label, value, delta or None, help). Computed from the shared facts."""
    if d.empty:
        return []
    bm, bp = brand_market_page.facts(d), barriers_page.facts(d)
    g, eras, tf = bm["read"], bp["eras"], trends_signals.facts()
    pool = bm["pool"]
    raw = vd.raw_counts()
    out = [("Data points", f"{len(d):,}", "tagged items", f"Items read and tagged by the one tagger: consumer comments, posts and reviews, retailer reviews, app reviews, and brand posts and ads. "
            f"{sum(v['collected'] for v in raw.values()):,} were collected before the lens filter. Brands are compared on the {len(pool):,} consumer items that name a brand.")]
    out.append(("Net sentiment", f"{ebi.sgn(g['net_f'])} vs {ebi.sgn(g['net_p'])}" if g else "-", f"vs peers: {bm['verdict'].replace(' with peers', '')}" if g else None,
                "% positive minus % negative, re-weighted to one channel mix where possible. The label says whether the gap is more than chance."))
    sg = bp["sig"]
    sg = sg[sg["group"] != "Product & look"].sort_values("rf", ascending=False) if len(sg) else sg
    if len(sg):
        t = sg.iloc[0]
        out.append(("Complaint gap", t["group"], f"{t['rf']:.1f}% vs {t['ro']:.1f}% of items",
                    "The topic group where Acuvue's consumers complain more often than peers' consumers, after the significance and channel checks."))
    else:
        out.append(("Complaint gap", "None", "no group differs", "No topic group has a higher Acuvue complaint rate than peers after the significance and channel checks."))
    if len(eras) and eras.iloc[-1]["n"] >= ebi.MIN_N:
        e = eras.iloc[-1]
        out.append(("Written app reviews", f"{e['neg']:.0f}% negative", f"{e['era']}, n={int(e['n'])}", "Share of written app reviews the tagger reads as negative, latest period."))
    else:
        out.append(("App reviews", "-", None, None))
    out.append(("Search interest", f"{ebi.pct(tf['idx_chg'])}" if tf else "-", f"{tf['window']} vs {tf['prev']}" if tf else None,
                "Google Trends index for Acuvue, Jan to the latest complete week against the same days last year. "
                + (f"Category search over the same weeks: {ebi.pct(tf['cat_chg'])}." if tf else "")))
    dd = pool["date"].dropna()
    out.append(("Data window", f"{dd.quantile(0.10).year} to {dd.max():%b %Y}" if len(dd) else "-", "90% of dated items" if len(dd) else None,
                f"From the year that holds the newest 90% of dated items in the brand pool to the latest item; the earliest is {dd.min():%b %Y}. "
                "Xiaohongshu comments and KiasuParents carry no usable date."))
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
        rows.append((f"{FOCAL} sentiment is {'{' + tone + ':' + bm['verdict'] + '}' if tone else bm['verdict']}", "No gap" if bm["verdict"] == "level with peers" else "B · one channel",
                     f"n={bm['n_f']} vs {bm['n_p']} items" + (f"; {len(std['channels'])} channels" if std else "") + f"; gap {ebi.pts(g['gap'])}, interval {ebi.sgn(g['lo'])} to {ebi.sgn(g['hi'])}",
                     "Brand Health > Tested gaps", "New"))
    for r in clear.sort_values("gap").itertuples():
        tone = "bad" if r.gap < 0 else "good"
        rows.append((f"{FOCAL} {{{tone}:{'trails' if r.gap < 0 else 'leads'}}} on **{r.channel}** {{{tone}:{ebi.pts(r.gap)}}}", "B · one channel",
                     f"Net sentiment {ebi.sgn(r.net_f)} vs {ebi.sgn(r.net_p)} (n={r.n_f} vs {r.n_p}); peers are {r.peer_top_share:.0f}% {r.peer_top}", "Brand Health > Acuvue by channel", "New"))
    sg = bp["sig"]
    for r in sg.itertuples():
        rows.append((f"{FOCAL} draws {{bad:more {r.group} complaints}} than peers", r.grade, f"n={r.kf} vs {r.ko} complaints; {', '.join(r.where) or 'one channel'} only",
                     "Research & Triangulation > Barriers", "New"))
    if len(eras) and eras.iloc[-1]["n"] >= ebi.MIN_N:
        e = eras.iloc[-1]
        rows.append((f"The **app** is the most visible friction: {{bad:{e['neg']:.0f}% of written reviews negative}} in {e['era']}", "Market fact", f"n={len(a)} written reviews; Acuvue only, skews negative; reviewers already installed it, so people who stopped earlier are not heard",
                     "Journey & App > App", "Confirms"))
    if len(m) >= ebi.MIN_N:
        rows.append(("Store reviews are {good:positive} and about the **shop**", "Directional", f"n={len(m)} contact-lens reviews; skews positive", "Retail & Promotions", "New"))
    if tf:
        rows.append(("Search interest is up while imports are down" if mf and tf["idx_chg"] > 0 > mf["units"] else "Demand signals", "Directional",
                     f"Google Trends index, {tf['weeks']} weeks" + (f"; imports {mf['first']} to {mf['last']}" if mf else ""), "Trends & Demand > Demand Signals", "New"))
    rows += _segment_rows()
    return pd.DataFrame(rows, columns=["Finding", "Evidence", "Base", "Where", "Tag"])


def _segment_rows() -> list:
    """Findings from the segment study (AI answers, reference voice, segment search terms), counted live from the same tables the pages read."""
    rows = []
    if sd.available():
        a = sd.ai_answers()
        if len(a):
            dom = sd.domain_table(a)
            n_ac = int(dom.loc[dom["Domain"].str.contains("acuvue", case=False), "Answers"].sum())
            n_oth = int(dom.loc[dom["Domain"].str.contains("coopervision|myalcon|bausch|olens", case=False), "Answers"].sum())
            rows.append((f"AI engines cite **acuvue.com** {n_ac} times in {len(a)} answers; other lens-brand sites {n_oth}", "Directional",
                         f"n={len(a)} answers (ChatGPT {int((a['engine'] == 'chatgpt_search').sum())}, Perplexity {int((a['engine'] == 'perplexity_web').sum())}); "
                         "AI answers, not consumers; Perplexity hides some sources", "Research & Triangulation > Research Findings", "New"))
        t = sd.term_table()
        pr = t[(t["Term"] == "presbyopia") & t["Readable"]]
        if len(pr) and pd.notna(pr.iloc[0]["Change"]):
            r = pr.iloc[0]
            rows.append((f"Searches for **presbyopia** are {{{'good' if r['Change'] > 0 else 'bad'}:{ebi.pct(r['Change'])}}}", "Directional",
                         f"Google Trends index, last 52 weeks vs the 52 before; {int(r['Weeks with searches'])} weeks with searches", "Trends & Demand > Demand Signals", "New"))
    if sd.reference_available():
        d = sd.reference_voice()
        if len(d) >= ebi.MIN_N:
            ex = d.explode("themes").dropna(subset=["themes"])
            top = ex["themes"].value_counts()
            if len(top) and int(top.iloc[0]) >= ebi.MIN_COUNT:
                rows.append((f"Viewers elsewhere raise **{top.index[0]}** most: {int(top.iloc[0])} of {len(d)} comments", "Directional",
                             f"n={len(d)} YouTube and TikTok comments read; not Singapore, counts only", "Reviews & Sentiment > New Wearers", "New"))
    return rows


def _open_pages(where: pd.Series, prefix: str = "ans") -> None:
    """One button per page that the findings above come from ("Tab > part" in the Where column), so the reader can open the detail."""
    pages = []
    for w in where.drop_duplicates():
        tab, _, part = w.partition(" > ")
        tab = tab.strip()
        key = (tab, part.strip() if tab == "Research & Triangulation" else None)
        if tab in ui.TABS and key not in pages:
            pages.append(key)
    if not pages:
        return
    st.caption("Open the page behind these findings:")
    for col, (tab, section) in zip(st.columns(max(len(pages), 3)), pages):
        with col:
            ui.goto(tab, f"{tab}: {section}" if section else tab, key=f"{prefix}_open_{ui.anchor_id(tab)}_{ui.anchor_id(section or '')}", section=section)


def _wa_table(d: pd.DataFrame) -> pd.DataFrame:
    """The WhatsApp map's barrier table for Acuvue on the shared labels, all peers (same frame as Journey & App > Message)."""
    peers = [b for b in vd.pool(d)["brand_std"].dropna().unique() if b != FOCAL]
    return whatsapp_map.build(barriers_page.wa_frame(d), FOCAL, peers)


@st.cache_data(ttl=600, show_spinner=False, max_entries=2)
def _exec(m_items: float, m_tags: float, m_code: float) -> dict:
    return exec_facts(vd.load())


def exec_facts(d: pd.DataFrame) -> dict:
    """What the Executive read shows, as plain values: the bottom line, what is new, what to send and
    how sure we are. Every figure comes from the same code as the page it points to."""
    bm, bp = brand_market_page.facts(d), barriers_page.facts(d)
    tf, mf = trends_signals.facts(), market_competitors.trade_facts()
    g, eras = bm["read"], bp["eras"]
    last = eras.iloc[-1] if len(eras) else None
    app_ok = last is not None and last["n"] >= ebi.MIN_N
    out = {"badges": []}
    detail = []
    if g:
        healthy = g["net_f"] > 0 and bm["verdict"] != "behind peers"
        out["bottom"] = ((f"The {FOCAL} brand is healthy, with sentiment on par with peers; the friction we can see is in the MyACUVUE app." if healthy
                          else f"The MyACUVUE app is the most visible friction to registering; the brand's own sentiment needs a look ({bm['verdict']}).") if app_ok
                         else f"We find no evidence that the {FOCAL} brand is what stops people registering.")
        same = "not measurably different from peers" if bm["verdict"] == "level with peers" else bm["verdict"]
        detail.append(f"Net sentiment {ebi.sgn(g['net_f'])} vs {ebi.sgn(g['net_p'])} for peers ({same}; gap {ebi.pts(g['gap'])}, range {ebi.sgn(g['lo'])} to {ebi.sgn(g['hi'])}).")
        out["badges"].append((f"Sentiment gap: {'no measurable gap' if bm['verdict'] == 'level with peers' else bm['verdict']}", "gray"))
    else:
        out["bottom"] = "The scraped data cannot yet separate Acuvue from its peers."
        out["badges"].append(("Sentiment gap: not readable", "gray"))
    if app_ok:
        detail.append(f"App: {last['neg']:.0f}% of {int(last['n'])} written reviews in {last['era']} negative (directional).")
        out["badges"].append((f"App: directional, n={int(last['n'])}", "orange"))
    out["detail"] = " ".join(detail)
    new, slide = [], []
    cg = bm["channels"]
    clear = cg[cg["ok"] & cg["lo"].notna() & ((cg["lo"] > 0) | (cg["hi"] < 0))] if len(cg) else cg
    if len(clear):
        r = clear.assign(_n=clear[["n_f", "n_p"]].min(axis=1), _a=clear["gap"].abs()).sort_values(["_n", "_a"], ascending=False).iloc[0]   # the gap with the most items behind it
        new.append((f"{FOCAL} {'trails' if r.gap < 0 else 'leads'} peers on **{r.channel}** by {ebi.pts(r.gap)}; the peers there are {r.peer_top_share:.0f}% {r.peer_top}",
                    "New", f"n={r.n_f} vs {r.n_p} items", "Brand Health > Acuvue by channel", "B · one channel"))
        slide.append((f"{ebi.pts(r.gap)}", f"{FOCAL} vs peers on {r.channel}", "New", f"n={r.n_f} vs {r.n_p}"))
    m = vd.maps(d)
    if len(m) >= ebi.MIN_N:
        acu = int(m["text"].str.contains("acuvue", case=False, na=False).sum())
        pos = (m["sentiment"] == "positive").mean() * 100
        new.append((f"Shoppers praise the shops ({pos:.0f}% positive) but only **{acu} of {len(m)}** store reviews name {FOCAL}: the brand is invisible where lenses are fitted",
                    "New", f"n={len(m)} contact-lens store reviews; skews positive", "Retail & Promotions", "Directional"))
        slide.append((f"{acu} of {len(m)}", f"store reviews name {FOCAL}", "New", f"{pos:.0f}% of reviews positive"))
    if tf and mf and tf["idx_chg"] > 0 > mf["units"]:
        new.append((f"Search interest in {FOCAL} is **{ebi.pct(tf['idx_chg'])}** while category imports fell {abs(mf['units']):.0f}% in units ({mf['first']} to {mf['last']}): interest has not fallen with imports",
                    "New", f"Google Trends index, {tf['weeks']} weeks; UN Comtrade HS 9001.30", "Trends & Demand > Demand Signals", "Directional"))
        slide.append((ebi.pct(tf['idx_chg']), f"search interest, while imports fell {abs(mf['units']):.0f}%", "New", f"{tf['weeks']} weeks of Google Trends"))
    if app_ok:
        new.append((f"The app is the most visible friction: **{last['neg']:.0f}%** of written reviews negative in {last['era']}",
                    "Confirms", f"n={int(last['n'])} written reviews, Acuvue only; matches desk-research hypothesis 1", "Journey & App > App", "Directional"))
        slide.append((f"{last['neg']:.0f}%", "of app reviews negative", "Confirms", f"n={int(last['n'])}, {last['era']}"))
    out["new"] = new
    out["slide"] = slide

    wa = _wa_table(d)
    out["bars"] = [dict(barrier=r["Barrier"], stage=r["Send at stage"], items=int(r["Acuvue items"]), app=int(r["of which app"]), can=r["WhatsApp can help"])
                   for _, r in wa.head(6).iterrows()] if len(wa) else []
    out["send"] = [(r["Barrier"], f"Send at {r['Send at stage']} · {int(r['Acuvue items'])} Acuvue items", r["Message angle"])
                   for _, r in wa[wa["WhatsApp can help"] == "Directly"].head(3).iterrows()] if len(wa) else []

    j = bp.get("journey") or {}
    if j.get("own_top") == "Repeat/Retention":
        out["stage_line"] = (f"{FOCAL} consumers' own complaints peak at **Repeat/Retention** ({j['own_top_n']} of {j['own_staged']} that name a stage): "
                             "test a lens-care and reorder message there.")
        out["stage_line"] = out["stage_line"].replace("**", "")
    return out


def _help_chart(bars: list, stacked: bool, key: str) -> None:
    """Acuvue complaint items per barrier, one bar each, in the WhatsApp map's priority order. Executive read: coloured by how directly a message can help.
    Key findings: split into app reviews and consumer comments."""
    if not bars:
        return
    y = [f"{b['barrier']} · {b['stage']}" for b in bars]
    fig = go.Figure()
    if stacked:
        fig.add_bar(y=y, x=[b["items"] - b["app"] for b in bars], orientation="h", name="Consumer comments", marker_color="#178197")
        fig.add_bar(y=y, x=[b["app"] for b in bars], orientation="h", name="App reviews", marker_color="#7048E8")
        fig.update_layout(barmode="stack", legend=dict(orientation="h", y=-0.2, title_text=""))
        say = f"{bars[0]['barrier']} draws the most Acuvue complaints ({bars[0]['items']}); {sum(b['app'] for b in bars)} of the {sum(b['items'] for b in bars)} shown come from the app."
    else:
        colour = {"Directly": "#168012", "Partly": "#B7791F", "Not really": "#94A3B8"}
        fig.add_bar(y=y, x=[b["items"] for b in bars], orientation="h", marker_color=[colour.get(b["can"], "#94A3B8") for b in bars],
                    text=[f"{b['items']}  ·  helps {b['can'].lower()}" for b in bars], textposition="outside", cliponaxis=False)
        fig.update_layout(xaxis=dict(range=[0, max(b["items"] for b in bars) * 1.6]), showlegend=False)
        n_dir = sum(b["can"] == "Directly" for b in bars)
        say = f"{n_dir} of the top {len(bars)} barriers can be answered directly in WhatsApp (green); the rest only partly (amber)."
    fig.update_yaxes(autorange="reversed", title=None)
    fig.update_xaxes(title="Acuvue complaint items")
    fig.update_layout(height=90 + 46 * len(bars), margin=dict(r=20))
    ui.plot(fig, say, "dir", "", key=key,
            bases=sum(b["items"] for b in bars), noun="Acuvue complaint items")


def _exec_data() -> dict:
    return _exec(vd.VOICE_DB.stat().st_mtime, vd.TAG_DB.stat().st_mtime, Path(__file__).stat().st_mtime) if vd.available() else {}


def exec_read() -> None:
    """The Executive read, shown above every tab: bottom line, what is new, what to send, and how sure we are."""
    e = _exec_data()
    if not e:
        return
    with st.expander("Executive read: the answer, what is new, what to send", expanded=False):
        st.markdown(f"### {e['bottom']}")
        if e.get("detail"):
            st.caption(e["detail"])
        if e.get("slide"):
            tone = {"New": ("#0B6B7C", "#E6F2F4"), "Confirms": ("#64748B", "#EEF2F6")}
            cards = "".join(
                f"<div style='flex:1;min-width:190px;border-left:4px solid {tone[t][0]};background:{tone[t][1]};border-radius:8px;padding:12px 16px'>"
                f"<div style='font-size:2.1rem;font-weight:800;line-height:1.1;color:#051F4A'>{big}</div>"
                f"<div style='font-size:1rem;color:#191919;margin-top:2px'>{label}</div>"
                f"<div style='font-size:.75rem;color:#64748B;margin-top:6px'><b style='color:{tone[t][0]};text-transform:uppercase;letter-spacing:.06em'>{ui.TAG_LABEL.get(t, t)}</b> · {base}</div></div>"
                for big, label, t, base in e["slide"])
            st.markdown(f"<div style='display:flex;flex-wrap:wrap;gap:12px;margin:8px 0 4px'>{cards}</div>", unsafe_allow_html=True)
            st.caption(ui.TAG_LEGEND)
        if e["send"]:
            st.markdown("**Send first** (needs J&J legal and PDPA review)")
            st.markdown("\n".join(f"- **{bar}** ({ev.split(' · ')[0].replace('Send at ', 'at ')}): {re.split(r': |, and |, with ', msg)[0]}" for bar, ev, msg in e["send"]))
        if e.get("stage_line"):
            st.caption(e["stage_line"])
        if e.get("handoff"):
            st.markdown(e["handoff"])
            ui.goto("Brand Health", "See the product complaints on Brand Health", key="exec_to_health")


def render(d: pd.DataFrame, products_all: pd.DataFrame) -> None:
    if d.empty:
        st.info("Run Scripts/build_voice_items.py and Scripts/tag_voice_items.py to build the tables this page reads.")
        return
    bm, bp = brand_market_page.facts(d), barriers_page.facts(d)
    tf, mf = trends_signals.facts(), market_competitors.trade_facts()

    st.caption("The bottom line is in the Executive read above the tabs. This page shows how sure we are of each finding and how a barrier becomes a message to test.")
    ui.section("How sure we are of each finding", "Net sentiment = % positive minus % negative (−100 to +100). A gap in pts = Acuvue net minus peers net. Fact = counted; Directional = small or skewed sample; No gap, B, A = strength of a brand gap. "
               "Learning / Validated = against the hypotheses in context.md and the desk research.", "Evidence", kind="fact")
    ev = _evidence_rows(bm, bp, tf, mf, d)
    ui.evidence_list(list(ev.itertuples(index=False, name=None)))
    _open_pages(ev["Where"])

    wa = _wa_table(d)
    if len(wa):
        ui.section("From barrier to message: what to test first",
                   "Ranked by Acuvue complaint items, weighted by how directly WhatsApp can help.",
                   "Lever", kind="dir")
        _help_chart([dict(barrier=r["Barrier"], stage=r["Send at stage"], items=int(r["Acuvue items"]), app=int(r["of which app"]), can=r["WhatsApp can help"])
                     for _, r in wa.head(6).iterrows()], True, "kf_bars")
        ui.flow_rows([(f"{r['Priority']}. {r['Barrier']} · {r['Send at stage']}", f"{int(r['Acuvue items'])} Acuvue items ({r['Acuvue share']}) · WhatsApp can help: {r['WhatsApp can help'].lower()}",
                       r["What to test"]) for _, r in wa.head(6).iterrows()],
                     ("Barrier and stage", "What we see", "Test"))
        ui.goto("Journey & App", "See the draft messages", key="ans_to_msg")

    overview_pages.render_cards([c for c in summary_facts.build(d, products_all) if c["where"] not in _IN_STRIP], "Supporting facts")

    with st.expander("Which tab answers my question?", expanded=False):
        for i, (q, targets) in enumerate(_WHERE):
            cq, cb = st.columns([3, 2], vertical_alignment="center")
            cq.markdown(q)
            with cb:
                for j, (label, tab, section) in enumerate(targets):
                    ui.goto(tab, label, key=f"ans_route_{i}_{j}", section=section)
