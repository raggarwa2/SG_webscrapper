# Merged Source Log

Single source log for all four Research runs and the scraped data. Every claim in the deliverables carries an ID that maps to a row here.

## ID convention

- **Research sources:** `R1-S##` (Run 1, wearer behaviour and clinical evidence), `R2-S##` (Run 2, competitive positioning), `R3-S##` (Run 3, retail, ECP and coupon dynamics), `R4-S##` (Run 4, digital loyalty and registration friction). The runs each started numbering at S01, so the run prefix is required.
- **Shorthand:** `SC-APP` means both app-store sources together (`SC-APP-GP` and `SC-APP-AS`).
- **Research claims:** `R1-C-14` means claim C-14 in Run 1, and so on. A claim's own source IDs are listed in the run's file; this log resolves them.
- **Scraped sources:** `SC-xxx` (see the second table). Scraped findings are cited as `SC-xxx` plus the figure.
- **Read depth:** as reported by each run (A / SN / snippet = abstract or snippet only; F / FT / full = full text read). Run 2 and Run 4 rows marked 'via subagent' or 'via enricher' are snippet-level.
- **Independence caveats:** (1) Run 4 reviewed the same Apple and Google Play MyACUVUE listings that SC-APP-AS and SC-APP-GP scrape, and quotes some project-inventory figures (2.48 / 1.67 / 3.32 ratings; 'marketplaces per project inventory'). App-review findings from R4 and SC-APP are therefore **one underlying source, not two**. (2) Run 3 saw some project inventory figures (app rating discrepancy). (3) SC-INV is internal documentation derived from the scraped data. (4) Runs 2, 3 and 4 share some web sources (for example the MyACUVUE FAQ, Capitol Optical pages, Alcon reward pages), so agreement on those is not independent.
- **Source IDs cited by a run but missing from its log:** none found in the claim tables (checked); Run 3 states S06, S38 and S39 were dropped.

## Table A. Research sources (all four runs)

| Log ID | Run | Title | Publisher | URL | Date | Type | Read depth |
|---|---|---|---|---|---|---|---|
| R1-S01 | R1 | Dropout rates among optical interventions for myopia control: systematic review | Contact Lens and Anterior Eye (repository record) | https://minerva.usc.gal/entities/publication/2179d949-e47b-4bdf-9647-98ff9e9bb9c4 | 2025 (vol 49(2)); record Feb 2026 | peer-reviewed | A |
| R1-S02 | R1 | Comparing dropout in myopia control trials | Myopia Profile | https://www.myopiaprofile.com/articles/comparing-dropout-myopia-control-trials | n/s | blog | A |
| R1-S03 | R1 | A Review of Contact Lens Dropout | Clinical Optometry | https://doaj.org/article/ca3fb4d0b1124f2a8438ec1e6636845e | Jun 2020 | peer-reviewed | A |
| R1-S04 | R1 | Factors in the success of new contact lens wearers | QxMD listing (journal n/s) | https://read.qxmd.com/read/27818113/factors-in-the-success-of-new-contact-lens-wearers | n/s | peer-reviewed | A |
| R1-S05 | R1 | Retention Rates in New Contact Lens Wearers | Eye & Contact Lens (PubMed) | https://pubmed.ncbi.nlm.nih.gov/28617731/ | Sep 2018 | peer-reviewed | A |
| R1-S06 | R1 | Patient considerations versus actual reasons for contact lens cessation | Contact Lens and Anterior Eye (UPCommons) | https://upcommons.upc.edu/entities/publication/2bb646ff-8685-419f-8f9f-6a90b69b89b3/full | Oct 2025 | peer-reviewed | A |
| R1-S07 | R1 | Clinical factors associated with contact lens dropout | Contact Lens and Anterior Eye (PubMed) | https://pubmed.ncbi.nlm.nih.gov/30538060/ | Jun 2019 | peer-reviewed | A |
| R1-S08 | R1 | Interventions for myopia control in children (Cochrane living review) | Cochrane (PubMed) | https://pubmed.ncbi.nlm.nih.gov/39945354/ | 13 Feb 2025 | peer-reviewed | A |
| R1-S09 | R1 | Same, City Research Online record | City, University of London | https://openaccess.city.ac.uk/id/eprint/34708/ | 2025 | peer-reviewed | A |
| R1-S10 | R1 | Peripheral add multifocal soft contact lenses in childhood myopia: meta-analysis | BMC Ophthalmology (DOAJ) | https://doaj.org/article/58939867207244d69e33e573d6892f3c | Apr 2024 | peer-reviewed | A |
| R1-S11 | R1 | Efficacy of interventions for myopia control: network meta-analyses | Acta Ophthalmologica (PubMed) | https://pubmed.ncbi.nlm.nih.gov/40219611/ | Dec 2025 issue | peer-reviewed | A |
| R1-S12 | R1 | Long-term effect of dual-focus contact lenses: 6-year trial | Optometry and Vision Science (Aston repository) | https://publications.aston.ac.uk/id/eprint/44269/1/Long_term_Effect_of_Dual_focus_Contact_Lenses_on.2.pdf | Mar 2022 | peer-reviewed | A |
| R1-S13 | R1 | Six-year MiSight 1 day clinical trial data | Myopia Profile | https://myopiaprofile.com/articles/six-year-misight-study-data | n/s | blog | A |
| R1-S14 | R1 | Randomized trial of soft contact lenses with novel ring focus | Ophthalmology Science (PMC) | https://pmc.ncbi.nlm.nih.gov/articles/PMC9762188 | 18 Oct 2022 | peer-reviewed | F |
| R1-S15 | R1 | SPACE: soft peripheral contact lens for eye elongation control | Contact Lens and Anterior Eye (Epistemonikos) | https://www.epistemonikos.org/en/documents/9ee6b53e15b836df233ac8d1d2dfaf65508cd69e | 2024 | peer-reviewed | A |
| R1-S16 | R1 | Joint position statement on contact lenses for myopia control, Asia-Pacific | Visual Neuroscience | https://www.maxapress.com/article/id/69bb601cfa6c583c17fdbbf1 | 26 Mar 2026 | peer-reviewed (sponsor-funded) | F |
| R1-S17 | R1 | Awareness of myopia complications among parents in France and the UK | Patient Related Outcome Measures (PMC) | https://pmc.ncbi.nlm.nih.gov/articles/PMC12623718 | 2025 | peer-reviewed | A |
| R1-S18 | R1 | Practitioner and parent survey on myopia control uptake | Frontiers in Public Health | https://www.frontiersin.org/journals/public-health/articles/10.3389/fpubh.2022.854654/epub | 2022 | peer-reviewed | A |
| R1-S19 | R1 | Parents' knowledge and perspective of optical methods for myopia control | PolyU Research | https://research.polyu.edu.hk/en/publications/parents-knowledge-and-perspective-of-optical-methods-for-myopia-c/ | n/s | peer-reviewed | A |
| R1-S20 | R1 | Cosmetic lens wear causes one-third of corneal infections | Review of Optometry (summarising AJO) | https://www.reviewofoptometry.com/news/article/cosmetic-lens-wear-causes-onethird-of-corneal-infections | c. 2021 | trade press | A |
| R1-S21 | R1 | Symptomatic dry eye disease prevalence in Singapore (PubMed 25269444; retrieved via mirror) | PubMed | https://pubmed.ncbi.nlm.nih.gov/25269444/ | n/s | peer-reviewed | A |
| R1-S22 | R1 | Multi-country assessment of compliance with daily disposable lens wear | McMaster Experts listing | https://experts.mcmaster.ca/scholarly-works/1334147 | n/s | peer-reviewed | A |
| R1-S23 | R1 | International trends in daily disposable prescribing (2000-2023) | Review of Optometry | https://www.reviewofoptometry.com/news/article/rise-in-daily-disposable-usage-linked-to-designs-and-parameter-ranges | n/s | trade press | A |
| R1-S24 | R1 | Wearers purchasing lenses over the Internet | Eye & Contact Lens (Birmingham portal) | https://research.birmingham.ac.uk/en/publications/characteristics-behaviors-and-awareness-of-contact-lens-wearers-p/ | n/s | peer-reviewed | A |
| R1-S25 | R1 | Can we identify those likely to drop out of orthokeratology? | Myopia Profile | https://old.myopiaprofile.com/?p=43349 | n/s | blog | A |
| R1-S26 | R1 | Mobile application for contact lens wearers | BMC Med Inform Decis Mak (DOAJ) | https://doaj.org/article/aa07dc07774145919573eec04a76e01a | Jun 2022 | peer-reviewed | A |
| R1-S27 | R1 | Dropout from lens wear (CPD) | Optician Online | https://www.opticianonline.net/cpd-archive/6617 | n/s | trade press | A |
| R1-S28 | R1 | CLI report on attracting potential and former wearers | OptiKnow | https://optiknow.ca/2024/04/30/new-research-report-highlights-actions-to-attract-potential-former-contact-lens-patients | 30 Apr 2024 | trade/industry release | A |
| R1-S29 | R1 | CLI report highlights untapped contact lens demand | Eyecare Business | https://eyecarebusiness.com/news/2024/318-cli-report-highlights-untapped-contact-lens-demand/ | 14 Mar 2024 | trade press | A |
| R1-S30 | R1 | CLI "Disrupting the Dropout Dilemma" | OptiKnow | https://optiknow.ca/2024/10/30/contact-lens-institute-report-aims-to-disrupt-the-dropout-dilemma | 30 Oct 2024 | trade/industry release | A |
| R1-S31 | R1 | CLI practice behaviours that retain new wearers | OptiKnow | https://optiknow.ca/2024/09/19/new-contact-lens-institute-research-pinpoints-practice-behaviors-that-help-retain-new-contact-lens-wearers | 19 Sep 2024 | trade/industry release | A |
| R1-S32 | R1 | Generational differences in contact lens choices | EyeWire | https://eyewire.news/news/generational-differences-drive-contact-lens-choices-and-technology-appeal-new-research-finds | Oct 2025 | trade press | A |
| R1-S33 | R1 | Rationale for CL wear differs by generation | Eye on Optics | https://eyeonoptics.co.nz/live-articles/rationale-for-cl-wear-differ-by-generation | 14 Oct 2025 | trade press | A |
| R1-S34 | R1 | Cost, purchase factors drive online contact lens searches | CRSToday Europe | https://crstodayeurope.com/news/cost-purchase-factors-and-correct-usage-drive-online-contact-lens-searches-according-to-new-research-in-the-us-and-canada/2482671/ | 19 Feb 2025 | trade press | A |
| R1-S35 | R1 | Survey shows most optical products purchased in store | Healio | https://www.healio.com/news/optometry/20240321/survey-shows-most-optical-products-purchased-in-store | 21 Mar 2024 | trade press | A |
| R1-S36 | R1 | Daily disposables versus reusables | Contact Lens Spectrum | https://digital.clspectrum.com/articles/daily-disposables-versus-reusables-which-technology-wins- | May 2024 | trade press | A |
| R1-S37 | R1 | Open your eyes to contact lenses | Scrivens Opticians | https://scrivens.com/blog/open-your-eyes-to-contact-lenses-2/ | 29 Jun 2023 | retailer page | A |
| R1-S38 | R1 | Glasses-only wearers lacking the full picture | CooperVision | https://coopervision.com/our-company/news-center/press-release/glasses-only-wearers-lacking-full-picture-about-contact-lenses | 13 Jul 2021 | brand page | A |
| R1-S39 | R1 | Knowledge and barriers to contact lens use among spectacle wearers | Khyber Medical University Journal | https://www.kmuj.kmu.edu.pk/article/view/23338 | n/s (data 2020-21) | peer-reviewed | A |
| R1-S40 | R1 | Alcon survey finds contact lens business shows "resilience" | Optometry Today | https://www.aop.org.uk/ot/news/2020/08/03/alcon-survey-finds-contact-lens-business-shows-resilience | 3 Aug 2020 | trade press (company survey) | A |
| R1-S41 | R1 | Research proves service before price brings loyalty | Optician Online | https://www.opticianonline.net/content/features/research-proves-service-before-price-brings-loyalty | n/s | trade press (company survey) | A |
| R1-S42 | R1 | J&J Vision: MyAcuvue coming soon | Eye on Optics | https://eyeonoptics.co.nz/live-articles/jj-vision-myacuvue-coming-soon/ | 3 Apr 2021 | trade press | A |
| R1-S43 | R1 | The contact lens follow-up factor | Optometry Times | https://www.optometrytimes.com/view/the-contact-lens-follow-up-factor | 28 Apr 2025 | trade press | A |
| R1-S44 | R1 | E-reminders improve CL compliance | Optometry Times | https://www.optometrytimes.com/view/bclacc-study-e-reminders-improve-cl-compliance | c. 2012 | trade press | A |
| R1-S45 | R1 | Adam Samuels (research profile) | UNSW | https://www.unsw.edu.au/hdr/adam-samuels | 2020-24 | university page | A |
| R1-S46 | R1 | mHealth app (LENSA) compliance study | An-Najah/AAUP repository | https://repository.aaup.edu/handle/123456789/2109 | Jan 2022 | thesis | A |
| R1-S47 | R1 | Myopia treatments available | SNEC | https://www.snec.com.sg/our-specialties/clinic-locations/myopia-centre/understanding-myopia/myopia-treatments-available | n/s | institutional page | A |
| R1-S48 | R1 | Managing childhood myopia safely | SNEC/SingHealth | https://www.snec.com.sg/news/singapore-health/managing-childhood-myopia-safely | 10 Sep 2024 | institutional page | A |
| R1-S49 | R1 | J&J Vision announces availability of Abiliti 1-Day in Singapore | Johnson & Johnson Vision | https://jjvision.com/press-release/johnson-johnson-vision-announces-availability-acuvue-abiliti-1-day-soft-lenses | 8 Dec 2022 | brand page | A |
| R1-S50 | R1 | Abiliti 1-Day (professionals, Singapore) | J&J Vision | https://www.jjvision.com/en-sg/seeyourabiliti/professionals/abiliti-1-day/ | n/s | brand page | A |
| R1-S51 | R1 | Abiliti 1-Day (consumer, Singapore) | J&J Vision | https://www.jjvision.com/en-sg/myopia/abiliti-1-day/ | n/s | brand page | A |
| R1-S52 | R1 | Abiliti Overnight (Singapore) | J&J Vision | https://www.jjvision.com/en-sg/myopia/abiliti-overnight/ | n/s | brand page | A |
| R1-S53 | R1 | Sponsored: Abiliti 1-Day three-year data | Eye on Optics (for J&J) | https://eyeonoptics.co.nz/live-articles/sponsored-boost-your-myopia-management-toolkit-acuvue-abiliti-1-day-s-three-year-data-unveiled | 5 Feb 2026 | sponsored trade | A |
| R1-S54 | R1 | Data validates Acuvue Abiliti 1-Day efficacy | Mivision | https://mivision.com.au/?p=55174365 | 2026 (exact n/s) | trade press | A |
| R1-S55 | R1 | Q&A: 24-month outcomes with Abiliti 1-Day | Ophthalmology Times | https://www.ophthalmologytimes.com/view/q-a-evaluating-24-month-outcomes-with-abiliti-1-day-in-pediatric-myopia-control | 1 Jun 2026 | trade (J&J-linked) | A |
| R1-S56 | R1 | CooperVision's MiSight 1 day gains approvals | CooperVision | https://coopervision.com/our-company/news-center/press-release/coopervision%E2%80%99s-innovative-misight-1-day-contact-lenses-gain | 18 Mar 2019 | brand page | A |
| R1-S57 | R1 | CooperVision expands MyDay MiSight into Asia Pacific | PR Newswire via AAP | https://aapnews.aap.com.au/news/cision20260302AE98033 | 2 Mar 2026 | company release | A |
| R1-S58 | R1 | MyDay MiSight 1 Day reaches Asia Pacific | Optometry Times | https://www.optometrytimes.com/view/myday-misight-1-day-reaches-asia-pacific-in-latest-global-expansion | 3 Mar 2026 | trade press | A |
| R1-S59 | R1 | Brilliant Futures programme | Optometry Today | https://www.aop.org.uk/ot/news/2020/11/11/brilliant-futures | 11 Nov 2020 | trade press | A |
| R1-S60 | R1 | Bausch + Lomb and BHVI myopia lens collaboration | NZ Optics | https://nzoptics.co.nz/live-articles/bausch-bhvi-to-collaborate-on-new-myopia-lens/ | n/s | trade press | A |
| R1-S61 | R1 | Contact Lenses and Solutions in Singapore (landing page) | Euromonitor | https://euromonitor.com/contact-lenses-and-solutions-in-singapore/report | 2024 | market report (paywalled) | A |
| R1-S62 | R1 | Think twice about buying contact lenses online | HSA | https://www.hsa.gov.sg/consumer-safety/articles/buying-contact-lenses-online | 22 Aug 2019 | official | A |
| R1-S63 | R1 | Free Olens lenses in Korea | Daily Vanity Singapore | https://dailyvanity.sg/beauty-tips/free-olens-contact-lens-korea/ | n/s | blog/media | A |
| R1-S64 | R1 | Eyewear market in South Korea | Daxue Consulting | https://daxueconsulting.com/eyewear-market-south-korea/ | 2023 data | consultancy blog | A |
| R1-S65 | R1 | NCT05634408 Abiliti 1-Day | ClinicalTrials.gov | https://clinicaltrials.gov/study/NCT05634408 | Verified Jan 2026 | registry | A |
| R1-S66 | R1 | NCT06765603 multizonal lens plus atropine | Tundra Space (mirror of registry) | https://tundraspace.com/directory/studies/nct06765603 | Jan 2025 | registry mirror | A |
| R1-S67 | R1 | NCT01729208 MiSight dual-focus study | ClinicalTrials.gov | https://clinicaltrials.gov/study/NCT01729208 | n/s | registry | A |
| R1-S68 | R1 | Acuvue Oasys MAX Multifocal 1-Day | Woptics (retailer) | https://woptics.sg/products/acuvue-oasys-max-multifocal-1-day | n/s | retailer page | A |
| R1-S69 | R1 | Contact lens forum thread | Lowyat.NET forum | https://forum.lowyat.net/topic/971787/+2600 | n/s | forum | A |
| R1-S70 | R1 | Academy of Ophthalmology report on multifocal lenses | Review of Optometry | https://www.reviewofoptometry.com/news/article/academy-of-ophthalmology-report-validates-multifocal-cl-use-for-myopia | 6 Nov 2024 | trade press | A |
| R1-S71 | R1 | Contact lens purchasing behavior | Contact Lens Spectrum | https://clspectrum.com/issues/2012/december/contact-lens-purchasing-behavior/ | Dec 2012 | trade (J&J survey) | A |
| R1-S72 | R1 | New data on contact lens dropouts: international perspective | Review of Optometry | https://www.reviewofoptometry.com/article/new-data-on-contact-lens-dropouts-an-international-perspective | n/s | trade press | A |
| R1-S73 | R1 | The terrible 20 | Optometric Management | https://www.optometricmanagement.com/issues/2000/november/the-terrible-20/ | Nov 2000 | trade press | A |
| R1-S74 | R1 | Practitioner perception of myopia control contact lenses | Myopia Profile | https://www.myopiaprofile.com/articles/eye-care-practitioners-contact-lenses | n/s | blog | A |
| R1-S75 | R1 | Understanding parental perceptions and barriers to myopia control uptake | The Ophthalmologist | https://theophthalmologist.com/issues/2026/articles/april/understanding-parental-perceptions-and-barriers-to-myopia-control-uptake | Apr 2026 | trade/opinion | A |
| R1-S76 | R1 | Today's contact lens dropout rate similar to 1990s | Healio | https://www.healio.com/news/optometry/20130709/10_3928_1081_597x_20130101_00_1257638 | Jul 2013 | trade press | A |
| R1-S77 | R1 | Contact Lens Study (recruiting, children 7-12) | SNEC/SERI | https://www.snec.com.sg/research-innovation/clinical-trials/clinical-trials-elmo | n/s | institutional page | A |
| R2-S01 | R2 | Contact Lenses and Solutions in Singapore | Euromonitor International | https://www.euromonitor.com/contact-lenses-and-solutions-in-singapore/report | 25 Jun 2026 | Other (syndicated report summary) | Full text read (public page); share and launch sentences from snippet |
| R2-S02 | R2 | Contact Lenses and Solutions in Singapore (listing) | MarketResearch.com / Euromonitor | https://www.marketresearch.com/Euromonitor-International-v746/Contact-Lenses-Solutions-Singapore-45638207/ | 25 Jun 2026 | Other (report listing) | Full text read |
| R2-S03 | R2 | Contact Lenses and Solutions (store category) | Euromonitor International | https://www.euromonitor.com/store/explore-reports/eyewear/contact-lenses-and-solutions | Jul 2025 report | Other | Snippet only |
| R2-S04 | R2 | Singapore Contact Lenses and Solutions (2024 edition listing) | MarketResearch.com / Euromonitor | https://www.marketresearch.com/Euromonitor-International-v746/Singapore-Contact-Lenses-Solutions-37192171/ | 30 May 2024 | Other | Snippet only |
| R2-S05 | R2 | Eyewear in Singapore | Euromonitor International | https://www.euromonitor.com/eyewear-in-singapore/report | 2026 | Other | Snippet only |
| R2-S06 | R2 | Singapore Contact Lenses Market Trend, Forecasts to 2033 | Spherical Insights | https://www.sphericalinsights.com/reports/singapore-contact-lenses-market | c. 2024 | Other | Snippet only |
| R2-S07 | R2 | Singapore Contact Lenses Market Report 2023 to 2030 | Insights10 | https://www.insights10.com/report/singapore-contact-lenses-market-analysis/ | c. 2024 | Other | Snippet only |
| R2-S08 | R2 | Singapore Contact Lenses Market Size & Outlook, 2030 | Grand View Research (Horizon) | https://www.grandviewresearch.com/horizon/outlook/contact-lenses-market/singapore | c. 2025 | Other | Snippet only |
| R2-S09 | R2 | Singapore Soft Contact Lens Market Size and Share Report by 2033 | Deep Market Insights | https://deepmarketinsights.com/vista/insights/soft-contact-lens-market/singapore | c. 2025 | Other | Snippet only |
| R2-S11 | R2 | Asia Pacific Contact Lenses Market Size Report, 2034 | Global Market Insights | https://www.gminsights.com/industry-analysis/asia-pacific-contact-lenses-market | c. 2025 | Other | Snippet only |
| R2-S12 | R2 | Asia-Pacific Contact Lenses Market Share, Companies & Trends 2025–2031 | Ken Research | https://www.kenresearch.com/industry-reports/asia-pacific-contact-lens-market | c. 2026 | Other | Snippet only |
| R2-S13 | R2 | Contact Lenses Market (global) 2026–2036 | Future Market Insights | https://www.futuremarketinsights.com/reports/contact-lenses-market | c. 2026 | Other | Snippet only |
| R2-S14 | R2 | Contact lenses imports/exports by country (HS 900130), 2023 and 2024 | World Bank WITS (UN Comtrade) | https://wits.worldbank.org/trade/comtrade/en/country/ALL/year/2024/tradeflow/Imports/partner/WLD/product/900130 | 2023–2024 data | Official statistic | Snippet only |
| R2-S15 | R2 | Alcon Inc. Form 20-F FY2023 | US SEC | https://www.sec.gov/Archives/edgar/data/1167379/000116737924000008/alc-20231231.htm | 2024 | Company filing | Snippet only |
| R2-S16 | R2 | Alcon marks 20 Years in Singapore with grand opening of expanded Tuas manufacturing facility | Singapore EDB | https://www.edb.gov.sg/en/about-edb/media-releases-publications/alcon-marks-20-years-with-tuas-site-expansion.html | Jun 2025 | Official / press release | Snippet only |
| R2-S17 | R2 | Eye care giant Alcon keeps 'lens' on the future… Tuas | AsiaOne | https://www.asiaone.com/singapore/eye-care-giant-alcon-keeps-lens-future-expanded-manufacturing-and-logistics-facility-tuas | 28 Jun 2025 | News | Snippet only |
| R2-S18 | R2 | Johnson & Johnson Form 10-K FY2025 | US SEC | https://www.sec.gov/Archives/edgar/data/200406/000020040626000016/jnj-20251228.htm | Feb 2026 | Company filing | Snippet only |
| R2-S19 | R2 | Johnson & Johnson Form 10-Q Q2 2025 | US SEC | https://www.sec.gov/Archives/edgar/data/200406/000020040625000178/jnj-20250629.htm | Jul 2025 | Company filing | Snippet only |
| R2-S20 | R2 | Johnson & Johnson leaders tout contact lens growth | Jacksonville Daily Record | https://www.jaxdailyrecord.com/news/2026/jul/23/johnson-johnson-leaders-tout-contact-lens-growth/ | 23 Jul 2026 | News | Snippet only |
| R2-S21 | R2 | Johnson & Johnson reports strong growth in vision products business | Jacksonville Daily Record | https://www.jaxdailyrecord.com/news/2025/jul/24/johnson-johnson-reports-strong-growth-in-vision-products-business/ | 24 Jul 2025 | News | Snippet only |
| R2-S22 | R2 | Johnson & Johnson Reports Q4 and Full-Year 2025 Sales Growth | Vision Monday | https://www.visionmonday.com/eyecare/article/johnson-and-johnson-reports-q4-and-full-year-2025-sales-growth-issues-2026-guidance/ | Jan 2026 | Trade press | Snippet only |
| R2-S23 | R2 | Alcon Form 6-K Q4 2025 interim financial report | US SEC | https://www.sec.gov/Archives/edgar/data/1167379/000116737926000013/q42025interimfinancialrepo.htm | Feb 2026 | Company filing | Snippet only |
| R2-S24 | R2 | CooperCompanies Announces Third Quarter 2025 Results | CooperCompanies | https://investor.coopercos.com/news-releases/news-release-details/coopercompanies-announces-third-quarter-2025-results | 27 Aug 2025 | Company release | Snippet only |
| R2-S25 | R2 | How COO Is Balancing Premium Lens Growth Against Asia-Pacific Risks? | Zacks via TradingView | https://www.tradingview.com/news/zacks:2bd3398f0094b:0-how-coo-is-balancing-premium-lens-growth-against-asia-pacific-risks/ | 2026 | News (financial) | Snippet only |
| R2-S26 | R2 | Reasons to Retain Cooper Companies Stock | Zacks via Yahoo Finance | https://finance.yahoo.com/markets/stocks/articles/reasons-retain-cooper-companies-stock-165400721.html | 2026 | News (financial) | Snippet only |
| R2-S27 | R2 | Bausch + Lomb Announces Fourth-Quarter and Full-Year 2025 Results | Bausch + Lomb | https://ir.bausch.com/press-releases/bausch-lomb-announces-fourth-quarter-and-full-year-2025-results-provides-2026 | 18 Feb 2026 | Company release | Snippet only |
| R2-S28 | R2 | Bausch + Lomb (BLCO) Q4 2025 Earnings Transcript | The Motley Fool | https://www.fool.com/earnings/call-transcripts/2026/04/21/bausch-lomb-blco-q4-2025-earnings-transcript/ | 2026 | Other (transcript) | Snippet only |
| R2-S29 | R2 | Bausch + Lomb, 'Harnessing Momentum,' Reports Q4 and Full-Year Revenue Growth | Vision Monday | https://www.visionmonday.com/eyecare/article/bausch-lomb-harnessing-momentum-reports-fourth-quarter-and-full-year-revenue-growth | Feb 2026 | Trade press | Snippet only |
| R2-S30 | R2 | CooperVision Expands MyDay MiSight 1 day … Into Asia Pacific Region | CooperVision Singapore | https://coopervision.com.sg/our-company/news-center/press-release/coopervision-expands-myday-misight-1-day-myopia-control-soft | 2 Mar 2026 | Brand page / press release | Snippet only |
| R2-S31 | R2 | MiSight 1 day | CooperVision Singapore | https://coopervision.com.sg/contact-lenses/misight-1-day | Undated | Brand page | Snippet only |
| R2-S32 | R2 | Brilliant Futures Myopia Management Program featuring MiSight 1 day is Now Available in Canada | CooperVision | https://coopervision.com/our-company/news-center/press-release/coopervision-brilliant-futures-myopia-management-program | c. 2019–2020 (pre-window; still-valid historical fact) | Brand press release | Snippet only |
| R2-S33 | R2 | Confronting the Myopia Epidemic: Innovations and Interventions in Asia | CooperVision Singapore | https://coopervision.com.sg/practitioner/myopia-management/confronting-myopia-epidemic-innovations-and-interventions-asia | Undated | Brand page | Snippet only |
| R2-S35 | R2 | MyACUVUE Membership Rewards (Singapore) | J&J Vision | https://www.acuvue.com/en-sg/myacuvue-rewards-benefits/ | Live 2026 | Brand page | Snippet only |
| R2-S36 | R2 | Contact Lens FAQs: MyACUVUE (Singapore) | J&J Vision | https://www.acuvue.com/en-sg/faq/ | Live 2026 | Brand page | Full text read (question headings); answers from snippet |
| R2-S37 | R2 | ACUVUE Referral Promotion | sgreferralpromo.com | https://sgreferralpromo.com/post/acuvue-referral-promotion/ | Valid to 1 Jan 2025; updated 2 Jan 2026 | Blog | Snippet only |
| R2-S38 | R2 | ACUVUE – Eye Gen | Eye Gen Pte Ltd | https://www.eyegen.com.sg/acuvue.html | Undated | Retailer page | Snippet only |
| R2-S39 | R2 | ACUVUE OASYS MAX 1-DAY | Evershine Optical | https://evershineoptical.com.sg/2024/11/13/acuvue-oasys-max-1-day-singapore/ | 13 Nov 2024 | Retailer page | Snippet only |
| R2-S40 | R2 | ACUVUE OASYS MAX 1-Day | Capitol Optical | https://capitol.com.sg/product/acuvue-oasys-max-1-day/ | Undated (live 2026) | Retailer page | Snippet only |
| R2-S41 | R2 | ACUVUE OASYS MAX 1-Day | Better Vision | https://www.bettervision.com.sg/product/acuvue-oasys-max-1-day/ | Undated (live 2026) | Retailer page | Snippet only |
| R2-S42 | R2 | Bausch + Lomb Ultra Oneday Multifocal | Capitol Optical | https://capitol.com.sg/product/bausch-lomb-ultra-oneday-multifocal/ | Undated (live 2026) | Retailer page | Snippet only |
| R2-S43 | R2 | Bausch + Lomb collection | Hirocon SG | https://hiroconsg.com/collections/baush-lomb | Undated (live 2026) | Retailer page | Snippet only |
| R2-S44 | R2 | How to reduce discomfort and irritation with the right contact lenses (B+L advertorial) | Her World Singapore | https://www.herworld.com/style/beauty/bausch-lomb-ultra-one-day-contact-lenses | 1 Jul 2021 (pre-window; only channel source) | News (sponsored) | Snippet only |
| R2-S45 | R2 | References – Ultra One Day | Bausch + Lomb Singapore | https://www.ultraoneday.sg/references/ | Undated | Brand page | Snippet only |
| R2-S46 | R2 | About Us (timeline) | Alcon | https://www.alcon.com/about-us/ | Live 2026 | Brand page | Snippet only |
| R2-S47 | R2 | Alcon Debuts Groundbreaking PRECISION7 | Alcon | https://investor.alcon.com/news-and-events/press-releases/news-details/2024/Alcon-Debuts-Groundbreaking-PRECISION7-a-One-Week-Replacement-Contact-Lens-to-Start-and-End-Every-Week-Fresh/default.aspx | 7 Nov 2024 | Company release | Snippet only |
| R2-S49 | R2 | HSA Removes over 1,200 Online Listings of Illegal Health Products | Health Sciences Authority | https://www.hsa.gov.sg/announcements/press-release/hsaopspangea2025 | 26 Jun 2025 | Official | Snippet only |
| R2-S51 | R2 | Why Singaporeans Love OLENS SG | PopularLens | https://www.popularlens.com/reasons-to-choose-olens-sg/ | Undated | Retailer blog | Snippet only |
| R2-S52 | R2 | Buy Olens Products Online | Ubuy Singapore | https://www.ubuy.com.sg/brand/olens | Undated | Retailer page | Snippet only |
| R2-S53 | R2 | Alcon expands its lens on the future… Tuas | HR Online | https://www.humanresourcesonline.net/alcon-expands-its-lens-on-the-future-with-new-manufacturing-logistics-facility-in-tuas-singapore | Jun/Jul 2025 | Trade press | Snippet only |
| R2-S54 | R2 | Acuvue Oasys 1-day | SGCONS | https://sgcons.com/product-category/acuvue/acuvue-oasys-1-day/ | Undated | Retailer page | Snippet only |
| R2-S55 | R2 | Starvision / OLENS profile (Korean) | Asia Economy (아시아경제) | https://view.asiae.co.kr/article/2022110714284100107 | 7 Nov 2022 (pre-window) | News (Korean, translated) | Snippet only (subagent) |
| R2-S56 | R2 | OLENS sale report (Korean) | Hankyung via Daum | https://v.daum.net/v/20250116172706596 | 16 Jan 2025 | News (Korean, translated) | Snippet only (subagent) |
| R2-S57 | R2 | CVC 49% stake in Starvision (Korean) | Seoul Economic Daily | https://www.sedaily.com/NewsView/2GNQ9EG58N | 17 Jan 2025 | News (Korean, translated) | Snippet only (subagent) |
| R2-S58 | R2 | CVC–Starvision deal (Korean) | Bloter | https://www.bloter.net/news/articleView.html?idxno=630176 | c. 20 Jan 2025 | News (Korean, translated) | Snippet only (subagent) |
| R2-S59 | R2 | CVC–Starvision deal (Korean) | Edaily Marketin | https://marketin.edaily.co.kr/News/Read?newsId=01594086642041328 | c. 25 Jan 2025 | News (Korean, translated) | Snippet only (subagent) |
| R2-S60 | R2 | Starvision 2024 results and Eyecody stake (Korean) | technovalue.com | http://technovalue.com/View.aspx?No=3714390 | 2025 | Trade press (Korean, translated) | Snippet only (subagent) |
| R2-S61 | R2 | Starvision 2025 results and trademark transfer (Korean) | Nate News | https://news.nate.com/view/20260510n01633 | 10 May 2026 | News (Korean, translated) | Snippet only (subagent) |
| R2-S62 | R2 | OLENS Thailand stores (Korean) | Optical Life (안경원라이프) | https://www.opticallife.co.kr/news/articleView.html?idxno=2220 | 29 Sep 2026 | Trade press (Korean, translated) | Snippet only (subagent) |
| R2-S63 | R2 | Starvision–CVC partnership (Korean) | Korea Optic News (한국안경신문) | http://www.opticnews.co.kr/news/articleView.html?idxno=43435 | Jan 2025 | Trade press (Korean, translated) | Snippet only (subagent) |
| R2-S64 | R2 | OLENS Global product page (shipping policy) | OLENS Global | https://www.olensglobal.com/product/1405 | Undated | Brand page | Snippet only (subagent) |
| R2-S65 | R2 | OLENS Global home | OLENS Global | https://www.olensglobal.com/ | Read Oct 2026 | Brand page | Snippet only (subagent) |
| R2-S66 | R2 | PopularLens home (OLENS prices) | PopularLens | https://www.popularlens.com/ | Undated (2026) | Retailer page | Snippet only (subagent) |
| R2-S67 | R2 | Alcon Reward Program T&Cs (Singapore) | Alcon Pte Ltd | https://alconsg.superapp.my/tnc | Effective 1 Jan 2026 | Brand page | Snippet only (subagent) |
| R2-S68 | R2 | Alcon to unveil new MARLO app at SECO 2024 | Alcon | https://www.alcon.com/media-release/alcon-unveil-new-marlo-app-seco-2024/ | 2024 | Press release | Snippet only (subagent) |
| R2-S69 | R2 | CooperVision Singapore Rewards Program | CooperVision Singapore | https://coopervisionsg-rewards.com/ | 1 Aug–31 Oct 2026 | Brand page | Snippet only (subagent) |
| R2-S70 | R2 | Presbyopia campaign page (buy 5 get 1) | CooperVision Singapore | https://coopervision.com.sg/presbyopia | Aug–Oct 2025 | Brand page | Snippet only (subagent) |
| R2-S71 | R2 | MyDay campaign (Capitol-exclusive) | CooperVision Singapore | https://coopervision.com.sg/myday-campaign | Undated | Brand page | Snippet only (subagent) |
| R2-S72 | R2 | Product pages: MyDay range, clariti 1 day, Biofinity, PRECISION1, DAILIES TOTAL1 Astigmatism and Multifocal | Capitol Optical | https://capitol.com.sg/product/myday/ (and sibling product pages) | Undated (live 2026) | Retailer page | Snippet only (subagent) |
| R2-S73 | R2 | DAILIES TOTAL1 product pages | Lensmart; Sin Chew Optics; Clear4Vision | https://lensmart.com.sg/product/dailies-total1/ | Undated (live 2026) | Retailer page | Snippet only (subagent) |
| R2-S74 | R2 | MyDay product page | Hirocon SG | https://hiroconsg.com/products/myday%C2%AE | Undated (live 2026) | Retailer page | Snippet only (subagent) |
| R2-S75 | R2 | Biofinity and clariti product pages | Better Vision | https://www.bettervision.com.sg/product/biofinity/ | Undated (live 2026) | Retailer page | Snippet only (subagent) |
| R2-S76 | R2 | Alcon Inc. Form 20-F FY2025 | US SEC | https://www.sec.gov/Archives/edgar/data/1167379/000116737926000014/alc-20251231.htm | 2026 | Company filing | Snippet only (enrichment) |
| R2-S77 | R2 | A 3-year Randomized Clinical Trial of MiSight Lenses for Myopia Control (Chamberlain P et al., Optom Vis Sci 96(8):556–567) | Optometry and Vision Science | URL not captured in this run (cited by CooperVision Singapore pages S31, S32) | Aug 2019 (pre-window landmark trial; results still the basis of the claim) | Peer-reviewed | Abstract or snippet only (enrichment) |
| R2-S78 | R2 | CooperCompanies Q1 FY2026 earnings call | CooperCompanies | URL not captured in this run | 5 Mar 2026 | Company commentary (transcript) | Snippet only (enrichment) |
| R2-S79 | R2 | CVC press release on Star Vision 49% stake | CVC Capital Partners | URL not captured in this run | 22 Jan 2025 | Company release | Snippet only (enrichment) |
| R3-S01 | R3 | Contact Lens, Owndays SG | Owndays | https://www.owndays.com/sg/en/contact-lens.html | snapshot Oct 2026 | Retailer page | SN |
| R3-S02 | R3 | OWNDAYS Contact Lens Promotion | Owndays | https://www.owndays.com/sg/en/news/bundle-sale | from 1 Sep 2024 | Retailer page | SN |
| R3-S03 | R3 | Owndays Clear Contact Lenses | Owndays | https://www.owndays.com/sg/en/contacts/clear-contactlens | snapshot | Retailer page | SN |
| R3-S04 | R3 | Owndays Ortho-K | Owndays | https://www.owndays.com/sg/en/contacts/orthok-contactlens | snapshot | Retailer page | SN |
| R3-S05 | R3 | Capitol Optical product and category pages (Acuvue, Dailies, B+L, Alcon, homepage) | Capitol Optical | https://capitol.com.sg/product-category/contact-lens/ | c. May to Sep 2026 | Retailer page | SN |
| R3-S07 | R3 | Better Vision homepage | Better Vision | https://www.bettervision.com.sg/ | 1 Oct 2026 | Retailer page | FT |
| R3-S08 | R3 | Subscription FAQs and rewards | Better Vision | https://www.bettervision.com.sg/contact-lens-subscription-exclusive-perks/ | 1 Oct 2026 | Retailer page | FT |
| R3-S09 | R3 | Acuvue Contact Lenses, authorised retailer | W Optics | https://woptics.sg/collections/acuvue | snapshot | Retailer page | SN |
| R3-S10 | R3 | PAssion Card terms, Optical 88; Optical 88 Singapore site | OnePA; Optical 88 | https://www.onepa.gov.sg/passion-card/passion-merchants/optical-88 ; https://www.optical88.com.sg/ | valid to 31 Aug 2026; snapshot | Other; retailer page | SN |
| R3-S11 | R3 | Eye Exam; Privacy Policy | Visio Optical | https://visiooptical.com/services/eye-exam/ ; https://visiooptical.com/privacy-policy/ | c. Mar 2024; 10 Aug 2026 | Retailer page | SN |
| R3-S12 | R3 | Bi-Weekly Acuvue Oasys | Atlantic Optical | https://www.atlanticoptical.com.sg/bi-weekly-acuvue-oasys | undated | Retailer page | SN |
| R3-S13 | R3 | Bausch + Lomb collection | Hirocon SG | https://hiroconsg.com/collections/baush-lomb | undated | Retailer page | SN |
| R3-S14 | R3 | Bausch & Lomb collection | Brighteyes SG | https://brighteyes.com.sg/collections/bausch-lomb | undated | Retailer page | SN |
| R3-S15 | R3 | MyACUVUE Membership Rewards | J&J Vision (ACUVUE SG) | https://www.acuvue.com/en-sg/myacuvue-rewards-benefits/ | 1 Oct 2026 | Brand page | FT |
| R3-S16 | R3 | Frequently asked questions | ACUVUE SG | https://www.acuvue.com/en-sg/faq/ | 1 Oct 2026 | Brand page | FT (answers from snippets) |
| R3-S17 | R3 | MyACUVUE Membership Benefits | ACUVUE SG | https://www.acuvue.com/en-sg/membership-benefits/ | snapshot | Brand page | SN |
| R3-S18 | R3 | Limited Time Promotion | ACUVUE SG | https://www.acuvue.com/en-sg/offers/limited-time-promotion/ | 1 Oct 2026 | Brand page | FT |
| R3-S19 | R3 | ACUVUE with CORTIS | ACUVUE SG | https://www.acuvue.com/en-sg/acuvue-with-cortis/ | 1 Oct 2026 | Brand page | FT |
| R3-S20 | R3 | MAX Fitters | ACUVUE SG | https://www.acuvue.com/en-sg/oasys-max/maxfitters/ | snapshot | Brand page | SN |
| R3-S21 | R3 | MyACUVUE (App Store, Singapore) | Apple / J&J Vision | https://apps.apple.com/sg/app/myacuvue/id1179732283 | snapshot | Brand page | SN |
| R3-S22 | R3 | Think twice about buying contact lenses online; Regulatory measures | HSA; MOH | https://www.hsa.gov.sg/announcements/buying-contact-lenses-online/ ; https://www.moh.gov.sg/newsroom/regulatory-measures-for-ensuring-safe-use-of-contact-lenses/ | c. Aug 2026; undated | Official statement | SN |
| R3-S23 | R3 | Owndays contact lens guide; JB contact lens posts | Lemon8 (consumer posts) | https://www.lemon8-app.com/@vhelory/7371600156136833552?region=sg | c. May 2024 to Mar 2025 | Forum or social | SN |
| R3-S24 | R3 | The Contact Lenses Thread, pages 75, 87, 88 | HardwareZone | https://forums.hardwarezone.com.sg/threads/the-contact-lenses-thread.1734691/page-88 | posts 2017 to Dec 2024 | Forum or social | FT |
| R3-S25 | R3 | Singapore sale calendars 2026 | ShopBack blog; DiveDeals; Miss Lobang | https://www.shopback.sg/blog/finance/sg-2026-post-9-9-sale-calendar-10-10-vs-11-11-vs-12-12-planning | c. Sep 2026 | Blog | SN |
| R3-S26 | R3 | Renu Fresh product pages | Watsons Singapore | https://www.watsons.com.sg/bausch-lomb-renu-fresh-multi-purpose-solution-355ml/p/BP_10129 | undated (c. 2025 to 2026) | Retailer page | SN |
| R3-S27 | R3 | Olens global trial set and product pages; Singapore third-party sellers | Olens; Kpop2; Popular Lens | https://www.olensglobal.com/products | snapshot | Retailer or brand page | SN |
| R3-S28 | R3 | Price promotion research (Oetzel and Luppold 2024; Inderst 2024; Frontiers 2025; Dai et al. field experiment, outside window) | Springer; Wiley; Frontiers; UCLA SSRN | https://link.springer.com/chapter/10.1007/978-3-658-44799-1_24 | 2024 to 2025; Dai c. 2017 | Peer-reviewed | SN |
| R3-S29 | R3 | A review of cosmetic contact lens infections | PMC | https://pmc.ncbi.nlm.nih.gov/articles/PMC6328606 | c. 2019 (outside window; used for the Singapore share) | Peer-reviewed | SN |
| R3-S30 | R3 | Prevalence and pattern of contact lens use in a Singapore community | PubMed (Lee et al.) | https://pubmed.ncbi.nlm.nih.gov/10656305/ | 2000 (outside window; only Singapore survey on who influences lens choice, and very dated) | Peer-reviewed | SN |
| R3-S31 | R3 | Gone Viral: contact lens videos on TikTok | PubMed | https://pubmed.ncbi.nlm.nih.gov/36044821/ | c. Nov 2022 (outside window; only content analysis found) | Peer-reviewed | SN |
| R3-S32 | R3 | Beyond Vision report | Contact Lens Institute (US) | https://www.contactlensinstitute.org/wp-content/uploads/2024/04/CLI-Beyond-Vision-Report-Spring-2024-FINAL.pdf | Spring 2024 | Other (US, non-Singapore) | SN (access blocked) |
| R3-S33 | R3 | J&J Vision opens ACUVUE Online Store on Shopee (Thailand) | Press release | https://www.ryt9.com/en/prg/220152 | Nov 2018 (outside window; only SE Asia precedent; non-Singapore) | News | SN |
| R3-S34 | R3 | Contact Lens Rebates 2026 | contactlenshq.com (US) | https://contactlenshq.com/contact-lens-rebates/ | c. Aug 2026 | Blog (non-Singapore) | SN |
| R3-S35 | R3 | CooperVision Singapore; MyDay participating outlets | CooperVision | https://coopervision.com.sg/ | snapshot; outlet list c. 2017 | Brand page | SN |
| R3-S36 | R3 | Alcon contact lenses (US) | Alcon | https://www.myalcon.com/contact-lenses/ | c. Feb 2026 | Brand page (non-Singapore) | SN |
| R3-S37 | R3 | Online Singapore lens sellers (SGCONS, Contactsdaily, Popular Lens, Lensza) | Retailers | https://sgcons.com/ | c. 2024 to 2026 | Retailer page | SN |
| R3-S40 | R3 | Acuvue Contact Lenses, Lenskart SG | Lenskart | https://www.lenskart.sg/contact-lenses/most-popular-contact-lenses/acuvue-contact-lenses.html | undated | Retailer page | SN |
| R4-S01 | R4 | Contact Lens FAQs: MyACUVUE, Age & Maintenance | Johnson & Johnson Vision (ACUVUE SG) | https://www.acuvue.com/en-sg/faq/ | undated (accessed Oct 2026) | retailer or brand page | full text read (answers partly from snippet) |
| R4-S02 | R4 | MyACUVUE Membership Rewards | ACUVUE SG | https://www.acuvue.com/en-sg/myacuvue-rewards-benefits/ | undated | retailer or brand page | abstract or snippet only |
| R4-S03 | R4 | Frequently asked questions (VIP, caps) | ACUVUE SG | https://www.acuvue.com.sg/frequently-asked-questions | undated | retailer or brand page | abstract or snippet only |
| R4-S04 | R4 | MyACUVUE Gamification Campaign T&C / Privacy | Johnson & Johnson Pte Ltd | https://www.acuvue.com.sg/myacuvue-privacy-policy | undated | retailer or brand page | abstract or snippet only |
| R4-S05 | R4 | MyACUVUE – App Store (Singapore) | Apple | https://apps.apple.com/sg/app/myacuvue/id1179732283 | reviews 2018–2022; listing accessed Oct 2026 | forum or social (app reviews) / other | full text read |
| R4-S06 | R4 | MyACUVUE – App Store (Malaysia) | Apple | https://apps.apple.com/my/app/myacuvue/id1179732283 | review 22 Oct 2024 | forum or social (app reviews) | abstract or snippet only |
| R4-S07 | R4 | MyACUVUE – Google Play | Google | https://play.google.com/store/apps/details?id=com.jnj.myacuvue.consumer&hl=en | reviews Apr 2024–Feb 2025; updated 31 Aug 2026 | forum or social (app reviews) | full text read |
| R4-S08 | R4 | MyACUVUE PRO – Google Play | Google | https://play.google.com/store/apps/details?id=com.jnj.myacuvue.pro.production&hl=en_SG | undated | retailer or brand page | abstract or snippet only |
| R4-S09 | R4 | MyAcuvue App | Tampines Optical | https://www.tampinesoptical.com/myacuvue-app/ | undated | retailer or brand page | abstract or snippet only |
| R4-S10 | R4 | ACUVUE | Eye Gen | https://www.eyegen.com.sg/acuvue.html | undated | retailer or brand page | abstract or snippet only |
| R4-S11 | R4 | ACUVUE Referral Promotion | sgreferralpromo.com | https://sgreferralpromo.com/post/acuvue-referral-promotion/ | updated 2 Jan 2026 | blog | abstract or snippet only |
| R4-S12 | R4 | J&J Vision to pioneer integrated eye health ecosystem in Singapore | Singapore EDB | https://www.edb.gov.sg/en/about-edb/media-releases-publications/johnson-and-johnson-vision-to-pioneer-integrated-eye-health-ecosystem-in-singapore.html | 17 Aug 2021 (pre-window) | company filing / official release | abstract or snippet only |
| R4-S13 | R4 | A*STAR and J&J Vision ink MoU for eye health digital innovation consortium | A*STAR | https://www.a-star.edu.sg/News/astarNews/news/press-releases/a-star-and-johnson-johnson-vision-ink-mou-for-eye-health-digital-innovation-consortium | 12 Jul 2022 (pre-window) | official release | abstract or snippet only |
| R4-S14 | R4 | J&J Vision, A*STAR forge partnership | Healthcare IT News | https://www.healthcareitnews.com/news/asia/johnson-johnson-vision-singapores-astar-forge-partnership-set-digital-eye-health | pre-window | trade press | abstract or snippet only |
| R4-S15 | R4 | CooperVision SG Rewards Program | CooperVision Singapore | https://coopervisionsg-rewards.com/ | programme 1 Aug–31 Oct 2026 | retailer or brand page | abstract or snippet only (fetch returned no content) |
| R4-S16 | R4 | Purchase MyDay and receive Starbucks Gift Cards | CooperVision Singapore | https://coopervision.com.sg/myday-campaign | undated | retailer or brand page | abstract or snippet only |
| R4-S17 | R4 | MyDay Participating Outlets | CooperVision Singapore | https://coopervision.com.sg/myday-campaign-outlets | undated | retailer or brand page | abstract or snippet only |
| R4-S18 | R4 | Alcon Reward Program – FAQ | Alcon (via superapp.my) | https://alconsg.superapp.my/faq | 2026 enrolment period | retailer or brand page | full text read |
| R4-S19 | R4 | Alcon Reward Program – T&C | Alcon (via superapp.my) | https://alconsg.superapp.my/tnc | 2026 | retailer or brand page | abstract or snippet only |
| R4-S20 | R4 | LACELLE GWP promotion T&C | Bausch + Lomb Singapore | https://www.bausch.com.sg/promotion/t-and-c2/ | 1 Oct–31 Dec 2025 | retailer or brand page | abstract or snippet only (via subagent) |
| R4-S21 | R4 | ULTRA Monthly GWP | Bausch + Lomb Singapore | https://www.bausch.com.sg/promotion-sh/ | Jul–Sep 2021 (pre-window) | retailer or brand page | abstract or snippet only (via subagent) |
| R4-S22 | R4 | OLENS – App Store (Singapore) | Apple / Starvision | https://apps.apple.com/sg/app/olens/id6740471164 | v1.0.1 18 Dec 2025; accessed Oct 2026 | retailer or brand page | full text read (via subagent) |
| R4-S23 | R4 | OLENS Global Membership | OLENS Global | https://www.olensglobal.com/membership | undated | retailer or brand page | abstract or snippet only |
| R4-S24 | R4 | $10 for monthly OLENS – where to buy | Lemon8 | https://www.lemon8-app.com/@eaturice/7220092277434171905?region=sg | c. Apr 2023 (inferred; pre-window) | forum or social | abstract or snippet only |
| R4-S25 | R4 | Cheap Contact Lens Singapore: Where To Buy Safely (2026) | PopularLens | https://www.popularlens.com/cheap-contact-lens-singapore-where-to-buy/ | 2026 | retailer or brand page | abstract or snippet only |
| R4-S26 | R4 | Contact Lens Reminder App | ContactsAsia | https://contactsasia.com/pages/contact-lens-reminder-app | undated | retailer or brand page | abstract or snippet only |
| R4-S27 | R4 | Frequently-asked Questions | ContactsAsia | https://contactsasia.com/pages/faq | c. 2022 | retailer or brand page | abstract or snippet only |
| R4-S28 | R4 | Contact Lens category | Better Vision | https://www.bettervision.com.sg/product-category/contact-lens/ | undated | retailer or brand page | abstract or snippet only |
| R4-S29 | R4 | The Contact Lenses Thread (page 87) | HardwareZone Forums | https://forums.hardwarezone.com.sg/threads/the-contact-lenses-thread.1734691/page-87 | posts Oct 2021–Oct 2022 | forum or social | full text read |
| R4-S30 | R4 | Which website to get cheapest contact lens? | HardwareZone Forums | https://forums.hardwarezone.com.sg/threads/which-website-to-get-cheapest-contact-lens.6247830/ | undated | forum or social | abstract or snippet only |
| R4-S31 | R4 | The Contact Lenses Thread (page 58) | HardwareZone Forums | https://forums.hardwarezone.com.sg/threads/the-contact-lenses-thread.1734691/page-58 | undated (pre-window) | forum or social | abstract or snippet only |
| R4-S32 | R4 | The Contact Lenses Thread (pages 63/64) | HardwareZone Forums | https://forums.hardwarezone.com.sg/threads/the-contact-lenses-thread.1734691/page-63 | undated (pre-window) | forum or social | abstract or snippet only |
| R4-S33 | R4 | How I Saved Over S$90 on Contact Lenses by Buying from Kiyomi Optometrist in JB | Lemon8 | https://www.lemon8-app.com/@thelazicatt/7373271135464522256?region=sg | c. May 2024 (inferred) | forum or social | full text read |
| R4-S34 | R4 | OWNDAYS Contact Lens Experience: A Beginner's Guide | Lemon8 | https://www.lemon8-app.com/@vhelory/7371600156136833552?region=sg | c. May 2024 (inferred) | forum or social | abstract or snippet only |
| R4-S35 | R4 | THINK before getting contact lens from owndays | Lemon8 | https://www.lemon8-app.com/pochismode/7353544507847213585?region=sg | c. Apr 2024 (inferred) | forum or social | abstract or snippet only |
| R4-S36 | R4 | First Time Trying Contact Lenses? | Lemon8 | https://www.lemon8-app.com/@cynthiaaxy_/7258510170370703873?region=sg | c. Jul 2023 (inferred; pre-window) | forum or social | abstract or snippet only |
| R4-S37 | R4 | Best contact lens ever + free trial (astig) | Lemon8 | https://www.lemon8-app.com/@joyce.ngz/7225653266154226178?region=sg | c. Apr 2023 (inferred; pre-window) | forum or social | abstract or snippet only |
| R4-S38 | R4 | The best local contact lens ever? | Lemon8 | https://www.lemon8-app.com/fathiahrahim/7332350015660163585?region=sg | c. Feb 2024 (inferred) | forum or social | abstract or snippet only |
| R4-S39 | R4 | MiSight 1 Day: Myopia Control for Kids in Singapore | Emme Vision Care | https://www.emmevisioncare.com/misight-1-day-myopia-control-lens-for-children | undated | retailer or brand page | abstract or snippet only |
| R4-S40 | R4 | Myopia Care in 2026: Current Trends and Best Practices | Singapore Optometric Association | https://singaporeoptometricassociation.com/current-myopia-care-trends-2026/ | 2026 | other (professional body) | abstract or snippet only |
| R4-S41 | R4 | Ways to Spend Child LifeSG Credits on Your Child's Eye Care | Raylite Optical | https://www.rayliteoptical.com.sg/blogs/news/tagged/ortho-k | 17 Aug 2026 | blog (retailer) | abstract or snippet only |
| R4-S42 | R4 | Myopia in Singapore Children: What Parents Should Know | Eye Cataract Retina clinic | https://eyecataractretina.com/blog/myopia-in-singapore-children-what-parents-should-know | undated | blog (clinic) | abstract or snippet only |
| R4-S43 | R4 | 2024新加坡配眼镜及隐形眼镜攻略 (2024 Singapore glasses and contact lens guide; Chinese) | Extrabux | https://www.extrabux.com/chs/guide/7784896 | 2024 | blog | abstract or snippet only |
| R4-S44 | R4 | 新加坡10家平价眼镜店 (10 budget optical shops in Singapore; Chinese) | Toutiao SG | https://toutiaosg.com/%E6%96%B0%E5%8A%A0%E5%9D%A110%E5%AE%B6%E5%B9%B3%E4%BB%B7%E7%9C%BC%E9%95%9C%E5%BA%97%E8%B5%B6%E7%B4%A7%E6%94%B6%E8%97%8F%E6%89%93%E5%8D%A1%EF%BC%81%E4%B9%B01%E9%80%811%E3%80%81%E8%B5%A0%E7%9C%BC | undated | news / blog | abstract or snippet only |
| R4-S45 | R4 | ACUVUE Abiliti – Singapore | Facebook (J&J Vision) | https://www.facebook.com/acuvueabilitisg/ | undated | retailer or brand page | abstract or snippet only |
| R4-S46 | R4 | Qoo10 deals thread, page 126 | HardwareZone Forums | https://forums.hardwarezone.com.sg/threads/qoo10-deals-strictly-no-referral-link-part-5.5735021/page-126 | c. Feb 2018 (pre-window) | forum or social | abstract or snippet only (via subagent) |
| R4-S47 | R4 | Dailies Total 1 (Buy 3 get 1 free) | Hirocon SG | https://hiroconsg.com/products/dailies-total-1%C2%AE-buy-3-get-1-free | undated | retailer or brand page | abstract or snippet only |
| R4-S48 | R4 | Alcon Dailies Total1 | Eyechamp | https://www.eyechamp.com.sg/product/dailies-total1 | undated | retailer or brand page | abstract or snippet only |
| R4-S49 | R4 | Why Singaporeans Love OLENS SG | PopularLens | https://www.popularlens.com/reasons-to-choose-olens-sg/ | undated | blog (retailer marketing) | abstract or snippet only |
| R4-S50 | R4 | A 3-Year Randomized Clinical Trial of MiSight Lenses for Myopia Control (Chamberlain et al.; NCT01729208) | Optometry and Vision Science 96(8):556–567 | https://pubmed.ncbi.nlm.nih.gov/?term=Chamberlain+MiSight+3-year+randomized+clinical+trial | 2019 (pre-window; landmark trial) | peer-reviewed | abstract or snippet only (via enricher) |
| R4-S51 | R4 | Coverage of J&J Vision Singapore eye health ecosystem announcement | BioSpectrum Asia | not captured (via enricher) | Aug 2021 (pre-window) | trade press | abstract or snippet only (via enricher) |

## Table B. Scraped and project sources

| Log ID | Origin | Description | Location | URL | Date range | Type | Read depth / notes |
|---|---|---|---|---|---|---|---|
| SC-YT | SC | YouTube videos (172) and comments (1,256), search-keyword and channel pulls, 5 brands | Scripts/output/youtube_data_sg.db (yt_videos, yt_comments) | n/a (scraped) | videos 2009-Sep 2026; comments 2019-2026 | Scraped social (platform: global audience, SG search tag) | Full dataset queried; GPT-4o-mini sentiment 1,256/1,256 |
| SC-IG | SC | Instagram posts (158) and comments (185), hashtag/account pulls | Scripts/output/instagram_data_sg.db | n/a (scraped) | Feb 2022-Sep 2026 | Scraped social | Full dataset queried; comments only for brand+market-relevant posts |
| SC-FB | SC | Facebook brand-page posts (120) and comments (33); no Alcon | Scripts/output/facebook_data_sg.db | n/a (scraped) | Sep 2025-Sep 2026 | Scraped social (brand-owned pages) | Full dataset queried |
| SC-RD | SC | Reddit posts (57) and comments (95) | Scripts/output/reddit_data_sg.db | n/a (scraped) | 2014-Sep 2026 | Scraped forum | Full dataset queried; brand tag = search keyword |
| SC-XHS | SC | Xiaohongshu posts (711, ZH+EN) and comments (156) | Scripts/output/xhs_data_sg.db | n/a (scraped) | epoch dates 2015-Sep 2026 | Scraped social | Full dataset queried; 220/711 originally tagged, 203 relevant added 1 Oct |
| SC-KP | SC | KiasuParents forum threads (41) | Scripts/output/sg_acuvue.db (forum_posts) | n/a (scraped) | Aug-Oct 2023 | Scraped forum | Full dataset queried |
| SC-LZR | SC | Lazada SG product reviews (92: ACUVUE 24, Alcon 38, B+L 30) | Scripts/output/sg_acuvue.db (reviews) | n/a (scraped) | Mar 2020-Sep 2026 | Scraped marketplace reviews | Full dataset queried |
| SC-PRD | SC | Lazada SG (40) and TikTok Shop SG (103) listings with price/promo, 143 total | Scripts/output/sg_acuvue.db (products) | n/a (scraped) | 23-25 Sep 2026 | Scraped marketplace listings | Full dataset queried |
| SC-APP-GP | SC | MyACUVUE Google Play reviews (95 written; store-wide 3.32 from 1,113 ratings) | Scripts/output/app_data_sg.db | n/a (scraped) | May 2017-Sep 2026 | Scraped app-store reviews | Full dataset queried; all 77 low-star reviews read |
| SC-APP-AS | SC | MyACUVUE Apple App Store SG reviews (24 written; 70 ratings, 2.36) | Scripts/output/app_data_sg.db | n/a (scraped) | Jul 2017-May 2026 | Scraped app-store reviews | Full dataset queried |
| SC-GM | SC | Google Maps reviews for 6 optical chains (4,771 reviews; 88 outlets; 199 strictly contact-lens reviews) | Scripts/output/gmaps_data_sg.db | n/a (scraped) | Dec 2015-Sep 2026 | Scraped retailer reviews | Full dataset queried; newest 100 per outlet |
| SC-GT | SC | Google Trends SG weekly index, 13 terms, 262 weeks | Scripts/output/trends_data_sg.db | n/a (scraped) | 26 Sep 2021-27 Sep 2026 | Scraped search-interest index | Full dataset queried; index not volume |
| SC-CT | SC | UN Comtrade HS 9001.30 Singapore imports/exports 2023-2025 (6 rows) | Scripts/output/UN Comtrade Database SG Lenses.csv | n/a (official statistic) | 2023-2025 | Official statistic | Full file read |
| SC-INV | SC | Project data inventory and EBI plan (data.md, EBI_insights_plan.md, Logs/summary.md): documented weaknesses and dashboard-coded counts (e.g. 47/77 app friction, 40 flagged lens listings) | project root | n/a (internal documents) | snapshot 30 Sep-1 Oct 2026 | Internal documentation (not independent of scraped data) | Read in full |

## Table C. Run status
| Run | Status |
|---|---|
| R1 | Complete (no hypotheses assigned; lighter search tool; abstracts mostly) |
| R2 | Complete but short of 25-query target (18 + 2 failed); H1, H2 |
| R3 | Cut short (credits); 32 queries; H3, H5a, H5b, H5c; marketplace pages not retrievable |
| R4 | Complete; 18 queries + 1 subagent (below 25-query target); H4 |