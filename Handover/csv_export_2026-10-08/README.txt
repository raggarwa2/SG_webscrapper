SG contact-lens project: data handover (CSV export)
Created 2026-10-08 11:19 by Scripts/export_databases_to_csv_for_handover.py

Folders
  01_raw_scraped/             Data as collected from each channel. One folder per
                              source database, one CSV per table. Some tables also
                              carry columns added at scrape time (translation,
                              model sentiment, journey stage); these are labelled
                              as such in DATA_DICTIONARY.csv by column name.
  02_tagged_and_consolidated/ Built from the raw data. voice_items is every comment,
                              post and review in one table (key: item_id); voice_tags
                              holds the model's sentiment, themes and journey stage
                              per item_id. voice_tags contains every tag version;
                              filter to the latest taxonomy_version before counting.
  MANIFEST.csv                Every file, its source, rows in the database, rows in
                              the CSV, and a check (ok / MISMATCH / skipped).
  DATA_DICTIONARY.csv         Every column of every table with its type.

Reading the files
  - UTF-8 with byte-order mark: Excel opens it directly; Python: encoding="utf-8-sig".
  - Text fields can contain line breaks inside quotes. Use a CSV reader.
  - Empty cell = no value (NULL) in the database.
  - Dates are as stored by each scraper (mostly ISO text); they are not unified in
    the raw folders. voice_items has one unified date column.

Not included
  Database backups, "before_*" snapshots, and test databases (see "skipped" rows
  in MANIFEST.csv). API keys and .env files are never read.
