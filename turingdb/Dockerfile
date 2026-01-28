FROM python:3.12

WORKDIR /app

# 시스템 패키지 업데이트 및 필수 도구 설치
RUN apt-get update && apt-get install -y \
    gcc \
    g++ \
    git \
    cmake \
    build-essential \
    curl \
    wget \
    && rm -rf /var/lib/apt/lists/*

# Python 패키지 설치
RUN pip install --no-cache-dir turingdb

# TuringDB 바이너리 다운로드 (GitHub Releases에서)
RUN wget -O /usr/local/bin/turingdb https://github.com/turing-db/turingdb/releases/latest/download/turingdb-linux-x86_64 || \
    echo "Binary download failed, will use Python SDK"

RUN chmod +x /usr/local/bin/turingdb || true

# 데이터 디렉토리 생성
RUN mkdir -p /data

# 환경 변수 설정
ENV TURINGDB_DATA_DIR=/data
ENV PYTHONUNBUFFERED=1
ENV PATH="/usr/local/bin:${PATH}"

# Python 서버 스크립트 복사
COPY turingdb_server.py /app/turingdb_server.py
RUN chmod +x /app/turingdb_server.py

# 포트 노출
EXPOSE 6666

# TuringDB 서버 실행
CMD ["python3", "/app/turingdb_server.py"]


