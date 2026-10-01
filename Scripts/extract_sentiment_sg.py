"""
extract_sentiment_sg.py

Sentiment/attribute extraction for SG MyACUVUE Lazada reviews + Kiasuparents
forum posts -- the two sources in sg_acuvue.db with real text but no
sentiment scoring yet (the social-listening DBs -- XHS/YouTube/Reddit/
Facebook/Instagram -- already carry LLM-scored sentiment from their own
scrapers).

Ported from Scripts/THscripts/extract_lazada_sentiment_th.py: same
structured-output idiom (OpenAI gpt-4o-mini + pydantic response_format),
same CostTracker, same pilot/full + --confirm spend gate, same
withheld-star-rating design (sentiment is coded from text alone, not the
rating, so it isn't circularly derived). Two differences from the TH
original:
  1. Attribute vocabulary is lens-specific, not skincare (see ATTRIBUTE_VOCAB).
  2. Results are written directly back onto the `reviews`/`forum_posts` rows
     in sg_acuvue.db via UPDATE, not to a side staging CSV -- these ARE the
     dashboard's core tables here, not a Silver-layer staging step. This also
     gives free resumability: the loader only selects rows where
     sentiment IS NULL, so a resumed run naturally skips whatever a prior
     run already wrote.

is_purchase_barrier_signal is intentionally NOT produced by this script --
that field exists on the YT/Reddit/FB/IG comment tables from those scrapers'
own logic, but isn't part of the pattern being ported here. Left as a
follow-up once the dashboard's actual barrier-detection logic is designed.

Usage:
  python extract_sentiment_sg.py                       # pilot: ~24-row sample, no DB writes
  python extract_sentiment_sg.py --mode full --confirm  # full batch, writes to sg_acuvue.db
"""
from __future__ import annotations

import argparse
import json
import os
import shutil
import sqlite3
import sys
import time
from datetime import datetime, date
from pathlib import Path
from typing import Optional

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
    load_dotenv()
except ImportError:
    def _load_env_manually(path=".env"):
        if not os.path.exists(path):
            return
        with open(path, "r", encoding="utf-8") as f:
            for line in f:
                line = line.strip()
                if not line or line.startswith("#") or "=" not in line:
                    continue
                key, _, value = line.partition("=")
                os.environ.setdefault(key.strip(), value.strip().strip('"').strip("'"))
    _load_env_manually()

REPO_ROOT = Path(__file__).resolve().parent.parent
SG_DB = REPO_ROOT / "Scripts" / "output" / "sg_acuvue.db"
BACKUP_DIR = REPO_ROOT / "Scripts" / "output" / "backups"

MODEL = "gpt-4o-mini"
PRICE_PER_1M_INPUT_TOKENS = 0.15
PRICE_PER_1M_OUTPUT_TOKENS = 0.60

BATCH_SIZE = 10
PILOT_SAMPLE_SIZE = 24  # ~half reviews, half forum posts

# Lens-specific vocabulary (mirrors the HK dashboard's existing negative-tail
# attribute categories) -- NOT the TH scripts' skincare vocabulary.
ATTRIBUTE_VOCAB = [
    "price", "comfort_dryness", "packaging", "shipping_fulfillment",
    "customer_service", "authenticity_counterfeit", "availability",
]

SENTIMENT_VALUES = {"positive", "negative", "neutral", "mixed"}


# ---------------------------------------------------------------------------
# Backup helper -- verbatim pattern from extract_lazada_sentiment_th.py
# ---------------------------------------------------------------------------
def backup_if_exists(path: Path, backup_dir: Path) -> None:
    if not path.exists():
        return
    backup_dir.mkdir(parents=True, exist_ok=True)
    stamp = datetime.now().strftime("%Y%m%d_%H%M%S")
    backup_path = backup_dir / f"{path.stem}_BACKUP_{stamp}{path.suffix}"
    shutil.copy2(path, backup_path)
    print(f"  [backup] {path.name} -> {backup_path}")


# ---------------------------------------------------------------------------
# Cost tracker -- same shape/rates as the TH scripts
# ---------------------------------------------------------------------------
class CostTracker:
    def __init__(self):
        self.prompt_tokens = 0
        self.completion_tokens = 0
        self.calls = 0

    def add(self, usage):
        if usage is None:
            return
        self.prompt_tokens += getattr(usage, "prompt_tokens", 0) or 0
        self.completion_tokens += getattr(usage, "completion_tokens", 0) or 0
        self.calls += 1

    def estimated_cost(self):
        return (
            self.prompt_tokens / 1_000_000 * PRICE_PER_1M_INPUT_TOKENS
            + self.completion_tokens / 1_000_000 * PRICE_PER_1M_OUTPUT_TOKENS
        )

    def summary(self):
        return (
            f"{self.calls} API calls, "
            f"{self.prompt_tokens:,} prompt tokens, "
            f"{self.completion_tokens:,} completion tokens, "
            f"~${self.estimated_cost():.4f} estimated (gpt-4o-mini rates, "
            f"verify against current OpenAI pricing)"
        )


# ---------------------------------------------------------------------------
# Structured output schema
# ---------------------------------------------------------------------------
class MentionExtraction(BaseModel):
    id: str
    sentiment: str  # validated against SENTIMENT_VALUES post-hoc
    attribute_tags: list[str]
    attribute_notes: Optional[str] = None
    confidence: float


class MentionBatchResponse(BaseModel):
    results: list[MentionExtraction]


SYSTEM_PROMPT = f"""You are a market-research analyst coding consumer text about contact
lenses and lens-care products (Acuvue, Alcon, Bausch & Lomb, CooperVision, Olens and
related solution/eye-drop brands) in Singapore. Text comes from two sources: Lazada
product reviews, and Kiasuparents forum posts/threads.

The BRAND for each item below is already known (given as `brand` in each item) -- do
NOT question or re-identify the brand, just read the text as feedback/discussion about
that already-identified brand. Focus only on the four signals below.

1. sentiment: one of "positive", "negative", "neutral", "mixed" -- the writer's overall
   sentiment, based on the TEXT ITSELF. A star rating (if one exists) is deliberately NOT
   given to you here -- some reviews carry a high star rating but lukewarm or mixed text
   (or vice versa); code strictly what the text says, don't guess a rating.

2. attribute_tags: zero or more of this controlled vocabulary ONLY:
   {", ".join(ATTRIBUTE_VOCAB)}
   -- whichever attributes the text actually comments on.

3. attribute_notes: optional short free-text note for anything notable the vocabulary
   above doesn't capture. Leave null (JSON null, not the text "null") if nothing notable
   falls outside the vocabulary.

4. confidence: 0.0-1.0, your confidence that the text contains enough real signal to
   support the sentiment/attribute read above. Many Lazada reviews are extremely short
   ("ok", "5 stars", "fast delivery") with almost no product commentary -- score those
   low rather than forcing a confident read from thin text.

Return one result per input id, matched exactly.
"""


def build_user_prompt(batch: list[tuple]) -> str:
    items = [{"id": mention_id, "brand": brand, "text": text} for mention_id, brand, text in batch]
    return json.dumps({"mentions": items}, ensure_ascii=False)


def extract_batch(client: OpenAI, batch: list[tuple], cost_tracker: CostTracker) -> dict:
    """batch: list of (mention_id, brand, text) tuples. Returns {mention_id: MentionExtraction}."""
    response = client.beta.chat.completions.parse(
        model=MODEL,
        messages=[
            {"role": "system", "content": SYSTEM_PROMPT},
            {"role": "user", "content": build_user_prompt(batch)},
        ],
        response_format=MentionBatchResponse,
    )
    cost_tracker.add(response.usage)

    parsed = response.choices[0].message.parsed
    if parsed is None:
        raise RuntimeError("Model did not return parseable structured output for this batch.")

    return {item.id: item for item in parsed.results}


def validate_and_clean(extraction: MentionExtraction) -> dict:
    sentiment = extraction.sentiment if extraction.sentiment in SENTIMENT_VALUES else "neutral"
    if extraction.sentiment not in SENTIMENT_VALUES:
        print(f"  [warn] non-canonical sentiment '{extraction.sentiment}' -> defaulted to "
              f"'neutral' (id={extraction.id})")

    clean_tags = [t for t in extraction.attribute_tags if t in ATTRIBUTE_VOCAB]
    dropped_tags = set(extraction.attribute_tags) - set(clean_tags)
    if dropped_tags:
        print(f"  [warn] dropping non-canonical attribute tag(s) {dropped_tags} (id={extraction.id})")

    attribute_notes = extraction.attribute_notes
    if isinstance(attribute_notes, str) and attribute_notes.strip().lower() == "null":
        attribute_notes = None

    confidence = max(0.0, min(1.0, extraction.confidence))

    return {
        "sentiment": sentiment,
        "attribute_tags": json.dumps(clean_tags, ensure_ascii=False),
        "attribute_notes": attribute_notes,
        "confidence": confidence,
    }


# ---------------------------------------------------------------------------
# Loaders -- mention_id is "review:<id>" or "forum:<id>" so a single batching/
# extraction loop can process both tables uniformly.
# ---------------------------------------------------------------------------
def load_pending_mentions(conn: sqlite3.Connection) -> pd.DataFrame:
    reviews = pd.read_sql_query(
        "SELECT id, brand, review_text AS text FROM reviews "
        "WHERE sentiment IS NULL AND review_text IS NOT NULL AND TRIM(review_text) != ''",
        conn,
    )
    reviews["mention_id"] = "review:" + reviews["id"].astype(str)
    reviews["source_table"] = "reviews"

    forum = pd.read_sql_query(
        "SELECT id, brand, content_summary AS text FROM forum_posts "
        "WHERE sentiment IS NULL AND content_summary IS NOT NULL AND TRIM(content_summary) != ''",
        conn,
    )
    forum["mention_id"] = "forum:" + forum["id"].astype(str)
    forum["source_table"] = "forum_posts"

    return pd.concat(
        [reviews[["mention_id", "source_table", "id", "brand", "text"]],
         forum[["mention_id", "source_table", "id", "brand", "text"]]],
        ignore_index=True,
    )


def ensure_sentiment_columns(conn: sqlite3.Connection) -> None:
    """forum_posts wasn't created with sentiment columns (it predates this
    script); reviews already has them from build_sg_products_reviews.py.
    Safe to rerun -- skips any column that already exists."""
    cur = conn.cursor()
    cur.execute("PRAGMA table_info(forum_posts)")
    existing = {row[1] for row in cur.fetchall()}
    for col in ("sentiment", "attribute_tags", "attribute_notes", "confidence"):
        if col not in existing:
            coltype = "REAL" if col == "confidence" else "TEXT"
            cur.execute(f"ALTER TABLE forum_posts ADD COLUMN {col} {coltype}")
    conn.commit()


def _checkpoint_path() -> Path:
    return BACKUP_DIR / "extract_sentiment_sg_results_checkpoint.json"


def _write_checkpoint(all_results: dict) -> None:
    """Safety-net file, written to local disk state independent of the live
    sg_acuvue.db -- so a DB-write failure (see run_extraction's docstring)
    never loses already-paid-for LLM extraction results. Overwritten after
    every batch."""
    BACKUP_DIR.mkdir(parents=True, exist_ok=True)
    with open(_checkpoint_path(), "w", encoding="utf-8") as f:
        json.dump(all_results, f, ensure_ascii=False)


def bulk_write_to_db(mentions_df: pd.DataFrame, all_results: dict) -> None:
    """Writes every result in ONE short-lived connection/transaction rather
    than trickling commits across the many-second, many-API-call extraction
    loop. A first attempt at this (many small conn.commit() calls held open
    for the ~20s duration of the full run) silently failed to persist on
    this Google-Drive-synced file -- no exception was raised, but a fresh
    connection afterward showed every row still NULL. Minimizing how long
    the connection stays open, and doing the write as a single transaction,
    avoids whatever sync/locking interaction caused that."""
    conn = sqlite3.connect(SG_DB)
    try:
        for mention_id, cleaned in all_results.items():
            match = mentions_df[mentions_df["mention_id"] == mention_id].iloc[0]
            conn.execute(
                f"UPDATE {match['source_table']} SET sentiment = ?, attribute_tags = ?, "
                f"attribute_notes = ?, confidence = ? WHERE id = ?",
                (cleaned["sentiment"], cleaned["attribute_tags"], cleaned["attribute_notes"],
                 cleaned["confidence"], int(match["id"])),
            )
        conn.commit()
    finally:
        conn.close()


def verify_db_write(all_results: dict) -> int:
    """Reopens a brand-new connection (not the one used to write) and counts
    how many of the just-written mention_ids actually show a non-NULL
    sentiment now. Returns the count so the caller can compare against
    len(all_results) and fail loudly rather than trusting the write silently."""
    conn = sqlite3.connect(SG_DB)
    try:
        review_ids = [int(mid.split(":", 1)[1]) for mid in all_results if mid.startswith("review:")]
        forum_ids = [int(mid.split(":", 1)[1]) for mid in all_results if mid.startswith("forum:")]
        n = 0
        if review_ids:
            q = f"SELECT COUNT(*) FROM reviews WHERE sentiment IS NOT NULL AND id IN ({','.join('?' * len(review_ids))})"
            n += conn.execute(q, review_ids).fetchone()[0]
        if forum_ids:
            q = f"SELECT COUNT(*) FROM forum_posts WHERE sentiment IS NOT NULL AND id IN ({','.join('?' * len(forum_ids))})"
            n += conn.execute(q, forum_ids).fetchone()[0]
        return n
    finally:
        conn.close()


def run_extraction(client: OpenAI, mentions_df: pd.DataFrame, cost_tracker: CostTracker) -> dict:
    """Runs extraction over all rows in mentions_df, accumulating results in
    memory (and checkpointing to a local JSON safety-net file after every
    batch). Does NOT touch sg_acuvue.db -- callers write results to the DB
    themselves via bulk_write_to_db(), in one shot, after this returns."""
    rows = list(zip(mentions_df["mention_id"], mentions_df["brand"], mentions_df["text"]))
    all_results: dict[str, dict] = {}

    for i in range(0, len(rows), BATCH_SIZE):
        batch = rows[i:i + BATCH_SIZE]
        batch_num = i // BATCH_SIZE + 1
        print(f"  extracting batch {batch_num} ({i + 1}-{min(i + BATCH_SIZE, len(rows))} of {len(rows)}) ...")
        try:
            batch_results = extract_batch(client, batch, cost_tracker)
        except Exception as e:
            print(f"  [error] batch failed: {e}")
            continue

        for mention_id, extraction in batch_results.items():
            all_results[mention_id] = validate_and_clean(extraction)

        _write_checkpoint(all_results)
        print(f"  -> {len(all_results)} of {len(rows)} extracted so far. {cost_tracker.summary()}")
        time.sleep(0.5)

    return all_results


def main():
    parser = argparse.ArgumentParser(description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter)
    parser.add_argument("--mode", choices=["pilot", "full"], default="pilot",
                         help=f"pilot (default): {PILOT_SAMPLE_SIZE}-row sample, print results, no DB writes. "
                              "full: process all rows with sentiment IS NULL, writes to sg_acuvue.db.")
    parser.add_argument("--confirm", action="store_true",
                         help="Required alongside --mode full to actually spend API budget and write to the DB.")
    parser.add_argument("--checkpoint-every", type=int, default=20)
    args = parser.parse_args()

    api_key = os.environ.get("OPENAI_API_KEY")
    if not api_key:
        print("ERROR: OPENAI_API_KEY not set in environment. Refusing to run -- "
              "set it in .env or the environment and re-run.")
        sys.exit(1)

    if args.mode == "full" and not args.confirm:
        print("ERROR: --mode full requires --confirm as an explicit spend gate. "
              "Re-run as: python extract_sentiment_sg.py --mode full --confirm")
        sys.exit(1)

    if not SG_DB.exists():
        print(f"ERROR: {SG_DB} not found. Run build_sg_products_reviews.py first.")
        sys.exit(1)

    client = OpenAI(api_key=api_key)
    cost_tracker = CostTracker()

    conn = sqlite3.connect(SG_DB)
    ensure_sentiment_columns(conn)
    mentions_df = load_pending_mentions(conn)
    print(f"Loaded {len(mentions_df)} pending mentions (sentiment IS NULL): "
          f"{mentions_df['source_table'].value_counts().to_dict()}")

    if mentions_df.empty:
        print("Nothing to extract -- every review/forum_post already has a sentiment value.")
        conn.close()
        return

    conn.close()  # only needed load_pending_mentions()/ensure_sentiment_columns() above; extraction itself doesn't touch the DB

    if args.mode == "pilot":
        print(f"\n=== PILOT MODE: up to {PILOT_SAMPLE_SIZE}-row sample, no DB writes ===")
        n = min(PILOT_SAMPLE_SIZE, len(mentions_df))
        sample = mentions_df.sample(n=n, random_state=42).reset_index(drop=True)
        print(f"Sample by source: {sample['source_table'].value_counts().to_dict()}")

        all_results = run_extraction(client, sample, cost_tracker)

        pd.set_option("display.max_colwidth", 120)
        print("\n=== PILOT RESULTS (review before running --mode full) ===")
        for _, row in sample.iterrows():
            cleaned = all_results.get(row["mention_id"], {})
            print(f"\n[{row['mention_id']}] brand={row['brand']}")
            print(f"  text: {str(row['text'])[:200]}")
            print(f"  sentiment:       {cleaned.get('sentiment')}")
            print(f"  attribute_tags:  {cleaned.get('attribute_tags')}")
            print(f"  attribute_notes: {cleaned.get('attribute_notes')}")
            print(f"  confidence:      {cleaned.get('confidence')}")

        print(f"\nPilot cost: {cost_tracker.summary()}")
        print(f"Full remaining corpus size: {len(mentions_df)} rows")
        print("\nReview the printed rows above. If quality looks right, run:\n"
              "  python extract_sentiment_sg.py --mode full --confirm")

    else:
        print("\n=== FULL BATCH MODE ===")
        backup_if_exists(SG_DB, BACKUP_DIR)

        all_results = run_extraction(client, mentions_df, cost_tracker)
        print(f"\nTotal cost this run: {cost_tracker.summary()}")
        print(f"{len(all_results)} of {len(mentions_df)} mentions extracted (checkpoint: {_checkpoint_path()})")

        print("Writing all results to sg_acuvue.db in a single transaction...")
        bulk_write_to_db(mentions_df, all_results)

        written = verify_db_write(all_results)
        if written == len(all_results):
            print(f"VERIFIED: {written} of {len(all_results)} rows confirmed persisted "
                  f"(re-read with a fresh connection).")
        else:
            print(f"WARNING: only {written} of {len(all_results)} rows verified persisted after the write. "
                  f"Extracted results are safe in {_checkpoint_path()} -- do not re-run extraction, "
                  f"investigate the DB write instead.")


if __name__ == "__main__":
    main()
