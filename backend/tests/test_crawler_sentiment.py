import logging
import time
from crawlers.affective_analysis import AffectiveAnalyzer
from core.dcp_algorithm import DCPCalculator
# from news_crawler_pipeline import RobustCrawler # Removed as class is not exposed

# Setup logging
logging.basicConfig(level=logging.INFO)
logger = logging.getLogger(__name__)

def test_sentiment_analyzer():
    logger.info("Testing AffectiveAnalyzer...")
    try:
        analyzer = AffectiveAnalyzer() # Will use default robust model
        
        test_cases = [
            ("이재명 대표는 한동훈 위원장의 발언을 강력하게 비판하며 대립각을 세웠다.", "이재명", "한동훈", "NEGATIVE_SENTIMENT"),
            ("나경원 의원과 안철수 의원은 이번 정책에서 뜻을 같이하며 협력하기로 했다.", "나경원", "안철수", "POSITIVE_SENTIMENT"),
            ("오늘 국회 본회의가 열렸다.", "이재명", "한동훈", None) # Neutral/Unrelated
        ]
        
        for text, p1, p2, expected in test_cases:
            rtype, score, evidence = analyzer.analyze_relationship(text, p1, p2)
            logger.info(f"Test: {p1}-{p2} | Expected: {expected} | Got: {rtype} ({score:.2f})")
            if expected:
                if rtype != expected:
                    logger.warning(f"Mismatch! Expected {expected}, got {rtype}")
        
        logger.info("AffectiveAnalyzer Test Completed!")
    except Exception as e:
        logger.error(f"Analyzer Test Failed: {e}")

def test_dcp():
    logger.info("Testing DCPCalculator...")
    dcp = DCPCalculator()
    # Mock API would be needed for real test, but we test module load and valid call
    try:
        score = dcp.calculate_impact_score("TestSubject", "TestTarget", "POSITIVE_SENTIMENT", 0.8)
        logger.info(f"DCP Calculation Result: {score}")
    except Exception as e:
        logger.error(f"DCP Test Failed: {e}")

if __name__ == "__main__":
    try:
        test_sentiment_analyzer()
        test_dcp()
    except Exception as e:
        logger.error(f"Test Failed: {e}")
