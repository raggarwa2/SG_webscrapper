# SG contact-lens project: summary of data captured

Counts read from the live databases on 2026-10-19. Focal brand: Acuvue. Peers: Alcon, Bausch & Lomb, CooperVision, Olens.

## 1. At a glance

- **About 11,250 analysable records** across 13 channels, plus a weekly Google search-interest series (3,930 points, an index and not records).
- **11,103 items** sit in one common table (`voice_items`); **3,064** of them are model-tagged under the current label standard (sentiment, up to 2 themes with polarity, journey stage).
- Window: mostly 2023 to 3 Oct 2026; the oldest items (YouTube, Reddit, XHS) go back to 2009 to 2015.
- Giveaway entries (233 comments: Instagram 173, Facebook 60) are excluded from every sentiment figure.

## 2. What we hold, by channel

| Channel | What it is | Records | Date range | Brands covered | Role in the study |
|---|---|---|---|---|---|
| YouTube | Videos and comments | 172 videos, 1,256 comments | 2009 to Sep 2026 | All five (Alcon 47, Olens 41, CooperVision 32, B+L 26, Acuvue 26 videos) | Consumer voice |
| Instagram | Posts and comments | 518 posts, 668 comments | Feb 2019 to Oct 2026 | Comments: Acuvue 476, Alcon 97, CooperVision 90, B+L 5, Olens 0 | Consumer voice and brand broadcast |
| Xiaohongshu (XHS) | Posts and comments | 711 posts, 156 comments | 2015 to Sep 2026 | All five (Acuvue 173, CooperVision 144, B+L 140, Olens 134, Alcon 120) | Consumer voice |
| Facebook brand pages | Posts and comments | 330 posts, 94 comments | Nov 2022 to Oct 2026 | Acuvue, CooperVision, B+L 100 posts each; Olens 30; no Alcon | Brand broadcast; thin comments |
| Reddit | Posts and comments | 57 posts, 95 comments | 2014 to Sep 2026 | All five (9 to 14 posts each) | Consumer voice (thin) |
| KiasuParents | Forum threads | 41 | Jan to Oct 2023 | Acuvue 17, Alcon 9, B+L 7, CooperVision 5, Olens 3 | Consumer voice (dated) |
| Lazada reviews | Product reviews | 92 (Acuvue 24, Alcon 38, B+L 30) | Mar 2020 to Sep 2026 | Acuvue, Alcon, B+L | Consumer voice (near-uniformly positive) |
| Lazada and TikTok Shop | Product and price listings | 143 (Lazada 40, TikTok Shop 103) | 23 to 25 Sep 2026 | Acuvue 36, B+L 34, Alcon 31, Olens 20, CooperVision 9 | Price and availability |
| MyACUVUE app | App store reviews | 119 (Google Play 95, avg 2.48; Apple 24, avg 1.67) | 2017 to Sep 2026 | Acuvue only | Owned experience |
| Google Maps | Optical-retailer reviews | 5,578 reviews, 88 outlets, 6 chains (Owndays 3,481, Capitol 847, Better Vision 637, Nanyang 243, Optical 88 241, Visio 129) | Dec 2015 to Oct 2026 | Retailers, not brands | Retail experience; 862 are clearly about contact lenses |
| Facebook retailer reviews | Recommend flag and text | 542 (34 about contact lenses) | Aug 2017 to Aug 2026 | Retailers (Owndays, Zoff, Better Vision, Capitol, Nanyang) | Retail experience (mostly spectacles) |
| Facebook retailer posts | Retailer page posts | 550 (50 per retailer; 33 about contact lenses) | Oct 2025 to Oct 2026 | 11 retailers | Brand broadcast |
| Facebook Ad Library | Meta ads | 124 from 18 pages; 27 verified as SG (26 Acuvue) | Sep 2022 to Oct 2026 | Alcon 59, Acuvue 49, B+L 14, CooperVision 2, Olens 0 | Brand broadcast |
| Google Trends | Weekly SG search-interest index | 3,930 weekly points, 262 weeks per term | Sep 2021 to Sep 2026 | 8 brand terms and 4 broader terms | Demand (index, not volume) |

## 3. How the data is organised for analysis

| Lens | Items | What it answers |
|---|---|---|
| Consumer voice | 3,387 (brand pool of 935 after giveaway removal) | How people talk about each brand; the only lens that compares brands |
| Owned experience | 119 | MyACUVUE app: what blocks registration and use |
| Retail experience | 6,120 | What happens in-store (Google Maps, retailer pages) |
| Brand broadcast | 1,477 | What brands and retailers say themselves (posts, ads) |

Labels: one model prompt (GPT-4o-mini) gives each item sentiment, up to 2 of 8 themes, a journey stage and a content type. Eight themes roll up to four decision groups: Product & look; Price, access & trust; Guidance & service; Loyalty & app.

## 4. Caveats to say out loud

- **Thin channels:** Reddit, Facebook comments (61 of 94 are CooperVision, 4 are Acuvue), B+L and Olens on Instagram comments (5 and 0), Lazada (positive-only).
- **Brands are compared only where both sides have 15 or more items.** Smaller bases show a dash.
- **Google Maps skews positive** (average about 4.75 stars; newest reviews per outlet), so its friction rate (7%) understates dissatisfaction. Contact-lens-only subset: 862 reviews, 13.5% friction.
- **Facebook ads:** only 27 of 124 are confirmed SG. Alcon's 59 are global creative, not SG spend.
- **Google Trends** is an index within a batch, not search volume. Competitor terms are too sparse to trend.
- **Gaps:** no Shopee, no TikTok Shop reviews, no Alcon on Facebook, forum data is from 2023, Watsons and HardwareZone not collected.

## 5. Where the files are

- Raw and tagged CSVs: `Handover/csv_export_2026-10-09/` (with `MANIFEST.csv` and `DATA_DICTIONARY.csv`). Lazada reviews have grown from 68 to 92 since that export; re-export before sharing the files.
- Databases: `Scripts/output/*.db`. Inventory detail: `data.md`.
