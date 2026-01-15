"""
database.py - SQLite 데이터베이스 관리 모듈
케이의 학술저널 RSS 모니터링 시스템
"""

import sqlite3
from pathlib import Path
from datetime import datetime
from typing import List, Dict, Optional, Tuple
import hashlib
import json


class Database:
    """학술 논문 데이터베이스 관리 클래스"""
    
    def __init__(self, db_path: str):
        """
        데이터베이스 초기화
        
        Args:
            db_path: SQLite 데이터베이스 파일 경로
        """
        self.db_path = Path(db_path).expanduser()
        self.db_path.parent.mkdir(parents=True, exist_ok=True)
        self._init_db()
    
    def _init_db(self):
        """데이터베이스 테이블 초기화"""
        with sqlite3.connect(self.db_path) as conn:
            cursor = conn.cursor()
            
            # 기존 테이블 마이그레이션 (keywords_matched 컬럼 추가)
            self._migrate_keywords_column(cursor)
            
            # 저널 테이블
            cursor.execute("""
                CREATE TABLE IF NOT EXISTS journals (
                    id INTEGER PRIMARY KEY AUTOINCREMENT,
                    name TEXT UNIQUE NOT NULL,
                    feed_url TEXT NOT NULL,
                    category TEXT,
                    last_fetched TIMESTAMP,
                    created_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP
                )
            """)
            
            # 논문 테이블
            cursor.execute("""
                CREATE TABLE IF NOT EXISTS articles (
                    id INTEGER PRIMARY KEY AUTOINCREMENT,
                    journal_id INTEGER NOT NULL,
                    title TEXT NOT NULL,
                    title_ko TEXT,
                    authors TEXT,
                    abstract TEXT,
                    abstract_ko TEXT,
                    summary_ko TEXT,
                    url TEXT,
                    doi TEXT,
                    published_date TIMESTAMP,
                    fetched_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP,
                    hash TEXT UNIQUE,
                    priority TEXT DEFAULT 'normal',
                    is_read INTEGER DEFAULT 0,
                    is_starred INTEGER DEFAULT 0,
                    notes TEXT,
                    keywords_matched TEXT,
                    FOREIGN KEY (journal_id) REFERENCES journals(id)
                )
            """)
            
            # 보고서 테이블
            cursor.execute("""
                CREATE TABLE IF NOT EXISTS reports (
                    id INTEGER PRIMARY KEY AUTOINCREMENT,
                    report_date DATE UNIQUE NOT NULL,
                    total_articles INTEGER,
                    high_priority_count INTEGER,
                    file_path TEXT,
                    craft_synced INTEGER DEFAULT 0,
                    created_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP
                )
            """)
            
            # 인덱스 생성
            cursor.execute("CREATE INDEX IF NOT EXISTS idx_articles_published ON articles(published_date)")
            cursor.execute("CREATE INDEX IF NOT EXISTS idx_articles_priority ON articles(priority)")
            cursor.execute("CREATE INDEX IF NOT EXISTS idx_articles_hash ON articles(hash)")
            
            conn.commit()
    
    def get_or_create_journal(self, name: str, feed_url: str, category: str = None) -> int:
        """
        저널 조회 또는 생성
        
        Returns:
            저널 ID
        """
        with sqlite3.connect(self.db_path) as conn:
            cursor = conn.cursor()
            
            cursor.execute("SELECT id FROM journals WHERE name = ?", (name,))
            result = cursor.fetchone()
            
            if result:
                return result[0]
            
            cursor.execute(
                "INSERT INTO journals (name, feed_url, category) VALUES (?, ?, ?)",
                (name, feed_url, category)
            )
            conn.commit()
            return cursor.lastrowid
    
    def article_exists(self, article_hash: str) -> bool:
        """논문 중복 체크"""
        with sqlite3.connect(self.db_path) as conn:
            cursor = conn.cursor()
            cursor.execute("SELECT 1 FROM articles WHERE hash = ?", (article_hash,))
            return cursor.fetchone() is not None
    
    @staticmethod
    def generate_hash(title: str, url: str) -> str:
        """논문 고유 해시 생성"""
        content = f"{title}|{url}"
        return hashlib.md5(content.encode()).hexdigest()
    
    def insert_article(self, article: Dict) -> Optional[int]:
        """
        논문 삽입
        
        Args:
            article: 논문 정보 딕셔너리
            
        Returns:
            삽입된 논문 ID 또는 None (중복 시)
        """
        article_hash = self.generate_hash(article.get('title', ''), article.get('url', ''))
        
        if self.article_exists(article_hash):
            return None
        
        with sqlite3.connect(self.db_path) as conn:
            cursor = conn.cursor()
            
            # keywords_matched를 JSON 문자열로 변환
            keywords = article.get('keywords_matched', [])
            keywords_json = json.dumps(keywords, ensure_ascii=False) if keywords else None
            
            cursor.execute("""
                INSERT INTO articles (
                    journal_id, title, title_ko, authors, abstract, abstract_ko,
                    summary_ko, url, doi, published_date, hash, priority, keywords_matched
                ) VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?)
            """, (
                article.get('journal_id'),
                article.get('title'),
                article.get('title_ko'),
                article.get('authors'),
                article.get('abstract'),
                article.get('abstract_ko'),
                article.get('summary_ko'),
                article.get('url'),
                article.get('doi'),
                article.get('published_date'),
                article_hash,
                article.get('priority', 'normal'),
                keywords_json
            ))
            
            conn.commit()
            return cursor.lastrowid
    
    def get_articles_since(self, hours: int = 24) -> List[Dict]:
        """
        최근 N시간 내 수집된 논문 조회
        
        Args:
            hours: 조회할 시간 범위
            
        Returns:
            논문 리스트
        """
        with sqlite3.connect(self.db_path) as conn:
            conn.row_factory = sqlite3.Row
            cursor = conn.cursor()
            
            cursor.execute("""
                SELECT a.*, j.name as journal_name, j.category
                FROM articles a
                JOIN journals j ON a.journal_id = j.id
                WHERE a.fetched_at >= datetime('now', ?)
                ORDER BY 
                    CASE a.priority 
                        WHEN 'high' THEN 1 
                        WHEN 'medium' THEN 2 
                        ELSE 3 
                    END,
                    a.published_date DESC
            """, (f'-{hours} hours',))
            
            return self._parse_articles(cursor.fetchall())
    
    def get_articles_by_date(self, date: str) -> List[Dict]:
        """특정 날짜에 수집된 논문 조회"""
        with sqlite3.connect(self.db_path) as conn:
            conn.row_factory = sqlite3.Row
            cursor = conn.cursor()
            
            cursor.execute("""
                SELECT a.*, j.name as journal_name, j.category
                FROM articles a
                JOIN journals j ON a.journal_id = j.id
                WHERE DATE(a.fetched_at) = ?
                ORDER BY 
                    CASE a.priority 
                        WHEN 'high' THEN 1 
                        WHEN 'medium' THEN 2 
                        ELSE 3 
                    END,
                    a.published_date DESC
            """, (date,))
            
            return self._parse_articles(cursor.fetchall())
    
    def _parse_articles(self, rows) -> List[Dict]:
        """
        조회 결과를 파싱하여 keywords_matched를 리스트로 변환
        """
        articles = []
        for row in rows:
            article = dict(row)
            # keywords_matched JSON 파싱
            kw = article.get('keywords_matched')
            if kw:
                try:
                    article['keywords_matched'] = json.loads(kw)
                except (json.JSONDecodeError, TypeError):
                    article['keywords_matched'] = []
            else:
                article['keywords_matched'] = []
            articles.append(article)
        return articles
    
    def _migrate_keywords_column(self, cursor):
        """
        기존 DB에 keywords_matched 컬럼이 없으면 추가
        """
        cursor.execute("PRAGMA table_info(articles)")
        columns = [col[1] for col in cursor.fetchall()]
        
        if 'keywords_matched' not in columns:
            cursor.execute("ALTER TABLE articles ADD COLUMN keywords_matched TEXT")
    
    def update_article_translation(self, article_id: int, title_ko: str, 
                                   abstract_ko: str, summary_ko: str):
        """논문 번역 정보 업데이트"""
        with sqlite3.connect(self.db_path) as conn:
            cursor = conn.cursor()
            cursor.execute("""
                UPDATE articles 
                SET title_ko = ?, abstract_ko = ?, summary_ko = ?
                WHERE id = ?
            """, (title_ko, abstract_ko, summary_ko, article_id))
            conn.commit()
    
    def save_report_record(self, report_date: str, total_articles: int,
                          high_priority_count: int, file_path: str) -> int:
        """보고서 기록 저장"""
        with sqlite3.connect(self.db_path) as conn:
            cursor = conn.cursor()
            cursor.execute("""
                INSERT OR REPLACE INTO reports 
                (report_date, total_articles, high_priority_count, file_path)
                VALUES (?, ?, ?, ?)
            """, (report_date, total_articles, high_priority_count, file_path))
            conn.commit()
            return cursor.lastrowid
    
    def mark_report_synced(self, report_date: str):
        """보고서 Craft 동기화 완료 표시"""
        with sqlite3.connect(self.db_path) as conn:
            cursor = conn.cursor()
            cursor.execute(
                "UPDATE reports SET craft_synced = 1 WHERE report_date = ?",
                (report_date,)
            )
            conn.commit()
    
    def get_stats(self) -> Dict:
        """데이터베이스 통계 조회"""
        with sqlite3.connect(self.db_path) as conn:
            cursor = conn.cursor()
            
            stats = {}
            
            cursor.execute("SELECT COUNT(*) FROM journals")
            stats['total_journals'] = cursor.fetchone()[0]
            
            cursor.execute("SELECT COUNT(*) FROM articles")
            stats['total_articles'] = cursor.fetchone()[0]
            
            cursor.execute("SELECT COUNT(*) FROM articles WHERE priority = 'high'")
            stats['high_priority'] = cursor.fetchone()[0]
            
            cursor.execute("""
                SELECT COUNT(*) FROM articles 
                WHERE fetched_at >= datetime('now', '-24 hours')
            """)
            stats['articles_24h'] = cursor.fetchone()[0]
            
            cursor.execute("""
                SELECT COUNT(*) FROM articles 
                WHERE fetched_at >= datetime('now', '-7 days')
            """)
            stats['articles_7d'] = cursor.fetchone()[0]
            
            return stats
    
    # ============ OpenAlex API 연동용 메서드 ============
    
    def get_articles_without_abstract(self, limit: int = 100) -> List[Dict]:
        """
        초록이 없거나 매우 짧은 논문 조회 (OpenAlex로 보충용)
        
        Args:
            limit: 최대 조회 수
            
        Returns:
            DOI가 있고 초록이 없는 논문 리스트
        """
        with sqlite3.connect(self.db_path) as conn:
            conn.row_factory = sqlite3.Row
            cursor = conn.cursor()
            
            cursor.execute("""
                SELECT a.*, j.name as journal_name, j.category
                FROM articles a
                JOIN journals j ON a.journal_id = j.id
                WHERE a.doi IS NOT NULL 
                  AND a.doi != ''
                  AND (a.abstract IS NULL OR LENGTH(a.abstract) < 50)
                ORDER BY a.fetched_at DESC
                LIMIT ?
            """, (limit,))
            
            return self._parse_articles(cursor.fetchall())
    
    def update_article_abstract(self, article_id: int, abstract: str, 
                                 abstract_ko: str = None, summary_ko: str = None):
        """
        논문 초록 업데이트 (OpenAlex에서 가져온 경우)
        
        Args:
            article_id: 논문 ID
            abstract: 영문 초록
            abstract_ko: 한국어 번역 초록 (옵션)
            summary_ko: 한국어 요약 (옵션)
        """
        with sqlite3.connect(self.db_path) as conn:
            cursor = conn.cursor()
            
            if abstract_ko and summary_ko:
                cursor.execute("""
                    UPDATE articles 
                    SET abstract = ?, abstract_ko = ?, summary_ko = ?
                    WHERE id = ?
                """, (abstract, abstract_ko, summary_ko, article_id))
            else:
                cursor.execute("""
                    UPDATE articles SET abstract = ? WHERE id = ?
                """, (abstract, article_id))
            
            conn.commit()
    
    def update_article_priority(self, article_id: int, priority: str, 
                                 keywords_matched: List[str] = None):
        """
        논문 우선순위 및 매칭 키워드 업데이트
        
        Args:
            article_id: 논문 ID
            priority: 우선순위 ('high', 'medium', 'normal')
            keywords_matched: 매칭된 키워드 리스트
        """
        with sqlite3.connect(self.db_path) as conn:
            cursor = conn.cursor()
            
            keywords_json = json.dumps(keywords_matched, ensure_ascii=False) if keywords_matched else None
            
            cursor.execute("""
                UPDATE articles 
                SET priority = ?, keywords_matched = ?
                WHERE id = ?
            """, (priority, keywords_json, article_id))
            
            conn.commit()
    
    def get_abstract_stats(self) -> Dict:
        """
        초록 보유 현황 통계
        """
        with sqlite3.connect(self.db_path) as conn:
            cursor = conn.cursor()
            
            stats = {}
            
            cursor.execute("SELECT COUNT(*) FROM articles")
            stats['total'] = cursor.fetchone()[0]
            
            cursor.execute("SELECT COUNT(*) FROM articles WHERE abstract IS NOT NULL AND LENGTH(abstract) >= 50")
            stats['with_abstract'] = cursor.fetchone()[0]
            
            cursor.execute("SELECT COUNT(*) FROM articles WHERE abstract IS NULL OR LENGTH(abstract) < 50")
            stats['without_abstract'] = cursor.fetchone()[0]
            
            cursor.execute("SELECT COUNT(*) FROM articles WHERE doi IS NOT NULL AND doi != ''")
            stats['with_doi'] = cursor.fetchone()[0]
            
            cursor.execute("""
                SELECT COUNT(*) FROM articles 
                WHERE doi IS NOT NULL AND doi != '' 
                  AND (abstract IS NULL OR LENGTH(abstract) < 50)
            """)
            stats['can_fetch_from_openalex'] = cursor.fetchone()[0]
            
            return stats


if __name__ == "__main__":
    # 테스트
    db = Database("./test_journals.db")
    print("Database initialized successfully!")
    print(f"Stats: {db.get_stats()}")
