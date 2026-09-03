# 국회의원 관계도 GraphDB 구조

## 📊 데이터베이스 개요

아래 개수는 초기 임포트 시점의 값이라 지금과 다르다. 현재 값은
`GET /api/stats` 를 본다. 특히 `SAME_PARTY` 는 엣지 폭증 때문에 생성을
중단했고(`scripts/simple_importer.py`), 호불호 관계는 수집을 돌 때마다
바뀐다.

### 전체 통계
- **총 노드 수**: 308개
- **총 엣지 수**: 20,589개

### 노드 타입별 개수
- **Party (정당)**: 8개
- **Member (의원)**: 300개

### 관계 타입별 개수
- **BELONGS_TO (소속)**: 300개
- **REPRESENTS (대표)**: 10개
- **SAME_PARTY (같은 정당)**: 20,279개 (현재는 생성하지 않는다)
- **POSITIVE_SENTIMENT / NEGATIVE_SENTIMENT (호불호)**: 뉴스 근거 집계로
  생성. 아래 상세 참조
- **SNS_INTERACTION (언급)**: 공동 언급

---

## 🏗️ GraphDB 구조

### 1. Node (노드)

#### Member Node (의원 노드)
```
Node ID: member_{id}
Labels: ["Member"]
Properties:
  - id: 고유 번호
  - name: 이름
  - party: 소속 정당
  - region: 지역구
  - sido: 시/도
  - region_detail: 상세 지역
  - committee: 소속 위원회
  - election_count: 당선 횟수 (초선/재선/3선...)
  - unit: 국회 대수 (제22대)
  - gender: 성별
  - election_method: 선출 방법 (지역구/비례대표)
  - photo_url: 사진 URL
  - photo_filename: 사진 파일명
  - monaCd: 의원 코드
  - image_url: API 이미지 URL
  - thumbnail_url: 썸네일 URL
```

**예시:**
```json
{
  "id": "member_211",
  "labels": ["Member"],
  "properties": {
    "id": 211,
    "name": "이재명",
    "party": "더불어민주당",
    "region": "",
    "sido": "",
    "committee": "",
    "election_count": "",
    "unit": "제22대",
    "gender": "",
    "election_method": "",
    "photo_url": "https://www.assembly.go.kr/...",
    "photo_filename": "이재명.jpg",
    "image_url": "/api/images/이재명.jpg",
    "thumbnail_url": "/api/images/이재명.jpg?thumbnail=true"
  }
}
```

#### Party Node (정당 노드)
```
Node ID: party_{정당명}
Labels: ["Party"]
Properties:
  - name: 정당명
```

**예시:**
```json
{
  "id": "party_더불어민주당",
  "labels": ["Party"],
  "properties": {
    "name": "더불어민주당"
  }
}
```

---

### 2. Edge (엣지/관계)

#### BELONGS_TO (소속 관계)
```
의원 --[BELONGS_TO]--> 정당
```
- **설명**: 의원이 특정 정당에 소속되어 있음
- **방향**: 의원 → 정당
- **개수**: 300개 (각 의원당 1개)

**예시:**
```json
{
  "from": "member_211",
  "to": "party_더불어민주당",
  "type": "BELONGS_TO",
  "properties": {}
}
```

#### SAME_PARTY (같은 정당 관계)
```
의원A <--[SAME_PARTY]--> 의원B
```
- **설명**: 두 의원이 같은 정당에 소속
- **방향**: 양방향
- **개수**: 20,279개

**예시:**
```json
{
  "from": "member_211",
  "to": "member_3",
  "type": "SAME_PARTY",
  "properties": {}
}
```

#### REPRESENTS (대표 관계)
```
의원 --[REPRESENTS]--> 지역
```
- **설명**: 의원이 특정 지역을 대표
- **방향**: 의원 → 지역
- **개수**: 10개

#### POSITIVE_SENTIMENT / NEGATIVE_SENTIMENT (호불호 관계)
```
의원 --[NEGATIVE_SENTIMENT]-- 의원      (무방향)
```
- **설명**: 뉴스 본문에서 확인된 우호·대립 관계
- **방향**: 없다. `source_id` 는 가나다순으로 앞선 이름일 뿐이다
  (`core/name_matcher.py` 의 `sorted`). 발화 주체 귀속이 들어오기 전까지
  화면도 화살표를 그리지 않는다.
- **한 쌍에 하나**: 두 극성이 동시에 존재할 수 없다. `/api/edge` 가 같은
  쌍의 다른 감정 엣지를 지운다.
- **만드는 곳**: `core/relation_evidence.py` 의 집계. 기사 단위 판정은
  `edge_observations` 에 쌓이고, 엣지는 그 집계 결과만 담는다. 자세한
  근거와 알고리즘은 `docs/MEDIA_BIAS_RESEARCH.md`.

**properties**
```json
{
  "score": 0.83,              // 최근 논조의 크기 0~1 (부호는 type 이 갖는다)
  "score_recent": -0.83,      // 반감기 45일을 적용한 부호 있는 논조
  "score_cumulative": -0.79,  // 감쇠 없는 부호 있는 논조
  "polarity": -1,
  "display_weight": 0.69,     // 화면 굵기. score x (0.5 + 0.5 x camp_coverage)
  "social_impact_score": 0.69,// 영향력 순위가 읽는 값
  "confidence": 0.58,         // 진영 교차 검증 신뢰도 0~1
  "camp_coverage": 0.667,     // 현재 극성을 보도한 진영 수 / 3
  "camps": {"보수": 2, "중도": 1, "진보": 0},        // 진영별 사건 수
  "camps_agree": {"보수": 2, "중도": 1, "진보": 0},  // 그중 현재 극성 지지
  "n_observations": 7,        // 근거 기사 수
  "n_clusters": 3,            // 전재를 묶은 뒤의 사건 수
  "n_press": 5,
  "presses": ["조선일보", "한겨레"],
  "first_seen": "2026-08-30",
  "last_seen": "2026-09-02",
  "peak_score": 0.91,
  "evidence": "근거 문장",
  "url": "https://...",       // 대표 근거 기사
  "press": "조선일보",
  "half_life_days": 45.0,
  "provenance": "aggregate"
}
```

`provenance` 가 없는 엣지는 집계 계층이 생기기 전에 만들어진 것이다.
`scripts/backfill_edge_observations.py` 가 근거 로그로 옮긴다.

#### edge_observations (관계 근거 로그)
엣지가 아니라 테이블이다. 기사 한 건이 만든 판정 하나가 한 행이다.
`(pair_key, url)` 이 유니크라 재수집해도 표본이 부풀지 않는다.

| 컬럼 | 설명 |
|---|---|
| `pair_key` | `"이름A\|이름B"` (가나다순). 방향 무관 |
| `polarity` | +1 우호 / -1 적대 |
| `score` | NLI 신뢰도 0~1 |
| `focus_weight` | 1/sqrt(기사 내 의원 수). 나열 기사를 깎는다 |
| `press`, `camp` | 언론사와 진영(보수/중도/진보) |
| `simhash` | 본문 앞 1500자의 63비트 지문. 전재 묶음용 |
| `url`, `title`, `article_date`, `evidence`, `observed_at` | 감사용 |

---

## 🏛️ 정당별 분석

### 더불어민주당
- **소속 의원**: 171명
- **주요 의원**: 이재명, 강득구, 강선우, 강유정, 강준현 등

### 국민의힘
- **소속 의원**: 107명
- **주요 의원**: 강대식, 강명구, 강민국, 강선영, 강승규 등

### 조국혁신당
- **소속 의원**: 12명
- **주요 의원**: 강경숙, 김선민, 김재원, 김준형, 박은정 등

### 개혁신당
- **소속 의원**: 3명
- **주요 의원**: 이주영, 이준석, 천하람

### 진보당
- **소속 의원**: 3명
- **주요 의원**: 윤종오, 전종덕, 정혜경

### 무소속
- **소속 의원**: 2명
- **주요 의원**: 김종민, 우원식

### 사회민주당
- **소속 의원**: 1명
- **주요 의원**: 한창민

### 기본소득당
- **소속 의원**: 1명
- **주요 의원**: 용혜인

---

## 🔍 네트워크 예시

### 이재명 의원의 네트워크 (깊이 2)
- **연결된 노드**: 172개
- **연결된 관계**: 14,706개
- **직접 연결**: 171개 노드
  - 1개 정당 노드 (더불어민주당)
  - 170개 의원 노드 (같은 정당 소속)

**관계 분포:**
- BELONGS_TO: 171개
- SAME_PARTY: 14,535개

---

## 📡 API 엔드포인트

### 통계 조회
```
GET /api/stats
```
**응답:**
```json
{
  "total_nodes": 308,
  "total_edges": 20589,
  "nodes_by_label": {
    "Party": 8,
    "Member": 300
  },
  "edges_by_type": {
    "BELONGS_TO": 300,
    "REPRESENTS": 10,
    "SAME_PARTY": 20279
  }
}
```

### 의원 검색
```
GET /api/search/{의원명}
```
**예시:** `/api/search/이재명`

### 관계 그래프 조회
```
GET /api/graph/{의원명}?depth=2
```
**예시:** `/api/graph/이재명?depth=2`

### 전체 그래프 조회
```
GET /api/graph/all?limit=50
```

### 이미지 조회
```
GET /api/images/{파일명}
GET /api/images/{파일명}?thumbnail=true
```

---

## 🌐 시각화 페이지

### GraphDB 구조 시각화
**URL**: http://localhost:5000/static/graph_structure.html

이 페이지에서 다음을 확인할 수 있습니다:
- 📊 전체 통계 (노드, 엣지 개수)
- 🏛️ 정당별 분석 (소속 의원 목록)
- 📦 노드 샘플 (의원 정보)
- 🔗 엣지 샘플 (관계 유형)
- 📈 관계 타입별 통계

### 3D 그래프 시각화
**URL**: http://localhost:3100

React 기반 3D WebGL 그래프 시각화:
- 인터랙티브 3D 그래프
- 의원 사진 표시
- 정당별 색상 구분
- 검색 및 필터링

---

## 💾 데이터 내보내기

### JSON 파일로 내보내기
```bash
docker exec korea-politician-backend python graph_viewer.py
```

생성되는 파일:
- `graph_structure.json` (약 2.6MB)
  - 모든 노드 정보
  - 모든 엣지 정보
  - 통계 정보

---

## 🔧 데이터 구조 확인 도구

### Python 스크립트
```bash
# 컨테이너 내부에서 실행
docker exec korea-politician-backend python graph_viewer.py
```

**기능:**
- 데이터베이스 개요 출력
- 정당별 분석
- 노드 샘플 출력
- 엣지 샘플 출력
- 특정 정치인 네트워크 분석
- JSON 파일로 내보내기

---

## 📝 데이터 소스

- **원본 데이터**: `assembly_members_complete.json`
- **데이터 개수**: 300명의 국회의원
- **데이터 출처**: 국회 공식 데이터
- **이미지**: `/img` 폴더 (300+ 의원 사진)

---

## 🚀 향후 확장 계획

### 추가 관계 타입
- **ALLY** (동맹): 정치적 동맹 관계
- **RIVAL** (경쟁): 정치적 경쟁 관계
- **MENTOR_OF** (멘토): 멘토-멘티 관계
- **COLLEAGUE** (동료): 동료 관계
- **MET_WITH** (회담): 회담/만남 기록

### 추가 노드 타입
- **Country** (국가): 국가 노드
- **Region** (지역): 지역 노드
- **Committee** (위원회): 위원회 노드
- **Bill** (법안): 법안 노드

### 글로벌 확장
- 미국, 중국, 일본, 영국, 독일, 프랑스, 러시아 등
- 국가 간 정치인 관계
- 국제 회담 및 협력 관계

---

**마지막 업데이트**: 2026년 1월 28일
**데이터 버전**: 제22대 국회
