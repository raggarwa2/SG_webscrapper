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
        "Which contact-lens listings for the tracked brands are offered for direct online sale on marketplaces, and who is selling ACUVUE?",
        ["fact"],
        "Listings found by our searches on Lazada SG and TikTok Shop SG. A floor, not a census.",
    )
    if products_all.empty:
        st.info("No product listings found.")
        return

    raw_flagged, d = _prepare(products_all)
    flagged = d[d["compliance_flag"] == 1]
    acu = flagged[flagged["brand"] == "Acuvue"]

    st.markdown(
        '<div class="caveat-box"><b>Why these listings matter.</b> Under the HSA, direct online sale of contact lenses '
        "(powered or non-powered) to consumers is illegal in Singapore, as confirmed by J&amp;J. A listing is flagged when it "
        "offers an actual contact lens (daily, biweekly or colour) on a marketplace, <b>whoever the seller is</b>. The flag is "
        "based on what the listing offers: it does not show that a sale was made or that the stock is fake. Whether a seller is "
        "a J&amp;J-authorised retailer is a separate question and does not change the HSA position, so that column below is "
        "secondary and left for J&amp;J to fill.</div>",
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
    ui.section("Lens listings by brand", "Distinct listings after removing repeat scrapes.", "Coverage")
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
    st.dataframe(by_brand, hide_index=True, width="stretch",
                 column_config={"Median price (S$)": st.column_config.NumberColumn(format="%.2f")})
    st.caption(
        "Median price mixes pack sizes (single lenses, 30-packs, vouchers), so it is not a price comparison. "
        "Brand comes from the search term used to find the listing; \"Other\" is unbranded cosmetic lenses."
    )
    fig = px.bar(
        by_brand[by_brand["Brand"] != "Other"], x="Brand", y="Lens listings", color="Brand",
        color_discrete_map=BRAND_COLORS, title="Distinct lens listings by brand", text="Lens listings",
    )
    fig.update_layout(showlegend=False)
    st.plotly_chart(fig, width="stretch")

    # ---- ACUVUE sellers ----
    ui.section(
        "Who is offering ACUVUE lenses for online sale",
        "Seller list for J&J. Authorisation is a secondary check: direct online sale of contact lenses is not permitted under the HSA.",
        "ACUVUE",
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
        st.dataframe(
            show, hide_index=True, width="stretch",
            column_config={
                "Price (S$)": st.column_config.NumberColumn(format="%.2f"),
                "Link": st.column_config.LinkColumn("Link", display_text="Open"),
            },
        )
        st.caption(
            "Lenskart Singapore's three rows are contact-lens credit vouchers (\"Moody/Acuvue & more\"), a retailer "
            "product rather than a lens listing. Link is blank where the scrape did not capture a URL."
        )

    # ---- price dispersion on one SKU ----
    ui.section(
        "Same product, different prices: RevitaLens 300 mL",
        "ACUVUE's own lens solution, sold online by several third-party sellers. It is a solution, not a lens, so the HSA rule on contact lenses does not apply to it.",
        "Price spread",
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
        c1, c2 = st.columns([2, 3])
        with c1:
            st.dataframe(
                agg, hide_index=True, width="stretch",
                column_config={c: st.column_config.NumberColumn(format="%.2f") for c in ("Lowest", "Median", "Highest")},
            )
            st.caption(
                f"Listed price in S$. {len(parsed)} of {len(rev)} RevitaLens listings state a pack size; "
                f"the other {len(rev) - len(parsed)} are excluded rather than guessed. "
                "Bundled cases or travel kits are not netted out."
            )
        with c2:
            order = sorted(parsed["Pack"].unique(), key=lambda s: int(s.split()[0]))
            fig = px.strip(parsed, x="Pack", y="selling_price", color="site_name", hover_data=["store_name", "product_name"],
                           category_orders={"Pack": order},
                           labels={"selling_price": "Listed price (S$)", "Pack": "", "site_name": "Site"},
                           title="RevitaLens: listed price by pack size")
            st.plotly_chart(fig, width="stretch")
        big = parsed["Pack"].value_counts().idxmax()
        grp = parsed[parsed["Pack"] == big]["selling_price"]
        ui.insight(
            f"Among the {len(grp)} listings of the same <b>{big}</b> pack, the listed price runs from "
            f"<b>S${grp.min():.2f}</b> to <b>S${grp.max():.2f}</b> ({grp.max() / grp.min():.1f}x). "
            "This is reseller pricing for the same product; whether the cheapest sellers are J&amp;J-authorised is for J&amp;J to confirm.",
            "warn",
        )

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
        st.caption(
            "Some listings sit under a brand only because of the search term that found them "
            "(for example third-party optical vouchers found under Alcon)."
        )

    ebi.limits([
        "Whether a seller is a <b>J&amp;J-authorised retailer</b> or the stock is <b>genuine</b>: needs J&amp;J&rsquo;s authorised-seller list. "
        "Neither changes the HSA position that direct online sale of contact lenses is illegal.",
        "How many lenses are sold, or whether listings are growing or shrinking. This is one snapshot with no sales data.",
        "Shopee: it is not in this database yet. Only Lazada SG and TikTok Shop SG are covered, and only what our search terms surfaced.",
        f"Repeat scrapes are removed ({len(raw_flagged)} flagged rows are {len(flagged)} distinct listings). "
        "Lazada's anonymous &ldquo;Reseller&rdquo; rows can hide several sellers behind one name.",
    ])
