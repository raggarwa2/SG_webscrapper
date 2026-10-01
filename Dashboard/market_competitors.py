"""
Market & Competitors page (Stage 1 EBI read-out, plan step 5).

Question: how do we stack up against competitors online, and is the category
growing? Sources: UN Comtrade (HS 9001.30 contact lenses, Singapore, annual),
Lazada SG + TikTok Shop SG lens-solution listings (price per 100 mL, promo/bundle
depth), and share of voice across social / forum / Xiaohongshu content.

Online only: under the HSA, direct online sale of contact lenses (powered or
non-powered) to consumers is illegal in Singapore (confirmed by J&J), so lens prices
cannot be compared online and solutions are the comparable product. In-store
pricing, bulk deals and market share are not in this data.
"""

import os
import re

import pandas as pd
import plotly.express as px
import streamlit as st

import ebi
import facebook_signals
import instagram_signals
import ui
import youtube_signals
from sg_common import BRAND_COLORS, DASH_DIR, XHS_DB, latest_mtime, normalize_brand, read_table

# Three identical copies of the same six rows exist (checked 2026-10-01). Preference order: the Excel
# in Scripts/output/ (numeric), the CSV beside it (text with "$" and commas), then the original in Scripts/data/.
_COMTRADE_NAME = "UN Comtrade Database SG Lenses"
COMTRADE_XLSX = os.path.normpath(os.path.join(DASH_DIR, "..", "Scripts", "output", _COMTRADE_NAME + ".xlsx"))
COMTRADE_CSV = os.path.normpath(os.path.join(DASH_DIR, "..", "Scripts", "output", _COMTRADE_NAME + ".csv"))
COMTRADE_XLSX_OLD = os.path.normpath(os.path.join(DASH_DIR, "..", "Scripts", "data", _COMTRADE_NAME + ".xlsx"))
_SITE_NAMES = {"lazada_sg": "Lazada SG", "tiktok_shop": "TikTok Shop SG"}
_VOICE_SOURCES = ["YouTube", "Instagram", "Facebook", "Reddit", "Xiaohongshu", "KiasuParents"]
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
    ui.section(
        "Is the category growing? Singapore contact-lens trade (HS 9001.30)",
        "UN Comtrade, annual, whole world as partner.",
        "Market fact",
    )
    st.markdown(ebi.tag("fact"), unsafe_allow_html=True)
    t = _load_comtrade(latest_mtime(COMTRADE_XLSX, COMTRADE_CSV, COMTRADE_XLSX_OLD))
    if t.empty:
        st.info("The UN Comtrade file was not found or could not be read.")
        return
    imp = t[t["Flow"] == "Imports"].set_index("Year")
    exp = t[t["Flow"] == "Exports"].set_index("Year")
    first, last = int(imp.index.min()), int(imp.index.max())
    chg_val = (imp.loc[last, "Value (US$ m)"] / imp.loc[first, "Value (US$ m)"] - 1) * 100
    chg_u = (imp.loc[last, "Units (m)"] / imp.loc[first, "Units (m)"] - 1) * 100
    m = st.columns(4)
    m[0].metric(f"Imports {last}", f"US${imp.loc[last, 'Value (US$ m)']:,.0f}m", f"{chg_val:+.0f}% vs {first} (value)", delta_color="off")
    m[1].metric(f"Imports {last}, units", f"{imp.loc[last, 'Units (m)']:,.0f}m", f"{chg_u:+.0f}% vs {first}", delta_color="off")
    m[2].metric(f"Exports {last}", f"US${exp.loc[last, 'Value (US$ m)']:,.0f}m" if last in exp.index else "n/a")
    m[3].metric(f"Import price per unit {last}", f"US${imp.loc[last, 'US$ per unit']:.2f}",
                f"{imp.loc[last, 'US$ per unit'] - imp.loc[first, 'US$ per unit']:+.2f} vs {first}", delta_color="off")
    c1, c2 = st.columns(2)
    with c1:
        fig = px.bar(t, x="Year", y="Value (US$ m)", color="Flow", barmode="group", title="Trade value (US$ m)")
        fig.update_xaxes(dtick=1)
        st.plotly_chart(fig, width="stretch")
        st.caption(f"UN Comtrade · Singapore · {int(t['Year'].min())}–{int(t['Year'].max())}")
    with c2:
        fig = px.bar(t, x="Year", y="Units (m)", color="Flow", barmode="group", title="Units (millions)")
        fig.update_xaxes(dtick=1)
        st.plotly_chart(fig, width="stretch")
        st.caption(f"UN Comtrade · Singapore · {int(t['Year'].min())}–{int(t['Year'].max())}")
    ui.insight(
        f"Imports fell <b>{abs(chg_u):.0f}%</b> in units and <b>{abs(chg_val):.0f}%</b> in value between {first} and {last}, "
        "while the average price per unit stayed roughly flat. The drop is volume, not price.",
    )
    st.caption(
        "Singapore exports about twice what it imports, so lenses move through and out of the country. "
        f"Imports are a rough proxy for local demand, not a measure of it. Only {len(imp)} annual points. "
        "SingStat's trade tables stop above this product level (no HS 9001.30 or optical-goods series), "
        "so this could not be cross-checked there."
    )


def _price_section(products: pd.DataFrame) -> None:
    ui.section(
        "Online price of contact-lens solution, per 100 mL",
        "Lens solution is the comparable product online: under the HSA, direct online sale of contact lenses is illegal in Singapore (confirmed by J&J).",
        "Directional",
    )
    st.markdown(ebi.tag("dir"), unsafe_allow_html=True)
    sol = ebi.dedupe_listings(products)
    sol = sol[(sol["category"] == "Lens Solution/Care") & sol["brand"].isin(BRAND_COLORS)].copy()
    if sol.empty:
        st.info("No lens-solution listings.")
        return
    sol["ml"] = [ebi.volume_ml(n, p) for n, p in zip(sol["product_name"], sol["pack_size"])]
    sol["per100"] = sol["selling_price"] / sol["ml"] * 100
    sol["Site"] = sol["site"].map(_SITE_NAMES).fillna(sol["site"])
    ok = sol.dropna(subset=["per100"])
    agg = ok.groupby(["brand", "Site"])["per100"].agg(Listings="size", Lowest="min", Median="median", Highest="max").reset_index()
    agg["Note"] = agg["Listings"].map(lambda n: f"thin (n<{ebi.MIN_N_PRICE})" if n < ebi.MIN_N_PRICE else "")
    agg = agg.rename(columns={"brand": "Brand"})
    c1, c2 = st.columns([3, 2])
    with c1:
        fig = px.box(ok, x="brand", y="per100", color="Site", points="all", hover_data=["store_name", "product_name"],
                     labels={"per100": "S$ per 100 mL", "brand": ""}, title="S$ per 100 mL by brand and site")
        st.plotly_chart(fig, width="stretch")
        st.caption(f"{', '.join(sorted(ok['Site'].unique()))} · {len(ok)} of {len(sol)} solution listings with pack size")
    with c2:
        st.dataframe(agg, hide_index=True, width="stretch",
                     column_config={c: st.column_config.NumberColumn(format="%.2f") for c in ("Lowest", "Median", "Highest")})
    st.caption(
        f"{len(ok)} of {len(sol)} distinct solution listings state a readable pack size; the other {len(sol) - len(ok)} are "
        "excluded rather than guessed. Price is the listed price and ignores bundled cases or travel kits. "
        "Multi-packs cost less per mL than single bottles, so a brand that sells mostly multi-packs looks cheaper here. "
        "Listings from third-party sellers, not brand stores, so this is the online reseller price, not J&J's or competitors' list price."
    )


def _promo_section(products: pd.DataFrame) -> None:
    ui.section(
        "Promotions and bundles on solution listings",
        "A listing counts if it is marked promo or its title offers a free item, bundle or multi-pack.",
        "Directional",
    )
    st.markdown(ebi.tag("dir"), unsafe_allow_html=True)
    d = ebi.dedupe_listings(products)
    d = d[(d["category"] == "Lens Solution/Care") & d["brand"].isin(BRAND_COLORS)].copy()
    if d.empty:
        st.info("No lens-solution listings.")
        return
    d["offer"] = (d["is_promo"] == 1) | d["product_name"].str.contains(_BUNDLE_RE, na=False)
    g = d.groupby("brand").agg(n=("offer", "size"), k=("offer", "sum")).reset_index()
    g["Listings with an offer"] = [ebi.share(int(k), int(n)) for k, n in zip(g["k"], g["n"])]
    st.dataframe(
        g.rename(columns={"brand": "Brand", "n": "Listings"}).drop(columns="k"),
        hide_index=True, width="stretch",
    )
    st.caption(
        f"Percentages need at least {ebi.MIN_N} listings; below that only counts are shown. Online only: the in-store "
        "bulk deals described in the project brief (for example buy-6-get-1) cannot be seen here."
    )


def _voice_section(jf: pd.DataFrame, selected_brands: list) -> None:
    ui.section(
        "Share of voice",
        "Brand-attributed comments and posts across social, forum and Xiaohongshu sources.",
        "Directional",
    )
    st.markdown(ebi.tag("dir"), unsafe_allow_html=True)
    if jf.empty:
        st.info("No journey data loaded.")
        return
    v = jf[jf["source"].isin(_VOICE_SOURCES) & jf["brand"].isin(selected_brands)].drop_duplicates(subset=["source", "brand", "text"])
    if v.empty:
        st.info("No brand-attributed content.")
        return
    tot = v.groupby("brand").size().rename("Items").reset_index().sort_values("Items", ascending=False)
    n_all = int(tot["Items"].sum())
    tot["Share of voice"] = [ebi.share(int(i), n_all) for i in tot["Items"]]
    by_src = v.groupby(["brand", "source"]).size().reset_index(name="Items")
    c1, c2 = st.columns([3, 2])
    with c1:
        fig = px.bar(by_src, x="brand", y="Items", color="source", title="Brand-attributed items by source")
        st.plotly_chart(fig, width="stretch")
        st.caption(f"{v['source'].nunique()} sources · {ebi.count(len(v), 'items')}")
    with c2:
        st.dataframe(tot.rename(columns={"brand": "Brand"}), hide_index=True, width="stretch")
    lead = tot.iloc[0]
    ui.insight(f"<b>{lead['brand']}</b> has the most brand-attributed content ({int(lead['Items']):,} of {n_all:,}). "
               "Volume is not sentiment or purchase intent, and one platform can dominate a brand (see the chart).")
    st.caption(
        "Sources differ a lot in size and in which brands they cover (for example Olens dominates YouTube; Facebook has no "
        "Alcon page), and only about 30% of Xiaohongshu posts carry a brand label. Treat this as who is being talked about, "
        "not who is winning."
    )


def _reach_table(selected_brands: list) -> pd.DataFrame:
    """Per brand: content count, YouTube views, Instagram/Facebook/Xiaohongshu likes, plus how much of a
    brand's YouTube views sit in its single biggest video. Posts/videos only (not comments)."""
    yt, _, _ = youtube_signals.load_sg_dashboard_data()
    ig, _, _ = instagram_signals.load_sg_dashboard_data()
    fb, _, _ = facebook_signals.load_sg_dashboard_data()
    xhs = read_table(XHS_DB, "SELECT brand_mentioned, likes, brand_relevant FROM xhs_posts")
    if not xhs.empty:
        xhs = xhs[(xhs["brand_relevant"] == 1) & xhs["brand_mentioned"].notna() & (xhs["brand_mentioned"] != "other")].copy()
        xhs["brand"] = xhs["brand_mentioned"].map(normalize_brand)
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
    return out


def _reach_section(jf: pd.DataFrame, selected_brands: list) -> None:
    ui.section(
        "Reach and engagement: does the leader change?",
        "The same brands ranked by content volume, YouTube views, and likes on Instagram and Xiaohongshu posts.",
        "Directional",
    )
    st.markdown(ebi.tag("dir"), unsafe_allow_html=True)
    if not selected_brands:
        st.info("No brands selected.")
        return
    r = _reach_table(selected_brands)

    # content-volume share: same basis as the share-of-voice table above
    items = pd.Series(0, index=selected_brands, dtype=float)
    if not jf.empty:
        v = jf[jf["source"].isin(_VOICE_SOURCES) & jf["brand"].isin(selected_brands)].drop_duplicates(subset=["source", "brand", "text"])
        items = v.groupby("brand").size().reindex(selected_brands).fillna(0)
    r["Comments & posts"] = r["brand"].map(items).fillna(0)

    measures = [
        ("Comments & posts", None),
        ("YouTube views", "YouTube videos"),
        ("Instagram likes", "Instagram posts"),
        ("Xiaohongshu likes", "Xiaohongshu posts"),
    ]
    shown, hidden = [], []
    long_rows = []
    for m, base_col in measures:
        total = float(r[m].sum())
        base_n = int(r[base_col].sum()) if base_col else int(total)
        if total <= 0:
            continue
        if base_n >= ebi.MIN_N:
            shown.append(m)
            for _, row in r.iterrows():
                long_rows.append({"Brand": row["brand"], "Measure": m, "Share": row[m] / total * 100})
        else:
            hidden.append(f"{m} (n={base_n})")
    if long_rows:
        long = pd.DataFrame(long_rows)
        fig = px.bar(long, x="Brand", y="Share", color="Measure", barmode="group",
                     labels={"Share": "% of the selected brands' total"},
                     title="Share of the selected brands, by measure")
        st.plotly_chart(fig, width="stretch")
        st.caption(f"{len(shown)} measures · selected brands")
        leaders = {m: long[long["Measure"] == m].sort_values("Share", ascending=False).iloc[0]["Brand"] for m in shown}
        if len(set(leaders.values())) > 1:
            msg = "The leader depends on the measure: " + "; ".join(f"<b>{b}</b> on {m.lower()}" for m, b in leaders.items()) + "."
        else:
            msg = f"<b>{next(iter(leaders.values()))}</b> leads on every measure shown."
        conc = []
        for col, label in (("Top video's share of YouTube views", "YouTube views"),
                           ("Top post's share of Xiaohongshu likes", "Xiaohongshu likes")):
            if col in r.columns:
                for _, row in r[r[col] >= 60].iterrows():
                    conc.append(f"one {'video' if 'video' in col else 'post'} is {row[col]:.0f}% of {row['brand']}'s {label}")
        if conc:
            msg += " Treat the reach figures with care: " + "; ".join(conc) + "."
        ui.insight(msg)
    if hidden:
        st.caption(f"Not charted (under {ebi.MIN_N} posts or videos): {', '.join(hidden)}.")

    show = r.rename(columns={"brand": "Brand"})
    cols = ["Brand", "Comments & posts", "YouTube videos", "YouTube views", "Top video's share of YouTube views",
            "Instagram posts", "Instagram likes", "Facebook posts", "Facebook likes", "Xiaohongshu posts", "Xiaohongshu likes",
            "Top post's share of Xiaohongshu likes"]
    cols = [c for c in cols if c in show.columns]
    pct_cols = ("Top video's share of YouTube views", "Top post's share of Xiaohongshu likes")
    st.dataframe(
        show[cols], hide_index=True, width="stretch",
        column_config={
            **{c: st.column_config.NumberColumn(format="%.0f%%") for c in pct_cols if c in cols},
            **{c: st.column_config.NumberColumn(format="localized") for c in cols if c not in ("Brand",) + pct_cols},
        },
    )
    st.caption(
        "Views and likes are on the videos and posts our searches found for each brand, including the brands' own pages "
        "(Instagram and Facebook), so they measure reach of that content, not consumer demand or preference. A few videos can "
        "carry a brand's total (see the top-video and top-post shares). Xiaohongshu posts are brand-relevant but not all are "
        "Singapore-specific. Facebook is in the table only: a fixed 30 posts per page and few likes."
    )


def render(products: pd.DataFrame, jf: pd.DataFrame, selected_brands: list) -> None:
    ebi.page_header(
        "How do we stack up against competitors online, and is the category growing?",
        ["fact", "dir"],
        "Trade data is a market fact; online prices, offers and share of voice are directional and online-only.",
    )
    _trade_section()
    _price_section(products)
    _promo_section(products)
    _voice_section(jf, selected_brands)
    _reach_section(jf, selected_brands)
    ebi.limits([
        "<b>Market share</b> (J&amp;J's ~36%), channel mix and penetration: not in scraped data; needs a retail-audit source or J&amp;J.",
        "<b>In-store prices and bulk deals</b> (for example buy-6-get-1 at optical chains): online data cannot see them.",
        "<b>Lens prices</b>: direct online sale of contact lenses is illegal under the HSA (confirmed by J&amp;J), so only solutions can be compared online.",
        "<b>Sales volume</b> for any brand. Listing counts and review counts are not sales.",
        "Whether the import decline reflects falling local demand: Singapore exports about twice what it imports, so imports alone cannot say.",
    ])
