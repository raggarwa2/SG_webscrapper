# Chart rules: client GM review (Acuvue)

Audience: the Acuvue GM, a client. They will look at each chart for about 30 seconds,
with no tooltips and no analyst in the room.
Purpose: show what the scraped market data says, as faithfully as possible.
I report the data. I do not interpret it, recommend actions, or tell a story.

## 1. Stay faithful to the data
- Show every category in the data. Never drop or "leave out" categories to make a cleaner chart.
- Small categories stay in. Fade them (lighter color) and label "low sample (n<10)" instead of hiding them.
- Use the data's own category names. Only rewrite them into plain English, never into a new grouping.
- If one item can belong to several categories, never add categories together or show a combined total.
  Say "an item can appear in more than one category" in the source line.
- Every number on the chart must be traceable to the scraped data. No estimates, no rounding that changes meaning.

## 2. No interpretation on the page
- Title is descriptive only. It says what is shown, not what it means.
  Good: "Barriers mentioned by customers, by theme"
  Bad: "The app is the barrier: 40 of 129 complaints are about the app"
- No "What this means", "So what", recommendations, or next steps.
- No callouts, arrows, or annotations that point the reader to a conclusion.
- Neutral wording. No loaded words like "problem", "failing", "weakness", "worst" in titles or labels.
- Example quotes are handled separately at the bottom of the page. Don't add quotes to charts.

## 3. Show the whole picture
- Barriers are shown as one overall category across all themes
  (for example, service, comfort and product, fitting and guidance, look and colour, price and value,
  loyalty and app, trust and authenticity, access and availability), not only the largest theme.
- Show positive and negative mentions together where the data has both, with the same scale and treatment.
- Don't explain the method on the chart. One short source line only:
  "Source: [sources], [date range]. Total items: [n]."

## 4. Readability rules (keep these)
1. Simplest chart type that fits. Default: sorted horizontal bar chart.
   Positive vs negative: diverging horizontal bars from a centre line.
2. One encoding per meaning. The number printed on a mark shows the same thing the mark's size or color shows.
3. Sort by value (largest first), never alphabetically.
4. Plain-English labels. No internal terms like "net", "items", "tagged".
5. Horizontal text only. No rotated labels.
6. Show "no data" explicitly. Never leave a blank that could be read as zero.
7. No chart junk: no toolbars, no 3D, minimal gridlines, direct labels instead of legends.
8. Colors: one consistent color for negative, one for positive, grey for low sample. Colorblind-safe.
   No single bar highlighted for emphasis.
9. Label each bar with the count and the share, e.g. "23 (18%)", and say what the share is "of".

## 5. Check by looking
After building each chart:
1. Render it to a PNG and open it.
2. Check, from the image only:
   - Is every category from the data present (including small ones)?
   - Does the title describe, without concluding?
   - Is there any wording, color or callout that pushes a conclusion? Remove it.
   - Do any totals add overlapping categories? Remove them.
   - Can a GM read what is shown in 30 seconds without help?
3. Fix and re-render if anything fails. Tell me the check result in 3 bullets.
