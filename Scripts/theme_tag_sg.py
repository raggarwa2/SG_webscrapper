"""
theme_tag_sg.py

Tags every item in the Brand Health pool with 1 or 2 themes from one fixed list, so brands can be compared on the same
themes across Xiaohongshu, Lazada, KiasuParents, Reddit, YouTube, Instagram and Facebook (only four of those sources
carry a theme field of their own, and each uses a different vocabulary).

Input : Scripts/output/theme_tag_queue.csv, written by the dashboard (Dashboard/theme_tags.py) with the pooled items
        that have no tag yet (columns brand, source, text, key). Open the dashboard's Brand Health tab once to refresh it.
Output: Scripts/output/theme_tags_sg.db, table theme_tags(key, brand, source, themes JSON, model, tagged_at).
        Resumable: the queue only holds items without a tag.

Same idiom as extract_sentiment_sg.py (OpenAI gpt-4o-mini, structured output, pilot / --confirm spend gate). Sentiment
is not produced here: it is already on each item. Praise versus complaint comes from that sentiment.

Usage:
  python theme_tag_sg.py                        # pilot: 24 items, prints the tags, writes nothing
  python theme_tag_sg.py --mode full --confirm  # tags the whole queue and writes theme_tags_sg.db
"""
from __future__ import annotations

import argparse
import json
import os
import sqlite3
import sys
import time
from datetime import datetime
from pathlib import Path

try:
    from openai import OpenAI
except ImportError:
    print("Missing dependency. Run: pip install openai")
    sys.exit(1)
try:
    from pydantic import BaseModel
except ImportError:
    print("Missing dependency. Run: pip install pydantic")
    sys.exit(1)

import pandas as pd

try:
    from dotenv import load_dotenv
    load_dotenv(Path(__file__).resolve().parent.parent / ".env")
except ImportError:
    pass

OUT = Path(__file__).resolve().parent / "output"
QUEUE = OUT / "theme_tag_queue.csv"
TAG_DB = OUT / "theme_tags_sg.db"
MODEL = "gpt-4o-mini"
BATCH = 20
MAX_CHARS = 600
# gpt-4o-mini list price per 1M tokens (input, output); used only for the spend estimate
PRICE_IN, PRICE_OUT = 0.15, 0.60

# the theme list lives in the dashboard module so the page and the tagger cannot drift apart


def _themes() -> dict:
    """THEMES from Dashboard/theme_tags.py without importing streamlit: read the dict literal."""
    import ast
    src = (Path(__file__).resolve().parent.parent / "Dashboard" / "theme_tags.py").read_text(encoding="utf-8")
    for node in ast.parse(src).body:
        if isinstance(node, ast.Assign) and getattr(node.targets[0], "id", "") == "THEMES":
            return ast.literal_eval(node.value)
    raise SystemExit("THEMES not found in Dashboard/theme_tags.py")


THEMES = _themes()
THEME_NAMES = list(THEMES)


class ItemTags(BaseModel):
    id: int
    themes: list[str]          # 0 to 2 names from the theme list; empty = off-topic or no theme


class BatchTags(BaseModel):
    items: list[ItemTags]


SYSTEM = (
    "You tag consumer comments and reviews about contact lenses in Singapore with themes. For each numbered item return 0 to 2 "
    "themes, the ones the item is actually about, most important first. Use only these names, spelled exactly:\n"
    + "\n".join(f"- {k}: {v}" for k, v in THEMES.items())
    + "\nReturn an empty list when the item has no clear theme (greeting, joke, off-topic, only a tag or emoji). "
    "Tag what is discussed, whether praised or criticised; do not judge sentiment. Return every id you were given."
)


def tag_batch(client: OpenAI, rows: list[dict]) -> tuple[dict, int, int]:
    user = "\n".join(f"{i}. [{r['brand']}] {str(r['text'])[:MAX_CHARS]!r}" for i, r in enumerate(rows))
    resp = client.beta.chat.completions.parse(
        model=MODEL, temperature=0,
        messages=[{"role": "system", "content": SYSTEM}, {"role": "user", "content": user}],
        response_format=BatchTags,
    )
    parsed = resp.choices[0].message.parsed
    out = {}
    for it in parsed.items:
        if 0 <= it.id < len(rows):
            out[it.id] = [t for t in it.themes if t in THEMES][:2]
    return out, resp.usage.prompt_tokens, resp.usage.completion_tokens


def main() -> None:
    ap = argparse.ArgumentParser()
    ap.add_argument("--mode", choices=["pilot", "full"], default="pilot")
    ap.add_argument("--confirm", action="store_true", help="required with --mode full to spend API budget and write the DB")
    args = ap.parse_args()

    if not QUEUE.exists():
        sys.exit(f"No queue at {QUEUE}. Open the dashboard's Brand Health tab once to write it.")
    q = pd.read_csv(QUEUE, encoding="utf-8").dropna(subset=["text"])
    if TAG_DB.exists():
        con = sqlite3.connect(TAG_DB)
        done = {r[0] for r in con.execute("SELECT key FROM theme_tags")} if con.execute(
            "SELECT name FROM sqlite_master WHERE name='theme_tags'").fetchone() else set()
        con.close()
        q = q[~q["key"].isin(done)]
    if args.mode == "pilot":
        q = q.sample(min(24, len(q)), random_state=1)
    n = len(q)
    chars = int(q["text"].astype(str).str.slice(0, MAX_CHARS).str.len().sum())
    est_in = chars / 3.5 + n * 12 + (n / BATCH + 1) * 450
    est_cost = est_in / 1e6 * PRICE_IN + n * 14 / 1e6 * PRICE_OUT
    print(f"{n} items to tag in {-(-n // BATCH)} calls, about ${est_cost:.2f} on {MODEL}.")
    if args.mode == "full" and not args.confirm:
        sys.exit("Refusing to spend: add --confirm.")
    key_ = os.environ.get("OPENAI_API_KEY")
    if not key_:
        sys.exit("OPENAI_API_KEY not set (.env at the project root).")
    client = OpenAI(api_key=key_)

    rows = q.to_dict("records")
    results, t_in, t_out = [], 0, 0
    for s in range(0, len(rows), BATCH):
        chunk = rows[s:s + BATCH]
        for attempt in range(3):
            try:
                tags, a, b = tag_batch(client, chunk)
                break
            except Exception as e:  # noqa: BLE001 - retry on any API/parse error
                print(f"  batch {s // BATCH}: {type(e).__name__}: {e}")
                time.sleep(2 * (attempt + 1))
        else:
            continue
        t_in += a; t_out += b
        for i, r in enumerate(chunk):
            if i in tags:
                results.append({**r, "themes": tags[i]})
        print(f"  {min(s + BATCH, n)}/{n}")
    cost = t_in / 1e6 * PRICE_IN + t_out / 1e6 * PRICE_OUT
    print(f"tagged {len(results)} of {n}; {t_in:,} in / {t_out:,} out tokens, about ${cost:.3f}.")

    if args.mode == "pilot":
        for r in results[:24]:
            print(f"- [{r['brand']}] {str(r['text'])[:110]!r} -> {r['themes']}")
        print("Pilot only: nothing written.")
        return
    con = sqlite3.connect(TAG_DB)
    con.execute("CREATE TABLE IF NOT EXISTS theme_tags (key TEXT PRIMARY KEY, brand TEXT, source TEXT, themes TEXT, model TEXT, tagged_at TEXT)")
    now = datetime.now().isoformat(timespec="seconds")
    con.executemany("INSERT OR REPLACE INTO theme_tags VALUES (?,?,?,?,?,?)",
                    [(r["key"], r["brand"], r["source"], json.dumps(r["themes"]), MODEL, now) for r in results])
    con.commit()
    con.close()
    print(f"wrote {len(results)} rows to {TAG_DB}")


if __name__ == "__main__":
    main()
