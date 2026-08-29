"""
GraphDB 데이터 구조 시각화 도구
Node, Edge, Properties를 보기 좋게 출력
"""

from core.graph_storage import graph_storage, run_sync, close_sync
import atexit
from scripts.simple_importer import SimpleImporter
import json
import os


def print_separator(title="", width=80):
    """구분선 출력"""
    if title:
        print(f"\n{'='*width}")
        print(f"{title:^{width}}")
        print(f"{'='*width}\n")
    else:
        print(f"{'='*width}\n")


def print_node_info(node, index=None):
    """노드 정보 출력"""
    prefix = f"[{index}] " if index is not None else ""
    print(f"{prefix}Node ID: {node['id']}")
    print(f"  Labels: {', '.join(node['labels'])}")
    print(f"  Properties:")
    for key, value in node['properties'].items():
        if isinstance(value, str) and len(value) > 50:
            value = value[:47] + "..."
        print(f"    - {key}: {value}")
    print()


def print_edge_info(edge, index=None):
    """엣지 정보 출력"""
    prefix = f"[{index}] " if index is not None else ""
    print(f"{prefix}Edge: {edge['from']} --[{edge['type']}]--> {edge['to']}")
    if edge.get('properties'):
        print(f"  Properties:")
        for key, value in edge['properties'].items():
            print(f"    - {key}: {value}")
    print()


def show_database_overview():
    """데이터베이스 전체 개요"""
    print_separator("GraphDB 데이터베이스 개요")
    
    stats = run_sync(graph_storage.get_statistics())
    
    print(f"📊 전체 통계")
    print(f"  총 노드 수: {stats['total_nodes']:,}개")
    print(f"  총 엣지 수: {stats['total_edges']:,}개")
    print()
    
    print(f"📦 노드 타입별 개수")
    for label, count in stats['nodes_by_label'].items():
        print(f"  - {label}: {count:,}개")
    print()
    
    print(f"🔗 관계 타입별 개수")
    for rel_type, count in stats['edges_by_type'].items():
        print(f"  - {rel_type}: {count:,}개")
    print()


def show_node_samples(label=None, limit=5):
    """노드 샘플 출력"""
    if label:
        print_separator(f"노드 샘플: {label} (최대 {limit}개)")
        nodes = graph_storage.find_nodes(label)[:limit]
    else:
        print_separator(f"전체 노드 샘플 (최대 {limit}개)")
        nodes = list(graph_storage.nodes.values())[:limit]
    
    if not nodes:
        print("노드가 없습니다.\n")
        return
    
    for i, node in enumerate(nodes, 1):
        print_node_info(node, i)


def show_edge_samples(rel_type=None, limit=10):
    """엣지 샘플 출력"""
    if rel_type:
        print_separator(f"관계 샘플: {rel_type} (최대 {limit}개)")
        edges = [e for e in graph_storage.edges if e['type'] == rel_type][:limit]
    else:
        print_separator(f"전체 관계 샘플 (최대 {limit}개)")
        edges = graph_storage.edges[:limit]
    
    if not edges:
        print("관계가 없습니다.\n")
        return
    
    for i, edge in enumerate(edges, 1):
        print_edge_info(edge, i)


def show_politician_network(name, depth=2):
    """특정 정치인의 네트워크 출력"""
    print_separator(f"정치인 네트워크: {name} (깊이: {depth})")
    
    # 정치인 검색
    members = graph_storage.find_nodes("Member", {"name": f"CONTAINS:{name}"})
    
    if not members:
        print(f"'{name}'을(를) 찾을 수 없습니다.\n")
        return
    
    member = members[0]
    print(f"🎯 중심 노드")
    print_node_info(member)
    
    # 네트워크 가져오기
    network = graph_storage.get_path(member['id'], max_depth=depth)
    
    print(f"📊 네트워크 통계")
    print(f"  연결된 노드: {len(network['nodes'])}개")
    print(f"  연결된 관계: {len(network['relationships'])}개")
    print()
    
    # 관계 타입별 분류
    rel_by_type = {}
    for rel in network['relationships']:
        rel_type = rel['type']
        if rel_type not in rel_by_type:
            rel_by_type[rel_type] = []
        rel_by_type[rel_type].append(rel)
    
    print(f"🔗 관계 타입별 분포")
    for rel_type, rels in rel_by_type.items():
        print(f"  - {rel_type}: {len(rels)}개")
    print()
    
    # 직접 연결된 노드들 (depth 1)
    direct_rels = graph_storage.get_relationships(member['id'], direction="both")
    
    if direct_rels:
        print(f"👥 직접 연결된 노드 ({len(direct_rels)}개)")
        for i, rel_info in enumerate(direct_rels[:10], 1):  # 최대 10개만
            edge = rel_info['edge']
            node = rel_info['node']
            direction = "→" if edge['from'] == member['id'] else "←"
            print(f"  [{i}] {direction} [{edge['type']}] {node['properties'].get('name', node['id'])}")
        
        if len(direct_rels) > 10:
            print(f"  ... 외 {len(direct_rels) - 10}개")
        print()


def show_party_analysis():
    """정당별 분석"""
    print_separator("정당별 분석")
    
    parties = graph_storage.find_nodes("Party")
    
    for party in parties:
        party_name = party['properties'].get('name', party['id'])
        print(f"🏛️  {party_name}")
        
        # 소속 의원 수 계산
        member_rels = [e for e in graph_storage.edges 
                      if e['type'] == 'BELONGS_TO' and e['to'] == party['id']]
        
        print(f"  소속 의원: {len(member_rels)}명")
        
        # 샘플 의원 출력
        if member_rels:
            print(f"  주요 의원:")
            for rel in member_rels[:5]:
                member = graph_storage.get_node(rel['from'])
                if member:
                    member_name = member['properties'].get('name', 'Unknown')
                    region = member['properties'].get('region', '')
                    print(f"    - {member_name} ({region})")
        print()


def export_to_json(output_file="graph_export.json"):
    """GraphDB 데이터를 JSON으로 내보내기"""
    print_separator(f"JSON 내보내기: {output_file}")
    
    data = {
        "statistics": run_sync(graph_storage.get_statistics()),
        "nodes": list(graph_storage.nodes.values()),
        "edges": graph_storage.edges
    }
    
    with open(output_file, 'w', encoding='utf-8') as f:
        json.dump(data, f, ensure_ascii=False, indent=2)
    
    print(f"✅ 데이터를 {output_file}에 저장했습니다.")
    print(f"  파일 크기: {os.path.getsize(output_file):,} bytes")
    print()


def main():
    """메인 실행 함수"""
    # 데이터 로드 확인
    if run_sync(graph_storage.get_statistics())['total_nodes'] == 0:
        print("데이터를 로드하는 중...")
        importer = SimpleImporter()
        run_sync(importer.import_data("data/assembly_members_complete.json"))
        print()
    
    # 1. 데이터베이스 개요
    show_database_overview()
    
    # 2. 정당 분석
    show_party_analysis()
    
    # 3. 노드 샘플 (의원)
    show_node_samples("Member", limit=3)
    
    # 4. 노드 샘플 (정당)
    show_node_samples("Party", limit=3)
    
    # 5. 관계 샘플
    show_edge_samples("BELONGS_TO", limit=5)
    show_edge_samples("SAME_PARTY", limit=5)
    
    # 6. 특정 정치인 네트워크
    show_politician_network("이재명", depth=2)
    show_politician_network("윤석열", depth=2)
    
    # 7. JSON 내보내기
    export_to_json("graph_structure.json")
    
    print_separator("완료")
    print("GraphDB 데이터 구조 분석이 완료되었습니다.")
    print("자세한 내용은 graph_structure.json 파일을 확인하세요.")


# 종료 시 커넥션 풀과 전용 이벤트 루프 정리
atexit.register(close_sync)


if __name__ == "__main__":
    main()
