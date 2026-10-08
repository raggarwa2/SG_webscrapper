"""
One data layer for every story page.

Scripts/build_voice_items.py puts every scraped post, comment and review into one table (voice_items_sg.db) and
Scripts/tag_voice_items.py gives each item the same sentiment, 1 or 2 of the eight themes (each with its own polarity), a
journey stage and a content type from one model prompt (voice_tags_sg.db). This module reads only those two tables, so a number
means the same thing on every page.

Lenses, never pooled with each other:
  consumer voice     the brand pool: brand-named, relevant, no giveaway entries (the only lens used to compare brands)
  category voice     lens-relevant consumer comments that name no tracked brand; read on themes only, never against a brand
  owned experience   MyACUVUE app reviews (Acuvue only)
  retail experience  Google Maps and retailer-page reviews: about the shop, not the brand
  brand broadcast    brands' own posts and ads

Themes are the tagging layer; headlines report at four decision groups (theme_tags.GROUPS).
"""

import json
import sqlite3
from pathlib import Path

import numpy as np
import pandas as pd
import streamlit as st

import charts
import ebi
import theme_tags
from sg_common import DB_DIR

VOICE_DB = Path(DB_DIR) / "voice_items_sg.db"
TAG_DB = Path(DB_DIR) / "voice_tags_sg.db"
FOCAL = "Acuvue"
GROUPS = theme_tags.GROUPS
GROUP_LIST = theme_tags.GROUP_LIST
THEMES = theme_tags.THEME_LIST
NO_THEME = "No theme"
CHANNELS = charts.SOURCE_ORDER
APP = "MyACUVUE app"
MAPS = "Google Maps"

LENS_LABEL = {"consumer_voice": "Consumer voice", "owned_experience": "Owned experience (app)",
              "retail_experience": "Retail experience", "brand_broadcast": "Brand broadcast"}
# context.md: the journey stage each channel is built to evidence (a channel's role, not a per-item label)
CHANNEL_ROLE = {
    "Xiaohongshu": ("Awareness, Engagement", "Creator posts: discovery and look"),
    "Xiaohongshu comments": ("Engagement", "Reactions to creator posts"),
    "YouTube": ("Awareness, Engagement, Consideration", "Reviews, how-tos and comparisons"),
    "Instagram": ("Awareness, Engagement", "Brand and creator posts, comments"),
    "Facebook": ("Awareness, Engagement", "Brand page posts, comments"),
    "Reddit": ("Awareness, Consideration", "Threads: advice and comparisons"),
    "KiasuParents": ("Awareness, Consideration", "Forum threads"),
    "Lazada reviews": ("Consideration, Purchase, Repeat", "Verified-purchase reviews"),
    "MyACUVUE app": ("Trial, Purchase, Repeat", "Registration and app friction"),
    "Google Maps": ("Consideration", "Retailer experience before a fitting"),
    "Facebook retailer reviews": ("Consideration", "Retailer experience"),
}
ERAS = [("2017-2019", 2017, 2019), ("2020-2023", 2020, 2023), ("2024-2026", 2024, 2026)]
SENT = ("positive", "neutral", "mixed", "negative")


# ---------------------------------------------------------------- loading
def _group_pol(themes: list, pol: dict) -> dict:
    """Polarity per decision group: the polarity of its themes on this item, 'mixed' when two themes disagree."""
    out = {}
    for g, ts in GROUPS.items():
        ps = [pol.get(t) for t in themes if t in ts and pol.get(t)]
        if ps:
            out[g] = ps[0] if len(set(ps)) == 1 else "mixed"
    return out


@st.cache_data(ttl=600, show_spinner=False, max_entries=2)
def _load(m_items: float, m_tags: float) -> pd.DataFrame:
    con = sqlite3.connect(f"file:{VOICE_DB.as_posix()}?mode=ro", uri=True)
    items = pd.read_sql_query(
        "SELECT item_id, source, unit, voice_type, lens, brand_std, owner_brand, retailer, account, date, title, text_en, text_orig, url, "
        "likes, views, rating_native, sentiment_native, lens_relevant, brand_relevant, is_contest, in_pool FROM voice_items", con)
    con.close()
    con = sqlite3.connect(f"file:{TAG_DB.as_posix()}?mode=ro", uri=True)
    tags = pd.read_sql_query(
        "SELECT item_id, sentiment, themes, theme_polarity, journey_stage, content_type, taxonomy_version, tagged_at FROM voice_tags", con)
    con.close()
    d = items.merge(tags, on="item_id", how="inner")
    if len(d):
        # one tagging run per number: keep the latest tag version when it covers the pool, so old and new labels never mix
        latest = d.loc[d["tagged_at"].idxmax(), "taxonomy_version"]
        pooled = d["in_pool"] == 1
        if pooled.any() and ((d["taxonomy_version"] == latest) & pooled).sum() / pooled.sum() >= 0.95:
            d = d[d["taxonomy_version"] == latest]
    d["themes"] = d["themes"].map(json.loads)
    d["pol"] = d["theme_polarity"].map(json.loads)
    d["groups"] = d["themes"].map(lambda ts: [g for g in GROUP_LIST if any(theme_tags.GROUP_OF[t] == g for t in ts)])
    d["gpol"] = [_group_pol(t, p) for t, p in zip(d["themes"], d["pol"])]
    d["date"] = pd.to_datetime(d["date"], errors="coerce")
    body = d["text_en"].fillna("").where(d["text_en"].fillna("").str.len() > 0, d["text_orig"].fillna(""))
    d["text"] = (d["title"].fillna("").where(d["unit"] == "post", "") + " " + body).str.strip()
    d["is_category"] = ((d["voice_type"] == "consumer") & (d["unit"] == "comment") & (d["lens_relevant"] == 1)
                        & (d["brand_relevant"] == 0) & (d["in_pool"] != 1) & (d["is_contest"] != 1))
    return d.drop(columns=["theme_polarity", "text_orig"]).reset_index(drop=True)


def available() -> bool:
    return VOICE_DB.exists() and TAG_DB.exists()


def load() -> pd.DataFrame:
    """Every tagged item, one row each (empty frame when the tables are missing)."""
    if not available():
        return pd.DataFrame()
    return _load(VOICE_DB.stat().st_mtime, TAG_DB.stat().st_mtime)


def stamp() -> float:
    """Changes whenever the items or the tags change: add it to the key of any cache that holds unified labels."""
    return (VOICE_DB.stat().st_mtime + TAG_DB.stat().st_mtime) if available() else 0.0


@st.cache_data(ttl=600, show_spinner=False, max_entries=2)
def _unified(m_items: float, m_tags: float) -> dict:
    """{'source_table|native_id': sentiment}: the one label every item gets, keyed by the id the scraper's own table uses."""
    d = _load(m_items, m_tags)[["item_id", "sentiment"]]
    con = sqlite3.connect(f"file:{VOICE_DB.as_posix()}?mode=ro", uri=True)
    ids = pd.read_sql_query("SELECT item_id, source_table, native_id FROM voice_items", con)
    con.close()
    m = ids.merge(d, on="item_id")
    return dict(zip(m["source_table"] + "|" + m["native_id"].astype(str), m["sentiment"]))


def unify(df: pd.DataFrame, table: str, id_col: str = "id", col: str = "sentiment") -> pd.DataFrame:
    """Give a scraper's own frame the unified sentiment, so a per-channel page and a story page count the same label. An item with
    no tag (not in any tagged scope) keeps the scraper's label; it is never part of a pooled figure."""
    if df is None or df.empty or col not in df.columns or id_col not in df.columns or not available():
        return df
    new = (table + "|" + df[id_col].astype(str)).map(_unified(VOICE_DB.stat().st_mtime, TAG_DB.stat().st_mtime))
    out = df.copy()
    out[col] = new.where(new.notna(), df[col])
    return out


def pool(d: pd.DataFrame) -> pd.DataFrame:
    """Consumer voice: the brand pool."""
    return d[(d["in_pool"] == 1) & d["brand_std"].notna()].reset_index(drop=True)


def category(d: pd.DataFrame) -> pd.DataFrame:
    return d[d["is_category"]].reset_index(drop=True)


def app(d: pd.DataFrame) -> pd.DataFrame:
    return d[d["source"] == APP].reset_index(drop=True)


def maps(d: pd.DataFrame) -> pd.DataFrame:
    return d[d["source"] == MAPS].reset_index(drop=True)


def own_posts(d: pd.DataFrame) -> pd.DataFrame:
    return d[(d["voice_type"] == "brand_owned") & (d["unit"] == "post") & d["owner_brand"].notna()].reset_index(drop=True)


def raw_counts() -> dict:
    """Items in voice_items by lens, and how many were analysed in the brand pool (for the sidebar and the data page)."""
    con = sqlite3.connect(f"file:{VOICE_DB.as_posix()}?mode=ro", uri=True)
    rows = con.execute("SELECT lens, COUNT(*), SUM(in_pool) FROM voice_items GROUP BY lens").fetchall()
    con.close()
    return {lens: {"collected": int(n), "pool": int(p or 0)} for lens, n, p in rows}


def consumer_funnel() -> dict:
    """Consumer-voice items split by what happened to them: in the brand pool, or why they are not (for the sidebar)."""
    con = sqlite3.connect(f"file:{VOICE_DB.as_posix()}?mode=ro", uri=True)
    r = con.execute(
        "SELECT COUNT(*), "
        "SUM(in_pool = 1), "
        "SUM(in_pool != 1 AND COALESCE(is_contest, 0) = 1), "
        "SUM(in_pool != 1 AND COALESCE(is_contest, 0) != 1 AND lens_relevant = 0), "
        "SUM(in_pool != 1 AND COALESCE(is_contest, 0) != 1 AND lens_relevant = 1 AND unit = 'comment' AND brand_relevant = 0), "
        "SUM(in_pool != 1 AND COALESCE(is_contest, 0) != 1 AND lens_relevant = 1 AND unit = 'post') "
        "FROM voice_items WHERE lens = 'consumer_voice'").fetchone()
    con.close()
    total, pool, giveaway, off_topic, no_brand, posts = (int(x or 0) for x in r)
    return {"collected": total, "pool": pool, "giveaway": giveaway, "off_topic": off_topic, "no_brand": no_brand,
            "posts": posts, "other": total - pool - giveaway - off_topic - no_brand - posts}


def raw_by_source() -> pd.DataFrame:
    """Per channel and unit: items collected, items in the brand pool, giveaway entries removed, and the lens."""
    con = sqlite3.connect(f"file:{VOICE_DB.as_posix()}?mode=ro", uri=True)
    r = pd.read_sql_query(
        "SELECT source, unit, lens, COUNT(*) AS collected, SUM(in_pool) AS pooled, "
        "SUM(CASE WHEN is_contest = 1 AND lens_relevant != 0 AND unit = 'comment' THEN 1 ELSE 0 END) AS giveaway "
        "FROM voice_items GROUP BY source, unit, lens", con)
    con.close()
    return r


# ---------------------------------------------------------------- statistics
def net(s) -> tuple | None:
    """(net sentiment in points, standard error in points, n) for labels; None when empty."""
    s = pd.Series(list(s), dtype=object)
    n = len(s)
    if n == 0:
        return None
    p, q = (s == "positive").mean(), (s == "negative").mean()
    return (p - q) * 100, float(np.sqrt(max(p + q - (p - q) ** 2, 0) / n) * 100), n


def net_text(s, min_n: int = ebi.MIN_N) -> str:
    r = net(s)
    if r is None or r[2] < min_n:
        return "-" if r is None else f"n={r[2]}"
    return f"{r[0]:+.0f}"


def gap(a, b) -> dict:
    """Focus-vs-peers gap in net points with a 95% interval; empty dict when either side is empty."""
    ra, rb = net(a), net(b)
    if ra is None or rb is None:
        return {}
    g, se = ra[0] - rb[0], float(np.hypot(ra[1], rb[1]))
    return {"net_f": ra[0], "net_p": rb[0], "n_f": ra[2], "n_p": rb[2], "gap": g, "lo": g - 1.96 * se, "hi": g + 1.96 * se}


def two_prop_p(k1: int, n1: int, k2: int, n2: int):
    """Two-sided p-value of a two-proportion z-test (None when a side is empty)."""
    import math
    if n1 == 0 or n2 == 0:
        return None
    pp = (k1 + k2) / (n1 + n2)
    se = math.sqrt(pp * (1 - pp) * (1 / n1 + 1 / n2))
    if se == 0:
        return 1.0
    return math.erfc(abs(k1 / n1 - k2 / n2) / se / math.sqrt(2))


def grade(a, b, by_channel: list) -> dict:
    """Evidence grade for 'focus vs peers'. a, b = polarity labels; by_channel = [(channel, focus labels, peer labels)].
    Not readable under MIN_N on either side; Level when the gap interval holds zero; B when it does not; A when the same
    sign also shows in 2+ channels that each have MIN_N on both sides."""
    out = {"grade": "Not readable", "net_f": None, "net_p": None, "gap": None, "lo": None, "hi": None, "where": []}
    if len(a) < ebi.MIN_N or len(b) < ebi.MIN_N:
        return out
    g = gap(a, b)
    out.update({k: g[k] for k in ("net_f", "net_p", "gap", "lo", "hi")})
    if g["lo"] <= 0 <= g["hi"]:
        out["grade"] = "Level"
        return out
    where = [c for c, fa, pb in by_channel
             if len(fa) >= ebi.MIN_N and len(pb) >= ebi.MIN_N and (net(fa)[0] - net(pb)[0]) * g["gap"] > 0]
    out["where"] = where
    out["grade"] = "A · corroborated" if len(where) >= 2 else "B · one channel"
    return out


GRADE_PHRASE = {"Not readable": "too few items to compare", "Level": "level with peers, the gap could be chance",
                "B · one channel": "a real gap, seen in one channel", "A · corroborated": "a real gap, confirmed in two or more channels"}


def grade_word(g: dict) -> str:
    if g["grade"] == "Not readable":
        return "not readable"
    if g["grade"] == "Level":
        return "level with peers"
    return "ahead of peers" if g["gap"] > 0 else "behind peers"


def brand_net(p: pd.DataFrame, col: str = "sentiment") -> pd.DataFrame:
    """One row per brand: n, sentiment shares, net sentiment and its 95% interval (None under MIN_N)."""
    rows = []
    for b in charts.BRAND_ORDER:
        s = p.loc[p["brand_std"] == b, col]
        if s.empty:
            continue
        r = net(s)
        ok = r[2] >= ebi.MIN_N
        rows.append({"brand": b, "n": r[2], "net": r[0] if ok else None, "lo": r[0] - 1.96 * r[1] if ok else None,
                     "hi": r[0] + 1.96 * r[1] if ok else None,
                     **{k: (s == k).mean() * 100 for k in SENT}})
    return pd.DataFrame(rows)


def channel_gaps(p: pd.DataFrame, focus: str = FOCAL) -> pd.DataFrame:
    """Focus vs the other brands pooled, per channel: both sides' n and net, the gap with its interval, and which peer
    brand supplies most of the peer items (a channel whose peers are one brand is a brand-vs-brand read, not 'vs peers')."""
    rows = []
    for c in CHANNELS:
        f, o = p[(p["source"] == c) & (p["brand_std"] == focus)], p[(p["source"] == c) & (p["brand_std"] != focus)]
        if f.empty and o.empty:
            continue
        g = gap(f["sentiment"], o["sentiment"]) if len(f) and len(o) else {}
        top = o["brand_std"].value_counts()
        rows.append({"channel": c, "n_f": len(f), "n_p": len(o), "net_f": g.get("net_f"), "net_p": g.get("net_p"),
                     "gap": g.get("gap"), "lo": g.get("lo"), "hi": g.get("hi"),
                     "ok": len(f) >= ebi.MIN_N and len(o) >= ebi.MIN_N,
                     "peer_top": top.index[0] if len(top) else None,
                     "peer_top_share": top.iloc[0] / len(o) * 100 if len(top) else None})
    return pd.DataFrame(rows)


def standardised(p: pd.DataFrame, focus: str = FOCAL, min_n: int = ebi.MIN_COUNT, col: str = "sentiment") -> dict:
    """Focus-vs-peers net-sentiment gap re-weighted to one channel mix: channels where both sides have min_n+ items, each
    weighted by its share of the pooled items there. Removes the effect of brands being strong on different channels."""
    use, w, nf, npp, vf, vp = [], [], [], [], 0.0, 0.0
    parts = []
    for c in CHANNELS:
        f, o = p[(p["source"] == c) & (p["brand_std"] == focus)][col], p[(p["source"] == c) & (p["brand_std"] != focus)][col]
        if len(f) >= min_n and len(o) >= min_n:
            parts.append((c, len(f) + len(o), net(f), net(o)))
    if not parts:
        return {}
    tot = sum(x[1] for x in parts)
    for c, n, rf, ro in parts:
        wt = n / tot
        use.append(c)
        nf.append(wt * rf[0])
        npp.append(wt * ro[0])
        vf += (wt * rf[1]) ** 2
        vp += (wt * ro[1]) ** 2
    g = sum(nf) - sum(npp)
    se = float(np.sqrt(vf + vp))
    return {"channels": use, "net_f": sum(nf), "net_p": sum(npp), "gap": g, "lo": g - 1.96 * se, "hi": g + 1.96 * se,
            "n": tot, "thin": any(min(x[2][2], x[3][2]) < ebi.MIN_N for x in parts)}


def group_labels(d: pd.DataFrame, group: str) -> pd.Series:
    """Polarity the model gave `group` on every item of d that touches it."""
    return pd.Series([gp[group] for gp in d["gpol"] if group in gp], dtype=object)


def group_table(p: pd.DataFrame, focus: str = FOCAL) -> pd.DataFrame:
    """Per decision group: how many items touch it (focus and peers), share of each side's items, net sentiment, gap and grade."""
    f_all, o_all = p[p["brand_std"] == focus], p[p["brand_std"] != focus]
    rows = []
    for g in GROUP_LIST:
        a, b = group_labels(f_all, g), group_labels(o_all, g)
        chans = [(c, group_labels(f_all[f_all["source"] == c], g), group_labels(o_all[o_all["source"] == c], g)) for c in CHANNELS]
        gr = grade(a, b, chans)
        rows.append({"group": g, "n_f": len(a), "n_p": len(b),
                     "share_f": len(a) / len(f_all) * 100 if len(f_all) else None,
                     "share_p": len(b) / len(o_all) * 100 if len(o_all) else None, **gr})
    return pd.DataFrame(rows)


def brand_cells(p: pd.DataFrame, keys: list, level: str = "group") -> dict:
    """{(brand, key): {n, share, net, base}} for every brand on every decision group (level='group') or theme (level='theme').
    n = the brand's items that touch the key, share = n as % of the brand's items, net = net sentiment of the polarity the model gave
    that key (None under MIN_N). Every brand is shown, not just the focus brand."""
    out = {}
    for b in charts.BRAND_ORDER:
        s = p[p["brand_std"] == b]
        if s.empty:
            continue
        for k in keys:
            labs = ([gp[k] for gp in s["gpol"] if k in gp] if level == "group"
                    else [pl[k] for pl, th in zip(s["pol"], s["themes"]) if k in th])
            n = len(labs)
            r = net(labs) if n >= ebi.MIN_N else None
            out[(b, k)] = {"n": n, "share": n / len(s) * 100, "net": r[0] if r else None, "base": len(s)}
    return out


def theme_table(p: pd.DataFrame, focus: str = FOCAL) -> pd.DataFrame:
    """The same read at the eight-theme level (detail under the groups)."""
    f_all, o_all = p[p["brand_std"] == focus], p[p["brand_std"] != focus]

    def lab(d, t):
        return pd.Series([pl[t] for pl, th in zip(d["pol"], d["themes"]) if t in th], dtype=object)
    rows = []
    for t in THEMES:
        a, b = lab(f_all, t), lab(o_all, t)
        chans = [(c, lab(f_all[f_all["source"] == c], t), lab(o_all[o_all["source"] == c], t)) for c in CHANNELS]
        rows.append({"theme": t, "group": theme_tags.GROUP_OF[t], "n_f": len(a), "n_p": len(b), **grade(a, b, chans)})
    return pd.DataFrame(rows)


def group_share(d: pd.DataFrame) -> dict:
    """{group or NO_THEME: share of the rows}, plus 'n'."""
    n = len(d)
    out = {"n": n}
    for g in GROUP_LIST:
        out[g] = sum(g in gs for gs in d["groups"]) / n * 100 if n else None
    out[NO_THEME] = sum(len(gs) == 0 for gs in d["groups"]) / n * 100 if n else None
    return out


def complaints(d: pd.DataFrame) -> pd.DataFrame:
    """One definition of a complaint: an item that is negative or mixed on a theme group. One row per item and group."""
    rows = []
    for r in d.itertuples():
        for g, pol in r.gpol.items():
            if pol in ("negative", "mixed"):
                rows.append((r.item_id, g, pol))
    return pd.DataFrame(rows, columns=["item_id", "group", "pol"])


def app_eras(a: pd.DataFrame) -> pd.DataFrame:
    rows = []
    for label, y0, y1 in ERAS:
        s = a[(a["date"].dt.year >= y0) & (a["date"].dt.year <= y1)]
        n = len(s)
        rows.append({"era": label, "n": n, "neg": (s["sentiment"] == "negative").mean() * 100 if n else None,
                     "stars": s["rating_native"].mean() if n else None})
    return pd.DataFrame(rows)


def coverage_matrix(p: pd.DataFrame) -> pd.DataFrame:
    """Brand x channel item counts in the pool."""
    return (p.groupby(["brand_std", "source"]).size().unstack(fill_value=0)
            .reindex(index=charts.BRAND_ORDER, columns=CHANNELS, fill_value=0))


# ---------------------------------------------------------------- items behind a number
def view(d: pd.DataFrame, limit: int = 300) -> pd.DataFrame:
    """Items as a reader sees them: when, where, who, how it was read, the words, and a link. Newest first."""
    v = d.sort_values("date", ascending=False, na_position="last").head(limit)
    return pd.DataFrame({
        "Date": v["date"].dt.strftime("%Y-%m-%d").fillna(""),
        "Channel": v["source"],
        "Brand": v["brand_std"].fillna(v["retailer"]).fillna(""),
        "Sentiment": v["sentiment"],
        "Themes": v["themes"].map(", ".join),
        "Text": v["text"].str.slice(0, 600),
        "Link": v["url"],
    })


LINK_CFG = {"Link": st.column_config.LinkColumn("Link", display_text="open", width="small"),
            "Text": st.column_config.TextColumn("Text", width="large")}
