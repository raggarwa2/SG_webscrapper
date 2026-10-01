"""MyACUVUE app data: reviews (tagged by store) + store metadata for Apple App Store and Google Play.

Writes to Scripts/output/app_data_sg.db (same DB as play_store_scraper.py):
  app_reviews          store/platform/source tag, reviewer_name, app_version, thumbs_up, developer_reply
  app_metadata_apple   Apple lookup API: rating, version, release notes, size, min iOS, screenshots, ...
  app_metadata         Google Play (existing table, refreshed)
  app_version_history  Apple most-recent-version snapshot (page only exposes the latest; grows per run)
  app_privacy          Apple privacy labels + Google Play data-safety, one row per data type
  app_rating_histogram Star histogram for both stores
Run: python Scripts/app_reviews_extras.py
"""
import json
import re
import sqlite3
import time
from pathlib import Path

import requests
from app_store_web_scraper import AppStoreEntry
from google_play_scraper import Sort, app as play_app, reviews as play_reviews

DB_PATH = Path(__file__).resolve().parent / "output" / "app_data_sg.db"
APPLE_ID = 1179732283
PLAY_PACKAGE = "com.jnj.myacuvue.consumer"
COUNTRY = "sg"
HEADERS = {
    "User-Agent": "Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 Chrome/124 Safari/537.36",
    "Accept-Language": "en-SG,en;q=0.9",
}
# store -> (platform, human-readable source tag)
TAGS = {"app_store": ("iOS", "Apple App Store"), "play_store": ("Android", "Google Play")}


def init_db():
    DB_PATH.parent.mkdir(parents=True, exist_ok=True)
    conn = sqlite3.connect(DB_PATH)
    conn.execute('''
        CREATE TABLE IF NOT EXISTS app_reviews (
            store TEXT, country TEXT, review_id TEXT, rating INTEGER, title TEXT, text TEXT,
            date TEXT, app_version TEXT, developer_reply TEXT,
            PRIMARY KEY (store, country, review_id)
        )''')
    existing = {r[1] for r in conn.execute("PRAGMA table_info(app_reviews)")}
    for col, typ in [("thumbs_up", "INTEGER"), ("platform", "TEXT"), ("source", "TEXT"),
                     ("reviewer_name", "TEXT"), ("developer_reply_date", "TEXT")]:
        if col not in existing:
            conn.execute(f"ALTER TABLE app_reviews ADD COLUMN {col} {typ}")
    conn.executescript('''
        CREATE TABLE IF NOT EXISTS app_metadata_apple (
            store TEXT, country TEXT, app_id INTEGER, fetched_at TEXT,
            title TEXT, developer TEXT, seller TEXT, bundle_id TEXT, avg_rating REAL, rating_count INTEGER,
            avg_rating_current_version REAL, rating_count_current_version INTEGER,
            version TEXT, current_version_released TEXT, first_released TEXT, release_notes TEXT,
            description TEXT, category TEXT, genres TEXT, content_rating TEXT, price REAL,
            file_size_bytes INTEGER, min_ios_version TEXT, languages TEXT, supported_devices TEXT,
            screenshots_iphone TEXT, screenshots_ipad TEXT, icon_url TEXT, store_url TEXT, raw_json TEXT,
            PRIMARY KEY (store, country, app_id, fetched_at)
        );
        CREATE TABLE IF NOT EXISTS app_version_history (
            store TEXT, country TEXT, version TEXT, released TEXT, release_notes TEXT,
            PRIMARY KEY (store, country, version)
        );
        CREATE TABLE IF NOT EXISTS app_privacy (
            store TEXT, country TEXT, section TEXT, category TEXT, data_type TEXT, purposes TEXT, fetched_at TEXT
        );
        CREATE TABLE IF NOT EXISTS app_rating_histogram (
            store TEXT, country TEXT, fetched_at TEXT, stars INTEGER, count INTEGER
        );
    ''')
    conn.commit()
    return conn


def upsert_review(conn, store, country, review_id, rating, title, text, date, version, reply,
                  reply_date, thumbs, reviewer):
    platform, source = TAGS[store]
    conn.execute('''
        INSERT INTO app_reviews (store, country, review_id, rating, title, text, date, app_version,
                                 developer_reply, developer_reply_date, thumbs_up, platform, source, reviewer_name)
        VALUES (?,?,?,?,?,?,?,?,?,?,?,?,?,?)
        ON CONFLICT(store, country, review_id) DO UPDATE SET
            rating=excluded.rating, title=excluded.title, text=excluded.text, date=excluded.date,
            app_version=COALESCE(excluded.app_version, app_reviews.app_version),
            developer_reply=excluded.developer_reply, developer_reply_date=excluded.developer_reply_date,
            thumbs_up=COALESCE(excluded.thumbs_up, app_reviews.thumbs_up),
            platform=excluded.platform, source=excluded.source,
            reviewer_name=COALESCE(excluded.reviewer_name, app_reviews.reviewer_name)
    ''', (store, country, review_id, rating, title, text, date, version, reply, reply_date, thumbs,
          platform, source, reviewer))


# ---------- reviews ----------
def scrape_apple_reviews(conn):
    n = 0
    for r in AppStoreEntry(app_id=APPLE_ID, country=COUNTRY).reviews():
        upsert_review(conn, "app_store", COUNTRY, str(r.id), r.rating, r.title, r.content,
                      str(r.date), r.app_version, None, None, None, r.user_name)
        n += 1
    conn.commit()
    print(f"[apple] reviews upserted: {n}")


def scrape_play_reviews(conn):
    token, n = None, 0
    while True:
        result, token = play_reviews(PLAY_PACKAGE, lang="en", country=COUNTRY, sort=Sort.NEWEST,
                                     count=100, continuation_token=token)
        if not result:
            break
        for r in result:
            upsert_review(conn, "play_store", COUNTRY, r["reviewId"], r["score"], None, r["content"],
                          str(r["at"]), r["reviewCreatedVersion"], r.get("replyContent"),
                          str(r["repliedAt"]) if r.get("repliedAt") else None, r["thumbsUpCount"],
                          r["userName"])
        n += len(result)
        conn.commit()
        if not token:
            break
        time.sleep(1.5)
    print(f"[play]  reviews upserted: {n}")


# ---------- Apple metadata ----------
def apple_page_shelves():
    html = requests.get(f"https://apps.apple.com/{COUNTRY}/app/id{APPLE_ID}", headers=HEADERS, timeout=30).text
    blob = re.search(r'<script[^>]*id="serialized-server-data"[^>]*>(.*?)</script>', html, re.S)
    return json.loads(blob.group(1))["data"][0]["data"]["shelfMapping"] if blob else {}


def scrape_apple_metadata(conn):
    res = requests.get("https://itunes.apple.com/lookup", params={"id": APPLE_ID, "country": COUNTRY},
                       timeout=30).json()["results"][0]
    now = time.strftime("%Y-%m-%d %H:%M:%S", time.gmtime())
    conn.execute('INSERT OR REPLACE INTO app_metadata_apple VALUES (?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?)', (
        "app_store", COUNTRY, APPLE_ID, now, res.get("trackName"), res.get("artistName"), res.get("sellerName"),
        res.get("bundleId"), res.get("averageUserRating"), res.get("userRatingCount"),
        res.get("averageUserRatingForCurrentVersion"), res.get("userRatingCountForCurrentVersion"),
        res.get("version"), res.get("currentVersionReleaseDate"), res.get("releaseDate"), res.get("releaseNotes"),
        res.get("description"), res.get("primaryGenreName"), json.dumps(res.get("genres")),
        res.get("contentAdvisoryRating"), res.get("price"), int(res["fileSizeBytes"]) if res.get("fileSizeBytes") else None,
        res.get("minimumOsVersion"), json.dumps(res.get("languageCodesISO2A")), json.dumps(res.get("supportedDevices")),
        json.dumps(res.get("screenshotUrls")), json.dumps(res.get("ipadScreenshotUrls")),
        res.get("artworkUrl512"), res.get("trackViewUrl"), json.dumps(res),
    ))
    conn.execute('INSERT OR REPLACE INTO app_version_history VALUES (?,?,?,?,?)',
                 ("app_store", COUNTRY, res.get("version"), res.get("currentVersionReleaseDate"), res.get("releaseNotes")))
    conn.commit()
    print(f"[apple] metadata: v{res.get('version')} rating {res.get('averageUserRating'):.2f} "
          f"({res.get('userRatingCount')} ratings), {int(res['fileSizeBytes']) / 1e6:.0f} MB, iOS {res.get('minimumOsVersion')}+")
    return now


def scrape_apple_page_extras(conn, now):
    shelves = apple_page_shelves()
    # most recent version (page shows the latest entry; history accumulates across runs)
    for it in shelves.get("mostRecentVersion", {}).get("items", []):
        m = re.match(r"Version (.+)", it.get("primarySubtitle", ""))
        if m:
            conn.execute('INSERT OR REPLACE INTO app_version_history VALUES (?,?,?,?,?)',
                         ("app_store", COUNTRY, m.group(1), it.get("secondarySubtitle"), it.get("text")))
    # star histogram
    ratings = shelves.get("productRatings", {}).get("items", [])
    if ratings and ratings[0].get("ratingCounts"):
        counts = ratings[0]["ratingCounts"]  # ordered 5 -> 1
        conn.execute("DELETE FROM app_rating_histogram WHERE store='app_store' AND country=?", (COUNTRY,))
        for stars, c in zip(range(5, 0, -1), counts):
            conn.execute("INSERT INTO app_rating_histogram VALUES (?,?,?,?,?)", ("app_store", COUNTRY, now, stars, c))
        print(f"[apple] histogram (5->1 stars): {counts}")
    # privacy labels
    conn.execute("DELETE FROM app_privacy WHERE store='app_store' AND country=?", (COUNTRY,))
    rows = 0
    for it in shelves.get("privacyTypes", {}).get("items", []):
        section = it.get("title")
        purposes = "; ".join(p.get("title", "") for p in it.get("purposes", []))
        for cat in it.get("categories", []):
            types = cat.get("dataTypes") or [None]
            for dt in types:
                conn.execute("INSERT INTO app_privacy VALUES (?,?,?,?,?,?,?)",
                             ("app_store", COUNTRY, section, cat.get("title"),
                              dt.get("title") if isinstance(dt, dict) else dt, purposes, now))
                rows += 1
    conn.commit()
    print(f"[apple] privacy label rows: {rows}")


# ---------- Google Play metadata ----------
def scrape_play_metadata(conn):
    info = play_app(PLAY_PACKAGE, lang="en", country=COUNTRY)
    conn.execute('''
        CREATE TABLE IF NOT EXISTS app_metadata (
            store TEXT, country TEXT, package TEXT, fetched_at TEXT,
            title TEXT, developer TEXT, score REAL, ratings INTEGER, reviews INTEGER,
            histogram TEXT, installs TEXT, real_installs INTEGER, version TEXT,
            updated TEXT, released TEXT, recent_changes TEXT, description TEXT,
            genre TEXT, content_rating TEXT, price REAL, contains_ads INTEGER,
            in_app_purchases INTEGER, android_version TEXT, privacy_policy TEXT,
            raw_json TEXT, PRIMARY KEY (store, country, package, fetched_at))''')
    now = time.strftime("%Y-%m-%d %H:%M:%S", time.gmtime())
    conn.execute('INSERT OR REPLACE INTO app_metadata VALUES (?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?)', (
        "play_store", COUNTRY, PLAY_PACKAGE, now, info.get("title"), info.get("developer"), info.get("score"),
        info.get("ratings"), info.get("reviews"), json.dumps(info.get("histogram")), info.get("installs"),
        info.get("realInstalls"), info.get("version"), str(info.get("updated")), info.get("released"),
        info.get("recentChanges"), info.get("description"), info.get("genre"), info.get("contentRating"),
        info.get("price"), int(bool(info.get("containsAds"))), int(bool(info.get("offersIAP"))),
        info.get("androidVersionText"), info.get("privacyPolicy"), json.dumps(info, default=str)))
    conn.execute("DELETE FROM app_rating_histogram WHERE store='play_store' AND country=?", (COUNTRY,))
    for stars, c in zip(range(1, 6), info.get("histogram") or []):
        conn.execute("INSERT INTO app_rating_histogram VALUES (?,?,?,?,?)", ("play_store", COUNTRY, now, stars, c))
    conn.commit()
    print(f"[play]  metadata: v{info.get('version')} score {info.get('score'):.2f} ({info.get('ratings')} ratings), "
          f"installs {info.get('installs')} (real {info.get('realInstalls')}), histogram(1->5) {info.get('histogram')}")
    return now


def _walk(o):
    yield o
    if isinstance(o, list):
        for x in o:
            yield from _walk(x)
    elif isinstance(o, dict):
        for x in o.values():
            yield from _walk(x)


def scrape_play_data_safety(conn, now):
    html = requests.get("https://play.google.com/store/apps/datasafety",
                        params={"id": PLAY_PACKAGE, "hl": "en", "gl": COUNTRY.upper()},
                        headers=HEADERS, timeout=30).text
    conn.execute("DELETE FROM app_privacy WHERE store='play_store' AND country=?", (COUNTRY,))
    rows = 0
    for m in re.finditer(r"AF_initDataCallback\(\{key: 'ds:\d+'.*?data:(.*?), sideChannel", html, re.S):
        try:
            data = json.loads(m.group(1))
        except ValueError:
            continue
        if "Data collected" not in m.group(1) and "No data shared" not in m.group(1):
            continue
        for node in _walk(data):
            if not isinstance(node, list):
                continue
            # headline flags, e.g. "No data shared with third parties"
            if len(node) > 1 and isinstance(node[1], str) and node[1].startswith(("No data shared", "Data shared", "No data collected")):
                conn.execute("INSERT INTO app_privacy VALUES (?,?,?,?,?,?,?)",
                             ("play_store", COUNTRY, "Data sharing", None, node[1], None, now)); rows += 1
            # data category: [icon, "Personal info", [None, "Name, Email..."], None, None, None?, [[type, 0, purposes], ...]]
            if (len(node) >= 5 and isinstance(node[0], list) and isinstance(node[4], list) and node[4]
                    and all(isinstance(x, list) and len(x) == 3 and isinstance(x[0], str) for x in node[4])):
                category = node[0][1] if len(node[0]) > 1 and isinstance(node[0][1], str) else None
                if category:
                    for dtype, _, purposes in node[4]:
                        conn.execute("INSERT INTO app_privacy VALUES (?,?,?,?,?,?,?)",
                                     ("play_store", COUNTRY, "Data collected", category, dtype, purposes, now)); rows += 1
            # security practices
            if len(node) == 3 and isinstance(node[1], str) and node[1].startswith(("Data", "You can request")) \
                    and ("encrypt" in node[1] or "delete" in node[1]):
                conn.execute("INSERT INTO app_privacy VALUES (?,?,?,?,?,?,?)",
                             ("play_store", COUNTRY, "Security practices", None, node[1], None, now)); rows += 1
        break
    conn.commit()
    print(f"[play]  data-safety rows: {rows}")


if __name__ == "__main__":
    conn = init_db()
    scrape_apple_reviews(conn)
    scrape_play_reviews(conn)
    apple_now = scrape_apple_metadata(conn)
    scrape_apple_page_extras(conn, apple_now)
    play_now = scrape_play_metadata(conn)
    scrape_play_data_safety(conn, play_now)
    conn.close()
