FROM python:3.12-slim

WORKDIR /app

# 시스템 패키지 업데이트 및 필요한 패키지 설치
RUN apt-get update && apt-get install -y \
    gcc \
    g++ \
    && rm -rf /var/lib/apt/lists/*

# Python 패키지 설치
COPY requirements.txt .
RUN pip install --no-cache-dir -r requirements.txt

# 애플리케이션 코드 복사
COPY . .

# 환경 변수 설정
ENV PYTHONUNBUFFERED=1
ENV TURINGDB_HOST=http://turingdb:6666
ENV TURINGDB_GRAPH=korea_politician

# 포트 노출
EXPOSE 5000

# FastAPI 서버 실행
CMD ["uvicorn", "api.turingdb_server:app", "--host", "0.0.0.0", "--port", "5000"]
