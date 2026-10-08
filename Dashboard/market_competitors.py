"""
Market & Competitors page (Stage 1 EBI read-out, plan step 5).

Question: how do we stack up against competitors online, and is the category
growing? Sources: UN Comtrade (HS 9001.30 contact lenses, Singapore, annual),
Lazada SG + TikTok Shop SG lens-solution listings (promo/bundle depth), and share of voice across social / forum / Xiaohongshu content.

Online only: under the HSA, direct online sale of contact lenses (powered or
non-powered) to consumers is illegal in Singapore (confirmed by J&J), so lens prices
cannot be compared online. Solution price per 100 mL was tried and left out: it says
nothing about registering for MyACUVUE. In-store pricing, bulk deals and market share
are not in this data.
"""

import os
import re

import pandas as pd
import plotly.graph_objects as go
from plotly.subplots import make_subplots
import streamlit as st

import charts
import ebi
import facebook_signals
import instagram_signals
import ui
import youtube_signals
from sg_common import BRAND_COLORS, DASH_DIR, XHS_DB, latest_mtime, normalize_brand, read_table, xhs_attributed

# Three identical copies of the same six rows exist (checked 2026-10-01). Preference order: the Excel
# in Scripts/output/ (numeric), the CSV beside it (text with "$" and commas), then the original in Scripts/data/.
_COMTRADE_NAME = "UN Comtrade Database SG Lenses"
COMTRADE_XLSX = os.path.normpath(os.path.join(DASH_DIR, "..", "Scripts", "output", _COMTRADE_NAME + ".xlsx"))
COMTRADE_CSV = os.path.normpath(os.path.join(DASH_DIR, "..", "Scripts", "output", _COMTRADE_NAME + ".csv"))
COMTRADE_XLSX_OLD = os.path.normpath(os.path.join(DASH_DIR, "..", "Scripts", "data", _COMTRADE_NAME + ".xlsx"))
_BUNDLE_RE = re.compile(r"free|bundle|promo|buy \d|travel kit|\+ ?lens case|\+ ?case|value pack|triple pack|twin pack", re.I)


def _num(s: pd.Series) -> pd.Series:
    """'$314,419,428 ' -> 314419428.0 (the CSV stores numbers as formatted text)."""
    return pd.to_numeric(s.astype(str).str.replace(r"[$,\s]", "", regex=True), errors="coerce")


@st.cache_data(show_spinner=False, ttl=3600, max_entries=2)
def _load_comtrade(mtime: float) -> pd.DataFrame:
    raw = pd.DataFrame()
    try:
        if os.path.exists(COMTRADE_XLSX):
            raw = pd.read_excel(COMTRADE_XLSX)
        elif os.path.exists(COMTRADE_CSV):
            raw = pd.read_csv(COMTRADE_CSV)
        elif os.path.exists(COMTRADE_XLSX_OLD):
            raw = pd.read_excel(COMTRADE_XLSX_OLD)
    except Exception:
        return pd.DataFrame()
    need = {"Period", "Trade Flow", "Trade Value (US$)", "Qty"}
    if raw.empty or not need <= set(raw.columns):
        return pd.DataFrame()
    d = raw[raw["Commodity Code"].astype(str).str.startswith("9001")].copy() if "Commodity Code" in raw else raw.copy()
    d["Flow"] = d["Trade Flow"].map({"M": "Imports", "X": "Exports"}).fillna(d["Trade Flow"])
    d["Year"] = pd.to_numeric(d["Period"], errors="coerce").astype("Int64")
    d["Value (US$ m)"] = _num(d["Trade Value (US$)"]) / 1e6
    d["Units (m)"] = _num(d["Qty"]) / 1e6
    d["US$ per unit"] = d["Value (US$ m)"] / d["Units (m)"]
    return d[["Year", "Flow", "Value (US$ m)", "Units (m)", "US$ per unit"]].dropna(subset=["Year"]).sort_values(["Flow", "Year"])


def _trade_section() -> None:
    t = _load_comtrade(latest_mtime(COMTRADE_XLSX, COMTRADE_CSV, COMTRADE_XLSX_OLD))
    if t.empty:
        ui.section("Category trade data is missing", "", "Category", kind="fact")
        st.info("The UN Comtrade file was not found or could not be read.")
        return
    imp = t[t["Flow"] == "Imports"].set_index("Year")
    exp = t[t["Flow"] == "Exports"].set_index("Year")
    first, last = int(imp.index.min()), int(imp.index.max())
    chg_val = (imp.loc[last, "Value (US$ m)"] / imp.loc[first, "Value (US$ m)"] - 1) * 100
    chg_u = (imp.loc[last, "Units (m)"] / imp.loc[first, "Units (m)"] - 1) * 100
    _dir = "shrinking" if chg_u < -5 else ("growing" if chg_u > 5 else "flat")
    ui.section(
        f"The category looks {_dir}: lens imports are {ebi.pct(chg_u)} in units, {first} to {last}",
        "Singapore, HS 9001.30, UN Comtrade, annual. Imports are a rough proxy for demand.",
        "Category", kind="dir")
    m = st.columns(4)
    m[0].metric(f"Imports {last}, value", f"US${imp.loc[last, 'Value (US$ m)']:,.0f}m", f"{ebi.pct(chg_val)} vs {first} (value)", delta_color="off")
    m[1].metric(f"Imports {last}, units", f"{imp.loc[last, 'Units (m)']:,.0f}m", f"{ebi.pct(chg_u)} vs {first}", delta_color="off")
    m[2].metric(f"Exports {last}, value", f"US${exp.loc[last, 'Value (US$ m)']:,.0f}m" if last in exp.index else "n/a")
    m[3].metric(f"Import price per unit {last}", f"US${imp.loc[last, 'US$ per unit']:.2f}",
                f"{ebi.usd(imp.loc[last, 'US$ per unit'] - imp.loc[first, 'US$ per unit'])} vs {first}", delta_color="off")
    fig = go.Figure()
    for flow, df_, colour in (("Imports", imp, "#C98B2B"), ("Exports", exp, "#6B7A90")):
        if df_.empty:
            continue
        y0 = int(df_.index.min())
        for col, label, dash in (("Units (m)", "units", "dash"), ("Value (US$ m)", "value", "solid")):
            idx = df_[col] / df_.loc[y0, col] * 100
            fig.add_scatter(x=idx.index, y=idx.values, mode="lines+markers+text", name=f"{flow}, {label}", line=dict(color=colour, dash=dash, width=3),
                            text=[f"{v:.0f}" if k == idx.index.max() else "" for k, v in idx.items()], textposition="middle right",
                            hovertemplate=flow + " " + label + ": %{y:.0f} (" + str(y0) + " = 100)<extra></extra>")
    fig.add_hline(y=100, line=dict(color="#CBD5E1", width=1))
    fig.update_xaxes(dtick=1, title=None)
    fig.update_yaxes(title=f"Index ({first} = 100)")
    ui.plot(fig, f"Import units fell {abs(chg_u):.0f}% and value {abs(chg_val):.0f}%: less volume, not a price effect." if chg_u < 0 and chg_val < 0
            else f"Import units {ebi.pct(chg_u)}, value {ebi.pct(chg_val)}, {first} to {last}.", "fact",
            (f"Exports are {exp.loc[last, 'Value (US$ m)'] / imp.loc[last, 'Value (US$ m)']:.1f}x imports by value in {last}: lenses pass through. " if last in exp.index else "")
            + "Imports only roughly proxy local demand; SingStat has no HS 9001.30 series to cross-check.",
            height=300, bases=f"UN Comtrade, Singapore · official statistics, not a sample · {len(imp)} annual points")


def _promo_section(products: pd.DataFrame) -> None:
    d = ebi.dedupe_listings(products)
    d = d[(d["category"] == "Lens Solution/Care") & d["brand"].isin(BRAND_COLORS)].copy()
    if d.empty:
        ui.section("No solution listings to check for offers", "", "Promotions", kind="fact")
        return
    d["offer"] = (d["is_promo"] == 1) | d["product_name"].str.contains(_BUNDLE_RE, na=False)
    g = d.groupby("brand").agg(n=("offer", "size"), k=("offer", "sum")).reset_index()
    g["Listings with an offer"] = [ebi.share(int(k), int(n)) for k, n in zip(g["k"], g["n"])]
    _big = g[g["n"] >= ebi.MIN_N]
    _pk = _big.assign(r=_big["k"] / _big["n"]).sort_values("r", ascending=False)
    ui.section(
        (f"{_pk.iloc[0]['brand']} offers on {_pk.iloc[0]['r'] * 100:.0f}% of its solution listings, the highest rate"
         if len(_pk) else "Offer rates are too thin to rank: counts only"),
        "Offer = marked promo, or a free item, bundle or multi-pack in the title.", "Promotions", kind="fact")
    shown = g[g["n"] >= ebi.MIN_N].assign(rate=lambda x: x["k"] / x["n"] * 100)
    if len(shown):
        order = charts.order_brands(shown["brand"].tolist())
        fig = go.Figure(go.Bar(y=order, x=[float(shown.set_index("brand").loc[b, "rate"]) for b in order], orientation="h",
                               marker_color=[BRAND_COLORS.get(b, "#6B7A90") for b in order],
                               text=[f"{shown.set_index('brand').loc[b, 'rate']:.0f}% ({int(shown.set_index('brand').loc[b, 'k'])} of {int(shown.set_index('brand').loc[b, 'n'])})" for b in order],
                               textposition="outside", cliponaxis=False))
        fig.update_xaxes(range=[0, 120], title="% of solution listings with an offer")
        fig.update_yaxes(autorange="reversed", title=None)
        fig.update_layout(height=80 + 52 * len(order))
        small = g[g["n"] < ebi.MIN_N]
        ui.plot(fig, "Share of solution listings with an offer.", "fact",
                "Online only; in-store bulk deals are not visible." + (" Under 15 listings, counts only: " + ", ".join(f"{r.brand} {int(r.k)} of {int(r.n)}" for r in small.itertuples()) + "." if len(small) else ""),
                bases={b: int(n) for b, n in zip(shown["brand"], shown["n"])}, noun="listings")
    ui.show_data("Show the offer table", g.rename(columns={"brand": "Brand", "n": "Listings"}).drop(columns="k"), f"% needs n\u2265{ebi.MIN_N}, else counts.")


def _voice_items(frames: dict, brands: list) -> pd.DataFrame:
    """Analysed items per brand and channel: the same items Brand Health reports as 'analysed' (one row each), so the
    two pages always agree. Columns: brand, source, Items."""
    rows = []
    for s in charts.SOURCE_ORDER:
        a = frames.get(s, {}).get("analysed")
        if a is None or a.empty:
            continue
        g = a[a["brand"].isin(brands)].groupby("brand").size()
        rows += [{"brand": b, "source": s, "Items": int(n)} for b, n in g.items()]
    return pd.DataFrame(rows, columns=["brand", "source", "Items"])


def _voice_section(frames: dict, selected_brands: list) -> None:
    by_src = _voice_items(frames, selected_brands)
    if by_src.empty:
        ui.section("No brand-attributed content to rank", "", "Voice", kind="fact")
        return
    tot = by_src.groupby("brand")["Items"].sum().reset_index().sort_values("Items", ascending=False)
    n_all = int(tot["Items"].sum())
    tot["Share of voice"] = [ebi.share(int(i), n_all) for i in tot["Items"]]
    lead = tot.iloc[0]
    ui.section(
        f"{lead['brand']} is talked about most ({int(lead['Items']):,} of {n_all:,} items)",
        "Where each brand's analysed items come from, most talked-about first. Reflects how much was collected, not market share.", "Share of voice", kind="fact")
    order = tot["brand"].tolist()
    fig = go.Figure()
    for src in charts.SOURCE_ORDER:
        s_ = by_src[by_src["source"] == src].set_index("brand")["Items"]
        if s_.empty:
            continue
        fig.add_bar(y=[charts.row_label(b, int(tot.set_index("brand").loc[b, "Items"])) for b in order],
                    x=[s_.get(b, 0) / tot.set_index("brand").loc[b, "Items"] * 100 for b in order], orientation="h", name=src,
                    marker_color=charts.SOURCE_COLORS.get(src), marker_line=dict(color="white", width=1.5), hovertemplate="%{y}<br>" + src + ": %{x:.0f}% of its items<extra></extra>")
    fig.update_layout(barmode="stack", height=110 + 52 * len(order), legend=dict(orientation="h", y=-0.25), xaxis=dict(range=[0, 100], title="% of the brand's analysed items"))
    fig.update_yaxes(autorange="reversed", title=None)
    _bsr = by_src.assign(share=by_src["Items"] / by_src.groupby("brand")["Items"].transform("sum") * 100).sort_values("share", ascending=False).iloc[0]
    ui.plot(fig, f"{_bsr['source']} is {_bsr['share']:.0f}% of {_bsr['brand']}'s items.", "fact",
            "Channels differ in size (Olens dominates YouTube; Facebook has no Alcon page). Shows who was collected, not who is winning.", height=110 + 52 * len(order),
            bases={r_["brand"]: int(r_["Items"]) for _, r_ in tot.iterrows()}, noun="analysed items")
    ui.show_data("Show share of voice by brand", tot.rename(columns={"brand": "Brand"}))


IG_TOP5_COL = "Top 5 posts' share of Instagram likes"


def _reach_table(selected_brands: list) -> pd.DataFrame:
    """Per brand: content count, YouTube views, Instagram/Facebook/Xiaohongshu likes, plus how much of a
    brand's YouTube views sit in its single biggest video. Posts/videos only (not comments)."""
    yt, _, _ = youtube_signals.load_sg_dashboard_data()
    ig, _, _ = instagram_signals.load_sg_dashboard_data()
    fb, _, _ = facebook_signals.load_sg_dashboard_data()
    xhs = read_table(XHS_DB, "SELECT brand_mentioned, likes, brand_relevant FROM xhs_posts")
    if not xhs.empty:
        xhs["brand_mentioned"] = xhs["brand_mentioned"].map(normalize_brand)
        xhs = xhs_attributed(xhs).copy()      # same Xiaohongshu posts as every other page
        xhs["brand"] = xhs["brand_mentioned"]
        xhs["likes"] = pd.to_numeric(xhs["likes"], errors="coerce").fillna(0)

    def per_brand(df, metric_col, count_name, metric_name):
        if df.empty:
            return pd.DataFrame(columns=["brand", count_name, metric_name])
        d = df.assign(_m=pd.to_numeric(df[metric_col], errors="coerce").fillna(0))
        return d.groupby("brand").agg(**{count_name: ("_m", "size"), metric_name: ("_m", "sum")}).reset_index()

    out = pd.DataFrame({"brand": selected_brands})
    for df, col, cn, mn in (
        (yt, "view_count", "YouTube videos", "YouTube views"),
        (ig, "likes_count", "Instagram posts", "Instagram likes"),
        (fb, "likes_count", "Facebook posts", "Facebook likes"),
        (xhs, "likes", "Xiaohongshu posts", "Xiaohongshu likes"),
    ):
        out = out.merge(per_brand(df, col, cn, mn), on="brand", how="left")
    out = out.fillna(0)
    for df, col, name in ((yt, "view_count", "Top video's share of YouTube views"),
                          (xhs, "likes", "Top post's share of Xiaohongshu likes")):
        if df.empty:
            continue
        v = df.assign(_v=pd.to_numeric(df[col], errors="coerce").fillna(0))
        top, tot = v.groupby("brand")["_v"].max(), v.groupby("brand")["_v"].sum()
        out[name] = out["brand"].map(lambda b, top=top, tot=tot: (top.get(b, 0) / tot.get(b, 1) * 100) if tot.get(b, 0) else 0)

    # Instagram: a few campaign posts can carry a brand's whole like total (e.g. MyACUVUE's ambassador
    # campaign), so also show the typical post (median) and how much the 5 biggest posts hold. Hidden
    # likes (NaN) are unknown, not zero, so they are left out of both.
    if not ig.empty:
        likes = pd.to_numeric(ig["likes_count"], errors="coerce")
        known = ig.assign(_l=likes).dropna(subset=["_l"]).groupby("brand")["_l"]
        # Left blank (not 0) for a brand with no Instagram posts: 0 would read as a measured result.
        out["Instagram median likes per post"] = out["brand"].map(known.median())
        out[IG_TOP5_COL] = out["brand"].map(
            lambda b: (known.get_group(b).nlargest(5).sum() / known.get_group(b).sum() * 100)
            if b in known.groups and known.get_group(b).sum() else None)
    return out


def _reach_section(frames: dict, selected_brands: list) -> None:
    if not selected_brands:
        st.info("No brands selected.")
        return
    r = _reach_table(selected_brands)

    # content-volume share: same basis as the share-of-voice table above
    items = _voice_items(frames, selected_brands).groupby("brand")["Items"].sum()
    r["Comments & posts"] = r["brand"].map(items).fillna(0)

    measures = [
        ("Comments & posts", None),
        ("YouTube views", "YouTube videos"),
        ("Instagram likes", "Instagram posts"),
        ("Xiaohongshu likes", "Xiaohongshu posts"),
    ]
    shown, hidden = [], []
    base_by_measure = {}
    long_rows = []
    for m, base_col in measures:
        total = float(r[m].sum())
        base_n = int(r[base_col].sum()) if base_col else int(total)
        if total <= 0:
            continue
        if base_n >= ebi.MIN_N:
            shown.append(m)
            base_by_measure[m] = base_n
            for _, row in r.iterrows():
                long_rows.append({"Brand": row["brand"], "Measure": m, "Share": row[m] / total * 100})
        else:
            hidden.append(f"{m} (n={base_n})")
    if long_rows:
        long = pd.DataFrame(long_rows)
        fig = make_subplots(rows=1, cols=len(shown), shared_yaxes=True, horizontal_spacing=0.04)
        for k, m_ in enumerate(shown, start=1):
            lm = long[long["Measure"] == m_]
            fig.add_bar(y=lm["Brand"], x=lm["Share"], orientation="h", showlegend=False, row=1, col=k,
                        marker_color=[BRAND_COLORS.get(b, "#6B7A90") for b in lm["Brand"]],
                        text=[f"{v:.0f}%" for v in lm["Share"]], textposition="outside", cliponaxis=False,
                        hovertemplate="%{y}: %{x:.0f}% of the selected brands' " + m_.lower() + "<extra></extra>")
            fig.update_xaxes(range=[0, 125], showticklabels=False, title_text=m_, row=1, col=k)
        fig.update_yaxes(autorange="reversed", title=None)
        fig.update_layout(height=100 + 46 * len(selected_brands))
        leaders = {m: long[long["Measure"] == m].sort_values("Share", ascending=False).iloc[0]["Brand"] for m in shown}
        if len(set(leaders.values())) > 1:
            msg = "Leader depends on the measure: " + "; ".join(f"<b>{b}</b> on {m.lower()}" for m, b in leaders.items()) + "."
        else:
            msg = f"<b>{next(iter(leaders.values()))}</b> leads on every measure shown."
        conc = []
        for col, label in (("Top video's share of YouTube views", "YouTube views"),
                           ("Top post's share of Xiaohongshu likes", "Xiaohongshu likes")):
            if col in r.columns:
                for _, row in r[r[col] >= 60].iterrows():
                    conc.append(f"one {'video' if 'video' in col else 'post'} is {row[col]:.0f}% of {row['brand']}'s {label}")
        if IG_TOP5_COL in r.columns:
            for _, row in r[(r[IG_TOP5_COL] >= 60) & (r["Instagram posts"] >= 15)].iterrows():
                conc.append(f"the 5 biggest posts are {row[IG_TOP5_COL]:.0f}% of {row['brand']}'s Instagram likes "
                            f"(typical post: {row['Instagram median likes per post']:.0f})")
        care = ("Read with care: " + "; ".join(conc) + ".") if conc else ""
        ui.section("The reach leader changes with the measure" if len(set(leaders.values())) > 1 else "One brand leads every reach measure",
                   "Content volume, YouTube views, Instagram and Xiaohongshu likes.", "Reach", kind="fact")
        ui.plot(fig, msg, "fact", care or f"Each panel: brand share of the selected brands' total · {len(shown)} measures", height=100 + 46 * len(selected_brands),
                bases=base_by_measure, noun="items behind each measure")
    if hidden:
        st.caption(f"Not charted (under {ebi.MIN_N} posts or videos): {', '.join(hidden)}.")

    show = r.rename(columns={"brand": "Brand"})
    cols = ["Brand", "Comments & posts", "YouTube videos", "YouTube views", "Top video's share of YouTube views",
            "Instagram posts", "Instagram likes", "Instagram median likes per post", IG_TOP5_COL, "Facebook posts", "Facebook likes", "Xiaohongshu posts", "Xiaohongshu likes",
            "Top post's share of Xiaohongshu likes"]
    cols = [c for c in cols if c in show.columns]
    pct_cols = ("Top video's share of YouTube views", "Top post's share of Xiaohongshu likes", IG_TOP5_COL)
    ui.show_data("Show the reach table", show[cols],
                 "Reach of the content our searches found, not demand. A few items can carry a total: compare the Instagram median with the total. "
                 "Xiaohongshu posts are not all Singapore-specific.",
                 column_config={
                     **{c: st.column_config.NumberColumn(format="%.0f%%") for c in pct_cols if c in cols},
                     **{c: st.column_config.NumberColumn(format="localized") for c in cols if c not in ("Brand",) + pct_cols},
                 })


def render(products: pd.DataFrame, frames: dict, selected_brands: list) -> None:
    selected_brands = charts.order_brands(selected_brands)   # fixed brand order on every chart
    ebi.page_header(
        "How do we stack up against competitors online, and is the category growing?",
        ["fact", "dir"],
        "Trade data is fact; online prices, offers and voice are directional.",
    )
    _trade_section()
    _promo_section(products)
    _voice_section(frames, selected_brands)
    _reach_section(frames, selected_brands)
    ebi.limits([
        "<b>Market share</b> (J&amp;J's ~36%), channel mix and penetration: need a retail-audit source or J&amp;J.",
        "<b>In-store prices and bulk deals</b>: online data cannot see them.",
        "<b>Lens prices</b>: online lens sale is illegal under the HSA, so none is shown.",
        "<b>Sales volume</b>: listing and review counts are not sales.",
        "Whether the import decline is falling demand: exports are twice imports, so imports alone cannot say.",
    ])


def trade_facts() -> dict:
    """Imports change first to last year (units and value) for the Summary card; {} if the trade file is missing."""
    t = _load_comtrade(latest_mtime(COMTRADE_XLSX, COMTRADE_CSV, COMTRADE_XLSX_OLD))
    if t.empty:
        return {}
    imp = t[t["Flow"] == "Imports"].set_index("Year")
    first, last = int(imp.index.min()), int(imp.index.max())
    return {"first": first, "last": last, "n_years": len(imp),
            "units": (imp.loc[last, "Units (m)"] / imp.loc[first, "Units (m)"] - 1) * 100,
            "value": (imp.loc[last, "Value (US$ m)"] / imp.loc[first, "Value (US$ m)"] - 1) * 100,
            "price": (imp.loc[last, "US$ per unit"] / imp.loc[first, "US$ per unit"] - 1) * 100}


def reach_facts(frames: dict, brands: list) -> dict:
    """Voice and reach for the Summary card: items per brand, the leader on each measure with enough posts, and the
    single items that carry a brand's total. Same inputs and thresholds as the Reach section."""
    items = _voice_items(frames, brands).groupby("brand")["Items"].sum().reindex(brands).fillna(0)
    r = _reach_table(brands)
    r["Comments & posts"] = r["brand"].map(items).fillna(0)
    leaders, conc = {}, []
    for m, base_col in (("Comments & posts", None), ("YouTube views", "YouTube videos"),
                        ("Instagram likes", "Instagram posts"), ("Xiaohongshu likes", "Xiaohongshu posts")):
        total = float(r[m].sum())
        n = int(r[base_col].sum()) if base_col else int(total)
        if total > 0 and n >= ebi.MIN_N:
            leaders[m] = r.loc[r[m].idxmax(), "brand"]
    for col, label, noun in (("Top video's share of YouTube views", "YouTube views", "video"),
                             ("Top post's share of Xiaohongshu likes", "Xiaohongshu likes", "post")):
        if col in r.columns:
            conc += [f"one {noun} is {row[col]:.0f}% of {row['brand']}'s {label}" for _, row in r[r[col] >= 60].iterrows()]
    if IG_TOP5_COL in r.columns:
        conc += [f"the 5 biggest posts are {row[IG_TOP5_COL]:.0f}% of {row['brand']}'s Instagram likes"
                 for _, row in r[(r[IG_TOP5_COL] >= 60) & (r["Instagram posts"] >= 15)].iterrows()]
    return {"items": items, "leaders": leaders, "conc": conc}
