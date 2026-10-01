# MyACUVUE Singapore: Positioning Against CooperVision, Alcon, Bausch + Lomb and Olens
## Deep-dive report (evidence triangulation of four Research runs and project scraped data)

**Evidence date:** 1 October 2026. **Source IDs:** see [00_source_log.md](00_source_log.md). Research claims are cited `R#-C-##` (run and claim), scraped sources `SC-xxx`.
**Scope:** positioning implications only. Out of scope: regulation and compliance analysis, market sizing, the definition of "eligible trial consumer", action plans, campaign tactics and message copy. Where regulatory facts affect how evidence can be read, they are flagged in one line and not analysed.

**Confidence rubric (as specified).** High = at least two independent source types including one primary or authoritative source, recent, no unresolved conflict. Medium = two sources of the same type, or one primary source uncorroborated, or minor conflicts. Low = single secondary source, dated, anecdotal, inferred or conflicted. Percentages are shown only where the base is at least 30; below that, counts are shown.

**Working hypothesis definitions** (inferred from the runs; H4's wording is the least certain): H1 J&J holds about 36% of the Singapore contact lens market. H2 revenue is rising while volume is flat or falling. H3 retailer bulk-deal incentives work against MyACUVUE registration. H4 app and registration-flow friction is a key drop-off point. H5a marketplace coupons anchor low prices and undercut ECP and MyACUVUE value. H5b cheap solutions and cosmetic lenses on marketplaces are an entry funnel. H5c competitors, including Olens, out-promote J&J on marketplaces.

**Run status.** All four runs are available. Run 1 had no hypotheses. Run 2 (H1, H2) ran 18 of 25 queries. Run 3 (H3, H5a/b/c) was cut short by credits and could not retrieve marketplace pages; H5a and H5c had only two adversarial searches. Run 4 (H4) ran 18 of 25 queries. Hypotheses were therefore tested with less evidence than planned where noted.

---

## Contents
1. Scrape audit (Step 1)
2. Validation of scraped findings (Step 2)
3. Cross-run conflicts and corrections
4. Findings by journey stage and segment
5. Competitor-by-dimension evidence grid
6. Gaps and blind spots (Step 3)
7. Barriers (Step 4)
8. Hypothesis scorecard (Step 5; full table in [3_hypothesis_table.md](3_hypothesis_table.md))
9. Positioning outputs (Step 6): map, messaging territories, strengths, weaknesses and white space
10. Red team (Step 7)
11. UNVERIFIED claims
12. What this analysis cannot tell us

---

## 1. Scrape audit

Counts were re-derived from the databases on 1 October 2026. Documented weaknesses come from SC-INV; additions found during this audit are marked **(new)**.

| Source | What it can support | What it cannot support | Reliability |
|---|---|---|---|
| **SC-APP-GP** Google Play, 95 written reviews (store-wide 3.32 from 1,113 ratings), 2017 to Sep 2026 | Types of friction users report (launch failure, OTP, store-binding, unsubscribe); change over time. | Prevalence of friction. Written reviews average 2.48 against 3.32 store-wide, so they skew negative. The store histogram is bimodal (517 five-star, 351 one-star of 1,113). Zero developer replies. Most of the 42 three-to-five-star reviews are a few words long ("Good", "Nice"), so positive reasons are barely documented (about a dozen explain why, mostly points and redemption) **(new)**. | **Medium** for friction types; **Low** for any rate. |
| **SC-APP-AS** Apple App Store SG, 24 written reviews, 70 ratings (2.36) | Direction of friction; the 2.4 headline rating. | Anything quantitative from n=24. Written reviews average 1.67 against 2.36 across all 70 ratings. Singapore storefront only. This reconciles Run 3's "2.4 from 68 vs 1.67 from 24": different measures, not different storefronts. | **Low** (n=24) |
| **SC-GM** Google Maps, 4,771 reviews, 6 optical chains, 88 outlets | Retail-environment friction themes (staff and fitting, wait, stock, upsell, pricing). | Any brand comparison (no brand field at all). Newest 100 reviews per outlet, 96% rated 4 to 5 stars (4,539 of 4,771), so dissatisfaction is understated. Owndays is 60% of rows (2,853; 41 outlets). Only 199 reviews are clearly about contact lenses (26 with friction; chain n=17 to 94). Visio Optical is one outlet; Nanyang included on weak evidence it sells ACUVUE. | **Low** for brands; **Medium** for friction themes at chain level |
| **SC-LZR** Lazada reviews, 92 (ACUVUE 24, Alcon 38, B+L 30) | Nothing about brand satisfaction. | Brand comparison: CooperVision and Olens absent. Structurally inflated: the collection returned "best"-sorted reviews, five per product; 90 of 92 are five-star (B+L has one 2-star and one 4-star). Mostly solutions, since contact lenses cannot be sold on marketplaces. The inventory says 68 reviews; 24 ACUVUE reviews were added on 1 Oct **(new reconciliation)**. | **Low** |
| **SC-PRD** Lazada and TikTok Shop listings, 143 (23 to 25 Sep 2026) | Online solution promo rates and prices; presence of marketplace lens listings. | Lens prices (51 rows flagged, 40 distinct lens listings, offered not sold). One $0.01 row is bad data. Solution prices are not comparable with lens prices; Olens and CooperVision listings are all flagged lens listings with undefined units. No Shopee. No sales or stock data. | **Medium** for solution promos; **Low** for lens prices |
| **SC-YT** YouTube, 172 videos, 1,256 comments | Topical themes of public video comments; which videos draw attention. | Singapore audience: "SG" is the search geography, not viewer location **(new)**. Brand tags follow search keyword or channel and can be wrong: CooperVision's second-largest video is an ACUVUE OASYS 1-Day video **(new)**. Views are dominated by single videos (ACUVUE: one video is 5.72M of 6.33M views, 90%; Alcon: 7.09M of 17.9M). Olens is 545 of 1,256 comments (43%). Only 65 of 280 MyACUVUE comments are lens-relevant. Barrier counts are raw and include off-topic comments. | **Low** |
| **SC-IG** Instagram, 158 posts, 185 comments | Brand-post engagement. | Brand comparison of consumer talk: 166 of 185 comments (90%) are MyACUVUE, Olens has none by design, B+L has 4. Only 70 of 158 posts are Singapore-relevant. | **Low** |
| **SC-FB** Facebook, 120 brand-page posts, 33 comments | Brand-owned content only. | Consumer sentiment (n=33). No Alcon. Only 4 posts mention app, register or points. | **Low** |
| **SC-RD** Reddit, 57 posts, 95 comments | Illustrative price and where-to-buy questions. | Brand comparison. Brand tags are search keywords and often wrong **(new)**: of 19 posts in Singapore subreddits, 9 are not about contact lenses (an "Alcon" aircon thread, an "Olens" mask thread). Only 35 of 57 posts are lens-relevant; most come from US subreddits (r/contacts, r/optometry); per-brand n is 4 to 8 lens-relevant. | **Low** |
| **SC-KP** KiasuParents, 41 threads, Aug to Oct 2023 | Parent and family topics (comfort, price, fitting); ACUVUE is the most discussed (17). | Current views (3 years old). Brand-level claims (Olens n=3, CooperVision n=5). Child-focused sample. | **Low** |
| **SC-XHS** Xiaohongshu, 711 posts, 156 comments | Themes in Chinese-language lens content; relative attention. | Singapore consumers: only 313 posts are Singapore-relevant and 68 are both Singapore- and brand-relevant. Likes are very concentrated (one Alcon post is 18,885 of 25,247 brand-relevant Alcon likes). Sentiment among the 68 Singapore-and-brand posts is n=12 to 20 per brand (below the floor). 40 comments are untagged. | **Low** |
| **SC-GT** Google Trends SG | Relative search interest for "Acuvue" and "Olens"; year-on-year change. | Competitor lines: Biotrue, Dailies Total30 are zero; Air Optix 4 non-zero weeks; others too sparse. Index, not volume. "Acuvue" is also the generic query for the category leader and may include app or promotion lookups **(new)**. | **Medium** for Acuvue and Olens; **Low** otherwise |
| **SC-CT** UN Comtrade HS 9001.30 | Supply-side trade flows. | Local consumption. Singapore is a manufacturing and re-export hub (exports are about twice imports). | **High** as a record; **Low** as a demand proxy |

**Brand-partial sources that cannot support brand comparisons:** SC-LZR (no CooperVision, no Olens), SC-FB (no Alcon), SC-IG comments (90% one brand), SC-GM (no brand dimension), SC-GT (competitor lines sparse), SC-KP (3 to 5 threads for three brands).
**Structurally inflated ratings:** SC-LZR (best-sorted, 98% five-star) and SC-GM (newest 100, 95% four to five-star). **Structurally deflated:** SC-APP written reviews.
**Too small for brand-level claims:** SC-RD, SC-FB comments, SC-KP, SC-XHS sentiment, SC-APP-AS.
**Sentiment tagging:** model-assigned (GPT-4o-mini) with no published accuracy check; the project's own barrier-list check was 78% fully correct on 40 comments (SC-INV). Journey stage is a static per-source lookup, not a per-row classification, so "barriers peak at stage X" is an artefact **(SC-INV)**.

---

## 2. Validation of scraped findings against the Research runs

"Independent" means a source type or underlying source that does not share data with the scraped finding.

| # | Scraped finding | Verdict | Conf. | Evidence for | Evidence against / limits |
|---|---|---|---|---|---|
| V1 | App friction concentrates on launch, update and sign-up. Project coding: 47 of 77 one-to-two-star reviews. My keyword pass on all 77 gives a similar direction (launch, update or freeze about 22; OTP, login or registration 14; date-of-birth entry 7, all 2017 to 2018; unsubscribe, spam or privacy 7; retailer lock-in or redemption 6 as primary theme). SC-APP | **Corroborated** (types, not prevalence) | Medium | R4-C-04 (OTP failures, 2022 to 2025); R4-C-03, R4-C-05, R2-C-14, R3-C-14 (brand rules: Singapore mobile number, NRIC/FIN, Singapore store region, 1,000-point cap, scan at store). | R4's app-review reading uses the **same reviews**, so it is not independent. Independent support is the brand's own rules, which show where friction can arise, not that it does. Play histogram: 46% five-star. Social and forum talk about the app is near zero (R4 searches; SC-RD, SC-KP, SC-FB). Written-review skew. |
| V2 | MyACUVUE app written ratings fall from about 3.0 (2017 to 2020) to 1.1 to 1.4 (2024 to 2025). 11 low-star Play reviews cite version 3.8.4 (Dec 2023 to Apr 2024) | **Partly corroborated** | Low | R4-C-15 (release notes always "Bug fixes and enhancement"; Play last updated 31 Aug 2026). | 2026 has only 3 written reviews, so recovery is untestable. Overall rating is not split by period. |
| V3 | Retailer lock-in and points freezing: store-binding, redemption problems | **Corroborated** | Medium | R4-C-11, R4-C-13, R3-C-14 (points at one "My Optical Store", staff scan); Alcon is also store-locked (R2-C-17, R4 grid). | Mechanism High (brand pages). Complaint prevalence unknown (about 6 to 15 of 77). Store-binding is a category norm, so it is not MyACUVUE-specific (R4 section 7). |
| V4 | Olens leads share of voice: 43% of YouTube comments (545/1,256); 39% of brand-relevant Xiaohongshu likes (37,673 of 95,562; 43% on the narrower Singapore-and-brand-relevant set); Acuvue and Olens have similar Google Trends interest | **Partly corroborated** | Medium for attention; not testable for sales | R2-C-06 (cosmetic lenses are the growth driver, Euromonitor); R3-C-24 (74% of TikTok lens videos decorative); R4 grid (Olens SG app, deep discounts). | R2-C-25: no official Olens Singapore store or distributor; reach is cross-border and via resellers. YouTube audience is not Singapore-specific; XHS likes are concentrated. Attention is not market share. |
| V5 | ACUVUE search interest +56% year on year (Jan to 20 Sep); my recomputation +60%; category +22% (recomputed +25%) | **Partly corroborated** | Low | R2-C-01 (share 34% to 36% in 2025); R2-C-12 (OASYS MAX 1-Day for Astigmatism launched Feb 2026); SC-YT: the 5.7M-view MAX Astigmatism video was published 21 Jan 2026. | Euromonitor covers 2025, not 2026. Low-volume branded terms; generic "Acuvue" lookups. Cause (launch, app, ads) unknown. |
| V6 | Bausch + Lomb is more promotional online: 7 of 25 B+L solution listings on promotion (7 of 11 on Lazada, mean 36.8% off) vs 1 of 26 ACUVUE (the project plan quotes 7 of 34 vs 1 of 26 on a wider B+L set) | **Corroborated** (direction) | Medium | R3-C-06 (B+L Capitol tiers 9%, 17%, 22% against ACUVUE 7%, 15%); R3-C-13 (Hirocon 16% to 21%, Brighteyes 18% to 25%); R2-C-22; R4 grid (LACELLE gift campaign). | Different channel and product: scraped data is online solutions, runs are retail lenses. Online-only (SC-INV). |
| V7 | Olens is low-priced: TikTok Shop listings mean S$11.75 (S$5.22 to S$31.11, n=20) | **Partly corroborated** | Low | R2 grid (S$35.90 per monthly pair; USD 11.50 to 23 per 10-day lens box); R3-C-20 (34% to 61% off list; reseller buy-one-get-one); R4 grid ("$10 for monthly", "98% off first order"). | Range S$5 to S$36 per listed unit; unit (pair, box) undefined in listings; promotions versus list price; Olens distributor claims UNVERIFIED (R2, R3, R4). Cause of range: unit, date, discount. |
| V8 | 40 distinct lens listings offered for direct online sale (7 ACUVUE; Olens 20 listing rows) | **Corroborated** (existence) | High | R2-C-26 and R3-C-17 (authorities state online lens sales are not permitted; 171 listings removed in 2025). | Offers, not sales. Whether sellers are authorised is not known. No regulatory analysis performed (out of scope). Affects reading of every marketplace finding. |
| V9 | Imports of HS 9001.30 fell 25% in units and 23% in value 2023 to 2025 (189.9M to 143.1M units; USD 314.4M to 241.7M) | **Corroborated** (as data) | High as data; not testable for local demand | R2-C-08 (2023 to 2024 same figures); R2-C-09 (hub). | The fall is all in 2024 (-25.6% units); 2024 to 2025 units are flat (+1.3%) and value -1.7%. Exports also fell (349.7M to 211.4M units). Not a demand series. |
| V10 | Retail friction themes (262 of 4,771 reviews, 5.5%): staff and fitting (67 single-theme), wait (47), stock (25), upsell (24), pricing (22). Contact-lens subset 26 of 199: wait 6, stock 5, staff and fitting 4, upsell 3 | **Partly corroborated** | Low | R4-C-10 (fitting scan "under 1 minute"), R3-C-02 (free teaching depends on 2 boxes), R4-C-09, R1-C-07 (ECP influence). Loyalty or points is mentioned in 1 of 262 friction reviews, which matches R3-C-14 (points live in the app, not at the till). | Chains, not brands. Newest-100 sampling. Contact-lens subset is small. |
| V11 | Lazada reviews are 91% positive | **Not testable / rejected** | n/a | none | Structural bias (section 1). Should not be used for brand comparison or satisfaction. |
| V12 | YouTube barrier flags by brand (Alcon 51/160, B+L 42/227, MyACUVUE 23/280) | **Not testable** | n/a | none | Raw, include off-topic comments, no rate, brand mis-tags. |
| V13 | KiasuParents: ACUVUE is the most discussed brand (17 of 41 threads); 9 of 17 mixed or negative; themes comfort, pricing, comparison with Malaysian brands (Biomedics) | **Partly corroborated** | Low | R1-C-24 (discomfort and dryness lead dropout); R4-C-06 and R4-C-12 (Malaysia price comparison). | 2023; n=17; family-oriented; a thread about Kuala Lumpur appears in ACUVUE counts. |
| V14 | Singapore Reddit lens posts are about price and where to buy ("Where to buy cheap contact lenses?" 2023; "price of contact lens" 2024; brand recommendations 2020 to 2023) | **Corroborated** (theme) | Low | R3-C-21, R4-C-06, R4-C-12 (price and channel comparison). Adds Reddit evidence where R4's own Reddit searches returned nothing (a retrieval limit, not absence). | About 10 relevant Singapore posts; no app discussion in them. |
| V15 | Xiaohongshu themes in Singapore-and-brand posts: recommendation 37, value 23, price 22, comfort 18, colour 13, authenticity 7 | **Partly corroborated** | Low | R1-C-08 (Gen Z cites appearance), R4 language list (cosmetic: natural look, affordable). | Theme counts are model-tagged on a small base; Chinese-language content in Singapore context is thin in all runs. |
| V16 | Instagram engagement concentrates in MyACUVUE (20 posts, 9,774 likes; Alcon 8 posts, 0 likes; Olens 0 posts) | **Not testable** | n/a | none; no run measured brand engagement. | Concentration in one post (8,009 likes). Brand-owned content. |

**Pattern.** Scraped findings that survive validation are about **friction types** (app, store-binding, retail environment), **price and channel talk**, and **Olens attention**. Scraped brand comparisons built on ratings or sentiment (Lazada, YouTube, Instagram, Facebook, Reddit) do not survive the audit.

---

## 3. Cross-run conflicts and corrections

Conflicts are shown as ranges with a likely cause; none are averaged.

| Topic | What each source says | Resolution and confidence |
|---|---|---|
| **J&J myopia control in Singapore** | Run 2 grid: "myopia control: no Singapore evidence found" and "J&J shows no Singapore myopia-control presence". Run 1 (R1-C-12; J&J press release 8 Dec 2022 and Singapore pages), Run 3 grid (Capitol lists Abiliti 1-Day at S$83) and Run 4 grid (Abiliti Singapore page, Facebook page) say Abiliti 1-Day launched in Singapore in December 2022, with Abiliti Overnight (ortho-k) CE-marked. | **Availability is established (High):** brand pages from three runs plus a retailer listing. Run 2's statement is a search gap and is **superseded**. Efficacy evidence for Abiliti is Low (sponsor-sourced; R1-C-32, K6). The Run 2 "white space" about myopia control is therefore wrong as stated. |
| **Alcon Singapore consumer programme** | Run 3: none found (C-29). Run 2 (C-17) and Run 4 (grid, 9b): Alcon Reward Program 2026 with e-stamps. | **Programme exists (Medium):** one primary brand page found by two runs (not independent). Run 3 miss caused by credit cut-off. |
| **Bausch + Lomb consumer programme** | Run 2 (C-23): none found. Run 4: time-limited gift-with-purchase (LACELLE S$20 Sephora e-gift for 6 boxes, 1 Oct to 31 Dec 2025). | Compatible: **campaigns, not a standing programme** (Medium). |
| **Olens loyalty** | Run 2: none in Singapore. Run 4: Olens Singapore app (first version 18 Dec 2025, one rating) and a global online membership not valid in physical stores. | Run 2's "no cosmetic brand runs a local loyalty scheme" is **partly outdated** (Medium). The app is nascent and one-rating. |
| **CooperVision prices and programme** | Run 3: no in-window prices; no programme. Run 2 gives Capitol prices (clariti S$65, MyDay S$79); Runs 2 and 4 find a time-limited GrabGift campaign (1 Aug to 31 Oct 2026). | Run 3 shortfall (credits). Campaign-based only (Medium). |
| **MyACUVUE welcome reward** | S$20 (retailer pages), S$30 (2018 forum), S$40 (referral link), up to S$60 (brand page). | Range S$20 to S$60 (Medium). Cause: different campaigns, referral versus organic, "up to" wording, undated retailer pages. |
| **Birthday multiplier** | 2x (brand FAQ read by R4) vs 1.5x (referral site; R2). | Range 1.5x to 2x (Low). Cause: programme change over time; referral site may copy older terms. |
| **MyACUVUE app rating** | 2.4 from 68 to 70 ratings (App Store); 1.67 from 24 written reviews; Play 3.32 or 3.4 store-wide; 2.48 from 95 written. | Resolved as different measures (section 1). Medium. |
| **H2 volume** | Euromonitor 2024: volume and value growth (R2-C-05); trade data 2024: units down 26% (R2-C-08, SC-CT); 2025: flat. | Range "growing" to "-26%". Cause: different measures (retail sales versus supply-chain flows in a hub). Low. |
| **Singapore market size** | USD 20.6M to USD 405.9M (R2-C-04). | Out of scope (market sizing). Not used. |
| **Olens price per unit** | S$12 (early 2023), S$35.90 (2026 reseller), about S$50 (2025 blog, UNVERIFIED), S$11.75 (TikTok listings mean). | Range S$12 to S$50 (Low). Cause: pair versus box, promotion versus list, date. |
| **Free teaching sessions** | Teaching free only with 2 or more boxes at one chain (R3-C-02; R4-C-09, same Lemon8 post family). | Single source family, Low. |

---

## 4. Findings by journey stage and segment

Segments: **EW** existing wearers, **NW** new wearers, **AC** active considerers (including glasses-only wearers, cosmetic-lens considerers; parents of children with myopia are tagged "segment not identifiable, parent" because they sit outside the three defined segments). Most behavioural evidence is non-Singapore; this is marked "non-SG".

### 4.1 Awareness
- **EW.** Product news draws attention: the OASYS MAX 1-Day for Astigmatism video is 5.72M views (SC-YT, one video, 90% of ACUVUE views), the same launch Euromonitor dates to February 2026 (R2-C-12, Medium). Search interest in "Acuvue" rose 56% year on year (SC-GT, Low). Confidence Low overall: global video, single measure.
- **NW.** No Singapore evidence. Direct-to-consumer brands reach some via Instagram ads (R4-C-02, Low).
- **AC.** Cosmetic: Olens has the most visible attention (V4). Coloured lenses are the category's stated growth driver (R2-C-06, Medium). Of TikTok lens videos 74% were decorative and 3.5% mentioned seeing an eye professional (R3-C-24, Low; 2022). Glasses-only wearers: interest is high but few are told they are candidates (R1-C-02, Medium, non-SG, industry-commissioned). Parents of children with myopia meet options through provider content (R4-C-07, Low).

### 4.2 Engagement
- **EW.** MyACUVUE is the only always-on, app-based membership in Singapore: 10 points per S$1, VIP tier, lifestyle rewards, a staff app (MyACUVUE PRO) (R2-C-13/14, R3-C-14, R4-C-03/11; **High** for mechanics). Alcon runs a 12-month e-stamp card, CooperVision and B+L run time-limited campaigns (R2-C-16/17, R4 grid). Registration is gated: Singapore mobile number and OTP, NRIC/FIN, named residency or pass types, Singapore store region (R4-C-03, High). Points are capped at 1,000 until the profile is complete (R4-C-05, R3-C-14). Verification and login failures recur in reviews (V1, R4-C-04). Release notes are uninformative (R4-C-15, High as a listing fact).
- **NW and AC.** No evidence of how these segments reach the app. Social posts rarely mention it (SC-FB 4 of 120 posts; SC-IG 31 of 158 brand posts).
- **Retailer-owned alternatives** occupy engagement too: MyCapitol Rewards, Better Vision Subscribe & Reward (R3-C-09/10, Medium), and online retailers offering reorder reminders over SMS or WhatsApp (R4-C-16, Medium). No brand-level WhatsApp reorder programme was found for any of the five brands.

### 4.3 Consideration
- **EW.** Wearers compare total cost across channels, not only brands (R4-C-06, Medium; R3-C-21, Low; SC-RD "Where to buy cheap contact lenses?"). Examples: S$330 in Johor Bahru against S$420+ in Singapore for an annual supply (single post, Low). ACUVUE is described as comfortable but expensive (SC-KP; R4 voice table). Daily-disposable use is rising globally and cost drives country differences (R1-C-21, Medium, non-SG).
- **NW.** Fear of infection and of the lens "rolling behind" the eye delays first wear (R4-C-08, Medium; consistent with R1-C-06 fear of touching the eye as the leading barrier in a UK survey, Medium, non-SG).
- **AC.** Glasses-only wearers cite lack of an ECP prompt and handling anxiety (R1-C-02/06/07, Medium, non-SG, industry-commissioned). Cosmetic considerers face very low price points and few professional prompts (V7, R3-C-24). Parents: safety and hygiene concern, ECP default to spectacles or atropine, cost (R1-C-09/10/11, Medium, non-SG except SNEC statements; R4 voice: S$640 for a myopia-control lens, pre-window).

### 4.4 Trial
- **NW.** Handling difficulty persists after teaching (R4-C-08, Medium). Teaching may be tied to bulk purchase at one chain (R3-C-02, R4-C-09, Low). Fitting quality is a trust issue (R4-C-10, Low). New-wearer first-year retention is about 74% to 78% (UK), and for 71% of dropouts no alternative lens was tried (R1-C-14, Medium, non-SG). J&J supplies free trial lenses and runs a collector-set promotion through about 110 stores (R3-C-15, Medium).
- **EW, AC.** No Singapore evidence. Asia-Pacific consensus recommends trial-lens fitting for myopia-control lenses (R1-C-34, Medium, sponsor-funded).

### 4.5 Purchase
- **EW.** Price tiers: ACUVUE OASYS MAX 1-Day S$90 list per 30; PRECISION1 and clariti 1 day sit about S$15 to S$25 below at the same retailer (R2 section 4b, Medium; prices undated). Bundles of 4 and 8 boxes save about 7% and 15% on ACUVUE at Capitol; B+L's tiers go to 22% (R3-C-06, Medium). Points accrue only on purchases at the member's chosen store (R4-C-11, **High**). Purchases are also made in Johor Bahru (often via WhatsApp) and from online retailers (R4-C-12, Medium; R3-C-21, Low). That earns no points.
- **NW.** Owndays' own-brand clear lenses cost about S$1.00 per lens against about S$2.03 for ACUVUE 1-Day Moist (R3-C-01, C-04; Medium). Welcome reward of S$20 to S$60 is redeemed in store (R2-C-13, R4).
- **AC.** Cosmetic lenses at S$5 to S$36 per listing unit online (V7) sit outside the ECP channel (V8). Daily Vanity and resellers market Olens as affordable (UNVERIFIED).

### 4.6 Repeat / Retention
- **EW.** Discomfort and dryness are the leading reasons established wearers stop (R1-C-24, C-25; Medium, non-SG; one Singapore dry-eye survey, OR 2.96 for lens wear). Up to 74% of dropouts can resume with an alternative (R1-C-26, Medium). SC-KP threads show comfort and dryness complaints about ACUVUE (V13, Low). Store-binding, points freezing when a store relocates, and a Johor Bahru switch (R4-C-13, Medium). Users call the app "basically a points tracker" and ask for prescription history and replacement reminders (R4-C-14, Low to Medium; SC-APP 2018 and 2020 requests).
- **NW.** Same dropout mechanisms; first weeks matter most (R1-C-14, Medium, non-SG).
- **AC.** Not applicable (no purchase yet).
- **Evidence for digital reminders improving behaviour is weak** (R1-C-04, C-05; Low): no randomised evidence found.

---

## 5. Competitor-by-dimension evidence grid

Each cell: finding, claim IDs, confidence. "NEF" = no evidence found (in the window, Singapore). Dimensions: A product innovation, B price and value, C ECP and retailer, D digital engagement and loyalty.

| Brand | A. Product innovation | B. Price and value | C. ECP and retailer | D. Digital and loyalty |
|---|---|---|---|---|
| **MyACUVUE (J&J)** | OASYS MAX 1-Day family; astigmatism and multifocal-for-astigmatism launched Feb 2026 (R2-C-12; Medium; launch date from a paywalled snippet). Abiliti 1-Day available since Dec 2022 (R1-C-12, R3 grid; **High** for availability); Abiliti efficacy evidence **Low** (R1-C-32). DEFINE cosmetic range (R2). "First and only" claims UNVERIFIED. | Premium: MAX S$90 list, S$76 to S$87 sold (R2 4b, R3-C-04; Medium). Bundle savings 7% to 15% (R3-C-06). Seen as expensive in Singapore; Johor Bahru about 20% cheaper in one post (R4-C-06; Low to Medium). | Widest participating network seen: about 110 stores in CORTIS promotion, MAX Fitters, MyACUVUE PRO (R3-C-15, Medium). Points only at designated store (R4-C-11; High). Chain-level friction: wait, fitting (V10, Low). | Only always-on membership (R2-C-13/14, R4 9b; **High** mechanics). App 2.36 (70 ratings) and Play 3.32; OTP, store-binding, low perceived value (V1, V3; **Medium**). Opaque release notes (R4-C-15, High). |
| **CooperVision** | MiSight 1 day sold in Singapore since 2019; strongest randomised evidence, Singapore trial site (R1-C-31, R2-C-15; Medium, sponsor-run). MyDay MiSight not yet in Singapore (R1-C-13, R2-C-15; Medium). | Mid to premium: clariti S$65 (S$44.50 elsewhere), MyDay S$79, Biofinity 6-pack S$77 (R2 4b; Medium). | Practitioner-led; funded Asia-Pacific myopia consensus statement (R1-C-34, Medium); Capitol-exclusive campaigns (R2, R4). | Time-limited GrabGift receipt-upload campaign Aug to Oct 2026; buy 5 get 1 (2025); no app (R2-C-16, R4; Medium). |
| **Alcon** | DAILIES TOTAL1, PRECISION1 (made in Singapore), no Singapore myopia-control or cosmetic evidence (R2-C-18/19). | PRECISION1 S$62 per 30; TOTAL1 S$55 to S$80 (R2 4b, R3-C-05). | Reward free box redeemed in the same store; deepest physical tie to Singapore is manufacturing, not retail (R2-C-17/19, R4). | Alcon Reward Program 2026: QR registration, receipt upload, 9-stamp cycle over 12 months (R2-C-17, R4; Medium). MARLO app US-only. |
| **Bausch + Lomb** | ULTRA One Day, Biotrue ONEday, LACELLE; myopia-lens licence, no Singapore launch (R1-C-39, R2-C-22). | Deepest bundle discounts: Capitol 9% / 17% / 22%; Hirocon 16% to 21%; Brighteyes 18% to 25%; Better Vision banner up to 45% (R3-C-06/08/13; Medium to Low). Online solutions promoted (V6). | Capitol, Hirocon, Better Vision, Brighteyes (R3 channel map); Watsons for solutions. | No standing programme; gift-with-purchase campaigns (R4 grid; Medium). |
| **Olens** | Korean cosmetic lenses only, monthly and 1-day (R2-C-24, R1-C-38). No clinical evidence. | Lowest observed price per unit (V7; Low). Deep first-order discounts (R4; Medium). | No official Singapore store or ECP partnership; resellers and cross-border e-store (R2-C-25; Medium). Thailand eye-test-first franchise model (R2-C-25). | Global membership not valid in physical stores; Singapore app (Dec 2025, one rating) (R4 grid; Medium). Social attention highest of five (V4). |

---

## 6. Gaps and blind spots (Step 3)

Ranked by how much each limits the positioning decision.

| Rank | Gap | Why it limits the decision | What would close it |
|---|---|---|---|
| 1 | **No internal funnel data**: installs, OTP success, profile completion, first scan, store-change requests; share of ACUVUE volume bought outside participating stores | H4, the main registration question, is Mixed because public data cannot rank channel leakage against app friction (R4 section 9d) | CRM, registration and app analytics (open item with J&J) |
| 2 | **No ECP or chain-buyer voice** (margins, rebates, scan behaviour, bundle incentives, preferred brands) | H3 is Insufficient; every ECP-influence finding is inference or non-Singapore, industry-funded (R1-C-35, R3 evidence note) | Interviews with chain buyers and independent optometrists; outlet-level scan versus sales data |
| 3 | **No Singapore consumer survey with barrier attribution and brand perception** | The perceptual map is built on brand promise and observed behaviour, not on how Singapore consumers perceive brands; barrier ranking by segment is inferred | The barrier-attribution survey (open item) with brand-image items |
| 4 | **Marketplaces**: no Shopee data; Lazada and TikTok Shop reviews are inflated or absent; no coupon depth or brand-store activity | H5a, H5b, H5c remain Insufficient (R3 could not retrieve pages; our scrape has no Shopee) | Shopee and Lazada brand-store capture; listing-level voucher data |
| 5 | **No Singapore data on new wearers**: first-year retention, dropout reasons, who starts wearing without an ECP | Trial-to-retention barriers rest on UK and US studies | Clinic or chain records; panel of new wearers |
| 6 | **Parents of children with myopia** (outside the three segments) | Myopia control is where CooperVision leads; parent voice is provider-authored; KiasuParents data is 2023 | Parent survey; fresh KiasuParents and HardwareZone pulls |
| 7 | **Competitor consumer voice** for Alcon, B+L, CooperVision in Singapore | Their placement on the map and their programmes' uptake rest on brand pages | Competitor programme enrolment data (not obtainable); Meta Ad Library; consumer interviews |
| 8 | **Time**: most dated consumer posts predate Oct 2023; forum data 2023; Reddit 2014 onward; Lemon8 dates inferred | Current attitudes (post-2024 price rise, 2026 launches) are under-observed | Fresh collection; dated posts only |
| 9 | **Independent clinical evidence for Abiliti 1-Day** | Myopia-control claims for J&J cannot be rated above Low | Peer-reviewed 2- or 3-year data or head-to-head trial |
| 10 | **Channels**: Watsons Optical, independent opticians, Johor Bahru sellers, WhatsApp resellers, Chinese-language and non-English voices | Likely major leakage and discovery routes are seen only through single posts | Mystery shopping; seller interviews; XHS expansion |
| 11 | **A second Singapore share source** for H1 | One paywalled source | Euromonitor tables, panel data |

---

## 7. Barriers (Step 4)

Only evidence rated Low or better in the validation steps is used. "Multi-source" means at least two independent source types (for example, a consumer post, a retailer or brand page, a study). Most barrier evidence is non-Singapore unless marked. Where a barrier was tested against scraped data, the scraped source is named.

### 7.1 Consideration to Trial

| Segment | Barrier | Backing | Type |
|---|---|---|---|
| **AC (glasses-only)** | **Fear of touching the eye and handling anxiety** | R1-C-06 (UK retailer survey, Pakistani hospital survey, 2000 practitioner study; Medium, non-SG) plus R4-C-08 (Singapore consumer posts of first-timers; Medium) | **Multi-source** (surveys plus Singapore consumer voice); Medium |
| **AC (glasses-only)** | **No professional prompt** | R1-C-02/07 (US industry survey and a multi-country brand release; Medium) | Single source family; non-SG, industry-commissioned. Not corroborated by scraped data |
| **AC, EW** | **Total cost versus other channels** (online and Johor Bahru) | R4-C-06 and R4-C-12 (forums, Lemon8; Medium), R3-C-21 (Low), SC-RD (price and where-to-buy posts, Low), SC-KP (pricing topic in 7 of 41 threads), SC-GM (pricing in 22 of 262 friction reviews) | **Multi-source** (consumer forums, scraped forums, retailer reviews); all anecdotal secondary, so Medium |
| **AC (cosmetic)** | **Few barriers: easy access outside ECPs** | SC-PRD (lens listings including Olens 20), R3-C-20, R4 grid, R2-C-25 | Multi-source that access is low-friction (Medium); whether this displaces the ECP path is not shown (H5b) |
| **AC (parents)** | **Safety, hygiene, handling doubts; ECP defaults to spectacles or atropine; cost** | R1-C-09/10/11 (SNEC statements, surveys; Medium), R4-C-07 (provider content, Low), R4 voice (S$640, pre-window) | Mostly single source type (institutional and survey); Singapore parent voice thin |
| **NW** | **Bulk-conditioned teaching and fitting quality** | R3-C-02, R4-C-09/10 | **Single source family** (Lemon8 posts), Low |

### 7.2 Trial to Repeat / Retention

| Segment | Barrier | Backing | Type |
|---|---|---|---|
| **NW, EW** | **Discomfort and dryness** | R1-C-24/25 (multiple peer-reviewed and trade sources, one Singapore dry-eye survey; Medium), SC-KP (comfort the most common topic; ACUVUE 9 of 17 mixed or negative) | **Multi-source** but Singapore evidence is thin and 2023; Medium |
| **NW** | **Vision problems (especially toric and multifocal), handling, early-weeks drop; no alternative tried (71% of dropouts)** | R1-C-14/15 (UK chart review, prospective registry, Spanish survey; Medium) | Single source type (peer-reviewed non-SG studies); not tested in Singapore |
| **EW** | **Purchase leaves the participating store** (Johor Bahru, online retailers, marketplaces), so registration earns nothing | R4-C-11 (High: points only at chosen store), R4-C-12, R4-C-13, R3-C-21, SC-RD, SC-KP (Malaysia comparison threads) | **Multi-source** (brand rules, forums, social posts); Medium. Prevalence unknown; J&J share rose 34% to 36% in 2025 (R2-C-01), which tempers it |
| **EW** | **Store-binding and points freezing** | R4-C-11/13 (High mechanic), R3-C-14, SC-APP (consumer reviews) | **Multi-source** (brand rules plus consumer reviews); R4 and SC-APP share underlying reviews. Medium |
| **EW** | **OTP, login and update failures** | SC-APP, R4-C-04 (same reviews), brand rules (R4-C-03) | Effectively **one consumer source** plus rules; Medium for existence, Low for prevalence |
| **EW** | **Low perceived app value** (no history, no replacement reminders) | R4-C-14 (Low to Medium), SC-APP 2018 and 2020 requests | Single source (app reviews). Low |
| **EW** | **Retailer-owned loyalty and recall compete for repeat attention** | R3-C-09/10/12 (Medium) | Single run (retailer pages); not tested with consumers |
| **EW** | **Price-driven re-use of dailies** | R1-C-22 (four-country survey; Low) | Single source, non-SG |
| **EW** | **Retail environment: waits, fitting quality, upsell** | SC-GM (26 of 199 contact-lens reviews), R4-C-10 | Two sources of different type, small; Low to Medium |

**Single-source barriers (not to be treated as established):** no-professional-prompt, bulk-conditioned teaching, low perceived app value, retailer-owned loyalty competition, price-driven re-use, new-wearer vision problems (non-SG).

---

## 8. Hypothesis scorecard (summary)

Full evidence for and against, and IDs, are in [3_hypothesis_table.md](3_hypothesis_table.md).

| H | Claim | Verdict | Confidence | Evidence level |
|---|---|---|---|---|
| H1 | J&J about 36% share | **Supported** | Medium | One paywalled primary source (retail value, lenses plus solutions, 2025). No scraped test |
| H2 | Revenue up, volume flat or falling | **Mixed** | Low | Value growth supported; volume claim contradicted for 2024 by Euromonitor and unresolved for 2025; trade data (flat units 2025) is hub-distorted. Run 2 had 2 of 3 planned disconfirmation searches |
| H3 | Retailer bulk deals work against registration | **Insufficient evidence** | Low | Mechanism observed; no incentive, rebate or scan data; J&J co-promotions run against it; competitors' programmes are also bulk-triggered. Tested with less evidence (Run 3 cut short) |
| H4 | App and registration friction is a key drop-off | **Mixed** | Medium | Friction real; whether it is *the* key drop-off is not shown; channel leakage may be as large. App-review evidence is one underlying source; no funnel data |
| H5a | Marketplace coupons anchor low prices | **Insufficient evidence** | Low | No marketplace coupon data. A narrower claim (consumers anchor on non-ECP channels such as Johor Bahru and online retailers) is partly supported (Medium) |
| H5b | Cheap solutions or cosmetic lenses are an entry funnel | **Insufficient evidence** | Low | Cosmetic wearers numerous and new to lenses; no evidence of movement into ECP-fitted lenses; solutions look like a follow-on purchase |
| H5c | Competitors, including Olens, out-promote J&J on marketplaces | **Insufficient evidence** | Low | No marketplace brand-store comparison; Olens leads social attention (Medium); B+L more promotional online solutions (Medium) |

---

## 9. Positioning outputs

### 9a. Perceptual map

**Important limit.** This map places brands by what each *promises and structures* in Singapore (brand pages, programmes, channels, price and promotion observed). It is not a map of consumer perception: no Singapore consumer brand-perception data exist in any source. Treat it as an evidence-based positioning hypothesis for a consumer survey to test.

**Candidate axes (from Run 2 section 4d plus evidence from Runs 1, 3, 4 and scraped data):**
1. Eye-health and clinical promise versus appearance and fashion promise.
2. Monthly cost of wear (modality-driven).
3. Channel anchoring: ECP-bound versus direct-to-consumer.
4. Loyalty depth: permanent membership versus episodic promotion.
5. Prescription complexity across life stages.

**Chosen axes**
- **X: eye-health and clinical promise (0) to appearance and fashion promise (10).**
- **Y: open-market and transactional (0) to ECP-anchored, structured relationship (10).** This merges candidates 3 and 4: in Singapore the loyalty programmes of J&J and Alcon are bound to a designated optical store (R4-C-11, R2-C-17), CooperVision is practitioner-led, B+L competes on retailer bundles and Olens reaches buyers through cross-border and reseller channels. Channel anchoring and loyalty depth move together, so one axis carries both.

**Why these two.** They separate the five brands more than any alternative, they match the segment structure (glasses-only and cosmetic considerers versus ECP-fitted wearers), they are the axes on which Runs 2, 3 and 4 independently found the clearest contrasts, and each placement has at least a brand page or retailer source behind it.

**Rejected axes.** *Monthly cost:* price is set by modality more than by brand (R2 4b; a monthly reusable at S$21 to S$26 per month against a daily silicone hydrogel at S$110 to S$212), prices are undated and retailer-specific, and brand spreads within the daily tier (S$15 to S$25 per box) are within bundle discount effects. *Prescription complexity:* describes portfolio breadth rather than a position, and five-brand placement evidence is thin (B+L, Olens none). *Loyalty depth on its own:* collapses into Y and has no evidence for Olens in stores or B+L.

**Placements** (scale 0 to 10; the range reflects the evidence spread, not statistical error)

| Brand | X (clinical to appearance) | Y (transactional to ECP-anchored) | Evidence note | Confidence |
|---|---|---|---|---|
| **MyACUVUE** | 2 (range 1 to 4) | 8 (range 7 to 9) | X: MAX tear-film and light-filter claims, Abiliti availability, Define cosmetic line a minor offset (R2-C-12, R1-C-12). Y: only always-on, store-bound membership, PRO app, widest participating network (R3-C-15, R4-C-11). Channel leakage and app friction mean the lived position is weaker than the design (V1, V3). | X Medium; Y Medium |
| **CooperVision** | 1 (range 0 to 2) | 6 (range 4 to 8) | X: MiSight with the strongest randomised evidence and a Singapore trial site (R1-C-31). Y: practitioner-led site, Capitol-exclusive campaigns, but only time-limited consumer programmes (R2-C-16, R3-C-28). | X Medium; Y Low |
| **Alcon** | 3 (range 2 to 4) | 7 (range 5 to 8) | X: comfort and moisture claims, no myopia-control or cosmetic evidence (R2-C-18). Y: store-locked 2026 e-stamp programme; retail visibility mostly via stock at chains (R2-C-17, R3-C-29). | X Low; Y Low |
| **Bausch + Lomb** | 3 (range 2 to 5) | 4 (range 2 to 6) | X: ULTRA comfort claims and a LACELLE cosmetic line; no clinical programme in Singapore (R2-C-22, R1-C-39). Y: deep bundles in many chains plus Watsons for solutions, campaigns rather than a programme (R3-C-06/13, R4 grid). | Low |
| **Olens** | 9 (range 8 to 10) | 2 (range 1 to 4) | X: cosmetic-only Korean positioning (R2-C-24, R1-C-38); attention highest of five (V4). Y: no official Singapore store; cross-border and resellers; online-only membership (R2-C-25, R4 grid). | X Medium; Y Low |

**Reading the map.** MyACUVUE and CooperVision occupy the clinical, ECP-anchored quadrant; CooperVision leans clinical (myopia control) while MyACUVUE leans structured relationship (membership). Alcon sits close to MyACUVUE on the structure axis, with a thinner Singapore consumer presence. B+L spans the middle on price-led bundles. Olens holds the opposite corner and its position does not overlap with the others except through ACUVUE DEFINE. Rendered visual: [perceptual_map.svg](perceptual_map.svg) and the published Artifact.

### 9b. Messaging territories by segment and stage

"Territory" means a theme MyACUVUE could credibly own relative to competitors on the evidence available. It is a positioning claim, not message copy.

| | Awareness | Engagement | Consideration | Trial | Purchase | Repeat / Retention |
|---|---|---|---|---|---|---|
| **Existing wearers** | **Precision for complex prescriptions** (astigmatism, multifocal-for-astigmatism). Competitors have comparable ranges (R2 4c), so ownership is not exclusive; ACUVUE launch attention (V5). **Low** | **The only standing, always-on membership.** Structurally unique (R2-C-13, R4 9b; High). Credibility limited today by friction (V1) and low perceived value (R4-C-14). Territory **contested by own execution**. **Medium** (structure) / **Low** (credibility) | **Comfort** is claimed by all four brands in near-identical terms (R2 4c); not ownable. Price: ACUVUE is premium and wearers compare cross-border (R4-C-06): not ownable. **Insufficient evidence** for any other territory | **Insufficient evidence** (no Singapore evidence on EW trial) | **Reward at the optician**: shared with Alcon (store-locked) and retailers' own schemes (R3-C-09/10). Not exclusive. **Low** | **Continuity: reminders, history, replacement tracking.** Users ask for it (R4-C-14); online retailers already offer reorder messaging (R4-C-16); no brand does. White space but **contested by retailers**. **Low to Medium** |
| **New wearers** | **Insufficient evidence** | **Insufficient evidence** | **Professionally guided first fitting.** ECP influence is strong in non-SG surveys (R1-C-07); CooperVision is also practitioner-led (R3-C-28). Shared. **Low** | **Confidence in the first wear (handling, insertion).** Fear and handling are the stated barriers (R4-C-08, R1-C-06/14); no competitor was found owning it; bulk-conditioned teaching at one chain suggests the space is unclaimed (R3-C-02). White space. **Low to Medium** | **Welcome value at the optician** (S$20 to S$60 range). Owndays own-brand at about S$1 per lens undercuts (R3-C-01); contested on price. **Low** | **Staying in lens: find the lens that works** (71% of UK dropouts had no alternative tried, R1-C-14; up to 74% can resume, R1-C-26; non-SG). A refit-oriented range story is available to a broad portfolio. **Low** |
| **Active considerers** | **Cosmetic:** Olens owns attention (V4); MyACUVUE has no visible claim. **Parents:** CooperVision's MiSight is the evidence leader; Abiliti is available but its evidence is Low (R1-C-31/32). Territory for MyACUVUE: **contested; behind on evidence**. **Medium** (that it is contested) | **Insufficient evidence** | **Professionally fitted versus unsupervised access.** Cosmetic lens infections are a documented risk including in Singapore (R1-C-19, Medium) and cheap online listings are widespread (V7, V8). A "fitted by a professional" contrast is available; regulation is not analysed here. **Low to Medium** | **Insufficient evidence** | **Insufficient evidence** | **Not applicable** (no purchase yet) |

### 9c. Strengths, weaknesses and white space for MyACUVUE

| Dimension | Strengths | Weaknesses | White space |
|---|---|---|---|
| **A. Product innovation** | OASYS MAX 1-Day family, with astigmatism and multifocal-for-astigmatism versions (R2-C-12; Medium). Abiliti 1-Day and Overnight available in Singapore (R1-C-12, R3; High availability). Widest range from daily to cosmetic (R3 grid). | Comfort claims are matched by Alcon, B+L and CooperVision (R2 4c); several J&J claims UNVERIFIED (R1 U-1 to U-7; R2 4c). Abiliti evidence is mostly sponsor-sourced (R1-C-32; Low). CooperVision has stronger randomised evidence (R1-C-31; Medium). | Complex-prescription premium dailies (competitors have ranges; ownership not shown). **Not** myopia control as a presence gap (Run 2's claim is superseded): the gap is evidence strength. |
| **B. Price and value** | J&J share rose from 34% to 36% (2025) despite premium list prices (R2-C-01; Medium; lenses plus solutions). Bundle discounts are moderate (7% to 15%) rather than price-led (R3-C-06). | Premium by S$15 to S$25 per box at the same retailer against PRECISION1 and clariti (R2 4b; Medium). Wearers call it expensive and benchmark Johor Bahru and online (R4-C-06, SC-RD, SC-KP; Medium to Low). B+L is more promotional (V6). Owndays own brand about S$1 per lens (R3-C-01). | Not found. Price is the most contested dimension. |
| **C. ECP and retailer** | Widest participating network (about 110 stores in one promotion), MAX Fitters, MyACUVUE PRO (R3-C-15; Medium). J&J funds chain-level promotions (R3-C-15). | Points earn only at one chosen store and depend on staff scanning (R3-C-14, R4-C-11; High mechanics). Store change friction (R4-C-13; Medium). Chains run their own schemes and some are not in the J&J list (R3-C-15). Chain-level service friction (V10; Low). | ECP and retailer voice is absent from all sources (gap 2). Not assessable. |
| **D. Digital engagement and loyalty** | Only always-on membership; points, VIP tier, birthday multiplier, lifestyle rewards (R2-C-13/14, R4 9b; High). | App 2.36 (70 ratings) and Play 3.32; written reviews 1.67 and 2.48; OTP and login failures, update breakage, unsubscribe complaints, store-binding (V1, V3; Medium). Identity gating (NRIC/FIN, Singapore store region) (R4-C-03; High). Opaque release notes (R4-C-15; High). Perceived as "points tracker" (R4-C-14; Low to Medium). | Brand-level reminders, prescription and order history, replacement tracking: requested by users and not offered by any brand (R4-C-14, C-16; Low to Medium), but online retailers already message on reorder. Cosmetic loyalty: Run 2's "no scheme" is partly closed by Olens's Singapore app (Dec 2025; nascent). |

---

## 10. Red team

Top five conclusions, attacked.

**1. "MyACUVUE is structurally ahead (only always-on membership) but experientially behind (app friction)."**
- *Strongest counter:* Alcon's 12-month e-stamp card and retailer-owned schemes (Better Vision up to 32% savings; MyCapitol Rewards) give wearers comparable or better immediate value; "permanent" may not matter. The Play histogram is 46% five-star, so many users are satisfied and the written reviews that drive "behind" are a negative-skewed subset; Run 4 itself found the app is almost never discussed.
- *Would overturn:* funnel data showing high OTP success, completion and scan rates; consumer research showing membership is irrelevant to choice.
- *Evidence already seen pointing that way:* yes (Play histogram; R4 social silence; retailer schemes).
- *Revised confidence:* structural uniqueness **Medium** (unchanged); experiential weakness **Medium for existence, Low for prevalence**. Do not say the app is a major cause of non-registration.

**2. "Purchases leaking outside participating stores may be a larger drop-off than app friction."**
- *Strongest counter:* evidence is a handful of forum, Lemon8 and Reddit posts, partly pre-2023; cross-border buyers may be a vocal minority. J&J's retail value share rose from 34% to 36% in 2025 (R2-C-01), which a large leakage would be expected to depress, although Euromonitor measures Singapore retail only and would not see Johor Bahru sales.
- *Would overturn:* CRM or panel data on the share of ACUVUE volume bought outside participating stores; evidence that leakers register anyway.
- *Already seen:* the share rise points the other way; nothing quantifies leakage.
- *Revised confidence:* that leakage behaviour exists **Medium** (multi-source, anecdotal); that it is the larger drop-off **Low** (R4's own rank-1 Medium is lowered).

**3. "Olens owns the appearance and cosmetic territory; cosmetic lenses are the growth engine, leaving ACUVUE DEFINE a possible entry."**
- *Strongest counter:* social attention (YouTube comments, Xiaohongshu likes) is not Singapore sales, platform audiences are global, one Xiaohongshu post dominates its brand's likes, and Olens has no official Singapore presence (R2-C-25). Olens interest in Google Trends was flat in 2026 (-3% to -0.6%) while category interest rose 22% to 25%, so Olens is not obviously the growth engine. The cosmetic buyer path bypasses ECPs and may never meet MyACUVUE.
- *Would overturn:* Singapore cosmetic sales shares; resale and grey-channel volumes.
- *Already seen:* flat 2026 Olens search interest and the Run 2 absence finding.
- *Revised confidence:* Olens's placement at the appearance end **Medium**; "white space for ACUVUE in cosmetic" **Low**.

**4. "The ECP relationship is the decisive lever for consideration and trial."**
- *Strongest counter:* nearly all evidence is US, UK or Spain and industry-commissioned (R1-C-02/07/35); consumers describe leaving the fitting store for cheaper channels (R4-C-10, C-12); chains run their own house brands and loyalty (R3-C-01/09), so the ECP's interest may not align with the brand's.
- *Would overturn:* Singapore consumer survey on who influences the decision; ECP interviews.
- *Already seen:* yes, all three counters are in the runs.
- *Revised confidence:* **Low** (from the Medium assigned to the underlying non-SG surveys).

**5. "MyACUVUE is behind CooperVision on myopia control for children."**
- *Strongest counter:* Abiliti 1-Day has been available since Dec 2022 (High) and J&J reports three-year data; MyDay MiSight is not yet in Singapore (R1-C-13); SNEC says atropine is now more commonly prescribed than lenses (R1-C-09), and soft myopia-control lenses were 2% to 3.5% of Asian prescribing in a 2022 survey (R1-C-10), so the contested segment may be small and slow.
- *Would overturn:* independent peer-reviewed Abiliti data; Singapore prescriber share data.
- *Already seen:* availability yes; efficacy data are sponsor-sourced.
- *Revised confidence:* "CooperVision leads on evidence strength" **Medium**; "J&J lacks a Singapore presence" **contradicted**; "myopia control is a decisive battleground" **Low** (size unknown).

**Additional challenge to scraped-data conclusions.** The most tempting scraped conclusions (brand sentiment ranking, "ACUVUE has the highest app friction versus competitors") fail because no competitor app reviews exist in the data (Alcon, CooperVision and B+L have no apps; Olens has one rating). Friction is absolute, not comparative.

---

## 11. UNVERIFIED claims (kept separate)

- J&J "first and only" TearStable plus OptiBlue; 94% comfort figure (R2 4c). Abiliti "twice as effective as dual-focus"; 3-year 55.2% no progression; 24-month real-world data; crossover trial versus MiSight "data on file"; Abiliti Overnight quality-of-life (R1 U-1 to U-5).
- Euromonitor's February 2026 launch date for OASYS MAX Astigmatism (paywalled snippet) (R2-C-12).
- MyACUVUE VIP threshold of 6,000 points; whether points expire; whether Student and Dependant Pass holders can register (R2-C-14, R4 section 6).
- Alcon 94% brand loyalty; CooperVision 61% / 42% / 26% survey (R1 U-9, U-10); "6% to 8% rebate redemption" (R3, secondary).
- Olens "official distributor in Singapore", "partnerships with local optometrists", "2015 Singapore entry", "Korea No. 1" (R2, R3, R4).
- B+L "96% moisture after 16 hours", "9% growth versus market" (R2).
- Platform voucher caps of 25% to 30% (R3, affiliate sources).
- CooperVision GrabGift 2026 mechanics (read via snippet).
- Whether lens-listing sellers are J&J-authorised (SC-INV, secondary).

---

## 12. What this analysis cannot tell us

- **Where in the funnel registration is lost.** Without installs, OTP success, profile completion and scan data, we cannot rank app friction against channel leakage or retailer behaviour. H4 is Mixed for this reason.
- **How Singapore consumers perceive the five brands.** The map shows promise and structure, not perception; the three segments cannot be sized or reached from these sources.
- **Whether retailer bundles, rebates or scan habits suppress registration (H3).** No ECP or chain voice exists.
- **Marketplace dynamics (H5a, H5b, H5c).** No Shopee data; no coupon depth or brand-store activity.
- **Sales, share by brand, or volume.** H1 rests on one paywalled source for lenses plus solutions; Singapore volume is unobserved.
- **New-wearer retention and dropout in Singapore**, and **parent decisions on myopia control**, which are inferred from non-Singapore studies and provider content.
- **Competitor programme uptake and satisfaction.** Only the existence of programmes is observed.
- **Present-day attitudes.** Most dated consumer posts are from before October 2023; several dates are inferred.

**Next evidence most worth obtaining (in order):**
1. J&J CRM and app analytics: installs, OTP success, profile completion, first scan, store-change requests, and purchase-channel share by registered member.
2. ECP and chain-buyer interviews, with outlet-level registration and scan data against sales.
3. The barrier-attribution survey, extended with brand-image items and the three segments, to test the map and the barrier ranking.
4. Shopee, Lazada and TikTok Shop brand-store capture with voucher depth.
5. A Singapore new-wearer and parent sample.
6. Independent Abiliti 1-Day evidence and Singapore prescriber data for myopia control.
