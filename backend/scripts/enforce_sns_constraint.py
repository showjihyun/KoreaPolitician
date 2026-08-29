import psycopg
import os
from dotenv import load_dotenv

load_dotenv('backend/.env')

def fix_constraints():
    db_config = {
        'host': os.getenv('POSTGRES_HOST', 'localhost'),
        'port': int(os.getenv('POSTGRES_PORT', 5432)),
        'user': os.getenv('POSTGRES_USER', 'postgres'),
        'password': os.getenv('POSTGRES_PASSWORD', '1234'),
        'dbname': os.getenv('POSTGRES_DB', 'postgres'),
    }

    try:
        with psycopg.connect(**db_config) as conn:
            with conn.cursor() as cur:
                print("Deduplicating and adding unique constraint...")
                # 1. Deduplicate
                cur.execute("""
                    DELETE FROM politician_sns_hotness a
                    USING politician_sns_hotness b
                    WHERE a.id < b.id 
                    AND a.member_name = b.member_name 
                    AND a.platform = b.platform 
                    AND a.post_id = b.post_id;
                """)
                print(f"Deleted {cur.rowcount} duplicates.")
                
                # 2. Add Constraint
                cur.execute("""
                    ALTER TABLE politician_sns_hotness 
                    ADD CONSTRAINT unique_sns_post_v2 UNIQUE (member_name, platform, post_id);
                """)
                print("Added unique constraint 'unique_sns_post_v2'.")
            conn.commit()
            print("Successfully updated database schema.")
    except Exception as e:
        print(f"Error: {e}")

if __name__ == "__main__":
    fix_constraints()
