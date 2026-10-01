"""
extract_shopee_sentiment.py

Sentiment/attribute extraction for Shopee TH per-review data (Acne-Aid
only, "Anand" pull, 430 reviews) -- the Shopee analog of
extract_lazada_sentiment.py. Same rationale: brand is already known (every
row is Acne-Aid by construction, per shopee_mentions.py) so no re-grounding
is needed; only sentiment/attribute_tags/attribute_notes/confidence are
extracted.

Design patterns reused verbatim from extract_lazada_sentiment.py (same
repo, same task family): backup_if_exists(), CostTracker, structured-output
idiom, OPENAI_API_KEY hard-fail, pilot/full mode + --confirm spend gate,
checkpointed resume every N batches. Deliberately categorical-only (no
fabricated numeric sentiment_score) -- see acneaid_medallion/gold/
QC_SENTIMENT_SCORE_BUG_AUDIT.md for why: fact_mention.csv's lazada_review
and tiktok_content passes both hardcode sentiment_score=0.0 rather than
emit a real numeric score, and every gold-layer consumer already reads the
categorical `sentiment` field instead. This script follows that same
(already-correct) pattern from the start rather than adding a new 0.0
placeholder column.

DOES NOT WRITE TO fact_mention.csv. Output is a standalone staging CSV
(output/acneaid_th_shopee_sentiment.csv) -- merging into fact_mention.csv
happens via build_facts.py's build_fact_mention_shopee(), a separate,
later step (run acneaid_medallion/silver/build_facts.py after this).

Usage:
  python extract_shopee_sentiment.py                       # pilot: 20-row sample
  python extract_shopee_sentiment.py --mode full --confirm # full batch (~430 rows)
"""
from __future__ import annotations

import argparse
import json
import os
import shutil
import sys
import time
from datetime import datetime, date
from pathlib import Path
from typing import Optional

try:
    from openai import OpenAI
except ImportError:
    print("Missing dependency. Run: pip install openai --break-system-packages")
    sys.exit(1)

try:
    from pydantic import BaseModel
except ImportError:
    print("Missing dependency. Run: pip install pydantic --break-system-packages")
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

REPO_ROOT = Path(__file__).resolve().parent
sys.path.insert(0, str(REPO_ROOT))
from shopee_mentions import load_shopee_mentions  # noqa: E402

MODEL = "gpt-4o-mini"
PRICE_PER_1M_INPUT_TOKENS = 0.15
PRICE_PER_1M_OUTPUT_TOKENS = 0.60

OUTPUT_DIR = REPO_ROOT / "output"
BACKUP_DIR = OUTPUT_DIR / "backups"
FULL_OUTPUT_PATH = OUTPUT_DIR / "acneaid_th_shopee_sentiment.csv"
PILOT_OUTPUT_PATH = OUTPUT_DIR / "acneaid_th_shopee_sentiment_PILOT.csv"

BATCH_SIZE = 10
PILOT_SAMPLE_SIZE = 20

# Same vocabulary as entity_resolution.py/extract_lazada_sentiment.py, for
# cross-source comparability in any downstream Gold table that rolls up
# attribute_tags across sources.
ATTRIBUTE_VOCAB = [
    "price", "packaging", "efficacy", "scent", "texture", "availability",
    "irritation_tolerance", "authenticity_counterfeit",
]

SENTIMENT_VALUES = {"positive", "negative", "neutral", "mixed"}


# ---------------------------------------------------------------------------
# Backup helper -- verbatim pattern from extract_lazada_sentiment.py
# ---------------------------------------------------------------------------
def backup_if_exists(path: Path, backup_dir: Path) -> None:
    if not path.exists():
        return
    backup_dir.mkdir(parents=True, exist_ok=True)
    stamp = datetime.now().strftime("%Y%m%d_%H%M%S")
    backup_path = backup_dir / f"{path.stem}_BACKUP_{stamp}{path.suffix}"
    shutil.copy2(path, backup_path)
    print(f"  [backup] {path.name} -> {backup_path}")


def safe_write_csv(df: pd.DataFrame, path: Path, backup_dir: Path) -> None:
    backup_if_exists(path, backup_dir)
    df.to_csv(path, index=False)
    print(f"  [write]  {path} ({len(df)} rows)")


# ---------------------------------------------------------------------------
# Cost tracker -- same shape/rates as extract_lazada_sentiment.py
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


SYSTEM_PROMPT = f"""You are a market-research analyst coding Shopee Thailand product
reviews for the Acne-Aid skincare brand. Every review below is for an Acne-Aid product
(already confirmed from the product listing) -- do NOT question or re-identify the
brand, just read the review as feedback about that product. Reviews are already
machine-translated to English where the source was Thai. Focus only on the three
signals below.

1. sentiment: one of "positive", "negative", "neutral", "mixed" -- the reviewer's overall
   sentiment toward the product, based on the REVIEW TEXT. A star rating is deliberately
   NOT given to you here -- some reviews carry a high star rating but lukewarm or mixed
   text (or vice versa); code strictly what the text itself says, don't guess a rating.

2. attribute_tags: zero or more of this controlled vocabulary ONLY:
   {", ".join(ATTRIBUTE_VOCAB)}
   -- whichever product attributes this review actually comments on.

3. attribute_notes: optional short free-text note for anything notable the vocabulary
   above doesn't capture. Leave null (JSON null, not the text "null") if nothing notable
   falls outside the vocabulary.

4. confidence: 0.0-1.0, your confidence that the review text itself contains enough real
   signal to support the sentiment/attribute read above. Many Shopee reviews are extremely
   short ("ok", "5 stars", "fast delivery", "good seller") with almost no product
   commentary -- score those low rather than forcing a confident read from thin text.

Return one result per input id, matched exactly.
"""


def build_user_prompt(batch: list[tuple]) -> str:
    items = [{"id": mention_id, "brand": brand, "text": text} for mention_id, brand, text in batch]
    return json.dumps({"reviews": items}, ensure_ascii=False)


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


RESULT_COLS = ["sentiment", "attribute_tags", "attribute_notes", "confidence", "snapshot_date"]

# Drive-sync can transiently drop mid-write -- same root cause documented in
# extract_lazada_sentiment.py. A checkpoint failure must never crash the run
# and throw away everything extracted so far.
CHECKPOINT_RETRY_ATTEMPTS = 5
CHECKPOINT_RETRY_DELAY_SECONDS = 3


def _write_csv_with_retry(df: pd.DataFrame, path: Path) -> bool:
    for attempt in range(CHECKPOINT_RETRY_ATTEMPTS):
        try:
            path.parent.mkdir(parents=True, exist_ok=True)
            df.to_csv(path, index=False)
            return True
        except OSError as e:
            print(f"  [warn] checkpoint write failed (attempt {attempt + 1}/{CHECKPOINT_RETRY_ATTEMPTS}): {e}")
            time.sleep(CHECKPOINT_RETRY_DELAY_SECONDS)
    print(f"  [warn] checkpoint write failed after {CHECKPOINT_RETRY_ATTEMPTS} attempts -- "
          f"continuing extraction in memory, will retry at the next checkpoint interval "
          f"(or the final flush at the end of the run).")
    return False


def merge_results(mentions_df: pd.DataFrame, results: dict) -> pd.DataFrame:
    out = mentions_df.copy()
    for col in RESULT_COLS:
        out[col] = out["mention_id"].map(lambda mid: results.get(mid, {}).get(col))
    return out


def load_existing_results(path: Path) -> dict:
    if not path.exists():
        return {}
    existing = pd.read_csv(path)
    if "sentiment" not in existing.columns:
        return {}
    done = existing[existing["sentiment"].notna()]
    return {row["mention_id"]: {col: row.get(col) for col in RESULT_COLS}
            for _, row in done.iterrows()}


def run_extraction(client: OpenAI, mentions_df: pd.DataFrame, cost_tracker: CostTracker,
                    snapshot_date: str, output_path: Path | None = None,
                    checkpoint_every: int = 20) -> pd.DataFrame:
    results: dict[str, dict] = load_existing_results(output_path) if output_path else {}
    if results:
        print(f"  Resuming: {len(results)} of {len(mentions_df)} mentions already extracted "
              f"in a previous run -- skipping those, only processing the rest.")

    pending = mentions_df[~mentions_df["mention_id"].isin(results.keys())]
    rows = list(zip(pending["mention_id"], pending["canonical_brand"], pending["text"]))
    if not rows:
        print("  Nothing to extract -- all mentions already have results from a previous run.")

    def checkpoint():
        if output_path is None:
            return
        merged = merge_results(mentions_df, results)
        if _write_csv_with_retry(merged, output_path):
            print(f"  [checkpoint] {output_path.name} ({len(results)} of {len(mentions_df)} rows extracted)")

    for i in range(0, len(rows), BATCH_SIZE):
        batch = rows[i:i + BATCH_SIZE]
        batch_num = i // BATCH_SIZE + 1
        print(f"  extracting batch {batch_num} "
              f"({i + 1}-{min(i + BATCH_SIZE, len(rows))} of {len(rows)} remaining) ...")
        try:
            batch_results = extract_batch(client, batch, cost_tracker)
        except Exception as e:
            print(f"  [error] batch failed: {e}")
            continue
        for mention_id, extraction in batch_results.items():
            cleaned = validate_and_clean(extraction)
            cleaned["snapshot_date"] = snapshot_date
            results[mention_id] = cleaned
        print(f"  -> {len(results)} of {len(mentions_df)} extracted so far (overall). {cost_tracker.summary()}")
        if batch_num % checkpoint_every == 0:
            checkpoint()
        time.sleep(0.5)

    checkpoint()
    return merge_results(mentions_df, results)


def main():
    parser = argparse.ArgumentParser(description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter)
    parser.add_argument("--mode", choices=["pilot", "full"], default="pilot",
                         help="pilot (default): 20-row sample, print + write _PILOT.csv, then stop. "
                              "full: run over all Shopee (Acne-Aid) mentions.")
    parser.add_argument("--confirm", action="store_true",
                         help="Required alongside --mode full to actually spend API budget.")
    parser.add_argument("--checkpoint-every", type=int, default=20)
    args = parser.parse_args()

    api_key = os.environ.get("OPENAI_API_KEY")
    if not api_key:
        print("ERROR: OPENAI_API_KEY not set in environment. Refusing to run -- "
              "set it in .env or the environment and re-run.")
        sys.exit(1)

    if args.mode == "full" and not args.confirm:
        print("ERROR: --mode full requires --confirm as an explicit spend gate. "
              "Re-run as: python extract_shopee_sentiment.py --mode full --confirm")
        sys.exit(1)

    client = OpenAI(api_key=api_key)
    cost_tracker = CostTracker()
    snapshot_date = date.today().isoformat()

    mentions_df = load_shopee_mentions()
    print(f"Loaded {len(mentions_df)} Acne-Aid Shopee mentions.")

    if args.mode == "pilot":
        print(f"\n=== PILOT MODE: {PILOT_SAMPLE_SIZE}-row sample ===")
        sample = mentions_df.sample(n=min(PILOT_SAMPLE_SIZE, len(mentions_df)), random_state=42).reset_index(drop=True)

        result = run_extraction(client, sample, cost_tracker, snapshot_date)

        pd.set_option("display.max_colwidth", 100)
        print("\n=== PILOT RESULTS (review before running --mode full) ===")
        for _, row in result.iterrows():
            print(f"\n[{row['mention_id']}] rating={row['rating']}")
            print(f"  text: {str(row['text'])[:200]}")
            print(f"  sentiment:       {row['sentiment']}")
            print(f"  attribute_tags:  {row['attribute_tags']}")
            print(f"  attribute_notes: {row['attribute_notes']}")
            print(f"  confidence:      {row['confidence']}")

        OUTPUT_DIR.mkdir(parents=True, exist_ok=True)
        safe_write_csv(result, PILOT_OUTPUT_PATH, BACKUP_DIR)

        print(f"\nPilot cost: {cost_tracker.summary()}")
        print(f"Full corpus size: {len(mentions_df)} rows")
        print("\nReview the printed rows above. If quality looks right, run:\n"
              "  python extract_shopee_sentiment.py --mode full --confirm")

    else:
        print("\n=== FULL BATCH MODE ===")
        OUTPUT_DIR.mkdir(parents=True, exist_ok=True)
        backup_if_exists(FULL_OUTPUT_PATH, BACKUP_DIR)

        result = run_extraction(
            client, mentions_df, cost_tracker, snapshot_date,
            output_path=FULL_OUTPUT_PATH, checkpoint_every=args.checkpoint_every,
        )

        print(f"\nTotal cost this run: {cost_tracker.summary()}")
        print(f"Final output: {FULL_OUTPUT_PATH} ({len(result)} rows, "
              f"{result['sentiment'].notna().sum()} with a completed extraction)")
        print("Done. This file is a STAGING output -- not yet merged into fact_mention.csv.")
        print("Next: python acneaid_medallion/silver/build_facts.py")


if __name__ == "__main__":
    main()
