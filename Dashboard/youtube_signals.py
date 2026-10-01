"""YouTube signals (SG) — yt_videos / yt_comments in youtube_data_sg.db."""

import _social
from sg_common import YT_DB

CFG = _social.Platform(
    key="youtube", label="YouTube", db_path=YT_DB,
    posts_table="yt_videos", comments_table="yt_comments",
    post_id="video_id", comment_post_id="video_id",
    title_cols=["title_en", "title"], text_cols=["description_en", "description"],
    date_col="published_at", url_col="url", channel_col="channel_title",
    metric_cols={"Total views": "view_count", "Total likes": "like_count"},
    comment_text_cols=["comment_text_en", "comment_text"],
    comment_like_col="like_count", comment_date_col="published_at",
    post_word="videos",
    caveat="YouTube comments are unsolicited viewer reactions to a video, not product reviews. View/like counts are a reach proxy, not a reception signal.",
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
