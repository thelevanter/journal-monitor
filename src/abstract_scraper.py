"""
abstract_scraper.py - 웹 스크래핑으로 초록 가져오기
케이의 학술저널 RSS 모니터링 시스템

출판사 웹페이지에서 직접 초록을 스크래핑
OpenAlex/Semantic Scholar보다 먼저 시도
"""

import requests
from bs4 import BeautifulSoup
import time
import logging
import re
from typing import Optional, Dict
from urllib.parse import urlparse

logging.basicConfig(level=logging.INFO)
logger = logging.getLogger(__name__)


class AbstractScraper:
    """출판사별 초록 스크래퍼"""
    
    def __init__(self, request_delay: float = 1.0):
        self.request_delay = request_delay
        self.session = requests.Session()
        self.session.headers.update({
            'User-Agent': 'Mozilla/5.0 (Macintosh; Intel Mac OS X 10_15_7) AppleWebKit/537.36 (KHTML, like Gecko) Chrome/120.0.0.0 Safari/537.36',
            'Accept': 'text/html,application/xhtml+xml,application/xml;q=0.9,*/*;q=0.8',
            'Accept-Language': 'en-US,en;q=0.9,ko;q=0.8',
        })
    
    def get_abstract(self, url: str) -> Optional[str]:
        """
        URL에서 초록 스크래핑
        
        Args:
            url: 논문 URL
            
        Returns:
            초록 텍스트 또는 None
        """
        if not url:
            return None
        
        try:
            domain = urlparse(url).netloc.lower()
            
            # 출판사별 스크래퍼 선택
            if 'tandfonline.com' in domain:
                return self._scrape_taylor_francis(url)
            elif 'sagepub.com' in domain:
                return self._scrape_sage(url)
            elif 'onlinelibrary.wiley.com' in domain:
                return self._scrape_wiley(url)
            elif 'sciencedirect.com' in domain:
                return self._scrape_elsevier(url)
            elif 'springer.com' in domain or 'link.springer.com' in domain:
                return self._scrape_springer(url)
            elif 'journals.sagepub.com' in domain:
                return self._scrape_sage(url)
            else:
                # 일반 스크래핑 시도
                return self._scrape_generic(url)
                
        except Exception as e:
            logger.debug(f"Scraping failed for {url}: {e}")
            return None
    
    def _fetch_page(self, url: str) -> Optional[BeautifulSoup]:
        """페이지 가져오기"""
        try:
            time.sleep(self.request_delay)
            response = self.session.get(url, timeout=30, allow_redirects=True)
            response.raise_for_status()
            return BeautifulSoup(response.text, 'html.parser')
        except Exception as e:
            logger.debug(f"Failed to fetch {url}: {e}")
            return None
    
    def _clean_abstract(self, text: str) -> str:
        """초록 텍스트 정리"""
        if not text:
            return ""
        
        # 공백 정리
        text = re.sub(r'\s+', ' ', text).strip()
        
        # "Abstract" 제거
        text = re.sub(r'^Abstract[\s:]*', '', text, flags=re.IGNORECASE)
        
        # HTML 엔티티 정리
        text = text.replace('\xa0', ' ')
        
        return text.strip()
    
    def _scrape_taylor_francis(self, url: str) -> Optional[str]:
        """Taylor & Francis (tandfonline.com) 스크래핑"""
        soup = self._fetch_page(url)
        if not soup:
            return None
        
        # 초록 찾기 - 여러 선택자 시도
        selectors = [
            'div.abstractSection.abstractInFull',
            'div.hlFld-Abstract',
            'div[class*="abstract"]',
            'section.abstract',
            'div.abstractInFull',
            'p.abstractInFull',
        ]
        
        for selector in selectors:
            abstract_div = soup.select_one(selector)
            if abstract_div:
                # 불필요한 요소 제거
                for tag in abstract_div.find_all(['h2', 'h3', 'button', 'a']):
                    tag.decompose()
                
                text = abstract_div.get_text(separator=' ')
                text = self._clean_abstract(text)
                
                if len(text) >= 100:
                    logger.info(f"  → T&F 스크래핑 성공 ({len(text)}자)")
                    return text
        
        return None
    
    def _scrape_sage(self, url: str) -> Optional[str]:
        """SAGE Publications 스크래핑"""
        soup = self._fetch_page(url)
        if not soup:
            return None
        
        selectors = [
            'div.abstractSection',
            'section.abstract',
            'div[class*="abstract"]',
            'div.hlFld-Abstract',
        ]
        
        for selector in selectors:
            abstract_div = soup.select_one(selector)
            if abstract_div:
                for tag in abstract_div.find_all(['h2', 'h3', 'button']):
                    tag.decompose()
                
                text = abstract_div.get_text(separator=' ')
                text = self._clean_abstract(text)
                
                if len(text) >= 100:
                    logger.info(f"  → SAGE 스크래핑 성공 ({len(text)}자)")
                    return text
        
        return None
    
    def _scrape_wiley(self, url: str) -> Optional[str]:
        """Wiley Online Library 스크래핑"""
        soup = self._fetch_page(url)
        if not soup:
            return None
        
        selectors = [
            'section.article-section__abstract',
            'div.abstract-group',
            'section[class*="abstract"]',
            'div[class*="abstract"]',
        ]
        
        for selector in selectors:
            abstract_div = soup.select_one(selector)
            if abstract_div:
                for tag in abstract_div.find_all(['h2', 'h3', 'button']):
                    tag.decompose()
                
                text = abstract_div.get_text(separator=' ')
                text = self._clean_abstract(text)
                
                if len(text) >= 100:
                    logger.info(f"  → Wiley 스크래핑 성공 ({len(text)}자)")
                    return text
        
        return None
    
    def _scrape_elsevier(self, url: str) -> Optional[str]:
        """Elsevier ScienceDirect 스크래핑"""
        soup = self._fetch_page(url)
        if not soup:
            return None
        
        selectors = [
            'div.abstract.author',
            'div[class*="Abstracts"]',
            'section#abstracts',
            'div.abstract',
        ]
        
        for selector in selectors:
            abstract_div = soup.select_one(selector)
            if abstract_div:
                for tag in abstract_div.find_all(['h2', 'h3', 'button']):
                    tag.decompose()
                
                text = abstract_div.get_text(separator=' ')
                text = self._clean_abstract(text)
                
                if len(text) >= 100:
                    logger.info(f"  → Elsevier 스크래핑 성공 ({len(text)}자)")
                    return text
        
        return None
    
    def _scrape_springer(self, url: str) -> Optional[str]:
        """Springer 스크래핑"""
        soup = self._fetch_page(url)
        if not soup:
            return None
        
        selectors = [
            'section[data-title="Abstract"]',
            'div#Abs1-content',
            'div.c-article-section__content',
            'section.Abstract',
        ]
        
        for selector in selectors:
            abstract_div = soup.select_one(selector)
            if abstract_div:
                text = abstract_div.get_text(separator=' ')
                text = self._clean_abstract(text)
                
                if len(text) >= 100:
                    logger.info(f"  → Springer 스크래핑 성공 ({len(text)}자)")
                    return text
        
        return None
    
    def _scrape_generic(self, url: str) -> Optional[str]:
        """일반 스크래핑 (메타 태그 등)"""
        soup = self._fetch_page(url)
        if not soup:
            return None
        
        # 메타 태그에서 초록 찾기
        meta_selectors = [
            ('meta[name="description"]', 'content'),
            ('meta[name="DC.description"]', 'content'),
            ('meta[property="og:description"]', 'content'),
            ('meta[name="citation_abstract"]', 'content'),
        ]
        
        for selector, attr in meta_selectors:
            meta = soup.select_one(selector)
            if meta and meta.get(attr):
                text = self._clean_abstract(meta.get(attr))
                if len(text) >= 100:
                    logger.info(f"  → 메타태그 스크래핑 성공 ({len(text)}자)")
                    return text
        
        # 일반 abstract 클래스 시도
        for selector in ['div.abstract', 'section.abstract', 'p.abstract']:
            abstract_div = soup.select_one(selector)
            if abstract_div:
                text = abstract_div.get_text(separator=' ')
                text = self._clean_abstract(text)
                
                if len(text) >= 100:
                    logger.info(f"  → 일반 스크래핑 성공 ({len(text)}자)")
                    return text
        
        return None


def fetch_abstracts_by_scraping(db, limit: int = 50) -> int:
    """
    웹 스크래핑으로 초록 보충
    
    Args:
        db: Database 인스턴스
        limit: 처리할 최대 논문 수
        
    Returns:
        업데이트된 논문 수
    """
    import sqlite3
    
    # 초록 없고 URL 있는 논문 조회
    with sqlite3.connect(db.db_path) as conn:
        conn.row_factory = sqlite3.Row
        cursor = conn.cursor()
        
        cursor.execute("""
            SELECT id, title, url
            FROM articles
            WHERE (abstract IS NULL OR abstract = '' OR LENGTH(abstract) < 50)
              AND url IS NOT NULL AND url != ''
            LIMIT ?
        """, (limit,))
        
        articles = [dict(row) for row in cursor.fetchall()]
    
    if not articles:
        logger.info("스크래핑할 논문이 없습니다.")
        return 0
    
    logger.info(f"웹 스크래핑 초록 보충 대상: {len(articles)}편")
    
    scraper = AbstractScraper()
    updated = 0
    
    for i, article in enumerate(articles, 1):
        url = article.get('url')
        if not url:
            continue
        
        logger.info(f"[{i}/{len(articles)}] {article.get('title', '')[:50]}...")
        
        abstract = scraper.get_abstract(url)
        
        if abstract and len(abstract) >= 50:
            db.update_article_abstract(article['id'], abstract)
            updated += 1
        else:
            logger.info(f"  → 스크래핑 실패")
    
    logger.info(f"\n웹 스크래핑으로 {updated}편 초록 보충 완료")
    return updated


if __name__ == "__main__":
    # 테스트
    scraper = AbstractScraper()
    
    test_urls = [
        "https://www.tandfonline.com/doi/full/10.1080/13604813.2025.2576357",
        "https://journals.sagepub.com/doi/abs/10.1177/00420980251336242",
    ]
    
    for url in test_urls:
        print(f"\nTesting: {url[:60]}...")
        abstract = scraper.get_abstract(url)
        if abstract:
            print(f"성공! ({len(abstract)}자)")
            print(abstract[:200] + "...")
        else:
            print("실패")
