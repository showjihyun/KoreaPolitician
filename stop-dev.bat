@echo off
echo ========================================
echo Korea Politician 개발 환경 종료
echo ========================================
echo.

echo Docker 컨테이너 종료 중...
docker-compose down
echo.
echo 모든 서비스가 종료되었습니다.
pause
