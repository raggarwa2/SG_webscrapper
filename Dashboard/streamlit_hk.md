# Streamlit Dashboard Build Prompt

Paste this entire section into Claude Code for your next project to reference how the previous Streamlit app was built.

---

## Project Context: What Was Built

I built a **Streamlit multi-page dashboard** for a Contact Lens Intelligence Pipeline (market research tool for APAC). The dashboard reads from:
- **SQLite database** (`output/lensdata.db`) — contains products, reviews, pricing, store data
- **CSV files** (`pricing.csv`, `distribution.csv`, `reputation.csv`, `new_launches.csv`, `news_partnerships.csv`, `public_listings.csv`) — research findings manually transcribed from deep-dive research
- **Excel reports** (`store_analysis_YYYYMMDD.xlsx`) — auto-generated after each pipeline run

---

## Architecture Overview

### Tech Stack
- **Frontend:** Streamlit (Python-based, no JavaScript needed)
- **Backend:** SQLite3 (local file database)
- **Data:** Pandas (SQL queries → DataFrames → Streamlit tables)
- **Visualization:** Plotly (charts, rankings, sentiment analysis)
- **Config:** YAML (to define which markets, brands, and sites are active)
- **Main file:** `app.py` (~7500 lines) — entry point for `streamlit run app.py`

### File Structure
```
G:\My Drive\G_Business\AI Native SMB\Web scrapper\
├── app.py                          ← Main Streamlit app (this is what you run)
├── pipeline_v2.py                  ← Backend: web scraper that populates the DB
├── analyse_stores.py               ← Generates Excel reports from DB data
├── config.yaml                     ← All config: brands, markets, keywords
├── requirements.txt                ← Dependencies (streamlit, pandas, plotly, pyyaml)
├── output/
│   ├── lensdata.db                 ← SQLite database (auto-created)
│   ├── store_analysis_YYYYMMDD.xlsx ← Excel reports (auto-generated)
│   └── *.log                       ← Pipeline run logs
└── pricing.csv, distribution.csv, ... ← Manual research CSVs
```

---

## How the Streamlit App Works

### Page 1: Dashboard
- Multi-tab layout: **Overview**, **Store Rankings**, **Price Comparison**, **All Reviews**
- **Overview tab:**
  - Summary stats: total products, total reviews, avg rating per brand
  - Top stores ranked by rating
  - Recent activity timeline
- **Store Rankings tab:**
  - Heatmap/table: Brand × Store, colored by customer sentiment (avg_rating)
  - Hover to see review count, discount %, price position vs brand avg
- **Price Comparison tab:**
  - Line chart: brand price trends over time
  - Scatter: price vs rating (does cheaper = worse reviews?)
- **All Reviews tab:**
  - Full table: every review, with Chinese → English translation, date, rating, store

### Page 2: Research Findings
- Six subsections (one per research pillar):
  1. **Pricing** — where are brands discounted? by how much?
  2. **Distribution** — which stores carry which brands? gaps?
  3. **Reputation** — what do customers say? sentiment analysis
  4. **New Product Launches** — upcoming SKUs, markets, dates
  5. **News & Partnerships** — brand moves, retail partnerships
  6. **Public Listing Signals** — earnings calls, investor data on brand expansion
- Each section reads from a CSV (`pricing.csv`, `distribution.csv`, etc.)
- **Geo-Validation Audit:** every row has a `geo_validated` column (Yes/No). App shows audit summary: how many rows per pillar, % validated.

### Page 3: Raw Database (Admin)
- Two tabs:
  - **Products:** raw SQL query → table of all products (searchable, sortable)
  - **Reviews:** raw SQL query → table of all reviews (with original Chinese + English translation)
- Used for debugging, spot-checks, or exporting for further analysis

---

## Data Sources and Schema

### SQLite Database (`lensdata.db`)

**Products table:**
```
id, brand, product_name, site, store_name, selling_price, original_price, 
avg_rating, review_count, url, discovered_at, last_updated
```

**Reviews table:**
```
id, product_id, review_text_chinese, review_text_english, rating, 
author_name, review_date, site, store_name, created_at
```

**Key insights the app calculates:**
- Discount % = (original_price - selling_price) / original_price
- Review language auto-detected (Traditional Chinese → English via GPT-4o-mini)
- Review sentiment inferred from rating (1-5 stars)

### CSV Files (Manual Research)

Each CSV has columns:
- `market` (HK, TH, SG, MY, etc.)
- `brand`
- Source/finding details (varies per pillar)
- `source_url` (link to the research source)
- `geo_validated` (Yes/No — from geo-validation audit in CONTEXT.md Section 4)

Example rows:
- **pricing.csv:** market, brand, product, store, selling_price, currency, date, url, geo_validated
- **distribution.csv:** market, brand, retailer, status (Present/Absent), url, geo_validated
- **reputation.csv:** market, brand, platform (Discuss.com.hk, etc.), date, language, sentiment (positive/negative/neutral), review_text, url, geo_validated

---

## Key Implementation Patterns

### 1. Multi-Page Routing (Streamlit Pages API)
```
app.py uses streamlit.pages.Page to define:
  - pages/1_Dashboard.py
  - pages/2_Research_Findings.py
  - pages/3_Admin_Database.py
```

### 2. Database Queries (Pandas + SQLite)
```python
import sqlite3
import pandas as pd

conn = sqlite3.connect('output/lensdata.db')
df = pd.read_sql("SELECT * FROM products WHERE brand = 'Acuvue'", conn)
```

### 3. Streamlit Components
- `st.metric()` — displays summary stats (products count, avg rating)
- `st.table()` — displays static tables
- `st.dataframe()` — interactive, sortable, searchable
- `st.plotly_chart()` — Plotly charts (heatmaps, line charts, scatter)
- `st.tabs()` — creates tab UI
- `st.sidebar` — sidebar filters (e.g., filter by brand/market/date range)
- `st.file_uploader()` — allows users to upload CSV research files
- `st.cache_data` — caches queries to avoid recomputing on every page load

### 4. Sidebar Filters
The app typically has a sidebar with:
- **Date range picker** (start_date, end_date)
- **Brand multi-select** (checkboxes for each brand in config)
- **Market multi-select** (HK, TH, SG, etc.)
- **Store filter** (dropdown or multi-select)
- **Sentiment filter** (for reviews: positive, negative, neutral)

Filters dynamically reload tables and charts.

### 5. Config-Driven (YAML)
```yaml
# config.yaml
markets:
  HK:
    time_window_months: 12
    sites:
      - hktvmall
      - 393lens
    brands:
      - name: Acuvue
      - name: Alcon
      - name: "Bausch & Lomb"
```

The app reads `config.yaml` at startup to:
- Populate brand/market dropdowns
- Validate that selected filters are in scope
- Show "not yet in scope" message if user filters for brands/markets not in config

---

## Running the App

### Prerequisites
1. Python 3.10+ installed
2. Dependencies: `pip install streamlit pandas plotly pyyaml`
3. Database must exist: `output/lensdata.db` (created by `pipeline_v2.py` on first run)
4. CSV files (optional): `pricing.csv`, `distribution.csv`, etc. in the project root

### Run the App
```bash
cd "G:\My Drive\G_Business\AI Native SMB\Web scrapper"
streamlit run app.py
```

Streamlit opens a local dev server at `http://localhost:8501`. Edits to `app.py` auto-reload.

### Deployment (optional)
- **Streamlit Cloud:** push to GitHub, connect GitHub repo to Streamlit Cloud, auto-deploys
- **Docker:** containerize with `Dockerfile`, push to AWS/GCP
- **Local scheduled run:** Windows Task Scheduler or cron to run `streamlit run app.py` on a schedule

---

## GitHub Integration (if used)

The project likely has:
- A GitHub repo (e.g., `github.com/your-org/lens-intelligence-pipeline`)
- A `push_to_github.py` script that commits new data after each pipeline run
- GitHub Actions CI/CD (optional): auto-run pipeline on schedule, commit results

Key files pushed to GitHub:
- `app.py` (Streamlit app code)
- `pipeline_v2.py` (scraper code)
- `config.yaml` (brands, markets, keywords)
- `requirements.txt` (Python dependencies)
- `.env` (API keys, secrets — gitignored)
- CSVs (research findings — may be in a separate private repo to protect research)
- Logs and database are **not** pushed (they're in `.gitignore`)

---

## Data Flow (End-to-End)

```
1. Run pipeline_v2.py
   ↓ discovers products via HKTVmall API + 393lens Playwright
   ↓ extracts reviews via Playwright + GPT-4o-mini translation
   ↓ writes to output/lensdata.db
   ↓ pushes to GitHub (optional)

2. Run analyse_stores.py
   ↓ reads lensdata.db
   ↓ generates store_analysis_YYYYMMDD.xlsx (4 sheets)
   ↓ saves to output/

3. Open app.py in Streamlit
   ↓ reads lensdata.db for dashboards
   ↓ reads *.csv files for research findings
   ↓ reads store_analysis*.xlsx for drill-down
   ↓ displays interactive dashboards and tables
   ↓ users filter by brand/market/date/store
```

---

## For Your Next Project

When building a similar Streamlit dashboard:

1. **Identify your data source:**
   - SQLite database? CSV files? API? Google Sheets? All of above?
   
2. **Define your pages and tabs:**
   - How many pages do you need? (dashboard, reports, admin, settings?)
   - What tabs per page? (overview, trends, details, raw data?)
   
3. **Design your sidebar filters:**
   - What dimensions do users want to slice by? (date, category, region, sentiment, status?)
   - Should filters be multi-select or single-select?
   
4. **Choose your visualizations:**
   - Heatmaps for rank comparisons (Plotly `imshow`)
   - Line charts for trends (Plotly `line`)
   - Bar charts for rankings (Plotly `bar`)
   - Scatter plots for correlation (Plotly `scatter`)
   - Tables for details (Streamlit `st.dataframe()`)
   
5. **Add interactivity:**
   - Use `@st.cache_data` to cache expensive queries
   - Use sidebar filters to dynamically reload charts
   - Use `st.columns()` for side-by-side layouts
   - Use `st.expander()` for collapsible sections
   
6. **Push to GitHub and deploy:**
   - Use Streamlit Cloud, Docker, or AWS for hosting
   - Set up CI/CD if data auto-updates

---

## Common Pitfalls to Avoid

1. **Don't run queries on every page load** → use `@st.cache_data(ttl=3600)` to cache
2. **Don't mix data loading and display logic** → separate into functions
3. **Don't hardcode credentials** → use `.env` and `os.getenv()`
4. **Don't assume database exists** → add init script that creates tables if missing
5. **Don't forget CSV headers** → CSVs must have headers for Streamlit to read correctly
6. **Don't forget timezone handling** → dates should be in ISO format (YYYY-MM-DD)
7. **Don't skip `@st.cache_data`** → apps will be slow without it

---

**End of prompt. Use this to guide your next Streamlit build!**
