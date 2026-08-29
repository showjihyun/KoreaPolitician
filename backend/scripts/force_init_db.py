import os
import sys
import psycopg

# Add root to sys.path for core imports
sys.path.append(os.getcwd())
from backend.core.graph_storage import GraphStorage

def init_all_db():
    db_config = {
        'host': os.environ.get('POSTGRES_HOST', 'localhost'),
        'port': int(os.environ.get('POSTGRES_PORT', 5432)),
        'user': os.environ.get('POSTGRES_USER', 'postgres'),
        'password': os.environ.get('POSTGRES_PASSWORD', '1234'),
        'dbname': os.environ.get('POSTGRES_DB', 'postgres'),
    }
    
    gs = GraphStorage()
    print("Initializing tables...")
    gs.init_db(db_config)
    print("Tables created successfully.")
    
    # Run cumulative SQL
    sql_path = "backend/scripts/update_cumulative_hotness.sql"
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
        print(f"Error updating cumulative: {e}")

if __name__ == "__main__":
    init_all_db()
