# Triangulation Analysis

Checks our scraped Hong Kong review/product data (`output/lensdata.db`) against the
research-agency framework described in `insight.txt`: the HK purchase-channel taxonomy,
the brand-switching barrier list, and the attribute-importance quadrant.

Prompts B, C, and D (barrier matches, attribute quadrant, combined summary) also
classify HK-relevant comments/posts from `output/youtube_data.db`,
`output/instagram_data.db`, and `output/facebook_data.db` alongside reviews and XHS
posts — same LLM classification pass, just a larger pool of consumer language.

It also pulls in the team's own manually-researched files under `Research/` —
`distribution.csv` and `pricing.csv` (which retailers are confirmed to exist, even ones
not yet scraped) and `reputation.csv` (external forum/press sentiment quotes) — so the
triangulation isn't limited to what the scraper happened to capture.

## Run it

1. Make sure `.env` (in the project root) has an `OPENAI_API_KEY` — same key already
   used by the scraping pipeline.
2. Install dependencies (same ones the rest of the project already uses):
   ```
   pip install pandas python-dotenv openai
   ```
3. From the project root, run:
   ```
   python triangulation/run_triangulation.py
   ```

This runs all four prompts and writes results to `output/triangulation/`. It takes a
few minutes and costs roughly a dollar or two in OpenAI API usage (gpt-4o-mini) the
first time. Re-running is nearly free — results are cached in
`output/triangulation/cache.json`, keyed by review/post, so only new reviews get
re-classified.

To run just one part (e.g. while checking new data), use `--prompt`:
```
python triangulation/run_triangulation.py --prompt a   # channel coverage (no API cost)
python triangulation/run_triangulation.py --prompt b    # barrier language match
python triangulation/run_triangulation.py --prompt c    # attribute quadrant validation
python triangulation/run_triangulation.py --prompt d    # combined per-brand summary
```

## What you get

| File | What it answers |
|---|---|
| `prompt_a_channel_coverage.md` / `.csv` | Which of the agency's 10 purchase channels are we scraping, and which online ones are we missing? |
| `prompt_b_barrier_matches.md` / `.csv` | Do the agency's 17 switching barriers actually show up in review/social text — and what complaints show up that AREN'T on their list? |
| `prompt_c_attribute_quadrant.md` / `.csv` | Do "comfort" and "12-hour wear" actually dominate the conversation per brand, as the agency's Key Drivers quadrant claims? |
| `prompt_d_triangulation_summary.md` | One-page-per-brand summary of where our data confirms vs. diverges from the agency's research — written as hypotheses to discuss with the client, not conclusions. |

Everything is plain markdown/CSV — no special software needed to open the results.

## Every claim links back to its source

Nothing in these outputs is asserted without a place to check it:
- Prompt A's "scraped via" / "known retailers" notes link to an actual scraped product
  page, or to the `distribution.csv`/`pricing.csv` row that mentions the retailer.
- Every example quote in Prompt B, and every attribute row in Prompt C, links to the
  actual review URL, XHS post URL, or forum thread (`reputation.csv`) it came from.
This isn't wired into a dashboard — it's just markdown links — but you can always click
through from a finding back to the original data.

## Notes on scope

- **Hong Kong only.** Thailand data (lazada_th, ta_to) is excluded — the agency's
  framework is HK-specific.
- **Offline channels are listed but not treated as gaps.** Independent optical stores,
  chain optical stores, supermarkets/department stores, and optometric centres are
  physical retail — a web scraper can't reach them, so Prompt A shows them for
  completeness against the agency's slide but doesn't recommend "closing" them.
- The taxonomy/barrier/attribute wording lives in `mappings.py` — edit it there if the
  agency updates their slides, no need to touch the rest of the script.
- **Every run archives the previous outputs.** Before Prompt B/C/D write new results,
  any existing `prompt_*.csv`/`.md` files are copied to
  `output/triangulation/history/<timestamp>_<label>/` (label via `--archive-label`,
  defaults to `auto`) — so a run can always be diffed against an earlier one, e.g. to
  see the effect of adding a new data source.
