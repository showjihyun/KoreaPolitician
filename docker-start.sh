#!/bin/bash

echo "=== KoreaPolitician Docker 시작 ==="

# Docker Compose로 서비스 시작
echo "1. Docker 컨테이너 빌드 및 시작 중..."
docker-compose up -d --build

# TuringDB가 준비될 때까지 대기
echo "2. TuringDB 준비 대기 중..."
sleep 15

# 컨테이너 상태 확인
echo "3. 컨테이너 상태 확인..."
docker-compose ps

echo ""
echo "=== 서비스 시작 완료 ==="
echo "TuringDB: http://localhost:6666"
echo "Backend API: http://localhost:5000"
echo "API 문서: http://localhost:5000/docs"
echo ""
echo "데이터 임포트를 위해 다음 명령어를 실행하세요:"
echo "docker-compose exec backend python turingdb_importer.py --import-all --json assembly_members_complete.json"
echo ""
echo "로그 확인:"
echo "docker-compose logs -f backend"
echo "docker-compose logs -f turingdb"
