from fastapi import Depends, FastAPI, Header, HTTPException, Query
from fastapi.encoders import jsonable_encoder
from fastapi.responses import JSONResponse
from fastapi.middleware.cors import CORSMiddleware
from fastapi.staticfiles import StaticFiles
import os
from core import cosponsorship
from core.graph_storage import graph_storage
from core.hotness import TREND_DAYS
from core.media_outlets import CAMPS, coverage_table
from core.db_config import db_config_from_env, env
from scripts.simple_importer import SimpleImporter, sync_member_profiles
from core.image_manager import image_manager
import logging
from collections import deque
import datetime
from pydantic import BaseModel
from contextlib import asynccontextmanager


logging.basicConfig(level=logging.INFO)

@asynccontextmanager
async def lifespan(app: FastAPI):
    """기동 시 DB 커넥션 풀을 열고 데이터를 적재하며, 종료 시 풀을 닫는다."""
    # 빈 문자열 환경변수(미등록 시크릿)를 미설정으로 처리한다.
    await graph_storage.init_db(db_config_from_env())

    json_file = "data/assembly_members_complete.json"
    # 노드가 없으면 JSON 에서 최초 임포트
    if os.path.exists(json_file) and (await graph_storage.get_statistics())["total_nodes"] == 0:
        logging.info("Loading data on startup...")
        importer = SimpleImporter()
        # 노드/엣지를 모아 한 트랜잭션으로 저장한다. 건별 왕복이면 원격 DB
        # 기준으로 기동에만 수십 초가 걸려 헬스체크를 넘긴다.
        async with graph_storage.batch():
            await importer.import_data(json_file)
        logging.info("Data loaded successfully!")
    elif os.path.exists(json_file):
        # 이미 데이터가 있는 DB 는 재임포트되지 않으므로, 나중에 추가된
        # 프로필 필드(홈페이지·국회 프로필·경력 등)를 여기서 보강한다.
        updated = await sync_member_profiles(json_file)
        if updated:
            logging.info(f"의원 프로필 {updated}명 보강")

    yield

    # 종료 시 커넥션 풀 반납
    await graph_storage.close()


app = FastAPI(lifespan=lifespan)

# Activity Log Queue (In-Memory, Ring Buffer)
activity_logs = deque(maxlen=50)

async def log_activity(action: str, details: str):
    await graph_storage.add_log(action, details)
    # Still keep in memory for very fast live updates if needed, 
    # but the API will primarily fetch from DB now.
    log = {
        "timestamp": datetime.datetime.now().strftime("%H:%M:%S"),
        "action": action,
        "details": details
    }
    activity_logs.appendleft(log)

class EdgeRequest(BaseModel):
    source: str
    target: str
    type: str
    properties: dict = {}


#: 호불호 관계 타입. 한 쌍에는 이 중 하나만 남는다.
SENTIMENT_TYPES = ("POSITIVE_SENTIMENT", "NEGATIVE_SENTIMENT")


def resolve_member(name: str):
    """이름으로 의원 노드를 찾는다. 정확히 같은 이름이 먼저다.

    부분일치만 쓰면 짧은 이름이 긴 이름에 흡수된다. 22대에는 박정·박정하·
    박정현·박정훈이 함께 있어서, "박정" 으로 넣은 관계가 "박정하" 에게
    붙었다. 실제로 그렇게 붙은 엣지가 세 건 있었다. 관계를 엉뚱한 사람에게
    귀속시키는 것은 이 프로젝트가 낼 수 있는 가장 나쁜 오류다.

    core/name_matcher.py 가 본문에서 같은 문제를 막고 있는데, API 경계에는
    같은 방어가 없었다.
    """
    wanted = (name or "").strip()
    if not wanted:
        return None
    exact = graph_storage.find_nodes("Member", {"name": wanted})
    if exact:
        return exact[0]
    # 정확히 맞는 이름이 없을 때만 부분일치로 물러선다. 검색창처럼
    # 사람이 일부만 친 경우를 위해서다.
    loose = graph_storage.find_nodes("Member", {"name": f"CONTAINS:{wanted}"})
    return loose[0] if loose else None

# CORS 설정
# allow_origins=["*"] 와 allow_credentials=True 를 함께 쓰면 스펙상 무효이며,
# Starlette 는 요청 Origin 을 그대로 반영해 사실상 모든 출처에 인증 포함
# 요청을 허용한다. 이 API 는 쿠키를 쓰지 않으므로 credentials 를 끈다.
# 배포 시 CORS_ALLOW_ORIGINS 로 출처를 좁힐 수 있다(쉼표 구분).
_origins_raw = env("CORS_ALLOW_ORIGINS")
_allow_origins = [o.strip() for o in _origins_raw.split(",")] if _origins_raw else ["*"]

app.add_middleware(
    CORSMiddleware,
    allow_origins=_allow_origins,
    allow_credentials=False,
    allow_methods=["GET", "POST", "OPTIONS"],
    allow_headers=["*"],
)


# 쓰기 엔드포인트 보호용 토큰. 설정하지 않으면 쓰기를 막는다.
# 공개 URL 에 무인증 write 를 열어두면 누구나 DB 를 채울 수 있다.
API_WRITE_TOKEN = env("API_WRITE_TOKEN")


def require_write_token(x_api_key: str = Header(default=None)):
    """쓰기 요청 인증. 토큰 미설정 시 엔드포인트 자체를 비활성화한다."""
    if not API_WRITE_TOKEN:
        raise HTTPException(
            status_code=503,
            detail="쓰기 기능이 비활성화되어 있습니다. API_WRITE_TOKEN 을 설정하세요.",
        )
    if x_api_key != API_WRITE_TOKEN:
        raise HTTPException(status_code=401, detail="유효하지 않은 API 키입니다.")

# 정적 파일 서빙
if os.path.exists("static"):
    app.mount("/static", StaticFiles(directory="static"), name="static")

@app.get('/api/graph/all')
async def graph_all(limit: int = Query(350, ge=1, le=1000)):
    """전체 정치인 관계 그래프 조회"""
    members = graph_storage.find_nodes("Member")
    
    # 제한된 수의 노드만 반환
    limited_members = members[:min(limit, len(members))]
    
    nodes = []
    relationships = []
    node_ids = set()
    
    # Fetch hotness scores for these members
    hotness_map = {}
    try:
        async with graph_storage.connection() as conn:
            async with conn.cursor() as cur:
                # 화제성은 뉴스와 유튜브를 합친 값이다. 총점만 주면 화면에서
                # "종합" 이라는 사실이 드러나지 않으므로 플랫폼별 소계도 함께 준다.
                # 총점과 소계를 한 번에, 같은 창에서 센다.
                #
                # 예전에는 총점을 요약 테이블의 저장값에서 읽었다. 그 값은
                # 크롤러가 마지막으로 돈 시점의 기준으로 계산돼 있어, 창을
                # 넓히자 화면에 '종합 2576 = 뉴스 4540 + 유튜브 1271' 처럼
                # 제 합과 안 맞는 숫자가 나갔다. 한 숫자를 두 곳에서 구하면
                # 언젠가 갈라진다. 소계를 더한 값이 곧 총점이다.
                await cur.execute("""
                    SELECT member_name,
                           SUM(hot_score),
                           (ARRAY_AGG(platform ORDER BY hot_score DESC))[1],
                           COALESCE(SUM(hot_score) FILTER (WHERE platform = 'News'), 0),
                           COALESCE(SUM(hot_score) FILTER (WHERE platform = 'YouTube'), 0)
                    FROM public.politician_sns_hotness
                    WHERE collected_at > NOW() - (%s * INTERVAL '1 day')
                    GROUP BY member_name
                """, (TREND_DAYS,))
                for r in await cur.fetchall():
                    hotness_map[r[0]] = {
                        "score": r[1], "platform": r[2],
                        "news": float(r[3] or 0), "youtube": float(r[4] or 0),
                    }
    except Exception as e:
        logging.warning(f"hotness summary 조회 실패: {e}")

    for member in limited_members:
        # 이미지 URL 및 화제성 점수 추가
        name = member["properties"].get("name")
        member_id = member["id"]
        
        if name:
            member["properties"]["image_url"] = f"/api/images/{name}.jpg"
            member["properties"]["thumbnail_url"] = f"/api/images/{name}.jpg?thumbnail=true"
            # SNS 화제성 점수 통합
            hot_info = hotness_map.get(name, {"score": 0, "platform": None, "news": 0, "youtube": 0})
            member["properties"]["hot_score"] = hot_info["score"]
            member["properties"]["hot_platform"] = hot_info["platform"]
            member["properties"]["hot_news"] = hot_info.get("news", 0)
            member["properties"]["hot_youtube"] = hot_info.get("youtube", 0)
        
        if member_id not in node_ids:
            nodes.append(member)
            node_ids.add(member_id)
        
        # 각 의원의 관계 추가.
        # 응답 크기를 위해 의원당 10개로 자르는데, 순서대로 자르면 호불호
        # 관계가 소속/지역/SNS 언급에 밀려 잘려 나간다. 이 화면의 핵심은
        # 호불호이므로 감정 관계를 먼저 담는다.
        rels = graph_storage.get_relationships(member_id, direction="out")
        # 상대 노드가 없는 엣지는 보내지 않는다.
        #
        # REPRESENTS 는 선거구를 가리키는데 선거구 노드는 적재하지 않는다.
        # 그래서 응답에 허공을 가리키는 엣지가 296개, 전체의 3분의 1이
        # 실려 나가고 있었다. 화면은 어차피 버리므로 그만큼이 순수한
        # 낭비였고, 더 나쁘게는 아래 의원당 10개 제한에서 자리를 한 칸씩
        # 차지해 실제 관계를 밀어냈다.
        rels = [r for r in rels if r["node"]]
        rels.sort(key=lambda r: 0 if r["edge"]["type"].endswith("_SENTIMENT") else 1)
        for rel in rels[:10]:  # 각 의원당 최대 10개 관계
            relationships.append(rel["edge"])
            if rel["node"] and rel["node"]["id"] not in node_ids:
                # 연결된 노드에도 이미지 및 화제성 점수 추가
                if rel["node"].get("labels") and "Member" in rel["node"]["labels"]:
                    rel_name = rel["node"]["properties"].get("name")
                    if rel_name:
                        rel["node"]["properties"]["image_url"] = f"/api/images/{rel_name}.jpg"
                        rel["node"]["properties"]["thumbnail_url"] = f"/api/images/{rel_name}.jpg?thumbnail=true"
                        hot_info = hotness_map.get(rel_name, {"score": 0, "platform": None, "news": 0, "youtube": 0})
                        rel["node"]["properties"]["hot_score"] = hot_info["score"]
                        rel["node"]["properties"]["hot_platform"] = hot_info["platform"]
                        rel["node"]["properties"]["hot_news"] = hot_info.get("news", 0)
                        rel["node"]["properties"]["hot_youtube"] = hot_info.get("youtube", 0)
                nodes.append(rel["node"])
                node_ids.add(rel["node"]["id"])
    
    return JSONResponse(content={
        "nodes": nodes,
        "relationships": relationships
    })

@app.get('/api/graph/{member_name}')
async def graph(member_name: str, depth: int = Query(2, ge=1, le=5)):
    """특정 의원의 관계 그래프 조회"""
    # 의원 검색
    members = graph_storage.find_nodes("Member", {"name": f"CONTAINS:{member_name}"})
    
    if not members:
        logging.info(f"No member found for search: {member_name}")
        return JSONResponse(content={
            "nodes": [], 
            "relationships": [], 
            "message": f"'{member_name}'에 대한 검색 결과가 없습니다."
        })
    
    member_id = members[0]["id"]
    data = graph_storage.get_path(member_id, max_depth=depth)
    
    # Fetch hotness scores for these members
    hotness_map = {}
    try:
        async with graph_storage.connection() as conn:
            async with conn.cursor() as cur:
                # 화제성은 뉴스와 유튜브를 합친 값이다. 총점만 주면 화면에서
                # "종합" 이라는 사실이 드러나지 않으므로 플랫폼별 소계도 함께 준다.
                # 총점과 소계를 한 번에, 같은 창에서 센다.
                #
                # 예전에는 총점을 요약 테이블의 저장값에서 읽었다. 그 값은
                # 크롤러가 마지막으로 돈 시점의 기준으로 계산돼 있어, 창을
                # 넓히자 화면에 '종합 2576 = 뉴스 4540 + 유튜브 1271' 처럼
                # 제 합과 안 맞는 숫자가 나갔다. 한 숫자를 두 곳에서 구하면
                # 언젠가 갈라진다. 소계를 더한 값이 곧 총점이다.
                await cur.execute("""
                    SELECT member_name,
                           SUM(hot_score),
                           (ARRAY_AGG(platform ORDER BY hot_score DESC))[1],
                           COALESCE(SUM(hot_score) FILTER (WHERE platform = 'News'), 0),
                           COALESCE(SUM(hot_score) FILTER (WHERE platform = 'YouTube'), 0)
                    FROM public.politician_sns_hotness
                    WHERE collected_at > NOW() - (%s * INTERVAL '1 day')
                    GROUP BY member_name
                """, (TREND_DAYS,))
                for r in await cur.fetchall():
                    hotness_map[r[0]] = {
                        "score": r[1], "platform": r[2],
                        "news": float(r[3] or 0), "youtube": float(r[4] or 0),
                    }
    except Exception as e:
        logging.warning(f"hotness summary 조회 실패: {e}")

    # 이미지 URL 및 화제성 점수 추가
    for node in data["nodes"]:
        if node.get("labels") and "Member" in node["labels"]:
            name = node["properties"].get("name")
            if name:
                node["properties"]["image_url"] = f"/api/images/{name}.jpg"
                node["properties"]["thumbnail_url"] = f"/api/images/{name}.jpg?thumbnail=true"
                hot_info = hotness_map.get(name, {"score": 0, "platform": None, "news": 0, "youtube": 0})
                node["properties"]["hot_score"] = hot_info["score"]
                node["properties"]["hot_platform"] = hot_info["platform"]
                node["properties"]["hot_news"] = hot_info.get("news", 0)
                node["properties"]["hot_youtube"] = hot_info.get("youtube", 0)
    
    return JSONResponse(content=data)

@app.get('/api/sns/hot_posts/{member_name}')
async def sns_hot_posts(member_name: str, limit: int = Query(5, ge=1, le=100)):
    """특정 의원의 화제가 된 SNS 포스트 수집"""
    try:
        async with graph_storage.connection() as conn:
            async with conn.cursor() as cur:
                # 화면이 "최근 일주일" 이라고 적어 두고 90일치를 보여 주면
                # 안 된다. 읽는 쪽도 같은 창을 쓴다.
                await cur.execute("""
                    SELECT platform, author_type, content_preview, engagement_data, hot_score, collected_at 
                    FROM public.politician_sns_hotness
                    WHERE member_name = %s
                      AND collected_at > NOW() - (%s * INTERVAL '1 day')
                    ORDER BY hot_score DESC, collected_at DESC
                    LIMIT %s
                """, (member_name, TREND_DAYS, limit))
                rows = await cur.fetchall()
                results = [{
                    "platform": r[0],
                    "author_type": r[1],
                    "content": r[2],
                    "engagement": r[3],
                    "hot_score": r[4],
                    "date": r[5].strftime("%Y-%m-%d %H:%M:%S")
                } for r in rows]
                return JSONResponse(content={"posts": results})
    except Exception as e:
        return JSONResponse(content={"error": str(e), "posts": []}, status_code=500)

@app.get('/api/sns/trends')
async def sns_trends(limit: int = Query(20, ge=1, le=200)):
    """전체 의원 중 가장 화제가 되는 SNS 포스트 수집"""
    try:
        async with graph_storage.connection() as conn:
            async with conn.cursor() as cur:
                await cur.execute("""
                    SELECT member_name, platform, author_type, content_preview, engagement_data, hot_score, collected_at 
                    FROM public.politician_sns_hotness
                    WHERE collected_at > NOW() - (%s * INTERVAL '1 day')
                    ORDER BY hot_score DESC, collected_at DESC
                    LIMIT %s
                """, (TREND_DAYS, limit))
                rows = await cur.fetchall()
                results = [{
                    "member_name": r[0],
                    "platform": r[1],
                    "author_type": r[2],
                    "content": r[3],
                    "engagement": r[4],
                    "hot_score": r[5],
                    "date": r[6].strftime("%Y-%m-%d %H:%M:%S")
                } for r in rows]
                return JSONResponse(content={"trends": results})
    except Exception as e:
        return JSONResponse(content={"error": str(e), "trends": []}, status_code=500)

@app.get('/api/search/{member_name}')
def search(member_name: str):
    """의원 검색"""
    members = graph_storage.find_nodes("Member", {"name": f"CONTAINS:{member_name}"})
    
    results = []
    for member in members:
        props = member["properties"]
        name = props.get("name")
        results.append({
            "name": name,
            "id": props.get("id"),
            "party": props.get("party"),
            "region": props.get("region"),
            "election_count": props.get("election_count"),
            "image_url": f"/api/images/{name}.jpg" if name else None,
            "thumbnail_url": f"/api/images/{name}.jpg?thumbnail=true" if name else None,
        })
    
    return JSONResponse(content={"members": results})

@app.post('/api/edge')
async def add_edge(req: EdgeRequest, _auth: None = Depends(require_write_token)):
    """관계 추가"""
    # Find source and target nodes by name
    src_node = resolve_member(req.source)
    tgt_node = resolve_member(req.target)

    if not src_node:
        return JSONResponse(content={"message": f"Source member '{req.source}' not found"}, status_code=404)
    if not tgt_node:
        return JSONResponse(content={"message": f"Target member '{req.target}' not found"}, status_code=404)

    src_id = src_node["id"]
    tgt_id = tgt_node["id"]

    try:
        edge = await graph_storage.add_edge(src_id, tgt_id, req.type, req.properties)
        # 호불호는 무방향이며 한 쌍에 극성 하나다.
        #
        # 예전에는 두 극성이 서로 다른 행이라 같은 두 사람 사이에 우호와
        # 적대가 동시에 남을 수 있었고, 이름 정렬이 바뀌면 역방향 사본까지
        # 생겼다. 이제 관계는 관측 전체를 집계해 극성 하나로 결정되므로,
        # 같은 쌍의 나머지 감정 엣지는 낡은 값이다.
        if req.type in SENTIMENT_TYPES:
            for edge_type in SENTIMENT_TYPES:
                for a, b in ((src_id, tgt_id), (tgt_id, src_id)):
                    if (a, b, edge_type) == (src_id, tgt_id, req.type):
                        continue
                    await graph_storage.remove_edge(a, b, edge_type)
    except Exception as e:
        # 저장 실패를 200 으로 돌려주면 크롤러가 성공한 줄 안다.
        logging.exception("엣지 저장 실패")
        return JSONResponse(content={"message": f"엣지 저장 실패: {e}"}, status_code=500)
    
    # Log Activity
    await log_activity("New Relation", f"{req.source} -> {req.target} ({req.type})")
    
    return JSONResponse(content={"message": "Edge added", "edge": edge})

@app.get('/api/relations/evidence')
async def relations_evidence(
    a: str = Query(None, description="의원 이름. b 와 함께 주면 그 쌍만 본다"),
    b: str = Query(None, description="의원 이름"),
    limit: int = Query(200, ge=1, le=1000),
    cursor: int = Query(0, ge=0, description="이전 응답의 next_cursor"),
):
    """관계 근거를 그대로 내보낸다. 감사용이며 인증이 필요 없다.

    r/politicalscience 에서 받은 지적은 "언론 편향이 그대로 관계도에
    들어간다" 였다. 여기에 대한 답은 편향이 없다는 주장이 아니라, 어떤
    기사가 어느 언론사에서 나와 어떤 판정을 만들었는지 전부 보여 주는
    것이다. 적대적 매체 지각 연구(Vallone 외 1985, Hansen & Kim 2011,
    이종혁 2015)에 따르면 관여도 높은 이용자는 어느 쪽이든 편향을
    지각하므로, 근거를 감추면 신뢰를 얻을 수 없다.

    a 와 b 를 주면 그 쌍의 집계 결과와 사건 묶음까지 함께 준다.
    주지 않으면 관측 원본을 id 순서로 페이지 단위로 준다.
    """
    from core import relation_evidence as ev

    try:
        if a and b:
            key = ev.pair_key(a, b)
            rows = await graph_storage.fetch_all(
                f"SELECT {ev.OBSERVATION_COLUMNS} FROM public.edge_observations "
                "WHERE pair_key = %s ORDER BY id",
                (key,),
            )
            observations = [ev.row_to_observation(r) for r in rows]
            if not observations:
                return JSONResponse(
                    content={"message": f"'{a}' 와 '{b}' 의 근거 기록이 없습니다."},
                    status_code=404,
                )
            edge = ev.aggregate(observations)
            entity_a, entity_b = ev.split_pair_key(key)
            # 뉴스 밖 대조 자료. 갈등으로 보도된 두 사람이 법안을 함께
            # 발의했다면 그 사실이 판단에 필요하다. 뉴스는 협력을 싣지
            # 않으므로(Galtung & Ruge 1965, Soroka 2006) 이 숫자가 뉴스만
            # 볼 때 생기는 공백을 메운다.
            #
            # null 은 "확인한 적 없음", 0 은 "확인했고 함께 발의한 적 없음"
            # 이다. 둘을 섞으면 없는 사실을 주장하게 된다.
            try:
                shared_bills = cosponsorship.bills_between(entity_a, entity_b)
            except Exception:                              # noqa: BLE001
                shared_bills = None
            return JSONResponse(content=jsonable_encoder({
                "pair": [entity_a, entity_b],
                "type": edge["type"] if edge else None,
                "aggregate": edge["properties"] if edge else None,
                "observations": ev.annotate_clusters(observations),
                "cosponsored_bills": shared_bills,
                "cosponsorship_collected": shared_bills is not None,
                "camp_table": coverage_table(),
            }))

        rows = await graph_storage.fetch_all(
            f"SELECT {ev.OBSERVATION_COLUMNS} FROM public.edge_observations "
            "WHERE id > %s ORDER BY id LIMIT %s",
            (cursor, limit),
        )
        observations = [ev.row_to_observation(r) for r in rows]
        return JSONResponse(content=jsonable_encoder({
            "count": len(observations),
            # 다음 쪽이 없으면 null. 커서는 id 라 삽입 중에도 건너뜀이 없다.
            "next_cursor": observations[-1]["id"] if len(observations) == limit else None,
            "observations": observations,
        }))
    except Exception as e:                                     # noqa: BLE001
        # 드라이버 메시지에는 접속 정보가 섞여 있어 그대로 내보내지 않는다.
        logging.warning(f"근거 조회 실패: {e}")
        return JSONResponse(content={"error": "evidence unavailable"}, status_code=500)


@app.get('/api/relations/camps')
async def relations_camps():
    """언론사를 어느 진영으로 보고 있는지 그대로 공개한다.

    진영 구분은 논쟁적인 판단이라 숨기면 안 된다. 표에 없는 매체는
    중도로 떨어지며, 교차 검증에서 진영 하나로만 센다.
    """
    return JSONResponse(content={
        "camps": CAMPS,
        "table": coverage_table(),
        "default": "중도",
        "note": "표에 없는 매체는 중도로 본다. 근거는 docs/MEDIA_BIAS_RESEARCH.md.",
    })


@app.get('/api/periods')
async def periods():
    """화면이 보여 주는 값들이 어느 기간을 근거로 하는지 알려 준다.

    호불호 관계는 수집을 시작한 날부터 지금까지 쌓인 전부다. 한 번 확인된
    관계는 지우지 않는다. 화제성은 "지금 누가 회자되는가" 라서 최근
    일주일만 본다.
    """
    try:
        async with graph_storage.connection() as conn:
            async with conn.cursor() as cur:
                # 관계 기간은 관계 로그에서 읽는다. 예전에는 끝 날짜를 화제성
                # 테이블에서 가져와, 수집이 실패한 날 관계는 계속 쌓이는데도
                # 기간이 멈춘 것처럼 보였다.
                # id 는 시각과 같은 순서로 늘어나므로 기존 (id DESC) 인덱스로
                # 양 끝을 집는다. MIN/MAX(timestamp) 는 색인이 없어 매 요청마다
                # 로그 전체를 훑었다.
                await cur.execute("""
                    SELECT (SELECT timestamp FROM turing_logs ORDER BY id ASC LIMIT 1),
                           (SELECT timestamp FROM turing_logs ORDER BY id DESC LIMIT 1),
                           (SELECT MAX(collected_at) FROM public.politician_sns_hotness)
                """)
                row = await cur.fetchone()
        rel_from, rel_to, collected = (row or (None, None, None))
        day = lambda v: v.strftime("%Y-%m-%d") if v else None   # noqa: E731
        return JSONResponse(content={
            "sentiment": {
                "mode": "cumulative",
                "from": day(rel_from),
                "to": day(rel_to),
            },
            "trend": {
                "mode": "rolling",
                "days": TREND_DAYS,
                "to": day(collected),
            },
        })
    except Exception as e:                                     # noqa: BLE001
        # 이 파일의 다른 DB 경로와 같이, 먼저 남기고 나간다. 드라이버 메시지에는
        # 접속 정보가 섞여 있어 그대로 내보내지 않는다.
        logging.warning(f"기간 조회 실패: {e}")
        return JSONResponse(content={"error": "periods unavailable"}, status_code=500)


@app.get('/api/stats')
async def stats():
    """통계 정보"""
    stats = await graph_storage.get_statistics()
    return JSONResponse(content=stats)

@app.get('/api/images/{filename}')
def serve_image(filename: str, thumbnail: bool = False):
    """이미지 서빙"""
    return image_manager.serve_image(filename, thumbnail=thumbnail)

@app.get('/api/dcp/context')
def dcp_context(subject: str, target: str):
    """
    DCP 알고리즘을 위한 문맥(동료 및 그들의 타겟에 대한 태도) 조회
    - 논문 정의에 따라 '동료(Ally)'는 동일 정당 소석 또는 우호 관계인 인물임.
    """
    # 1. Find Subject node
    sub_nodes = graph_storage.find_nodes("Member", {"name": f"CONTAINS:{subject}"})
    if not sub_nodes:
        return JSONResponse(content={"allies_context": [], "ally_basis": "unknown",
                                     "ally_count": 0})
    
    sub_node = sub_nodes[0]
    sub_id = sub_node["id"]
    sub_party = sub_node["properties"].get("party")
    
    # 2. Find Allies
    allies = set()

    # Strategy A: Outgoing Positive Sentiment
    rels_out = graph_storage.get_relationships(sub_id, direction="out")
    for r in rels_out:
        if r["edge"]["type"] == "POSITIVE_SENTIMENT":
             if r["node"]: allies.add(r["node"]["id"])

    # Strategy B: 공동발의
    #
    # 예전 정의는 "같은 정당" 이었다. 그러면 같은 당 의원 170명이 서로 전부
    # 동맹이 되어, 공명 점수가 사실상 정당 소속을 되풀이한다. 편향을
    # 보정하려는 자리에서 정파 구조를 증폭하는 셈이었다.
    #
    # 공동발의는 뉴스와 무관하게 기록되는 협력의 직접 증거다. 자료가 아직
    # 없으면 예전 정의로 물러서되, 그 사실을 응답에 적어 둔다.
    ally_basis = "cosponsorship"
    if cosponsorship.is_populated():
        for name, _bills in cosponsorship.allies_of(subject):
            ally_node = resolve_member(name)
            if ally_node:
                allies.add(ally_node["id"])
    elif sub_party:
        ally_basis = "same_party_fallback"
        party_members = graph_storage.find_nodes("Member", {"party": sub_party})
        for pm in party_members:
            if pm["id"] != sub_id:
                allies.add(pm["id"])
    else:
        ally_basis = "sentiment_only"

    allies.discard(sub_id)

    # 3. For each Ally, check relation to Target
    tgt_nodes = graph_storage.find_nodes("Member", {"name": f"CONTAINS:{target}"})
    if not tgt_nodes:
        return JSONResponse(content={"allies_context": [], "ally_basis": "unknown",
                                     "ally_count": 0})
    tgt_id = tgt_nodes[0]["id"]
    
    context_data = []
    
    for ally_id in allies:
        # Fetch relationships from Ally to Target
        ally_rels = graph_storage.get_relationships(ally_id, direction="out")
        for ar in ally_rels:
            # 상대 노드가 없는 엣지가 있다. REPRESENTS 는 선거구를 가리키는데
            # 선거구 노드는 적재하지 않는다. 예전에는 여기서 곧바로 첨자를
            # 붙여 읽다가 None 을 만나면 500 이 났다.
            if ar["node"] and ar["node"]["id"] == tgt_id:
                # Found relation Ally -> Target
                edge = ar["edge"]
                if edge["type"] in SENTIMENT_TYPES:
                    props = edge["properties"]
                    weight = props.get("score", 0.5)
                    # 예전에는 존재하지 않는 count 속성을 읽어 늘 1이었다.
                    # 지금은 집계가 사건 수를 남기므로 그것을 쓴다.
                    events = props.get("n_clusters", 1)

                    # Heuristic: weight boosted by how often it was observed
                    effective_weight = weight * (1 + (0.05 * events))

                    context_data.append({
                        "ally": ar["node"]["properties"].get("name"),
                        "relation": edge["type"],
                        "weight": effective_weight,
                        "events": events,
                    })

    return JSONResponse(content={
        "allies_context": context_data,
        # 동맹을 무엇으로 정의했는지 밝힌다. same_party_fallback 이면 공동발의
        # 자료가 아직 없다는 뜻이고, 그 결과는 정파 구조를 그대로 되풀이한다.
        "ally_basis": ally_basis,
        "ally_count": len(allies),
    })

@app.get('/api/activity_logs')
async def get_activity_logs(limit: int = Query(50, ge=1, le=200),
                            history: bool = False, search: str = None):
    """활동 로그 조회 (기본값: 최근 50개)"""
    if history:
        # DB에서 히스토리 조회
        logs = await graph_storage.get_logs(limit=limit if limit <= 200 else 200, search=search)
        return JSONResponse(content={"logs": logs})
    
    # In-memory 필터링 (간단 검색)
    res_logs = list(activity_logs)
    if search:
        res_logs = [log for log in res_logs if search in log["details"] or search in log["action"]]
        
    return JSONResponse(content={"logs": res_logs[:limit]})

@app.get('/api/images')
def list_images():
    """이미지 목록"""
    images = image_manager.get_all_images()
    return JSONResponse(content={"images": images})

@app.get('/api/intelligence')
async def get_intelligence():
    """상업용 인사이트 조회를 위한 지능형 분석 데이터 제공"""
    data = await graph_storage.get_intelligence()
    return JSONResponse(content=data)

@app.get('/health')
async def health():
    """헬스체크.

    예전에는 DB 를 보지 않고 항상 healthy 를 반환해서, DB 가 끊겨도
    Render 헬스체크를 통과한 채 빈 그래프를 200 으로 서빙했다.
    """
    db_ok = await graph_storage.ping()
    body = {
        "status": "healthy" if db_ok else "degraded",
        "database": "up" if db_ok else "down",
        "nodes": len(graph_storage.nodes),
    }
    return JSONResponse(content=body, status_code=200 if db_ok else 503)

if __name__ == "__main__":
    import uvicorn
    uvicorn.run(
        "turingdb_server:app",
        host="0.0.0.0",
        port=5000,
        reload=True
    )
