# Dashboard summary (one line per chart; update with every page change)

Rules are in CLAUDE.md ("Dashboard summary"). Format: `chart: what it plots | key number or finding | source`.
Status: Reviewed = user has checked the page; Pending = not yet.

## 1. Brand Overview (brand_overview_page.py + market_competitors.py) | Rebuilt, awaiting review
Order: 1 Scorecard (HK block), then SG-only blocks 2 Ratings, 3 Category, 4 Share of voice, 5 Reach, limits box. No top card.
1. Scorecard table (HK "Brand health scorecard"): per brand products, stores, weighted rating, reviews collected, items per channel (KiasuParents, XHS, Reddit, YouTube, Instagram, Facebook), social signals
2. Ratings (SG-only): bar of weighted rating for brands with 15+ ratings | Acuvue 4.98 on 56 ratings, 3 of 5 brands chartable; CooperVision and Olens have none (footnote), no significance test | retailer pages. "Reviews collected" chart removed (in table + strip)
3. Category (SG-only): cards imports 2025 value US$242m (-23% vs 2023), units 143m (-25%), price per unit US$1.69 | two bar panels units/value 2023-2025: stepped down ~26% in 2024, flat since | UN Comtrade HS 9001.30. Exports 2.0x imports (pass-through), not shown
4. Share of voice (SG-only; home of this number): stacked bar per brand, % of analysed items by channel | top brand by items; Olens dominates YouTube, no Alcon Facebook page | voice items. Table on click
5. Reach (SG-only): bars of brand share for YouTube views, Instagram likes, XHS likes (15+ posts each) | leader changes by measure; warns if one item is 60%+ of a brand | scraped. Comments & posts panel removed (is share of voice). Table on click
6. Limits box: no market share (J&J ~36%), no in-store prices or bulk deals, no lens prices (HSA), counts are not sales, import decline may not be falling demand
Removed: solution offer rates, intro card, Reviews-collected chart.

## Layout standard (HK pattern; client likes the HK story)
- Proof foot (closed expander, word search, links): Brand Overview, Brand Health (brand pool); Price (priced listings); Reviews & Sentiment (reviews); Social Signals (per channel: tagged items + posts/videos with links); Catalog > Store ranking (listings); Journey & App, Research > Barriers, Key findings, Retail & Promotions (complaint items / store reviews); Trends (brand-named items). None: Data Notes, search-index views, desk-research and Stage 2 views.
- Tab order and sub-tabs as HK (9 tabs); SG adds Journey & App, Retail & Promotions, Data Notes position, Brand protection (Catalog), Barriers and Stage 2 bridge (Research pills).
- Each tab: HK's data blocks in HK order, then SG-only blocks. NO bottom-line card at the top (only Key findings has one). Finding-led section titles, one-line takeaway per chart, tables collapsed, limits note last.
- Barrier charts use the framework barrier labels; Product & look is excluded from them (headline strip owns it).
- Research & Triangulation uses HK's pill menu in HK order; HK sections with no SG data stay as labelled gap pills.
- One home per number: share of voice and category imports = Brand Overview; composite sentiment = Brand Health; review-level evidence = Reviews & Sentiment; complaint topics = Barriers; store rating = Catalog; channel coverage = Data Notes; Google Maps = Retail & Promotions; hypotheses = Triangulation.

## Map of tabs 2-11 (from section/chart headlines in code; not yet reviewed)
Replace each block with the final state as you finish reviewing that page. Numbers are kept only where a page is final.

## 2. Brand Health | Pending (brand_health_page.py, brand_market_page.py)
- HK "All Brands Overview": balanced score cards + ranking dots: % positive or neutral on social channels with 15+ items (XHS, Reddit, YouTube, Instagram, Facebook), sqrt(n)-weighted; all brands healthy (72 to 88); title states the channel-weighted net gap (Acuvue level with peers, -5, interval -16 to +6), no rank | brand_health_page
- Heatmap: % positive or neutral by brand and channel; Lazada reviews and KiasuParents shown beside the score, not in it | brand_health_page
- Acuvue by channel: net sentiment Acuvue vs peers where both sides have 15+ items (+11 Reddit to +49 XHS; real gap only YouTube and KiasuParents, both behind) | brand_health_page
- HK "Brand Deep-Dive" (per-brand view, brand_health_page.render): Acuvue by channel as above; hesitation view on XHS, Reddit, YouTube, Instagram
- SG-only, Consumers vs own posts: complaint/praise topic share, consumers raise <top> in X% of items, Acuvue posts about it in Y% (brand_market_page)

## 3. Price Intelligence | Pending (app.py)
- Median price by brand (headline "runs from X to Y"); average discount by store and brand
- Check: online lens sale is illegal under HSA; confirm what is priced and that it is lenses

## 4. Reviews & Sentiment | Pending (app.py)
- Review Intelligence: volume and average rating by month; "X% of reviews are 1-2 star"; lowest-rated list; positive/neutral/negative share by brand; metrics total reviews, positive %, negative %, rating
- Sentiment Intelligence: positive/negative cards; monthly sentiment by sub-brand
- New Wearers: first-time-buyer reviews (count, avg rating vs overall, positive/negative %), newest-first list

## 5. Social Signals | Pending (app.py)
- XHS: 10 most-liked posts per brand; audience reaction in comments; post vs comment positive share and gap; negative posts count
- Reddit, YouTube, Instagram, Facebook: not yet mapped (detail lives in app.py and *_signals loaders)

## 6. Journey & App (barriers_page.py, SG-only) | Barrier moved to Research & Triangulation, Retail to Retail & Promotions
Opens on header strip (6 cards: data points 11,103, net sentiment +38 vs +44, top complaint Product & look, written app reviews 94% negative (n=33), search interest +56%, data window) then nav 1-3.
1. Journey: stacked bar of Acuvue complaint items per stage by source (consumer n=51, app n=78) | default view Acuvue consumers only: peak Repeat/Retention, 22 of 51 staged; Acuvue+app view peaks at Trial (62 of 127) only because the app is placed at Trial by design | journey_stage_sg.db. Acuvue-only view; channel-role map
2. App reviews: Apple/Google avg and 1-star share (Apple 2.36 / 51%, Google 3.32 / 32%); star polarisation; negative share by era (94% of 33 written in 2024-2026; stars milder); top issue chart (79 negative) | written reviews 119 | app stores
3. Message: WhatsApp map, barrier to stage to draft message; test and guardrail per message | 85 Acuvue items vs 83 peer items | needs J&J legal/PDPA review

## 7. Retail & Promotions | Pending (app.py)
- Google Maps: store friction in optical chains (reviews, outlets, avg stars, % describing friction)
- Store reviews on shared labels (barriers_page.render_retail): Google Maps contact-lens reviews 862, 87% positive, complaints on service and guidance, only 12 name Acuvue (535 Owndays); chain table; Loyalty & app 9 tags in store vs 78 in app
- Facebook retailers sub-tab: not yet mapped

## 8. Catalog Explorer | Pending (app.py, brand_protection.py)
- Store ranking by review-weighted rating (15+ reviews); multi-brand stores; every tracked listing (price, rating, discount)
- Brand protection: flagged rows, distinct lens listings, named sellers; most-listed brand; sellers of Acuvue; RevitaLens pack price spread across sellers

## 9. Research & Triangulation | Pending (app.py pill menu in HK order; triangulation_pages.py, research_extra_pages.py)
Pills: Research Findings, Channel Coverage, Distribution Gap, Barrier Matches, Barriers (SG), Attribute Quadrant, Combined Summary, Share of Voice, -ve and +ve Tail, Price vs. Sentiment, External Validation, Purchasing Trend, Before vs After, Stage 2 bridge (SG).
- Research Findings: hypothesis check (supported / mixed / cannot test) + Category users & positioning (positioning map, MyACUVUE vs Olens) | triangulation_pages, positioning_pages
- Channel Coverage: items collected per retail channel, online gaps (Shopee none) | triangulation_pages. Home of channel coverage
- Barrier Matches: framework barrier vs scraped complaint items, pool of brands | triangulation_pages
- Barriers (SG-only): framework barrier labels on Acuvue own complaints (consumer + app); Product & look set aside (headline strip owns it); barrier x lens heatmap; peers not compared | barriers_page.render_barrier
- Combined Summary = Key findings (answer_page.py): bottom line, how sure we are of each finding. Only page with a bottom line
- Share of Voice: share of analysed items by brand and channel | research_extra_pages. Same figure as Brand Overview (see overlaps)
- -ve and +ve Tail: complaint tail | research_extra_pages
- Stage 2 bridge (SG-only): five hypotheses scraping cannot test | overview_pages
- Gap pills, no SG data, labelled in the app (Distribution Gap, Attribute Quadrant, Price vs. Sentiment, External Validation, Purchasing Trend, Before vs After): Distribution Gap and Purchasing Trend link to Retail & Promotions and Trends & Demand. Decision on which to build is pending (docs/DECISION_LOG.md)

## 10. Trends & Demand | Pending (trends_demand_page.py, trends_signals.py)
- Demand signals: search interest vs scraped activity (Acuvue index, share of category, Olens index, peak week)
- Monthly trends: brand-named activity over time, brand-quarter table; Anomaly explorer

## 11. Data Notes | Pending (method_page.py, app.py)
- Coverage & method: items collected, pool vs other lenses; brands by channel (thin cells); label standard
- Data coverage & known limitations

## Overlaps to resolve
- Category import change (-25% units): Brand Overview and Combined Summary fact (summary_facts.py). Keep one.
- Share of voice by brand and channel: Brand Overview, Research > Share of Voice, Data Notes "Brands are heard on different channels", plus the data-points card. Keep one chart.
- "Comments & posts" reach panel repeats share-of-voice counts (Brand Overview). Keep one.
- Review/rating and negative share appear in Brand Overview scorecard, Reviews & Sentiment, Brand Health score, Catalog store ranking, Barriers app/store reviews. Assign each number one home.
- Framework barrier chart in Research & Triangulation > Barriers (Acuvue own complaints) AND Barrier Matches (pool of brands): keep one, link the other.
- Complaint topics: Barriers (2), Triangulation barrier-by-brand, Research > -ve and +ve Tail, Reviews 1-2 star. One complaint chart, others link.
- Channel coverage: Data Notes channel table, Research > Channel Coverage, Data Notes limitations. Keep one (Distribution Gap is a gap pill, not a chart).
- Google Maps/store reviews: Retailers (Google Maps) friction view and the Store reviews topic chart, both in Retail & Promotions now. Keep one.
- Hypotheses: Stage 2 bridge (five hypotheses) vs Research Findings hypothesis check. Keep one.
- Post vs comment gap (XHS, Social) vs consumers vs own posts (Brand Health): check same finding.
- Limits box text (HSA, no sales volume) repeats on several pages; keep in Data Notes.
## Off-goal candidates (CLAUDE.md "only data about lenses and the registration barrier")
- RevitaLens (solution) pack prices in Brand protection; Price Intelligence if it prices online lenses (HSA bars online sale); Catalog listing-level price table.
