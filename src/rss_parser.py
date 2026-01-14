"""
rss_parser.py - RSS 피드 파싱 모듈
케이의 학술저널 RSS 모니터링 시스템
"""

import feedparser
import xml.etree.ElementTree as ET
from pathlib import Path
from datetime import datetime, timedelta
from typing import List, Dict, Optional, Tuple
from dataclasses import dataclass
import time
import re
from html import unescape
import logging

logging.basicConfig(level=logging.INFO)
logger = logging.getLogger(__name__)


@dataclass
class FeedInfo:
    """피드 정보 데이터 클래스"""
    name: str
    url: str
    category: str


class RSSParser:
    """RSS 피드 파싱 클래스"""
    
    def __init__(self, opml_path: str, request_delay: float = 1.0):
        """
        RSS 파서 초기화
        
        Args:
            opml_path: OPML 파일 경로
            request_delay: 피드 간 요청 딜레이 (초)
        """
        self.opml_path = Path(opml_path).expanduser()
        self.request_delay = request_delay
        self.feeds: List[FeedInfo] = []
        
        if self.opml_path.exists():
            self._parse_opml()
    
    def _parse_opml(self):
        """OPML 파일 파싱하여 피드 목록 추출"""
        try:
            tree = ET.parse(self.opml_path)
            root = tree.getroot()
            
            for outline in root.iter('outline'):
                # 폴더인 경우 (자식 outline이 있음)
                children = list(outline)
                if children:
                    category = outline.get('text', 'Uncategorized')
                    for child in children:
                        xml_url = child.get('xmlUrl')
                        if xml_url:
                            self.feeds.append(FeedInfo(
                                name=child.get('title') or child.get('text', 'Unknown'),
                                url=xml_url,
                                category=category
                            ))
                else:
                    # 단독 피드인 경우
                    xml_url = outline.get('xmlUrl')
                    if xml_url:
                        self.feeds.append(FeedInfo(
                            name=outline.get('title') or outline.get('text', 'Unknown'),
                            url=xml_url,
                            category='Uncategorized'
                        ))
            
            logger.info(f"Loaded {len(self.feeds)} feeds from OPML")
            
        except ET.ParseError as e:
            logger.error(f"Error parsing OPML: {e}")
            raise
    
    def get_feeds_by_category(self, category: str) -> List[FeedInfo]:
        """카테고리별 피드 목록 조회"""
        return [f for f in self.feeds if f.category == category]
    
    def get_categories(self) -> List[str]:
        """모든 카테고리 목록"""
        return list(set(f.category for f in self.feeds))
    
    @staticmethod
    def _clean_html(text: str) -> str:
        """HTML 태그 제거 및 텍스트 정리"""
        if not text:
            return ""
        # HTML 태그 제거
        clean = re.sub(r'<[^>]+>', '', text)
        # HTML 엔티티 디코딩
        clean = unescape(clean)
        # 여러 공백을 하나로
        clean = re.sub(r'\s+', ' ', clean).strip()
        return clean
    
    @staticmethod
    def _parse_date(entry: dict) -> Optional[datetime]:
        """피드 엔트리에서 날짜 파싱"""
        # published_parsed 또는 updated_parsed 사용
        date_struct = entry.get('published_parsed') or entry.get('updated_parsed')
        
        if date_struct:
            try:
                return datetime(*date_struct[:6])
            except (TypeError, ValueError):
                pass
        
        # 문자열로 시도
        for key in ['published', 'updated', 'dc:date']:
            if key in entry:
                try:
                    # 다양한 날짜 형식 시도
                    from dateutil import parser
                    return parser.parse(entry[key])
                except:
                    pass
        
        return None
    
    @staticmethod
    def _extract_doi(entry: dict) -> Optional[str]:
        """DOI 추출"""
        # dc:identifier나 prism:doi에서 추출
        doi = entry.get('prism_doi') or entry.get('dc_identifier')
        if doi:
            return doi
        
        # 링크에서 DOI 추출 시도
        link = entry.get('link', '')
        doi_match = re.search(r'10\.\d{4,}/[^\s]+', link)
        if doi_match:
            return doi_match.group()
        
        return None
    
    @staticmethod
    def _extract_authors(entry: dict) -> str:
        """저자 추출"""
        authors = []
        
        # author 필드
        if 'author' in entry:
            authors.append(entry['author'])
        
        # authors 리스트
        if 'authors' in entry:
            for author in entry['authors']:
                if isinstance(author, dict):
                    authors.append(author.get('name', ''))
                else:
                    authors.append(str(author))
        
        # dc:creator
        if 'dc_creator' in entry:
            if isinstance(entry['dc_creator'], list):
                authors.extend(entry['dc_creator'])
            else:
                authors.append(entry['dc_creator'])
        
        # 중복 제거 및 정리
        authors = [a.strip() for a in authors if a.strip()]
        authors = list(dict.fromkeys(authors))  # 순서 유지하며 중복 제거
        
        return ', '.join(authors) if authors else ''
    
    def fetch_feed(self, feed: FeedInfo, hours: int = 24, 
                   max_articles: int = 10) -> List[Dict]:
        """
        단일 피드에서 최근 논문 수집
        
        Args:
            feed: 피드 정보
            hours: 최근 N시간 내 논문만
            max_articles: 최대 수집 개수
            
        Returns:
            논문 리스트
        """
        articles = []
        cutoff_time = datetime.now() - timedelta(hours=hours)
        
        try:
            logger.info(f"Fetching: {feed.name}")
            parsed = feedparser.parse(feed.url)
            
            if parsed.bozo and parsed.bozo_exception:
                logger.warning(f"Feed warning for {feed.name}: {parsed.bozo_exception}")
            
            for entry in parsed.entries[:max_articles * 2]:  # 여유있게 가져옴
                pub_date = self._parse_date(entry)
                
                # 날짜 필터링 (날짜 없으면 포함)
                if pub_date and pub_date < cutoff_time:
                    continue
                
                # 제목과 URL 필수
                title = self._clean_html(entry.get('title', ''))
                url = entry.get('link', '')
                
                if not title or not url:
                    continue
                
                # 초록 추출 (summary, description, content 순서로 시도)
                abstract = ''
                for key in ['summary', 'description']:
                    if key in entry and entry[key]:
                        abstract = self._clean_html(entry[key])
                        break
                
                if not abstract and 'content' in entry:
                    for content in entry['content']:
                        if content.get('value'):
                            abstract = self._clean_html(content['value'])
                            break
                
                article = {
                    'title': title,
                    'url': url,
                    'abstract': abstract[:2000] if abstract else '',  # 길이 제한
                    'authors': self._extract_authors(entry),
                    'doi': self._extract_doi(entry),
                    'published_date': pub_date.isoformat() if pub_date else None,
                    'journal_name': feed.name,
                    'category': feed.category
                }
                
                articles.append(article)
                
                if len(articles) >= max_articles:
                    break
            
            logger.info(f"  → {len(articles)} articles found")
            
        except Exception as e:
            logger.error(f"Error fetching {feed.name}: {e}")
        
        return articles
    
    def fetch_all_feeds(self, hours: int = 24, 
                        max_articles_per_feed: int = 10,
                        categories: List[str] = None) -> List[Dict]:
        """
        모든 피드에서 논문 수집
        
        Args:
            hours: 최근 N시간 내 논문만
            max_articles_per_feed: 피드당 최대 수집 개수
            categories: 특정 카테고리만 (None이면 전체)
            
        Returns:
            논문 리스트
        """
        all_articles = []
        feeds_to_fetch = self.feeds
        
        if categories:
            feeds_to_fetch = [f for f in self.feeds if f.category in categories]
        
        total = len(feeds_to_fetch)
        for i, feed in enumerate(feeds_to_fetch, 1):
            logger.info(f"[{i}/{total}] Processing {feed.name}...")
            
            articles = self.fetch_feed(feed, hours, max_articles_per_feed)
            all_articles.extend(articles)
            
            # 요청 간 딜레이
            if i < total:
                time.sleep(self.request_delay)
        
        logger.info(f"Total articles collected: {len(all_articles)}")
        return all_articles
    
    def fetch_academic_only(self, hours: int = 24, 
                           max_articles_per_feed: int = 10) -> List[Dict]:
        """학술 저널 카테고리만 수집"""
        academic_categories = [
            'Academic: Geography Journals',
            'Academic: Sociology Journals',
            'Academic: Theory & Philosophy',
            'Academic: Planning Studies',
            'Academic: Urban & Planning History'
        ]
        return self.fetch_all_feeds(hours, max_articles_per_feed, academic_categories)


if __name__ == "__main__":
    # 테스트
    parser = RSSParser("./Feeds.opml")
    print(f"Loaded {len(parser.feeds)} feeds")
    print(f"Categories: {parser.get_categories()}")
    
    # 첫 번째 피드만 테스트
    if parser.feeds:
        articles = parser.fetch_feed(parser.feeds[0], hours=168, max_articles=3)
        for article in articles:
            print(f"\n- {article['title'][:60]}...")
            print(f"  Authors: {article['authors'][:50]}")
