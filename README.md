# 대한민국 정치인 인물 관계도 뉴스 크롤러/감정분석 파이프라인

## 개요

이 프로젝트는 대한민국 정치인 인물 관계도 구축을 위한 뉴스 크롤링, 감정분석, DB 저장 자동화 파이프라인입니다. 네이버 뉴스에서 정치 섹션 헤드라인과 언론사별 많이 본 뉴스를 크롤링하고, 기사 본문에서 정치인 이름을 추출, 감정분석(영어 모델 활용) 후 PostgreSQL DB에 저장합니다.

- **크롤링**: Playwright 기반 네이버 뉴스/랭킹 크롤러
- **감정분석**: HuggingFace 다국어 BERT(5단계) + Google Translate
- **DB 저장**: PostgreSQL (news_sentiment 테이블)
- **로깅**: 파일 및 콘솔에 상세 기록

## 주요 기능

- 네이버 정치 뉴스 헤드라인/랭킹(많이 본 뉴스) 자동 크롤링
- newspaper3k로 기사 본문 전문 수집
- 정치인 이름 자동 추출(샘플 리스트)
- 기사 내 2명 이상 정치인 등장 시 감정분석(한글→영어 번역 후 5단계)
- 결과를 PostgreSQL DB에 자동 저장
- 전체 파이프라인 로깅 및 예외 처리

## 실행 환경

- Python 3.8+
- PostgreSQL 12+
- 주요 패키지: playwright, newspaper3k, googletrans, transformers, torch, psycopg2

### 설치

```bash
# 가상환경 권장
python -m venv .venv
source .venv/bin/activate  # (Windows: .venv\Scripts\activate)
pip install -r requirements.txt
# Playwright 브라우저 설치
python -m playwright install
```

### 환경 변수 (선택)
- PG_HOST, PG_PORT, PG_USER, PG_PASSWORD, PG_DB (기본값: localhost, 5432, postgres, password, postgres)

## 실행 방법

```bash
python backend/news_crawler_pipeline.py
```
- 실행 결과는 콘솔과 `news_crawler_pipeline.log`에 기록됩니다.
- DB에 `public.news_sentiment` 테이블이 자동 생성/저장됩니다.

## DB 테이블 구조

| 컬럼명            | 타입    | 설명           |
|-------------------|---------|----------------|
| id                | SERIAL  | PK             |
| title             | TEXT    | 기사 제목      |
| url               | TEXT    | 기사 URL       |
| press             | TEXT    | 언론사         |
| date              | TEXT    | 날짜           |
| politicians       | TEXT    | 등장 정치인(,구분) |
| sentiment_label   | TEXT    | 감정분석 라벨  |
| sentiment_score   | FLOAT   | 감정 점수      |
| content           | TEXT    | 기사 본문      |

## 확장/활용 예시
- Neo4j 등 그래프DB로 이관하여 인물 관계 시각화
- 프론트엔드(React+D3.js)와 연동하여 네트워크 그래프 제공
- 크롤링/분석 자동화(스케줄러, 배치)
- 감정분석 모델 파인튜닝/고도화

## 참고/문의
- 네이버 뉴스 구조 변경 시 크롤러 셀렉터 수정 필요
- 감정분석 모델은 영어권 5단계(BERT-multilingual) 사용, 한글 기사 자동 번역
- 문의: github issue 또는 프로젝트 관리자 