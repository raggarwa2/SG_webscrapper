"""
Brand Overview: the first tab, laid out like the HK dashboard. A scorecard table (one row per brand: products, stores, weighted
rating, reviews, then how many comments or posts each channel holds), the rating chart under it, and the competitors and category
page below. Channel counts are the pooled items of voice_data, so they match every other page.
"""

import pandas as pd
import plotly.express as px
import streamlit as st

import ebi
import market_competitors
import ui
import voice_data as vd
from sg_common import BRAND_COLORS

# Pool sources shown as one scorecard column each (posts and comments of a channel are added together).
SCORE_COLS = {
    "KiasuParents": ["KiasuParents"],
    "XHS": ["Xiaohongshu", "Xiaohongshu comments"],
    "Reddit": ["Reddit"],
    "YouTube": ["YouTube"],
    "Instagram": ["Instagram"],
    "Facebook": ["Facebook"],
}


def scorecard(products: pd.DataFrame, reviews: pd.DataFrame, pool: pd.DataFrame, brands: list, weighted_rating) -> pd.DataFrame:
    rows, rating_n = [], {}
    for b in brands:
        bp, br = products[products["brand"] == b], reviews[reviews["brand"] == b]
        n_rev = int(bp.loc[bp["total_reviews"] > 0, "total_reviews"].sum())
        rating_n[b] = n_rev
        rating = weighted_rating(bp) if n_rev >= ebi.MIN_N else float("nan")
        row = {"Brand": b, "Products": len(bp), "Stores": bp["store_name"].nunique(),
               "Weighted rating": round(rating, 2) if pd.notna(rating) else None, "Reviews collected": len(br)}
        pb = pool[pool["brand_std"] == b]
        for col, sources in SCORE_COLS.items():
            row[f"{col} items"] = int(pb["source"].isin(sources).sum())
        row["Social signals"] = sum(row[f"{c} items"] for c in SCORE_COLS if c != "KiasuParents")
        rows.append(row)
    out = pd.DataFrame(rows)
    out.attrs["rating_n"] = rating_n
    return out


def render(products: pd.DataFrame, reviews: pd.DataFrame, d: pd.DataFrame, brands: list, weighted_rating,
           caption: str, story_frames) -> None:
    _pool0 = vd.pool(d) if not d.empty else pd.DataFrame(columns=["brand_std", "source"])
    _sel = _pool0[_pool0["brand_std"].isin(brands)]["brand_std"].value_counts()
    st.subheader(f"{_sel.index[0]} is heard most ({_sel.iloc[0] / _sel.sum() * 100:.0f}% of brand-named items); ratings are too thin to rank brands" if len(_sel)
                 else "Brand health scorecard")
    st.caption(caption)
    st.caption("Channel columns count the comments and posts that name the brand and are about lenses (the brand pool; giveaway "
               "entries removed). Weighted rating is shown when a brand has 15+ ratings. Brand Health reads sentiment across these channels.")
    pool = vd.pool(d) if not d.empty else pd.DataFrame(columns=["brand_std", "source"])
    sc = scorecard(products, reviews, pool, brands, weighted_rating)
    if sc.empty:
        st.info("No brands selected.")
    else:
        st.dataframe(sc, hide_index=True, width="stretch")
        rated = sc.dropna(subset=["Weighted rating"]).sort_values("Weighted rating", ascending=False)
        unrated = [b for b in sc["Brand"] if b not in set(rated["Brand"])]
        if rated.empty:
            ui.section("No brand has enough ratings to chart", f"Weighted rating needs {ebi.MIN_N}+ ratings on the retailer pages scraped.", "Ratings", kind="fact")
        else:
            focal = rated[rated["Brand"] == "Acuvue"]
            lead = (f"Acuvue rates {focal.iloc[0]['Weighted rating']:.2f} of 5 on {sc.attrs['rating_n']['Acuvue']:,} ratings; "
                    f"{len(rated)} of {len(sc)} brands have enough ratings to compare" if len(focal)
                    else f"Only {len(rated)} of {len(sc)} brands have enough ratings to compare, and Acuvue is not one of them")
            ui.section(lead, "Rating weighted by each product's number of ratings, retailer pages only. A gap is not tested for significance.", "Ratings", kind="fact")
            fig = px.bar(rated, x="Brand", y="Weighted rating", color="Brand", color_discrete_map=BRAND_COLORS, range_y=[0, 5], text="Weighted rating")
            fig.update_traces(textposition="outside", cliponaxis=False)
            fig.update_layout(showlegend=False)
            ui.plot(fig, "", "fact",
                    (f"No rating shown for {', '.join(unrated)}: under {ebi.MIN_N} ratings on the retailer pages scraped. "
                     "Ratings are thin across the category, and a brand's absence here is not a low score." if unrated else ""),
                    bases={b: sc.attrs["rating_n"][b] for b in rated["Brand"]}, noun="ratings")

    st.divider()
    st.markdown("#### Competitors & category")
    market_competitors.render(products, story_frames(), brands)
    ui.read_comments(pool[pool["brand_std"].isin(brands)], "Read the brand comments behind this page (brand pool)", key="bo_read")
