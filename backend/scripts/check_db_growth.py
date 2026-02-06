import psycopg2
import os
from datetime import datetime, timedelta

def check_db_growth():
    db_config = {
        'host': os.environ.get('POSTGRES_HOST', 'localhost'),
        'port': 5432,
        'user': os.environ.get('POSTGRES_USER', 'postgres'),
        'password': os.environ.get('POSTGRES_PASSWORD', '1234'),
        'dbname': os.environ.get('POSTGRES_DB', 'postgres'),
    }

    try:
        with psycopg2.connect(**db_config) as conn:
            with conn.cursor() as cur:
                # 1. 최근 10분 내 뉴스 데이터 수
                ten_mins_ago = (datetime.now() - timedelta(minutes=10)).strftime('%Y-%m-%d %H:%M:%S')
                cur.execute("SELECT count(*) FROM public.news_sentiment WHERE inserted_at > %s", (ten_mins_ago,))
                recent_news = cur.fetchone()[0]
                print(f"News articles added in last 10 mins: {recent_news}")
                
                # 2. 최근 10분 내 활동 로그 수
                cur.execute("SELECT count(*) FROM public.turing_logs WHERE timestamp > %s", (ten_mins_ago,))
                recent_logs = cur.fetchone()[0]
                print(f"Activity logs added in last 10 mins: {recent_logs}")
                
                # 3. 전체 뉴스 테이블 크기
                cur.execute("SELECT count(*) FROM public.news_sentiment")
                total_news = cur.fetchone()[0]
                print(f"Total News records in DB: {total_news}")

                # 5. 가장 최근 뉴스 1개 확인
                cur.execute("SELECT title, press, inserted_at FROM public.news_sentiment ORDER BY inserted_at DESC LIMIT 1")
                latest_news = cur.fetchone()
                if latest_news:
                    print(f"Latest News: [{latest_news[2]}] {latest_news[1]} - {latest_news[0]}")
                else:
                    print("No news found in table.")

    except Exception as e:
        print(f"Error: {e}")

if __name__ == "__main__":
    check_db_growth()
