import psycopg
import os

def fix_duplicates():
    # Use accurate port from .env or manual if needed
    db_config = {
        'host': os.environ.get('POSTGRES_HOST', 'localhost'),
        'port': 25432, # Force correct port
        'user': os.environ.get('POSTGRES_USER', 'postgres'),
        'password': os.environ.get('POSTGRES_PASSWORD', '1234'),
        'dbname': os.environ.get('POSTGRES_DB', 'postgres'),
    }

    try:
        with psycopg.connect(**db_config) as conn:
            with conn.cursor() as cur:
                print("1. Cleaning up existing duplicates...")
                # Keep only one record per (member_name, platform, post_id)
                cur.execute("""
                    DELETE FROM public.politician_sns_hotness
                    WHERE id IN (
                        SELECT id
                        FROM (
                            SELECT id,
                                   ROW_NUMBER() OVER (PARTITION BY member_name, platform, post_id ORDER BY collected_at DESC) as row_num
                            FROM public.politician_sns_hotness
                        ) s
                        WHERE row_num > 1
                    );
                """)
                print(f"Deleted {cur.rowcount} duplicate rows.")

                print("2. Adding unique constraint to (member_name, platform, post_id)...")
                # Check if constraint exists
                cur.execute("""
                    SELECT count(*) FROM pg_constraint WHERE conname = 'unique_sns_post_v2'
                """)
                if cur.fetchone()[0] == 0:
                    cur.execute("""
                        ALTER TABLE public.politician_sns_hotness 
                        ADD CONSTRAINT unique_sns_post_v2 UNIQUE (member_name, platform, post_id);
                    """)
                    print("Constraint 'unique_sns_post_v2' added.")
                else:
                    print("Constraint 'unique_sns_post' already exists.")
                    
            conn.commit()
            print("Database cleanup and schema update successful!")
    except Exception as e:
        print(f"Error: {e}")

if __name__ == "__main__":
    fix_duplicates()
