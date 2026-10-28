Consumer Intel gold delivery - schema gold-1.2
Study: MYACUVUE SG (myacuvue-sg)
Market: SG   Run: all   Generated (UTC): 2026-10-28T03:15:08+00:00

What this is: an external evidence base on how a brand is doing in one market (prices, promotions, reviews, forum and social conversation, search position). It stops at the external data; it contains no strategy and no scores.
Missing data is an empty cell plus a status, never zero. A source that failed is `blocked` on the Coverage sheet with its reason; it is not reported as 0 results.
No names or photos are in these tables. Reviewers and commenters appear only as author_hash. (The saved copy of each page, kept as evidence, is a copy of what the site shows publicly.)
Join keys: country + platform + listing_id (+ run_id for a snapshot). posts and post_comments join on platform + post_id + run_id. All IDs are text; keep them as text when you import (long IDs lose digits as numbers).
Time: observed_at_utc is UTC. source_posting_date keeps the source's own time zone where it gave one (source_date_tz).
Every row has bronze_ref, the raw response it came from, so any number can be checked against the original.
Repeated runs are kept as separate snapshots (same listing_id, different run_id and observation_date), so change over time can be read.
Free text that begins with = + - or @ is stored as text. In the CSV files such a cell starts with a single quote; the Excel file stores it as plain text without the quote.
CSV is the data (UTF-8 with BOM). Excel is the easy read of the same rows. Tables longer than the Excel sheet limit are split by month in the workbook; the CSV is never split.
Collection methods: http = our own agent on public pages; apify = a paid third-party route used only with the owner's opt-in; har_import = a browser export captured by the owner. See the handoff note for terms-of-use status per source.
search_ranks.rank_basis says whether rank has been verified against a captured page.
search_interest holds Google Trends weekly points. Google scales each request to its own peak, so the index is not search volume and two requests are comparable only through the anchor term carried in both.
search_summary and search_insights are read-outs derived from search_interest by fixed rules (4-week levels, change against the previous 4 weeks and the same weeks a year ago, rank, share of the leader); every figure can be recomputed from search_interest. They state comparisons only: no advice, no score.
Other derived tables (themes, change flags, timeline) are not part of schema gold-1.2.
