"""Facebook signals (SG) — fb_posts / fb_comments in facebook_data_sg.db (brand pages; no Alcon page)."""

import _social
from sg_common import FB_DB

CFG = _social.Platform(
    key="facebook", label="Facebook", db_path=FB_DB,
    posts_table="fb_posts", comments_table="fb_comments",
    post_id="post_id",
    title_cols=["text"], text_cols=["text"],
    date_col="published_at", url_col="url", channel_col="page",
    metric_cols={"Total likes": "likes_count", "Total shares": "shares_count"},
    comment_text_cols=["comment_text"],
    comment_like_col="like_count", comment_date_col="published_at",
    caveat="Facebook data is brand-page posts plus public comments (no Alcon SG page). Page posts are brand marketing, not consumer opinion; only the comments carry consumer sentiment.",
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
