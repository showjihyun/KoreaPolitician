---
description: 국회의원 명단 최신화 및 실시간 뉴스 데이터 수집 통합 워크플로우
---

### 국회의원 데이터 통합 수집 워크플로우

이 워크플로우는 국회의원 명단을 먼저 최신화한 뒤, 해당 명단을 바탕으로 뉴스를 크롤링합니다.

// turbo
1. 통합 실행 스크립트로 전체 프로세스 실행
   ```powershell
   $env:PYTHONPATH='.'; python run_full_pipeline.py
   ```

2. (또는) 개별 단계별 실행
   * **1단계: 국회의원 명단 최신화**
     ```powershell
     $env:PYTHONPATH='backend'; python backend/crawlers/politician_crawler.py
     ```
   * **2단계: 뉴스 수집 및 분석**
     ```powershell
     $env:PYTHONPATH='backend'; python backend/crawlers/news_crawler_pipeline.py
     ```

> [!TIP]
> `run_full_pipeline.py`를 사용하면 명단 수집이 완료된 후 자동으로 뉴스 수집이 시작됩니다.
