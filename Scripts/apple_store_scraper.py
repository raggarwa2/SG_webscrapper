import sqlite3
import time
from pathlib import Path
from app_store_web_scraper import AppStoreEntry

# Route directly into the consolidated output directory
DB_PATH = Path(__file__).resolve().parent / "output" / "app_data_sg.db"

def init_db():
    DB_PATH.parent.mkdir(parents=True, exist_ok=True)
    conn = sqlite3.connect(DB_PATH)
    cursor = conn.cursor()
    
    # Uses the composite primary key to prevent duplicate review entries
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

def scrape_app_store(conn, app_id=1179732283, country='sg'):
    cursor = conn.cursor()
    total_reviews = 0
    
    # Initialize the App Store entry for the target country
    app = AppStoreEntry(app_id=app_id, country=country)
    
    print(f"Starting Apple App Store extraction for ID {app_id} in {country.upper()}...")
    
    # Iterate lazily over batches to bypass RSS limits
    for review in app.reviews():
        developer_response = review.developer_response.body if review.developer_response else None
        
        cursor.execute('''
            INSERT INTO app_reviews 
            (store, country, review_id, rating, title, text, date, app_version, developer_reply)
            VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?)
            ON CONFLICT(store, country, review_id) DO UPDATE SET
                rating=excluded.rating,
                title=excluded.title,
                text=excluded.text,
                date=excluded.date,
                developer_reply=excluded.developer_reply
        ''', (
            'app_store',
            country,
            str(review.id),
            review.rating,
            review.title,
            review.review,
            str(review.date),
            None, # Apple does not reliably expose the exact review version via web endpoints
            developer_response
        ))
        
        total_reviews += 1
        
        # Commit in batches and apply a polite delay
        if total_reviews % 50 == 0:
            conn.commit()
            print(f"Saved {total_reviews} reviews...")
            time.sleep(1) 
            
    conn.commit()
    print(f"Extraction complete. Total reviews saved: {total_reviews}")

if __name__ == "__main__":
    db_connection = init_db()
    
    # Scrape the SG storefront for MyACUVUE
    scrape_app_store(db_connection, app_id=1179732283, country='sg')
    
    db_connection.close()