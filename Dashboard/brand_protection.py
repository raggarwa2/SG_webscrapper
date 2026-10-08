"""
Brand Protection page (Stage 1 EBI read-out, plan step 3).

Question: which contact-lens listings for the tracked brands are offered for
direct online sale on marketplaces, and who is selling ACUVUE? Built only from
the scraped marketplace listings (Lazada SG + TikTok Shop SG). Under the HSA,
direct online sale of contact lenses (powered or non-powered) to consumers is
illegal in Singapore (confirmed by J&J), so `compliance_flag` — an actual contact
lens for a tracked brand listed on a marketplace, see
Scripts/build_sg_products_reviews.py — is a compliance signal whoever the seller
is. It is based on what the listing offers; it does not show a sale was made or
that the stock is fake. Whether a seller is a J&J-authorised retailer is a
separate, secondary question.
"""

import pandas as pd
import plotly.express as px
import streamlit as st

import ebi
import ui
from sg_common import BRAND_COLORS

# Sellers that are a recognisable retailer rather than an anonymous marketplace handle.
_NAMED_RETAILERS = {"Lenskart Singapore"}
_SITE_NAMES = {"lazada_sg": "Lazada SG", "tiktok_shop": "TikTok Shop SG"}


def _seller_type(store) -> str:
    if store in _NAMED_RETAILERS:
        return "Named retailer"
    if store == "Reseller":
        return "Unnamed (Lazada 'Reseller')"
    return "Marketplace handle"


def _prepare(products_all: pd.DataFrame):
    raw_flagged = products_all[products_all["compliance_flag"] == 1]
    d = ebi.dedupe_listings(products_all).copy()
    d["site_name"] = d["site"].map(_SITE_NAMES).fillna(d["site"])
    d["seller_type"] = d["store_name"].map(_seller_type)
    return raw_flagged, d


def render(products_all: pd.DataFrame) -> None:
    ebi.page_header(
        "Which lens listings are offered for direct online sale, and who sells ACUVUE?",
        ["fact"],
        "Found by our searches on Lazada and TikTok Shop. A floor, not a census.",
    )
    if products_all.empty:
        st.info("No product listings found.")
        return

    raw_flagged, d = _prepare(products_all)
    flagged = d[d["compliance_flag"] == 1]
    acu = flagged[flagged["brand"] == "Acuvue"]

    st.markdown(
        '<div class="caveat-box"><b>Why flagged:</b> direct online sale of contact lenses is illegal in Singapore under the HSA '
        "(confirmed by J&amp;J), whoever the seller is. A flag shows an offer, not a sale or fake stock. "
        "Seller authorisation is secondary: left for J&amp;J to confirm.</div>",
        unsafe_allow_html=True,
    )

    # ---- headline numbers ----
    k = st.columns(4)
    k[0].metric("Flagged rows scraped", f"{len(raw_flagged):,}",
                help="Rows with compliance_flag = 1 before removing repeat scrapes of the same listing.")
    k[1].metric("Distinct lens listings", f"{len(flagged):,}",
                help="One per (site, seller, title) after removing repeat scrapes.")
    k[2].metric("Named sellers", f"{flagged.loc[flagged['store_name'] != 'Reseller', 'store_name'].nunique():,}",
                help="Distinct seller names. Lazada shows several sellers only as 'Reseller', so this undercounts.")
    k[3].metric("ACUVUE lens listings", f"{len(acu):,}",
                help="Distinct flagged listings under the ACUVUE brand.")

    # ---- by brand ----
    _top = d[d["compliance_flag"] == 1].groupby("brand").size().sort_values(ascending=False)
    ui.section(
        (f"{_top.index[0]} has the most lens listings online ({int(_top.iloc[0])})"
         if len(_top) else "No lens listings flagged"),
        "Distinct listings after removing repeat scrapes.", "Coverage", kind="fact")
    rows = []
    for b, g in d.groupby("brand"):
        lens = g[g["compliance_flag"] == 1]
        rows.append({
            "Brand": b,
            "Lens listings": len(lens),
            "All listings tracked": len(g),
            "Lens share of listings": ebi.share(len(lens), len(g)),
            "Sellers": lens["store_name"].nunique(),
            "Sites": ", ".join(sorted(lens["site_name"].unique())),
            "Median price (S$)": round(lens["selling_price"].median(), 2) if lens["selling_price"].notna().any() else None,
        })
    by_brand = pd.DataFrame(rows).sort_values("Lens listings", ascending=False)
    fig = px.bar(
        by_brand[by_brand["Brand"] != "Other"], x="Brand", y="Lens listings", color="Brand",
        color_discrete_map=BRAND_COLORS, text="Lens listings",
    )
    fig.update_layout(showlegend=False)
    ui.plot(fig, f"{int((by_brand['Brand'] != 'Other').sum())} brands have flagged lens listings: not only ACUVUE.", "fact",
            "Marketplaces · distinct lens listings after removing repeat scrapes", height=240,
            bases={r["Brand"]: int(r["Lens listings"]) for _, r in by_brand[by_brand["Brand"] != "Other"].iterrows()}, noun="lens listings")
    ui.show_data("Show the brand table", by_brand, "Median price mixes pack sizes: not a price comparison. Brand = search term; \"Other\" = unbranded cosmetic lenses.",
                 column_config={"Median price (S$)": st.column_config.NumberColumn(format="%.2f")})

    # ---- ACUVUE sellers ----
    ui.section(
        f"{acu['store_name'].nunique()} sellers offer ACUVUE lenses online",
        "Authorisation is secondary: direct online sale is not permitted under the HSA.",
        "ACUVUE", kind="fact",
    )
    if acu.empty:
        st.info("No ACUVUE lens listings in the scraped data.")
    else:
        show = acu[["product_name", "store_name", "seller_type", "site_name", "selling_price", "category", "url"]].copy()
        show["J&J-authorised seller?"] = "To confirm"
        show = show.rename(columns={
            "product_name": "Listing", "store_name": "Seller", "seller_type": "Seller type", "site_name": "Site",
            "selling_price": "Price (S$)", "category": "Category", "url": "Link",
        }).sort_values(["Seller", "Listing"])
        per = acu.assign(Site=acu["site_name"]).groupby(["store_name", "Site"]).size().reset_index(name="Listings")
        top_sellers = per.groupby("store_name")["Listings"].sum().sort_values(ascending=False).head(10).index.tolist()
        fig_s = px.bar(per[per["store_name"].isin(top_sellers)], y="store_name", x="Listings", color="Site", orientation="h",
                       category_orders={"store_name": top_sellers}, labels={"store_name": ""})
        fig_s.update_yaxes(autorange="reversed")
        fig_s.update_layout(height=90 + 34 * len(top_sellers))
        ui.plot(fig_s, f"{top_sellers[0]} lists the most ACUVUE lenses ({int(per.loc[per['store_name'] == top_sellers[0], 'Listings'].sum())}).", "fact",
                f"Top {len(top_sellers)} of {acu['store_name'].nunique()} sellers", bases=len(acu), noun="ACUVUE lens listings")
        ui.show_data("Show every ACUVUE listing", show, "Lenskart's three rows are credit vouchers, not lenses. Link blank where no URL was scraped.",
                     column_config={"Price (S$)": st.column_config.NumberColumn(format="%.2f"),
                                    "Link": st.column_config.LinkColumn("Link", display_text="Open")})

    # ---- price dispersion on one SKU ----
    ui.section(
        "RevitaLens packs sell at different prices across sellers",
        "Lens solution sold by third parties. Outside the HSA lens rule.",
        "Price spread", kind="fact",
    )
    rev = d[(d["brand"] == "Acuvue") & (d["category"] == "Lens Solution/Care")
            & d["product_name"].str.contains("revita", case=False, na=False)].copy()
    rev["ml"] = [ebi.volume_ml(n, p) for n, p in zip(rev["product_name"], rev["pack_size"])]
    parsed = rev.dropna(subset=["ml", "selling_price"]).copy()
    parsed["Pack"] = parsed["ml"].map(lambda v: f"{int(v)} mL")
    if parsed.empty:
        st.info("No RevitaLens listings with a readable pack size.")
    else:
        # Compare within the same pack size only: bulk packs are cheaper per mL, so mixing
        # pack sizes would overstate how much sellers differ.
        agg = (parsed.groupby(["Pack", "site_name"])["selling_price"]
               .agg(Listings="size", Lowest="min", Median="median", Highest="max").reset_index()
               .rename(columns={"site_name": "Site"}))
        agg["ml"] = agg["Pack"].str.replace(" mL", "").astype(int)
        agg = agg.sort_values(["ml", "Site"]).drop(columns="ml")
        order = sorted(parsed["Pack"].unique(), key=lambda s: int(s.split()[0]))
        fig = px.strip(parsed, x="Pack", y="selling_price", color="site_name", hover_data=["store_name", "product_name"],
                       category_orders={"Pack": order},
                       labels={"selling_price": "Listed price (S$)", "Pack": "", "site_name": "Site"})
        big = parsed["Pack"].value_counts().idxmax()
        grp = parsed[parsed["Pack"] == big]["selling_price"]
        ui.plot(fig, f"The same {big} pack lists from S${grp.min():.2f} to S${grp.max():.2f} ({grp.max() / grp.min():.1f}x).", "fact",
                f"{len(parsed)} of {len(rev)} listings state a pack size; the rest are excluded. Reseller pricing; J&J to confirm authorisation.",
                height=260, bases={k: int(v) for k, v in parsed["Pack"].value_counts().reindex(order).items()}, noun="RevitaLens listings")
        ui.show_data("Show prices by pack and site", agg, "S$. Bundles not netted out.",
                     column_config={c: st.column_config.NumberColumn(format="%.2f") for c in ("Lowest", "Median", "Highest")})

    # ---- competitors ----
    with st.expander("Competitor and other lens listings (context)"):
        comp = flagged[flagged["brand"] != "Acuvue"][
            ["brand", "product_name", "store_name", "seller_type", "site_name", "selling_price", "url"]
        ].rename(columns={"brand": "Brand", "product_name": "Listing", "store_name": "Seller",
                          "seller_type": "Seller type", "site_name": "Site", "selling_price": "Price (S$)", "url": "Link"})
        st.dataframe(
            comp.sort_values(["Brand", "Seller"]), hide_index=True, width="stretch",
            column_config={"Price (S$)": st.column_config.NumberColumn(format="%.2f"),
                           "Link": st.column_config.LinkColumn("Link", display_text="Open")},
        )
        st.caption("Some listings sit under a brand only because of the search term that found them.")

    ebi.limits([
        "Seller authorisation or genuine stock: needs J&amp;J&rsquo;s authorised-seller list. Neither changes the HSA position.",
        "Units sold, or listing growth: one snapshot, no sales data.",
        "Shopee is not covered; only Lazada and TikTok Shop, and only what our searches surfaced.",
        f"Repeats removed ({len(raw_flagged)} rows = {len(flagged)} listings). Lazada &ldquo;Reseller&rdquo; can hide several sellers.",
    ])
