"""
정치인 관계 분석기
- 뉴스 기사 분석
- 관계 유형 추출
- 관계 강도 계산
"""

import asyncio
import json
import re
from typing import List, Dict, Tuple
from playwright.async_api import async_playwright, Page
from collections import defaultdict
import logging

logging.basicConfig(level=logging.INFO)
logger = logging.getLogger(__name__)


class RelationshipAnalyzer:
    def __init__(self):
        # 관계 키워드 정의
        self.relationship_keywords = {
            'ALLY': ['협력', '동맹', '연대', '지지', '함께', '공동', '협약', '파트너'],
            'RIVAL': ['대립', '경쟁', '반대', '비판', '공격', '갈등', '충돌', '논쟁'],
            'MENTOR_OF': ['멘토', '스승', '지도', '후원', '육성'],
            'COLLEAGUE': ['동료', '함께', '같이', '공동'],
            'MET_WITH': ['만남', '회담', '면담', '대화', '회의', '미팅'],
        }
        
        # 정치인 이름 목록 (한국)
        self.politician_names = set()
    
    def load_politicians(self, members_data: List[Dict]):
        """정치인 이름 목록 로드"""
        self.politician_names = {m['name'] for m in members_data if m.get('name')}
        logger.info(f"Loaded {len(self.politician_names)} politician names")
    
    async def search_news(self, query: str, page: Page, max_results: int = 20) -> List[Dict]:
        """네이버 뉴스 검색"""
        news_items = []
        
        try:
            search_url = f"https://search.naver.com/search.naver?where=news&query={query}"
            await page.goto(search_url, wait_until="networkidle", timeout=30000)
            
            # 뉴스 아이템 추출
            items = await page.locator(".news_area").all()
            
            for item in items[:max_results]:
                try:
                    title_elem = await item.locator(".news_tit").first
                    title = await title_elem.text_content()
                    link = await title_elem.get_attribute("href")
                    
                    desc_elem = await item.locator(".news_dsc").first
                    description = await desc_elem.text_content() if desc_elem else ""
                    
                    news_items.append({
                        'title': title.strip() if title else "",
                        'description': description.strip() if description else "",
                        'link': link,
                    })
                except Exception as e:
                    logger.debug(f"Error extracting news item: {e}")
                    continue
            
            return news_items
            
        except Exception as e:
            logger.error(f"Error searching news for '{query}': {e}")
            return []
    
    def extract_relationships_from_text(self, text: str, person1: str) -> List[Tuple[str, str, str]]:
        """텍스트에서 관계 추출"""
        relationships = []
        
        # 텍스트에서 다른 정치인 이름 찾기
        mentioned_politicians = []
        for name in self.politician_names:
            if name != person1 and name in text:
                mentioned_politicians.append(name)
        
        # 각 정치인에 대해 관계 유형 판단
        for person2 in mentioned_politicians:
            # 두 이름 사이의 텍스트 추출
            pattern = f"{person1}.*?{person2}|{person2}.*?{person1}"
            matches = re.findall(pattern, text)
            
            if matches:
                context = " ".join(matches)
                
                # 관계 유형 판단
                relationship_scores = defaultdict(int)
                for rel_type, keywords in self.relationship_keywords.items():
                    for keyword in keywords:
                        if keyword in context:
                            relationship_scores[rel_type] += 1
                
                # 가장 높은 점수의 관계 선택
                if relationship_scores:
                    best_rel = max(relationship_scores.items(), key=lambda x: x[1])
                    relationships.append((person1, person2, best_rel[0]))
        
        return relationships
    
    async def analyze_politician_relationships(
        self, 
        member_name: str, 
        page: Page,
        max_news: int = 50
    ) -> List[Dict]:
        """특정 정치인의 관계 분석"""
        logger.info(f"Analyzing relationships for {member_name}")
        
        # 뉴스 검색
        news_items = await self.search_news(member_name, page, max_news)
        
        # 관계 추출
        all_relationships = []
        relationship_counts = defaultdict(lambda: defaultdict(int))
        
        for news in news_items:
            text = news['title'] + " " + news['description']
            relationships = self.extract_relationships_from_text(text, member_name)
            
            for person1, person2, rel_type in relationships:
                key = (person1, person2, rel_type)
                relationship_counts[key]['count'] += 1
                if 'sources' not in relationship_counts[key]:
                    relationship_counts[key]['sources'] = []
                relationship_counts[key]['sources'].append(news['link'])
        
        # 결과 정리
        for (person1, person2, rel_type), data in relationship_counts.items():
            all_relationships.append({
                'from': person1,
                'to': person2,
                'type': rel_type,
                'strength': min(data['count'] * 10, 100),  # 0-100 스케일
                'evidence_count': data['count'],
                'sources': data['sources'][:5],  # 최대 5개 소스
            })
        
        return all_relationships
    
    async def analyze_all_relationships(
        self, 
        members_data: List[Dict],
        sample_size: int = None
    ) -> List[Dict]:
        """모든 정치인의 관계 분석"""
        self.load_politicians(members_data)
        
        all_relationships = []
        
        # 샘플링 (테스트용)
        if sample_size:
            members_data = members_data[:sample_size]
        
        async with async_playwright() as p:
            browser = await p.chromium.launch(headless=True)
            context = await browser.new_context()
            page = await context.new_page()
            
            for i, member in enumerate(members_data):
                name = member.get('name')
                if not name:
                    continue
                
                logger.info(f"Processing {i+1}/{len(members_data)}: {name}")
                
                relationships = await self.analyze_politician_relationships(name, page)
                all_relationships.extend(relationships)
                
                # 요청 간 딜레이
                await asyncio.sleep(2)
            
            await browser.close()
        
        return all_relationships


async def main():
    """메인 실행 함수"""
    # 기존 데이터 로드
    with open("../../assembly_members_complete.json", "r", encoding="utf-8") as f:
        members_data = json.load(f)
    
    # 관계 분석기 실행
    analyzer = RelationshipAnalyzer()
    
    # 샘플로 10명만 분석 (전체는 시간이 오래 걸림)
    logger.info("Starting relationship analysis (sample: 10 members)...")
    relationships = await analyzer.analyze_all_relationships(members_data, sample_size=10)
    
    # 결과 저장
    output_file = "../../data/relationships.json"
    with open(output_file, "w", encoding="utf-8") as f:
        json.dump(relationships, f, ensure_ascii=False, indent=2)
    
    logger.info(f"Analysis completed. Found {len(relationships)} relationships")
    logger.info(f"Results saved to {output_file}")


if __name__ == "__main__":
    asyncio.run(main())
