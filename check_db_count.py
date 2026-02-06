import psycopg2
import os
from dotenv import load_dotenv
from datetime import datetime

# Load .env explicitly if needed, or rely on environment variables being set
load_dotenv('c:\\WorkSpace\\Syndeo\\KoreaPolitician\\.env')

def check_count():
    try:
        conn = psycopg2.connect(
            host=os.getenv('POSTGRES_HOST', 'localhost'),
            database=os.getenv('POSTGRES_DB', 'korea_politician'),
            user=os.getenv('POSTGRES_USER', 'postgres'),
            password=os.getenv('POSTGRES_PASSWORD', 'password'),
            port=os.getenv('POSTGRES_PORT', '5432')
        )
        cur = conn.cursor()
        today = datetime.now().strftime('%Y%m%d')
        cur.execute(f"SELECT count(*) FROM public.news_sentiment WHERE base_date = '{today}'")
        count = cur.fetchone()[0]
        print(f"Today ({today}) Saved Count: {count}")
        
        # Check some sample titles
        cur.execute(f"SELECT title FROM public.news_sentiment WHERE base_date = '{today}' LIMIT 3")
        rows = cur.fetchall()
        print("Sample Articles:")
        for row in rows:
            print(f"- {row[0]}")
            
        cur.close()
        conn.close()
    except Exception as e:
        print(f"DB Error: {e}")

if __name__ == "__main__":
    check_count()
