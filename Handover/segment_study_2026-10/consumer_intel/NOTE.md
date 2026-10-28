# CURRENT STATE (2026-10-28, final export): read this first; older sections below are partly superseded
Files were re-exported after the YouTube Singapore rule and the Perplexity retry. **Segment-tagged items that count, per source:**

| Segment | YouTube videos (on-topic AND Singapore-signalled) | KiasuParents (in window) | TikTok videos (Singapore-signalled) | AI answers: ChatGPT / Perplexity | Google Trends series |
|---|---|---|---|---|---|
| S1 glasses-only | 0 | 0 | 0 (not searched) | 3 / 2 | 3 |
| S2 dropouts | 0 | 0 | 0 (not searched) | 3 / 3 | 3 |
| S3 part-timers | 0 | 0 | 0 (not searched) | 3 / 3 | 3 |
| S4 surgery choosers | 0 | 0 | 0 | 3 / 3 | 4 |
| S5 students/teens | 0 | 0 | 0 (not searched) | 3 / 3 | 3 |
| S6 over-40s | 0 | 0 | 1 (off-segment: coloured-lens review) | 3 / 3 | 3 |
| S7 sporty | 0 | 0 | 0 (not searched) | 3 / 3 | 3 |
| S8 screen-heavy | 1 | 0 | 2 (1 coloured-lens review, 1 beginner insertion video) | 3 / 3 | 3 |

- **YouTube:** the strict Singapore rule (Singapore word in title/description/tags, or channel country = SG) moved 162 videos to "probable: no Singapore signal". They are still in `social_posts.csv` with that reason; before the rule 7 to 33 videos per segment counted. The pack's list of owner-approved Singapore channels (`market_channels`) is empty, so channels that set no country (most creators) are not counted. Comments are only counted under a counted video: none.
- **Every segment is under 15 on every item-based source.** Read all cells as "no online evidence we could tie to Singapore" (this is not representative).
- **AI answers are not consumer voice.** They are what ChatGPT search (24 of 24 answered) and Perplexity (23 of 24; fresh session, one input-box failure) say in reply to one fixed, brand-free question per segment (3 questions per segment). They show how AI engines describe each segment and which sources they cite; do not count them as consumers.
- **YouTube caveat: its rows are not all about contact lenses, and not verified as Singapore.** Spot-checks found about 1 in 3 videos and comments off-topic (10 of 30 in the first pass, 5 of 15 videos and 8 of 15 comments in the second): glasses and surgery clips, lens-shop promotions, stunts, and chatter comments. Only `scope_status = found` rows are meant to be on-topic, and even those are unreliable. The file keeps every row as the tool produced it; nothing was deleted or relabelled. Use YouTube only as a lead list to read by hand, not as counted evidence.
- Rows from before the YouTube rule (the older counts in the sections below) are superseded; the file contents are current.
- Apify spend in total about US$0.44 (TikTok US$0.096, Instagram US$0.345); Instagram comments (120) are not usable evidence (see below).

---
# MYACUVUE SG: segment pilot, Step 1 (free sources only)

Study `myacuvue-sg`, collected 2026-10-27, exit country Singapore (home IP), depth quick, no Apify (US$0 paid spend).
**This is not representative of Singapore consumers. A cell under 15 items means "no online evidence", not "no such people".**

## Window and filters
- Window: posts and comments from 2024-10-26 to 2026-10-27 (24 months). Older items are dropped (KiasuParents: kept as `out` rows; YouTube: dropped from search and comments).
- Dropped inside the tool: giveaway/contest/promo text; retailer, clinic, optical-chain and brand accounts (word list `voice_filter` in `packs/sg.yaml`); duplicates (same video or post id).
- **Singapore only is NOT fully met.** YouTube can only bias to Singapore (`regionCode=SG`); it cannot filter. In a 15-video sample, 6 or more were not identifiably Singapore (mainland China, Taiwan, US creators). **Superseded by the strict Singapore rule in UPDATE 2026-10-28 (4): YouTube now leaves 1 on-topic Singapore video.** KiasuParents, Google Trends (geo SG) and the ChatGPT/Perplexity questions (en-SG, "in Singapore") are Singapore-scoped.

## Items per segment and source
An item = a YouTube video judged on-topic ("found": a contact-lens word in title or tags), a substantive comment on such a video, a KiasuParents post that is on-topic and in the window, or an AI-search answer. Google Trends is an index (series), not items.

| Segment | YouTube videos on-topic | YouTube comments (substantive, on those videos) | KiasuParents on-topic in window | AI answers (ChatGPT / Perplexity) | Google Trends series |
|---|---|---|---|---|---|
| S1 glasses-only | 22 | 306 | 0 | 1 / 0 (blocked) | 3 |
| S2 dropouts | 17 | 176 | 0 | 1 / 1 | 3 |
| S3 part-timers | 8 | 58 | 0 | 1 / 0 (blocked) | 3 |
| S4 surgery choosers | 9 | 174 | 0 | 1 / 0 (blocked) | 4 |
| S5 students and teens | 19 | 218 | 0 | 1 / 1 | 3 |
| S6 over-40s | 7 | 29 | 0 | 1 / 1 | 3 |
| S7 sporty | 21 | 242 | 0 | 1 / 0 (blocked) | 3 |
| S8 screen-heavy | 9 | 20 | 0 | 1 / 1 | 3 |

Per source: YouTube 346 videos in the table: 265 from segment queries (112 on-topic, 31 probable, 122 out or dropped) and 81 from brand queries (no segment); 1,337 comments; KiasuParents 65 matched posts, 0 usable; AI search 12 answers; Google Trends 8 segment requests.

**Comment counts overstate on-topic voice.** In the sample about 6 of 15 comments were on-topic (the rest are chatter such as "Oh boy!!!", other languages, replies to other commenters). S6 and S8 reach 15 only through comments.

## Spot-check (relevance)
- YouTube, 30 items (15 videos, 15 comments): off-topic 10 of 30 (1 video: a classroom joke matched on a hashtag; 9 comments).
- KiasuParents, 30 of 65 posts: off-topic 12 of 30 (swimming classes, tutoring, clothes, grammar; 2 were spam). 0 are inside the window anyway: 63 posts date from 2009-2012, 2 are WhatsApp spam from 2026-08-06. Newest-first search on the site confirms there are no genuine in-window contact-lens posts.
- AI search, all 15 answers read: 3 were a Perplexity sign-up prompt, not answers (off-topic 3 of 15). They were removed and are BLOCKED; the 12 remaining answer the question asked.
- Google Trends: not item-based, not spot-checked.

## Queries used (English and Chinese; KiasuParents used English only)
- S1: glasses vs contacts; never tried contact lens; afraid of contact lens; 眼镜 隐形眼镜 选择
- S2: stopped wearing contacts; back to glasses; give up contact lens; 不戴隐形眼镜 改回眼镜
- S3: contact lens occasional use; contacts only for events; wear contacts only on weekends; 偶尔戴隐形眼镜
- S4: LASIK vs contacts; SMILE vs contact lens; ICL vs contact lens; 激光近视手术 隐形眼镜
- S5: contact lens for school; first contact lens teen; contact lens for child; kids contact lens myopia; 学生 隐形眼镜
- S6: presbyopia contact lens; multifocal contact lens; reading glasses vs contacts; 老花 隐形眼镜
- S7: contacts swimming; contact lens gym; contact lens running; contact lens badminton; 戴隐形眼镜 游泳
- S8: contact lens dry eyes work; contacts eye strain computer; dry eyes office contacts; 隐形眼镜 干眼 电脑
- Brand queries (rows with an empty `segment`): MyACUVUE, Alcon, CooperVision, Bausch + Lomb, Olens, each with its aliases and the category words. KiasuParents found no brand threads. Rows from segment queries carry brand `Segments (brand-free)` and a `segment` id.
- AI questions: one fixed, brand-free question per segment (in the study file `clients/myacuvue_sg_segments.yaml`); each asked in a fresh chat.

## Sources not run
TikTok videos and comments, Instagram comments (Step 2, see below), Facebook, retail, app reviews, Google Maps: not run. No Apify spend.

## Problems and BLOCKED
- Perplexity: 4 of 8 questions BLOCKED (S1 input box not found; S3, S4, S7 sign-up wall after its free questions). Perplexity selectors were never verified live before; ChatGPT worked for 8 of 8.
- First AI-search attempt crashed (host out of memory); re-run succeeded.
- KiasuParents parser treated "No matches found" as an unreadable page; fixed (real capture added as a test fixture). The segment slot now judges each matched post on its own text and date.
- Google Trends: Latin-script terms only for brand queries (no Chinese spelling known for the brands).

## Step 2 (not run)
Rule: only for a segment with fewer than 15 on-topic items. Counting videos only, S3, S4, S6 and S8 are under 15; counting comments, none is. Because comments are noisy and YouTube is not Singapore-filtered, this needs the owner's decision and a cost estimate before any Apify run.

## Files
- `forum_threads.csv`, `social_posts.csv`, `social_comments.csv`, `search_interest.csv`, `ai_search.csv`: the tool's per-table dump, unmerged and untagged beyond the tool's own `segment` column.
- `gold_set/`: the tool's delivery set (same data, with a data dictionary).


---
# UPDATE 2026-10-28: second pass (more YouTube queries, more ChatGPT questions; US$0 paid)
32 new YouTube queries (4 per segment, about half name Singapore) and 16 new brand-free questions (2 per segment) were added; earlier queries were skipped, not repeated. Files above were re-exported and now include both passes.

| Segment | YouTube videos on-topic (was) | YouTube comments, substantive on those videos | ChatGPT answers (was 1) | Perplexity answers (was 0-1) |
|---|---|---|---|---|
| S1 glasses-only | 33 (22) | 374 | 3 | 1 |
| S2 dropouts | 18 (17) | 73 | 3 | 3 |
| S3 part-timers | 18 (8) | 95 | 3 | 0 |
| S4 surgery choosers | 10 (9) | 204 | 3 | 0 |
| S5 students/teens | 21 (19) | 254 | 3 | 1 |
| S6 over-40s | 9 (7) | 44 | 3 | 0 |
| S7 sporty | 26 (21) | 457 | 3 | 0 |
| S8 screen-heavy | 13 (9) | 39 | 3 | 1 |

- **Still under 15 videos: S4 (10), S6 (9), S8 (13).** KiasuParents still has 0 in-window items; Perplexity is blocked after about 3 questions (sign-up wall, or no input box), so 13 of 32 new answers failed.
- Table now holds 516 videos (81 from brand queries, no segment) and 1,834 comments. Comment counts per segment moved because a comment seen under two segments is stored once (last segment wins).
- **Spot-check, new items:** videos 5 of 15 off-topic or not consumer voice (a SEED lens-brand account, a colour-lens shop, a laser clinic, a shopping clip, a stunt video); comments about 8 of 15 off-topic or chatter ("Drama queen", "Steak knife works better"). The trade/giveaway word list missed SEED, moodylenses and NewYorkLaserVision, so some trade accounts remain in the file. Filter by `scope_status = found` and treat them with care.
- Singapore-only is still not met on YouTube (most new creators are US, Taiwan or mainland China).


---
# UPDATE 2026-10-28 (2): Step 2, TikTok via Apify (S4, S6, S8 only; Instagram not run)
Run on S4, S6 and S8 (2 queries each, English), plus the comments of two accounts you confirmed: `lenskartsg` and `acuvuesg`. Exit country Singapore.
**Spend (estimated by the tool, hard cap US$1):** probe 1 US$0.012 + this run US$0.084 = about **US$0.096** for the study. Nothing else was paid.

| Segment | TikTok videos on-topic and Singapore-signalled | TikTok comments kept |
|---|---|---|
| S4 surgery choosers | 0 (22 out, 18 without a Singapore signal) | 0 |
| S6 over-40s | 1 | 7 |
| S8 screen-heavy | 2 | 20 |
| not tied to a segment (comments on `lenskartsg` / `acuvuesg` videos) | 3 account videos (not items) | 3 |

- **Step 2 did not rescue S4, S6 or S8.** Each stays under 15 items on TikTok. The search is not country-filtered, so most results had no Singapore signal ("probable", no comments fetched). S4 found nothing Singapore-tagged at all.
- **The hits do not match their segments.** The 2 S6 and S8 review videos are coloured-lens (Moody) reviews, not presbyopia or screen use; the S8 video with 20 comments is a beginner struggling to insert lenses (Singlish: "leh", "dun"), which fits S1 (never tried) better than S8. Segment tags follow the query, not the content.
- **Spot-check (all items, since there are few):** 7 videos judged "found": 4 off-topic (3 `acuvuesg` F1/CORTIS event posts and a Lenskart store-refit post; the filter let them through as account videos) and 3 on contact lenses. Comments: about 9 of 30 are chatter ("💕💕💕", "ready!", "dont cry", "Juhoon mi bias!!"), the rest are on contact lenses.
- **Comments fetched vs kept:** 120 fetched, 30 kept. The rest were removed by the window, giveaway words or, for Lenskart glasses promotions (170, 182, 68 comments), the rule that a comment must itself name contacts, LASIK, ICL or surgery. The glasses-ad comments were therefore mostly off-topic and dropped.
- **Singapore:** TikTok items here carry a Singapore tag or come from a Singapore account. TikTok comments carry no location, so they are Singapore-tied only through their video.
- Not run: Instagram comments, Facebook, retail, app reviews, Google Maps.
- Segments under 15 on-topic items after all sources: S4, S6, S8. Per the rule in this note, read those cells as "no online evidence we could tie to Singapore".


---
# UPDATE 2026-10-28 (3): Step 2, Instagram comments via Apify
Read the 5 brand accounts and 9 retailer/optical-chain accounts already in the pack (Instagram has no keyword search), posts from the last 24 months. **Spend (tool estimate): US$0.345** (cap US$1). Total Apify spend for the study: about US$0.44.

- 190 account posts read; 40 name a contact-lens word or product line (acuvuesg 10, coopervisionsg 10, bauschandlombsg 5, olens_contactlens 5, capitolopticalsg 3, better_vision_sg 3, others 4). Their comments: **120 kept** (old, giveaway and tag-only comments dropped). They carry **no segment** (no query produced them), so they cannot lift S4, S6 or S8 above 15.
- **They are almost all off-topic.** Spot-check of 30 of the 120: about 28 are fan or contest comments, not lens voice: K-pop ambassador fandom (CORTIS, "Juhoon", "Martin"), and replies to a frame-style contest ("Round Frame", "Oval frames are my go-to", the same text posted twice). Only 1 to 2 are on contact lenses (for example a request for a -8.5D lens that is only made to -8.0D). The contest replies slipped past the giveaway word list because the posts do not say "giveaway" in the comment itself.
- Treat `social_comments` rows with `platform = instagram` as **not usable evidence for any segment**. They are in the CSV unchanged, as the tool produced them.
- Instagram only embeds about 15 latest comments per post, so even on-topic posts give little.

## Overall Step 2 result
TikTok (US$0.096) and Instagram (US$0.345) did not give S4, S6 or S8 15 on-topic Singapore items. Under the rule in this note, read S4, S6 and S8 as "no online evidence we could tie to Singapore". Not run: Facebook, retail, app reviews, Google Maps.


---
# UPDATE 2026-10-28 (4): YouTube strict Singapore rule (US$0 paid; 608 YouTube quota units)
**Result: after the rule YouTube has 1 on-topic Singapore video and 0 substantive comments in the whole study. Read YouTube as "no online evidence we could tie to Singapore" for every segment.**

Rule (in the tool now, `adapters/youtube.py`, words in `packs/sg.yaml`): a video counts as Singapore only if its title, description or tags contain singapore, singaporean, s'pore, sg or the Singapore flag emoji (or a tag starting `sg`, such as #sgtiktok), or its channel country is SG (YouTube channels endpoint). Singlish particles are not a signal. A video without a signal becomes `probable` ("market: no Singapore signal"): the row is kept, its comments are not collected. YouTube comments have no location, so a comment is Singapore-tied only through its video.

| Segment | Videos on-topic before | after | Substantive comments before | after |
|---|---|---|---|---|
| no segment (brand queries) | 13 | 0 | 29 | 0 |
| S1 glasses-only | 33 | 0 | 374 | 0 |
| S2 dropouts | 18 | 0 | 73 | 0 |
| S3 part-timers | 18 | 0 | 95 | 0 |
| S4 surgery choosers | 10 | 0 | 204 | 0 |
| S5 students and teens | 21 | 0 | 254 | 0 |
| S6 over-40s | 9 | 0 | 44 | 0 |
| S7 sporty | 26 | 0 | 457 | 0 |
| S8 screen-heavy | 13 | 1 | 39 | 0 |
| **Total** | **161** | **1** | **1,569** | **0** |

- 162 stored video rows (158 distinct videos) were downgraded from found to probable. No row was deleted. `in_scope` was set to 0 on them to match. The one video left is from Medical Channel Asia (S8) and has no substantive comments.
- Why so few: only 21 of 494 videos carry any Singapore signal; only 6 of 376 channels declare country SG, and 117 channels set no country. Search with `regionCode=SG` is a bias, not a filter.
- **Spot-check, before the rule (30 on-topic videos, 30 substantive comments, random):** videos: 0 of 30 identifiably Singapore (19 had a declared non-Singapore channel country: US 12, TW 2, IN 2, PH, HK, GB; 11 had no country, several clearly Taiwan or mainland China); 1 clearly off-topic (smart-contact-lens photonics item) and about 3 borderline (costume lenses, a dry-eye clinic video, a shop listing). Comments: 10 of 30 off-topic or no content ("Same", "Hahaha Definitely", a tech-olympics joke, a fan message to the creator); all 30 sit under non-Singapore videos.
- Retry: adding "Singapore" to the search words (S4 and S6, 6 queries, 600 units) returned 47 videos, 1 on-topic Singapore (the same one). Most results fail the contact-lens-word check, not the Singapore rule. A full run would cost about 6,400 units and is not expected to help; it was not run. The test study was deleted.
- Closed: the 52 channels with no country set were checked by the owner on 2026-10-28; none is a Singapore contact-lens voice, so `market_channels` stays empty and nothing was added back.
- **Not changed:** the CSV and `gold_set/` files in this folder were exported before this rule. Their YouTube rows still show the old `scope_status`; re-export from the study (or filter on `scope_reason`) to get the strict version. The tables above in this note (first pass, second pass) describe the old rule.
- Consequence for the segment table: S1 to S8 now rest on KiasuParents (0 in window), Google Trends (series, not items) and AI-search answers only. TikTok (UPDATE (2)) already used its own Singapore signal.



---
# UPDATE 2026-10-28 (5): brand-led queries and the `purpose` column
New column **`purpose`** on posts and comments (also in the gold set): `brand_quarter` = produced by a brand-led query, `segment` = produced by a segment query or an account read (Instagram/TikTok accounts included). Existing rows were back-filled by the slot that produced them. Split on it; do not mix the two in counts.

Brand-led runs (same filters as before: 24-month window, giveaway/promo and trade accounts dropped, de-duplicated, Singapore signal required):
- **YouTube:** 5 brands, 4 to 6 queries each ("<brand> contact lenses review", "<brand> Singapore", "<brand> daily", product lines). Some queries failed with HTTP 429 (rate limit), so Bausch + Lomb and Olens have fewer queries than planned.
- **TikTok (Apify):** 3 queries per brand, estimated spend **US$0.0975** (cap US$1). Total Apify spend for the study is now about US$0.54.
- Instagram has no keyword search, so no brand-led Instagram query was possible; brand and retailer accounts were already read (see above).

**Brand rows that count (brand named + lens word + Singapore signal + in window), per quarter, YouTube + TikTok:**

| Brand | 2024-Q4 | 2025-Q1 | 2025-Q2 | 2025-Q3 | 2025-Q4 | 2026-Q1 | 2026-Q2 | 2026-Q3 | 2026-Q4 | total |
|---|---|---|---|---|---|---|---|---|---|---|
| MyACUVUE | 0 | 0 | 0 | 0 | 0 | 1 | 0 | 3 | 0 | 4 |
| Alcon | 0 | 0 | 0 | 0 | 0 | 0 | 0 | 0 | 0 | 0 |
| Bausch + Lomb | 0 | 0 | 0 | 0 | 0 | 0 | 0 | 0 | 0 | 0 |
| CooperVision | 0 | 0 | 0 | 0 | 0 | 0 | 1 | 0 | 0 | 1 |
| Olens | 0 | 0 | 0 | 1 | 0 | 0 | 0 | 0 | 0 | 1 |

**Brand rows on topic but with no Singapore signal (dated, kept, NOT counted):** they are what the strict Singapore rule moved to "probable". Read them as an upper bound, not as Singapore evidence.

| Brand | 2024-Q4 | 2025-Q1 | 2025-Q2 | 2025-Q3 | 2025-Q4 | 2026-Q1 | 2026-Q2 | 2026-Q3 | 2026-Q4 | total |
|---|---|---|---|---|---|---|---|---|---|---|
| MyACUVUE | 0 | 1 | 5 | 1 | 3 | 5 | 4 | 2 | 1 | 22 |
| Alcon | 0 | 2 | 2 | 3 | 1 | 4 | 3 | 6 | 5 | 26 |
| Bausch + Lomb | 0 | 4 | 1 | 0 | 2 | 1 | 3 | 3 | 1 | 15 |
| CooperVision | 0 | 3 | 0 | 3 | 1 | 0 | 0 | 4 | 1 | 12 |
| Olens | 2 | 2 | 1 | 1 | 2 | 1 | 6 | 5 | 4 | 24 |

- **Most brands have 0 to 1 readable quarters** on counted rows (MyACUVUE has 2 quarters on TikTok, CooperVision 1 on YouTube, Olens 1 on TikTok; Alcon and Bausch + Lomb none). Under the rule in this note, that means "no online evidence we could tie to Singapore", not "no activity".
- **Undated rows:** posts: instagram/segment: 0 of 150; tiktok/brand_quarter: 0 of 300; tiktok/segment: 0 of 180; youtube/brand_quarter: 0 of 215; youtube/segment: 0 of 435. Comments with no date: 0 of 2009. KiasuParents threads with no date: 0 of 65. No undated row was dropped for lacking a date.
