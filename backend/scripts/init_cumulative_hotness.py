import psycopg
import os

def init_cumulative():
    db_config = {
        'host': os.environ.get('POSTGRES_HOST', 'localhost'),
        'port': int(os.environ.get('POSTGRES_PORT', 5432)),
        'user': os.environ.get('POSTGRES_USER', 'postgres'),
        'password': os.environ.get('POSTGRES_PASSWORD', '1234'),
        'dbname': os.environ.get('POSTGRES_DB', 'postgres'),
    }

    sql_path = "backend/scripts/update_cumulative_hotness.sql"
    if not os.path.exists(sql_path):
        print(f"SQL file not found: {sql_path}")
        return

    with open(sql_path, "r", encoding="utf-8") as f:
        sql = f.read()

    try:
        with psycopg.connect(**db_config) as conn:
            with conn.cursor() as cur:
                print("Updating cumulative hotness data...")
                cur.execute(sql)
                print("Database update successful!")
            conn.commit()
    except Exception as e:
        print(f"Error updating database: {e}")

if __name__ == "__main__":
    init_cumulative()
