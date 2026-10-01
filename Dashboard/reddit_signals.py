"""Reddit signals (SG) — reddit_posts / reddit_comments in reddit_data_sg.db. Replaces the HK LIHKG module."""

import _social
from sg_common import REDDIT_DB

CFG = _social.Platform(
    key="reddit", label="Reddit", db_path=REDDIT_DB,
    posts_table="reddit_posts", comments_table="reddit_comments",
    post_id="post_id",
    title_cols=["title"], text_cols=["selftext"],
    date_col="created_utc", url_col="permalink", channel_col="subreddit",
    metric_cols={"Total score": "score", "Total comments": "num_comments"},
    comment_text_cols=["comment_text"],
    comment_like_col="score", comment_date_col="created_utc",
    post_word="threads",
    caveat="Reddit threads are unsolicited forum discussion (mostly r/singapore), not product reviews; many threads are years old.",
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
