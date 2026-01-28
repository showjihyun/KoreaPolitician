#!/bin/bash

echo "========================================"
echo "Korea Politician 개발 환경 시작"
echo "========================================"
echo ""

echo "[1/3] Docker 컨테이너 시작 중..."
docker-compose up -d
if [ $? -ne 0 ]; then
    echo "Docker 시작 실패!"
    exit 1
fi
echo "Docker 컨테이너 시작 완료!"
echo ""

echo "[2/3] Backend 상태 확인 중..."
sleep 5
echo "Backend: http://localhost:5000"
echo "TuringDB: http://localhost:6666"
echo ""

echo "[3/3] Frontend 개발 서버 시작 중..."
echo "Frontend: http://localhost:3100"
echo ""
cd frontend
npm run dev
