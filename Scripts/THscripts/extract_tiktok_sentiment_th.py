"""
extract_tiktok_sentiment.py

Extract brand entity resolution + sentiment + attribute tags from TikTok comment data,
reusing entity_resolution.py's LLM extraction logic.

Reads: tiktok_full_clean_translated.csv (8,506 comments, already translated to English)
Outputs: output/acneaid_th_tiktok_mention_coded.csv (ready for fact_mention integration)

Same extraction logic as entity_resolution.py:
  - brand_mentioned: list of brands, grounded to canonical 8-brand tracked set (NOT 9)
  - product_mentioned: list of products (empty for most non-Acne-Aid brands)
  - sentiment: positive/negative/neutral/mixed
  - attribute_tags: controlled vocabulary (price, packaging, efficacy, scent, texture,
                    availability, irritation_tolerance, authenticity_counterfeit)
  - attribute_notes: free text for anything else
  - confidence: 0-1 model confidence in brand identification

Checkpointing: resumable. Interrupt anytime; re-run the same command to pick up where it left off.

Usage:
  python extract_tiktok_sentiment.py                       # pilot: 30-row sample, review quality
  python extract_tiktok_sentiment.py --mode full --confirm  # full: all 8,506 comments

Requirements:
  pip install openai pydantic python-dotenv pandas --break-system-packages
"""

import argparse
import json
import os
import re
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
sys.path.insert(0, str(REPO_ROOT / "dashboard" / "acneaid_dashboard" / "app" / "lib"))
from sku_competitor_map import SKU_LIST, COMPETITOR_MAP

MODEL = "gpt-4o-mini"
PRICE_PER_1M_INPUT_TOKENS = 0.15
PRICE_PER_1M_OUTPUT_TOKENS = 0.60

TIKTOK_CSV = REPO_ROOT / "tiktok_full_clean_translated.csv"
OUTPUT_DIR = REPO_ROOT / "output"
BACKUP_DIR = OUTPUT_DIR / "backups"
FULL_OUTPUT_PATH = OUTPUT_DIR / "acneaid_th_tiktok_mention_coded.csv"
PILOT_OUTPUT_PATH = OUTPUT_DIR / "acneaid_th_tiktok_mention_coded_PILOT.csv"

BATCH_SIZE = 10
PILOT_SAMPLE_SIZE = 30

# Canonical entity list -- TRACKED 8-brand set (not the 9-brand entity_resolution uses).
# This is what build_facts.py filters on (dim_brand.status == 'tracked').
CANONICAL_BRANDS = [
    "Acne-Aid", "CeraVe", "Cetaphil", "Neutrogena", "Clean and Clear",
    "Eucerin", "Smooth E", "Bifesta",
]

CANONICAL_PRODUCTS: dict[str, list[str]] = {"Acne-Aid": [s["key"] for s in SKU_LIST]}
for _sku_key, _brand_map in COMPETITOR_MAP.items():
    for _brand, _product_name in _brand_map.items():
        if _brand in CANONICAL_BRANDS:  # only tracked brands
            CANONICAL_PRODUCTS.setdefault(_brand, []).append(_product_name)
for _brand in CANONICAL_BRANDS:
    CANONICAL_PRODUCTS.setdefault(_brand, [])

ATTRIBUTE_VOCAB = [
    "price", "packaging", "efficacy", "scent", "texture", "availability",
    "irritation_tolerance", "authenticity_counterfeit",
]


def _normalize_product_key(name: str) -> str:
    n = re.sub(r"(?<!\d)1x(\d+\s*ml)\b", r"\1", name, flags=re.IGNORECASE)
    return re.sub(r"\s+", " ", n).strip().lower()


PRODUCT_LOOKUP: dict[str, dict[str, str]] = {
    brand: {_normalize_product_key(p): p for p in products}
    for brand, products in CANONICAL_PRODUCTS.items()
}


def _build_entity_list_block() -> str:
    lines = []
    for brand in CANONICAL_BRANDS:
        products = CANONICAL_PRODUCTS.get(brand, [])
        lines.append(f"- {brand}")
        for p in products:
            lines.append(f"    * {p}")
        if not products:
            lines.append("    (no canonical product list for this brand -- brand-level only)")
    return "\n".join(lines)


ENTITY_LIST_BLOCK = _build_entity_list_block()


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
    df.to_csv(path, index=False, encoding='utf-8')
    print(f"  [write]  {path} ({len(df)} rows)")


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
            f"~${self.estimated_cost():.4f} estimated (gpt-4o-mini rates)"
        )


class BrandMention(BaseModel):
    brand: str
    product: Optional[str] = None


class MentionExtraction(BaseModel):
    id: str
    brands_mentioned: list[BrandMention]
    sentiment: str
    attribute_tags: list[str]
    attribute_notes: Optional[str] = None
    confidence: float


class MentionBatchResponse(BaseModel):
    results: list[MentionExtraction]


SENTIMENT_VALUES = {"positive", "negative", "neutral", "mixed"}

SYSTEM_PROMPT = f"""You are a market-research analyst performing entity resolution on
consumer-generated content (TikTok comments) about acne skincare brands in Thailand.
The text has already been machine-translated to English.

For each mention below, identify:

1. brands_mentioned: every brand from the CANONICAL LIST below that this
   specific comment is actually discussing. For each brand, also give `product` --
   the single closest matching product name from that brand's canonical product
   list below, or null if the comment doesn't identify a specific product or no
   canonical product list exists for that brand.

   CRITICAL -- fail closed: only use brand/product names EXACTLY as they
   appear in the canonical list below. Never invent, guess, or normalize a
   variant spelling into a "close enough" canonical entry. If you are not
   confident which brand a comment refers to, or confident a competitor
   brand is even being discussed at all (as opposed to skincare/acne in
   general), leave brands_mentioned empty ([]) rather than guessing. Same
   for product: if you can't confidently identify a specific product from
   the list, set product to null.

CANONICAL BRAND AND PRODUCT LIST (tracked brands only):
{ENTITY_LIST_BLOCK}

2. sentiment: one of "positive", "negative", "neutral", "mixed" -- the
   overall sentiment of the comment toward the brand(s)/product(s) it discusses.

3. attribute_tags: zero or more of this controlled vocabulary ONLY:
   {", ".join(ATTRIBUTE_VOCAB)}
   -- whichever product attributes this comment actually comments on.

4. attribute_notes: optional short free-text note for anything notable
   the controlled vocabulary above doesn't capture. Leave null if nothing notable
   falls outside the vocabulary.

5. confidence: your own 0.0-1.0 confidence in the brand/product identification
   for this comment specifically (not the sentiment or attributes).

Return one result per input id, matched exactly.
"""


def build_user_prompt(batch: list[tuple]) -> str:
    items = [{"id": mention_id, "text": text} for mention_id, text in batch]
    return json.dumps({"mentions": items}, ensure_ascii=False)


def extract_batch(client: OpenAI, batch: list[tuple], cost_tracker: CostTracker) -> dict:
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
    clean_brands, clean_products = [], []
    for bm in extraction.brands_mentioned:
        if bm.brand not in CANONICAL_BRANDS:
            print(f"  [warn] dropping non-canonical brand '{bm.brand}' (id={extraction.id})")
            continue
        product = bm.product
        if isinstance(product, str) and product.strip().lower() == "null":
            product = None
        if product is not None:
            canonical = PRODUCT_LOOKUP.get(bm.brand, {}).get(_normalize_product_key(product))
            if canonical is not None:
                product = canonical
            else:
                print(f"  [warn] dropping non-canonical product '{product}' for brand "
                      f"'{bm.brand}' (id={extraction.id})")
                product = None
        clean_brands.append(bm.brand)
        clean_products.append(product)

    sentiment = extraction.sentiment if extraction.sentiment in SENTIMENT_VALUES else "neutral"
    if extraction.sentiment not in SENTIMENT_VALUES:
        print(f"  [warn] non-canonical sentiment '{extraction.sentiment}' -> 'neutral' (id={extraction.id})")

    clean_tags = [t for t in extraction.attribute_tags if t in ATTRIBUTE_VOCAB]
    dropped_tags = set(extraction.attribute_tags) - set(clean_tags)
    if dropped_tags:
        print(f"  [warn] dropping non-canonical attribute tag(s) {dropped_tags} (id={extraction.id})")

    confidence = max(0.0, min(1.0, extraction.confidence))

    return {
        "brand_mentioned": json.dumps(clean_brands, ensure_ascii=False),
        "product_mentioned": json.dumps(clean_products, ensure_ascii=False),
        "sentiment": sentiment,
        "attribute_tags": json.dumps(clean_tags, ensure_ascii=False),
        "attribute_notes": extraction.attribute_notes,
        "confidence": confidence,
    }


def load_tiktok_csv() -> pd.DataFrame:
    """Load TikTok CSV and format for extraction. Generates mention_id from video_id + comment_id."""
    df = pd.read_csv(TIKTOK_CSV)

    # Deduplicate by comment_id (in case video_id appears multiple times)
    df = df.drop_duplicates(subset=["comment_id"], keep="first").reset_index(drop=True)

    # Generate stable mention_id from comment_id
    df["mention_id"] = "tiktok_comment_" + df["comment_id"].astype(str)

    # Use comment_text (already translated to English by translate_tiktok_content.py)
    text = df["comment_text"].fillna("").astype(str).str.strip()
    text = text[text.str.len() > 0]

    return pd.DataFrame({
        "mention_id": df.loc[text.index, "mention_id"],
        "source": "tiktok_content",
        "brand": df.loc[text.index, "brand"],  # source-tagged brand (for sampling only)
        "text": text.values,
        "comment_create_time": df.loc[text.index, "comment_create_time"],
    }).reset_index(drop=True)


RESULT_COLS = ["brand_mentioned", "product_mentioned", "sentiment",
               "attribute_tags", "attribute_notes", "confidence", "snapshot_date"]

CHECKPOINT_RETRY_ATTEMPTS = 5
CHECKPOINT_RETRY_DELAY_SECONDS = 3


def _write_csv_with_retry(df: pd.DataFrame, path: Path) -> bool:
    for attempt in range(CHECKPOINT_RETRY_ATTEMPTS):
        try:
            path.parent.mkdir(parents=True, exist_ok=True)
            df.to_csv(path, index=False, encoding='utf-8')
            return True
        except OSError as e:
            print(f"  [warn] checkpoint write failed (attempt {attempt + 1}/{CHECKPOINT_RETRY_ATTEMPTS}): {e}")
            time.sleep(CHECKPOINT_RETRY_DELAY_SECONDS)
    print(f"  [warn] checkpoint write failed after {CHECKPOINT_RETRY_ATTEMPTS} attempts.")
    return False


def merge_results(source_df: pd.DataFrame, results: dict) -> pd.DataFrame:
    out = source_df.copy()
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


def run_extraction(client: OpenAI, source_df: pd.DataFrame, cost_tracker: CostTracker,
                    snapshot_date: str, output_path: Path | None = None,
                    checkpoint_every: int = 20) -> pd.DataFrame:
    results: dict[str, dict] = load_existing_results(output_path) if output_path else {}
    if results:
        print(f"  Resuming: {len(results)} of {len(source_df)} comments already extracted "
              f"-- skipping those, only processing the rest.")

    pending = source_df[~source_df["mention_id"].isin(results.keys())]
    rows = list(zip(pending["mention_id"], pending["text"]))
    if not rows:
        print("  Nothing to extract -- all comments already have results from a previous run.")
        return merge_results(source_df, results)

    def checkpoint():
        if output_path is None:
            return
        merged = merge_results(source_df, results)
        if _write_csv_with_retry(merged, output_path):
            print(f"  [checkpoint] {output_path.name} ({len(results)} of {len(source_df)} rows extracted)")

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
        print(f"  -> {len(results)} of {len(source_df)} extracted so far. {cost_tracker.summary()}")
        if batch_num % checkpoint_every == 0:
            checkpoint()
        time.sleep(0.5)

    checkpoint()
    return merge_results(source_df, results)


def main():
    parser = argparse.ArgumentParser(description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter)
    parser.add_argument("--mode", choices=["pilot", "full"], default="pilot",
                        help="pilot (default): 30-row sample, review quality. "
                             "full: all 8,506 TikTok comments.")
    parser.add_argument("--confirm", action="store_true",
                        help="Required alongside --mode full to actually spend API budget.")
    parser.add_argument("--checkpoint-every", type=int, default=20,
                        help="Full mode: checkpoint progress every N batches (default 20).")
    args = parser.parse_args()

    api_key = os.environ.get("OPENAI_API_KEY")
    if not api_key:
        print("ERROR: OPENAI_API_KEY not set. Set it in .env or environment and re-run.")
        sys.exit(1)

    if args.mode == "full" and not args.confirm:
        print("ERROR: --mode full requires --confirm as a spend gate.")
        print("Re-run as: python extract_tiktok_sentiment.py --mode full --confirm")
        sys.exit(1)

    print(f"Loading TikTok data from {TIKTOK_CSV}...")
    source_df = load_tiktok_csv()
    print(f"Loaded {len(source_df)} comments, source brands: {source_df['brand'].value_counts().to_dict()}")

    client = OpenAI(api_key=api_key)
    cost_tracker = CostTracker()
    snapshot_date = date.today().isoformat()

    if args.mode == "pilot":
        print(f"\n=== PILOT MODE: {PILOT_SAMPLE_SIZE}-row sample ===")
        sample = source_df.sample(n=min(PILOT_SAMPLE_SIZE, len(source_df)), random_state=42).reset_index(drop=True)
        print(f"Sampled {len(sample)} rows")

        result = run_extraction(client, sample, cost_tracker, snapshot_date)

        pd.set_option("display.max_colwidth", 100)
        print("\n=== PILOT RESULTS (review before running --mode full) ===")
        for _, row in result.iterrows():
            print(f"\n[{row['mention_id']}]")
            print(f"  text: {row['text'][:150]}")
            print(f"  brand_mentioned:   {row['brand_mentioned']}")
            print(f"  product_mentioned: {row['product_mentioned']}")
            print(f"  sentiment:         {row['sentiment']}")
            print(f"  attribute_tags:    {row['attribute_tags']}")
            print(f"  attribute_notes:   {row['attribute_notes']}")
            print(f"  confidence:        {row['confidence']}")

        OUTPUT_DIR.mkdir(parents=True, exist_ok=True)
        safe_write_csv(result, PILOT_OUTPUT_PATH, BACKUP_DIR)

        print(f"\nPilot cost: {cost_tracker.summary()}")
        print("\nReview the results above. If quality looks right, run:\n"
              "  python extract_tiktok_sentiment.py --mode full --confirm")

    else:
        print("\n=== FULL BATCH MODE ===")
        OUTPUT_DIR.mkdir(parents=True, exist_ok=True)
        backup_if_exists(FULL_OUTPUT_PATH, BACKUP_DIR)

        result = run_extraction(
            client, source_df, cost_tracker, snapshot_date,
            output_path=FULL_OUTPUT_PATH, checkpoint_every=args.checkpoint_every,
        )

        print(f"\nTotal cost this run: {cost_tracker.summary()}")
        print(f"Final output: {FULL_OUTPUT_PATH} ({len(result)} rows, "
              f"{result['sentiment'].notna().sum()} with completed extraction)")
        print("\nNext step: integrate into fact_mention by running build_facts.py")
        print("Done.")


if __name__ == "__main__":
    main()
