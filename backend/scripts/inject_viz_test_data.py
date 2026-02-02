import psycopg2
import json
import os

def inject_test_data():
    db_config = {
        'host': os.environ.get('POSTGRES_HOST', 'localhost'),
        'port': int(os.environ.get('POSTGRES_PORT', 5432)),
        'user': os.environ.get('POSTGRES_USER', 'postgres'),
        'password': os.environ.get('POSTGRES_PASSWORD', '1234'),
        'dbname': os.environ.get('POSTGRES_DB', 'postgres'),
    }
    
    try:
        conn = psycopg2.connect(**db_config)
        cur = conn.cursor()
        
        # 1. Jo Kuk -> Han Dong-hoon (High Impact)
        # IDs based on previous lookup: Cho(100005), Han(100008)
        edge_high = {
            'score': 0.95,
            'social_impact_score': 1.48, # Near max for thickest line
            'evidence': '[TEST] Highly tense relationship between Cho and Han (DCP Amplified)',
            'url': 'http://test.com/viz1',
            'date': '2024-02-01'
        }
        cur.execute("""
            INSERT INTO turing_edges (source_id, target_id, type, properties)
            VALUES (%s, %s, %s, %s)
            ON CONFLICT (source_id, target_id, type) DO UPDATE 
            SET properties = EXCLUDED.properties
        """, ('100005', '100008', 'NEGATIVE_SENTIMENT', json.dumps(edge_high)))

        # 2. Lee Jae-myung -> Han Dong-hoon (Moderate-High Impact)
        # ID: Lee(100006)
        edge_mid = {
            'score': 0.85,
            'social_impact_score': 1.15,
            'evidence': '[TEST] Strong opposition from Lee towards Han',
            'url': 'http://test.com/viz2',
            'date': '2024-02-01'
        }
        cur.execute("""
            INSERT INTO turing_edges (source_id, target_id, type, properties)
            VALUES (%s, %s, %s, %s)
            ON CONFLICT (source_id, target_id, type) DO UPDATE 
            SET properties = EXCLUDED.properties
        """, ('100006', '100008', 'NEGATIVE_SENTIMENT', json.dumps(edge_mid)))

        # 3. An friendly relation for balance
        # ID: An Cheol-soo (100007? let's check or just use name)
        # Actually I'll just use known IDs.
        
        conn.commit()
        print("[+] Test data injected successfully.")
        cur.close()
        conn.close()
        
    except Exception as e:
        print(f"[-] Injection failed: {e}")

if __name__ == "__main__":
    inject_test_data()
