"""Instagram signals (SG) — ig_posts / ig_comments in instagram_data_sg.db."""

import _social
from sg_common import IG_DB

CFG = _social.Platform(
    key="instagram", label="Instagram", db_path=IG_DB,
    posts_table="ig_posts", comments_table="ig_comments",
    post_id="post_id",
    title_cols=["caption_en", "caption"], text_cols=["caption_en", "caption"],
    date_col="published_at", url_col="url", channel_col="owner_username",
    metric_cols={"Total likes": "likes_count", "Total comments": "comments_count"},
    comment_text_cols=["comment_text_en", "comment_text"],
    comment_like_col="like_count", comment_date_col="published_at",
    extra_post_filters=["market_relevant"],
    caveat="Instagram posts are brand/creator content and comments are audience reactions. Posts flagged not SG-relevant or not about the tagged brand are excluded.",
)


def load_sg_dashboard_data():
    """(posts, comments, excluded_posts) — see _social.load_data."""
    return _social.load_data(CFG)


def on_topic_comments(comments):
    return _social.on_topic(comments)


def purchase_barrier_rate(on_topic_df):
    return _social.purchase_barrier_rate(on_topic_df)


def get_monthly_comment_counts(brand):
    return _social.monthly_counts(CFG, brand)


def render():
    _social.render(CFG)
