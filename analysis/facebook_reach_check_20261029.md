# Facebook reach check: can we pull more Singapore consumer voice? (2026-10-29)

Verdict: **no-go** on more Facebook scraping for consumer voice. Trials cost about $0.65 (budget $2). No large run was made. Builds on `facebook_findings_20261007.md`.

## Groups (actor `datahamster/facebook-groups-search`, 8 queries, 16 groups, $0.25)
Only four are about contact lenses; none is a place where Singapore people ask or discuss.

| Group | Members | Status | 10-post sample (apify/facebook-groups-scraper) |
|---|---|---|---|
| MyEyeBB Color Contact Lens (facebook.com/groups/myeyebb/) | 738 | public | Brand-run content, Jun 2026; 4 comments in 10 posts; not Singapore-specific |
| Colored Contact Lenses for Sale! (groups/123663784324102/) | 8,100 | public | Chinese wholesale ads, Aug-Oct 2026; 3 comments in 10 posts |
| MISLENS Contact Lenses (groups/388406712378196/) | 1,300 | public | 10 of 10 vendor ads (cases, chains); 0 comments |
| Contact Lens SG (groups/2751108218453264/) | 512 | private | Seller group; not readable without a login |

Other 12 hits are general groups (Expats In Singapore 90.8K, Singapore Primary School Parents 92.2K, Lobang Lovers 61.9K, Seedly 38.1K, and others). Not scraped: the groups actor has no keyword filter, so a lens post can only be found by paying for every post. Untested.

## Actor facts
- Groups scraper: public groups only, $0.005 per post (free tier), returns `commentsCount`. Comments scraper: $0.0025 per comment.
- Posts scraper: no comment count on any page; reactions only as `likes`, `reactionLikeCount`, `topReactionsCount` (no breakdown).
- Reviews scraper (`apify/facebook-reviews-scraper`): returned nothing for acuvuesg, coopervisionsg, BauschandLombSG.
- Our `Scripts/facebook_scraper_sg.py` never sets `includeNestedComments`, so it has skipped replies. Free fix.
- Messenger and visitor posts: not public, not reachable.

## Higher cap or run back to 2022 (10 older posts per page, 30 posts, $0.16 plus comments)
- Held posts already reach back to 2024-09 (Acuvue), 2024-05 (CooperVision), 2022-11 (B+L).
- 30 older posts gave 3 comments, 0 usable (one B+L Artelac eye-gel video, non-lens, authors not Singapore-looking).
- Older posts get 1 to 11 likes (CooperVision MiSight 165 is the exception). Estimate for another 100 posts per brand: 0 to 5 usable comments, about $1.50. Extrapolated from 30 posts.

## Brand replies (27 posts that had comments, re-scraped with replies on, $0.13)
- 80 rows: 78 top-level, 2 replies; one brand reply (Bausch and Lomb Singapore, supplement question, answered within 2 days).
- About 6 question comments exist, not 20. Lens questions ("astigmatism lenses?", "near Orchard?", "where can I purchase?") have no visible reply.

## Yield and cost
| Route | Usable lens-related SG comments | Cost |
|---|---|---|
| Deeper or older brand-page runs | 0 to 5 | about $1.50 |
| Lens-specific groups | about 0 (vendor ads) | about $0.05 per 10 posts |
| General groups, blind scrape | unknown, probably a few per 1,000 posts | $5 per 1,000 posts |

If tested later: one run capped at about $1 (200 posts) on Expats In Singapore, after other sources are exhausted. Consumer voice stays with Reddit, TikTok, Google Maps and app reviews.
