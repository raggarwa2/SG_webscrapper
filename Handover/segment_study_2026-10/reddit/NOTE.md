# Reddit collection for the segment study (SG), partial

Collected 2026-10-27/28. File: `reddit_segment_posts.csv` (224 posts, as collected: no sentiment or theme tagging, not merged into voice_items). Script: `Scripts/reddit_segment_study.py`.

**This is not representative of Singapore contact-lens users.** It is what a few Reddit communities say in public. **A segment with under 15 items means "no online evidence", not "the segment does not exist".** Nothing here supports a rate or a comparison between segments.

**Status: partial.** The free archive used (Arctic Shift) went down on 2026-10-28 at about 11:05 and was still down when this was written. Posts only; **comments were not collected** (they need the archive). Gaps are listed under "What is missing".

## Counts per segment (posts kept)

| Segment | Kept | Reads as |
|---|---|---|
| Surgery choosers (LASIK, SMILE, ICL) | 50 | readable |
| Screen-heavy professionals | 8 | no online evidence |
| Over-40s | 7 | no online evidence |
| Sporty wearers | 1 | no online evidence |
| Glasses-only wearers | 1 | no online evidence |
| Dropouts | 1 | no online evidence |
| Students, teens, parents | 0 | no online evidence |
| Part-timers | 0 | no online evidence |
| Brand keywords only (Acuvue, Olens) | 3 | no online evidence |
| Unassigned: lens or glasses posts that match no segment phrase | 153 | general category voice |
| **Total** | **224** | |

A post's segment is the first keyword phrase (list below, most specific first) that appears in it, with the words in order and within 15 characters. A post can fit several segments but carries one. `search_keyword` is that phrase; `(no segment keyword)` means none matched. Only about one post in four of the kept set carries a segment phrase, so the segment counts are small by construction.

## Window and filters

- **Window:** 2024-10-27 to 2026-10-27 (24 months). 103 of the 224 are from the last 12 months (`in_last_12m`).
- **Singapore:** the post is in a Singapore subreddit, or, in any other subreddit, the text names Singapore, SGD, S$, SG, SNEC, TTSH, Capitol or Nanyang Optical, Johor, or CDC vouchers. Place names and Singlish alone are not enough outside Singapore subreddits. "HSA" and "Owndays" are not used outside them (US health savings account; a chain sold worldwide).
- **Eye relevance:** lens, glasses and surgery terms count (lens-adjacent posts about glasses or surgery are in scope). Sunglasses, beer or AR glasses, phone contacts and the slang "icl" do not. In general Singapore subreddits the eye term must be in the title, or two different eye terms in the body.
- **Dropped:** giveaway or promo text, bot authors, removed posts, and duplicates (same post id, or same title and author). Spam found: 113 posts; duplicates: 659.
- **Not applied:** no LLM relevance check, no brand-relevance check.

## Subreddits

- **Singapore subreddits swept (whole 24 months, every post read):** askSingapore (partial, see below), singapore, SingaporeRaw, SGExams, NationalServiceSG, singaporefi, VisionCorrectionSG, singaporeparents, sgmums, SingaporeHealth, nus, NTU, sgfitness, SingaporeFitness, SGBeauty, sgcareers.
- **Global eye subreddits:** glasses (swept); lasik (partial); contactlenses, eyecare, Optometry, askoptometry, Presbyopia, EyeSurgery, Myopia (not collected, see below).
- **Kept by subreddit:** askSingapore 141, NationalServiceSG 21, SGExams 19, SingaporeRaw 12, glasses 10, singapore 6, VisionCorrectionSG 2, and 13 other subreddits with 1 to 3 each. The 27 Apify rows from a first pilot account for most of the small, non-Singapore ones.
- **Posts read in completed sweeps:** 294,342 (askSingapore not counted; its sweep is being redone).

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

The 27 rows with `source = apify` came from 10 Apify searches ("<segment phrase> Singapore", plus two askSingapore/singapore queries), so their `search_keyword` carries that text.

## Spot-check (30 random kept posts, read by hand)

Final filters, seed 33: **3 of 30 off-topic (10%)**: a post about girls in Singapore, a post on spotting Singaporeans overseas, and a post titled only "Eye power". The other 27 are about lenses, glasses, eye surgery or eye health.

Earlier filter versions failed this check and were rebuilt: 22 of 30 off-topic (substring matches such as "icl" in slang and "changi" in "changing"), then 11 of 30, then 6 of 30. The CSV is from the final version only. A sample of 30 has a wide margin; treat the rate as roughly 5% to 25%.

## What is missing

- **Comments.** Not collected: the archive was down.
- **r/lasik:** partial (about 8 weekly windows failed from Dec 2024 to Feb 2025, and the sweep stopped after 2026-06-11).
- **r/askSingapore:** 2 windows failed (around 2026-01-07 and 2026-02-12). The sweep is queued to be re-run.
- **eyecare, Optometry, askoptometry, Presbyopia, EyeSurgery, Myopia:** the archive gave no data (requests failed).
- **contactlenses:** the archive returned no posts at all in two runs, without errors. Not checked against Reddit itself, so r/contactlenses is unconfirmed, not known to be empty.
- The counts above are therefore a floor for surgery and general lens voice, and say nothing about eye-care subreddits.
- To fill the gaps once the archive is back: `python reddit_segment_study.py --stage sweep`, then `--stage export` (this file's counts will change; regenerate the table).

## Cost

Apify: $0.96 of the $5.00 cap (10 pilot searches plus one probe, posts only). Arctic Shift archive: free.
