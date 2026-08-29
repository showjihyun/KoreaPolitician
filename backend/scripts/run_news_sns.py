import subprocess
import os
import sys
import logging
import time

# 로깅 설정
logging.basicConfig(
    level=logging.INFO,
    format='[%(asctime)s] %(levelname)s - %(message)s'
)
logger = logging.getLogger(__name__)

def run_script(script_path, cwd):
    """지정된 스크립트를 subprocess로 실행"""
    logger.info(f"실행 시작: {script_path}")
    env = os.environ.copy()
    env['PYTHONPATH'] = os.path.abspath(os.path.join(cwd, 'backend'))
    env['PYTHONIOENCODING'] = 'utf-8' # 출력 인코딩 강제
    
    process = subprocess.Popen(
        [sys.executable, script_path],
        cwd=cwd,
        env=env,
        stdout=subprocess.PIPE,
        stderr=subprocess.STDOUT,
        text=True,
        encoding='utf-8',
        errors='replace'
    )
    
    # 실시간 로그 출력
    for line in iter(process.stdout.readline, ''):
        print(line.strip())
        
    process.stdout.close()
    return_code = process.wait()
    
    if return_code == 0:
        logger.info(f"성공적으로 완료됨: {script_path}")
    else:
        logger.error(f"실행 실패 (Return Code {return_code}): {script_path}")
        # 전체 중단 대신 에러 로깅 후 다음 주기로 넘어가게 할 수도 있음
        # 여기선 run_script 레벨에선 에러를 던지거나 함
        return False
    return True

def main():
    root_dir = os.path.abspath(os.curdir)
    INTERVAL_MINUTES = 60
    
    # DB 포트 및 설정 로드
    from dotenv import load_dotenv
    load_dotenv(os.path.join(root_dir, 'backend/.env'))
    
    # graph_storage를 사용하기 위해 환경 설정
    sys.path.append(os.path.join(root_dir, 'backend'))
    from core.graph_storage import graph_storage, run_sync, close_sync
    from core.db_config import db_config_from_env
    import atexit
    # 프로세스 종료 시 커넥션 풀과 전용 이벤트 루프 정리
    atexit.register(close_sync)
    
    # 빈 문자열 환경변수(미등록 시크릿)를 미설정으로 처리한다.
    db_config = db_config_from_env()
    run_sync(graph_storage.init_db(db_config))
    
    while True:
        logger.info(f"=== [전체 파이프라인 시작] {time.strftime('%Y-%m-%d %H:%M:%S')} ===")
        
        # 1. 뉴스 크롤링 파이프라인 (News Crawler)
        news_script = "backend/crawlers/news_crawler_pipeline.py"
        logger.info("=== 1단계: 실시간 뉴스 수집 시작 ===")
        news_success = run_script(news_script, root_dir)

        # 2. SNS 화제성 수집 (SNS Crawler)
        sns_script = "backend/crawlers/sns_crawler_pipeline.py"
        logger.info("=== 2단계: SNS 화제성 수집 시작 ===")
        sns_success = run_script(sns_script, root_dir)
            
        # 수집이 성공적으로 진행되었다면 날짜 업데이트
        if news_success or sns_success:
            today_str = time.strftime('%Y-%m-%d')
            logger.info(f"=== 통계 날짜 업데이트: {today_str} ===")
            run_sync(graph_storage.set_setting("last_data_update", today_str))

        logger.info(f"=== [전체 파이프라인 종료] {INTERVAL_MINUTES}분 대기 후 재시작 ===")
        time.sleep(INTERVAL_MINUTES * 60)

if __name__ == "__main__":
    main()
