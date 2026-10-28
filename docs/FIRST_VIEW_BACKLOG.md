# First-view backlog: 15 more no-LLM summaries

Each runs on the same item table as `FIRST_VIEW_SPEC.md`, with plain pandas, regex and counting. No API calls. Apply the same global rules (filters, base of 15 for rates, 10 for bars, sample-size strip, click-through).

Effort: S = under half a day, M = about a day. Value: how much the end user gets from it on first sight.

| # | Summary | What it shows | How (no LLM) | Chart | Effort | Value |
|---|---|---|---|---|---|---|
| 1 | Channel-comparability map | Which brand pairs can be compared fairly, and on which channels | Count items per brand × source; mark a pair comparable where both sides reach 15 | Grid of ticks / dashes | S | High |
| 2 | Duplicate and near-duplicate share | How much of the data is repeated or copy-pasted | Exact match on normalised text; near match by 5-word shingles (Jaccard 0.8) | Bar by source + examples list | S | High |
| 3 | Language mix | How much is non-English and where | `lang_guess` share by source and brand; note translation needs | Stacked bar | S | Medium |
| 4 | Text length and effort | Where comments are substantive vs one-word | Median character count and % under 20 characters, by source | Box plot or bar | S | Medium |
| 5 | Top contributors | Whether a few accounts dominate | Count by `account`/author; share of items from the top 10 accounts | Pareto bar + share tile | S | High |
| 6 | Posting-time pattern | When people write | Hour of day and day of week from timestamps, where present | Heatmap (weekday × hour) | S | Medium |
| 7 | Question and help-seeking share | How many items ask something | Contains `?` or starts with how/where/can/is/why/should; count by source and brand | Bar + list of top questions | S | High |
| 8 | Price mentions | What prices people quote | Regex for `$`, `S$`, `SGD`, digits with currency; median and range per brand | Dot plot of quoted prices | M | High |
| 9 | Retailer and platform mentions | Where people say they buy | Dictionary of retailer names (Shopee, Lazada, Watsons, Guardian, optical shops...) counted in text | Bar + brand × retailer heatmap | S | High |
| 10 | Competitor co-mention | Which brands are named together | Items where 2+ `brand_std` names or aliases appear; pair counts | Chord-free matrix heatmap | M | High |
| 11 | Hashtag and mention network | What tags travel with the topic | Extract `#tags` and `@handles`; top 20 by count, by brand | Ranked bar + table | S | Medium |
| 12 | Link and domain share | What outside sites are cited | Extract URLs from text; count domains | Bar of domains | S | Low |
| 13 | New-vs-recurring terms | What is rising | Phrases whose last-6-month frequency is 2× the earlier period (base 10) | Slope chart or two-column list | M | High |
| 14 | Rating vs text-length check | Whether low ratings write more | Correlate `rating_native` with character count; mean length per star | Bar by star | S | Low |
| 15 | Engagement outliers | Items far above normal for their source | Likes above 99th percentile or 5× source median; list with link | Strip chart + top list | S | Medium |

## Suggested order

1. Quick wins that change how the end user reads the rest: #1, #2, #5, #3.
2. Business-relevant counts: #9, #7, #8.
3. Needs a little more logic: #10, #13.
4. The rest as time allows.

## Notes per item

- **#1** feeds a banner on View 2 ("these brands are not comparable on this channel").
- **#2** also gives a clean count for View 1's "removed" tile.
- **#5** flag with a warning when the top 10 accounts supply over 25% of a source's items.
- **#6** needs a timestamp, not just a date; skip and say so when the source has date only.
- **#7** a list of the 20 most-liked questions is useful to the content team and costs nothing.
- **#8** keep currency symbols and quoted ranges separate; show "n price mentions" as the base, and hide a brand under 15.
- **#9** the dictionary is a CSV the user can edit (`retailers.csv`: `name`, `alias`).
- **#10** matching is on `brand_std` plus an alias list (`brands.csv`), case-insensitive, whole word.
- **#13** this is a frequency comparison, not a meaning check; label it "wording that is rising".
- **#14 and #15** are small add-ons to View 4 rather than new sections.

## Out of scope here (needs a model, so costs tokens)

Sentiment, themes with polarity, journey stage, barrier labels, summaries in prose, translation. These stay in the tagging step.
