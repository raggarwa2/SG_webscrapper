# Triangulation Analysis — Singapore

SG adaptation of `../triangulation_hk/`. Same four prompts (A channel coverage, B barrier
language, C attribute quadrant, D per-brand summary); different data sources and framework.

Run from the `Scripts/` folder (needs `OPENAI_API_KEY` in `.env`):

```
python triangulation_sg/run_triangulation.py              # all prompts
python triangulation_sg/run_triangulation.py --prompt a   # channel coverage, no API cost
```

Outputs go to `output/triangulation_sg/` (previous runs archived under `history/`;
LLM results cached in `cache.json`, so re-runs only classify new rows).

## Data sources (all `market = 'SG'`)

| Source | DB / table | Filter |
|---|---|---|
| Lazada reviews | `sg_acuvue.db` reviews | all with text |
| Products (Prompt A) | `sg_acuvue.db` products | Lazada + TikTok Shop |
| Kiasuparents forum summaries | `sg_acuvue.db` forum_posts | all (replaces HK `reputation.csv`) |
| XHS posts | `xhs_data_sg.db` | `market_relevant` (XHS is China-wide) |
| Google Maps optical retailers (Prompt A) | `gmaps_data_sg.db` | per-chain places/reviews |
| MyACUVUE app reviews (Prompt A) | `app_data_sg.db` | SG |
| YouTube / Instagram / Facebook / Reddit comments | `*_data_sg.db` | lens- and brand-relevant |

## Differences from HK — check these

- **Channel taxonomy is a draft** (`mappings.py`), built from `context.md`/`scripts.md` (Lazada, Shopee,
  TikTok Shop, MyACUVUE app, Optical 88/Watsons Optical, ECPs). HK's came from an agency slide; no SG
  equivalent exists.
- **Barriers are SG-specific** (10 consolidated, from `analysis/4_category_user_barrier_framework.md`). The attribute
  quadrant is still the HK one, unchanged. 
- **Brand names are normalised** (`MyACUVUE`/`ACUVUE` → `Acuvue`, `Bausch + Lomb` → `Bausch & Lomb`).
  Prompt D covers Acuvue, Alcon, Bausch & Lomb, CooperVision, Olens.
- **No `distribution.csv` / `pricing.csv` for SG** (looked in `data/research/`), so Prompt A
  shows scraper coverage only, with no "known but not scraped" evidence.
- **Lazada products and reviews have no URL stored**, so Lazada quotes appear without a source link.
- **Facebook has no English column**; the original comment text is classified as-is.
- Shopee has no data in `sg_acuvue.db`, so it shows as a gap in Prompt A.
