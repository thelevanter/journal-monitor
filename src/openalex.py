"""
openalex.py - OpenAlex API 연동 모듈
케이의 학술저널 RSS 모니터링 시스템

OpenAlex: 무료 학술 메타데이터 API
- DOI 기반 논문 정보 조회
- 초록이 없는 논문 보충에 활용
"""

import requests
import time
import logging
from typing import Dict, List, Optional
from dataclasses import dataclass

logging.basicConfig(level=logging.INFO)
logger = logging.getLogger(__name__)


@dataclass
class OpenAlexWork:
    """OpenAlex 논문 정보 데이터 클래스"""
    doi: str
    title: str
    abstract: str
    authors: List[str]
    publication_year: int
    cited_by_count: int
    open_access_url: Optional[str] = None


class OpenAlexClient:
    """OpenAlex API 클라이언트"""
    
    BASE_URL = "https://api.openalex.org"
    
    def __init__(self, email: str = None, request_delay: float = 0.2):
        """
        클라이언트 초기화
        
        Args:
            email: API 요청 시 사용할 이메일 (polite pool용, 속도 제한 완화)
            request_delay: 요청 간 대기 시간 (초)
        """
        self.email = email
        self.request_delay = request_delay
        self.session = requests.Session()
        
        # User-Agent 설정 (polite pool 이용)
        if email:
            self.session.headers.update({
                'User-Agent': f'JournalMonitor/1.0 (mailto:{email})'
            })
        else:
            self.session.headers.update({
                'User-Agent': 'JournalMonitor/1.0'
            })
    
    def _reconstruct_abstract(self, inverted_index: Dict) -> str:
        """
        OpenAlex의 inverted index 형식 초록을 원문으로 복원
        
        OpenAlex는 초록을 {word: [positions]} 형태로 저장
        예: {"The": [0], "quick": [1], "brown": [2], ...}
        
        Args:
            inverted_index: OpenAlex abstract_inverted_index 필드
            
        Returns:
            복원된 초록 텍스트
        """
        if not inverted_index:
            return ""
        
        # 위치 → 단어 매핑
        position_word = {}
        for word, positions in inverted_index.items():
            for pos in positions:
                position_word[pos] = word
        
        # 위치 순서대로 단어 조합
        if not position_word:
            return ""
        
        max_pos = max(position_word.keys())
        words = [position_word.get(i, '') for i in range(max_pos + 1)]
        
        return ' '.join(words)
    
    def get_work_by_doi(self, doi: str) -> Optional[OpenAlexWork]:
        """
        DOI로 논문 정보 조회
        
        Args:
            doi: 논문 DOI (10.xxxx/xxxx 형식 또는 전체 URL)
            
        Returns:
            OpenAlexWork 또는 None
        """
        # DOI 정규화
        doi = doi.strip()
        if doi.startswith('http'):
            # https://doi.org/10.xxxx/xxxx → 10.xxxx/xxxx
            doi = doi.split('doi.org/')[-1]
        
        # API 호출
        url = f"{self.BASE_URL}/works/https://doi.org/{doi}"
        
        try:
            time.sleep(self.request_delay)  # Rate limiting
            
            params = {}
            if self.email:
                params['mailto'] = self.email
            
            response = self.session.get(url, params=params, timeout=30)
            
            if response.status_code == 404:
                logger.debug(f"DOI not found in OpenAlex: {doi}")
                return None
            
            response.raise_for_status()
            data = response.json()
            
            # 초록 복원
            abstract = ""
            if data.get('abstract_inverted_index'):
                abstract = self._reconstruct_abstract(data['abstract_inverted_index'])
            
            # 저자 목록 추출
            authors = []
            for authorship in data.get('authorships', []):
                author = authorship.get('author', {})
                name = author.get('display_name', '')
                if name:
                    authors.append(name)
            
            # Open Access URL 추출
            oa_url = None
            if data.get('open_access', {}).get('oa_url'):
                oa_url = data['open_access']['oa_url']
            
            return OpenAlexWork(
                doi=doi,
                title=data.get('title', ''),
                abstract=abstract,
                authors=authors,
                publication_year=data.get('publication_year', 0),
                cited_by_count=data.get('cited_by_count', 0),
                open_access_url=oa_url
            )
            
        except requests.exceptions.RequestException as e:
            logger.error(f"OpenAlex API error for DOI {doi}: {e}")
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
            work = self.get_work_by_doi(doi)
            
            if work and work.abstract:
                results[doi] = work.abstract
                success += 1
                logger.info(f"[{i}/{total}] ✓ {doi[:40]}...")
            else:
                logger.info(f"[{i}/{total}] ✗ {doi[:40]}... (초록 없음)")
            
            if progress_callback:
                progress_callback(i, total)
        
        logger.info(f"완료: {success}/{total} 논문 초록 획득")
        return results
    
    def get_work_metadata(self, doi: str) -> Optional[Dict]:
        """
        DOI로 전체 메타데이터 조회 (디버깅/분석용)
        
        Returns:
            원본 API 응답 딕셔너리
        """
        doi = doi.strip()
        if doi.startswith('http'):
            doi = doi.split('doi.org/')[-1]
        
        url = f"{self.BASE_URL}/works/https://doi.org/{doi}"
        
        try:
            time.sleep(self.request_delay)
            
            params = {}
            if self.email:
                params['mailto'] = self.email
            
            response = self.session.get(url, params=params, timeout=30)
            response.raise_for_status()
            
            return response.json()
            
        except Exception as e:
            logger.error(f"Error fetching metadata: {e}")
            return None


def fetch_missing_abstracts(db, email: str = None, limit: int = 50, 
                           translate: bool = False, summarizer=None):
    """
    초록이 없는 논문들의 초록을 OpenAlex에서 가져와 DB 업데이트
    
    Args:
        db: Database 인스턴스
        email: OpenAlex polite pool용 이메일
        limit: 처리할 최대 논문 수
        translate: 번역 여부 (summarizer 필요)
        summarizer: Summarizer 인스턴스 (번역 시 필요)
        
    Returns:
        업데이트된 논문 수
    """
    # 초록 없는 논문 조회
    articles = db.get_articles_without_abstract(limit=limit)
    
    if not articles:
        logger.info("초록이 없는 논문이 없습니다.")
        return 0
    
    logger.info(f"초록 보충 대상: {len(articles)}편")
    
    # OpenAlex 클라이언트
    client = OpenAlexClient(email=email)
    
    updated = 0
    
    for i, article in enumerate(articles, 1):
        doi = article.get('doi')
        if not doi:
            continue
        
        logger.info(f"[{i}/{len(articles)}] {article.get('title', '')[:50]}...")
        
        # OpenAlex에서 초록 가져오기
        work = client.get_work_by_doi(doi)
        
        if work and work.abstract and len(work.abstract) >= 50:
            if translate and summarizer:
                # 번역도 함께 수행
                try:
                    temp_article = {
                        'title': article.get('title', ''),
                        'abstract': work.abstract
                    }
                    result = summarizer.translate_and_summarize(temp_article)
                    
                    db.update_article_abstract(
                        article['id'],
                        work.abstract,
                        result.abstract_ko,
                        result.summary_ko
                    )
                    
                    # 우선순위도 업데이트
                    if result.priority != 'normal':
                        db.update_article_priority(
                            article['id'],
                            result.priority,
                            result.keywords_matched
                        )
                    
                    logger.info(f"  → 초록 + 번역 완료 (우선순위: {result.priority})")
                    
                except Exception as e:
                    logger.error(f"  → 번역 실패: {e}")
                    db.update_article_abstract(article['id'], work.abstract)
            else:
                db.update_article_abstract(article['id'], work.abstract)
                logger.info(f"  → 초록 업데이트 완료")
            
            updated += 1
        else:
            logger.info(f"  → OpenAlex에 초록 없음")
    
    logger.info(f"\n총 {updated}편 초록 보충 완료")
    return updated


def recheck_priorities(db, summarizer):
    """
    초록이 있지만 키워드 매칭 안 된 논문들의 우선순위 재계산
    
    Args:
        db: Database 인스턴스
        summarizer: Summarizer 인스턴스
        
    Returns:
        (재분류된 수, high 수, medium 수)
    """
    import sqlite3
    import json
    
    with sqlite3.connect(db.db_path) as conn:
        conn.row_factory = sqlite3.Row
        cursor = conn.cursor()
        
        # 초록은 있지만 keywords_matched가 없는 논문 조회
        cursor.execute("""
            SELECT id, title, abstract, priority, keywords_matched
            FROM articles
            WHERE abstract IS NOT NULL 
              AND LENGTH(abstract) >= 50
              AND (keywords_matched IS NULL OR keywords_matched = '[]')
        """)
        
        articles = cursor.fetchall()
    
    if not articles:
        logger.info("우선순위 재계산 대상이 없습니다.")
        return 0, 0, 0
    
    logger.info(f"우선순위 재계산 대상: {len(articles)}편")
    
    rechecked = 0
    high_count = 0
    medium_count = 0
    
    for article in articles:
        title = article['title'] or ''
        abstract = article['abstract'] or ''
        
        priority, keywords = summarizer._check_priority(title, abstract)
        
        if keywords:  # 키워드 매칭된 경우만 업데이트
            db.update_article_priority(article['id'], priority, keywords)
            rechecked += 1
            
            if priority == 'high':
                high_count += 1
                logger.info(f"  🔴 HIGH: {title[:50]}... → {keywords}")
            elif priority == 'medium':
                medium_count += 1
                logger.info(f"  🟡 MEDIUM: {title[:50]}... → {keywords}")
    
    logger.info(f"\n재분류 완료: {rechecked}편 (🔴 {high_count} / 🟡 {medium_count})")
    return rechecked, high_count, medium_count


def translate_priority_articles(db, summarizer, priorities=['high', 'medium']):
    """
    특정 우선순위 논문 중 번역 안 된 것만 번역
    
    Args:
        db: Database 인스턴스
        summarizer: Summarizer 인스턴스  
        priorities: 번역할 우선순위 리스트
        
    Returns:
        번역된 논문 수
    """
    import sqlite3
    
    placeholders = ','.join(['?' for _ in priorities])
    
    with sqlite3.connect(db.db_path) as conn:
        conn.row_factory = sqlite3.Row
        cursor = conn.cursor()
        
        # 해당 우선순위 중 번역 안 된 논문
        cursor.execute(f"""
            SELECT id, title, abstract, priority
            FROM articles
            WHERE priority IN ({placeholders})
              AND abstract IS NOT NULL
              AND LENGTH(abstract) >= 50
              AND (abstract_ko IS NULL OR abstract_ko = '' OR summary_ko IS NULL OR summary_ko = '')
        """, priorities)
        
        articles = [dict(row) for row in cursor.fetchall()]
    
    if not articles:
        logger.info("번역할 논문이 없습니다.")
        return 0
    
    logger.info(f"번역 대상: {len(articles)}편 (우선순위: {', '.join(priorities)})")
    
    translated = 0
    
    for i, article in enumerate(articles, 1):
        logger.info(f"[{i}/{len(articles)}] {article['title'][:50]}...")
        
        try:
            result = summarizer.translate_and_summarize(article)
            
            db.update_article_translation(
                article['id'],
                result.title_ko,
                result.abstract_ko,
                result.summary_ko
            )
            
            translated += 1
            logger.info(f"  → 번역 완료")
            
        except Exception as e:
            logger.error(f"  → 번역 실패: {e}")
    
    logger.info(f"\n번역 완료: {translated}/{len(articles)}편")
    return translated


if __name__ == "__main__":
    # 테스트
    client = OpenAlexClient()
    
    # 테스트 DOI
    test_doi = "10.1177/0309132520925833"  # Progress in Human Geography 논문
    
    print(f"Testing DOI: {test_doi}")
    work = client.get_work_by_doi(test_doi)
    
    if work:
        print(f"\n제목: {work.title}")
        print(f"저자: {', '.join(work.authors[:3])}{'...' if len(work.authors) > 3 else ''}")
        print(f"연도: {work.publication_year}")
        print(f"인용수: {work.cited_by_count}")
        print(f"\n초록 ({len(work.abstract)}자):")
        print(work.abstract[:300] + "..." if len(work.abstract) > 300 else work.abstract)
    else:
        print("논문을 찾을 수 없습니다.")
