# 언론 보도 편향 연구 조사와 호불호 알고리즘 보정안

작성일: 2026-09-02
갱신: 2026-09-03 (1단계 구현 반영)
계기: r/politicalscience 게시글(`docs/reddit_post.md`)에 대해 "언론의 편향 보도와 어그로성 기사 때문에 데이터 신뢰도가 낮다"는 지적이 들어옴.
목적: 언론 편향을 다루는 정치학·커뮤니케이션학·전산언어학 논문 가운데 인용이 높은 것을 추려, 정치인 관계도의 호불호 연산에 적용할 수 있는 부분을 찾고 보정 알고리즘 5개를 제안한다.

## 구현 현황 (2026-09-03)

| 항목 | 상태 | 코드 |
|---|---|---|
| 6.0 관측 로그 | 완료 | `backend/core/relation_evidence.py`, 테이블 `edge_observations` |
| 6.0 언론사 저장 | 완료 | `news_crawler_pipeline.save_observations` |
| 5(a) 사건 클러스터링 | 완료 | `simhash`, `assign_clusters` |
| 2 진영 교차 검증 | 완료 | `core/media_outlets.py`, `_confidence` |
| 5(c) 시간 감쇠 | 완료 | 반감기 45일, `score_recent` / `score_cumulative` |
| 감사 공개 | 완료 | `GET /api/relations/evidence`, `/api/relations/camps` |
| 분포 리포트 | 완료 | `scripts/evidence_report.py` |
| 손코딩 표본·채점 | 완료 | `scripts/coding_sample.py` (Krippendorff alpha) |
| 4 발화 주체 귀속 | 완료 | `crawlers/affective_analysis.py`, 방향 복원 |
| 3 공동발의 그래프 | 코드만 | `core/cosponsorship.py`, `crawlers/assembly_bills_pipeline.py` — **자료 없음** |
| 3 부정성 역가중 | 보류 | 관측 표본이 더 필요하다 |
| 5(b) 어그로 할인 | 부분 | focus weight만 적용, 클릭베이트 분류기 미착수 |
| 1 언론사 논조 기준선 | 보류 | 언론사x정당 셀당 표본 부족 |

부수 변경 셋을 함께 했다. 첫째, 임포터가 넣던 근거 없는 샘플 관계 다섯 건의
생성을 중단했다. 둘째, 늘 실패하던 DCP 호출을 파이프라인에서 뺐다(§6.0).
셋째, DCP 의 동맹 정의를 "같은 정당" 에서 공동발의로 바꿨다.

### 공동발의는 비어 있다 (2026-09-03 결정)

열린국회정보 OpenAPI 는 등록 키를 요구하는데, 키 발급을 하지 않기로 했다.
따라서 `cosponsorship` 테이블은 비어 있고 다음이 따라온다.

- DCP 의 동맹 정의는 `same_party_fallback` 으로 물러선다. `/api/dcp/context`
  응답의 `ally_basis` 가 그렇게 표시한다. DCP 자체가 파이프라인에서 빠져
  있으므로 화면에 드러나는 영향은 없다.
- 감사 응답의 `cosponsored_bills` 는 `null` 이고 `cosponsorship_collected` 는
  `false` 다. **`null` 과 `0` 을 구분한다.** `null` 은 확인한 적 없음,
  `0` 은 확인했고 함께 발의한 적 없음이다. 둘을 같이 0 으로 돌려주면
  협력한 적 없는 사이라고 주장하는 셈이 된다.
- 알고리즘 3의 사전확률과 역가중은 근거가 없으므로 착수하지 않는다.

수집 코드와 테스트는 그대로 둔다. 키를 나중에 넣으면 `ASSEMBLY_API_KEY`
하나로 동작하고, GitHub Actions 단계도 이미 걸려 있다. 키 없이 쓸 수 있는
공식 경로는 확인 결과 없었다. likms.assembly.go.kr 화면을 긁는 방법이
남아 있으나 깨지기 쉬워 손대지 않았다.

남은 가장 큰 구멍은 여전히 **사람이 검증한 표본**이다. 표집과 채점 도구는
만들었으므로, 남은 것은 두 사람이 CSV 를 채우는 일이다.

### 운영 순서

새 스크립트가 여럿이라 실행 순서를 적어 둔다. 전부 `PYTHONPATH=backend` 와
`POSTGRES_*` 환경변수가 필요하다.

```bash
# 1. 집계 이전에 만들어진 엣지를 근거 로그로 옮긴다. 한 번만.
#    먼저 무엇을 할지 본다.
python backend/scripts/backfill_edge_observations.py --dry-run
#    근거 기사 주소가 없는 엣지(임포터가 넣던 예시 5건)를 지우려면
python backend/scripts/backfill_edge_observations.py --drop-unsourced
#    지운 뒤에는 API 를 재기동해야 인메모리 그래프에 반영된다.

# 2. 수집. 근거를 쌓고 쌍마다 엣지를 다시 쓴다. 매일 자동으로 돈다.
python backend/crawlers/news_crawler_pipeline.py

# 3. 분포 확인. 최소 사건 수를 2로 올릴지, 진영표에 무엇을 채울지 판단한다.
python backend/scripts/evidence_report.py

# 4. 손코딩. 두 사람이 coder1 / coder2 열을 각자 채운 뒤 채점한다.
python backend/scripts/coding_sample.py sample -n 200
python backend/scripts/coding_sample.py score

# 5. 공동발의. ASSEMBLY_API_KEY 가 있을 때만 의미가 있다.
python backend/crawlers/assembly_bills_pipeline.py
```

조율값은 전부 환경변수로 열려 있다. 기본값의 근거는 각 상수 옆에 적어 두었다.

| 환경변수 | 기본값 | 무엇을 바꾸나 |
|---|---|---|
| `RELATION_HALF_LIFE_DAYS` | 45 | 최근 논조의 반감기 |
| `RELATION_SIMHASH_DISTANCE` | 6 | 같은 사건으로 묶을 본문 유사도 |
| `RELATION_CLUSTER_WINDOW_DAYS` | 1 | 같은 사건으로 볼 날짜 창 |
| `RELATION_CAMP_RELIABILITY` | 0.7 | 진영 하나가 도달할 수 있는 신뢰 상한 |
| `RELATION_MIN_CLUSTERS` | 1 | 엣지로 승격하는 최소 사건 수 |
| `RELATION_NLI_THRESHOLD` | 0.65 | 함의 확률 하한 |
| `RELATION_DIRECTION_MARGIN` | 0.10 | 방향을 인정할 정방향-역방향 점수 차 |
| `RELATION_WINDOW_RADIUS` | 1 | 문맥 창의 앞뒤 문장 수 |
| `RELATION_DROP_NARRATION` | 꺼짐 | 켜면 기자 서술을 엣지에서 아예 뺀다 |

---

## 1. 현재 호불호 연산이 어떻게 돌아가는지 (보정 대상)

문서를 읽는 사람이 코드를 열지 않아도 되도록 핵심만 적는다. 인용 줄 번호는 2026-09-02 기준이다.

| 단계 | 위치 | 동작 | 편향 관점에서 문제 |
|---|---|---|---|
| 수집 | `backend/crawlers/news_crawler_pipeline.py:315-435` | 네이버 뉴스 정치·경제·사회 섹션 5쪽씩 + 의원별 검색("{이름} 의원", "{이름} 국회") | 포털 한 곳. 언론사(`press`)는 긁지만 엣지에는 저장하지 않음 |
| 극성 판정 | `backend/crawlers/affective_analysis.py:61-113` | mDeBERTa NLI zero-shot. 3문장 창에 두 이름이 모두 있으면 "서로 우호적/협력적" vs "서로 적대적/비판적" 가설 점수를 내고, 0.65 넘는 창 중 **최대값 하나**를 기사 점수로 씀 | 누가 누구에게 한 말인지(발화 주체) 구분 없음. 기자 서술과 정치인 발언이 동급. 자극적인 한 문장이 기사 전체를 대표 |
| 쌍 열거 | `news_crawler_pipeline.py:529-543` | 기사에 등장한 의원 모든 쌍(O(n²))에 대해 판정 | 이름이 가나다순 정렬이라 엣지 방향은 의미 없음(`core/name_matcher.py:94`) |
| 저장 | `backend/core/graph_storage.py:405-427` | `(source, target, type)` 키로 `dict.update` → **마지막 기사가 덮어씀** | 기사 수, 언론사 분포, 시간 흐름이 전부 사라짐. 집계 기반 보정이 불가능 |
| DCP 증폭 | `backend/core/dcp_algorithm.py:49-63`, `api/turingdb_server.py:439-450` | 같은 정당 = 동맹으로 보고 공명 점수 가산 | 정파 구조를 보정하는 게 아니라 증폭함. 운영 환경에서는 API 주소 문제로 사실상 no-op |
| 중복 제거 | `news_crawler_pipeline.py:518-527, 630-631` | 제목·본문 해시 dedup이 있으나 `seen_*`에 add하지 않아 **죽은 코드** | 통신사 전재 기사가 여러 URL로 들어와 각각 엣지를 덮어씀 |
| 주목도 | `backend/core/hotness.py:111-118` | 1/√(기사 내 의원 수) 가중, 7일 창 | 주목도에만 있고 호불호에는 없음 |

현재 엣지: 갈등 36 vs 우호 3 (`docs/reddit_post.md`). 이 비대칭은 아래 논문들이 말하는 "부정성·갈등 선택 편향"과 정확히 일치한다.

---

## 2. 조사 방법

- 검색: 웹 검색(Google Scholar 대체로 OpenAlex·Semantic Scholar API, KCI, DBpia, RISS, arXiv/ACL Anthology).
- 인용 수 기준: 국제 논문은 **OpenAlex `cited_by_count` (2026-09-02 조회)**. Google Scholar는 보통 이보다 2~3배 높게 나오므로 순위 비교용으로만 쓴다. 국내 논문은 **KCI 피인용 횟수** 또는 DBpia 표기 값.
- Semantic Scholar는 조회 중 429(rate limit)가 걸려 일부만 확보했다. 조회 실패한 논문은 표에 "미조회"로 남긴다.
- 선정 기준: (1) 언론 보도 자체의 편향(선택·논조·프레임)을 다루는가, (2) 정치 행위자(정당·정치인)에 대한 보도를 대상으로 하는가, (3) 측정 방법이 코드로 옮길 수 있는가.

---

## 3. 국제 논문 Top 10 (인용 수 순)

| # | 논문 | 인용 수 (OpenAlex) | 핵심 개념 | 우리 알고리즘에 적용할 부분 |
|---|---|---|---|---|
| 1 | Entman, R. (1993). *Framing: Toward Clarification of a Fractured Paradigm*. J. of Communication 43(4). | 15,904 | 프레이밍 = 선택(selection)과 현저성(salience). 같은 사실도 어떤 측면을 부각하느냐로 평가가 갈림 | "무엇을 말했는가"와 "기자가 어떻게 포장했는가"를 분리해야 함 → 알고리즘 4 |
| 2 | Galtung, J. & Ruge, M. (1965). *The Structure of Foreign News*. J. of Peace Research 2(1). | 3,363 | 뉴스 가치 12개. 부정성, 갈등, 엘리트 인물, 개인화가 보도 확률을 높임 | 갈등 36 : 우호 3 은 보도 선택 확률의 비대칭. 역확률 가중이 필요 → 알고리즘 3 |
| 3 | Mullainathan, S. & Shleifer, A. (2005). *The Market for News*. American Economic Review 95(4). | 1,225 | 편향은 독자 수요에서 나옴. 독자가 **여러 매체를 교차해 읽으면(cross-checking)** 편향이 상쇄됨 | 진영이 다른 언론사들이 같은 극성을 보고할 때만 신뢰 → 알고리즘 2 |
| 4 | Harcup, T. & O'Neill, D. (2001). *What Is News? Galtung and Ruge Revisited*. Journalism Studies 2(2). | 1,158 | 뉴스 가치 재검증. 나쁜 뉴스, 갈등, 권력 엘리트가 여전히 핵심 선택 기준 | 2번과 같음. 갈등 기사 과잉의 이론적 근거 |
| 5 | Gentzkow, M. & Shapiro, J. (2006). *Media Bias and Reputation*. J. of Political Economy 114(2). | 1,045 | 매체는 독자의 사전 신념에 맞추는 쪽으로 기울며, 경쟁·교차 검증 가능성이 편향을 줄임 | 언론사별 성향 추정치를 두고 보정해야 함 → 알고리즘 1, 2 |
| 6 | Groseclose, T. & Milyo, J. (2005). *A Measure of Media Bias*. Quarterly J. of Economics 120(4). | 1,005 | 매체가 인용하는 싱크탱크 분포를 의원들의 인용 분포와 비교해 매체 성향 점수(ADA 척도)를 산출 | 언론사 성향을 **손으로 라벨링하지 않고 데이터로 추정**하는 원형 → 알고리즘 1 |
| 7 | Vallone, R., Ross, L. & Lepper, M. (1985). *The Hostile Media Phenomenon*. J. of Personality and Social Psychology 49(3). | 872 (+752 중복 DOI) | 같은 보도를 봐도 양쪽 당파 모두 "우리 편에 불리하다"고 지각함 | reddit의 "편향" 지적 일부는 이 효과일 수 있음. 반박이 아니라 **근거 공개(언론사 분포·불확실성)**로 대응 → §7 |
| 8 | Soroka, S. (2006). *Good News and Bad News: Asymmetric Responses to Economic Information*. J. of Politics 68(2). | 861 | 언론은 부정 정보를 긍정 정보보다 훨씬 많이, 크게 다룸 | 우호 관계는 뉴스가 안 되므로 뉴스만으로는 우호 엣지가 구조적으로 부족 → 알고리즘 3 |
| 9 | Gentzkow, M. & Shapiro, J. (2010). *What Drives Media Slant? Evidence from U.S. Daily Newspapers*. Econometrica 78(1). | 573 (NBER 판) / S2 1,359 | 의회 회의록에서 정당별 특징 어구를 뽑고, 신문이 어느 쪽 어구를 쓰는지로 slant 지수 산출 | 국회 회의록 + 기사 본문으로 한국 언론사 slant를 자동 추정 가능 → 알고리즘 1 |
| 10 | D'Alessio, D. & Allen, M. (2000). *Media Bias in Presidential Elections: A Meta-Analysis*. J. of Communication 50(4). | 518 | 편향을 **게이트키핑(어떤 사건을 싣나)·보도량(coverage)·진술(statement, 논조)** 세 가지로 분해 | 한 점수로 뭉개지 말고 세 축을 따로 측정·표시 → 알고리즘 2(게이트키핑), 3(보도량), 1(논조) |

### 3.1 인용 수는 낮지만 설계에 직접 쓰이는 논문

| 논문 | 인용 수 | 왜 필요한가 |
|---|---|---|
| Baron, D. (2006). *Persistent Media Bias*. J. of Public Economics 90. | 499 | 편향은 매체가 아니라 **기자 개인 수준**에서도 지속됨. 기자 바이라인을 저장하면 보정 단위를 더 잘게 가져갈 수 있음 |
| Gentzkow, Shapiro & Taddy (2019). *Measuring Group Differences in High-Dimensional Choices*. Econometrica 87(4). | 395 | 회의록에서 정당 특징 어구를 뽑는 통계적으로 안전한 방법(단순 χ²는 과적합). 알고리즘 1의 도구 |
| Chakraborty et al. (2016). *Stop Clickbait*. ASONAM. | 346 | 클릭베이트 제목 탐지 특성(감탄·의문·수사, 제목-본문 불일치). 어그로 기사 할인 → 알고리즘 5 |
| Budak, Goel & Rao (2016). *Fair and Balanced? Quantifying Media Bias through Crowdsourced Content Analysis*. Public Opinion Quarterly 80(S1). | 337 | 15개 매체 분석 결과 매체들은 생각보다 비슷하며 **스캔들 기사에서만 당파성이 튄다**. 스캔들·갈등 기사에 특히 교차 검증이 필요한 근거 |
| Trussler & Soroka (2014). *Consumer Demand for Cynical and Negative News Frames*. Int'l J. of Press/Politics 19(3). | 336 | 독자가 부정·냉소 프레임을 실제로 더 선택함. 부정성 편향이 공급과 수요 양쪽에서 생긴다는 근거 |
| Recasens, Danescu-Niculescu-Mizil & Jurafsky (2013). *Linguistic Models for Analyzing and Detecting Biased Language*. ACL. | 296 | 편향 언어를 **프레이밍 편향**(주관어·강조어)과 **인식론적 편향**(사실동사·함축동사·헤지)으로 나누고 단서 어휘를 제시. 기자 서술 톤 탐지의 기초 → 알고리즘 4 |
| Hamborg, Donnay & Gipp (2019). *Automated identification of media bias in news articles: an interdisciplinary literature review*. Int'l J. on Digital Libraries 20. | 216 | 편향을 생산 단계별로 분류: 사건 선택, 취재원 선택, 누락/포함, 표현·라벨링, 배치, 사진, spin. 우리 파이프라인의 어느 단계가 어떤 편향에 노출되는지 대조표의 기준 |
| Hansen & Kim (2011). *Is the Media Biased Against Me? A Meta-Analysis of the Hostile Media Effect Research*. Communication Research Reports 28. | 152 | 34개 연구 메타분석. 관여도가 높을수록 적대적 매체 지각이 커짐. 정치 관계도 이용자는 관여도가 높은 집단 |
| Eberl, Boomgaarden & Wagner (2017). *One Bias Fits All? Three Types of Media Bias and Their Effects on Party Preferences*. Communication Research 44(8). | 149 | 편향을 **가시성(visibility)·논조(tonality)·의제(agenda)**로 나눠 측정. 논조와 의제 편향만 정당 선호에 영향. 관계도는 논조 편향 보정이 1순위라는 근거 |
| Hamborg & Donnay (2021). *NewsMTSC: (Multi-)Target-dependent Sentiment Classification in Political News Articles*. EACL. | 55 | 뉴스는 리뷰와 달리 감성이 암시적이고 한 문장에 여러 표적이 있음. 표적별 감성 분류 데이터셋과 모델 → 알고리즘 4 |
| Kim, Lelkes & McCrain (2022). *Measuring dynamic media bias*. PNAS 119(32). | 45 | 매체 편향은 주 단위로도 크게 흔들림. 등장 인물의 이념 평균(가시성 편향)을 시계열로 측정. 편향 추정치를 고정값이 아닌 시계열로 관리 → 알고리즘 5 |
| Ban, Fouirnaies, Hall & Snyder (2019). *How Newspapers Reveal Political Power*. Political Science Research and Methods 7(4). | 33 | 보도량 자체가 권력 지표. 보도량(가시성)은 호불호와 분리해 다뤄야 함 |
| Padgett, Dunaway & Darr (2019). *As Seen on TV? How Gatekeeping Makes the U.S. House Seem More Extreme*. J. of Communication 69(6). | 미조회(API 제한) | 46,218건 TV 대본 분석. 게이트키핑이 **극단 성향 의원을 과대 대표**함. 갈등 엣지가 특정 의원에 몰리는 현상의 설명 |
| Wagner & Gruszczynski (2018). *Who Gets Covered? Ideological Extremity and News Coverage of Members of the U.S. Congress*. Int'l J. of Press/Politics 23(3). | 미조회(API 제한) | 하원에서 이념 극단성이 보도량과 양의 상관. 보도량 기반 주목도는 "영향력"이 아니라 "극단성+갈등"을 측정한다는 경고 |

---

## 4. 국내 논문 (KCI 피인용 기준)

| 논문 | 학술지 | KCI 피인용 | 핵심 내용 | 적용 |
|---|---|---|---|---|
| 이준웅 (2002). 갈등적 이슈에 대한 뉴스 프레임 구성방식이 의견형성에 미치는 영향 | 한국언론학보 46(1) | 132 | 갈등 이슈 프레임이 수용자 의견 형성에 미치는 영향의 내러티브 해석모형 | 갈등 프레임 = 한국 정치 보도의 기본값. 알고리즘 3의 국내 근거 |
| 이종혁 (2015). 언론 보도에 대한 편향적 인식이 공정성 평가에 미치는 영향: 우호적·중립적·적대적 매체 비교 | 한국언론학보 59(1) | 38 (DBpia) | 2012 대선 보도. 우호 매체엔 동화, 적대 매체엔 대조 편향. 중립 매체가 가장 공정하다고 평가받음 | 한국판 적대적 매체 효과. reddit 반응 해석과 UI 대응(§7) |
| 최창식·임영호 (2021). 대통령 관련 보도의 감성 분석과 정파성의 지형 | 한국언론학보 65(1) | 37 | 10개 신문 약 9만 건, KNU 감성사전으로 신문별 감성지수. 한겨레 가장 긍정, 조선 유일 부정. 한겨레 제외 전 신문 지수가 지지율과 상관 | **언론사×대상 논조 기준선**을 만드는 국내 선례. 알고리즘 1의 초기값 |
| 이재완·김용환 (2023). 언론사의 정파성에 따른 이태원 참사 뉴스 프레임 비교 | 정치커뮤니케이션연구 71 | 13 | 조선·중앙·동아 vs 한겨레·경향 토픽모델링·의미연결망 | 진영 클러스터 정의(보수/진보)의 근거. 알고리즘 2 |
| 김나현·이상엽 (2022). 신문사의 정치 성향에 따른 코로나19 보도 내용 분석 | 정보사회와 미디어 23(1) | 11 | 기계학습·네트워크·토픽모델링으로 신문사 성향별 보도 차이 | 언론사 성향 자동 분류가 한국어에서 되는 근거 |
| 유재광·오경수 (2012). 신문의 뉴스프레임과 정치인 발언 보도태도 연구: 미디어법 이슈 | 정치커뮤니케이션연구 26 | 10 | 5개 신문 494건. **같은 정치인 발언을 신문이 자사 프레임에 맞춰 선택·해석** | 발언(정치인) vs 해석(기자)을 분리해야 하는 직접 근거. 알고리즘 4 |
| 박영흠 (2024). 한국 언론 정파성의 기원과 형성: 신문의 적대적 정파성 | 언론과 사회 32(2) | 6 | 민주화 이후 신문이 생존 전략으로 상대 진영을 공격하는 "적대적 정파성" 채택 | 한국 언론 편향이 논조 편향(tonality)이 아니라 **공격 선택 편향**임을 시사. 알고리즘 2·3 |
| 양혜승 (2017). 정치뉴스의 갈등 프레임이 수용자의 이슈 인식, 정서 반응, 뉴스 기억에 미치는 영향 | 지역과 커뮤니케이션 21(4) | 5 | 갈등 프레임 기사는 해결 가능성을 더 부정적으로 인식시키고 분노를 유발 | 갈등 엣지의 과다 표시가 이용자 인식에 미칠 영향. UI 경고 근거 |
| 정성호·이준호 (2011). 국회 의정활동과 구사언어에 대한 신문보도 내용분석 | 정치커뮤니케이션연구 20 | 4 | 2010년 4개 신문 14,357건. 국회의원 발언 보도는 중립이 다수지만 **부정 > 긍정**, 정당 친화적 신문일수록 해당 정당 보도량 높음 | 한국 국회 보도의 부정성·보도량 편향 실측치. 알고리즘 3의 사전확률 |
| 최선규·유수정·양성은 (2012). 뉴스 시장의 경쟁과 미디어 편향성: 취재원 인용을 중심으로 | 정보통신정책연구 19(2) | 미조회 | 12개 매체 10개 이슈, Groseclose-Milyo 방식(취재원 인용)으로 이념 점수. 한국 언론 평균은 보수 편향, 신문이 방송보다 분산 큼 | Groseclose-Milyo가 한국에서 작동한 선례. 알고리즘 1 |
| 이신행 (2024). 국내 주요 종합일간지의 이념 성향에 따른 15~20대 대선 보도 편향과 이슈 현저성 | 한국언론학보 68(3) | 미조회 | 9개 일간지, 보도량 편향 지수 + 이슈 현저성. 편향은 신문 간 차이보다 **선거 시기별 차이**가 큼 | 언론사 성향 점수를 고정값이 아니라 기간별로 재추정해야 함. 알고리즘 5 |
| Kim, Lee & Na (2023). *A New Korean Text Classification Benchmark for Recognizing the Political Intents in Online Newspapers* (KoPolitic). arXiv:2311.01712 | arXiv | 1 | 보수2·중도2·진보2 신문 정치면 12,000건. 정치 성향(1~5)·친정부(0~5) 이중 라벨. KoBERT/KoBigBird 등 베이스라인 | 한국어 기사 성향 분류기의 학습 데이터. 알고리즘 1의 부트스트랩 |

참고 데이터: AI Hub "낚시성 기사 탐지 데이터"(약 36만 건, 제목-본문 일관성 라벨)는 알고리즘 5의 어그로 할인에 바로 쓸 수 있다.

---

## 5. 논문이 말하는 편향 유형 ↔ 현재 코드의 취약 지점

| 편향 유형 (출처) | 정의 | 현재 코드에서 드러나는 곳 | 보정 알고리즘 |
|---|---|---|---|
| 게이트키핑/사건 선택 (D'Alessio & Allen; Hamborg) | 어떤 사건을 기사로 만들 것인가 | 한 진영 매체만 보도한 갈등도 엣지로 확정 | 2 |
| 보도량/가시성 (D'Alessio & Allen; Eberl; Ban; Padgett) | 누가 얼마나 자주 등장하나 | 주목도 점수 = 보도량. 극단·갈등형 의원에 쏠림 | 3, 5 |
| 논조/진술 (D'Alessio & Allen; Eberl; 최창식·임영호) | 등장 인물을 어떻게 평가하나 | 언론사 정보가 엣지에 없어 논조 기준선을 뺄 수 없음 | 1 |
| 부정성/갈등 뉴스가치 (Galtung & Ruge; Soroka; 이준웅; 정성호·이준호) | 부정·갈등이 보도될 확률이 훨씬 높음 | 갈등 36 : 우호 3 | 3 |
| 발언 선택·해석 (유재광·오경수; Entman) | 같은 발언을 매체가 자사 프레임에 맞춰 재구성 | NLI가 "서로 적대적"만 묻고 발화 주체·인용 여부를 안 봄 | 4 |
| 프레이밍/인식론적 언어 편향 (Recasens) | 기자의 주관어·헤지·함축 | 기자 서술 문장이 정치인 발언과 동일 가중 | 4 |
| 어그로/클릭베이트 (Chakraborty; AI Hub) | 제목-본문 불일치, 자극 어휘 | 기사 단위 최대값 채택이라 자극 문장 하나가 기사 대표 | 5 |
| 통신사 전재/중복 (연합뉴스 포털 송고 70%+) | 같은 사건이 여러 URL로 반복 | dedup 죽은 코드, 마지막 기사가 덮어씀 | 5 |
| 동적 편향 (Kim, Lelkes & McCrain; 이신행) | 편향이 시기별로 변함 | 누적 엣지에 시간 정보 없음 | 5 |
| 적대적 매체 지각 (Vallone; Hansen & Kim; 이종혁) | 관여도 높은 이용자는 어느 쪽이든 편향을 지각 | 근거 링크 1개, 언론사 분포·불확실성 미표시 | §7 (UI) |

---

## 6. 추천 알고리즘 5개

### 6.0 선행 필수 작업 (모든 알고리즘의 전제) — 구현 완료

집계 기반 보정은 관측이 쌓여야 가능한데 예전에는 마지막 기사 하나만 남았다. 아래 세 가지를 먼저 넣었다.

1. **관측 로그 테이블** `edge_observations`. 기사 한 건의 판정 하나가 한 행이다. `(pair_key, url)` 유니크라 재수집해도 표본이 부풀지 않는다. 컬럼은 `docs/GRAPH_STRUCTURE.md` 참조.
2. **언론사 저장**: 관측마다 `press` 와 `camp` 를 남긴다. 기자 바이라인(Baron 2006)은 아직 안 넣었다.
3. **방향 무효화**: `pair_key` 가 이름을 가나다순으로 정렬해 무방향 키를 만든다. 프론트는 호불호 엣지에 화살표를 그리지 않는다.

흐름이 바뀐 부분:

```
예전:  기사 -> 쌍마다 POST /api/edge -> dict.update (마지막 기사가 덮어씀)
지금:  기사 -> edge_observations 적재
       수집 종료 -> 쌍마다 집계 -> 쌍당 POST /api/edge 한 번
```

`/api/edge` 는 호불호 엣지를 쓸 때 같은 쌍의 나머지 감정 엣지를 지운다. 예전에는 두 극성이 서로 다른 행이라 같은 두 사람 사이에 우호와 대립이 동시에 남을 수 있었다.

**함께 정리한 것 둘.**

- 임포터의 샘플 관계 다섯 건(`("권성동","이재명","NEGATIVE_SENTIMENT",95,...)` 등) 생성을 중단했다. 근거 기사도 언론사도 없는 숫자가 실제 관측과 나란히 놓였고 척도마저 달랐다(샘플 0~100, 실제 0~1). 신뢰도를 논하는 대시보드에서 가장 먼저 빠져야 할 데이터다. 이미 저장된 것은 `scripts/backfill_edge_observations.py` 가 목록으로 보여 주고, `--drop-unsourced` 를 줄 때만 지운다.
- DCP 호출을 파이프라인에서 뺐다. `DCPCalculator` 가 동맹 문맥을 `http://localhost:5000` 에서 가져오도록 되어 있어 GitHub Actions 에서는 매번 실패하고 입력을 그대로 돌려줬다. 즉 `social_impact_score` 는 늘 `score` 와 같았다. 게다가 동맹을 "같은 정당"으로 정의해 정파 구조를 보정하는 게 아니라 증폭한다. 지금은 집계가 `social_impact_score` 를 채우고, 동맹 정의는 알고리즘 3에서 공동발의로 바꾼 뒤 되살린다.

### 알고리즘 1. 언론사 성향 보정 가중 합산 (Outlet-Slant-Adjusted Tonality)

**근거**: Groseclose & Milyo 2005, Gentzkow & Shapiro 2010, Gentzkow·Shapiro·Taddy 2019, Eberl et al. 2017(논조 편향), 최선규 외 2012, 최창식·임영호 2021, KoPolitic 2023.

**아이디어**: 언론사 o가 정당 p 소속 인물을 평소에 얼마나 부정적으로 쓰는지(언론사×정당 논조 기준선)를 데이터로 추정해 두고, 각 관측에서 그 기준선을 뺀다. 조선일보가 민주당 의원을 비판적으로 쓴 기사와 한겨레가 같은 의원을 비판적으로 쓴 기사는 정보량이 다르다.

**수식**:

```
y_a ∈ [-1, 1]      기사 a의 부호 있는 NLI 점수 (+우호, −적대)
b[o, p] = mean(y_a : press(a)=o, target party=p) − mean(y_a : 전체)
b'[o, p] = n[o,p] / (n[o,p] + k) · b[o, p]          # k≈30, 표본 적으면 0으로 수축
y'_a = y_a − b'[press(a), party(target)]
S_ij = Σ_a w_a · y'_a / Σ_a w_a                    # w_a는 알고리즘 5의 가중치
```

**언론사 성향 초기값**: 최창식·임영호(2021)의 신문별 감성지수 순위와 KoPolitic의 보수2/중도2/진보2 분류를 사전값으로 쓰고, 관측이 쌓이면 위 b 테이블로 대체한다. 더 나아가면 Gentzkow-Shapiro 방식으로 **열린국회정보 회의록**에서 정당 특징 어구를 뽑아 언론사별 사용률로 slant를 자동 추정한다(어구 선택은 Gentzkow·Shapiro·Taddy 2019의 벌점 회귀를 써야 과적합을 피함).

**적용 위치**: 새 모듈 `backend/core/bias_correction.py`. 야간 배치에서 b 테이블 재계산 후 `turing_edges` 집계.
**데이터 요구**: 엣지별 press(선행 작업 2). 정당 정보는 이미 노드에 있음.
**리스크**: 표본이 적은 언론사×정당 조합은 노이즈. 수축 계수 k로 방어하고, b 테이블은 공개해서 검증받는다.

### 알고리즘 2. 진영 교차 검증 (Cross-Camp Corroboration)

**근거**: Mullainathan & Shleifer 2005(교차 읽기가 편향을 상쇄), Gentzkow & Shapiro 2006, Budak·Goel·Rao 2016(스캔들에서만 당파성이 튐), D'Alessio & Allen 2000(게이트키핑), 박영흠 2024(적대적 정파성), 이재완·김용환 2023.

**아이디어**: 갈등 보도가 한 진영 매체에서만 나오면 "사건"이 아니라 "공격 선택"일 수 있다. 진영이 다른 매체가 같은 극성을 독립적으로 보도했을 때만 엣지 신뢰도를 올린다.

**수식**:

```
C = {보수, 중도·통신·방송, 진보}                 # 언론사 → 진영 매핑 (알고리즘 1의 slant로 갱신)
q_c = 진영 c 기사 중 극성 s를 지지하는 비율 (기사 없으면 0)
κ_ij = |{c : q_c > 0}| / |C|                     # 진영 커버리지
conf_ij = 1 − Π_c (1 − q_c)                      # 독립 확인 확률
edge_weight = |S_ij| · (0.5 + 0.5 · κ_ij)
```

**표시 규칙**: κ < 2/3 이면 점선 + "단일 진영 보도" 배지. 툴팁에 진영별 기사 수를 그대로 보여준다.
**적용 위치**: `bias_correction.py` 집계 단계, `turingdb_server.py`의 엣지 응답에 `camp_coverage`, `confidence` 필드 추가, 프론트 스타일 분기(`App.jsx:610-622`).
**데이터 요구**: press → 진영 매핑 테이블. 네이버는 수십 개 언론사를 모으므로 추가 수집 없이 가능.
**리스크**: 중도 진영에 통신사(연합·뉴시스·뉴스1)를 넣으면 전재 기사 때문에 항상 κ가 채워짐. 알고리즘 5의 사건 클러스터링을 먼저 적용해야 한다.

#### 구현 (2026-09-03) — 신뢰도 수식을 바꿨다

위에 적은 `conf = 1 − Π(1 − q_c)` 는 쓸 수 없다. 한 진영이 만장일치면 `q = 1` 이라 곱이 0이 되고 `conf = 1` 이 나온다. 즉 **한 진영만 보도해도 신뢰도가 최대**가 된다. 교차 검증을 하려던 목적과 정반대다.

진영을 잡음 섞인 관측자로 보는 형태로 바꿨다(`core/relation_evidence.py` 의 `_confidence`).

```
진영 c 에 대해
    s_c = 현재 극성을 지지하는 사건 수
    n_c = 그 진영의 전체 사건 수
    r_c = CAMP_RELIABILITY · (1 − 0.5^s_c) · (s_c / n_c)     # CAMP_RELIABILITY = 0.7
conf = 1 − Π_c (1 − r_c)
```

`(1 − 0.5^s_c)` 는 같은 진영 안에서 사건이 늘수록 신뢰가 오르되 1에 수렴하게 하고, `CAMP_RELIABILITY` 가 그 상한을 0.7로 누른다. `s_c / n_c` 는 진영 안에서 극성이 갈리면 깎는다. 결과:

| 근거 | conf |
|---|---|
| 보수 1건 | 0.35 |
| 보수 3건 | 0.61 |
| 보수 12건 | 0.70 (상한) |
| 보수 1 + 진보 1 | 0.58 |
| 보수 3 + 진보 3 | 0.85 |

한 진영이 아무리 많이 써도 두 진영이 각자 쓴 것을 못 넘는다. 이것이 Mullainathan & Shleifer(2005)의 교차 확인 논지다.

**전재 대응**: 클러스터 하나가 여러 진영에 걸치면 그 진영들을 각각 세지 않고 중도(통신)로 접는다(`media_outlets.cluster_camp`). 여러 진영이 같은 원문을 실은 것은 각 진영의 편집 판단이 아니라 통신사 한 곳의 판단이기 때문이다. 실측으로 확인했다. 연합·조선·한겨레가 같은 전재본을 실으면 κ = 1/3 에 머물고, 경향이 독자 취재를 하나 보태야 κ = 2/3 으로 올라간다.

**진영 매핑**: `core/media_outlets.py` 에 표로 두고 근거를 함께 적었다. 모르는 매체는 억지로 배정하지 않고 중도로 둔다.

### 알고리즘 3. 부정성 선택 편향 역가중 + 협력 사전확률 (Negativity IPW with Co-sponsorship Prior)

**근거**: Galtung & Ruge 1965, Harcup & O'Neill 2001, Soroka 2006, Trussler & Soroka 2014, Padgett et al. 2019, Wagner & Gruszczynski 2018, 정성호·이준호 2011, 이준웅 2002.

**아이디어**: 협력은 뉴스가 안 되고 갈등은 뉴스가 된다. 그래서 뉴스만 보면 우호 관계가 구조적으로 사라진다. 뉴스 선택을 거치지 않는 **공동발의(열린국회정보 의안 API)**를 협력의 실측치로 삼아, (a) 우호 관측의 선택 확률을 추정해 역가중하고 (b) 쌍마다 사전확률을 준다.

**수식**:

```
π_pos = P(뉴스에 우호 관측 | 공동발의 ≥ k 인 쌍)
π_neg = P(뉴스에 적대 관측 | 반대 정당 & 회의록 상호 반박 있는 쌍)
w_a  *= min(π_neg / π_pos, 5)  (우호 관측에만)          # 역확률 가중, 상한 5

μ_ij = +0.3 (공동발의 ≥ k) / −0.2 (반대 정당 & 공동발의 0) / 0 (그 외)
S_ij^post = (n0 · μ_ij + Σ_a w_a y'_a) / (n0 + Σ_a w_a)   # n0 ≈ 2, 사전 강도
엣지 표시 조건: |S_ij^post| > τ  이고  Σ_a w_a ≥ 2
```

**부수 효과**: DCP의 "같은 정당 = 동맹" 휴리스틱(`turingdb_server.py:439-450`)을 "공동발의 ≥ k = 동맹"으로 바꾸면 정파 구조를 그대로 증폭하는 문제가 사라진다. 갈등 엣지 하나로 확정하던 것도 관측 2건 이상으로 올라간다.
**적용 위치**: 새 수집기 `backend/crawlers/assembly_bills_pipeline.py`(공동발의 그래프), `dcp_algorithm.py` 동맹 정의, `bias_correction.py` 사전확률.
**데이터 요구**: 22대 국회 의안 공동발의자 목록. 공개 API라 부담 적음.
**리스크**: π 추정은 초기 표본이 작다. 처음엔 π_neg/π_pos를 정성호·이준호(2011)의 부정 > 긍정 비율에서 보수적으로 잡고(예: 2.0), 관측이 쌓이면 갱신한다.

#### 구현 (2026-09-03) — 그래프만, 역가중은 아직

공동발의 수집과 DCP 동맹 정의 교체까지 했다. 사전확률·역가중은 관측이 더 쌓여야 한다.

**수집**: 열린국회정보 OpenAPI 의 "국회의원 발의법률안"(`nzmimeepazxkubdpn`)에서 22대 법안을 받는다. `RST_PROPOSER`(대표발의)와 `PUBL_PROPOSER`(공동발의, 쉼표 구분)를 읽어 쌍을 센다. 이름은 "강경숙의원", "나경원(국민의힘)" 처럼 표기가 흔들려 정리한 뒤 의원 명부와 교집합만 남긴다. 명부에 없는 이름(전직 의원, 정부 제출)은 버린다. 억지로 맞추면 없는 협력 관계가 생긴다.

**API 키가 필요하다.** `ASSEMBLY_API_KEY` 를 환경변수로 넣는다. open.assembly.go.kr 에서 발급받는다. 키가 없으면 수집기는 안내만 남기고 끝나며, 나머지 파이프라인을 막지 않는다. **2026-09-03 현재 키를 발급받지 않기로 해서 이 표는 비어 있다.** 위 "공동발의는 비어 있다" 절을 본다.

**DCP 동맹 정의 교체**: `/api/dcp/context` 가 공동발의 5건 이상인 상대를 동맹으로 본다. 예전 정의("같은 정당")로는 같은 당 의원 170명이 서로 전부 동맹이라, 공명 점수가 사실상 정당 소속을 되풀이했다. 편향을 보정하려는 자리에서 정파 구조를 증폭하고 있었다. 공동발의 자료가 아직 없으면 예전 정의로 물러서되, 응답의 `ally_basis` 에 `same_party_fallback` 이라고 밝힌다.

같은 자리에서 `count` 속성을 읽던 코드도 고쳤다. 그 속성은 뉴스 파이프라인이 쓴 적이 없어 늘 1이었다. 지금은 집계가 남기는 사건 수(`n_clusters`)를 쓴다.

**감사 화면 대조**: `GET /api/relations/evidence?a=&b=` 응답에 `cosponsored_bills` 를 함께 준다. 뉴스가 갈등이라고 말하는 두 사람이 법안을 몇 건 함께 냈는지가 판단에 필요하다.

### 알고리즘 4. 발화 주체 귀속 표적 감성 (Attributed Target-Dependent Stance)

**근거**: Entman 1993, Recasens et al. 2013, Hamborg 2020, Hamborg & Donnay 2021(NewsMTSC), 유재광·오경수 2012, Baron 2006.

**아이디어**: 지금 NLI는 "A와 B는 서로 적대적이다"만 묻는다. "A가 B를 비판했다"(정치인 발언, 사실)와 "기자가 A·B를 대립 구도로 서술했다"(프레이밍)는 다른 정보다. 관계 엣지는 **정치인이 발화 주체인 진술**로만 만들고, 기자 서술의 평가어는 언론사 논조 추정(알고리즘 1)의 입력으로 돌린다. 이렇게 하면 엣지 방향도 비로소 의미를 갖는다.

**추출 스키마** (창 단위):

```
{ holder: A, target: B,
  stance: support | oppose | neutral,
  evidence_type: direct_quote | indirect_quote | reporter_narration,
  hedged: bool,           # "관측", "전망", "~것으로 보인다", "설"
  span: 원문 }
```

**가중치**:

```
직접 인용 1.0 / 간접 인용 0.7 / 기자 서술 0.3(엣지엔 미반영, 논조 추정에만)
hedged 이면 × 0.5
기사 점수 = 상위 3개 창의 평균 (현재의 단일 최대값 대체)
```

**구현 경로 두 가지**:
- 저비용: NLI 가설을 방향형으로 바꾼다. `affective_analysis.py:96-97`의 두 가설을 "{A}은(는) {B}을(를) 비판하거나 공격했다 / 지지하거나 옹호했다" 및 그 역방향까지 4개로 늘리고, 인용 단서("라고", "고 말했다", "밝혔다", 따옴표)로 evidence_type을 규칙 판정.
- 고품질: DCP 논문(`docs/DCP_paper.txt:96`)이 원래 상정한 LLM 구조화 추출. 위 스키마를 JSON으로 뽑는다. 비용은 기사당 1회로, 현재 O(n²) NLI 호출보다 오히려 적다.

**적용 위치**: `affective_analysis.py:61-113` 전면 교체, `news_crawler_pipeline.py:529-543`의 쌍 열거를 추출 결과 순회로 변경.
**리스크**: 한국어 인용 구조는 주어 생략이 많다. 창 크기 3문장은 유지하되, holder를 못 찾은 창은 reporter_narration으로 강등한다.

#### 구현 (2026-09-03) — 회수와 정밀도가 함께 올랐다

저비용 경로(방향형 NLI + 인용 단서 규칙)로 갔다. LLM 추출은 GitHub Actions 90분 예산과 API 비용 때문에 보류했다.

**먼저 비용을 쟀다.** CPU(러너에는 GPU 가 없다) 기준 NLI 1회 101ms, 5명이 등장하는 기사 1건에 1.6초. 가설을 4개로 늘리면 기사 3000건이 8스레드에서 약 20분이다. 예산 안이라 진행했다.

**대칭 가설이 관계를 버리고 있었다.** 재는 김에 실측했더니, 교과서적인 갈등 문장에서 관계가 하나도 나오지 않았다.

| 전제: "나경원 의원은 이재명 대표를 겨냥해 비판했다" | 함의 확률 |
|---|---|
| 대칭 (현재) "서로 적대적이거나 비판적인 관계이다" | 0.607 |
| 방향형 "나경원은 이재명을 비판했다" | 0.956 |
| 역방향 "이재명은 나경원을 비판했다" | 0.093 |

대칭 가설은 *상호* 상태를 주장하는데, 한쪽이 비판한 문장은 그것을 함의하지 않는다. 임계값 0.65 를 못 넘어 버려졌다. 이것이 엣지가 39개뿐이었던 이유 중 하나다.

**공동 언급을 관계로 읽는 문제는 앵커 규칙으로 막았다.** 방향형 가설만 넣으면 회수가 늘면서 오탐도 는다. 의원 5명이 나오는 기사에서 실측:

| 창 안에 두 이름이 있으면 인정 | 관계 10개 (그중 6개가 서로 아무 말도 하지 않은 쌍) |
|---|---|
| 같은 문장에 함께 나올 때만 인정 | 관계 4개, 전부 실제 관계 |

셋 이상이 섞인 창에서는 같은 문장을 요구하고, 창 안에 두 사람뿐이면 창 전체를 인정한다. 후자는 "나 의원", "이 대표" 같은 축약 지칭을 살리기 위해서다. 순수 공동 언급 기사("두 사람이 같은 행사에 참석했다")는 이제 관계를 만들지 않는다.

**방향은 절대 점수가 아니라 두 방향의 차이로 판정한다.** 갈등 문맥에서는 모델이 역방향에도 후하게 답한다(위 표에서도 역방향이 0.672 까지 나온 창이 있었다). 같은 창에서 두 방향을 나란히 물어 0.10 이상 차이가 날 때만 방향을 인정하고, 기사 단위로 모아 한쪽이 두 배를 넘을 때만 엣지에 화살표를 준다. 서로 주고받은 관계는 `mutual` 로 남는다.

**부수 수정**: 창 안 이름 확인이 단순 부분일치였다. `find_names` 로 바꿔, `extract_politicians` 가 막아 둔 김건/김건희 류 오탐이 이 단계에서 다시 들어오는 길을 닫았다. 문장 분리도 `split('.')` 에서 정규식으로 바꿔 "3.5%" 에서 쪼개지지 않게 했다.

**남은 한계**: 기자 서술을 엣지에서 완전히 빼는 원안 대신 0.3 무게로 눌러 두었다. 지금 수집량에서 빼면 관계 대부분이 사라진다. `RELATION_DROP_NARRATION=1` 로 끌 수 있고, `evidence_type` 이 관측에 남아 있어 알고리즘 1이 서술만 따로 쓸 수 있다.

### 알고리즘 5. 사건 단위 중복 제거 + 어그로 할인 + 시간 감쇠 (One Event, One Vote)

**근거**: Chakraborty et al. 2016, Potthast et al. 2016, AI Hub 낚시성 기사 탐지 데이터, Kim·Lelkes·McCrain 2022(동적 편향), 이신행 2024(시기별 편향), Ban et al. 2019(보도량은 별도 지표), 연합뉴스 포털 송고 비중(70%+), 저장소의 `.refs` EWMA 메모.

**아이디어**: 같은 사건을 다룬 전재 기사 20건은 관측 1건이다. 자극적 제목의 기사는 신호가 아니라 잡음에 가깝다. 그리고 편향과 관계는 시간에 따라 변하므로 "최근 논조"와 "충돌 이력"을 따로 든다.

**절차**:

```
(a) 사건 클러스터링
    본문 앞 1,000자 SimHash, Jaccard ≥ 0.8  또는
    같은 날 + 같은 의원 집합 + 제목 코사인 ≥ 0.7   → 동일 cluster_id
    클러스터당 관측 1건, 언론사 목록은 클러스터에 합침 (알고리즘 2의 κ 계산용)
    복제 수 log(1 + copies)는 주목도(hotness)에만 반영

(b) 어그로 할인
    p_cb = 제목-본문 일관성 분류기 확률 (AI Hub 데이터로 학습) 또는 제목 단서 사전
    w_a = focus_weight(n_names) · (1 − 0.5 · p_cb)          # focus_weight는 hotness.py:111-118 재사용

(c) 시간 감쇠 (쌍 단위, 일 단위 스텝)
    S_t = α · C_t + (1 − α) · S_{t−1},  α = 0.2 (반감기 약 3일) 또는 반감기 90일 지수감쇠
    별도 보관: n_total, first_seen, last_seen, 최대 |y'|   → "충돌 이력" 뷰
```

**표시**: 현재 관계도는 S_t(최근 논조)로, "누적" 패널은 n_total·first_seen으로 그린다. reddit 글에서 고민한 누적 vs 7일 창 문제를 두 값을 모두 저장하는 것으로 푼다.
**적용 위치**: `news_crawler_pipeline.py:518-527`(죽은 dedup 교체), `hotness.py`(EWMA 유틸), `bias_correction.py`.
**리스크**: SimHash 임계값을 높게 잡으면 후속 보도가 같은 사건으로 묶인다. 클러스터를 24시간 창으로 제한한다.

#### 구현 (2026-09-03) — (a)와 (c)만, (b)는 절반

**(a) 사건 클러스터링.** Jaccard 대신 63비트 SimHash 해밍 거리를 쓴다(BIGINT 한 칸에 들어가고 비교가 popcount 한 번이다). 어절 shingle 은 조사와 띄어쓰기가 흔들리는 한국어에서 전재 기사끼리도 크게 벌어져, 문자 4-그램으로 바꿨다. 임계값은 실측해서 정했다.

| 경우 | 해밍 거리 |
|---|---|
| 같은 원문 + 매체별 저작권·기자 문구 | 5 |
| 같은 원문을 절반으로 자름 | 4 |
| 같은 날 같은 주제, 다른 취재 | 26 |

두 무리가 크게 벌어져 있어 임계값 6으로 잡았다. 여기에 "정규화한 제목이 같으면 같은 사건" 규칙을 더했다. 전재는 제목을 그대로 두고 본문만 잘라 싣는 경우가 흔하다.

클러스터링은 전역이 아니라 **쌍 단위**로 한다. 같은 두 사람을 함께 언급한 기사끼리만 비교하면 되므로 비교 대상이 몇 건에서 몇십 건이다. 24시간 창(`CLUSTER_WINDOW_DAYS = 1`)으로 후속 보도가 묶이는 것을 막는다.

죽어 있던 제목·본문 해시 dedup 도 살렸다. `seen_titles`/`seen_contents` 에 `add` 를 하지 않아 두 줄이 아무 일도 하지 않고 있었다.

**(b) 어그로 할인은 절반만.** `focus_weight(1/√n)` 만 적용했다. 나열 기사에서 뽑은 쌍은 그 기사의 주제가 아닐 확률이 높다. 화제성에 쓰던 함수를 그대로 재사용한다. 클릭베이트 분류기(AI Hub 낚시성 기사 데이터)는 2단계로 미뤘다.

**(c) 시간 감쇠.** 일 단위 EWMA 대신 반감기 지수 감쇠를 쓴다. 형태는 같으면서 배치 재계산에 강하다. 관측이 없는 날을 건너뛰어도 결과가 같기 때문이다.

```
w_time = 0.5 ^ (age_days / HALF_LIFE_DAYS),  HALF_LIFE_DAYS = 45
score_recent     = Σ w_time·w_a·y / Σ w_time·w_a     # 화면 굵기의 근거
score_cumulative = Σ w_a·y / Σ w_a                   # 감쇠 없는 이력
```

반감기를 45일로 잡은 이유. 저장소의 설계 메모(`.refs`)는 EWMA α 0.1~0.3 을 제안했는데 일 단위로 환산하면 반감기 2~7일이라 정치 관계에는 지나치게 빠르다. 국회 회기가 분기로 돌아가는 점을 보고 분기의 절반으로 잡았다. `RELATION_HALF_LIFE_DAYS` 로 바꿀 수 있다.

`n_observations`, `n_clusters`, `first_seen`, `last_seen`, `peak_score` 를 함께 저장해 "충돌 이력" 뷰의 재료를 남겼다.

### 알고리즘 조합 순서

```
관측 로그(6.0) → 5(a) 클러스터링 → 4 추출 → 5(b) 가중치 → 1 논조 보정 → 3 역가중·사전확률 → 2 교차 검증 → 5(c) 감쇠 → turing_edges
```

먼저 넣을 것 하나만 고르면 **6.0 + 알고리즘 5(a)** 다. 이것 없이는 나머지가 계산 자체가 안 된다.

현재 구현된 경로(2026-09-03):

```
기사 → NLI 판정 → edge_observations 적재 (press, camp, simhash, focus_weight)
     → 쌍 단위 SimHash 클러스터링 (전재를 사건 하나로)
     → 사건별 극성·점수 압축
     → 반감기 45일 가중 평균 → score_recent / score_cumulative
     → 진영별 사건 수 → camp_coverage, confidence
     → display_weight = |score_recent| · (0.5 + 0.5·camp_coverage)
     → POST /api/edge (같은 쌍의 다른 감정 엣지는 삭제)
```

빠져 있는 자리는 두 곳이다. NLI 판정 다음에 알고리즘 4(발화 주체 귀속)가 들어가고, 반감기 가중 전에 알고리즘 1(언론사 논조 기준선)과 3(역가중)이 들어간다.

---

## 7. 검증과 공개 (reddit 요청에 대한 답)

- **코더 간 신뢰도**: 관측 로그에서 200쌍을 층화 표집(극성·진영 커버리지별)해 2인이 코딩, Krippendorff's α 보고. 0.67 미만이면 알고리즘 4를 다시 손본다. 극성별 precision/recall과 공동발의 그래프와의 일치율도 함께 낸다.
- **적대적 매체 지각 대응**: Vallone(1985), Hansen & Kim(2011), 이종혁(2015)에 따르면 관여도 높은 이용자는 어느 쪽이든 편향을 지각한다. 따라서 "우리는 편향이 없다"가 아니라 **엣지마다 언론사 진영 분포·기사 수·신뢰도·기준선 테이블을 그대로 노출**하는 게 맞다. 이종혁(2015)은 중립 매체가 가장 공정하다고 평가받았다고 하므로, 교차 검증(알고리즘 2)을 통과한 엣지를 시각적으로 구분하면 신뢰도 인식에 직접 도움이 된다.
- **감사용 덤프**: reddit 글에서 약속한 "원본 엣지 + 기사 URL" 엔드포인트에 press, cluster_id, camp_coverage, confidence를 같이 내보낸다.

### 실제로 한 것 (2026-09-03)

- **화면**: 호불호 선의 굵기가 `display_weight` 를 따르고, 진영 교차가 안 된 관계는 점선이 된다. 선 위에 마우스를 올리면 사건 수, 기사 수, 진영별 사건 수, 방향, 근거 종류(직접 인용/간접 인용/기자 서술), 신뢰도, 관측 기간, 근거 문장이 그대로 나온다. 근거 기록이 없는 옛 관계는 "근거 기록 없음" 으로 표시된다.
- **방향**: 근거가 한쪽을 가리킬 때만 화살표를 그린다. 예전에는 모든 호불호 엣지에 화살표가 있었는데 방향이 전부 이름 정렬의 부산물이었다. 서로 주고받은 관계는 화살표 없이 남는다.
- **감사 공개**: `GET /api/relations/evidence` 가 기사 단위 근거를 그대로 내보낸다. 쌍을 지정하면 집계 결과, 사건 묶음(전재 기사가 어떻게 하나로 접혔는지), 공동발의 건수, 진영표까지 함께 준다. 인증이 없는 읽기 전용이다. `GET /api/relations/camps` 는 언론사 진영 배정을 공개한다. 진영 구분은 논쟁적인 판단이라 숨기면 안 된다.
- **분포 리포트**: `scripts/evidence_report.py` 가 사건 수 분포, 진영 커버리지, 신뢰도 히스토그램, 전재 비율, 극성 균형, 진영표에 없는 매체 목록을 낸다. 최소 사건 수를 2로 올릴지 같은 조율 판단에 쓴다.
- **코더 간 신뢰도**: 도구는 만들었고 사람이 채우면 된다. `scripts/coding_sample.py sample` 이 극성x진영으로 층화 표집해 CSV 를 만들고, `score` 가 단순 일치율과 Krippendorff's alpha, 극성별 정밀도·재현율, 진영별 정밀도를 낸다. 무작위 표집이면 갈등과 보수지 기사가 표본을 채워 우호 관계의 정밀도를 못 잰다. alpha 는 라벨이 한쪽으로 치우칠 때 단순 일치율이 부풀지 않게 보정한다.

**아직 갱신하지 않은 것**: `docs/reddit_post.md` 는 집계 이전 상태를 설명한다. 아래 문장들이 이제 맞지 않는다.

- "Source concentration. One news portal, three sections. Outlet-level slant is not controlled for" — 포털은 여전히 하나지만 언론사 진영은 통제한다.
- "39 directed sentiment edges" — 방향은 근거가 있을 때만 표시하며, 관계 수는 재집계로 바뀐다.
- "No inter-coder reliability" — 여전히 맞다. 도구만 생겼다.

게시 전에 손봐야 한다.

---

## 8. 출처

국제 논문
- Entman 1993: https://academic.oup.com/joc/article-abstract/43/4/51/4160153
- Galtung & Ruge 1965: https://doi.org/10.1177/002234336500200104
- Mullainathan & Shleifer 2005: https://doi.org/10.1257/0002828054825619
- Harcup & O'Neill 2001: https://doi.org/10.1080/14616700118449
- Gentzkow & Shapiro 2006: https://doi.org/10.1086/499414
- Groseclose & Milyo 2005: https://ideas.repec.org/p/umc/wpaper/0501.html
- Vallone, Ross & Lepper 1985: https://doi.org/10.1037/0022-3514.49.3.577
- Soroka 2006: https://www.journals.uchicago.edu/doi/abs/10.1111/j.1468-2508.2006.00413.x
- Gentzkow & Shapiro 2010: https://www.wallis.rochester.edu/assets/pdf/conference14/biasmeas081507.pdf
- D'Alessio & Allen 2000: https://academic.oup.com/joc/article/50/4/133/4110147
- Baron 2006: https://doi.org/10.1016/j.jpubeco.2004.10.006
- Gentzkow, Shapiro & Taddy 2019: https://doi.org/10.3982/ecta16566
- Chakraborty et al. 2016: https://arxiv.org/abs/1610.09786
- Budak, Goel & Rao 2016: https://academic.oup.com/poq/article-abstract/80/S1/250/2223443
- Trussler & Soroka 2014: https://doi.org/10.1177/1940161214524832
- Recasens et al. 2013: https://aclanthology.org/P13-1162/
- Hamborg, Donnay & Gipp 2019: https://doi.org/10.1007/s00799-018-0261-y
- Hansen & Kim 2011: https://www.tandfonline.com/doi/abs/10.1080/08824096.2011.565280
- Eberl, Boomgaarden & Wagner 2017: https://journals.sagepub.com/doi/abs/10.1177/0093650215614364
- Hamborg & Donnay 2021 (NewsMTSC): https://aclanthology.org/2021.eacl-main.142/ , https://github.com/fhamborg/NewsMTSC
- Kim, Lelkes & McCrain 2022: https://www.pnas.org/doi/10.1073/pnas.2202197119
- Ban, Fouirnaies, Hall & Snyder 2019: https://ideas.repec.org/a/cup/pscirm/v7y2019i04p661-678_00.html
- Padgett, Dunaway & Darr 2019: https://academic.oup.com/joc/article-abstract/69/6/696/5681995
- Wagner & Gruszczynski 2018: https://journalistsresource.org/politics-and-government/congress-media-coverage-political-extreme-research/

국내 논문·데이터
- 이준웅 2002: https://www.kci.go.kr/kciportal/ci/sereArticleSearch/ciSereArtiView.kci?sereArticleSearchBean.artiId=ART000851049
- 이종혁 2015: https://www.dbpia.co.kr/journal/articleDetail?nodeId=NODE06205824
- 최창식·임영호 2021: https://www.kci.go.kr/kciportal/landing/article.kci?arti_id=ART002688121
- 이재완·김용환 2023: https://www.kci.go.kr/kciportal/landing/article.kci?arti_id=ART003043322
- 김나현·이상엽 2022: https://www.kci.go.kr/kciportal/ci/sereArticleSearch/ciSereArtiView.kci?sereArticleSearchBean.artiId=ART002832164
- 유재광·오경수 2012: https://www.kci.go.kr/kciportal/ci/sereArticleSearch/ciSereArtiView.kci?sereArticleSearchBean.artiId=ART001703725
- 박영흠 2024: https://www.kci.go.kr/kciportal/ci/sereArticleSearch/ciSereArtiView.kci?sereArticleSearchBean.artiId=ART003084400
- 양혜승 2017: https://www.kci.go.kr/kciportal/ci/sereArticleSearch/ciSereArtiView.kci?sereArticleSearchBean.artiId=ART002288481
- 정성호·이준호 2011: https://www.kci.go.kr/kciportal/ci/sereArticleSearch/ciSereArtiView.kci?sereArticleSearchBean.artiId=ART001544235
- 최선규·유수정·양성은 2012: https://www.dbpia.co.kr/journal/articleDetail?nodeId=NODE10856166
- 이신행 2024: https://www.dbpia.co.kr/journal/articleDetail?nodeId=NODE11825347
- KoPolitic (Kim, Lee & Na 2023): https://arxiv.org/abs/2311.01712 , https://github.com/kdavid2355/kopolitic-benchmark-dataset
- AI Hub 낚시성 기사 탐지 데이터: https://aihub.or.kr/aihubdata/data/view.do?dataSetSn=71338
- 연합뉴스 포털 송고 비중: https://ko.wikipedia.org/wiki/연합뉴스

인용 수 조회
- OpenAlex API (https://api.openalex.org), 2026-09-02
- KCI 논문 상세 페이지 "피인용 횟수", 2026-09-02
