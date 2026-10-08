"""
Insight layer for the story pages: turns the dashboard's frames into the three things a
marketer reads first — what the numbers show, why, and what it suggests — plus the
coverage numbers (analysed of collected) behind them. Rule-based; no LLM at runtime.

The Brand Health score: per source, the share of labelled items (positive, neutral, mixed or negative) that are
positive or neutral, then a sqrt(n)-weighted mean over the sources that have at least MIN_SOURCE_N analysed items
for the brand. Mixed items stay in the base (they count as not positive-or-neutral), so every percentage on every
page is read from the same n as the sentiment-mix bars.
"""

import json
import math

import pandas as pd
import streamlit as st

import barrier_taxonomy
import theme_tags
import charts
import ebi
from sg_common import FB_DB, IG_DB, REDDIT_DB, SG_DB, XHS_DB, YT_DB, normalize_brand, read_table, xhs_attributed

PACK_BAND = 5            # a brand score within this many points of the peer median counts as "within the pack"
MIN_SOURCE_N = 5         # fewest analysed items a source needs to count towards a brand's score
LABELS = ("positive", "neutral", "mixed", "negative")  # every usable label
VALID = LABELS   # the base of every percentage is ALL labelled items, so a % always matches the bars of the mix chart (n is the same)
APP_SOURCE = "MyACUVUE app"
FOCAL = "Acuvue"

# What each reason suggests for a brand marketer. Phrased as hypotheses to test, not conclusions.
IMPLICATIONS = {
    # theme level (Brand Health complaints, Journey headline)
    "Comfort & product": "Comfort is the core promise: lead with comfort proof and fitting advice, and check handling support for new wearers.",
    "Price & value": "Value is not obvious: test cost-per-day and trial offers before discounting.",
    "Look & colour": "Cosmetic buyers judge on look: show colour and fit more clearly.",
    "Trust & authenticity": "Doubt about genuine product is a trust issue: make authorised-seller proof easy to find.",
    "Access & availability": "People cannot find where to buy: show authorised stockists and online options.",
    "Fitting & guidance": "Fitting, prescription and handling steps slow people down: simplify the path to a first fitting and support new wearers.",
    "Loyalty & app": "Sign-up, points and message volume cost goodwill: fix sign-up and login first, then simplify the points rules and review send frequency.",
    "Service": "Store experience undercuts the brand: train retailers and promote no-upsell fitting.",
    # barrier label level (app reviews, WhatsApp map)
    "Registration / login friction": "Fix sign-up and login first: they lose people before any lens decision.",
    "Loyalty & rewards": "Loyalty rules (points tied to one store, redemption limits) breed complaints: test simpler rules.",
    "Unwanted messaging / privacy": "Message volume and data-sharing worries erode goodwill: review consent wording and send frequency.",
    "App utility & support": "The app reads as a points tracker: add reorder and lens-change reminders and a way to get help.",
    "Product experience": "Comfort is the core promise: lead with comfort proof and fitting advice.",
    "Fear / handling difficulty": "New wearers fear handling the lens: offer teaching, a trial pair and a first-week check-in.",
    "Colour & look (cosmetic lenses)": "Cosmetic buyers judge on look: show colour and fit more clearly.",
    "Store service & upsell": "Store experience undercuts the brand: train retailers and promote no-upsell fitting.",
    "Price & channel cost": "Value is not obvious: test cost-per-day and trial offers before discounting.",
    "Authenticity & quality control": "Doubt about genuine product is a trust issue: make authorised-seller proof easy to find.",
    "Lack of professional guidance": "Fitting and prescription steps slow people down: simplify the path to a first fitting.",
    "Availability & where to buy": "People cannot find where to buy: show authorised stockists and online options.",
    barrier_taxonomy.OTHER: "Unmatched comments: read them for new themes.",
}


# ---------------------------------------------------------------------------
# Source frames: analysed items and collected counts, same shape for every source
# ---------------------------------------------------------------------------

_RAW_COMMENTS = {
    "Reddit": (REDDIT_DB, "reddit_comments"),
    "YouTube": (YT_DB, "yt_comments"),
    "Instagram": (IG_DB, "ig_comments"),
    "Facebook": (FB_DB, "fb_comments"),
}


@st.cache_data(ttl=3600, show_spinner=False, max_entries=2)
def raw_collected() -> dict:
    """Comments actually scraped per brand and channel, straight from the databases. The dashboard's
    loaders already drop comments on posts judged off-brand or not SG, so counting from those frames
    would understate what was collected (e.g. Alcon YouTube: 160 scraped, 5 left after that step)."""
    out = {}
    for src, (db, table) in _RAW_COMMENTS.items():
        d = read_table(db, f"SELECT brand, COUNT(*) AS n FROM {table} GROUP BY brand")
        if d.empty:
            out[src] = pd.Series(dtype=int)
            continue
        d["brand"] = d["brand"].map(normalize_brand)
        out[src] = d.groupby("brand")["n"].sum()
    return out

def _abs_url(u):
    """Reddit stores relative permalinks; everything else is already absolute."""
    if isinstance(u, str) and u.startswith("/r/"):
        return "https://www.reddit.com" + u
    return u if isinstance(u, str) else None


def _clean(df: pd.DataFrame, brand_col: str, sent_col: str, date_col: str, text_col: str = None, urls=None) -> pd.DataFrame:
    """Analysed items: brand, sentiment (one of LABELS), date, text, url. urls is a list/array aligned with df rows."""
    cols = ["brand", "sentiment", "date", "text", "url"]
    if df is None or df.empty:
        return pd.DataFrame(columns=cols)
    out = pd.DataFrame({
        "brand": df[brand_col].values,
        "sentiment": df[sent_col].values,
        "date": pd.to_datetime(df[date_col], errors="coerce", utc=True).dt.tz_localize(None).values if date_col in df.columns else pd.NaT,
        "text": df[text_col].values if text_col and text_col in df.columns else None,
        "url": list(urls) if urls is not None else None,
    })
    return out[out["sentiment"].isin(LABELS)]


_BLANK = {"collected": pd.Series(dtype=int), "analysed": pd.DataFrame(columns=["brand", "sentiment", "date", "text", "url"])}


@st.cache_data(ttl=3600, show_spinner=False, max_entries=2)
def _extra_sources() -> tuple:
    """Two consumer sources that live outside the dashboard's main frames: KiasuParents forum posts and
    Xiaohongshu comments (a comment takes the brand and relevance of the post it sits under)."""
    forum = read_table(SG_DB, "SELECT brand, post_date, post_title, content_summary, post_url, sentiment, topic_tags FROM forum_posts")
    if not forum.empty:
        def _sent(row):
            if pd.notna(row["sentiment"]):
                return row["sentiment"]
            try:
                return json.loads(row["topic_tags"]).get("sentiment")
            except Exception:
                return None
        forum["sentiment"] = forum.apply(_sent, axis=1)
        forum["brand"] = forum["brand"].map(normalize_brand)
        forum["text"] = forum["content_summary"].fillna(forum["post_title"])
    xc = read_table(XHS_DB, "SELECT c.sentiment, c.content_en, p.brand AS search_brand, p.brand_mentioned, p.brand_relevant, p.url "
                            "FROM xhs_comments c JOIN xhs_posts p ON p.post_id = c.post_id")
    if not xc.empty:
        xc["brand_mentioned"] = xc["brand_mentioned"].map(normalize_brand)
        xc["search_brand"] = xc["search_brand"].map(normalize_brand)
    return forum, xc


def build_frames(reviews: pd.DataFrame, xhs: pd.DataFrame, social: dict) -> dict:
    """{source: {"collected": Series(brand -> n), "analysed": DataFrame(brand, sentiment, date, text, url)}}.

    The pool = every consumer data point that (1) is attributed to one of the five brands, (2) was judged relevant
    (on-topic, on-brand, Singapore where the scraper can tell), and (3) carries one of the four sentiment labels
    (Positive, Neutral, Mixed, Negative). Sources: Lazada reviews, KiasuParents, Xiaohongshu posts and comments,
    Reddit, YouTube, Instagram and Facebook comments. Brand-owned posts, MyACUVUE app reviews (ACUVUE only), Google Maps
    retailer reviews and listings are not in the pool (see inventory).

    social maps a source name to (raw_comments_df, module) where module.on_topic_comments drops
    off-topic items. Collected = rows scraped for the brand; analysed = relevant items with a usable
    sentiment label (what every chart on the page is drawn from)."""
    frames = {}
    raw = raw_collected()
    forum, xc = _extra_sources()

    rev = reviews.copy() if reviews is not None else pd.DataFrame()
    if not rev.empty:
        # Same label scale as every other channel: the model's label on the review text; the star rating only fills a gap.
        stars = rev["rating"].map(lambda r: None if pd.isna(r) or r <= 0 else "positive" if r >= 4 else "neutral" if r == 3 else "negative")
        rev["sentiment"] = rev["sentiment"].where(rev["sentiment"].isin(LABELS), stars)
        frames["Lazada reviews"] = {
            "collected": rev.groupby("brand").size(),
            "analysed": _clean(rev, "brand", "sentiment", "review_date", "review_text"),
        }
    else:
        frames["Lazada reviews"] = _BLANK

    if not forum.empty:
        frames["KiasuParents"] = {
            "collected": forum.groupby("brand").size(),
            "analysed": _clean(forum, "brand", "sentiment", "post_date", "text", urls=forum["post_url"]),
        }
    else:
        frames["KiasuParents"] = _BLANK

    if xhs is not None and not xhs.empty:
        attributed = xhs_attributed(xhs)
        frames["Xiaohongshu"] = {
            "collected": xhs.groupby("brand").size(),
            "analysed": _clean(attributed, "brand_mentioned", "sentiment", "publish_date", "content_en", urls=attributed["url"]),
        }
    else:
        frames["Xiaohongshu"] = _BLANK

    if not xc.empty:
        att = xhs_attributed(xc)
        frames["Xiaohongshu comments"] = {
            "collected": xc.groupby("search_brand").size(),
            "analysed": _clean(att, "brand_mentioned", "sentiment", "date_none", "content_en", urls=att["url"]),
        }
    else:
        frames["Xiaohongshu comments"] = _BLANK

    for name in ("Reddit", "YouTube", "Instagram", "Facebook"):
        loaded, module = social.get(name, (None, None))
        if loaded is None or loaded.empty:
            frames[name] = {"collected": raw.get(name, pd.Series(dtype=int)), "analysed": _BLANK["analysed"]}
            continue
        on = module.on_topic_comments(loaded)
        posts = module.load_sg_dashboard_data()[0]
        urls = posts.drop_duplicates("post_key").set_index("post_key")["url_display"].map(_abs_url) if not posts.empty else pd.Series(dtype=object)
        frames[name] = {
            "collected": raw.get(name, loaded.groupby("brand").size()),
            "analysed": _clean(on, "brand", "sentiment", "date", "text_display", urls=on["post_key"].map(urls).values if "post_key" in on.columns else None),
        }
        if "is_contest" in loaded.columns:   # on-topic comments that answer a giveaway: removed from the pool, counted for the note
            frames[name]["contest_removed"] = int((loaded["is_contest"].fillna(False).astype(bool) & (loaded["is_lens_relevant"] != 0)).sum())
    return frames


def coverage(frames: dict, brands: list) -> pd.DataFrame:
    """One row per brand x source: collected, analysed, % positive-or-neutral, % negative, status."""
    rows = []
    for b in brands:
        for s in charts.SOURCE_ORDER:
            f = frames.get(s, {})
            collected = int(f.get("collected", pd.Series(dtype=int)).get(b, 0))
            a = f.get("analysed", pd.DataFrame())
            a = a[a["brand"] == b] if not a.empty else a
            n = len(a)
            v = a[a["sentiment"].isin(VALID)] if n else a
            scored_n = len(v)
            pos_neu = float(v["sentiment"].isin(["positive", "neutral"]).mean() * 100) if scored_n else None
            neg = float((v["sentiment"] == "negative").mean() * 100) if scored_n else None
            status = "ok" if scored_n >= MIN_SOURCE_N else ("none" if collected == 0 else "thin")
            rows.append({"brand": b, "source": s, "collected": collected, "analysed": n, "scored_n": scored_n,
                         "pos_neu": pos_neu, "neg": neg, "status": status})
    return pd.DataFrame(rows)


def exclusions(cov: pd.DataFrame, channels: list | None = None) -> pd.DataFrame:
    """Per channel: items collected, items that reached the sentiment pool, and the items removed on the way
    (off-brand, non-Singapore, off-topic, giveaway entry or no sentiment label). `cov` is coverage(). Removed never goes below zero:
    Xiaohongshu is collected under the search brand but analysed under the brand mentioned, so a brand can gain items."""
    rows = []
    for s in channels or charts.SOURCE_ORDER:
        d = cov[cov["source"] == s]
        coll, ana = int(d["collected"].sum()), int(d["scored_n"].sum())
        rows.append({"Channel": s, "Collected": coll, "In the sentiment pool": ana, "Removed": max(coll - ana, 0)})
    return pd.DataFrame(rows)


def scope_note(cov: pd.DataFrame, channels: list | None = None, what: str = "Sentiment") -> str:
    """One sentence saying what a sentiment chart is built from and what was left out, so a smaller count than
    'collected' reads as a filter, not a bug. Names the channel that lost the most items."""
    ex = exclusions(cov, channels)
    coll, ana, rem = int(ex["Collected"].sum()), int(ex["In the sentiment pool"].sum()), int(ex["Removed"].sum())
    if coll == 0:
        return f"{what} only: nothing collected for this selection."
    text = (f"{what} only: {ana:,} of {coll:,} collected items are used. {rem:,} were removed as off-brand, "
            "non-Singapore, off-topic, giveaway entries or without a sentiment label")
    big = ex.sort_values("Removed", ascending=False).iloc[0]
    if len(ex) > 1 and rem and big["Removed"] >= 0.3 * rem:
        text += f" (most from {big['Channel']}: {int(big['Removed']):,} of {int(big['Collected']):,})"
    return text + "."


def scores(cov: pd.DataFrame) -> dict:
    """{brand: {"score": float|None, "components": [(source, pos_neu_pct, n)]}} from the coverage table."""
    out = {}
    for b, g in cov.groupby("brand", sort=False):
        comps = [(r.source, r.pos_neu, r.scored_n) for r in g.itertuples() if r.status == "ok"]
        if not comps:
            out[b] = {"score": None, "components": []}
            continue
        w = [n ** 0.5 for _, _, n in comps]
        out[b] = {"score": sum(p * wi for (_, p, _), wi in zip(comps, w)) / sum(w), "components": comps}
    return out


def band(score) -> str:
    if score is None:
        return "No score"
    return "Healthy" if score >= 65 else "Mixed" if score >= 45 else "At risk"


def verdict(sc: dict, focus: str = FOCAL) -> dict:
    """Plain-language read of where the focal brand stands among the scored brands."""
    scored = {b: v["score"] for b, v in sc.items() if v["score"] is not None}
    if focus not in scored:
        return {"text": f"{focus} cannot be scored: no source has {MIN_SOURCE_N} or more analysed items.", "rank": None}
    peers = [s for b, s in scored.items() if b != focus]
    ranked = sorted(scored, key=lambda b: -scored[b])
    rank = ranked.index(focus) + 1
    text = f"{focus} scores {scored[focus]:.0f} ({band(scored[focus]).lower()})"
    in_pack, spread = None, None
    if peers:
        med = float(pd.Series(peers).median())
        d = scored[focus] - med
        spread = (min(scored.values()), max(scored.values()))
        in_pack = abs(d) < PACK_BAND
        # The order of brands is not quoted: scores sit close together and rest on different channels, so a rank would overstate the gap.
        text += (f", within the pack: {abs(d):.0f} point{'' if round(abs(d)) == 1 else 's'} {'above' if d >= 0 else 'below'} the peer median ({med:.0f})"
                 if in_pack else
                 f", {abs(d):.0f} points {'above' if d >= 0 else 'below'} the peer median ({med:.0f})")
        text += f". Brand scores run from {spread[0]:.0f} to {spread[1]:.0f}"
    return {"text": text + ".", "rank": rank, "score": scored[focus], "scored": len(scored), "in_pack": in_pack, "spread": spread}


def monthly_trend(frames: dict, brands: list) -> pd.DataFrame:
    """Monthly % positive-or-neutral per brand, sqrt(n)-weighted across sources. Columns: month, Brand, pct, n."""
    parts = []
    for s, f in frames.items():
        a = f["analysed"]
        if a.empty:
            continue
        a = a[a["brand"].isin(brands) & a["sentiment"].isin(VALID)].dropna(subset=["date"])
        if a.empty:
            continue
        a = a.assign(month=a["date"].dt.to_period("M").astype(str), pos=a["sentiment"].isin(["positive", "neutral"]))
        parts.append(a.groupby(["brand", "month"]).agg(pos=("pos", "sum"), n=("pos", "size")).reset_index())
    if not parts:
        return pd.DataFrame(columns=["month", "Brand", "pct", "n"])
    m = pd.concat(parts, ignore_index=True)
    m["w"] = m["n"] ** 0.5
    m["wp"] = m["pos"] / m["n"] * 100 * m["w"]
    g = m.groupby(["brand", "month"]).agg(wp=("wp", "sum"), w=("w", "sum"), n=("n", "sum")).reset_index()
    g["pct"] = g["wp"] / g["w"]
    return g.rename(columns={"brand": "Brand"})[["month", "Brand", "pct", "n"]]


# ---------------------------------------------------------------------------
# Why: reasons behind negative / mixed items
# ---------------------------------------------------------------------------

def negative_items(frames: dict, brands: list) -> pd.DataFrame:
    """One row per distinct negative or mixed item in the pool (any channel), one row per reason it matches.

    This reads the same analysed items as every other number on the Brand Health page, so a count of negative items
    always reconciles with the sentiment mix. MyACUVUE app reviews are not in the pool (ACUVUE only)."""
    parts = []
    for src_name, f in frames.items():
        a = f["analysed"]
        if a.empty:
            continue
        d = a[a["brand"].isin(brands) & a["sentiment"].isin(["negative", "mixed"])].assign(source=src_name)
        parts.append(d[["source", "brand", "sentiment", "text", "url"]])
    if not parts:
        return pd.DataFrame(columns=["source", "brand", "sentiment", "text", "url", "reason"])
    d = pd.concat(parts, ignore_index=True).dropna(subset=["text"]).drop_duplicates(["source", "brand", "text"])
    d["reason"] = d["text"].map(barrier_taxonomy.themes_of)      # theme level: one list for every brand view
    return d.explode("reason")


def reasons(neg: pd.DataFrame, focus: str, peers: list) -> pd.DataFrame:
    """Reasons ranked by how often they appear in the focus brand's negative/mixed items, versus peers.

    An item can carry several reasons, so shares can add to more than 100%. A share is only shown
    when its base is at least ebi.MIN_N items; below that the count is shown instead."""
    f = neg[neg["brand"] == focus]
    p = neg[neg["brand"].isin(peers)]
    nf, npeer = f.drop_duplicates(["source", "brand", "text"]).shape[0], p.drop_duplicates(["source", "brand", "text"]).shape[0]
    rows = []
    for reason in list(theme_tags.THEMES) + [barrier_taxonomy.OTHER]:
        kf = int((f["reason"] == reason).sum())
        kp = int((p["reason"] == reason).sum())
        if kf == 0 and kp == 0:
            continue
        share_f = kf / nf * 100 if nf >= ebi.MIN_N else float("nan")
        share_p = kp / npeer * 100 if npeer >= ebi.MIN_N else float("nan")
        rows.append({
            "reason": reason, "brand_k": kf, "peer_k": kp,
            "brand_share": share_f, "peer_share": share_p,
            "brand_text": f"{share_f:.0f}% ({kf})" if nf >= ebi.MIN_N else f"{kf} of {nf}",
            "peer_text": f"{share_p:.0f}% ({kp})" if npeer >= ebi.MIN_N else f"{kp} of {npeer}",
            "gap": share_f - share_p if nf >= ebi.MIN_N and npeer >= ebi.MIN_N else float("nan"),
        })
    df = pd.DataFrame(rows)
    if df.empty:
        return df
    df["_other"] = df["reason"] == barrier_taxonomy.OTHER
    df = df.sort_values(["_other", "brand_k"], ascending=[True, False]).drop(columns="_other").reset_index(drop=True)
    df.attrs["n_focus"], df.attrs["n_peers"] = nf, npeer
    return df


def quotes(neg: pd.DataFrame, brand: str, reason: str, k: int = 2) -> pd.DataFrame:
    """Up to k readable verbatims for a brand and reason, preferring different sources."""
    d = neg[(neg["brand"] == brand) & (neg["reason"] == reason)].copy()
    d["len"] = d["text"].astype(str).str.len()
    d = d[(d["len"] >= 40) & (d["len"] <= 400)].sort_values("len", ascending=False)
    picked = d.drop_duplicates("source").head(k)
    if len(picked) < k:
        picked = pd.concat([picked, d.drop(picked.index).head(k - len(picked))])
    return picked[["source", "text", "url"]]


def wilson(k: int, n: int, z: float = 1.96) -> tuple:
    """95% Wilson interval (in %) for k of n. Wider than the plain normal interval at small n, and never leaves 0-100."""
    if n <= 0:
        return None, None
    p = k / n
    d = 1 + z * z / n
    centre = p + z * z / (2 * n)
    half = z * math.sqrt(p * (1 - p) / n + z * z / (4 * n * n))
    return (centre - half) / d * 100, (centre + half) / d * 100


def two_prop_p(k1: int, n1: int, k2: int, n2: int):
    """Two-sided p-value that two shares (k1/n1 vs k2/n2) are equal, by a pooled two-proportion z-test. None if undefined."""
    if min(n1, n2) <= 0:
        return None
    p = (k1 + k2) / (n1 + n2)
    se = math.sqrt(p * (1 - p) * (1 / n1 + 1 / n2))
    if se == 0:
        return None
    return math.erfc(abs(k1 / n1 - k2 / n2) / se / math.sqrt(2))


def pool(frames: dict, brands: list) -> pd.DataFrame:
    """Every analysed item of the selected brands in one frame, with its source. Columns: source, brand, sentiment, date, text, url."""
    parts = [f["analysed"].assign(source=s_) for s_, f in frames.items() if not f["analysed"].empty]
    if not parts:
        return pd.DataFrame(columns=["source", "brand", "sentiment", "date", "text", "url"])
    p = pd.concat(parts, ignore_index=True)
    return p[p["brand"].isin(brands)]


def rollup(frames: dict, brands: list) -> pd.DataFrame:
    """One row per brand, pooling every data point in the pool: volume, share of voice, sentiment mix, net sentiment
    (% positive minus % negative), % positive-or-neutral with its 95% interval, and how concentrated the items are in one channel.
    Percentages are only filled when the brand has at least ebi.MIN_N items; otherwise they are None and the count stands alone."""
    p = pool(frames, brands)
    total = len(p)
    rows = []
    for b in brands:
        a = p[p["brand"] == b]
        n = len(a)
        vc = a["sentiment"].value_counts()
        k = {lab: int(vc.get(lab, 0)) for lab in LABELS}
        pn = k["positive"] + k["neutral"]
        ok = n >= ebi.MIN_N
        lo, hi = wilson(pn, n) if ok else (None, None)
        src = a["source"].value_counts()
        rows.append({
            "brand": b, "n": n, "channels": int(a["source"].nunique()), "sov": n / total * 100 if total else None,
            **{f"k_{lab}": k[lab] for lab in LABELS},
            **{f"pct_{lab}": (k[lab] / n * 100 if ok else None) for lab in LABELS},
            "net": ((k["positive"] - k["negative"]) / n * 100) if ok else None,
            "k_pn": pn, "pn": pn / n * 100 if ok else None, "lo": lo, "hi": hi,
            "top_source": src.index[0] if len(src) else None, "top_share": src.iloc[0] / n * 100 if len(src) else None,
        })
    return pd.DataFrame(rows)


def vs_peers(roll: pd.DataFrame, focus: str) -> dict:
    """Focus brand against the other brands pooled: both shares positive-or-neutral, the gap, and whether it is distinguishable
    from chance (two-proportion test, 95%). Empty dict if either side has under ebi.MIN_N items."""
    f = roll[roll["brand"] == focus]
    p = roll[roll["brand"] != focus]
    if f.empty or p.empty:
        return {}
    nf, kf = int(f.iloc[0]["n"]), int(f.iloc[0]["k_pn"])
    npe, kp = int(p["n"].sum()), int(p["k_pn"].sum())
    if nf < ebi.MIN_N or npe < ebi.MIN_N:
        return {}
    pv = two_prop_p(kf, nf, kp, npe)
    return {"focus_pn": kf / nf * 100, "peer_pn": kp / npe * 100, "gap": kf / nf * 100 - kp / npe * 100,
            "nf": nf, "npeer": npe, "p": pv, "distinct": pv is not None and pv < 0.05}


# Data that exists in the project but is NOT pooled, with the reason a marketer can repeat. Counts are supplied by the app.
EXCLUDED = {
    "Posts, videos and threads": ("Carry reach, not sentiment; the comments under them are pooled.", "Conversation & content"),
    "MyACUVUE app reviews": ("ACUVUE only; no peer.", "see Owned experience"),
    "Google Maps retailer reviews": ("About stores, not brands.", "Journey & barriers"),
    "Product listings and prices": ("Not opinions.", "Market & Channel"),
    "Google Trends": ("A search index, not content.", "Evidence & Stage 2"),
}
_POOL_WHAT = {
    "Lazada reviews": "Star-rated product reviews, Singapore",
    "KiasuParents": "Parent-forum posts",
    "Xiaohongshu": "Consumer posts that name a tracked brand",
    "Xiaohongshu comments": "Comments under those posts",
    "Reddit": "Comments on relevant threads",
    "YouTube": "Comments on relevant videos",
    "Instagram": "Comments on relevant posts",
    "Facebook": "Comments on brand-page posts",
}


def inventory(frames: dict, brands: list, extras: dict | None = None) -> pd.DataFrame:
    """Every data source in the project and whether it is pooled. Columns: Source, What it is, Collected, In the pool, Status, Where it is used."""
    rows = []
    for s_ in charts.SOURCE_ORDER:
        f = frames.get(s_)
        coll = int(f["collected"].reindex(brands).fillna(0).sum()) if f is not None and len(f["collected"]) else 0
        a = f["analysed"] if f is not None else pd.DataFrame()
        used = int(a["brand"].isin(brands).sum()) if len(a) else 0
        rows.append({"Source": s_, "What it is": _POOL_WHAT.get(s_, ""), "Collected": f"{coll:,}" if coll else charts.NO_DATA,
                     "In the pool": f"{used:,}" if used else charts.NO_DATA, "Status": "In the pool",
                     "Note": "Brand-tagged, relevant, labelled."})
    for name, (why, where) in EXCLUDED.items():
        n = (extras or {}).get(name)
        rows.append({"Source": name, "What it is": "", "Collected": f"{int(n):,}" if n else charts.NO_DATA,
                     "In the pool": "Kept apart", "Status": "Kept apart", "Note": f"{why} ({where})"})
    return pd.DataFrame(rows)


def _recent_delta(frames: dict, brand: str, days: int = 90) -> dict:
    """% positive-or-neutral for the last `days` before the cut-off versus the `days` before that.
    Unweighted pool of all sources; delta is None unless both windows have at least ebi.MIN_N items."""
    parts = [f["analysed"] for f in frames.values() if not f["analysed"].empty]
    out = {"recent": None, "prev": None, "delta": None, "n_recent": 0, "n_prev": 0}
    if not parts:
        return out
    a = pd.concat(parts, ignore_index=True)
    a = a[(a["brand"] == brand) & a["sentiment"].isin(VALID)].dropna(subset=["date"])
    end = pd.Timestamp(ebi.CUTOFF_DATE)
    win = pd.Timedelta(days=days)
    cur, prv = a[(a["date"] > end - win) & (a["date"] <= end)], a[(a["date"] > end - 2 * win) & (a["date"] <= end - win)]
    out["n_recent"], out["n_prev"] = len(cur), len(prv)
    if len(cur) >= ebi.MIN_N and len(prv) >= ebi.MIN_N:
        out["recent"] = cur["sentiment"].isin(["positive", "neutral"]).mean() * 100
        out["prev"] = prv["sentiment"].isin(["positive", "neutral"]).mean() * 100
        out["delta"] = out["recent"] - out["prev"]
    return out


def snapshot(frames: dict, brands: list, jf_all: pd.DataFrame, products: pd.DataFrame, focus: str = FOCAL) -> dict:
    """Everything the Summary snapshot shows, computed live: Acuvue tiles, a brand comparison table
    and three takeaways. All five brands are used so the comparison does not depend on sidebar filters."""
    brands = charts.order_brands(brands)
    cov = coverage(frames, brands)
    sc = scores(cov)
    v = verdict(sc, focus)
    peers = [b for b in brands if b != focus]

    # Share of voice: analysed items across all sources
    sov_n = cov.groupby("brand")["analysed"].sum().reindex(brands).fillna(0)
    sov = (sov_n / sov_n.sum() * 100) if sov_n.sum() else sov_n

    # Why: negative/mixed reasons (app reviews excluded so brands compare like-for-like)
    neg = negative_items(frames, brands)
    why = reasons(neg, focus, peers) if not neg.empty else pd.DataFrame()
    named = why[~why["reason"].eq(barrier_taxonomy.OTHER)] if not why.empty else why
    top_reason = named.iloc[0] if not named.empty else None
    n_focus = why.attrs.get("n_focus", 0) if not why.empty else 0

    # Median listing price by brand (compliant, de-duplicated listings)
    price = pd.Series(dtype=float)
    if products is not None and not products.empty:
        p = ebi.dedupe_listings(products)
        p = p[p["selling_price"].notna() & p["brand"].isin(brands)]
        price = p.groupby("brand")["selling_price"].median()
    focus_price = price.get(focus)

    rows = []
    for b in brands:
        nb = neg[neg["brand"] == b]["reason"].value_counts() if not neg.empty else pd.Series(dtype=int)
        nb = nb[nb.index != barrier_taxonomy.OTHER]
        rows.append({
            "Brand": b,
            "Health score": sc[b]["score"],
            "Band": band(sc[b]["score"]),
            "Share of voice %": float(sov.get(b, 0)),
            "Median price (SGD)": float(price[b]) if b in price.index else None,
            "Price vs Acuvue %": (float(price[b]) / focus_price - 1) * 100 if focus_price and b in price.index and b != focus else None,
            "Top complaint": nb.index[0] if len(nb) else "n/a (too few)",
        })
    table = pd.DataFrame(rows)

    app = app_story(jf_all)
    trend = _recent_delta(frames, focus)
    cov_f = cov[cov["brand"] == focus]
    vp = vs_peers(rollup(frames, brands), focus)
    snap = {
        "verdict": v, "vs_peers": vp, "score": sc.get(focus, {}).get("score"), "band": band(sc.get(focus, {}).get("score")),
        "trend": trend, "sov": float(sov.get(focus, 0)), "top_reason": top_reason, "n_focus_neg": n_focus,
        "app": app, "table": table, "scored_sources": int((cov_f["status"] == "ok").sum()),
        "analysed": int(cov_f["analysed"].sum()), "thin": int(cov_f["scored_n"].sum()) < ebi.MIN_N,
    }

    # Takeaways: one lead, one gap, one action
    tk = []
    scored = {b: sc[b]["score"] for b in brands if sc[b]["score"] is not None}
    lines = []
    if vp:
        word = "level with" if not vp["distinct"] else ("above" if vp["gap"] > 0 else "below")
        lines.append(f"Pooled sentiment: {focus} is {word} its peers ({vp['focus_pn']:.0f}% vs {vp['peer_pn']:.0f}% positive or neutral"
                     + ("" if vp["distinct"] else ", within chance") + ").")
    lines.append(v["text"])
    tk.append(("Where Acuvue stands", lines))
    if top_reason is not None:
        k, share = int(top_reason["brand_k"]), top_reason["brand_text"]
        txt = f"{top_reason['reason']} is the most common complaint ({share})."
        if pd.notna(top_reason["gap"]):
            txt += f" Peers: {top_reason['peer_text']}, a {top_reason['gap']:+.0f} point gap."
        tk.append(("Biggest gap to fix", [txt]))
    else:
        tk.append(("Biggest gap to fix", ["Too few negative comments to name a reason."]))
    if app:
        share_neg = f"{app['negative']} of {app['n']} MyACUVUE app reviews are negative"
        tops = ", ".join(list(app["top_reasons"])[:2])
        tk.append(("Link to registration", [share_neg + (f"; mainly {tops}." if tops else "."),
                                            IMPLICATIONS.get(next(iter(app["top_reasons"]), ""), "Read app complaints before pushing registration.")]))
    elif top_reason is not None:
        tk.append(("What to test", [IMPLICATIONS.get(top_reason["reason"], "")]))
    snap["takeaways"] = tk
    return snap


def app_story(jf_all: pd.DataFrame) -> dict:
    """The MyACUVUE app as an owned-experience signal: negative app reviews and what they are about."""
    if jf_all is None or jf_all.empty:
        return {}
    a = jf_all[jf_all["source"] == APP_SOURCE].drop_duplicates(["source", "brand", "text"])
    if a.empty:
        return {}
    neg = a[a["sentiment"] == "negative"].copy()
    neg["reason"] = neg["text"].map(barrier_taxonomy.classify)
    top = neg.explode("reason")["reason"].value_counts()
    return {"n": len(a), "negative": len(neg), "top_reasons": top.head(3).to_dict(), "items": neg.explode("reason")}
