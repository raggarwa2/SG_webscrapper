# Reddit collection for the segment study (SG)

Collected 2026-10-27/28. Files: `reddit_segment_posts.csv` (232 posts) and `reddit_segment_comments.csv` (3,409 comments), as collected: no sentiment or theme tagging, not merged into voice_items. Script: `Scripts/reddit_segment_study.py`.

**This is not representative of Singapore contact-lens users.** It is what a few Reddit communities say in public. **A segment with under 15 items means "no online evidence", not "the segment does not exist".** Nothing here supports a rate or a comparison between segments.

## Counts per segment

| Segment | Posts | Threads' comments | Reads as |
|---|---|---|---|
| Surgery choosers (LASIK, SMILE, ICL) | 50 | 618 | readable |
| Screen-heavy professionals | 8 | 59 | posts: no online evidence; comments come from only 8 threads |
| Over-40s | 7 | 47 | posts: no online evidence; comments come from only 7 threads |
| Sporty wearers | 1 | 0 | no online evidence |
| Glasses-only wearers | 1 | 10 | no online evidence |
| Dropouts | 1 | 10 | no online evidence |
| Students, teens, parents | 0 | 0 | no online evidence |
| Part-timers | 0 | 0 | no online evidence |
| Brand keywords only (Acuvue, Olens) | 3 | 14 | no online evidence |
| Unassigned: lens or glasses posts that match no segment phrase | 161 | 2,651 | general category voice |
| **Total** | **232** | **3,409** | |

A post's segment is the first keyword phrase (list below, most specific first) that appears in it, with the words in order and within 15 characters of each other. A post carries one segment. `search_keyword` is that phrase; `(no segment keyword)` means none matched. Only about one post in three carries a segment phrase, so segment counts are small by construction. **A comment takes the segment of its thread**, not of its own text.

## Window and filters

- **Window:** 2024-10-27 to 2026-10-27 (24 months). 110 of the 232 posts and 1,621 of the comments are from the last 12 months (`in_last_12m` on posts; use `created_utc` on comments).
- **Singapore:** the post is in a Singapore subreddit, or, in any other subreddit, the text names Singapore, SGD, S$, SG, SNEC, TTSH, Capitol or Nanyang Optical, Johor, or CDC vouchers. Place names and Singlish alone are not enough outside Singapore subreddits. "HSA" and "Owndays" do not count there (US health savings account; a chain sold worldwide).
- **Eye relevance:** lens, glasses and surgery terms count (lens-adjacent posts about glasses or surgery are in scope). Sunglasses, beer or AR glasses, phone contacts and the slang "icl" do not. In general Singapore subreddits the eye term must be in the title, or two different eye terms in the body.
- **Dropped:** giveaway or promo text, bot authors, removed or deleted posts and comments, and duplicate posts (same post id, or same title and author).
- **Comments are not filtered for topic.** They are the replies to the 232 kept posts (up to 300 per thread; the largest thread has 273). `has_eye_term` = 1 for 968 of them marks comments that name a lens, glasses or eye term; the rest are often on-topic only in context ("Great value and service", "Paris Miki").
- **Not applied:** no LLM relevance check, no brand-relevance check.

## Subreddits

- **Singapore subreddits swept (every post in the 24 months read, no failed windows):** askSingapore, singapore, SingaporeRaw, SGExams, NationalServiceSG, singaporefi, VisionCorrectionSG, singaporeparents, sgmums, SingaporeHealth, nus, NTU, sgfitness, SingaporeFitness, SGBeauty, sgcareers.
- **Global eye subreddits swept:** glasses, lasik (5,961 posts), Optometry (10,770), Myopia (4,049), Presbyopia (1 post). Almost none of these posts are from Singapore, so they add few rows.
- **Nothing in the archive for:** contactlenses, eyecare, askoptometry, EyeSurgery. The archive returned 0 posts with no errors, in three runs. This is the archive's coverage, not proof that those subreddits are empty on Reddit.
- **Posts read in sweeps:** 379,721, of which 34,860 were lens, glasses or eye related; 232 passed all filters.
- **Kept posts by subreddit:** askSingapore 146, NationalServiceSG 21, SGExams 19, SingaporeRaw 12, glasses 10, singapore 6, and 13 other subreddits with 1 to 3 each (r/u_shingawaeye 3, r/myopia 3, r/VisionCorrectionSG 2, and 10 with a single post, mostly from the Apify pilot). 27 posts come from an earlier paid Apify pilot (`source = apify`); the rest are `source = arctic`. Comments exist only for `arctic` posts.

## Keywords

Segment phrases, most specific first (word order matters; the first match labels the post):
- glasses-only: never tried contacts; glasses or contacts; contacts or glasses; glasses vs contacts
- dropout: stopped wearing contacts; stop wearing contacts; back to glasses; gave up contacts
- part-timer: contacts occasionally; contacts sometimes; contacts special occasions
- surgery: LASIK; SMILE surgery; ICL; ReLEx; eye surgery
- student: contacts school; contacts teen; first time contacts; contact lenses student; contacts kid
- over-40: presbyopia; multifocal; reading glasses; progressive lenses; bifocal
- sporty: contacts swimming; contacts gym; contacts running; contacts badminton; contacts sports
- screen-heavy: dry eyes; eye strain; contacts computer; contacts office
- brand: Acuvue; Air Optix; Biofinity; Olens; Bausch Lomb; CooperVision
- generic (segment left as unassigned): contact lenses; contact lens; contacts; glasses

The 27 `apify` rows came from 10 Apify searches ("<segment phrase> Singapore", plus two askSingapore/singapore queries). Their `search_keyword` keeps that wording.

## Spot-check (30 random items, read by hand)

- **Posts (final filters, 224-post version, seed 33): 3 of 30 off-topic (10%).** Off-topic: a post about girls in Singapore, a post on spotting Singaporeans overseas, a post titled only "Eye power". The 8 posts added afterwards by the gap sweep were not sampled.
- **Comments (seed 5): 11 of 30 off-topic or empty (about a third).** Mostly short replies in a few large off-topic threads (an accent thread, a childcare thread, a gif). The on-topic ones are substantive (Lenskart vs Owndays vs Zoff, progressive lens experiences, eye drop advice). Use `has_eye_term` to narrow.
- Earlier filter versions failed this check and were rebuilt: 22 of 30, then 11 of 30, then 6 of 30 posts off-topic (substring matches such as "icl" in slang and "changi" in "changing"). The CSVs are from the final version only. With 30 items the margin is wide; read the post rate as roughly 5% to 25%.

## Limits

- Reddit only, public posts; Arctic Shift (a free community archive) was the source for 205 of 232 posts and all comments. It was down from about 11:05 to 15:00 on 2026-10-28; nothing is missing as a result (every gap was re-swept with 0 failed windows).
- Comments for the 27 Apify-sourced posts were not fetched.
- Scores and comment counts are as archived, not live.
- To refresh: `python reddit_segment_study.py --stage sweep`, then `--stage archive-comments`, then `--stage export`.

## Cost

Apify: $0.96 of the $5.00 cap (10 pilot searches plus one probe, posts only). Arctic Shift archive: free.
