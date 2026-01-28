"""
간단한 인메모리 그래프 저장소
TuringDB 대신 사용할 수 있는 경량 그래프 데이터베이스
"""

import json
from typing import Dict, List, Any, Optional
from collections import defaultdict


class GraphStorage:
    def __init__(self):
        self.nodes: Dict[str, Dict[str, Any]] = {}
        self.edges: List[Dict[str, Any]] = []
        self.node_index: Dict[str, List[str]] = defaultdict(list)  # label -> node_ids
        
    def add_node(self, node_id: str, labels: List[str], properties: Dict[str, Any]):
        """노드 추가"""
        self.nodes[node_id] = {
            "id": node_id,
            "labels": labels,
            "properties": properties
        }
        
        # 인덱스 업데이트
        for label in labels:
            if node_id not in self.node_index[label]:
                self.node_index[label].append(node_id)
    
    def add_edge(self, from_id: str, to_id: str, rel_type: str, properties: Dict[str, Any] = None):
        """엣지 추가"""
        edge = {
            "from": from_id,
            "to": to_id,
            "type": rel_type,
            "properties": properties or {}
        }
        self.edges.append(edge)
    
    def get_node(self, node_id: str) -> Optional[Dict[str, Any]]:
        """노드 조회"""
        return self.nodes.get(node_id)
    
    def find_nodes(self, label: str, properties: Dict[str, Any] = None) -> List[Dict[str, Any]]:
        """노드 검색"""
        node_ids = self.node_index.get(label, [])
        results = []
        
        for node_id in node_ids:
            node = self.nodes[node_id]
            
            # 속성 필터링
            if properties:
                match = True
                for key, value in properties.items():
                    node_value = node["properties"].get(key)
                    
                    # CONTAINS 연산 지원
                    if isinstance(value, str) and value.startswith("CONTAINS:"):
                        search_term = value.replace("CONTAINS:", "")
                        if not (node_value and search_term in str(node_value)):
                            match = False
                            break
                    elif node_value != value:
                        match = False
                        break
                
                if match:
                    results.append(node)
            else:
                results.append(node)
        
        return results
    
    def get_relationships(self, node_id: str, direction: str = "both", rel_type: str = None) -> List[Dict[str, Any]]:
        """노드의 관계 조회"""
        results = []
        
        for edge in self.edges:
            if rel_type and edge["type"] != rel_type:
                continue
            
            if direction in ["out", "both"] and edge["from"] == node_id:
                results.append({
                    "edge": edge,
                    "node": self.nodes.get(edge["to"])
                })
            
            if direction in ["in", "both"] and edge["to"] == node_id:
                results.append({
                    "edge": edge,
                    "node": self.nodes.get(edge["from"])
                })
        
        return results
    
    def get_path(self, start_id: str, max_depth: int = 2) -> Dict[str, Any]:
        """경로 탐색 (BFS)"""
        visited = set()
        queue = [(start_id, 0)]
        nodes = {}
        edges = []
        
        while queue:
            current_id, depth = queue.pop(0)
            
            if current_id in visited or depth > max_depth:
                continue
            
            visited.add(current_id)
            
            # 노드 추가
            if current_id in self.nodes:
                nodes[current_id] = self.nodes[current_id]
            
            # 관계 탐색
            if depth < max_depth:
                for rel in self.get_relationships(current_id, direction="both"):
                    edge = rel["edge"]
                    next_node = rel["node"]
                    
                    if next_node:
                        next_id = next_node["id"]
                        
                        # 엣지 추가
                        if edge not in edges:
                            edges.append(edge)
                        
                        # 큐에 추가
                        if next_id not in visited:
                            queue.append((next_id, depth + 1))
        
        return {
            "nodes": list(nodes.values()),
            "relationships": edges
        }
    
    def get_statistics(self) -> Dict[str, Any]:
        """통계 정보"""
        stats = {
            "total_nodes": len(self.nodes),
            "total_edges": len(self.edges),
            "nodes_by_label": {},
            "edges_by_type": defaultdict(int)
        }
        
        # 라벨별 노드 수
        for label, node_ids in self.node_index.items():
            stats["nodes_by_label"][label] = len(node_ids)
        
        # 타입별 엣지 수
        for edge in self.edges:
            stats["edges_by_type"][edge["type"]] += 1
        
        stats["edges_by_type"] = dict(stats["edges_by_type"])
        
        return stats
    
    def clear(self):
        """모든 데이터 삭제"""
        self.nodes.clear()
        self.edges.clear()
        self.node_index.clear()


# 전역 그래프 저장소
graph_storage = GraphStorage()
