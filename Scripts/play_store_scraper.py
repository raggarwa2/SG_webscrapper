import sqlite3
import time
from pathlib import Path
from google_play_scraper import reviews, Sort

# Strict output pathing to the consolidated directory
DB_PATH = Path(__file__).resolve().parent / "output" / "app_data_sg.db"

def init_db():
    DB_PATH.parent.mkdir(parents=True, exist_ok=True)
    conn = sqlite3.connect(DB_PATH)
    cursor = conn.cursor()
    
    # Create the app_reviews table with a composite primary key
    cursor.execute('''
        CREATE TABLE IF NOT EXISTS app_reviews (
            store TEXT,
            country TEXT,
            review_id TEXT,
            rating INTEGER,
            title TEXT,
            text TEXT,
            date TEXT,
            app_version TEXT,
            developer_reply TEXT,
            PRIMARY KEY (store, country, review_id)
        )
    ''')
    conn.commit()
    return conn

def scrape_play_store(conn, package_name='com.jnj.myacuvue.consumer', country='sg', lang='en'):
    cursor = conn.cursor()
    continuation_token = None
    total_reviews = 0

    print(f"Starting extraction for {package_name} in {country.upper()}...")

    while True:
        # Use the reviews() function with a continuation_token in a while loop
        result, continuation_token = reviews(
            package_name,
            lang=lang,
            country=country,
            sort=Sort.NEWEST,
            count=100,
            continuation_token=continuation_token
        )
        
        if not result:
            break

        for rev in result:
            # ON CONFLICT DO UPDATE clause during ingestion to handle rewritten reviews
            cursor.execute('''
                INSERT INTO app_reviews 
                (store, country, review_id, rating, title, text, date, app_version, developer_reply)
                VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?)
                ON CONFLICT(store, country, review_id) DO UPDATE SET
                    rating=excluded.rating,
                    title=excluded.title,
                    text=excluded.text,
                    date=excluded.date,
                    app_version=excluded.app_version,
                    developer_reply=excluded.developer_reply
            ''', (
                'play_store',
                country,
                rev['reviewId'],
                rev['score'],
                None, # Title is generally not used in Play Store reviews
                rev['content'],
                str(rev['at']),
                rev['reviewCreatedVersion'],
                rev.get('replyContent') 
            ))
        
        conn.commit()
        total_reviews += len(result)
        print(f"Saved {total_reviews} reviews...")
        
        if not continuation_token:
            break
            
        # Add a 1-2 second sleep between pages to ensure safe capture
        time.sleep(1.5)

    print("Extraction complete.")

if __name__ == "__main__":
    db_connection = init_db()
    
    # Scrape the SG storefront requesting English
    scrape_play_store(db_connection, package_name='com.jnj.myacuvue.consumer', country='sg', lang='en')
    
    db_connection.close()