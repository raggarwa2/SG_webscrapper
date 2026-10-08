"""Facebook retailers & promotions (SG) -- retailer Page reviews/posts and Meta Ad Library ads.

Source role: channel barriers and competitive activity, NOT product sentiment (see
analysis/facebook_findings_20261007.md). Only contact-lens reviews are barrier-tagged; spectacle-only
reviews are shown separately so they are not mistaken for lens feedback."""

import plotly.express as px
import streamlit as st

import ui
from sg_common import FB_ADS_DB, FB_RETAIL_DB, read_table


@st.cache_data(show_spinner=False, ttl=3600)
def _load():
    rev = read_table(FB_RETAIL_DB, "SELECT * FROM fb_retailer_reviews")
    posts = read_table(FB_RETAIL_DB, "SELECT * FROM fb_retailer_posts")
    ads = read_table(FB_ADS_DB, "SELECT * FROM fb_ads")
    return rev, posts, ads


def render():
    rev, posts, ads = _load()
    if rev.empty and posts.empty and ads.empty:
        st.info("No Facebook retailer or ad data yet. Run facebook_retailers_sg.py and facebook_ads_sg.py.")
        return
    st.caption("Singapore only. Retailer Page reviews and posts, plus Meta Ad Library ads. Use for channel barriers "
               "and promotion activity, not product sentiment.")

    if not rev.empty:
        ui.subheader("Retailer reviews", "Most reviews are about spectacles; only contact-lens reviews are barrier-tagged.", "Facebook")
        rev["type"] = rev["is_contact_lens"].map({1: "Contact lens", 0: "Other / spectacles"}).fillna("Other / spectacles")
        by = rev.groupby(["retailer", "type"]).size().reset_index(name="reviews")
        fig = px.bar(by, x="retailer", y="reviews", color="type", labels={"retailer": "", "reviews": "Reviews", "type": ""})
        st.plotly_chart(fig, width="stretch")
        st.caption("Pages with no Facebook reviews (reviews switched off): Optical 88, Visio Optical, Lenskart SG, "
                   "Watsons SG, Guardian SG, Unity Pharmacy.")

        cl = rev[(rev["is_contact_lens"] == 1) & rev["barrier_tag"].notna()]
        if not cl.empty:
            ui.subheader("Contact-lens barriers at retailers", "Complaints vs positive reviews where the retailer solved the barrier. Tiny samples, directional only.", "Facebook")
            tag = cl.groupby(["barrier_tag", "barrier_polarity"]).size().reset_index(name="mentions")
            fig = px.bar(tag, y="barrier_tag", x="mentions", color="barrier_polarity", orientation="h",
                         labels={"barrier_tag": "", "mentions": "Mentions", "barrier_polarity": ""})
            st.plotly_chart(fig, width="stretch")
            st.caption("Tags marked [PROPOSED] are not yet in the project's 10-barrier taxonomy.")
            show = cl[["retailer", "barrier_polarity", "barrier_tag", "text"]].rename(
                columns={"retailer": "Retailer", "barrier_polarity": "Type", "barrier_tag": "Barrier", "text": "Review"})
            st.dataframe(show, hide_index=True, width="stretch", height=280)

    if not posts.empty:
        ui.subheader("Contact-lens promotion posts by retailer", "Retailer Page posts that mention contact lenses.", "Facebook")
        cp = posts[posts["is_contact_lens"] == 1]
        if not cp.empty:
            n = cp.groupby("retailer").size().reset_index(name="posts").sort_values("posts", ascending=False)
            st.plotly_chart(px.bar(n, x="retailer", y="posts", labels={"retailer": "", "posts": "Posts (last 50 per page)"}), width="stretch")
            top = cp.sort_values("likes_count", ascending=False).head(15)[["retailer", "published_at", "likes_count", "text"]]
            st.dataframe(top.rename(columns={"retailer": "Retailer", "published_at": "Date", "likes_count": "Likes", "text": "Post"}),
                         hide_index=True, width="stretch", height=300)

    if not ads.empty:
        ui.subheader("Ads running in Singapore (Meta Ad Library)", "Only advertisers confirmed as Singapore entities are counted as SG.", "Facebook")
        a = ads[ads["brand_relevant"] == 1].copy()
        a["Advertiser status"] = a["sg_verified"].map({1: "Confirmed SG", 0: "Unverified advertiser country"})
        c = a.groupby(["page_name", "Advertiser status"]).agg(ads=("ad_key", "count"), active=("is_active", "sum")).reset_index()
        top_ads = c.sort_values("ads", ascending=False).head(12)
        fig = px.bar(top_ads, y="page_name", x="ads", color="Advertiser status", orientation="h",
                     color_discrete_map={"Confirmed SG": "#178197", "Unverified advertiser country": "#B7791F"},
                     labels={"page_name": "", "ads": "Ads", "Advertiser status": ""}, text="ads")
        fig.update_yaxes(autorange="reversed")
        fig.update_layout(height=90 + 34 * len(top_ads), legend=dict(orientation="h", y=-0.2))
        st.plotly_chart(fig, width="stretch")
        ui.show_data("Show all advertisers", c.rename(columns={"page_name": "Advertiser", "ads": "Ads", "active": "Active"}).sort_values("Ads", ascending=False))
        st.caption("The Ad Library gives no advertiser country, so unconfirmed advertisers may be overseas. Many ads are variants of one creative.")
