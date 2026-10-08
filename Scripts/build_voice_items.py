"""
build_voice_items.py

Phase 1 of the common-taxonomy plan: one table, one row per piece of voice, with the same columns whatever the channel.

Every scraped source has its own column names, date format, brand spelling and relevance flags. This script reads them all
(read-only) and writes Scripts/output/voice_items_sg.db, table voice_items, so that the tagger (next phase) and every dashboard
page start from one frame instead of re-deriving it per page.

What each row says:
  unit        comment | post | thread | review | ad
  voice_type  consumer | brand_owned | retailer_customer | retailer_owned | app_user | paid_ad
                brand_owned = the account belongs to a tracked brand (name match on the account; owner_brand says whose)
  entity_type brand | retailer | app   (Google Maps and Facebook retailer reviews are about a retailer, not a brand)
  brand_std   Acuvue | Alcon | Bausch & Lomb | CooperVision | Olens, else NULL (Dashboard/sg_common.normalize_brand)
  in_pool     1 if the item is in the Brand Health pool (brand-attributed + relevant + one of the 4 sentiment labels), the
              same rule as Dashboard/insights.build_frames
              PLUS the contest exclusion above; the dashboard applies the same rule (sg_common.is_contest_caption). Brand-owned posts, app, Google Maps, retailer and ad rows are 0.
  lens        which analysis lens the row belongs to: consumer_voice | owned_experience | retail_experience | brand_broadcast
  is_contest  1 for a giveaway post, or a comment written to enter one (a contest entry is not a consumer opinion, so it is
              kept out of the pool). Instagram: the parent caption has a contest word AND a way to enter by commenting
              (comment, tell us, tag a friend, how to enter, answer); a caption that only says "win by signing up" is not
              enough, because its comments are ordinary reactions. Facebook: the scraper's own is_contest_or_spam flag.
  journey_stage_src is the old per-source constant, kept for reference only; it is not a per-item measurement.

Not included (not voice): product and price listings, Google Trends, app metadata.

Usage:
  python build_voice_items.py            # rebuilds voice_items_sg.db and prints a QA report
  python build_voice_items.py --check    # QA report only, from the existing db
"""
from __future__ import annotations

import argparse
import hashlib
import json
import re
import sqlite3
import sys
from datetime import datetime, timezone
from pathlib import Path

import pandas as pd

ROOT = Path(__file__).resolve().parent.parent
OUT = Path(__file__).resolve().parent / "output"
DEST = OUT / "voice_items_sg.db"
sys.path.insert(0, str(ROOT / "Dashboard"))
from sg_common import BRAND_COLORS, is_contest_caption, normalize_brand  # noqa: E402  (pandas + stdlib only)

TRACKED = list(BRAND_COLORS)
LABELS = ("positive", "neutral", "mixed", "negative")
NAME_KEYS = {"Acuvue": "acuvue", "Alcon": "alcon", "Bausch & Lomb": "bausch", "CooperVision": "coopervision", "Olens": "olens"}

COLUMNS = [
    "item_id", "source", "source_table", "native_id", "parent_id", "unit", "voice_type", "entity_type", "lens",
    "brand_raw", "brand_std", "retailer", "account", "owner_brand", "market", "date", "title", "text_en", "text_orig",
    "lang_guess", "text_translated", "url", "likes", "views", "rating_native", "sentiment_native", "native_themes",
    "native_barrier", "journey_stage_src", "brand_relevant", "sg_relevant", "lens_relevant", "is_contest", "in_pool", "built_at",
]
LENS_OF = {"consumer": "consumer_voice", "app_user": "owned_experience", "retailer_customer": "retail_experience",
           "brand_owned": "brand_broadcast", "paid_ad": "brand_broadcast", "retailer_owned": "brand_broadcast"}


def ro(name: str) -> sqlite3.Connection:
    p = (OUT / name).as_posix()
    return sqlite3.connect(f"file:{p}?mode=ro", uri=True)


def read(db: str, sql: str) -> pd.DataFrame:
    try:
        con = ro(db)
        try:
            return pd.read_sql_query(sql, con)
        finally:
            con.close()
    except Exception as exc:  # a missing source must not stop the others
        print(f"  ! {db}: {exc}")
        return pd.DataFrame()


def to_date(s: pd.Series) -> pd.Series:
    """Epoch seconds (Xiaohongshu), ISO strings and plain timestamps -> YYYY-MM-DD (UTC)."""
    s = pd.Series(s).reset_index(drop=True)
    num = pd.to_numeric(s, errors="coerce")
    a = pd.to_datetime(num, unit="s", utc=True, errors="coerce")
    b = pd.to_datetime(s.where(num.isna()), utc=True, errors="coerce", format="mixed")
    return a.fillna(b).dt.strftime("%Y-%m-%d")


_CJK = re.compile(r"[㐀-鿿가-힯぀-ヿ]")


def lang_guess(text) -> str | None:
    t = str(text or "")
    if not t.strip():
        return None
    return "zh/ko/ja" if len(_CJK.findall(t)) / max(len(t), 1) > 0.15 else "en"


def clean_text(v):
    if v is None or (isinstance(v, float) and pd.isna(v)):
        return None
    v = re.sub(r"\s+", " ", str(v)).strip()
    return v or None


_OWNER_RE = re.compile(r"(?<![a-z])(?:my)?(" + "|".join(NAME_KEYS.values()) + ")")


def owner_of(account) -> str | None:
    """Which tracked brand's official account this is, else None. Name match anchored at the start of a word (optionally
    after 'my'), so 'opticalconshop' is not read as Alcon. Still directional: it cannot tell a reseller named after a brand."""
    m = _OWNER_RE.search(re.sub(r"[^a-z0-9]+", " ", str(account or "").lower()))
    if not m:
        return None
    return next(b for b, k in NAME_KEYS.items() if k == m.group(1))


def sent_ok(s: pd.Series) -> pd.Series:
    return s.isin(LABELS)


def std(df: pd.DataFrame, source: str, table: str, unit: str, voice, **cols) -> pd.DataFrame:
    """Build the standard frame. Each kwarg is a column name in df, a Series aligned to df, or a constant."""
    if df is None or df.empty:
        return pd.DataFrame(columns=COLUMNS)
    df = df.reset_index(drop=True)
    o = pd.DataFrame(index=df.index)
    for k, v in cols.items():
        if isinstance(v, pd.Series):
            o[k] = v.reset_index(drop=True)
        elif isinstance(v, str) and v in df.columns:
            o[k] = df[v]
        else:
            o[k] = v
    o["source"], o["source_table"], o["unit"] = source, table, unit
    o["voice_type"] = voice.reset_index(drop=True) if isinstance(voice, pd.Series) else voice
    return o


def finish(o: pd.DataFrame) -> pd.DataFrame:
    for c in COLUMNS:
        if c not in o.columns:
            o[c] = None
    o["brand_std"] = o["brand_raw"].map(normalize_brand)
    o.loc[~o["brand_std"].isin(TRACKED), "brand_std"] = None
    o["market"] = o["market"].fillna("SG")
    o["entity_type"] = o["entity_type"].fillna("brand")
    o["lens"] = o["voice_type"].map(LENS_OF)
    o["text_en"] = o["text_en"].map(clean_text)
    o["text_orig"] = o["text_orig"].map(clean_text)
    o["text_en"] = o["text_en"].fillna(o["text_orig"])
    o["lang_guess"] = o["text_orig"].fillna(o["text_en"]).map(lang_guess)
    o["text_translated"] = ((o["text_orig"].notna()) & (o["text_en"] != o["text_orig"])).astype(int)
    o["in_pool"] = o["in_pool"].fillna(0).astype(int)
    o["is_contest"] = o["is_contest"].fillna(0).astype(int)
    o["item_id"] = [hashlib.sha1(f"{s}|{t}|{n}".encode("utf-8")).hexdigest()[:16]
                    for s, t, n in zip(o["source"], o["source_table"], o["native_id"])]
    o["built_at"] = datetime.now(timezone.utc).strftime("%Y-%m-%d %H:%M:%S")
    return o[COLUMNS]


def flag(s: pd.Series) -> pd.Series:
    """Source flag -> 1 / 0 / NULL (NULL stays unknown, as the dashboard's 'NaN fails open')."""
    return pd.to_numeric(s, errors="coerce").astype("Int64")


# ---------------------------------------------------------------- social platforms (posts + comments)
def load_youtube():
    p = read("youtube_data_sg.db", "SELECT * FROM yt_videos")
    p["_title"] = p["title_en"].fillna(p["title"])
    p["_text"] = p["description_en"].fillna(p["description"])
    p["_orig"] = p["description"].fillna(p["title"])
    p["_url"] = p["url"]
    p["_likes"] = pd.to_numeric(p["like_count"], errors="coerce")
    p["_views"] = pd.to_numeric(p["view_count"], errors="coerce")
    posts = std(p, "YouTube", "yt_videos", "post",
                pd.Series(["brand_owned" if owner_of(a) else "consumer" for a in p["channel_title"]]),
                native_id="video_id", brand_raw="brand", account="channel_title",
                owner_brand=p["channel_title"].map(owner_of), title=p["_title"].map(clean_text),
                text_en=p["_text"], text_orig=p["_orig"], date=to_date(p["published_at"]), url="_url",
                likes="_likes", views="_views", journey_stage_src="journey_stage", brand_relevant=flag(p["brand_relevant"]),
                lens_relevant=flag(p["is_lens_relevant"]), market="market")
    c = read("youtube_data_sg.db", "SELECT * FROM yt_comments")
    ok = p.set_index("video_id")["brand_relevant"].reindex(c["video_id"]).fillna(1).to_numpy() != 0
    pool = pd.Series(ok) & (flag(c["is_lens_relevant"]).fillna(1) != 0).reset_index(drop=True) & sent_ok(c["sentiment"]).reset_index(drop=True) \
        & c["brand"].map(normalize_brand).isin(TRACKED).reset_index(drop=True)
    comments = std(c, "YouTube", "yt_comments", "comment", "consumer", native_id="id", parent_id="video_id",
                   brand_raw="brand", account="author", text_en="comment_text_en", text_orig="comment_text",
                   date=to_date(c["published_at"]), likes=pd.to_numeric(c["like_count"], errors="coerce"),
                   sentiment_native="sentiment", brand_relevant=pd.Series(ok).astype(int),
                   lens_relevant=flag(c["is_lens_relevant"]), market="market", in_pool=pool.astype(int))
    return pd.concat([posts, comments], ignore_index=True)


def load_instagram():
    p = read("instagram_data_sg.db", "SELECT * FROM ig_posts")
    p["_contest"] = [is_contest_caption(a, b) for a, b in zip(p["caption_en"], p["caption"])]
    posts = std(p, "Instagram", "ig_posts", "post",
                pd.Series(["brand_owned" if owner_of(a) else "consumer" for a in p["owner_username"]]),
                native_id="post_id", brand_raw="brand", account="owner_username",
                owner_brand=p["owner_username"].map(owner_of), text_en="caption_en", text_orig="caption",
                date=to_date(p["published_at"]), url="url", likes=pd.to_numeric(p["likes_count"], errors="coerce"),
                views=pd.to_numeric(p["video_views"], errors="coerce"), journey_stage_src="journey_stage",
                brand_relevant=flag(p["brand_relevant"]), sg_relevant=flag(p["market_relevant"]),
                lens_relevant=flag(p["is_lens_relevant"]), is_contest=p["_contest"].astype(int), market="market")
    c = read("instagram_data_sg.db", "SELECT * FROM ig_comments")
    contest = p.set_index("post_id")["_contest"].reindex(c["post_id"]).fillna(False).astype(bool).to_numpy()
    pr = p.set_index("post_id")[["brand_relevant", "market_relevant"]].reindex(c["post_id"])
    ok = ((pr["brand_relevant"].fillna(1) != 0) & (pr["market_relevant"].fillna(1) != 0)).to_numpy()
    pool = pd.Series(ok) & (flag(c["is_lens_relevant"]).fillna(1) != 0).reset_index(drop=True) & sent_ok(c["sentiment"]).reset_index(drop=True) \
        & c["brand"].map(normalize_brand).isin(TRACKED).reset_index(drop=True) & ~pd.Series(contest)
    comments = std(c, "Instagram", "ig_comments", "comment", "consumer", native_id="id", parent_id="post_id",
                   brand_raw="brand", account="author", text_en="comment_text_en", text_orig="comment_text",
                   date=to_date(c["published_at"]), likes=pd.to_numeric(c["like_count"], errors="coerce"),
                   sentiment_native="sentiment", brand_relevant=pd.Series(ok).astype(int),
                   lens_relevant=flag(c["is_lens_relevant"]), is_contest=pd.Series(contest).astype(int), market="market",
                   in_pool=pool.astype(int))
    return pd.concat([posts, comments], ignore_index=True)


def load_facebook():
    p = read("facebook_data_sg.db", "SELECT * FROM fb_posts")
    posts = std(p, "Facebook", "fb_posts", "post", "brand_owned", native_id="post_id", brand_raw="brand", account="page",
                owner_brand=p["page"].map(owner_of).fillna(p["brand"].map(normalize_brand)), text_orig="text",
                date=to_date(p["published_at"]), url="url", likes=pd.to_numeric(p["likes_count"], errors="coerce"),
                journey_stage_src="journey_stage", sg_relevant=flag(p["market_relevant"]),
                lens_relevant=flag(p["is_lens_relevant"]), market="market")
    c = read("facebook_data_sg.db", "SELECT * FROM fb_comments")
    pr = p.set_index("post_id")["market_relevant"].reindex(c["post_id"])
    ok = (pr.fillna(1) != 0).to_numpy()
    spam = (flag(c["is_contest_or_spam"]).fillna(0) == 1).reset_index(drop=True)
    pool = pd.Series(ok) & (flag(c["is_lens_relevant"]).fillna(1) != 0).reset_index(drop=True) & sent_ok(c["sentiment"]).reset_index(drop=True) \
        & c["brand"].map(normalize_brand).isin(TRACKED).reset_index(drop=True) & ~spam
    comments = std(c, "Facebook", "fb_comments", "comment", "consumer", native_id="id", parent_id="post_id",
                   brand_raw="brand", account="author", text_orig="comment_text", date=to_date(c["published_at"]),
                   likes=pd.to_numeric(c["like_count"], errors="coerce"), sentiment_native="sentiment",
                   native_barrier="barrier_tag", lens_relevant=flag(c["is_lens_relevant"]),
                   is_contest=spam.astype(int), sg_relevant=pd.Series(ok).astype(int), market="market", in_pool=pool.astype(int))
    return pd.concat([posts, comments], ignore_index=True)


def load_reddit():
    p = read("reddit_data_sg.db", "SELECT * FROM reddit_posts")
    p["_text"] = p["selftext"]
    posts = std(p, "Reddit", "reddit_posts", "post", "consumer", native_id="post_id", brand_raw="brand",
                account="author", title=p["title"].map(clean_text), text_orig="_text",
                date=to_date(p["created_utc"]),
                url=p["permalink"].map(lambda u: "https://www.reddit.com" + u if isinstance(u, str) and u.startswith("/r/") else u),
                likes=pd.to_numeric(p["score"], errors="coerce"), journey_stage_src="journey_stage",
                brand_relevant=flag(p["brand_relevant"]), lens_relevant=flag(p["is_lens_relevant"]), market="market")
    c = read("reddit_data_sg.db", "SELECT * FROM reddit_comments")
    ok = (p.set_index("post_id")["brand_relevant"].reindex(c["post_id"]).fillna(1) != 0).to_numpy()
    pool = pd.Series(ok) & (flag(c["is_lens_relevant"]).fillna(1) != 0).reset_index(drop=True) & sent_ok(c["sentiment"]).reset_index(drop=True) \
        & c["brand"].map(normalize_brand).isin(TRACKED).reset_index(drop=True)
    comments = std(c, "Reddit", "reddit_comments", "comment", "consumer", native_id="id", parent_id="post_id",
                   brand_raw="brand", account="author", text_orig="comment_text", date=to_date(c["created_utc"]),
                   likes=pd.to_numeric(c["score"], errors="coerce"), sentiment_native="sentiment",
                   brand_relevant=pd.Series(ok).astype(int), lens_relevant=flag(c["is_lens_relevant"]),
                   market="market", in_pool=pool.astype(int))
    return pd.concat([posts, comments], ignore_index=True)


# ---------------------------------------------------------------- Xiaohongshu, forum, Lazada
def load_xhs():
    p = read("xhs_data_sg.db", "SELECT * FROM xhs_posts")
    p["_brand"] = p["brand_mentioned"]
    attributed = p["_brand"].map(normalize_brand).isin(TRACKED) & (flag(p["brand_relevant"]).fillna(1) != 0)
    posts = std(p, "Xiaohongshu", "xhs_posts", "post", "consumer", native_id="post_id", brand_raw="_brand",
                account="author", title=p["title"].map(clean_text), text_en="content_en", text_orig="content_zh",
                date=to_date(p["publish_date"]), url="url", likes=pd.to_numeric(p["likes"], errors="coerce"),
                sentiment_native="sentiment", native_themes="themes", journey_stage_src="journey_stage",
                brand_relevant=flag(p["brand_relevant"]), sg_relevant=flag(p["market_relevant"]), market="SG",
                in_pool=(attributed & sent_ok(p["sentiment"]) & p["content_en"].map(clean_text).notna()).astype(int))
    c = read("xhs_data_sg.db", "SELECT c.*, p.brand_mentioned AS _brand, p.brand_relevant AS _br, p.url AS _url "
                               "FROM xhs_comments c JOIN xhs_posts p ON p.post_id = c.post_id")
    att = c["_brand"].map(normalize_brand).isin(TRACKED) & (flag(c["_br"]).fillna(1) != 0)
    comments = std(c, "Xiaohongshu comments", "xhs_comments", "comment", "consumer", native_id="id", parent_id="post_id",
                   brand_raw="_brand", account="author", text_en="content_en", text_orig="content_zh", url="_url",
                   likes=pd.to_numeric(c["likes"], errors="coerce"), sentiment_native="sentiment",
                   native_themes="themes", brand_relevant=flag(c["_br"]), market="SG",
                   in_pool=(att & sent_ok(c["sentiment"]) & c["content_en"].map(clean_text).notna()).astype(int))
    return pd.concat([posts, comments], ignore_index=True)


def load_forum():
    f = read("sg_acuvue.db", "SELECT * FROM forum_posts")
    if f.empty:
        return f

    def sent(r):
        if pd.notna(r["sentiment"]):
            return r["sentiment"]
        try:
            return json.loads(r["topic_tags"]).get("sentiment")
        except Exception:
            return None
    f["_sent"] = f.apply(sent, axis=1)
    f["_text"] = f["content_summary"].fillna(f["post_title"])
    return std(f, "KiasuParents", "forum_posts", "thread", "consumer", native_id="id", brand_raw="brand",
               title=f["post_title"].map(clean_text), text_orig="_text", date=to_date(f["post_date"]), url="post_url",
               sentiment_native="_sent", native_themes="attribute_tags", journey_stage_src="journey_stage",
               in_pool=(sent_ok(f["_sent"]) & f["brand"].map(normalize_brand).isin(TRACKED)
                        & f["_text"].map(clean_text).notna()).astype(int))


def load_lazada():
    r = read("sg_acuvue.db", "SELECT * FROM reviews")
    if r.empty:
        return r
    stars = r["rating"].map(lambda v: None if pd.isna(v) or v <= 0 else "positive" if v >= 4 else "neutral" if v == 3 else "negative")
    r["_sent"] = r["sentiment"].where(sent_ok(r["sentiment"]), stars)   # stars only fill a gap, as in the dashboard
    return std(r, "Lazada reviews", "reviews", "review", "consumer", native_id="id", brand_raw="brand",
               account="store_name", text_orig="review_text", date=to_date(r["review_date"]),
               likes=pd.to_numeric(r["helpful_count"], errors="coerce"), rating_native=pd.to_numeric(r["rating"], errors="coerce"),
               sentiment_native="_sent", native_themes="attribute_tags", journey_stage_src="journey_stage",
               in_pool=(sent_ok(r["_sent"]) & r["brand"].map(normalize_brand).isin(TRACKED)
                        & r["review_text"].map(clean_text).notna()).astype(int))


# ---------------------------------------------------------------- outside the brand pool
def load_app():
    a = read("app_data_sg.db", "SELECT * FROM app_reviews")
    a["_title"] = a["title"].map(clean_text)
    return std(a, "MyACUVUE app", "app_reviews", "review", "app_user", entity_type="app", native_id="review_id",
               brand_raw="Acuvue", account="platform", retailer=a["store"], title="_title", text_orig="text",
               date=to_date(a["date"]), likes=pd.to_numeric(a["thumbs_up"], errors="coerce"),
               rating_native=pd.to_numeric(a["rating"], errors="coerce"))


def load_gmaps():
    g = read("gmaps_data_sg.db", "SELECT * FROM gmaps_reviews")
    clear = ((flag(g["is_lens_related"]) == 1) & (flag(g["cl_keyword"]) == 1)).astype(int)   # 'clearly contact lens' pair
    return std(g, "Google Maps", "gmaps_reviews", "review", "retailer_customer", entity_type="retailer",
               native_id="review_id", parent_id="place_id", brand_raw=None, retailer="chain", account="place_name",
               text_orig="text", date=to_date(g["published_at"]), likes=pd.to_numeric(g["likes"], errors="coerce"),
               rating_native=pd.to_numeric(g["rating"], errors="coerce"), sentiment_native="sentiment",
               native_themes="themes", lens_relevant=clear)


def load_fb_retailers():
    r = read("facebook_retailers_sg.db", "SELECT * FROM fb_retailer_reviews")
    p = read("facebook_retailers_sg.db", "SELECT * FROM fb_retailer_posts")
    rev = std(r, "Facebook retailer reviews", "fb_retailer_reviews", "review", "retailer_customer", entity_type="retailer",
              native_id="review_key", brand_raw=None, retailer="retailer", account="reviewer", text_orig="text",
              date=to_date(r["published_at"]), likes=pd.to_numeric(r["likes"], errors="coerce"),
              rating_native=pd.to_numeric(r["recommended"], errors="coerce"),   # 1 = recommends, 0 = does not (no stars)
              native_barrier="barrier_tag", lens_relevant=flag(r["is_contact_lens"]))
    post = std(p, "Facebook retailer posts", "fb_retailer_posts", "post", "retailer_owned", entity_type="retailer",
               native_id="post_id", brand_raw=None, retailer="retailer", account="page", text_orig="text",
               date=to_date(p["published_at"]), url="url", likes=pd.to_numeric(p["likes_count"], errors="coerce"),
               lens_relevant=flag(p["is_contact_lens"]))
    return pd.concat([rev, post], ignore_index=True)


def load_ads():
    a = read("facebook_ads_sg.db", "SELECT * FROM fb_ads")
    return std(a, "Facebook ads", "fb_ads", "ad", "paid_ad", native_id="ad_key", brand_raw="brand", account="page_name",
               owner_brand=a["page_name"].map(owner_of), title=a["headline"].map(clean_text), text_orig="ad_text",
               date=to_date(a["start_date"]), url="ad_library_url", brand_relevant=flag(a["brand_relevant"]),
               sg_relevant=flag(a["sg_verified"]))


# ---------------------------------------------------------------- build + QA
def build() -> pd.DataFrame:
    loaders = [load_youtube, load_instagram, load_facebook, load_reddit, load_xhs, load_forum, load_lazada, load_app,
               load_gmaps, load_fb_retailers, load_ads]
    parts = []
    for fn in loaders:
        d = fn()
        print(f"  {fn.__name__:<20} {len(d):>6} rows")
        parts.append(d)
    items = finish(pd.concat([p for p in parts if not p.empty], ignore_index=True))
    items["native_id"] = items["native_id"].astype(str)
    items["parent_id"] = items["parent_id"].astype("string").astype(object).where(items["parent_id"].notna(), None)
    items = inherit_urls(items)
    dup = int(items["item_id"].duplicated().sum())
    if dup:
        print(f"  ! {dup} duplicate item_ids; keeping the first of each")
        items = items.drop_duplicates("item_id")
    return items


def inherit_urls(items: pd.DataFrame) -> pd.DataFrame:
    """Comments carry no link of their own: give each the link of the post it sits under."""
    post_url = items[(items["unit"] == "post") & items["url"].notna()].set_index(["source", "native_id"])["url"]
    post_url = post_url[~post_url.index.duplicated()]
    m = items["url"].isna() & items["parent_id"].notna() & (items["unit"] == "comment")
    keys = pd.MultiIndex.from_arrays([items.loc[m, "source"], items.loc[m, "parent_id"].astype(str)])
    items.loc[m, "url"] = post_url.reindex(keys).to_numpy()
    return items


def write(items: pd.DataFrame) -> None:
    tmp = DEST.with_suffix(".tmp")
    tmp.unlink(missing_ok=True)
    con = sqlite3.connect(tmp)
    items.to_sql("voice_items", con, index=False)
    con.execute("CREATE UNIQUE INDEX ux_voice_items ON voice_items(item_id)")
    con.execute("CREATE INDEX ix_voice_items_lens ON voice_items(lens, brand_std)")
    con.commit()
    con.close()
    tmp.replace(DEST)


def qa(items: pd.DataFrame) -> None:
    pd.set_option("display.width", 200, "display.max_columns", 30, "display.max_rows", 100)
    print("\n== rows by source / unit / voice_type ==")
    print(items.groupby(["lens", "source", "unit", "voice_type"]).size().rename("n").to_string())
    print("\n== brand_std by lens (NULL = not brand-attributed / retailer rows) ==")
    print(items.assign(brand_std=items["brand_std"].fillna("(none)")).pivot_table(
        index="brand_std", columns="lens", values="item_id", aggfunc="count", fill_value=0).to_string())
    print("\n== completeness: % of rows with a value ==")
    for c in ("date", "text_en", "url", "sentiment_native", "native_themes", "rating_native"):
        print(f"  {c:<18}", (items.groupby("source")[c].apply(lambda s: round(s.notna().mean() * 100))).to_dict())
    print("\n== language / translation (share of rows with CJK text; of those, % with an English version) ==")
    zh = items[items["lang_guess"] == "zh/ko/ja"]
    print(f"  {len(zh)} rows look non-English;", zh.groupby("source").apply(
        lambda d: f"{len(d)} rows, {round(d['text_translated'].mean() * 100)}% translated").to_dict())
    print("\n== brand-owned vs consumer posts (name match on account) ==")
    print(items[items["unit"].isin(["post", "thread"])].pivot_table(
        index="source", columns="voice_type", values="item_id", aggfunc="count", fill_value=0).to_string())
    print("\n== contest entries (kept out of the pool) ==")
    k = items[items["is_contest"] == 1]
    print(k.groupby(["source", "unit", "brand_std"], dropna=False).size().rename("n").to_string() if len(k) else "  none")
    print("\n== pool reconciliation: in_pool rows vs model-tagged items in theme_tags_sg.db ==")
    try:
        con = ro("theme_tags_sg.db")
        tagged = dict(con.execute("SELECT source, COUNT(*) FROM theme_tags GROUP BY source").fetchall())
        con.close()
    except Exception as exc:
        tagged = {}
        print("  (theme_tags_sg.db not readable:", exc, ")")
    pool = items[items["in_pool"] == 1]
    rec = pd.DataFrame({"in_pool_rows": pool.groupby("source").size(),
                        "distinct_brand_text": pool.assign(k=pool["brand_std"].fillna("") + "|" + pool["text_en"].fillna("").str.lower())
                        .groupby("source")["k"].nunique()}).fillna(0).astype(int)
    rec["tagged_in_db"] = pd.Series(tagged)
    print(rec.fillna(0).astype(int).to_string())
    print(f"  total in_pool = {len(pool)}")


def main() -> None:
    ap = argparse.ArgumentParser()
    ap.add_argument("--check", action="store_true", help="QA report from the existing db, no rebuild")
    args = ap.parse_args()
    if args.check:
        con = sqlite3.connect(f"file:{DEST.as_posix()}?mode=ro", uri=True)
        items = pd.read_sql_query("SELECT * FROM voice_items", con)
        con.close()
    else:
        print("Building voice_items ...")
        items = build()
        write(items)
        print(f"Wrote {len(items)} rows to {DEST}")
    qa(items)


if __name__ == "__main__":
    main()
