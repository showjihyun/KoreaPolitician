import subprocess
import os
import sys
import logging

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
        sys.exit(return_code)

def main():
    root_dir = os.path.abspath(os.curdir)
    
    # 1. 국회의원 명단 수집 (Politician Crawler)
    politician_script = "backend/crawlers/politician_crawler.py"
    logger.info("=== 1단계: 국회의원 명단 최신화 시작 ===")
    run_script(politician_script, root_dir)
    
    # 2. 뉴스 크롤링 파이프라인 (News Crawler)
    news_script = "backend/crawlers/news_crawler_pipeline.py"
    logger.info("=== 2단계: 실시간 뉴스 수집 시작 ===")
    run_script(news_script, root_dir)

    # 3. SNS 화제성 수집 (SNS Crawler)
    sns_script = "backend/crawlers/sns_crawler_pipeline.py"
    logger.info("=== 3단계: SNS 화제성 수집 시작 ===")
    run_script(sns_script, root_dir)

if __name__ == "__main__":
    main()
