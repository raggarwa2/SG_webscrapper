"""
Themes & channels: every channel read on the same eight themes, from one tagger.

The channels used to look different because each carried its own labels. Scripts/build_voice_items.py puts every item in one
table (voice_items_sg.db) and Scripts/tag_voice_items.py gives each item the same sentiment, 1 or 2 of the eight THEMES (each
with its own polarity), and a content type, from one model prompt (voice_tags_sg.db). This page reads only those two tables, so
it does not depend on the per-channel loaders and does not move any number on Brand Health or Journey & barriers.

Four lenses are kept apart and never pooled: consumer voice (the Brand Health pool, minus giveaway entries), owned experience
(the MyACUVUE app), retail experience (Google Maps and retailer pages: about the shop, not the brand) and brand broadcast
(brands' own posts and ads). Brand comparisons use the consumer lens only.

Rules: no rate under ebi.MIN_N items (count only); every chart has a sample-size strip; praise vs complaint comes from the
polarity the model gave that theme, not from the theme itself.

Order: summary -> channels -> themes (Acuvue vs peers) -> stores and app -> brand voice -> supporting data.
"""

import html
import json
import sqlite3
from pathlib import Path

import numpy as np
import pandas as pd
import plotly.graph_objects as go
import streamlit as st

import charts
import ebi
import theme_tags
import ui
from sg_common import BRAND_COLORS, DB_DIR, SENTIMENT_COLORS

VOICE_DB = Path(DB_DIR) / "voice_items_sg.db"
TAG_DB = Path(DB_DIR) / "voice_tags_sg.db"
FOCAL = "Acuvue"
THEMES = theme_tags.THEME_LIST
NO_THEME = "No theme"
SENT = ("positive", "neutral", "mixed", "negative")
CONTENT_ORDER = ["promo", "education_news", "giveaway_spam", "experience", "opinion", "question", "other"]
CONTENT_LABEL = {"promo": "Promotion", "education_news": "Education / news", "giveaway_spam": "Giveaway / spam",
                 "experience": "Own experience", "opinion": "Opinion", "question": "Question", "other": "Other"}
CONTENT_COLOR = {"promo": "#B7791F", "education_news": "#59A5D7", "giveaway_spam": "#9AA5B1", "experience": "#168012",
                 "opinion": "#0B3556", "question": "#7048E8", "other": "#D5DBE1"}
ERAS = [("2017-2019", 2017, 2019), ("2020-2023", 2020, 2023), ("2024-2026", 2024, 2026)]


# ---------------------------------------------------------------- data
@st.cache_data(ttl=600, show_spinner=False, max_entries=2)
def _load(m_items: float, m_tags: float) -> pd.DataFrame:
    """voice_items joined to voice_tags: one row per tagged item, themes as a list, polarity as a dict."""
    con = sqlite3.connect(f"file:{VOICE_DB.as_posix()}?mode=ro", uri=True)
    items = pd.read_sql_query(
        "SELECT item_id, source, unit, voice_type, lens, brand_std, owner_brand, retailer, date, text_en, rating_native, "
        "sentiment_native, lens_relevant, is_contest, in_pool FROM voice_items", con)
    con.close()
    con = sqlite3.connect(f"file:{TAG_DB.as_posix()}?mode=ro", uri=True)
    tags = pd.read_sql_query(
        "SELECT item_id, sentiment, themes, theme_polarity, journey_stage, content_type, taxonomy_version FROM voice_tags", con)
    con.close()
    d = items.merge(tags, on="item_id", how="inner")
    d["themes"] = d["themes"].map(json.loads)
    d["pol"] = d["theme_polarity"].map(json.loads)
    d["date"] = pd.to_datetime(d["date"], errors="coerce")
    return d.drop(columns=["theme_polarity"]).reset_index(drop=True)


def _theme_pol(d: pd.DataFrame, theme: str) -> pd.Series:
    """The polarity the model gave `theme` on every item of d that carries that theme."""
    return pd.Series([p[theme] for p, th in zip(d["pol"], d["themes"]) if theme in th], dtype=object)


def _net(s: pd.Series):
    """(net sentiment in points, standard error in points, n) for a series of labels; None when empty."""
    n = len(s)
    if n == 0:
        return None
    p, q = (s == "positive").mean(), (s == "negative").mean()
    return (p - q) * 100, float(np.sqrt(max(p + q - (p - q) ** 2, 0) / n) * 100), n


def _grade(a: pd.Series, b: pd.Series, by_channel: list) -> dict:
    """Evidence grade for 'focus vs peers on one theme'. a, b = polarity labels of focus and peers.
    by_channel = [(focus labels, peer labels)] per channel. Not readable under MIN_N on either side; Level when the gap
    interval holds zero; B when it does not; A when the same sign also shows in 2+ channels that each have MIN_N on both sides."""
    out = {"grade": "Not readable", "net_f": None, "net_p": None, "gap": None, "lo": None, "hi": None}
    if len(a) < ebi.MIN_N or len(b) < ebi.MIN_N:
        return out
    (nf, sf, _), (npp, sp, _) = _net(a), _net(b)
    gap, se = nf - npp, float(np.hypot(sf, sp))
    out.update(net_f=nf, net_p=npp, gap=gap, lo=gap - 1.96 * se, hi=gap + 1.96 * se)
    if out["lo"] <= 0 <= out["hi"]:
        out["grade"] = "Level"
        return out
    same = 0
    for fa, pb in by_channel:
        if len(fa) >= ebi.MIN_N and len(pb) >= ebi.MIN_N and (_net(fa)[0] - _net(pb)[0]) * gap > 0:
            same += 1
    out["grade"] = "A · corroborated" if same >= 2 else "B · one channel"
    return out


def theme_table(pool: pd.DataFrame, focus: str) -> pd.DataFrame:
    f_all = pool[pool["brand_std"] == focus]
    p_all = pool[pool["brand_std"] != focus]
    rows = []
    for t in THEMES:
        a, b = _theme_pol(f_all, t), _theme_pol(p_all, t)
        chans = [(_theme_pol(f_all[f_all["source"] == c], t), _theme_pol(p_all[p_all["source"] == c], t))
                 for c in charts.SOURCE_ORDER]
        g = _grade(a, b, chans)
        rows.append({"theme": t, "n_f": len(a), "n_p": len(b), **g})
    return pd.DataFrame(rows)


def channel_rows(d: pd.DataFrame) -> list:
    """(row label, mask) for the channel x theme grid. Consumer rows use the Brand Health pool; the app is left out (see page)."""
    rows = [(f"Consumer · {c}", (d["source"] == c) & (d["in_pool"] == 1)) for c in charts.SOURCE_ORDER]
    rows += [
        ("Retail · Google Maps (contact lens)", d["source"] == "Google Maps"),
        ("Retail · Facebook retailer reviews", d["source"] == "Facebook retailer reviews"),
        ("Retail · retailer posts", d["source"] == "Facebook retailer posts"),
        ("Brand · own posts", (d["voice_type"] == "brand_owned") & (d["unit"] == "post")),
        ("Brand · Facebook ads", d["source"] == "Facebook ads"),
    ]
    return rows


def theme_share(d: pd.DataFrame, mask: pd.Series) -> dict:
    """{theme or NO_THEME: share of the rows in mask}, plus 'n'."""
    s = d[mask]
    n = len(s)
    out = {"n": n}
    for t in THEMES:
        out[t] = (sum(t in th for th in s["themes"]) / n * 100) if n else None
    out[NO_THEME] = (sum(len(th) == 0 for th in s["themes"]) / n * 100) if n else None
    return out


def grid_themes(d: pd.DataFrame) -> tuple:
    """(shown, left out): a theme is left out of the grid when no row reaches ebi.MIN_N items on it."""
    rows = [m for _, m in channel_rows(d) if m.any()]
    best = {t: max((sum(t in th for th in d[m]["themes"]) for m in rows), default=0) for t in THEMES}
    return [t for t in THEMES if best[t] >= ebi.MIN_N], [t for t in THEMES if best[t] < ebi.MIN_N]


def channel_heat(d: pd.DataFrame) -> tuple:
    shown, left_out = grid_themes(d)
    cols = shown + [NO_THEME]
    z, text, ylab, bases = [], [], [], {}
    for label, mask in channel_rows(d):
        sh = theme_share(d, mask)
        n = sh["n"]
        if n == 0:
            continue
        bases[label] = n
        ylab.append(charts.row_label(label, n))
        if n < ebi.MIN_N:
            z.append([None] * len(cols))
            text.append([str(sum(c in th for th in d[mask]["themes"])) if c != NO_THEME else str(sum(len(th) == 0 for th in d[mask]["themes"]))
                         for c in cols])
        else:
            z.append([sh[c] for c in cols])
            text.append([f"{sh[c]:.0f}%" for c in cols])
    fig = go.Figure(go.Heatmap(
        z=z, x=[c.replace(" & ", " &<br>") for c in cols], y=ylab, text=text, texttemplate="%{text}", zmin=0, zmax=60, xgap=3, ygap=3, hoverongaps=False,
        colorscale=[[0, "#F1F5F9"], [1, "#5FB0C0"]], textfont=dict(size=11, color="#191919"),
        colorbar=dict(title=dict(text="% of items", side="top", font=dict(size=11)), thickness=12, len=0.7,
                      tickvals=[0, 20, 40, 60], ticktext=["0%", "20%", "40%", "60%+"], tickfont=dict(size=10)),
        hovertemplate="%{y}<br>%{x}: %{text}<extra></extra>"))
    fig.update_xaxes(side="top", tickangle=0, title=None)
    fig.update_yaxes(autorange="reversed", title=None)
    fig.update_layout(height=120 + 46 * len(ylab), plot_bgcolor="#F1F5F9", margin=dict(t=70, l=10, r=10, b=10))
    return fig, bases, left_out


def app_eras(app: pd.DataFrame) -> pd.DataFrame:
    rows = []
    for label, y0, y1 in ERAS:
        s = app[(app["date"].dt.year >= y0) & (app["date"].dt.year <= y1)]
        n = len(s)
        rows.append({"era": label, "n": n, "neg": (s["sentiment"] == "negative").mean() * 100 if n else None,
                     "stars": s["rating_native"].mean() if n else None})
    return pd.DataFrame(rows)


# ---------------------------------------------------------------- page
def _pts(v: float) -> str:
    return f"{ebi.sgn(v)}"


def render() -> None:
    if not (VOICE_DB.exists() and TAG_DB.exists()):
        st.info("Run Scripts/build_voice_items.py and Scripts/tag_voice_items.py to build the tables this page reads.")
        return
    d = _load(VOICE_DB.stat().st_mtime, TAG_DB.stat().st_mtime)
    if d.empty:
        st.info("No tagged items yet.")
        return
    pool = d[(d["in_pool"] == 1) & d["brand_std"].notna()].reset_index(drop=True)
    tt = theme_table(pool, FOCAL)
    readable = tt[tt["grade"] != "Not readable"]
    maps = d[d["source"] == "Google Maps"]
    app = d[d["source"] == "MyACUVUE app"]
    own = d[(d["voice_type"] == "brand_owned") & (d["unit"] == "post") & d["owner_brand"].notna()]
    n_pool = len(pool)
    n_f = int((pool["brand_std"] == FOCAL).sum())

    # ---- numbers behind the summary --------------------------------------------------------------------------
    if len(readable):
        r0 = readable.iloc[0]
        verdict = ("not clearly different from" if r0["grade"] == "Level" else ("ahead of" if r0["gap"] > 0 else "behind"))
        chance = "; the gap could be chance" if r0["grade"] == "Level" else ""
        theme_txt = ", ".join(readable["theme"])
        head = (f"{FOCAL} can be read against peers on {len(readable)} of {len(THEMES)} themes ({html.escape(theme_txt)}); "
                f"on {html.escape(r0['theme'])} it is {verdict} peers (net {_pts(r0['net_f'])} vs {_pts(r0['net_p'])}{chance}).")
    else:
        head = f"{FOCAL} cannot yet be read against peers on any theme: no theme has {ebi.MIN_N}+ items for both sides."
    mrows = [(t, p) for pol, th in zip(maps["pol"], maps["themes"]) for t, p in pol.items()]
    mt = pd.DataFrame(mrows, columns=["theme", "pol"]) if mrows else pd.DataFrame(columns=["theme", "pol"])
    mcount = mt.groupby(["theme", "pol"]).size().unstack(fill_value=0) if len(mt) else pd.DataFrame()
    for c in ("positive", "mixed", "negative", "neutral"):
        if c not in mcount.columns:
            mcount[c] = 0
    mcount["total"] = mcount[["positive", "mixed", "negative", "neutral"]].sum(axis=1) if len(mcount) else []
    eras = app_eras(app) if len(app) else pd.DataFrame()
    last_era = eras.iloc[-1] if len(eras) else None
    top_pos = mcount["positive"].idxmax() if len(mcount) and mcount["positive"].max() else None
    top_neg = mcount["negative"].idxmax() if len(mcount) and mcount["negative"].max() else None
    tot_tags = int(mcount["total"].sum()) if len(mcount) else 0
    pos_share = mcount["positive"].sum() / tot_tags * 100 if tot_tags >= ebi.MIN_N else None
    store_txt = (f"store reviews are {pos_share:.0f}% positive, with complaints concentrated on {html.escape(top_neg.lower())}"
                 if pos_share is not None and top_neg else "")
    app_bad = last_era is not None and last_era["n"] >= ebi.MIN_N
    app_txt = (f"the MyACUVUE app is {last_era['neg']:.0f}% negative in {last_era['era']} (n={int(last_era['n'])})" if app_bad else "")
    tail = "; ".join(x for x in (store_txt, app_txt) if x)
    bottom = head + (f" Beyond the brand pool, {tail}." if tail else "")

    rows_all = channel_rows(d)
    shares = []
    for label, mask in rows_all:
        sh = theme_share(d, mask)
        if sh["n"] >= ebi.MIN_N:
            best = max(THEMES, key=lambda t: sh[t] or 0)
            shares.append((label, best, sh[best], sh["n"]))
    shares.sort(key=lambda x: -x[2])
    picked, seen = [], set()
    for s in shares:
        if s[1] not in seen:
            picked.append(s)
            seen.add(s[1])
        if len(picked) == 2:
            break
    chan_txt = "; ".join(f"{html.escape(s[0].split(' · ')[-1])}: {s[2]:.0f}% {html.escape(s[1].lower())}" for s in picked) or "too few items per channel"

    own_f = own[own["owner_brand"] == FOCAL]
    promo = (own_f["content_type"] == "promo").mean() * 100 if len(own_f) >= ebi.MIN_N else None
    cons_f = pool[pool["brand_std"] == FOCAL]
    comfort_cons = sum("Comfort & product" in th for th in cons_f["themes"]) / len(cons_f) * 100 if len(cons_f) else None
    comfort_own = sum("Comfort & product" in th for th in own_f["themes"]) / len(own_f) * 100 if len(own_f) >= ebi.MIN_N else None

    args = [
        {"label": "Channels", "value": f"{len(shares)} channels", "tone": "flat",
         "text": f"Each channel has its own theme mix ({chan_txt})."},
        {"label": "Themes", "value": f"{len(readable)} of {len(THEMES)}", "tone": "watch" if len(readable) < 3 else "flat",
         "text": f"themes have {ebi.MIN_N}+ {FOCAL} and peer items; the rest are counts only or left out for lack of data."},
    ]
    if last_era is not None and last_era["n"] >= ebi.MIN_N:
        args.append({"label": "Stores & app", "value": f"{last_era['neg']:.0f}% negative", "tone": "bad",
                     "text": f"of MyACUVUE app reviews in {last_era['era']} (n={int(last_era['n'])}); store reviews are mostly praise."})
    if promo is not None:
        args.append({"label": "Voice", "value": f"{promo:.0f}% promo", "tone": "watch",
                     "text": f"of {FOCAL}'s own posts; {comfort_own:.0f}% touch comfort, against {comfort_cons:.0f}% of consumer items."})
    action = ("Read comfort as the one theme with enough evidence and treat the rest as leads: collect more items on price, access, "
              "fitting and service before claiming a lead or a gap. Fix the app and in-store service first, since that is where "
              "complaints concentrate.")
    ui.pyramid(bottom, args, html.escape(action))

    # ---- 1. Channels -----------------------------------------------------------------------------------------
    ui.section("Every channel talks about a different mix of themes",
               "Share of items touching each theme, all lenses on one grid. Rows under 30 items show counts only. "
               "Consumer rows are the Brand Health pool; retail and brand rows are about shops and brand broadcast, not consumers.",
               "1 · Channels", kind="fact")
    fig, bases, grid_left_out = channel_heat(d)
    grid_shown = [t for t in THEMES if t not in grid_left_out]
    top_cell = max(((r[0], t, theme_share(d, r[1])[t]) for r in rows_all for t in grid_shown if theme_share(d, r[1])["n"] >= ebi.MIN_N),
                   key=lambda x: x[2] or 0, default=None)
    say = (f"{top_cell[0].split(' · ')[-1]} is the most focused: {top_cell[2]:.0f}% of its items are about {top_cell[1].lower()}."
           if top_cell else "No channel has enough items to compare.")
    ui.plot(fig, say, key="cv_heat", note="One item can carry two themes, so a row can add to more than 100%.",
            bases=bases, noun="tagged items")
    if grid_left_out:
        st.caption("Left out: " + ", ".join(grid_left_out) + f" (no row reaches {ebi.MIN_N} items on them; they stay in the tagging and return when they do).")
    st.caption("MyACUVUE app reviews are not on this grid: 30 of the 119 are filed under Service although they are about the app. "
               "The next re-tag fixes the Loyalty & app wording.")

    # ---- 2. Themes: focus vs peers ---------------------------------------------------------------------------
    n_read = len(readable)
    ui.section(f"Only {n_read} of {len(THEMES)} themes {'has' if n_read == 1 else 'have'} enough {FOCAL} items to read" if n_read < len(THEMES)
               else f"{FOCAL} can be read against peers on every theme",
               "Net sentiment on the theme (positive minus negative, using the polarity the model gave that theme). "
               "Consumer voice only, giveaway entries removed.", "2 · Themes", kind="fact")
    tv = tt[(tt["n_f"] >= ebi.MIN_N) | (tt["n_p"] >= ebi.MIN_N)].reset_index(drop=True)
    t_left = tt[~tt["theme"].isin(tv["theme"])]
    bar = go.Figure()
    thin_f = [ebi.is_thin(n) or n == 0 for n in tv["n_f"]]
    thin_p = [ebi.is_thin(n) or n == 0 for n in tv["n_p"]]
    bar.add_bar(y=tv["theme"], x=tv["n_f"], orientation="h", name=FOCAL, marker=dict(color=BRAND_COLORS[FOCAL], pattern=charts.thin_fill(thin_f)))
    bar.add_bar(y=tv["theme"], x=tv["n_p"], orientation="h", name="Peers pooled", marker=dict(color="#9AA5B1", pattern=charts.thin_fill(thin_p)))
    bar.add_vline(x=ebi.MIN_N, line_dash="dash", line_color=charts.AMBER)
    bar.update_layout(barmode="group", height=max(260, 110 + 50 * len(tv)), legend=dict(orientation="h", y=-0.14, traceorder="normal"),
                      xaxis_title=f"Items on the theme (dashed line = {ebi.MIN_N}, the minimum for a rate)", yaxis_title=None)
    bar.update_yaxes(autorange="reversed")
    ui.plot(bar, f"{n_read} of {len(THEMES)} themes {'clears' if n_read == 1 else 'clear'} the {ebi.MIN_N}-item line on both sides; hatched bars are directional only.",
            key="cv_themes", bases={FOCAL: n_f, "Peers": n_pool - n_f}, noun="pooled items")
    view = pd.DataFrame({
        "Theme": tv["theme"],
        f"{FOCAL} items": tv["n_f"], "Peer items": tv["n_p"],
        f"{FOCAL} net": [f"{ebi.sgn(v)}" if v is not None and pd.notna(v) else f"n={n}, too few" for v, n in zip(tv["net_f"], tv["n_f"])],
        "Peers net": [f"{ebi.sgn(v)}" if v is not None and pd.notna(v) else f"n={n}, too few" for v, n in zip(tv["net_p"], tv["n_p"])],
        "Gap, pts (95% interval)": [f"{ebi.sgn(g)} ({ebi.sgn(lo)} to {ebi.sgn(hi)})" if g is not None and pd.notna(g) else "-" for g, lo, hi in zip(tv["gap"], tv["lo"], tv["hi"])],
        "Evidence": tv["grade"],
    })
    st.dataframe(view, hide_index=True, width="stretch")
    st.caption("Evidence: Not readable = under 30 items on a side. Level = the gap could be chance. B = a real gap, seen in one channel. "
               "A = a real gap that two channels with 30+ items each agree on.")
    if len(t_left):
        st.caption("Left out: " + ", ".join(f"{r.theme} ({r.n_f} vs {r.n_p})" for r in t_left.itertuples())
                   + f" (under {ebi.MIN_N} items for both {FOCAL} and peers; {FOCAL} vs peers counts in brackets).")

    # ---- 3. Stores and app -----------------------------------------------------------------------------------
    ui.section((f"Store reviews are {pos_share:.0f}% positive; the MyACUVUE app is {last_era['neg']:.0f}% negative"
                if pos_share is not None and app_bad else "Stores and the MyACUVUE app"),
               "Two lenses kept out of the brand comparison: Google Maps reviews are about the shop, the app is Acuvue's own.",
               "3 · Stores & app", kind="fact")
    left, right = st.columns(2)
    with left:
        show = mcount[mcount["total"] >= ebi.MIN_N].sort_values("total", ascending=False) if len(mcount) else mcount
        if len(show):
            fm = go.Figure()
            for pol in ("positive", "mixed", "negative"):
                fm.add_bar(y=[charts.row_label(t, int(n)) for t, n in zip(show.index, show["total"])], x=show[pol], orientation="h",
                           name=charts.SENTIMENT_LABELS[pol], marker_color=SENTIMENT_COLORS[pol])
            fm.update_layout(barmode="stack", height=90 + 56 * len(show), legend=dict(orientation="h", y=-0.12, traceorder="normal"), xaxis_title=None)
            fm.update_yaxes(autorange="reversed")
            lead = "Store reviews by theme."
            if top_neg:
                lead = f"{top_neg} draws the most complaints ({int(mcount.loc[top_neg, 'negative'])} of {int(mcount.loc[top_neg, 'total'])} tags)"
                fg = "Fitting & guidance"
                if fg in mcount.index and mcount.loc[fg, "total"] >= ebi.MIN_N and fg != top_neg:
                    lead += f"; {fg.lower()} is praised in {int(mcount.loc[fg, 'positive'])} of {int(mcount.loc[fg, 'total'])}"
                lead += "."
            ui.plot(fm, lead, key="cv_maps", note="Google Maps reviews that are clearly about contact lenses. Skews positive: only the newest reviews were pulled.",
                    bases={"Google Maps": len(maps)}, noun="contact-lens reviews")
            small = mcount[mcount["total"] < ebi.MIN_N]
            if len(small):
                st.caption("Counts only (under 30 tags): " + "; ".join(f"{t} {int(r.positive)} positive / {int(r.negative)} negative" for t, r in small.iterrows()) + ".")
        else:
            st.caption("No tagged Google Maps reviews yet.")
    with right:
        if len(eras) and eras["n"].sum():
            fa = go.Figure(go.Bar(x=[charts.row_label(e, int(n)) for e, n in zip(eras["era"], eras["n"])],
                                  y=[v if (v is not None and pd.notna(v) and n >= ebi.MIN_N) else None for v, n in zip(eras["neg"], eras["n"])],
                                  marker_color=SENTIMENT_COLORS["negative"], text=[f"{v:.0f}%" if (v is not None and pd.notna(v) and n >= ebi.MIN_N) else f"n={int(n)}"
                                                                               for v, n in zip(eras["neg"], eras["n"])], textposition="outside"))
            fa.update_layout(height=330, yaxis=dict(range=[0, 110], title="% negative"), xaxis_title=None)
            ui.plot(fa, f"{eras.iloc[0]['neg']:.0f}% of early reviews were negative, {eras.iloc[-1]['neg']:.0f}% in {eras.iloc[-1]['era']}."
                    if eras.iloc[0]["n"] >= ebi.MIN_N and eras.iloc[-1]["n"] >= ebi.MIN_N else "MyACUVUE app reviews by period.",
                    key="cv_app", note="Apple App Store and Google Play written reviews; Acuvue only, so no peer comparison.",
                    bases={r.era: int(r.n) for r in eras.itertuples()}, noun="app reviews")
    chains = maps.groupby("retailer").agg(n=("item_id", "size"),
                                          net=("sentiment", lambda s: (s == "positive").mean() * 100 - (s == "negative").mean() * 100),
                                          neg=("pol", lambda ps: np.mean([any(v == "negative" for v in p.values()) for p in ps]) * 100))
    chains = chains.sort_values("n", ascending=False)
    ct = pd.DataFrame({"Chain": chains.index, "Contact-lens reviews": chains["n"].values,
                       "Net sentiment": [f"{ebi.sgn(v)}" if n >= ebi.MIN_N else f"n={n}, too few" for v, n in zip(chains["net"], chains["n"])],
                       "Reviews with a negative theme": [f"{v:.0f}%" if n >= ebi.MIN_N else "-" for v, n in zip(chains["neg"], chains["n"])]})
    st.dataframe(ct, hide_index=True, width="stretch")
    ui.n_strip({r.Chain: int(r._2) for r in ct.itertuples()}, noun="contact-lens reviews")

    # ---- 4. Voice: what brands say vs what people say --------------------------------------------------------
    ui.section(f"{FOCAL}'s own posts are mostly promotion; consumers talk about comfort" if promo is not None and promo >= 50
               else "What brands post vs what people say", "Brands' own posts (Instagram, Facebook, YouTube) by content type.",
               "4 · Voice", kind="fact")
    brands_own = [b for b in charts.BRAND_ORDER if (own["owner_brand"] == b).sum() >= ebi.MIN_N]
    if brands_own:
        fv = go.Figure()
        for ct_ in CONTENT_ORDER:
            fv.add_bar(y=[charts.row_label(b, int((own["owner_brand"] == b).sum())) for b in brands_own],
                       x=[(own[own["owner_brand"] == b]["content_type"] == ct_).mean() * 100 for b in brands_own], orientation="h",
                       name=CONTENT_LABEL[ct_], marker_color=CONTENT_COLOR[ct_])
        fv.update_layout(barmode="stack", height=90 + 60 * len(brands_own), legend=dict(orientation="h", y=-0.3, traceorder="normal"),
                         xaxis=dict(range=[0, 100], title="% of posts"))
        fv.update_yaxes(autorange="reversed")
        small_b = [b for b in charts.BRAND_ORDER if 0 < (own["owner_brand"] == b).sum() < ebi.MIN_N]
        ui.plot(fv, (f"{promo:.0f}% of {FOCAL}'s own posts are promotions." if promo is not None else "Content type of brands' own posts."),
                key="cv_voice", note=("Brands under 30 posts are left out: " + ", ".join(f"{b} ({int((own['owner_brand'] == b).sum())})" for b in small_b) + ".") if small_b else "",
                bases={b: int((own["owner_brand"] == b).sum()) for b in brands_own}, noun="own posts")
    if promo is not None and comfort_cons is not None:
        st.caption(f"Comfort & product is the theme of {comfort_own:.0f}% of {FOCAL}'s own posts and {comfort_cons:.0f}% of consumer items about {FOCAL}. "
                   "Promotional copy usually carries no theme, so read this as a difference in what is posted, not a missed message.")

    # ---- Supporting data -------------------------------------------------------------------------------------
    with st.expander("Supporting data: tagging coverage, method and caveats", expanded=False):
        cov = (d.groupby(["lens", "source"]).agg(tagged=("item_id", "size"), in_pool=("in_pool", "sum"),
                                                  versions=("taxonomy_version", lambda s: ", ".join(sorted(set(s))))).reset_index())
        cov["lens"] = cov["lens"].map({"consumer_voice": "Consumer voice", "owned_experience": "Owned experience",
                                        "retail_experience": "Retail experience", "brand_broadcast": "Brand broadcast"})
        st.dataframe(cov.rename(columns={"lens": "Lens", "source": "Source", "tagged": "Model-tagged", "in_pool": "In the brand pool",
                                         "versions": "Tag version"}), hide_index=True, width="stretch")
        agree = pool[pool["sentiment_native"].isin(SENT)]
        n_contest = int(((d["source"] == "Instagram") & (d["unit"] == "comment") & (d["is_contest"] == 1) & (d["lens_relevant"] != 0)).sum())
        st.markdown(
            f"- **Model-tagged:** all {len(d):,} items on this page carry model tags (one prompt, `gpt-4o-mini`); none is a keyword draft.\n"
            f"- **Brand pool:** {n_pool:,} items. Instagram comments under giveaway posts are removed from the pool "
            "(they answer the prize question, so they are not opinions); the Brand Health page applies the same rule.\n"
            f"- **Against the older labels:** the new sentiment agrees with the source label on {(agree['sentiment'] == agree['sentiment_native']).mean():.0%} "
            f"of {len(agree):,} pool items. The new labels are stricter on promotional and off-topic items, so net sentiment reads lower; "
            "Brand Health still uses the older labels, so the two pages differ by that much.\n"
            "- **Not yet fixed:** the app theme wording (see the note under the grid) and the Loyalty & app theme, which has almost no consumer items.")
        if len(readable):
            st.markdown("**Theme read by channel (focus vs peers, both sides 30+ items)**")
            f_all, p_all = pool[pool["brand_std"] == FOCAL], pool[pool["brand_std"] != FOCAL]
            rows = []
            for t in readable["theme"]:
                for c in charts.SOURCE_ORDER:
                    a, b = _theme_pol(f_all[f_all["source"] == c], t), _theme_pol(p_all[p_all["source"] == c], t)
                    if len(a) >= ebi.MIN_N and len(b) >= ebi.MIN_N:
                        rows.append({"Theme": t, "Channel": c, f"{FOCAL} net": f"{ebi.sgn(_net(a)[0])} (n={len(a)})", "Peers net": f"{ebi.sgn(_net(b)[0])} (n={len(b)})"})
            st.dataframe(pd.DataFrame(rows) if rows else pd.DataFrame({"Note": ["No channel has 30+ items on both sides."]}),
                         hide_index=True, width="stretch")
