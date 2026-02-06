import psycopg2
import os
from dotenv import load_dotenv

def setup_db():
    # .env 파일이 backend 폴더에 있으므로 경로 지정
    load_dotenv('backend/.env')
    
    db_config = {
        'host': os.getenv('POSTGRES_HOST', 'localhost'),
        'port': int(os.getenv('POSTGRES_PORT', 5432)),
        'user': os.getenv('POSTGRES_USER', 'postgres'),
        'password': os.getenv('POSTGRES_PASSWORD', 'password'),
        'dbname': os.getenv('POSTGRES_DB', 'korea_politician'),
    }
    
    try:
        conn = psycopg2.connect(**db_config)
        cur = conn.cursor()
        
        # SNS 화제성 정보 저장 테이블
        cur.execute('''
            CREATE TABLE IF NOT EXISTS public.politician_sns_hotness (
                id SERIAL PRIMARY KEY,
                member_name TEXT,
                platform VARCHAR(20),
                author_type VARCHAR(20),
                post_id TEXT,
                content_preview TEXT,
                engagement_data JSONB,
                hot_score FLOAT,
                sentiment_score FLOAT,
                collected_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP
            );
        ''')
        
        cur.execute('CREATE INDEX IF NOT EXISTS idx_sns_hotness_member ON public.politician_sns_hotness(member_name);')
        cur.execute('CREATE INDEX IF NOT EXISTS idx_sns_hotness_date ON public.politician_sns_hotness(collected_at);')
        
        # 각 의원별 최종/현재 화제성 점수 요약 테이블 (빠른 조회를 위함)
        cur.execute('''
            CREATE TABLE IF NOT EXISTS public.politician_hotness_summary (
                member_name TEXT PRIMARY KEY,
                current_hot_score FLOAT DEFAULT 0,
                daily_change FLOAT DEFAULT 0,
                top_platform VARCHAR(20),
                last_updated TIMESTAMP DEFAULT CURRENT_TIMESTAMP
            );
        ''')
        
        conn.commit()
        print("Success: Database tables for SNS analysis created.")
        
    except Exception as e:
        # 인코딩 오류 방지를 위해 repr() 사용
        print(f"Error setting up database: {repr(e)}")
    finally:
        if 'cur' in locals(): cur.close()
        if 'conn' in locals(): conn.close()

if __name__ == "__main__":
    setup_db()
