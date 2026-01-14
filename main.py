#!/usr/bin/env python3
"""
Journal Monitor - 메인 실행 파일
케이의 학술저널 RSS 모니터링 시스템

사용법:
    python main.py                    # 기본 실행 (24시간 내 논문)
    python main.py --hours 48         # 48시간 내 논문
    python main.py --no-translate     # 번역 없이 수집만
    python main.py --craft            # Craft용 콘텐츠 출력
    python main.py --stats            # 통계만 출력
"""

import os
import sys
import argparse
import logging
from pathlib import Path
from datetime import date, datetime
import yaml

# 프로젝트 경로 추가
sys.path.insert(0, str(Path(__file__).parent))

from src.database import Database
from src.rss_parser import RSSParser
from src.summarizer import Summarizer
from src.report_generator import ReportGenerator

logging.basicConfig(
    level=logging.INFO,
    format='%(asctime)s [%(levelname)s] %(message)s',
    datefmt='%Y-%m-%d %H:%M:%S'
)
logger = logging.getLogger(__name__)


class JournalMonitor:
    """학술저널 모니터링 메인 클래스"""
    
    def __init__(self, config_path: str = None):
        """
        초기화
        
        Args:
            config_path: 설정 파일 경로
        """
        self.config = self._load_config(config_path)
        self._init_components()
    
    def _load_config(self, config_path: str = None) -> dict:
        """설정 파일 로드"""
        if config_path is None:
            config_path = Path(__file__).parent / 'config.yaml'
        
        config_path = Path(config_path)
        
        if config_path.exists():
            with open(config_path, 'r', encoding='utf-8') as f:
                config = yaml.safe_load(f)
            logger.info(f"Config loaded from {config_path}")
            return config
        else:
            logger.warning("Config file not found, using defaults")
            return self._default_config()
    
    def _default_config(self) -> dict:
        """기본 설정"""
        return {
            'paths': {
                'opml_file': '~/Documents/JournalMonitor/Feeds.opml',
                'database': '~/Documents/JournalMonitor/data/journals.db',
                'reports_dir': '~/Documents/JournalMonitor/reports',
                'templates_dir': './templates'
            },
            'anthropic': {
                'model': 'claude-sonnet-4-20250514',
                'max_tokens': 1024
            },
            'rss': {
                'fetch_hours': 24,
                'max_articles_per_feed': 10,
                'request_delay': 1.0
            },
            'craft': {
                'enabled': True,
                'daily_note': True
            }
        }
    
    def _init_components(self):
        """컴포넌트 초기화"""
        paths = self.config['paths']
        
        # 경로 확장
        opml_path = Path(paths['opml_file']).expanduser()
        db_path = Path(paths['database']).expanduser()
        reports_dir = Path(paths['reports_dir']).expanduser()
        templates_dir = Path(paths.get('templates_dir', './templates'))
        
        # 디렉토리 생성
        db_path.parent.mkdir(parents=True, exist_ok=True)
        reports_dir.mkdir(parents=True, exist_ok=True)
        
        # 컴포넌트 초기화
        self.db = Database(str(db_path))
        self.parser = RSSParser(
            str(opml_path),
            request_delay=self.config['rss'].get('request_delay', 1.0)
        )
        self.report_gen = ReportGenerator(
            template_dir=str(templates_dir) if templates_dir.exists() else None,
            output_dir=str(reports_dir)
        )
        
        # API 키 체크
        self.api_key = os.environ.get('ANTHROPIC_API_KEY')
        if self.api_key:
            self.summarizer = Summarizer(
                api_key=self.api_key,
                model=self.config['anthropic'].get('model', 'claude-sonnet-4-20250514')
            )
        else:
            self.summarizer = None
            logger.warning("ANTHROPIC_API_KEY not set - translation disabled")
    
    def run(self, hours: int = None, translate: bool = True, 
            academic_only: bool = True) -> dict:
        """
        메인 실행
        
        Args:
            hours: 수집할 시간 범위
            translate: 번역 수행 여부
            academic_only: 학술 저널만 수집 (categories 설정 없을 때)
            
        Returns:
            실행 결과 요약
        """
        if hours is None:
            hours = self.config['rss'].get('fetch_hours', 24)
        
        max_per_feed = self.config['rss'].get('max_articles_per_feed', 10)
        
        logger.info("=" * 60)
        logger.info("📚 Journal Monitor 시작")
        logger.info(f"   수집 범위: 최근 {hours}시간")
        logger.info(f"   피드당 최대: {max_per_feed}편")
        logger.info("=" * 60)
        
        # 1. RSS 피드에서 논문 수집
        logger.info("\n[1/4] RSS 피드 수집 중...")
        
        # config에서 카테고리 가져오기
        categories = self.config['rss'].get('categories', None)
        if categories:
            logger.info(f"   카테고리: {', '.join(categories)}")
            articles = self.parser.fetch_all_feeds(hours, max_per_feed, categories)
        elif academic_only:
            articles = self.parser.fetch_academic_only(hours, max_per_feed)
        else:
            articles = self.parser.fetch_all_feeds(hours, max_per_feed)
        
        if not articles:
            logger.info("수집된 논문이 없습니다.")
            return {'total': 0, 'new': 0}
        
        logger.info(f"   → {len(articles)}편 수집됨")
        
        # 2. 번역 및 요약 (API 키가 있고, 번역 옵션이 켜진 경우)
        if translate and self.summarizer:
            logger.info("\n[2/4] 번역 및 요약 중...")
            articles = self.summarizer.batch_translate(articles)
        else:
            logger.info("\n[2/4] 번역 스킵")
            # 우선순위만 체크
            if self.summarizer:
                for article in articles:
                    priority, keywords = self.summarizer._check_priority(
                        article.get('title', ''),
                        article.get('abstract', '')
                    )
                    article['priority'] = priority
                    article['keywords_matched'] = keywords
        
        # 3. 데이터베이스 저장
        logger.info("\n[3/4] 데이터베이스 저장 중...")
        new_count = 0
        for article in articles:
            # 저널 등록
            journal_id = self.db.get_or_create_journal(
                name=article.get('journal_name', 'Unknown'),
                feed_url='',
                category=article.get('category')
            )
            article['journal_id'] = journal_id
            
            # 논문 저장
            article_id = self.db.insert_article(article)
            if article_id:
                new_count += 1
        
        logger.info(f"   → {new_count}편 새로 저장 (중복 제외)")
        
        # 4. 보고서 생성
        logger.info("\n[4/4] 보고서 생성 중...")
        
        # 오늘 저장된 논문으로 보고서 생성
        today_articles = self.db.get_articles_by_date(date.today().isoformat())
        
        if today_articles:
            report_path = self.report_gen.generate_report(today_articles)
            logger.info(f"   → 로컬 보고서: {report_path}")
            
            # 보고서 기록 저장
            summary = self.report_gen.get_report_summary(today_articles)
            self.db.save_report_record(
                report_date=date.today().isoformat(),
                total_articles=summary['total'],
                high_priority_count=summary['high_priority'],
                file_path=report_path
            )
            
            # Craft 콘텐츠 생성
            craft_content = self.report_gen.generate_craft_content(today_articles)
            craft_path = Path(report_path).parent / f"craft_{date.today().strftime('%Y%m%d')}.md"
            with open(craft_path, 'w', encoding='utf-8') as f:
                f.write(craft_content)
            logger.info(f"   → Craft용 콘텐츠: {craft_path}")
        
        # 결과 요약
        logger.info("\n" + "=" * 60)
        logger.info("✅ 완료!")
        stats = self.db.get_stats()
        logger.info(f"   총 저장 논문: {stats['total_articles']}편")
        logger.info(f"   오늘 수집: {new_count}편")
        logger.info(f"   높은 관심도: {stats['high_priority']}편")
        logger.info("=" * 60)
        
        return {
            'total': len(articles),
            'new': new_count,
            'stats': stats
        }
    
    def show_stats(self):
        """통계 출력"""
        stats = self.db.get_stats()
        
        print("\n📊 Journal Monitor 통계")
        print("=" * 40)
        print(f"총 저널 수:        {stats['total_journals']}개")
        print(f"총 논문 수:        {stats['total_articles']}편")
        print(f"높은 관심도:       {stats['high_priority']}편")
        print(f"최근 24시간:       {stats['articles_24h']}편")
        print(f"최근 7일:          {stats['articles_7d']}편")
        print("=" * 40)
    
    def get_craft_content(self, target_date: date = None) -> str:
        """특정 날짜의 Craft용 콘텐츠 반환"""
        if target_date is None:
            target_date = date.today()
        
        articles = self.db.get_articles_by_date(target_date.isoformat())
        
        if not articles:
            return f"## 📚 학술저널 브리핑\n{target_date} - 수집된 논문이 없습니다."
        
        return self.report_gen.generate_craft_content(articles, target_date)


def main():
    """CLI 엔트리포인트"""
    parser = argparse.ArgumentParser(
        description='케이의 학술저널 RSS 모니터링 시스템',
        formatter_class=argparse.RawDescriptionHelpFormatter,
        epilog="""
예시:
    python main.py                    # 기본 실행
    python main.py --hours 48         # 48시간 내 논문 수집
    python main.py --no-translate     # 번역 없이 수집만
    python main.py --stats            # 통계 확인
    python main.py --craft            # Craft용 콘텐츠 출력
        """
    )
    
    parser.add_argument('--config', '-c', type=str, 
                        help='설정 파일 경로')
    parser.add_argument('--hours', '-H', type=int, default=24,
                        help='수집할 시간 범위 (기본: 24)')
    parser.add_argument('--no-translate', action='store_true',
                        help='번역 없이 수집만')
    parser.add_argument('--all-feeds', action='store_true',
                        help='모든 피드 수집 (학술 외 포함)')
    parser.add_argument('--stats', action='store_true',
                        help='통계만 출력')
    parser.add_argument('--craft', action='store_true',
                        help='Craft용 콘텐츠 출력')
    
    args = parser.parse_args()
    
    try:
        monitor = JournalMonitor(config_path=args.config)
        
        if args.stats:
            monitor.show_stats()
        elif args.craft:
            content = monitor.get_craft_content()
            print(content)
        else:
            monitor.run(
                hours=args.hours,
                translate=not args.no_translate,
                academic_only=not args.all_feeds
            )
    
    except KeyboardInterrupt:
        print("\n중단됨")
        sys.exit(1)
    except Exception as e:
        logger.error(f"오류 발생: {e}")
        raise


if __name__ == "__main__":
    main()
