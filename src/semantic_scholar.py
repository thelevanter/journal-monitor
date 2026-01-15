"""
semantic_scholar.py - Semantic Scholar API 연동 모듈
케이의 학술저널 RSS 모니터링 시스템

Semantic Scholar: 무료 학술 메타데이터 API
- DOI 기반 논문 정보 조회
- OpenAlex에서 못 찾은 초록 보충에 활용
"""

import requests
import time
import logging
from typing import Dict, List, Optional
from dataclasses import dataclass

logging.basicConfig(level=logging.INFO)
logger = logging.getLogger(__name__)


@dataclass
class SemanticScholarPaper:
    """Semantic Scholar 논문 정보 데이터 클래스"""
    doi: str
    title: str
    abstract: str
    authors: List[str]
    year: int
    citation_count: int
    open_access_pdf: Optional[str] = None


class SemanticScholarClient:
    """Semantic Scholar API 클라이언트"""
    
    BASE_URL = "https://api.semanticscholar.org/graph/v1"
    
    def __init__(self, api_key: str = None, request_delay: float = 1.0):
        """
        클라이언트 초기화
        
        Args:
            api_key: API 키 (없어도 됨, 있으면 rate limit 완화)
            request_delay: 요청 간 대기 시간 (초) - 무료는 1초 권장
        """
        self.api_key = api_key
        self.request_delay = request_delay
        self.session = requests.Session()
        
        self.session.headers.update({
            'User-Agent': 'JournalMonitor/1.0'
        })
        
        if api_key:
            self.session.headers.update({
                'x-api-key': api_key
            })
    
    def get_paper_by_doi(self, doi: str) -> Optional[SemanticScholarPaper]:
        """
        DOI로 논문 정보 조회
        
        Args:
            doi: 논문 DOI (10.xxxx/xxxx 형식 또는 전체 URL)
            
        Returns:
            SemanticScholarPaper 또는 None
        """
        # DOI 정규화
        doi = doi.strip()
        if doi.startswith('http'):
            doi = doi.split('doi.org/')[-1]
        
        # API 호출
        url = f"{self.BASE_URL}/paper/DOI:{doi}"
        params = {
            'fields': 'title,abstract,authors,year,citationCount,openAccessPdf'
        }
        
        try:
            time.sleep(self.request_delay)  # Rate limiting
            
            response = self.session.get(url, params=params, timeout=30)
            
            if response.status_code == 404:
                logger.debug(f"DOI not found in Semantic Scholar: {doi}")
                return None
            
            if response.status_code == 429:
                logger.warning("Semantic Scholar rate limit hit, waiting...")
                time.sleep(5)
                return None
            
            response.raise_for_status()
            data = response.json()
            
            # 저자 목록 추출
            authors = []
            for author in data.get('authors', []):
                name = author.get('name', '')
                if name:
                    authors.append(name)
            
            # Open Access PDF URL 추출
            oa_pdf = None
            if data.get('openAccessPdf'):
                oa_pdf = data['openAccessPdf'].get('url')
            
            return SemanticScholarPaper(
                doi=doi,
                title=data.get('title', ''),
                abstract=data.get('abstract', '') or '',
                authors=authors,
                year=data.get('year', 0) or 0,
                citation_count=data.get('citationCount', 0) or 0,
                open_access_pdf=oa_pdf
            )
            
        except requests.exceptions.RequestException as e:
            logger.error(f"Semantic Scholar API error for DOI {doi}: {e}")
            return None
        except Exception as e:
            logger.error(f"Unexpected error for DOI {doi}: {e}")
            return None
    
    def batch_get_abstracts(self, dois: List[str], 
                           progress_callback=None) -> Dict[str, str]:
        """
        여러 DOI의 초록 일괄 조회
        
        Args:
            dois: DOI 리스트
            progress_callback: 진행상황 콜백 (current, total)
            
        Returns:
            {doi: abstract} 딕셔너리
        """
        results = {}
        total = len(dois)
        success = 0
        
        for i, doi in enumerate(dois, 1):
            paper = self.get_paper_by_doi(doi)
            
            if paper and paper.abstract:
                results[doi] = paper.abstract
                success += 1
                logger.info(f"[{i}/{total}] ✓ {doi[:40]}...")
            else:
                logger.info(f"[{i}/{total}] ✗ {doi[:40]}... (초록 없음)")
            
            if progress_callback:
                progress_callback(i, total)
        
        logger.info(f"완료: {success}/{total} 논문 초록 획득")
        return results


def fetch_abstracts_from_semantic_scholar(db, limit: int = 50):
    """
    OpenAlex에서 못 찾은 초록을 Semantic Scholar에서 보충
    
    Args:
        db: Database 인스턴스
        limit: 처리할 최대 논문 수
        
    Returns:
        업데이트된 논문 수
    """
    import sqlite3
    
    # 초록 없고 DOI 있는 논문 조회
    with sqlite3.connect(db.db_path) as conn:
        conn.row_factory = sqlite3.Row
        cursor = conn.cursor()
        
        cursor.execute("""
            SELECT id, title, doi
            FROM articles
            WHERE (abstract IS NULL OR abstract = '' OR LENGTH(abstract) < 50)
              AND doi IS NOT NULL AND doi != ''
            LIMIT ?
        """, (limit,))
        
        articles = [dict(row) for row in cursor.fetchall()]
    
    if not articles:
        logger.info("Semantic Scholar로 보충할 논문이 없습니다.")
        return 0
    
    logger.info(f"Semantic Scholar 초록 보충 대상: {len(articles)}편")
    
    client = SemanticScholarClient()
    updated = 0
    
    for i, article in enumerate(articles, 1):
        doi = article.get('doi')
        if not doi:
            continue
        
        logger.info(f"[{i}/{len(articles)}] {article.get('title', '')[:50]}...")
        
        paper = client.get_paper_by_doi(doi)
        
        if paper and paper.abstract and len(paper.abstract) >= 50:
            db.update_article_abstract(article['id'], paper.abstract)
            logger.info(f"  → Semantic Scholar에서 초록 획득!")
            updated += 1
        else:
            logger.info(f"  → Semantic Scholar에도 초록 없음")
    
    logger.info(f"\nSemantic Scholar로 {updated}편 초록 보충 완료")
    return updated


if __name__ == "__main__":
    # 테스트
    client = SemanticScholarClient()
    
    # 테스트 DOI
    test_doi = "10.1177/0309132520925833"
    
    print(f"Testing DOI: {test_doi}")
    paper = client.get_paper_by_doi(test_doi)
    
    if paper:
        print(f"\n제목: {paper.title}")
        print(f"저자: {', '.join(paper.authors[:3])}{'...' if len(paper.authors) > 3 else ''}")
        print(f"연도: {paper.year}")
        print(f"인용수: {paper.citation_count}")
        print(f"\n초록 ({len(paper.abstract)}자):")
        print(paper.abstract[:300] + "..." if len(paper.abstract) > 300 else paper.abstract)
    else:
        print("논문을 찾을 수 없습니다.")
