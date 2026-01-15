"""
report_generator.py - 마크다운 보고서 생성 모듈
케이의 학술저널 RSS 모니터링 시스템
"""

from pathlib import Path
from datetime import datetime, date
from typing import List, Dict, Optional
from collections import defaultdict
import logging
import yaml
import re

try:
    from jinja2 import Environment, FileSystemLoader, BaseLoader
except ImportError:
    print("jinja2 패키지를 설치해주세요: pip install jinja2")
    raise

logging.basicConfig(level=logging.INFO)
logger = logging.getLogger(__name__)


# 인라인 템플릿 (외부 파일 없이도 동작)
DEFAULT_TEMPLATE = '''# 📚 학술저널 일일 브리핑
**{{ report_date }}** | 총 **{{ total_count }}**편 수집

---

{% if high_priority_articles %}
## 🔴 높은 관심도 ({{ high_priority_articles|length }}편)
{% for article in high_priority_articles %}
### {{ loop.index }}. {{ article.title_ko or article.title }}

{% if article.title_ko %}
> **원제:** {{ article.title }}
{% endif %}

- **저널:** {{ article.journal_name }}
- **저자:** {{ article.authors or '정보 없음' }}
{% if article.keywords_matched %}
- **🏷️ 키워드:** {{ article.keywords_matched|join(', ') }}
{% endif %}
- **🔗 링크:** [원문 보기]({{ article.url }})

{% if article.summary_ko %}
**📝 요약:** {{ article.summary_ko }}
{% endif %}

{% if article.abstract_ko %}
<details>
<summary>전체 초록 번역</summary>

{{ article.abstract_ko }}

</details>
{% endif %}

---

{% endfor %}
{% endif %}

{% if medium_priority_articles %}
## 🟡 중간 관심도 ({{ medium_priority_articles|length }}편)
{% for article in medium_priority_articles %}
### {{ loop.index }}. {{ article.title_ko or article.title }}

- **저널:** {{ article.journal_name }}
{% if article.keywords_matched %}
- **🏷️ 키워드:** {{ article.keywords_matched|join(', ') }}
{% endif %}
- **🔗 링크:** [원문 보기]({{ article.url }})

{% if article.summary_ko %}
{{ article.summary_ko }}
{% endif %}

---

{% endfor %}
{% endif %}

{% if normal_articles %}
## 📋 기타 논문 ({{ normal_articles|length }}편)

| 저널 | 제목 | 링크 |
|------|------|------|
{% for article in normal_articles %}
| {{ article.journal_name }} | {{ (article.title_ko or article.title)[:60] }}{% if (article.title_ko or article.title)|length > 60 %}...{% endif %} | [보기]({{ article.url }}) |
{% endfor %}

{% endif %}

---

## 📊 저널별 통계

| 카테고리 | 저널명 | 수집 |
|----------|--------|------|
{% for journal, count in journal_stats.items() %}
| {{ journal_categories.get(journal, '-') }} | {{ journal }} | {{ count }}편 |
{% endfor %}

---

*이 보고서는 Journal Monitor에 의해 자동 생성되었습니다.*
*생성 시각: {{ generated_at }}*
'''


class ReportGenerator:
    """마크다운 보고서 생성기"""
    
    def __init__(self, template_dir: str = None, output_dir: str = None, config_path: str = None):
        """
        초기화
        
        Args:
            template_dir: 템플릿 디렉토리 경로
            output_dir: 출력 디렉토리 경로
            config_path: config.yaml 경로
        """
        self.output_dir = Path(output_dir) if output_dir else Path('./reports')
        self.output_dir.mkdir(parents=True, exist_ok=True)
        
        # 템플릿 설정
        if template_dir and Path(template_dir).exists():
            template_path = Path(template_dir) / 'daily_report.md.j2'
            if template_path.exists():
                env = Environment(loader=FileSystemLoader(template_dir))
                self.template = env.get_template('daily_report.md.j2')
            else:
                env = Environment(loader=BaseLoader())
                self.template = env.from_string(DEFAULT_TEMPLATE)
        else:
            env = Environment(loader=BaseLoader())
            self.template = env.from_string(DEFAULT_TEMPLATE)
        
        # 키워드 로드
        self.keywords = self._load_keywords(config_path)
    
    def _load_keywords(self, config_path: str = None) -> Dict[str, List[str]]:
        """config.yaml에서 키워드 로드"""
        keywords = {
            'high': [],
            'medium': []
        }
        
        # config.yaml 찾기
        if config_path:
            config_file = Path(config_path)
        else:
            # 여러 위치 시도
            possible_paths = [
                Path('./config.yaml'),
                Path('../config.yaml'),
                Path(__file__).parent.parent / 'config.yaml'
            ]
            config_file = None
            for p in possible_paths:
                if p.exists():
                    config_file = p
                    break
        
        if config_file and config_file.exists():
            try:
                with open(config_file, 'r', encoding='utf-8') as f:
                    config = yaml.safe_load(f)
                
                if 'keywords' in config:
                    keywords['high'] = config['keywords'].get('priority_high', [])
                    keywords['medium'] = config['keywords'].get('priority_medium', [])
                    logger.info(f"Loaded {len(keywords['high'])} high, {len(keywords['medium'])} medium keywords")
            except Exception as e:
                logger.warning(f"Failed to load keywords: {e}")
        
        return keywords
    
    def _match_keywords(self, article: Dict) -> List[str]:
        """논문에서 키워드 매칭"""
        matched = []
        
        # 검색 대상 텍스트
        title = (article.get('title', '') + ' ' + article.get('title_ko', '')).lower()
        abstract = (article.get('abstract', '') + ' ' + article.get('abstract_ko', '')).lower()
        text = title + ' ' + abstract
        
        # 모든 키워드에서 매칭
        all_keywords = self.keywords['high'] + self.keywords['medium']
        
        for keyword in all_keywords:
            # 대소문자 무시 매칭
            if keyword.lower() in text:
                matched.append(keyword)
        
        return matched
    
    def _categorize_articles(self, articles: List[Dict]) -> Dict[str, List[Dict]]:
        """우선순위별 논문 분류 + 키워드 매칭"""
        categorized = {
            'high': [],
            'medium': [],
            'normal': []
        }
        
        for article in articles:
            # 키워드 매칭 추가
            article['keywords_matched'] = self._match_keywords(article)
            
            priority = article.get('priority', 'normal')
            if priority in categorized:
                categorized[priority].append(article)
            else:
                categorized['normal'].append(article)
        
        return categorized
    
    def _get_journal_stats(self, articles: List[Dict]) -> Dict[str, int]:
        """저널별 통계"""
        stats = defaultdict(int)
        for article in articles:
            journal = article.get('journal_name', 'Unknown')
            stats[journal] += 1
        return dict(sorted(stats.items(), key=lambda x: x[1], reverse=True))
    
    def _get_journal_categories(self, articles: List[Dict]) -> Dict[str, str]:
        """저널-카테고리 매핑"""
        mapping = {}
        for article in articles:
            journal = article.get('journal_name', 'Unknown')
            category = article.get('category', '-')
            if journal not in mapping:
                mapping[journal] = category
        return mapping
    
    def generate_report(self, articles: List[Dict], 
                        report_date: date = None) -> str:
        """
        마크다운 보고서 생성
        
        Args:
            articles: 논문 리스트
            report_date: 보고서 날짜 (None이면 오늘)
            
        Returns:
            생성된 보고서 파일 경로
        """
        if report_date is None:
            report_date = date.today()
        
        # 논문 분류 (키워드 매칭 포함)
        categorized = self._categorize_articles(articles)
        
        # 템플릿 렌더링
        report_content = self.template.render(
            report_date=report_date.strftime('%Y년 %m월 %d일'),
            total_count=len(articles),
            high_priority_articles=categorized['high'],
            medium_priority_articles=categorized['medium'],
            normal_articles=categorized['normal'],
            journal_stats=self._get_journal_stats(articles),
            journal_categories=self._get_journal_categories(articles),
            generated_at=datetime.now().strftime('%Y-%m-%d %H:%M:%S')
        )
        
        # 파일 저장
        filename = f"journal_brief_{report_date.strftime('%Y%m%d')}.md"
        filepath = self.output_dir / filename
        
        with open(filepath, 'w', encoding='utf-8') as f:
            f.write(report_content)
        
        logger.info(f"Report saved: {filepath}")
        
        return str(filepath)
    
    def generate_craft_content(self, articles: List[Dict], 
                               report_date: date = None) -> str:
        """
        Craft Daily Note용 간결한 콘텐츠 생성
        """
        if report_date is None:
            report_date = date.today()
        
        # 논문 분류 (키워드 매칭 포함)
        categorized = self._categorize_articles(articles)
        
        lines = []
        lines.append(f"## 📚 학술저널 브리핑")
        lines.append(f"총 {len(articles)}편 수집\n")
        
        # 높은 관심도 상세 표시
        if categorized['high']:
            lines.append(f"### 🔴 높은 관심도 ({len(categorized['high'])}편)")
            for article in categorized['high']:
                title = article.get('title_ko') or article.get('title', '')
                journal = article.get('journal_name', '')
                url = article.get('url', '')
                summary = article.get('summary_ko', '')
                keywords = article.get('keywords_matched', [])
                
                lines.append(f"- **[{title[:50]}{'...' if len(title) > 50 else ''}]({url})**")
                lines.append(f"  - 저널: {journal}")
                if keywords:
                    lines.append(f"  - 키워드: {', '.join(keywords)}")
                if summary:
                    lines.append(f"  - {summary[:100]}{'...' if len(summary) > 100 else ''}")
                lines.append("")
        
        # 중간 관심도 간략하게
        if categorized['medium']:
            lines.append(f"### 🟡 중간 관심도 ({len(categorized['medium'])}편)")
            for article in categorized['medium'][:5]:
                title = article.get('title_ko') or article.get('title', '')
                url = article.get('url', '')
                lines.append(f"- [{title[:40]}{'...' if len(title) > 40 else ''}]({url})")
            if len(categorized['medium']) > 5:
                lines.append(f"- ... 외 {len(categorized['medium']) - 5}편")
            lines.append("")
        
        # 기타
        if categorized['normal']:
            lines.append(f"### 📋 기타: {len(categorized['normal'])}편")
        
        return '\n'.join(lines)
    
    def get_report_summary(self, articles: List[Dict]) -> Dict:
        """보고서 요약 통계"""
        categorized = self._categorize_articles(articles)
        
        return {
            'total': len(articles),
            'high_priority': len(categorized['high']),
            'medium_priority': len(categorized['medium']),
            'normal': len(categorized['normal']),
            'journals_count': len(set(a.get('journal_name') for a in articles))
        }


if __name__ == "__main__":
    # 테스트
    test_articles = [
        {
            'title': 'Governing through Infrastructure',
            'title_ko': '인프라를 통한 통치',
            'journal_name': 'Environment and Planning D',
            'category': 'Academic: Geography Journals',
            'authors': 'Smith, J.',
            'url': 'https://example.com/1',
            'summary_ko': '이 논문은 도시 인프라가 어떻게 통치의 도구가 되는지 분석합니다.',
            'priority': 'high'
        },
        {
            'title': 'Urban Planning in Seoul',
            'title_ko': '서울의 도시계획',
            'journal_name': 'Planning Perspectives',
            'category': 'Academic: Planning Studies',
            'authors': 'Kim, S.',
            'url': 'https://example.com/2',
            'summary_ko': '서울의 도시계획 역사를 분석합니다.',
            'priority': 'medium'
        }
    ]
    
    generator = ReportGenerator(output_dir='./test_reports')
    report_path = generator.generate_report(test_articles)
    print(f"Test report: {report_path}")
