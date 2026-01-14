"""
summarizer.py - Claude API 번역/요약 모듈
케이의 학술저널 RSS 모니터링 시스템
"""

import os
from typing import Dict, List, Optional, Tuple
from dataclasses import dataclass
import logging
import re

try:
    import anthropic
except ImportError:
    print("anthropic 패키지를 설치해주세요: pip install anthropic")
    raise

logging.basicConfig(level=logging.INFO)
logger = logging.getLogger(__name__)


@dataclass
class TranslationResult:
    """번역 결과 데이터 클래스"""
    title_ko: str
    abstract_ko: str
    summary_ko: str
    priority: str
    keywords_matched: List[str]


class Summarizer:
    """Claude API를 사용한 번역/요약 클래스"""
    
    def __init__(self, api_key: str = None, model: str = "claude-sonnet-4-20250514"):
        """
        번역기 초기화
        
        Args:
            api_key: Anthropic API 키 (None이면 환경변수에서)
            model: 사용할 Claude 모델
        """
        self.api_key = api_key or os.environ.get('ANTHROPIC_API_KEY')
        if not self.api_key:
            raise ValueError("ANTHROPIC_API_KEY가 필요합니다")
        
        self.client = anthropic.Anthropic(api_key=self.api_key)
        self.model = model
        
        # 우선순위 키워드 설정
        self.priority_keywords = {
            'high': [
                'governmentality', '통치성', 'assemblage', '어셈블리지',
                'new materialism', '신유물론', 'foucault', '푸코',
                'deleuze', '들뢰즈', 'guattari', '가타리',
                'lefebvre', '르페브르', 'urban politics', '도시정치',
                'housing financialization', '주거 금융화', 'gentrification', '젠트리피케이션',
                'displacement', '축출', 'dispossession', '탈취',
                'biopolitics', '생명정치', 'necropolitics', '죽음정치',
                'territory', '영토', 'territoriality', '영토성'
            ],
            'medium': [
                'urban planning', '도시계획', 'political geography', '정치지리',
                'spatial', '공간', 'mobility', '이동성', 'infrastructure', '인프라',
                'housing', '주거', 'rent', '임대', 'property', '재산',
                'neoliberal', '신자유주의', 'accumulation', '축적',
                'state', '국가', 'governance', '거버넌스', 'planning theory', '계획이론'
            ]
        }
    
    def _check_priority(self, title: str, abstract: str) -> Tuple[str, List[str]]:
        """
        키워드 기반 우선순위 판별
        
        Returns:
            (priority, matched_keywords)
        """
        text = f"{title} {abstract}".lower()
        matched = []
        
        # 높은 우선순위 키워드 체크
        for kw in self.priority_keywords['high']:
            if kw.lower() in text:
                matched.append(kw)
        
        if matched:
            return 'high', matched
        
        # 중간 우선순위 키워드 체크
        for kw in self.priority_keywords['medium']:
            if kw.lower() in text:
                matched.append(kw)
        
        if matched:
            return 'medium', matched
        
        return 'normal', []
    
    def translate_and_summarize(self, article: Dict) -> TranslationResult:
        """
        논문 제목/초록 번역 및 요약
        
        Args:
            article: 논문 정보 딕셔너리
            
        Returns:
            TranslationResult
        """
        title = article.get('title', '')
        abstract = article.get('abstract', '')
        
        # 우선순위 체크
        priority, keywords_matched = self._check_priority(title, abstract)
        
        # 초록이 없거나 너무 짧으면 간단 번역만
        if not abstract or len(abstract) < 50:
            title_ko = self._translate_title(title)
            return TranslationResult(
                title_ko=title_ko,
                abstract_ko="",
                summary_ko="(초록 없음)",
                priority=priority,
                keywords_matched=keywords_matched
            )
        
        # Claude API로 번역 및 요약
        try:
            result = self._call_claude_api(title, abstract)
            result.priority = priority
            result.keywords_matched = keywords_matched
            return result
            
        except Exception as e:
            logger.error(f"API 호출 실패: {e}")
            # 폴백: 제목만 간단 번역
            return TranslationResult(
                title_ko=self._translate_title(title),
                abstract_ko="(번역 실패)",
                summary_ko="(요약 실패)",
                priority=priority,
                keywords_matched=keywords_matched
            )
    
    def _translate_title(self, title: str) -> str:
        """제목만 간단 번역"""
        try:
            response = self.client.messages.create(
                model=self.model,
                max_tokens=200,
                messages=[{
                    "role": "user",
                    "content": f"다음 학술 논문 제목을 한국어로 번역해주세요. 번역만 출력하세요.\n\n{title}"
                }]
            )
            return response.content[0].text.strip()
        except:
            return title  # 실패 시 원본 반환
    
    def _call_claude_api(self, title: str, abstract: str) -> TranslationResult:
        """
        Claude API 호출하여 번역 및 요약 수행
        """
        prompt = f"""당신은 인문지리학과 도시연구를 전공하는 한국인 연구자를 위한 학술 조교입니다.
다음 영어 학술 논문의 제목과 초록을 분석해주세요.

## 논문 정보
제목: {title}

초록: {abstract}

## 요청사항
아래 형식으로 정확히 응답해주세요:

[제목 번역]
(학술적으로 정확한 한국어 번역)

[초록 번역]  
(자연스러운 한국어 번역, 전문용어는 적절히 처리)

[핵심 요약]
(2-3문장으로 핵심 논점, 방법론, 주요 발견을 요약. 연구자가 읽을 가치가 있는지 판단할 수 있도록)

응답은 위 형식만 포함해주세요."""

        response = self.client.messages.create(
            model=self.model,
            max_tokens=1500,
            messages=[{"role": "user", "content": prompt}]
        )
        
        return self._parse_response(response.content[0].text)
    
    def _parse_response(self, response_text: str) -> TranslationResult:
        """API 응답 파싱"""
        title_ko = ""
        abstract_ko = ""
        summary_ko = ""
        
        # 정규식으로 각 섹션 추출
        title_match = re.search(r'\[제목 번역\]\s*\n(.+?)(?=\n\[|\Z)', response_text, re.DOTALL)
        abstract_match = re.search(r'\[초록 번역\]\s*\n(.+?)(?=\n\[|\Z)', response_text, re.DOTALL)
        summary_match = re.search(r'\[핵심 요약\]\s*\n(.+?)(?=\n\[|\Z)', response_text, re.DOTALL)
        
        if title_match:
            title_ko = title_match.group(1).strip()
        if abstract_match:
            abstract_ko = abstract_match.group(1).strip()
        if summary_match:
            summary_ko = summary_match.group(1).strip()
        
        return TranslationResult(
            title_ko=title_ko,
            abstract_ko=abstract_ko,
            summary_ko=summary_ko,
            priority='normal',  # 나중에 설정됨
            keywords_matched=[]
        )
    
    def batch_translate(self, articles: List[Dict], 
                        progress_callback=None) -> List[Dict]:
        """
        여러 논문 일괄 번역
        
        Args:
            articles: 논문 리스트
            progress_callback: 진행상황 콜백 함수 (current, total)
            
        Returns:
            번역 정보가 추가된 논문 리스트
        """
        results = []
        total = len(articles)
        
        for i, article in enumerate(articles, 1):
            logger.info(f"[{i}/{total}] Translating: {article.get('title', '')[:50]}...")
            
            try:
                translation = self.translate_and_summarize(article)
                
                article['title_ko'] = translation.title_ko
                article['abstract_ko'] = translation.abstract_ko
                article['summary_ko'] = translation.summary_ko
                article['priority'] = translation.priority
                article['keywords_matched'] = translation.keywords_matched
                
            except Exception as e:
                logger.error(f"번역 실패: {e}")
                article['title_ko'] = article.get('title', '')
                article['abstract_ko'] = ""
                article['summary_ko'] = "(번역 실패)"
                article['priority'] = 'normal'
                article['keywords_matched'] = []
            
            results.append(article)
            
            if progress_callback:
                progress_callback(i, total)
        
        return results
    
    def update_priority_keywords(self, high: List[str] = None, 
                                  medium: List[str] = None):
        """우선순위 키워드 업데이트"""
        if high:
            self.priority_keywords['high'].extend(high)
        if medium:
            self.priority_keywords['medium'].extend(medium)


if __name__ == "__main__":
    # 테스트
    summarizer = Summarizer()
    
    test_article = {
        'title': 'Governing through Infrastructure: The Politics of Urban Assemblages',
        'abstract': '''This paper examines how urban governance operates through 
        infrastructural assemblages, drawing on Foucault's concept of governmentality 
        and Deleuze and Guattari's assemblage theory. Through a case study of 
        Seoul's smart city initiatives, we analyze how technical systems become 
        enrolled in the production of governable subjects and spaces.'''
    }
    
    result = summarizer.translate_and_summarize(test_article)
    print(f"제목: {result.title_ko}")
    print(f"요약: {result.summary_ko}")
    print(f"우선순위: {result.priority}")
    print(f"매칭 키워드: {result.keywords_matched}")
