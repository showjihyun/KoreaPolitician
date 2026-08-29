# DB 접근은 async 이므로 동기 테스트에서는 run_sync 브리지로 호출한다.
import os
import logging
from core.graph_storage import GraphStorage, run_sync, close_sync

# Setup logging
logging.basicConfig(level=logging.INFO)
logger = logging.getLogger(__name__)

def test_persistence():
    db_config = {
        'host': os.environ.get('POSTGRES_HOST', 'localhost'),
        'port': int(os.environ.get('POSTGRES_PORT', 5432)),
        'user': os.environ.get('POSTGRES_USER', 'postgres'),
        'password': os.environ.get('POSTGRES_PASSWORD', '1234'),
        'dbname': os.environ.get('POSTGRES_DB', 'postgres'),
    }
    
    logger.info("1. Initialize GraphStorage (First Run)")
    gs1 = GraphStorage()
    run_sync(gs1.init_db(db_config))
    
    # Add Data
    test_node_id = "test_node_001"
    test_edge_target = "test_node_002"
    
    logger.info(f"Adding Node: {test_node_id}")
    run_sync(gs1.add_node(test_node_id, ["TestLabel"], {"name": "Test Node", "score": 99}))
    
    logger.info(f"Adding Edge: {test_node_id} -> {test_edge_target}")
    run_sync(gs1.add_edge(test_node_id, test_edge_target, "TEST_RELATION", {"weight": 0.5}))
    
    logger.info("2. Re-initialize GraphStorage (Simulate Restart)")
    run_sync(gs1.close())

    gs2 = GraphStorage()
    run_sync(gs2.init_db(db_config))
    
    # Verify Data
    node = gs2.get_node(test_node_id)
    if node:
        logger.info(f"Node Loaded: {node}")
        assert node['properties']['score'] == 99
    else:
        logger.error("Node NOT found in DB!")
        
    rels = gs2.get_relationships(test_node_id, direction="out", rel_type="TEST_RELATION")
    if rels:
        logger.info(f"Edge Loaded: {rels[0]['edge']}")
        assert rels[0]['edge']['to'] == test_edge_target
    else:
        logger.error("Edge NOT found in DB!")
        
    run_sync(gs2.close())
    close_sync()

    logger.info("Persistence Test Completed.")

if __name__ == "__main__":
    test_persistence()
