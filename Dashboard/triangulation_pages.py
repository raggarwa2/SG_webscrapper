"""
Triangulation story page: does each finding survive a check against an independent source?
Three kinds of source are set against each other: scraped consumer data (what the dashboard counts), desk research
(analysis/*.md) and channel evidence (Prompt A coverage). Sections: channel coverage, barrier match, hypothesis check,
and the per-brand summary when Prompt D has run.

Files come from Scripts/output/triangulation_sg/ (python triangulation_sg/run_triangulation.py). A missing file never
raises: the section says "Not run yet" and names the command. The barrier view is built from the shared labels: the complaint
items (negative or mixed) of the brand pool on Brand & market, so its base reconciles with that page. The separate Prompt B
comment base and the Prompt D per-brand prose are no longer shown.
"""

import html
import os
import re
from datetime import datetime

import pandas as pd
import plotly.graph_objects as go
import streamlit as st

import barrier_taxonomy
import charts
import ebi
import insights
import journey_barriers
import ui
import voice_data as vd
from sg_common import DASH_DIR, DB_DIR

TRI_DIR = os.path.join(DB_DIR, "triangulation_sg")
ANALYSIS_DIR = os.path.normpath(os.path.join(DASH_DIR, "..", "analysis"))
RUN_CMD = "python triangulation_sg/run_triangulation.py --prompt {p}"
TEAL = "#178197"        # the dashboard's own accent (Journey coverage dots)
GREY = "#B8C2CC"        # peers / not-covered grey used by charts.gap_bars

# The 10 SG-framework barriers (Scripts/triangulation_sg/mappings.BARRIERS), in framework order:
# (start of the Prompt B barrier text, display label, label in barrier_taxonomy.KEYWORDS,
#  row of the cross-segment table in analysis/4_category_user_barrier_framework.md that carries its confidence).
FRAMEWORK = [
    ("price and channel cost", "Price & channel cost", "Price & channel cost", "Total cost versus other channels"),
    ("loyalty rules limit value", "Loyalty rules limit value", "Loyalty & rewards", "Purchases outside participating stores"),
    ("rewards unreliable", "Rewards unreliable or cut", "Loyalty & rewards", "Store-binding and points freezing"),
    ("registration or login friction", "Registration / login friction", "Registration / login friction", "OTP, login and update failures"),
    ("app low utility", "App low utility", "App utility & support", "Low perceived app value"),
    ("unwanted messaging", "Messaging / privacy concern", "Unwanted messaging / privacy", ""),
    ("prefers whatsapp", "WhatsApp chat / support gap", "App utility & support", ""),
    ("product experience", "Product experience", "Product experience", "Discomfort and dryness"),
    ("fear or handling", "Fear / handling difficulty", "Fear / handling difficulty", "Fear of touching the eye and handling"),
    ("lack of professional guidance", "Lack of professional guidance", "Lack of professional guidance", "No professional prompt"),
]
# Prompt B sources as named on the dashboard. The last two are read for the source map only: app reviews are ACUVUE-only
# and Google Maps reviews are about shops, so (like Journey & barriers) they stay out of the brand comparison.
SRC_NAMES = {"review": "Lazada reviews", "kiasuparents_forum": "KiasuParents", "xhs_post": "Xiaohongshu", "reddit_comment": "Reddit",
             "youtube_comment": "YouTube", "instagram_comment": "Instagram", "facebook_comment": "Facebook",
             "app_review": "MyACUVUE app reviews", "gmaps_review": "Google Maps shop reviews"}
OWNED = ("app_review", "gmaps_review")
OWNED_COLORS = {"app_review": "#E8A33D", "gmaps_review": charts.MUTED}   # the app orange used on Journey; grey for shops
OFF_FRAMEWORK = ["Colour & look (cosmetic lenses)", "Availability & where to buy", "Authenticity & quality control"]


# ---------------------------------------------------------------------------
# Loaders: every one degrades to None instead of raising
# ---------------------------------------------------------------------------

@st.cache_data(show_spinner=False)
def _read_csv(path: str, mtime: float) -> pd.DataFrame:
    return pd.read_csv(path)


@st.cache_data(show_spinner=False)
def _read_text(path: str, mtime: float) -> str:
    with open(path, encoding="utf-8-sig") as fh:
        return fh.read()


def _path(name: str, folder: str = TRI_DIR) -> str | None:
    p = os.path.join(folder, name)
    return p if os.path.exists(p) else None


def load_csv(name: str) -> pd.DataFrame | None:
    p = _path(name)
    if not p:
        return None
    try:
        return _read_csv(p, os.path.getmtime(p))
    except Exception:
        return None


def load_text(name: str, folder: str = TRI_DIR) -> str | None:
    p = _path(name, folder)
    if not p:
        return None
    try:
        return _read_text(p, os.path.getmtime(p))
    except Exception:
        return None


def _stamp(name: str) -> str:
    p = _path(name)
    return datetime.fromtimestamp(os.path.getmtime(p)).strftime("%d %b %Y") if p else ""


def not_run(prompt: str) -> None:
    st.info(f"Not run yet: run {RUN_CMD.format(p=prompt)} (from the Scripts folder).")


# ---------------------------------------------------------------------------
# Desk research: hypothesis table and barrier-framework confidence
# ---------------------------------------------------------------------------

_ID = re.compile(r"\bR(\d)-([CS])-?(\d+)\b|\b([CS])-?(\d+)\b|\bto\b")


def _desk_ids(cell: str) -> set:
    """Desk-research claim (C) and source (S) ids in a Source IDs cell, ranges ("C-04 to C-15") expanded."""
    ids, run, prev, rng = set(), None, None, False
    for m in _ID.finditer(cell):
        if m.group(0) == "to":
            rng = True
            continue
        if m.group(1):
            run, kind, num = m.group(1), m.group(2), int(m.group(3))
        else:
            kind, num = m.group(4), int(m.group(5))
        if run is None:
            continue
        nums = range(prev[1] + 1, num + 1) if rng and prev and prev[0] == kind and num > prev[1] else [num]
        ids.update((run, kind, x) for x in nums)
        prev, rng = (kind, num), False
    return ids


def _cells(line: str) -> list:
    return [c.strip() for c in line.strip().strip("|").split("|")]


def hypotheses() -> pd.DataFrame | None:
    """One row per hypothesis in analysis/3_hypothesis_table.md; every count is read from the table, none typed here."""
    txt = load_text("3_hypothesis_table.md", ANALYSIS_DIR)
    if not txt:
        return None
    rows = []
    for line in txt.splitlines():
        if not re.match(r"\|\s*\*\*H\d", line):
            continue
        c = [x.replace("**", "") for x in _cells(line)]
        if len(c) < 8:
            continue
        ids = _desk_ids(c[6])
        rows.append({
            "id": c[0], "claim": c[1], "verdict": c[2], "confidence": c[3],
            "desk_claims": sum(1 for _, k, _ in ids if k == "C"), "desk_sources": sum(1 for _, k, _ in ids if k == "S"),
            "scraped": sorted(set(re.findall(r"SC-[A-Z]+(?:-[A-Z]+)*", c[6]))), "tested_less": c[7],
        })
    return pd.DataFrame(rows) if rows else None


def framework_confidence() -> dict:
    """Confidence the desk research gives each barrier: the cross-segment table in analysis/4_category_user_barrier_framework.md."""
    txt = load_text("4_category_user_barrier_framework.md", ANALYSIS_DIR) or ""
    out, on = {}, False
    for line in txt.splitlines():
        if line.startswith("## Cross-segment barrier summary"):
            on = True
        elif on and line.startswith("## "):
            break
        elif on and line.startswith("|") and not line.startswith("|---") and "Barrier" not in line.split("|")[1]:
            c = _cells(line)
            if len(c) >= 4:
                out[c[0]] = c[3]
    return out


# ---------------------------------------------------------------------------
# Section 1: channel coverage (Prompt A)
# ---------------------------------------------------------------------------

def _channels(cc: pd.DataFrame) -> pd.DataFrame:
    d = cc.copy()
    d["products"] = pd.to_numeric(d["product_count"], errors="coerce").fillna(0).astype(int)
    d["reviews"] = pd.to_numeric(d["review_count"], errors="coerce").fillna(0).astype(int)
    d["items"] = d["products"] + d["reviews"]
    d["covered"] = d["items"] > 0
    d["online"] = d["online_channel"].astype(str).str.lower().isin(["true", "1", "yes"])
    return d


def _channel_chart(d: pd.DataFrame) -> go.Figure:
    labels = [charts.row_label(r.taxonomy_category, int(r.items), note="no data collected") for r in d.itertuples()]
    fig = go.Figure(go.Bar(
        y=labels, x=d["items"], orientation="h",
        marker=dict(color=[TEAL if c else GREY for c in d["covered"]]),
        text=[f"{n:,}" if n else charts.NO_DATA for n in d["items"]], textposition="outside", cliponaxis=False,
        customdata=d[["products", "reviews"]],
        hovertemplate="%{y}<br>%{customdata[0]:,} product listings · %{customdata[1]:,} reviews<extra></extra>",
    ))
    fig.update_layout(height=max(360, 46 * len(d) + 60), showlegend=False,
                      xaxis=dict(title="Items collected (listings + reviews)", range=[0, max(int(d["items"].max()), 1) * 1.3]),
                      yaxis=dict(autorange="reversed", title=None))
    return fig


def _channel_section(cc: pd.DataFrame | None) -> None:
    if cc is None or cc.empty:
        ui.section("Channel coverage is not available yet", "Which channels we scrape against where brands are sold.", "1 · Evidence base", kind="fact")
        not_run("a")
        return
    d = _channels(cc)
    gaps = d[d["online"] & ~d["covered"]]
    off = d[~d["online"] & ~d["covered"]]
    ui.section(f"{int(d['covered'].sum())} of {len(d)} retail channels carry scraped data; "
               f"{len(gaps)} online channels have none",
               "Which channels we scrape. Teal = data collected; grey = none.", "1 · Evidence base", kind="fact")
    n_prod, n_rev = int(d["products"].sum()), int(d["reviews"].sum())
    ui.plot(_channel_chart(d),
            f"No data from {_join(gaps['taxonomy_category'])}." if len(gaps) else "Every online channel has some coverage.",
            note="Optical chains and independent opticians are Google Maps reviews of the shops, not product listings. "
                 "The MyACUVUE app is app-store reviews. Under 15 items is directional.",
            bases={"Product listings": n_prod, "Reviews": n_rev}, noun="collected items", key="tri_channels")
    if _has_evidence(d):
        st.caption("Channels with research evidence of where brands are sold are marked in the table below.")
    else:
        st.warning("**Not scraped is not the same as not present.** We hold no evidence of where each brand is sold in Singapore "
                   "(no distribution or retailer list was supplied), so these gaps cannot be read as brands being absent. "
                   + (f"Offline and clinic channels ({_join(off['taxonomy_category'])}) are out of reach for a scraper." if len(off) else ""))
    with st.expander("Channel table", expanded=False):
        show = d[["taxonomy_category", "products", "reviews", "notes"]].rename(columns={
            "taxonomy_category": "Channel", "products": "Product listings", "reviews": "Reviews", "notes": "What we hold"})
        for col in ("Product listings", "Reviews"):
            show[col] = show[col].map(lambda n: f"{n:,}" if n else charts.NO_DATA)
        st.dataframe(show, hide_index=True, width="stretch")


def _has_evidence(d: pd.DataFrame) -> bool:
    """True when the coverage file carries research evidence of where brands are sold."""
    return "research_evidence" in d.columns and d["research_evidence"].fillna("").astype(str).str.strip().ne("").any()


def _join(names) -> str:
    names = [str(n) for n in names]
    return names[0] if len(names) == 1 else ", ".join(names[:-1]) + " and " + names[-1] if names else "none"


# ---------------------------------------------------------------------------
# Section 2: barrier match (Prompt B vs Journey labels vs framework)
# ---------------------------------------------------------------------------

def _state(k: int) -> str:
    """Seen = insights.MIN_SOURCE_N or more comments, trace = fewer, none = no match."""
    return "clear" if k >= insights.MIN_SOURCE_N else ("faint" if k > 0 else "none")


def _read_of(llm: str | None, kw: str) -> str:
    states = {llm, kw} - {None}
    if llm == "clear" and kw == "clear":
        return "Confirmed by both"
    if llm is None:
        return {"clear": "Seen in flags", "faint": "Trace in flags", "none": "Not seen"}[kw]
    if "clear" in states:
        return "One method only"
    return "Trace in both" if "faint" in states else "Not seen"


def _keyword_counts(d: pd.DataFrame, brands: list) -> tuple:
    """(count per barrier label, n complaint items): the brand pool's negative or mixed items, labelled by barrier_taxonomy.classify
    (the 12 shared labels). The same complaint definition as Brand & market and Barriers & journey."""
    p = vd.pool(d)
    flagged = p[p["brand_std"].isin(brands) & p["sentiment"].isin(["negative", "mixed"])]
    if flagged.empty:
        return pd.Series(dtype=int), 0
    ex = flagged["text"].map(barrier_taxonomy.classify).explode()
    return ex.value_counts(), len(flagged)


def _llm_counts(bm: pd.DataFrame) -> list:
    """Prompt B matches per framework barrier (all brands pooled)."""
    out = []
    for start, *_ in FRAMEWORK:
        m = bm[bm["barrier"].str.lower().str.startswith(start)]
        out.append(int(m["match_count"].sum()))
    return out


def _conf_for(conf: dict, row: str) -> str:
    """Confidence for a cross-segment row, matched on the start of its name (the table adds qualifiers in brackets)."""
    return next((v for k, v in conf.items() if row and k.startswith(row)), "")


def _owned_counts(src: pd.DataFrame | None) -> list:
    """Prompt B matches per framework barrier in the app and Google Maps reviews."""
    out = []
    for start, *_ in FRAMEWORK:
        if src is None or src.empty:
            out.append(0)
            continue
        m = src[src["source"].isin(OWNED) & src["barrier"].str.lower().str.startswith(start)]
        out.append(int(m["match_count"].sum()))
    return out


def barrier_rows(bm: pd.DataFrame | None, kw: pd.Series, n_flagged: int, src: pd.DataFrame | None = None) -> pd.DataFrame:
    conf = framework_confidence()
    llm = _llm_counts(bm) if bm is not None and not bm.empty else [None] * len(FRAMEWORK)
    owned = _owned_counts(src)
    rows = []
    for i, ((start, label, kw_type, conf_row), k_llm, k_own) in enumerate(zip(FRAMEWORK, llm, owned), start=1):
        k_kw = int(kw.get(kw_type, 0))
        k_all = None if k_llm is None else k_llm + k_own      # the model read: public comments plus app and shop reviews
        rows.append({"n": i, "label": label, "kw_type": kw_type, "conf": _conf_for(conf, conf_row),
                     "llm": k_llm, "owned": k_own, "kw": k_kw,
                     "read": _read_of(_state(k_all) if k_all is not None else None, _state(k_kw)),
                     "shared": kw_type in {r[2] for r in FRAMEWORK if r[1] != label}})
    return pd.DataFrame(rows)


def _barrier_bars(rows: pd.DataFrame, col: str, base: int) -> go.Figure:
    k = rows[col].astype(int)
    pct = k / base * 100 if base >= ebi.MIN_N else None
    fig = go.Figure(go.Bar(
        y=rows["label"], x=pct if pct is not None else k, orientation="h", marker_color=TEAL,
        text=[f"{n} ({p:.0f}%)" if pct is not None else f"{n}" for n, p in zip(k, pct if pct is not None else k)],
        textposition="outside", cliponaxis=False,
        customdata=k, hovertemplate="%{y}<br>%{customdata} comments<extra></extra>",
    ))
    top = float((pct if pct is not None else k).max() or 1)
    fig.update_layout(height=max(340, 40 * len(rows) + 60), showlegend=False,
                      xaxis=dict(range=[0, top * 1.3], ticksuffix="%" if pct is not None else "",
                                 title="Share of comments read" if pct is not None else "Comments matched"),
                      yaxis=dict(autorange="reversed", title=None))
    return fig


def _brand_bubbles(bm: pd.DataFrame, base: pd.DataFrame | None, brands: list, order: list) -> tuple | None:
    """Brand x barrier bubble map from Prompt B, drawn by the same function as the Journey bubble chart."""
    start_to_label = {s: lab for s, lab, *_ in FRAMEWORK}

    def short(b):
        low = str(b).lower()
        return next((lab for s, lab in start_to_label.items() if low.startswith(s)), None)

    d = bm[bm["brand"].isin(brands)].assign(reason=lambda x: x["barrier"].map(short)).dropna(subset=["reason"])
    if d.empty or base is None:
        return None
    ex = d.loc[d.index.repeat(d["match_count"].astype(int))][["brand", "reason"]]
    n_brand = base.groupby("brand")["items"].sum().reindex(brands, fill_value=0)
    focus = insights.FOCAL if insights.FOCAL in brands else brands[0]
    return journey_barriers._bubbles(ex, brands, order, n_brand, focus), {b: int(n_brand[b]) for b in brands}


def _source_map(src: pd.DataFrame, base: pd.DataFrame, rows: pd.DataFrame) -> tuple | None:
    """Barrier x source bubble map: where each framework barrier is voiced. Bubble area = share of that source's items;
    the number inside = items. A source under ebi.MIN_N items is drawn hollow (counts only)."""
    n_src = base.groupby("source")["items"].sum()
    cols = [c for c in SRC_NAMES if n_src.get(c, 0) > 0]
    if not cols or src.empty:
        return None
    start = {lab: st_ for st_, lab, *_ in FRAMEWORK}
    recs = []
    for r in rows.itertuples():
        for c in cols:
            hit = src[(src["source"] == c) & src["barrier"].str.lower().str.startswith(start[r.label])]
            recs.append({"barrier": r.label, "source": c, "k": int(hit["match_count"].sum())})
    k = pd.DataFrame(recs)
    k["share"] = k["k"] / k["source"].map(n_src) * 100
    xlab = {c: charts.row_label(SRC_NAMES[c], int(n_src[c])) for c in cols}
    top = float(k["share"].max() or 1)
    fig = go.Figure()
    for c in cols:
        d = k[(k["source"] == c) & (k["k"] > 0)]
        col = OWNED_COLORS.get(c) or charts.SOURCE_COLORS.get(SRC_NAMES[c], TEAL)
        thin = ebi.is_thin(int(n_src[c]))
        marker = (dict(size=26, color="rgba(255,255,255,0)", line=dict(width=2, color=col)) if thin else
                  dict(size=d["share"], sizemode="area", sizeref=2 * top / (46 ** 2), sizemin=14, color=col, opacity=0.85, line=dict(width=0)))
        fig.add_trace(go.Scatter(
            x=[xlab[c]] * len(d), y=d["barrier"], mode="markers+text", text=d["k"], textposition="middle center",
            textfont=dict(color="#334155" if thin else "white", size=12), marker=marker, showlegend=False,
            customdata=d[["k", "share"]], name=SRC_NAMES[c],
            hovertemplate=SRC_NAMES[c] + "<br>%{y}<br>%{customdata[0]} items" + ("" if thin else " (%{customdata[1]:.0f}% of source)") + "<extra></extra>"))
    grid = dict(showgrid=True, gridcolor="rgba(128,128,128,0.15)", automargin=True, tickfont=dict(size=12))
    fig.update_xaxes(categoryorder="array", categoryarray=[xlab[c] for c in cols], side="top", title=None, **grid)
    fig.update_yaxes(categoryorder="array", categoryarray=[r.label for r in rows.itertuples()][::-1], title=None, **grid)
    fig.update_layout(height=max(380, 44 * len(rows) + 130))
    # barriers voiced mostly in the app or shop reviews rather than in public comments
    big = k[k["source"].map(n_src) >= ebi.MIN_N]
    lead = big[big["k"] > 0].sort_values("share", ascending=False).drop_duplicates("barrier")
    owned_led = lead[lead["source"].isin(OWNED)]["barrier"].tolist()
    say = (f"{len(owned_led)} of {len(rows)} framework barriers are voiced mostly in app or shop reviews, not in public comments: "
           f"{_join(owned_led)}." if owned_led else "No framework barrier is voiced mainly in the app or shop reviews.")
    return fig, say, {SRC_NAMES[c]: int(n_src[c]) for c in cols}


def _themes_off_list() -> pd.DataFrame | None:
    txt = load_text("prompt_b_barrier_matches.md")
    if not txt or "divergences" not in txt:
        return None
    rows = []
    for line in txt.split("divergences", 1)[1].splitlines():
        if line.startswith("|") and not line.startswith("|---") and "Theme" not in line:
            c = _cells(line)
            if len(c) >= 2 and c[1].isdigit():
                rows.append({"Theme": c[0], "Mentions": int(c[1])})
    return pd.DataFrame(rows) if rows else None


def _barrier_section(rows: pd.DataFrame, bm, base, kw: pd.Series, n_flagged: int, brands: list, src=None) -> None:
    have_llm = bm is not None and not bm.empty
    n_both = int((rows["read"] == "Confirmed by both").sum())
    n_seen = int(rows["read"].isin(["Confirmed by both", "One method only", "Seen in flags"]).sum())
    if have_llm:
        title = (f"{n_both} of 10 framework barriers are confirmed by both methods; "
                 f"{int((rows['read'] == 'Not seen').sum())} are not seen")
    else:
        title = f"{n_seen} of 10 framework barriers appear in complaint items (shared labels)"
    ui.section(title, "The 10 barriers from the desk-research framework, set against what scraped comments say.", "2 · Barrier", kind="fact")

    if not have_llm:
        st.caption("Read on the shared labels: the brand pool's negative or mixed items, sorted into the framework's barrier types "
                   "(model tags where tagged, keywords otherwise). Directional.")

    if have_llm:
        pub = base[~base["source"].isin(OWNED)] if base is not None else None
        n_read = int(pub["items"].sum()) if pub is not None else 0
        top = rows.sort_values("llm", ascending=False).iloc[0]
        ui.plot(_barrier_bars(rows, "llm", n_read), f"{top['label']} is the most common framework barrier in scraped comments.",
                note="A comment can carry several barriers. Matched by a language model (Prompt B) on public comments: Lazada reviews, "
                     "KiasuParents, Xiaohongshu, Reddit, YouTube, Instagram and Facebook. App and shop reviews are in the map below.",
                bases=n_read if n_read else f"Comment base not recorded: rerun {RUN_CMD.format(p='b')}",
                noun="comments read by the model", key="tri_barrier_llm")
        order = [r.label for r in rows.itertuples()]
        built = _brand_bubbles(bm, pub, brands, order)
        if built:
            fig, n_brand = built
            ui.plot(fig, "Brand by barrier, as matched by the model.", key="tri_barrier_bubbles",
                    note=f"Bubble = share of the brand's comments read; number = comments. Hollow = under {ebi.MIN_N} comments (counts only). "
                         "Comments that name no tracked brand are left out here but counted in the bars above.",
                    bases=n_brand, noun="comments read")
        smap = _source_map(src, base, rows) if src is not None and base is not None else None
        if smap:
            fig, say, n_by_src = smap
            ui.plot(fig, say, key="tri_barrier_sources",
                    note=f"Bubble = share of that source's items; number = items. Hollow = under {ebi.MIN_N} items (counts only). "
                         "Orange = MyACUVUE app reviews (ACUVUE only); grey = Google Maps reviews of optical shops (lens-related or friction). "
                         "Neither is in the brand comparison above.",
                    bases=n_by_src, noun="items read")
        elif src is None:
            not_run("b")
    else:
        top = rows.sort_values("kw", ascending=False).iloc[0]
        ui.plot(_barrier_bars(rows, "kw", n_flagged), f"{top['label']} is the most common framework barrier in complaint items." if top["kw"] else "No complaint item matches a framework barrier.",
                note="The brand pool's negative or mixed items (the same complaint definition as Brand & market). An item can carry several barriers.",
                bases=n_flagged, noun="complaint items", key="tri_barrier_kw")

    # Side-by-side table: the triangulation itself
    show = pd.DataFrame({
        "Framework barrier": [f"{r.n} · {r.label}" for r in rows.itertuples()],
        "Desk-research confidence": [r.conf or "Not rated in the framework" for r in rows.itertuples()],
    })
    if have_llm:
        n_pub = int(base[~base["source"].isin(OWNED)]["items"].sum()) if base is not None else None
        n_own = int(base[base["source"].isin(OWNED)]["items"].sum()) if base is not None else None
        nm = lambda k, n: f"{k:,}" if k else (f"No matches (of {n:,})" if n is not None else "No matches")
        show["Model matches: public comments"] = [nm(r.llm, n_pub) for r in rows.itertuples()]
        if src is not None:
            show["Model matches: app and shop reviews"] = [nm(r.owned, n_own) for r in rows.itertuples()]
    show["Shared labels (complaint items)"] = [
        (f"{r.kw:,}" if r.kw else f"No matches (of {n_flagged:,})") + (" (type shared with another barrier)" if r.shared and r.kw else "")
        for r in rows.itertuples()]
    show["Read"] = rows["read"].values
    st.dataframe(show, hide_index=True, width="stretch")
    st.caption(f"Seen = {insights.MIN_SOURCE_N}+ comments; trace = 1 to {insights.MIN_SOURCE_N - 1}; none = no match. Loyalty rules and rewards share one label, "
               "as do app low utility and the WhatsApp gap, so their counts repeat.")

    off = pd.DataFrame({"Type the framework does not list": OFF_FRAMEWORK,
                        "Shared labels (complaint items)": [f"{int(kw.get(t, 0)):,}" if int(kw.get(t, 0)) else f"No matches (of {n_flagged:,})" for t in OFF_FRAMEWORK]})
    themes = _themes_off_list()
    with st.expander("What scraped comments say that the framework does not list", expanded=False):
        st.dataframe(off, hide_index=True, width="stretch")
        if themes is not None:
            st.dataframe(themes.sort_values("Mentions", ascending=False).head(12), hide_index=True, width="stretch")
            st.caption(f"The 12 most frequent of {len(themes)} themes the model found outside the 10 barriers (Prompt B), by number of comments. "
                       "Most are delivery and packaging praise, not purchase barriers.")


# ---------------------------------------------------------------------------
# Section 3: hypothesis check
# ---------------------------------------------------------------------------

_VERDICT = {"supported": "Supported", "mixed": "Mixed", "insufficient evidence": "Insufficient evidence"}


_HEADLINE = {
    "H1": "J&J holds ~36% of the market", "H2": "Revenue up, volume flat or down", "H3": "Bulk deals work against registration",
    "H4": "App friction drives drop-off", "H5a": "Marketplace coupons undercut value", "H5b": "Cheap lenses are an entry funnel",
    "H5c": "Olens out-promotes J&J online",
}


def _headline(hid: str, claim: str = "") -> str:
    """Short name for a hypothesis; falls back to its claim from the table when a new one is added."""
    return _HEADLINE.get(hid) or claim


def _live_check(hid: str, d: pd.DataFrame) -> str:
    """The one number this dashboard can put against a hypothesis, read live; otherwise says it cannot."""
    if hid == "H4":
        a = vd.app(d)
        if len(a):
            return f"{int((a['sentiment'] == 'negative').sum())} of {len(a)} MyACUVUE app reviews are negative (Barriers & journey)."
    if hid == "H5c":
        p = vd.pool(d)
        y = p[p["source"] == "YouTube"]
        if len(y) and (y["brand_std"] == "Olens").any():
            k, n = int((y["brand_std"] == "Olens").sum()), len(y)
            share = f"{k / n * 100:.0f}% of" if n >= ebi.MIN_N else f"{k} of"
            return f"Olens holds {share} {n:,} analysed YouTube comments: attention, not marketplace promotion."
    return "Not testable with scraped data."


def _hyp_chart(h: pd.DataFrame) -> go.Figure:
    labels = [f"{_headline(r.id, r.claim)}<br>{_VERDICT.get(r.verdict.lower(), r.verdict)}" for r in h.itertuples()]
    fig = go.Figure()
    fig.add_trace(go.Bar(y=labels, x=h["desk_claims"], name="Desk-research claims", orientation="h", marker_color=GREY,
                         text=h["desk_claims"], textposition="outside", cliponaxis=False))
    fig.add_trace(go.Bar(y=labels, x=h["scraped"].map(len), name="Scraped sources", orientation="h", marker_color=TEAL,
                         text=h["scraped"].map(len), textposition="outside", cliponaxis=False))
    fig.update_layout(barmode="group", height=max(360, 62 * len(h) + 80),
                      xaxis=dict(title="Evidence cited in the hypothesis table", range=[0, max(int(h["desk_claims"].max()), 1) * 1.25]),
                      yaxis=dict(autorange="reversed", title=None), legend=dict(orientation="h", y=-0.2, title_text=""))
    return fig


def _hypothesis_section(h: pd.DataFrame | None, d: pd.DataFrame) -> None:
    if h is None:
        ui.section("Hypothesis check is not available", "Each hypothesis against the evidence behind it.", "3 · Research check", kind="fact")
        st.info("The hypothesis table (analysis/3_hypothesis_table.md) was not found.")
        return
    v = h["verdict"].str.lower().map(lambda x: _VERDICT.get(x, x)).value_counts()
    n = len(h)
    sup, mix, ins = int(v.get("Supported", 0)), int(v.get("Mixed", 0)), int(v.get("Insufficient evidence", 0))
    ui.section(f"{sup} of {n} hypotheses are supported, {mix} are mixed and {ins} cannot be tested yet",
               "Verdicts are the desk-research table's own; counts are read from it.", "3 · Research check", kind="fact")
    scraped_only = h[h["scraped"].map(len) == 0]
    say = (f"Every hypothesis rests mainly on desk research: {int(h['desk_claims'].sum())} claims against "
           f"{int(h['scraped'].map(len).sum())} scraped sources."
           + (f" {_join([_headline(r.id, r.claim) for r in scraped_only.itertuples()])} cite no scraped source." if len(scraped_only) else ""))
    ui.plot(_hyp_chart(h), say,
            note="Scraped sources are the SC-coded datasets and inventories the table cites. A longer bar is more evidence, not a stronger verdict.",
            bases=f"{n} hypotheses in the desk-research table", key="tri_hypotheses")
    show = pd.DataFrame({
        "Hypothesis": [f"{_headline(r.id, r.claim)} ({r.id})" for r in h.itertuples()],
        "Claim": h["claim"],
        "Verdict": h["verdict"].str.lower().map(lambda x: _VERDICT.get(x, x.title())) + " · " + h["confidence"] + " confidence",
        "Evidence base": [f"{r.desk_claims} desk claims, {r.desk_sources} desk sources; scraped: " + (", ".join(r.scraped) or "none")
                          for r in h.itertuples()],
        "Dashboard check (live)": [_live_check(r.id, d) for r in h.itertuples()],
    })
    st.dataframe(show, hide_index=True, width="stretch", column_config={
        "Hypothesis": st.column_config.TextColumn(width="medium"), "Claim": st.column_config.TextColumn(width="large"), "Dashboard check (live)": st.column_config.TextColumn(width="large")})
    st.caption("Insufficient evidence means the table found too little to say, not that the hypothesis is false.")


# ---------------------------------------------------------------------------
# Section 4: per-brand summary (Prompt D), shown only when it has run
# ---------------------------------------------------------------------------

def _brand_summaries() -> dict | None:
    txt = load_text("prompt_d_triangulation_summary.md")
    if not txt:
        return None
    parts = re.split(r"^## (.+)$", txt, flags=re.M)
    return {parts[i].strip(): parts[i + 1].strip() for i in range(1, len(parts) - 1, 2)} or None


def _summary_section(brands: list) -> None:
    sums = _brand_summaries()
    if not sums:
        return
    ui.section("Each brand's scraped data confirms some of the framework and diverges from the rest",
               "Written by a language model from the Prompt B/C counts. Divergences are hypotheses to test, not findings.",
               "4 · Position", kind="dir")
    st.warning("Read with care: these are machine-written drafts and can misstate the framework (one says app friction contradicts it, "
               "but registration friction is barrier 4). They also rest on a thin Prompt B read. Check each claim against sections 2 and 3 before use.")
    shown = [b for b in brands if b in sums]
    for b in shown:
        with st.expander(b, expanded=False):
            st.markdown(sums[b])


# ---------------------------------------------------------------------------
# Page
# ---------------------------------------------------------------------------

def render(selected_brands: list, voice: pd.DataFrame) -> None:
    brands = charts.order_brands(selected_brands)
    cc = load_csv("prompt_a_channel_coverage.csv")
    bm = base = src = None     # Prompt B's separate comment base is retired: barriers are read on the shared labels only
    h = hypotheses()
    kw, n_flagged = _keyword_counts(voice, brands) if voice is not None and not voice.empty else (pd.Series(dtype=int), 0)
    rows = barrier_rows(bm, kw, n_flagged, src)

    # ---- Pyramid ---------------------------------------------------------------------------------------------
    d = _channels(cc) if cc is not None and not cc.empty else None
    gaps = d[d["online"] & ~d["covered"]] if d is not None else None
    have_llm = bm is not None and not bm.empty
    n_both = int((rows["read"] == "Confirmed by both").sum())
    n_seen = int(rows["read"].isin(["Confirmed by both", "One method only", "Seen in flags"]).sum())
    args = []
    if d is not None:
        args.append({"label": "Evidence base", "value": f"{int(d['covered'].sum())} of {len(d)}", "stat": "Retail channels with scraped data",
                     "text": f"Retail channels carry scraped data; {html.escape(_join(gaps['taxonomy_category']))} have none"
                             + ("." if _has_evidence(d) else ", and we hold no evidence of where brands are sold."),
                     "tone": "watch"})
    args.append({"label": "Barrier", "value": f"{n_both if have_llm else n_seen} of 10", "stat": "Desk-research barriers seen in complaint items",
                 "text": ("Framework barriers are confirmed by both the Prompt B read and the shared labels." if have_llm
                          else "Framework barriers appear in the brand pool's complaint items (shared labels)."),
                 "tone": "good" if (n_both if have_llm else n_seen) >= 6 else "watch"})
    answer = (f"Scraped data confirms {n_both if have_llm else n_seen} of the 10 desk-research barriers"
              + ("" if d is None or _has_evidence(d) else " but cannot say where brands are sold") + ".")
    implication = "Treat barriers confirmed by both methods as findings and the rest as hypotheses."
    if h is not None:
        v = h["verdict"].str.lower()
        sup, ins = int((v == "supported").sum()), int((v == "insufficient evidence").sum())
        open_ids = _join(h.loc[v == "insufficient evidence", "id"])
        args.append({"label": "Research check", "value": f"{sup} of {len(h)}", "stat": "Hypotheses the desk research supports",
                     "text": f"Hypotheses are supported; {int((v == 'mixed').sum())} are mixed and {ins} ({html.escape(open_ids)}) cannot be tested yet.",
                     "tone": "bad" if ins > len(h) / 2 else "watch"})
        answer = answer[:-1] + f"; {ins} of {len(h)} hypotheses cannot be tested yet."
        implication = (f"Close the evidence gaps before taking {html.escape(open_ids)} to the client: marketplace capture including Shopee, "
                       "ECP and chain interviews, and J&J CRM data. Until then treat them as hypotheses.")
    ui.pyramid(html.escape(answer), args, implication)

    # ---- Sections --------------------------------------------------------------------------------------------
    t_ev, t_bar, t_res = (st.container() for _ in range(3))
    with t_ev:
        _channel_section(cc)
    with t_bar:
        _barrier_section(rows, bm, base, kw, n_flagged, brands, src)
    with t_res:
        _hypothesis_section(h, voice)

    # ---- Supporting data -------------------------------------------------------------------------------------
    with st.expander("Supporting data and method", expanded=False):
        files = [("Channel coverage (Prompt A)", "prompt_a_channel_coverage.csv", "a")]
        st.dataframe(pd.DataFrame([{"Output": lab, "Last run": _stamp(f) or "Not run yet", "Command": "" if _stamp(f) else RUN_CMD.format(p=p)}
                                   for lab, f, p in files]), hide_index=True, width="stretch")
        st.markdown(
            f"- **Shared labels** are the {n_flagged:,} negative or mixed items of the brand pool (Brand & market), labelled by "
            "`barrier_taxonomy.classify` (model tags where `theme_tag_sg.py` has tagged the text, keywords otherwise). Same base as that page.\n"
            "- **Retired:** the separate Prompt B comment base and the Prompt D per-brand prose. Their output files stay in "
            "`Scripts/output/triangulation_sg/`; they are no longer read, so every count here reconciles with the other tabs.\n"
            "- **Desk research** is `analysis/3_hypothesis_table.md` and `4_category_user_barrier_framework.md`; verdicts are not recomputed here.\n"
            "- **Not included:** the Hong Kong distribution-gap, share-of-voice, price and reputation cross-checks (no Singapore data), "
            "and the attribute quadrant (Prompt C), which still uses the Hong Kong attribute set."
        )
        if d is None:
            not_run("a")
