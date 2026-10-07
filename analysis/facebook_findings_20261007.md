# Facebook (Singapore only) - findings and source role, 2026-10-07

## Source role: Facebook is a CHANNEL / BARRIER / COMPETITIVE-ACTIVITY source, not a product-sentiment source
- Brand-page comments are too thin and contest-driven (54 of 77 SG comments are contest entries or spam).
- Retailer reviews are mostly about spectacles (170 spectacle-only vs 34 contact-lens of 542), and mostly dated 2019-2022.
- Use Reddit / TikTok / Google Maps / app reviews for product experience. Use Facebook for: retailer-access barriers,
  promotion mechanics (ads + retailer posts), and what brands/retailers push.

## Data held (all Singapore)
| Dataset | DB | Rows |
|---|---|---|
| Brand-page posts (Acuvue SG, CooperVision SG, B+L Singapore; 100 each) | facebook_data_sg.db | 300 (+30 Olens global - exclude) |
| Brand-page comments | facebook_data_sg.db | 77 SG (+17 Olens) |
| Retailer reviews (Owndays, Better Vision, Capitol, Nanyang, Zoff) | facebook_retailers_sg.db | 542 |
| Retailer posts (11 retailers x 50) | facebook_retailers_sg.db | 550 |
| Ad Library ads (SG reach; only 'sg_verified' = confirmed SG advertiser) | facebook_ads_sg.db | 124 (27 sg_verified) |
No reviews available on Facebook for: Optical 88, Visio Optical, Lenskart SG, Watsons SG, Guardian SG, Unity Pharmacy.

## Barrier evidence (contact-lens reviews/comments only; project 10-barrier taxonomy + 2 proposed)
Proposed additions (not in mappings.py BARRIERS; need sign-off before use in triangulation):
1. eye-exam gating or fee - Owndays AMK refused contact lenses (last check >6 months); Better Vision Causeway Point quoted a checking fee if not buying.
2. stock / appointment availability or delivery wait - Nanyang (restock quoted 2 months, no follow-up), Capitol (no appointment slots, 2020).
   Mitigations seen: free/fast home delivery and sample lenses (Better Vision, Capitol).
Taxonomy hits: rewards unreliable (B+L Ultra $20 FairPrice voucher not received; 2 customers, one comment posted 3x),
lack of professional guidance (unanswered "where can I buy / astigmatism lens near Orchard" questions on B+L and Acuvue pages).
Sample sizes are tiny (single digits). Directional, not quantified.

## Competitive activity
- Acuvue SG ads: ~25 active, almost all one CORTIS collector-set promotion (buy 2 boxes); retailers (Lenskart, Owndays, Capitol) repeat it with a 4-box threshold.
- Alcon is retailer-led in SG (Better Vision, Capitol, Optical 88 run Dailies Total1 / Total30 offers); no SG Alcon page used.
- Clear4Vision (SG status UNVERIFIED) runs buy-5-get-1 and 90+30 bundles across Acuvue, Alcon, B+L.
- Aug 2026: Owndays, Lenskart, Capitol all promote Ortho-K / myopia management for children.
- Engagement: CooperVision MiSight post 306 likes (best); Acuvue SG averages 1.1 likes/post on 34K followers.

## Tags added (rule-based, re-run with Scripts/facebook_retag_sg.py)
fb_retailer_reviews: is_contact_lens, is_spectacle_only, barrier_tag, barrier_polarity (barrier = complaint; mitigated = recommended review describing a solved barrier)
fb_comments: is_contest_or_spam, barrier_tag, barrier_polarity
Backups: output/backups/facebook_*_BACKUP_20261007.db

## Known limits
- Rule-based tagging; spot-check before quoting numbers. Duplicate comments not de-duplicated.
- Ad Library exposes no advertiser country; only Acuvue SG and Bausch and Lomb Singapore are confirmed SG.
- Olens (global page) is in facebook_data_sg.db but is out of scope; filter brand != 'Olens'.
