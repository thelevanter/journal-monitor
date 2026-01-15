"""
📚 Journal Monitor Dashboard
케이의 학술논문 모니터링 대시보드
"""

import streamlit as st
import streamlit.components.v1 as components
import sqlite3
import pandas as pd
from pathlib import Path
from datetime import datetime, timedelta
import plotly.express as px
import plotly.graph_objects as go
import yaml
import json
import networkx as nx
from pyvis.network import Network
import tempfile
import os
import re

# 토픽 클러스터링
from sklearn.feature_extraction.text import TfidfVectorizer
from sklearn.cluster import KMeans
from sklearn.decomposition import PCA

# 지도 시각화
try:
    import folium
    from streamlit_folium import folium_static
    FOLIUM_AVAILABLE = True
except ImportError:
    FOLIUM_AVAILABLE = False

# Claude API
try:
    from anthropic import Anthropic
    ANTHROPIC_AVAILABLE = True
except ImportError:
    ANTHROPIC_AVAILABLE = False

# 페이지 설정
st.set_page_config(
    page_title="Journal Monitor",
    page_icon="📚",
    layout="wide",
    initial_sidebar_state="expanded"
)

# CSS 스타일
st.markdown("""
<style>
    .priority-high { color: #ff4b4b; font-weight: bold; }
    .priority-medium { color: #ffa500; font-weight: bold; }
    .priority-low { color: #808080; }
    .metric-card {
        background-color: #f0f2f6;
        padding: 20px;
        border-radius: 10px;
        text-align: center;
    }
    .article-card {
        padding: 15px;
        border-left: 4px solid #ccc;
        margin-bottom: 10px;
        background-color: #fafafa;
        border-radius: 0 8px 8px 0;
    }
    .article-card.high { border-left-color: #ff4b4b; }
    .article-card.medium { border-left-color: #ffa500; }
    .article-card.low { border-left-color: #808080; }
    
    /* 키워드 태그 스타일 */
    .keyword-tag {
        display: inline-block;
        padding: 4px 12px;
        margin: 3px;
        border-radius: 15px;
        font-size: 14px;
        font-weight: 500;
    }
    .keyword-tag.high {
        background: linear-gradient(135deg, #ff6b6b, #ee5a5a);
        color: white;
    }
    .keyword-tag.medium {
        background: linear-gradient(135deg, #ffc048, #ffb020);
        color: #333;
    }
    .keyword-tag.count-1 { font-size: 12px; opacity: 0.7; }
    .keyword-tag.count-2 { font-size: 13px; opacity: 0.8; }
    .keyword-tag.count-3 { font-size: 14px; opacity: 0.9; }
    .keyword-tag.count-4 { font-size: 15px; }
    .keyword-tag.count-5 { font-size: 16px; font-weight: 600; }
    
    /* 키워드 컨테이너 */
    .keyword-container {
        background: linear-gradient(135deg, #667eea 0%, #764ba2 100%);
        padding: 20px;
        border-radius: 15px;
        margin-bottom: 20px;
    }
    .keyword-container h4 {
        color: white;
        margin-bottom: 15px;
    }
    .keyword-badges {
        display: flex;
        flex-wrap: wrap;
        gap: 8px;
    }
    .keyword-badge {
        background: rgba(255,255,255,0.9);
        color: #333;
        padding: 6px 14px;
        border-radius: 20px;
        font-size: 13px;
        font-weight: 500;
        display: inline-flex;
        align-items: center;
        gap: 6px;
    }
    .keyword-badge .count {
        background: #667eea;
        color: white;
        padding: 2px 8px;
        border-radius: 10px;
        font-size: 11px;
        font-weight: 600;
    }
</style>
""", unsafe_allow_html=True)


class DashboardDB:
    """대시보드용 데이터베이스 연결"""
    
    def __init__(self, db_path: str):
        self.db_path = db_path
    
    def get_connection(self):
        return sqlite3.connect(self.db_path)
    
    def get_stats(self) -> dict:
        """전체 통계"""
        with self.get_connection() as conn:
            cursor = conn.cursor()
            
            # 전체 논문 수
            cursor.execute("SELECT COUNT(*) FROM articles")
            total = cursor.fetchone()[0]
            
            # 우선순위별
            cursor.execute("SELECT COUNT(*) FROM articles WHERE priority = 'high'")
            high = cursor.fetchone()[0]
            
            cursor.execute("SELECT COUNT(*) FROM articles WHERE priority = 'medium'")
            medium = cursor.fetchone()[0]
            
            # 오늘 수집
            today = datetime.now().strftime('%Y-%m-%d')
            cursor.execute("SELECT COUNT(*) FROM articles WHERE DATE(fetched_at) = ?", (today,))
            today_count = cursor.fetchone()[0]
            
            # 이번 주
            week_ago = (datetime.now() - timedelta(days=7)).strftime('%Y-%m-%d')
            cursor.execute("SELECT COUNT(*) FROM articles WHERE DATE(fetched_at) >= ?", (week_ago,))
            week_count = cursor.fetchone()[0]
            
            # 초록 있는 논문
            cursor.execute("SELECT COUNT(*) FROM articles WHERE abstract IS NOT NULL AND LENGTH(abstract) > 50")
            with_abstract = cursor.fetchone()[0]
            
            return {
                'total': total,
                'high': high,
                'medium': medium,
                'low': total - high - medium,
                'today': today_count,
                'week': week_count,
                'with_abstract': with_abstract
            }
    
    def get_articles(self, priority: str = None, journal: str = None, 
                     days: int = None, search: str = None, 
                     starred_only: bool = False, unread_only: bool = False,
                     limit: int = 100) -> pd.DataFrame:
        """논문 목록 조회"""
        query = """
            SELECT 
                a.id,
                a.title,
                a.title_ko,
                a.abstract,
                a.abstract_ko,
                a.summary_ko,
                a.url,
                a.doi,
                a.priority,
                a.keywords_matched,
                a.fetched_at,
                a.published_date,
                a.is_read,
                a.is_starred,
                j.name as journal_name,
                j.category
            FROM articles a
            LEFT JOIN journals j ON a.journal_id = j.id
            WHERE 1=1
        """
        params = []
        
        if priority and priority != "전체":
            query += " AND a.priority = ?"
            params.append(priority.lower())
        
        if journal and journal != "전체":
            query += " AND j.name = ?"
            params.append(journal)
        
        if days:
            date_from = (datetime.now() - timedelta(days=days)).strftime('%Y-%m-%d')
            query += " AND DATE(a.fetched_at) >= ?"
            params.append(date_from)
        
        if search:
            query += " AND (a.title LIKE ? OR a.abstract LIKE ? OR a.title_ko LIKE ? OR a.keywords_matched LIKE ?)"
            search_term = f"%{search}%"
            params.extend([search_term, search_term, search_term, search_term])
        
        if starred_only:
            query += " AND a.is_starred = 1"
        
        if unread_only:
            query += " AND a.is_read = 0"
        
        query += " ORDER BY a.fetched_at DESC LIMIT ?"
        params.append(limit)
        
        with self.get_connection() as conn:
            df = pd.read_sql_query(query, conn, params=params)
        
        return df
    
    def get_journals(self) -> list:
        """저널 목록"""
        with self.get_connection() as conn:
            cursor = conn.cursor()
            cursor.execute("SELECT DISTINCT name FROM journals ORDER BY name")
            return [row[0] for row in cursor.fetchall()]
    
    def get_daily_counts(self, days: int = 30) -> pd.DataFrame:
        """일별 수집 현황"""
        date_from = (datetime.now() - timedelta(days=days)).strftime('%Y-%m-%d')
        
        query = """
            SELECT 
                DATE(fetched_at) as date,
                COUNT(*) as count,
                SUM(CASE WHEN priority = 'high' THEN 1 ELSE 0 END) as high,
                SUM(CASE WHEN priority = 'medium' THEN 1 ELSE 0 END) as medium
            FROM articles
            WHERE DATE(fetched_at) >= ?
            GROUP BY DATE(fetched_at)
            ORDER BY date
        """
        
        with self.get_connection() as conn:
            df = pd.read_sql_query(query, conn, params=[date_from])
        
        return df
    
    def get_journal_distribution(self) -> pd.DataFrame:
        """저널별 분포"""
        query = """
            SELECT 
                j.name as journal,
                COUNT(*) as count,
                SUM(CASE WHEN a.priority = 'high' THEN 1 ELSE 0 END) as high,
                SUM(CASE WHEN a.priority = 'medium' THEN 1 ELSE 0 END) as medium
            FROM articles a
            LEFT JOIN journals j ON a.journal_id = j.id
            GROUP BY j.name
            ORDER BY count DESC
            LIMIT 20
        """
        
        with self.get_connection() as conn:
            df = pd.read_sql_query(query, conn)
        
        return df
    
    def get_keyword_stats(self, days: int = None) -> pd.DataFrame:
        """키워드 통계 (기간 필터 옵션)"""
        if days:
            date_from = (datetime.now() - timedelta(days=days)).strftime('%Y-%m-%d')
            query = """
                SELECT keywords_matched, priority
                FROM articles
                WHERE keywords_matched IS NOT NULL 
                  AND keywords_matched != ''
                  AND DATE(fetched_at) >= ?
            """
            params = [date_from]
        else:
            query = """
                SELECT keywords_matched, priority
                FROM articles
                WHERE keywords_matched IS NOT NULL AND keywords_matched != ''
            """
            params = []
        
        with self.get_connection() as conn:
            df = pd.read_sql_query(query, conn, params=params)
        
        # 키워드 파싱 및 집계
        keyword_counts = {}
        keyword_priorities = {}  # 키워드별 최고 우선순위 추적
        
        for _, row in df.iterrows():
            keywords = row['keywords_matched']
            priority = row['priority']
            if keywords:
                try:
                    kw_list = json.loads(keywords)
                    if isinstance(kw_list, list):
                        for kw in kw_list:
                            kw = str(kw).strip()
                            if kw:
                                keyword_counts[kw] = keyword_counts.get(kw, 0) + 1
                                # high가 medium보다 우선
                                if kw not in keyword_priorities or priority == 'high':
                                    keyword_priorities[kw] = priority
                except (json.JSONDecodeError, TypeError):
                    for kw in keywords.split(','):
                        kw = kw.strip()
                        if kw:
                            keyword_counts[kw] = keyword_counts.get(kw, 0) + 1
                            if kw not in keyword_priorities or priority == 'high':
                                keyword_priorities[kw] = priority
        
        result = pd.DataFrame([
            {'keyword': k, 'count': v, 'priority': keyword_priorities.get(k, 'normal')} 
            for k, v in sorted(keyword_counts.items(), key=lambda x: -x[1])
        ])
        
        return result
    
    def get_today_keywords(self) -> pd.DataFrame:
        """오늘 수집된 논문의 키워드 통계"""
        return self.get_keyword_stats(days=1)
    
    def mark_as_read(self, article_id: int):
        """읽음 표시"""
        with self.get_connection() as conn:
            cursor = conn.cursor()
            cursor.execute(
                "UPDATE articles SET is_read = 1 WHERE id = ?",
                (article_id,)
            )
            conn.commit()
    
    def toggle_starred(self, article_id: int):
        """즐겨찾기 토글"""
        with self.get_connection() as conn:
            cursor = conn.cursor()
            cursor.execute(
                "UPDATE articles SET is_starred = CASE WHEN is_starred = 1 THEN 0 ELSE 1 END WHERE id = ?",
                (article_id,)
            )
            conn.commit()
    
    def toggle_read(self, article_id: int):
        """읽음 표시 토글"""
        with self.get_connection() as conn:
            cursor = conn.cursor()
            cursor.execute(
                "UPDATE articles SET is_read = CASE WHEN is_read = 1 THEN 0 ELSE 1 END WHERE id = ?",
                (article_id,)
            )
            conn.commit()


def load_config() -> dict:
    """config.yaml 로드"""
    config_path = Path("./config.yaml")
    if config_path.exists():
        with open(config_path, 'r', encoding='utf-8') as f:
            return yaml.safe_load(f)
    return {}


def save_config(config: dict):
    """config.yaml 저장"""
    config_path = Path("./config.yaml")
    with open(config_path, 'w', encoding='utf-8') as f:
        yaml.dump(config, f, allow_unicode=True, default_flow_style=False, sort_keys=False)


def render_article_card(article: pd.Series, db: 'DashboardDB' = None):
    """논문 카드 렌더링"""
    priority = article.get('priority', 'normal') or 'normal'
    priority_emoji = {'high': '🔴', 'medium': '🟡', 'normal': '⚪', 'low': '⚪'}.get(priority, '⚪')
    
    title_en = article.get('title', 'No Title')
    title_ko = article.get('title_ko', '')
    
    if title_ko:
        display_title = f"{title_ko} ({title_en})"
    else:
        display_title = title_en
    
    journal = article.get('journal_name', 'Unknown')
    fetched = article.get('fetched_at', '')[:10] if article.get('fetched_at') else ''
    
    keywords = article.get('keywords_matched', '')
    if keywords:
        try:
            kw_list = json.loads(keywords)
            if isinstance(kw_list, list):
                keywords = ', '.join(kw_list)
        except:
            pass
    
    # 상태 확인
    article_id = article.get('id')
    is_starred = bool(article.get('is_starred', 0))
    is_read = bool(article.get('is_read', 0))
    
    with st.container():
        col1, col2, col3, col4 = st.columns([0.85, 0.05, 0.05, 0.05])
        
        with col1:
            # 제목에 읽음 표시 반영
            read_style = "" if not is_read else "~~"
            star_mark = "⭐ " if is_starred else ""
            st.markdown(f"### {star_mark}{priority_emoji} {display_title}")
            st.caption(f"📰 {journal} · 📅 {fetched}{' · ✅ 읽음' if is_read else ''}")
            
            if keywords:
                st.markdown(f"🏷️ `{keywords}`")
        
        with col2:
            # 즐겨찾기 버튼
            star_icon = "⭐" if is_starred else "☆"
            if st.button(star_icon, key=f"star_{article_id}", help="즐겨찾기 토글"):
                if db:
                    db.toggle_starred(article_id)
                    st.rerun()
        
        with col3:
            # 읽음 표시 버튼
            read_icon = "✅" if is_read else "☐"
            if st.button(read_icon, key=f"read_{article_id}", help="읽음 표시 토글"):
                if db:
                    db.toggle_read(article_id)
                    st.rerun()
        
        with col4:
            if article.get('url'):
                st.link_button("🔗", article['url'], help="원문 보기")
        
        abstract_en = article.get('abstract', '')
        abstract_ko = article.get('abstract_ko', '')
        summary_ko = article.get('summary_ko', '')
        
        if abstract_en or abstract_ko or summary_ko:
            with st.expander("📄 상세 보기"):
                if summary_ko:
                    st.markdown("**💡 요약:**")
                    st.markdown(summary_ko)
                    st.divider()
                
                if abstract_en:
                    st.markdown("**📝 Abstract (영문):**")
                    st.markdown(abstract_en)
                
                if abstract_ko:
                    st.markdown("")
                    st.markdown("**📝 초록 (한국어 번역):**")
                    st.markdown(abstract_ko)
                
                if article.get('doi'):
                    st.divider()
                    doi = article['doi']
                    doi_url = f"https://doi.org/{doi}" if not doi.startswith('http') else doi
                    st.markdown(f"**DOI:** [{doi}]({doi_url})")
        
        st.divider()


def render_today_keywords(db: DashboardDB):
    """오늘의 키워드 인포그래픽 - Streamlit 네이티브 버전"""
    today_kw = db.get_today_keywords()
    
    if today_kw.empty:
        st.info("오늘 수집된 논문에서 매칭된 키워드가 없습니다.")
        return
    
    # 상위 12개 키워드
    top_keywords = today_kw.head(12)
    
    col1, col2 = st.columns([1, 1])
    
    with col1:
        st.markdown("#### 🏷️ 키워드 태그")
        st.caption("클릭하면 해당 키워드 논문 목록으로 이동")
        
        # 4열로 키워드 버튼 배치
        kw_cols = st.columns(4)
        
        for i, (_, row) in enumerate(top_keywords.iterrows()):
            kw = row['keyword']
            count = row['count']
            priority = row.get('priority', 'normal')
            
            # 우선순위별 이모지
            if priority == 'high':
                emoji = "🔴"
            elif priority == 'medium':
                emoji = "🟡"
            else:
                emoji = "🔵"
            
            with kw_cols[i % 4]:
                # 버튼 클릭 시 해당 키워드로 논문 목록 페이지 이동
                if st.button(f"{emoji} {kw} ({count})", key=f"kw_btn_{i}", use_container_width=True):
                    st.session_state.selected_keyword = kw
                    st.session_state.selected_menu = "📑 논문 목록"
                    st.rerun()
        
        st.caption("🔴 High · 🟡 Medium · 🔵 기타")
    
    with col2:
        st.markdown("#### 📊 키워드 빈도")
        
        if not top_keywords.empty:
            # 색상 매핑
            colors = []
            for _, row in top_keywords.iterrows():
                if row.get('priority') == 'high':
                    colors.append('#ff4b4b')
                elif row.get('priority') == 'medium':
                    colors.append('#ffa500')
                else:
                    colors.append('#4A90D9')
            
            fig = go.Figure(go.Bar(
                x=top_keywords['count'].values,
                y=top_keywords['keyword'].values,
                orientation='h',
                marker_color=colors,
                text=top_keywords['count'].values,
                textposition='auto',
            ))
            
            fig.update_layout(
                yaxis={'categoryorder': 'total ascending'},
                height=350,
                margin=dict(l=0, r=0, t=10, b=0),
                xaxis_title="",
                yaxis_title="",
                showlegend=False
            )
            
            st.plotly_chart(fig, use_container_width=True)


def main():
    """메인 대시보드"""
    
    db_path = Path("./data/journals.db")
    
    if not db_path.exists():
        st.error(f"데이터베이스를 찾을 수 없습니다: {db_path}")
        st.info("JournalMonitor를 먼저 실행해주세요.")
        return
    
    db = DashboardDB(str(db_path))
    
    # session_state 초기화
    if 'selected_keyword' not in st.session_state:
        st.session_state.selected_keyword = None
    if 'selected_menu' not in st.session_state:
        st.session_state.selected_menu = None
    
    with st.sidebar:
        st.title("📚 Journal Monitor")
        st.caption("케이의 학술논문 모니터링")
        
        st.divider()
        
        # 키워드 클릭으로 메뉴 이동 시 반영
        default_index = 0
        menu_options = ["🏠 홈", "📑 논문 목록", "📊 기간 분석", "📈 통계", "⚙️ 설정"]
        if st.session_state.selected_menu:
            if st.session_state.selected_menu in menu_options:
                default_index = menu_options.index(st.session_state.selected_menu)
        
        menu = st.radio(
            "메뉴",
            menu_options,
            index=default_index,
            label_visibility="collapsed"
        )
        
        st.divider()
        
        stats = db.get_stats()
        st.metric("총 논문", f"{stats['total']:,}편")
        
        col1, col2 = st.columns(2)
        with col1:
            st.metric("🔴 High", stats['high'])
        with col2:
            st.metric("🟡 Medium", stats['medium'])
        
        st.metric("오늘 수집", f"{stats['today']}편")
    
    if menu == "🏠 홈":
        render_home(db, stats)
    elif menu == "📑 논문 목록":
        render_articles(db)
    elif menu == "📊 기간 분석":
        render_period_analysis(db)
    elif menu == "📈 통계":
        render_statistics(db)
    elif menu == "⚙️ 설정":
        render_settings()


def render_home(db: DashboardDB, stats: dict):
    """홈 화면"""
    st.title("📚 학술논문 모니터링 대시보드")
    
    # 요약 카드
    col1, col2, col3, col4 = st.columns(4)
    
    with col1:
        st.metric("오늘 수집", f"{stats['today']}편")
    
    with col2:
        st.metric("이번 주", f"{stats['week']}편")
    
    with col3:
        st.metric("🔴 High Priority", f"{stats['high']}편")
    
    with col4:
        st.metric("초록 보유율", f"{stats['with_abstract'] / stats['total'] * 100:.1f}%" if stats['total'] > 0 else "0%")
    
    st.divider()
    
    # ===== 오늘의 키워드 인포그래픽 (새로 추가) =====
    st.subheader("🎯 오늘의 연구 키워드")
    render_today_keywords(db)
    
    st.divider()
    
    # 최근 수집 트렌드
    col1, col2 = st.columns(2)
    
    with col1:
        st.subheader("📊 최근 30일 수집 현황")
        daily = db.get_daily_counts(30)
        
        if not daily.empty:
            fig = px.bar(
                daily, 
                x='date', 
                y='count',
                color_discrete_sequence=['#4A90D9']
            )
            fig.update_layout(
                xaxis_title="",
                yaxis_title="논문 수",
                showlegend=False,
                height=300
            )
            st.plotly_chart(fig, use_container_width=True)
        else:
            st.info("데이터가 없습니다.")
    
    with col2:
        st.subheader("📰 저널별 분포")
        journal_dist = db.get_journal_distribution()
        
        if not journal_dist.empty:
            fig = px.pie(
                journal_dist.head(10),
                values='count',
                names='journal',
                hole=0.4
            )
            fig.update_layout(height=300)
            st.plotly_chart(fig, use_container_width=True)
        else:
            st.info("데이터가 없습니다.")
    
    st.divider()
    
    # 최근 High Priority 논문
    st.subheader("🔴 최근 High Priority 논문")
    
    high_articles = db.get_articles(priority='high', limit=5)
    
    if not high_articles.empty:
        for _, article in high_articles.iterrows():
            render_article_card(article, db=db)
    else:
        st.info("High priority 논문이 없습니다.")


def render_articles(db: DashboardDB):
    """논문 목록 화면"""
    st.title("📑 논문 목록")
    
    # 키워드에서 이동해온 경우 검색어 자동 설정
    default_search = ""
    if st.session_state.get('selected_keyword'):
        default_search = st.session_state.selected_keyword
        st.info(f"🏷️ '{default_search}' 키워드 논문 목록")
        # 사용 후 초기화 (다음 방문 시 리셋)
        st.session_state.selected_keyword = None
        st.session_state.selected_menu = None
    
    # 필터 옵션 - 1행: 기본 필터
    col1, col2, col3, col4 = st.columns(4)
    
    with col1:
        priority_filter = st.selectbox("우선순위", ["전체", "high", "medium", "normal"])
    
    with col2:
        journals = ["전체"] + db.get_journals()
        journal_filter = st.selectbox("저널", journals)
    
    with col3:
        days_options = [("전체", None), ("오늘", 1), ("최근 7일", 7), ("최근 30일", 30)]
        days_filter = st.selectbox("기간", days_options, format_func=lambda x: x[0])
    
    with col4:
        search = st.text_input("🔍 검색", value=default_search, placeholder="제목, 초록, 키워드...")
    
    # 필터 옵션 - 2행: 즐겨찾기/읽음 필터
    col1, col2, col3, col4 = st.columns(4)
    with col1:
        starred_only = st.toggle("⭐ 즐겨찾기만", value=False)
    with col2:
        unread_only = st.toggle("☐ 안읽은 것만", value=False)
    
    st.divider()
    
    articles = db.get_articles(
        priority=priority_filter if priority_filter != "전체" else None,
        journal=journal_filter if journal_filter != "전체" else None,
        days=days_filter[1],
        search=search if search else None,
        starred_only=starred_only,
        unread_only=unread_only,
        limit=50
    )
    
    st.caption(f"총 {len(articles)}편")
    
    if not articles.empty:
        for _, article in articles.iterrows():
            render_article_card(article, db=db)
    else:
        st.info("조건에 맞는 논문이 없습니다.")


def render_period_analysis(db: DashboardDB):
    """기간 분석 페이지"""
    st.title("📊 기간 분석")
    
    st.markdown("""
    선택한 기간 동안의 논문 수집 현황, 키워드 트렌드, 저널 분포 등을 분석합니다.
    """)
    
    # ========== 기간 선택 UI ==========
    st.subheader("📅 분석 기간 선택")
    
    col1, col2, col3 = st.columns([2, 1, 1])
    
    with col1:
        period_options = {
            "1개월": 30,
            "3개월": 90,
            "6개월": 180,
            "12개월": 365,
            "커스텀": None
        }
        selected_period = st.radio(
            "기간 선택",
            list(period_options.keys()),
            horizontal=True,
            label_visibility="collapsed"
        )
    
    # 커스텀 날짜 선택
    if selected_period == "커스텀":
        col1, col2 = st.columns(2)
        with col1:
            start_date = st.date_input("시작일", value=datetime.now() - timedelta(days=30))
        with col2:
            end_date = st.date_input("종료일", value=datetime.now())
        days = (end_date - start_date).days
        date_from = start_date.strftime('%Y-%m-%d')
        date_to = end_date.strftime('%Y-%m-%d')
    else:
        days = period_options[selected_period]
        date_from = (datetime.now() - timedelta(days=days)).strftime('%Y-%m-%d')
        date_to = datetime.now().strftime('%Y-%m-%d')
    
    st.caption(f"📆 분석 기간: **{date_from}** ~ **{date_to}** ({days}일)")
    
    st.divider()
    
    # ========== 데이터 조회 ==========
    period_stats = get_period_stats(db, days)
    period_keywords = db.get_keyword_stats(days=days)
    period_daily = db.get_daily_counts(days=days)
    
    # ========== 1. 핵심 요약 ==========
    st.subheader("📝 핵심 요약")
    
    col1, col2, col3, col4, col5 = st.columns(5)
    
    with col1:
        st.metric("총 논문 수", f"{period_stats['total']:,}편")
    with col2:
        st.metric("🔴 High", f"{period_stats['high']}편")
    with col3:
        st.metric("🟡 Medium", f"{period_stats['medium']}편")
    with col4:
        avg_daily = period_stats['total'] / days if days > 0 else 0
        st.metric("일평균", f"{avg_daily:.1f}편")
    with col5:
        read_rate = (period_stats['read'] / period_stats['total'] * 100) if period_stats['total'] > 0 else 0
        st.metric("읽음률", f"{read_rate:.1f}%")
    
    # Top 5 키워드 표시
    if not period_keywords.empty:
        top5 = period_keywords.head(5)
        top5_str = " · ".join([f"**{row['keyword']}**({row['count']})".replace('**', '') for _, row in top5.iterrows()])
        st.info(f"🏷️ 주요 키워드: {top5_str}")
    
    st.divider()
    
    # ========== 2. 키워드 트렌드 ==========
    st.subheader("🏷️ 키워드 분석")
    
    tab1, tab2, tab3 = st.tabs(["키워드 빈도", "키워드 트렌드", "🔗 공출현 네트워크"])
    
    with tab1:
        if not period_keywords.empty:
            col1, col2 = st.columns([1, 1])
            
            with col1:
                # 가로 막대 차트
                top20 = period_keywords.head(20)
                
                colors = []
                for _, row in top20.iterrows():
                    if row.get('priority') == 'high':
                        colors.append('#ff4b4b')
                    elif row.get('priority') == 'medium':
                        colors.append('#ffa500')
                    else:
                        colors.append('#4A90D9')
                
                fig = go.Figure(go.Bar(
                    x=top20['count'].values,
                    y=top20['keyword'].values,
                    orientation='h',
                    marker_color=colors,
                    text=top20['count'].values,
                    textposition='auto',
                ))
                
                fig.update_layout(
                    title="키워드 빈도 Top 20",
                    yaxis={'categoryorder': 'total ascending'},
                    height=500,
                    margin=dict(l=0, r=0, t=40, b=0),
                    xaxis_title="",
                    yaxis_title="",
                )
                
                st.plotly_chart(fig, use_container_width=True)
            
            with col2:
                # 파이 차트
                top10 = period_keywords.head(10)
                
                fig = px.pie(
                    top10,
                    values='count',
                    names='keyword',
                    title="키워드 비율 Top 10",
                    hole=0.4
                )
                fig.update_layout(height=500)
                st.plotly_chart(fig, use_container_width=True)
        else:
            st.info("해당 기간에 키워드 데이터가 없습니다.")
    
    with tab3:
        st.markdown("""
        같은 논문에 함께 등장한 키워드들을 네트워크로 시각화합니다.  
        - 노드 크기 = 연결 수 (다른 키워드와 얼마나 자주 함께 등장하는지)
        - 엣지 두께 = 공출현 횟수
        - 🔴 High Priority · 🟡 Medium Priority · 🔵 기타
        """)
        
        col1, col2 = st.columns([3, 1])
        with col2:
            min_cooccur = st.slider("최소 공출현 횟수", 1, 10, 2, help="이 횟수 이상 함께 등장한 키워드만 표시")
        
        cooccurrence_df = get_keyword_cooccurrence(db, days, min_count=min_cooccur)
        
        if not cooccurrence_df.empty:
            st.caption(f"키워드 연결 수: {len(cooccurrence_df)}개")
            render_keyword_network(cooccurrence_df, period_keywords)
            
            # 공출현 Top 10 테이블
            with st.expander("📊 공출현 Top 10 보기"):
                top10 = cooccurrence_df.head(10)
                for i, row in top10.iterrows():
                    st.markdown(f"**{row['source']}** ↔ **{row['target']}**: {row['weight']}회")
        else:
            st.info("공출현 데이터가 부족합니다. 기간을 늘리거나 최소 공출현 횟수를 낮춰보세요.")
    
    with tab2:
        # 일별 키워드 트렌드 (상위 5개 키워드)
        if not period_keywords.empty:
            st.markdown("주요 키워드의 일별 등장 트렌드")
            
            top5_keywords = period_keywords.head(5)['keyword'].tolist()
            keyword_trend = get_keyword_daily_trend(db, days, top5_keywords)
            
            if not keyword_trend.empty:
                fig = px.line(
                    keyword_trend,
                    x='date',
                    y='count',
                    color='keyword',
                    title="주요 키워드 일별 트렌드",
                    markers=True
                )
                fig.update_layout(height=400)
                st.plotly_chart(fig, use_container_width=True)
            else:
                st.info("트렌드 데이터가 부족합니다.")
        else:
            st.info("해당 기간에 키워드 데이터가 없습니다.")
    
    st.divider()
    
    # ========== 3. 수집 현황 ==========
    st.subheader("📈 수집 현황")
    
    if not period_daily.empty:
        fig = go.Figure()
        
        fig.add_trace(go.Scatter(
            x=period_daily['date'],
            y=period_daily['count'],
            mode='lines+markers',
            name='전체',
            line=dict(color='#4A90D9', width=2)
        ))
        
        fig.add_trace(go.Bar(
            x=period_daily['date'],
            y=period_daily['high'],
            name='High',
            marker_color='#ff4b4b'
        ))
        
        fig.add_trace(go.Bar(
            x=period_daily['date'],
            y=period_daily['medium'],
            name='Medium',
            marker_color='#ffa500'
        ))
        
        fig.update_layout(
            title="일별 논문 수집 현황",
            xaxis_title="",
            yaxis_title="논문 수",
            barmode='stack',
            height=400
        )
        
        st.plotly_chart(fig, use_container_width=True)
    else:
        st.info("해당 기간에 수집 데이터가 없습니다.")
    
    st.divider()
    
    # ========== 4. 저널별 분포 ==========
    st.subheader("📰 저널별 분포")
    
    journal_stats = get_period_journal_stats(db, days)
    
    if not journal_stats.empty:
        col1, col2 = st.columns([1, 1])
        
        with col1:
            fig = px.bar(
                journal_stats,
                x='count',
                y='journal',
                orientation='h',
                color='high',
                color_continuous_scale='Reds',
                title="저널별 논문 수"
            )
            fig.update_layout(
                yaxis={'categoryorder': 'total ascending'},
                height=500,
                xaxis_title="논문 수",
                yaxis_title=""
            )
            st.plotly_chart(fig, use_container_width=True)
        
        with col2:
            fig = px.pie(
                journal_stats.head(10),
                values='count',
                names='journal',
                title="저널 비율 Top 10",
                hole=0.4
            )
            fig.update_layout(height=500)
            st.plotly_chart(fig, use_container_width=True)
    else:
        st.info("해당 기간에 저널 데이터가 없습니다.")
    
    st.divider()
    
    # ========== 5. 개인 활동 요약 ==========
    st.subheader("📚 개인 활동 요약")
    
    col1, col2, col3 = st.columns(3)
    
    with col1:
        st.metric("⭐ 즐겨찾기", f"{period_stats['starred']}편")
    with col2:
        st.metric("✅ 읽음", f"{period_stats['read']}편")
    with col3:
        unread = period_stats['total'] - period_stats['read']
        st.metric("☐ 안읽음", f"{unread}편")
    
    # 즐겨찾기 논문 목록
    if period_stats['starred'] > 0:
        with st.expander(f"⭐ 즐겨찾기한 논문 ({period_stats['starred']}편)"):
            starred_articles = db.get_articles(days=days, starred_only=True, limit=20)
            for _, article in starred_articles.iterrows():
                priority_emoji = {'high': '🔴', 'medium': '🟡'}.get(article.get('priority'), '⚪')
                title = article.get('title_ko') or article.get('title')
                st.markdown(f"- {priority_emoji} **{title}**")
    
    st.divider()
    
    # ========== 6. 이론 연결망 ==========
    st.subheader("🧠 이론 연결망")
    
    st.markdown("""
    논문에서 언급된 이론가와 이론적 개념들의 연결 패턴을 분석합니다.
    - 🟣 **보라**: 이론가 (Foucault, Deleuze, Lefebvre 등)
    - 🟦 **파랑**: 이론적 개념 (governmentality, assemblage 등)
    """)
    
    theory_data = analyze_theory_connections(db, days)
    
    if theory_data['theorists'] or theory_data['concepts']:
        col1, col2 = st.columns(2)
        
        with col1:
            if theory_data['theorists']:
                st.markdown("**📚 주요 이론가 언급 횟수**")
                for name, count in sorted(theory_data['theorists'].items(), key=lambda x: -x[1])[:10]:
                    st.markdown(f"- {name}: **{count}**회")
        
        with col2:
            if theory_data['concepts']:
                st.markdown("**💡 주요 개념 언급 횟수**")
                for name, count in sorted(theory_data['concepts'].items(), key=lambda x: -x[1])[:10]:
                    st.markdown(f"- {name}: **{count}**회")
        
        st.markdown("---")
        st.markdown("**이론가-개념 연결망**")
        render_theory_network(theory_data)
    else:
        st.info("해당 기간에 이론적 데이터가 부족합니다. 기간을 늘려보세요.")
    
    st.divider()
    
    # ========== 7. 토픽 클러스터링 ==========
    st.subheader("📚 토픽 클러스터링")
    
    st.markdown("""
    논문 초록을 기반으로 자동 클러스터링하여 연구 주제를 발견합니다.  
    TF-IDF + KMeans 알고리즘 사용.
    """)
    
    col1, col2 = st.columns([3, 1])
    with col2:
        n_clusters = st.slider("클러스터 수", 3, 10, 5)
    
    clustering_result = perform_topic_clustering(db, days, n_clusters=n_clusters)
    
    if clustering_result['error']:
        st.warning(f"클러스터링 실패: {clustering_result['error']}. 데이터가 더 필요합니다.")
    else:
        # 클러스터 시각화 (Scatter plot)
        df_cluster = clustering_result['articles']
        
        fig = px.scatter(
            df_cluster,
            x='x',
            y='y',
            color='cluster',
            hover_data=['title_ko', 'priority'],
            title="논문 클러스터 분포 (PCA 2D)",
            color_continuous_scale='viridis'
        )
        fig.update_layout(height=500)
        st.plotly_chart(fig, use_container_width=True)
        
        # 클러스터별 대표 키워드
        st.markdown("**클러스터별 대표 키워드**")
        
        cols = st.columns(min(n_clusters, 5))
        for i, keywords in clustering_result['clusters'].items():
            with cols[i % 5]:
                cluster_count = len(df_cluster[df_cluster['cluster'] == i])
                st.markdown(f"**클러스터 {i+1}** ({cluster_count}편)")
                st.caption(", ".join(keywords))
        
        # 클러스터별 논문 목록
        with st.expander("클러스터별 논문 목록 보기"):
            for i in range(n_clusters):
                cluster_articles = df_cluster[df_cluster['cluster'] == i]
                st.markdown(f"### 클러스터 {i+1}: {', '.join(clustering_result['clusters'][i][:3])}")
                for _, art in cluster_articles.head(5).iterrows():
                    title = art.get('title_ko') or art.get('title')
                    priority_emoji = {'high': '🔴', 'medium': '🟡'}.get(art.get('priority'), '⚪')
                    st.markdown(f"- {priority_emoji} {title}")
                st.markdown("---")
    
    st.divider()
    
    # ========== 8. 사례 지역 지도 ==========
    st.subheader("🗺️ 사례 지역 분포")
    
    st.markdown("""
    논문에서 언급된 도시/지역을 지도에 표시합니다.  
    원 크기는 언급 횟수에 비례합니다.
    """)
    
    location_df = extract_locations(db, days)
    
    if not location_df.empty:
        col1, col2 = st.columns([2, 1])
        
        with col1:
            render_location_map(location_df)
        
        with col2:
            st.markdown("**🏙️ 상위 언급 도시**")
            for _, row in location_df.head(15).iterrows():
                st.markdown(f"- {row['city']}: **{row['count']}**회")
            
            # 한국 도시 하이라이트
            korea_cities = location_df[location_df['city'].str.lower().isin(['seoul', 'busan', 'incheon', 'daegu', 'gwangju', 'daejeon', 'ulsan', 'jeju'])]
            if not korea_cities.empty:
                st.markdown("---")
                st.markdown("🇰🇷 **한국 도시**")
                for _, row in korea_cities.iterrows():
                    st.markdown(f"- {row['city']}: **{row['count']}**회")
    else:
        st.info("해당 기간에 지역 데이터가 없습니다.")
    
    st.divider()
    
    # ========== 9. AI 연구 인사이트 ==========
    st.subheader("🤖 AI 연구 인사이트")
    
    st.markdown("""
    Claude AI가 수집된 논문들을 분석하여 연구 트렌드, 걸, 떠오르는 질문 등을 제안합니다.
    """)
    
    if not ANTHROPIC_AVAILABLE:
        st.warning("Anthropic 라이브러리가 설치되지 않았습니다.")
    elif not os.environ.get('ANTHROPIC_API_KEY'):
        st.warning("ANTHROPIC_API_KEY 환경변수가 설정되지 않았습니다.")
    else:
        if st.button("🤖 AI 인사이트 생성", type="primary"):
            with st.spinner("Claude가 논문을 분석 중..."):
                insights = generate_ai_insights(db, days, period_keywords)
                
                if insights:
                    st.markdown(insights)
                else:
                    st.error("인사이트 생성에 실패했습니다.")
        else:
            st.info("버튼을 클릭하면 Claude AI가 연구 트렌드를 분석합니다.")


def get_period_stats(db: DashboardDB, days: int) -> dict:
    """기간별 통계 조회"""
    date_from = (datetime.now() - timedelta(days=days)).strftime('%Y-%m-%d')
    
    with db.get_connection() as conn:
        cursor = conn.cursor()
        
        # 전체 논문 수
        cursor.execute("""
            SELECT COUNT(*) FROM articles 
            WHERE DATE(fetched_at) >= ?
        """, (date_from,))
        total = cursor.fetchone()[0]
        
        # High priority
        cursor.execute("""
            SELECT COUNT(*) FROM articles 
            WHERE DATE(fetched_at) >= ? AND priority = 'high'
        """, (date_from,))
        high = cursor.fetchone()[0]
        
        # Medium priority
        cursor.execute("""
            SELECT COUNT(*) FROM articles 
            WHERE DATE(fetched_at) >= ? AND priority = 'medium'
        """, (date_from,))
        medium = cursor.fetchone()[0]
        
        # 읽음
        cursor.execute("""
            SELECT COUNT(*) FROM articles 
            WHERE DATE(fetched_at) >= ? AND is_read = 1
        """, (date_from,))
        read = cursor.fetchone()[0]
        
        # 즐겨찾기
        cursor.execute("""
            SELECT COUNT(*) FROM articles 
            WHERE DATE(fetched_at) >= ? AND is_starred = 1
        """, (date_from,))
        starred = cursor.fetchone()[0]
        
        return {
            'total': total,
            'high': high,
            'medium': medium,
            'read': read,
            'starred': starred
        }


def get_period_journal_stats(db: DashboardDB, days: int) -> pd.DataFrame:
    """기간별 저널 통계"""
    date_from = (datetime.now() - timedelta(days=days)).strftime('%Y-%m-%d')
    
    query = """
        SELECT 
            j.name as journal,
            COUNT(*) as count,
            SUM(CASE WHEN a.priority = 'high' THEN 1 ELSE 0 END) as high,
            SUM(CASE WHEN a.priority = 'medium' THEN 1 ELSE 0 END) as medium
        FROM articles a
        LEFT JOIN journals j ON a.journal_id = j.id
        WHERE DATE(a.fetched_at) >= ?
        GROUP BY j.name
        ORDER BY count DESC
        LIMIT 20
    """
    
    with db.get_connection() as conn:
        df = pd.read_sql_query(query, conn, params=[date_from])
    
    return df


def get_keyword_daily_trend(db: DashboardDB, days: int, keywords: list) -> pd.DataFrame:
    """키워드별 일별 트렌드"""
    date_from = (datetime.now() - timedelta(days=days)).strftime('%Y-%m-%d')
    
    query = """
        SELECT DATE(fetched_at) as date, keywords_matched
        FROM articles
        WHERE DATE(fetched_at) >= ?
          AND keywords_matched IS NOT NULL 
          AND keywords_matched != ''
    """
    
    with db.get_connection() as conn:
        df = pd.read_sql_query(query, conn, params=[date_from])
    
    if df.empty:
        return pd.DataFrame()
    
    # 일별/키워드별 카운트
    daily_counts = {}
    
    for _, row in df.iterrows():
        date = row['date']
        kw_matched = row['keywords_matched']
        
        try:
            kw_list = json.loads(kw_matched)
            if isinstance(kw_list, list):
                for kw in kw_list:
                    kw = str(kw).strip()
                    if kw in keywords:
                        key = (date, kw)
                        daily_counts[key] = daily_counts.get(key, 0) + 1
        except:
            pass
    
    # DataFrame으로 변환
    result = []
    for (date, kw), count in daily_counts.items():
        result.append({'date': date, 'keyword': kw, 'count': count})
    
    return pd.DataFrame(result)


def get_keyword_cooccurrence(db: DashboardDB, days: int, min_count: int = 2) -> pd.DataFrame:
    """키워드 공출현 데이터 추출"""
    date_from = (datetime.now() - timedelta(days=days)).strftime('%Y-%m-%d')
    
    query = """
        SELECT keywords_matched
        FROM articles
        WHERE DATE(fetched_at) >= ?
          AND keywords_matched IS NOT NULL 
          AND keywords_matched != ''
    """
    
    with db.get_connection() as conn:
        df = pd.read_sql_query(query, conn, params=[date_from])
    
    if df.empty:
        return pd.DataFrame()
    
    # 키워드 쌍 카운트
    cooccurrence = {}
    
    for _, row in df.iterrows():
        kw_matched = row['keywords_matched']
        
        try:
            kw_list = json.loads(kw_matched)
            if isinstance(kw_list, list) and len(kw_list) >= 2:
                # 모든 키워드 쌍 조합
                kw_list = [str(kw).strip() for kw in kw_list]
                for i in range(len(kw_list)):
                    for j in range(i + 1, len(kw_list)):
                        pair = tuple(sorted([kw_list[i], kw_list[j]]))
                        cooccurrence[pair] = cooccurrence.get(pair, 0) + 1
        except:
            pass
    
    # DataFrame으로 변환
    result = []
    for (kw1, kw2), count in cooccurrence.items():
        if count >= min_count:
            result.append({'source': kw1, 'target': kw2, 'weight': count})
    
    return pd.DataFrame(result).sort_values('weight', ascending=False)


def render_keyword_network(cooccurrence_df: pd.DataFrame, keyword_stats: pd.DataFrame):
    """키워드 공출현 네트워크 시각화"""
    if cooccurrence_df.empty:
        st.info("공출현 데이터가 부족합니다. 더 많은 데이터가 필요합니다.")
        return
    
    # 키워드 우선순위 매핑
    priority_map = {}
    if not keyword_stats.empty:
        for _, row in keyword_stats.iterrows():
            priority_map[row['keyword']] = row.get('priority', 'normal')
    
    # NetworkX 그래프 생성
    G = nx.Graph()
    
    # 엣지 추가
    for _, row in cooccurrence_df.iterrows():
        G.add_edge(row['source'], row['target'], weight=row['weight'])
    
    # Pyvis 네트워크 생성
    net = Network(height='500px', width='100%', bgcolor='#ffffff', font_color='#333333')
    net.barnes_hut(gravity=-3000, central_gravity=0.3, spring_length=100)
    
    # 노드 추가 (우선순위에 따른 색상)
    for node in G.nodes():
        priority = priority_map.get(node, 'normal')
        
        if priority == 'high':
            color = '#ff4b4b'  # 빨강
        elif priority == 'medium':
            color = '#ffa500'  # 주황
        else:
            color = '#4A90D9'  # 파랑
        
        # 노드 크기 = 연결 수
        size = 15 + G.degree(node) * 3
        
        net.add_node(node, label=node, color=color, size=size, title=f"{node}\n연결: {G.degree(node)}개")
    
    # 엣지 추가
    for edge in G.edges(data=True):
        weight = edge[2]['weight']
        net.add_edge(edge[0], edge[1], value=weight, title=f"공출현: {weight}회")
    
    # HTML 생성
    with tempfile.NamedTemporaryFile(delete=False, suffix='.html', mode='w', encoding='utf-8') as f:
        net.save_graph(f.name)
        f.seek(0)
        html_content = open(f.name, 'r', encoding='utf-8').read()
    
    # Streamlit에 렌더링
    components.html(html_content, height=520, scrolling=True)


# ========== 이론 연결망 분석 ==========
THEORISTS = [
    "Foucault", "Deleuze", "Guattari", "Lefebvre", "Harvey", "Massey", 
    "Latour", "Haraway", "Barad", "Bennett", "Agamben", "Butler",
    "Bourdieu", "Gramsci", "Marx", "Weber", "Simmel", "Sassen",
    "Castells", "Brenner", "Smith", "Jessop", "Peck", "Theodore"
]

THEORETICAL_CONCEPTS = [
    "governmentality", "biopolitics", "discipline", "panopticon",
    "assemblage", "rhizome", "deterritorialization", "becoming",
    "new materialism", "posthuman", "actor-network", "ANT",
    "right to the city", "production of space", "spatial triad",
    "territory", "sovereignty", "borders", "mobility",
    "infrastructure", "platform", "smart city", "algorithm",
    "neoliberalism", "gentrification", "displacement", "accumulation"
]


def analyze_theory_connections(db: DashboardDB, days: int) -> dict:
    """이론가/개념 연결 분석"""
    date_from = (datetime.now() - timedelta(days=days)).strftime('%Y-%m-%d')
    
    query = """
        SELECT title, abstract, keywords_matched
        FROM articles
        WHERE DATE(fetched_at) >= ?
          AND abstract IS NOT NULL 
          AND LENGTH(abstract) > 100
    """
    
    with db.get_connection() as conn:
        df = pd.read_sql_query(query, conn, params=[date_from])
    
    if df.empty:
        return {'theorists': {}, 'concepts': {}, 'connections': []}
    
    # 이론가 및 개념 카운트
    theorist_counts = {t: 0 for t in THEORISTS}
    concept_counts = {c: 0 for c in THEORETICAL_CONCEPTS}
    connections = {}  # (이론가, 개념) 쌍
    
    for _, row in df.iterrows():
        text = f"{row['title']} {row['abstract']}".lower()
        
        found_theorists = []
        found_concepts = []
        
        for t in THEORISTS:
            if t.lower() in text:
                theorist_counts[t] += 1
                found_theorists.append(t)
        
        for c in THEORETICAL_CONCEPTS:
            if c.lower() in text:
                concept_counts[c] += 1
                found_concepts.append(c)
        
        # 연결 기록
        for t in found_theorists:
            for c in found_concepts:
                key = (t, c)
                connections[key] = connections.get(key, 0) + 1
    
    # 필터링 (0보다 큰 것만)
    theorist_counts = {k: v for k, v in theorist_counts.items() if v > 0}
    concept_counts = {k: v for k, v in concept_counts.items() if v > 0}
    connections = [(k[0], k[1], v) for k, v in connections.items() if v > 0]
    connections.sort(key=lambda x: -x[2])
    
    return {
        'theorists': theorist_counts,
        'concepts': concept_counts,
        'connections': connections[:30]  # Top 30
    }


def render_theory_network(theory_data: dict):
    """이론 연결망 시각화"""
    if not theory_data['connections']:
        st.info("이론적 연결 데이터가 부족합니다.")
        return
    
    G = nx.Graph()
    
    # 노드 추가
    for t, count in theory_data['theorists'].items():
        G.add_node(t, node_type='theorist', count=count)
    
    for c, count in theory_data['concepts'].items():
        G.add_node(c, node_type='concept', count=count)
    
    # 엣지 추가
    for t, c, weight in theory_data['connections']:
        G.add_edge(t, c, weight=weight)
    
    # Pyvis
    net = Network(height='500px', width='100%', bgcolor='#ffffff', font_color='#333333')
    net.barnes_hut(gravity=-2000, central_gravity=0.3, spring_length=150)
    
    for node in G.nodes(data=True):
        name = node[0]
        data = node[1]
        
        if data.get('node_type') == 'theorist':
            color = '#9b59b6'  # 보라
            shape = 'dot'
        else:
            color = '#3498db'  # 파랑
            shape = 'box'
        
        size = 15 + data.get('count', 1) * 2
        net.add_node(name, label=name, color=color, size=size, shape=shape,
                    title=f"{name}\n등장: {data.get('count', 0)}회")
    
    for edge in G.edges(data=True):
        net.add_edge(edge[0], edge[1], value=edge[2]['weight'],
                    title=f"연결: {edge[2]['weight']}회")
    
    with tempfile.NamedTemporaryFile(delete=False, suffix='.html', mode='w', encoding='utf-8') as f:
        net.save_graph(f.name)
        html_content = open(f.name, 'r', encoding='utf-8').read()
    
    components.html(html_content, height=520, scrolling=True)


# ========== AI 인사이트 ==========
def generate_ai_insights(db: DashboardDB, days: int, keyword_stats: pd.DataFrame) -> str:
    """Claude API로 AI 인사이트 생성"""
    if not ANTHROPIC_AVAILABLE:
        return None
    
    api_key = os.environ.get('ANTHROPIC_API_KEY')
    if not api_key:
        return None
    
    date_from = (datetime.now() - timedelta(days=days)).strftime('%Y-%m-%d')
    
    # 데이터 수집
    query = """
        SELECT title, title_ko, abstract, priority, keywords_matched
        FROM articles
        WHERE DATE(fetched_at) >= ?
          AND priority IN ('high', 'medium')
        ORDER BY priority DESC, fetched_at DESC
        LIMIT 30
    """
    
    with db.get_connection() as conn:
        df = pd.read_sql_query(query, conn, params=[date_from])
    
    if df.empty:
        return "분석할 논문이 부족합니다."
    
    # 논문 요약 준비
    articles_summary = []
    for _, row in df.iterrows():
        title = row['title_ko'] or row['title']
        keywords = row['keywords_matched'] or ''
        articles_summary.append(f"- [{row['priority'].upper()}] {title} (키워드: {keywords})")
    
    articles_text = "\n".join(articles_summary[:20])
    
    # 키워드 통계
    if not keyword_stats.empty:
        top_keywords = keyword_stats.head(10)['keyword'].tolist()
        keywords_text = ", ".join(top_keywords)
    else:
        keywords_text = "데이터 없음"
    
    prompt = f"""
당신은 인문지리학/도시연구 전문가입니다. 아래는 최근 {days}일간 수집된 학술논문 목록입니다.

**주요 키워드**: {keywords_text}

**논문 목록**:
{articles_text}

위 데이터를 바탕으로 다음을 한국어로 작성해주세요:

1. **연구 트렌드 요약** (3-4문장): 이 기간 어떤 주제가 활발히 연구되고 있는지

2. **연구 걸/기회** (2-3개): 아직 충분히 탐구되지 않은 영역, 새로운 연구 기회

3. **떠오르는 연구 질문** (2-3개): 이 논문들에서 발견되는 미해결 질문들

4. **통찰성/인사이트** (2-3개): 독자에게 도움이 될 흥미로운 발견

간결하게 작성해주세요.
"""
    
    try:
        client = Anthropic(api_key=api_key)
        response = client.messages.create(
            model="claude-sonnet-4-20250514",
            max_tokens=1500,
            messages=[{"role": "user", "content": prompt}]
        )
        return response.content[0].text
    except Exception as e:
        return f"오류 발생: {str(e)}"


# ========== 토픽 클러스터링 ==========
def perform_topic_clustering(db: DashboardDB, days: int, n_clusters: int = 5) -> dict:
    """논문 초록 기반 토픽 클러스터링 (TF-IDF + KMeans)"""
    date_from = (datetime.now() - timedelta(days=days)).strftime('%Y-%m-%d')
    
    query = """
        SELECT id, title, title_ko, abstract, priority
        FROM articles
        WHERE DATE(fetched_at) >= ?
          AND abstract IS NOT NULL 
          AND LENGTH(abstract) > 100
    """
    
    with db.get_connection() as conn:
        df = pd.read_sql_query(query, conn, params=[date_from])
    
    if len(df) < n_clusters:
        return {'clusters': [], 'articles': df, 'error': '데이터 부족'}
    
    # TF-IDF 벡터화
    abstracts = df['abstract'].tolist()
    
    vectorizer = TfidfVectorizer(
        max_features=1000,
        stop_words='english',
        ngram_range=(1, 2),
        min_df=2
    )
    
    try:
        tfidf_matrix = vectorizer.fit_transform(abstracts)
    except:
        return {'clusters': [], 'articles': df, 'error': 'TF-IDF 실패'}
    
    # KMeans 클러스터링
    kmeans = KMeans(n_clusters=n_clusters, random_state=42, n_init=10)
    df['cluster'] = kmeans.fit_predict(tfidf_matrix)
    
    # PCA로 2D 축소
    pca = PCA(n_components=2, random_state=42)
    coords = pca.fit_transform(tfidf_matrix.toarray())
    df['x'] = coords[:, 0]
    df['y'] = coords[:, 1]
    
    # 클러스터별 대표 키워드 추출
    feature_names = vectorizer.get_feature_names_out()
    cluster_keywords = {}
    
    for i in range(n_clusters):
        center = kmeans.cluster_centers_[i]
        top_indices = center.argsort()[-5:][::-1]
        cluster_keywords[i] = [feature_names[idx] for idx in top_indices]
    
    return {
        'clusters': cluster_keywords,
        'articles': df,
        'error': None
    }


# ========== 사례 지역 추출 및 지도 ==========
CITY_COORDS = {
    # 아시아
    "seoul": (37.5665, 126.9780), "tokyo": (35.6762, 139.6503), 
    "beijing": (39.9042, 116.4074), "shanghai": (31.2304, 121.4737),
    "hong kong": (22.3193, 114.1694), "singapore": (1.3521, 103.8198),
    "bangkok": (13.7563, 100.5018), "mumbai": (19.0760, 72.8777),
    "delhi": (28.7041, 77.1025), "jakarta": (-6.2088, 106.8456),
    # 유럽
    "london": (51.5074, -0.1278), "paris": (48.8566, 2.3522),
    "berlin": (52.5200, 13.4050), "amsterdam": (52.3676, 4.9041),
    "barcelona": (41.3851, 2.1734), "rome": (41.9028, 12.4964),
    "vienna": (48.2082, 16.3738), "copenhagen": (55.6761, 12.5683),
    "stockholm": (59.3293, 18.0686), "oslo": (59.9139, 10.7522),
    # 북미
    "new york": (40.7128, -74.0060), "los angeles": (34.0522, -118.2437),
    "chicago": (41.8781, -87.6298), "san francisco": (37.7749, -122.4194),
    "toronto": (43.6532, -79.3832), "vancouver": (49.2827, -123.1207),
    "mexico city": (19.4326, -99.1332),
    # 남미
    "sao paulo": (-23.5505, -46.6333), "buenos aires": (-34.6037, -58.3816),
    "rio de janeiro": (-22.9068, -43.1729), "bogota": (4.7110, -74.0721),
    # 아프리카/중동
    "cape town": (-33.9249, 18.4241), "johannesburg": (-26.2041, 28.0473),
    "cairo": (30.0444, 31.2357), "dubai": (25.2048, 55.2708),
    "istanbul": (41.0082, 28.9784), "tel aviv": (32.0853, 34.7818),
    # 오세아니아
    "sydney": (-33.8688, 151.2093), "melbourne": (-37.8136, 144.9631),
    "auckland": (-36.8509, 174.7645),
    # 한국 도시
    "busan": (35.1796, 129.0756), "incheon": (37.4563, 126.7052),
    "daegu": (35.8714, 128.6014), "gwangju": (35.1595, 126.8526),
    "daejeon": (36.3504, 127.3845), "ulsan": (35.5384, 129.3114),
    "jeju": (33.4996, 126.5312),
}


def extract_locations(db: DashboardDB, days: int) -> pd.DataFrame:
    """논문에서 지역명 추출"""
    date_from = (datetime.now() - timedelta(days=days)).strftime('%Y-%m-%d')
    
    query = """
        SELECT title, abstract
        FROM articles
        WHERE DATE(fetched_at) >= ?
          AND abstract IS NOT NULL
    """
    
    with db.get_connection() as conn:
        df = pd.read_sql_query(query, conn, params=[date_from])
    
    if df.empty:
        return pd.DataFrame()
    
    # 지역명 카운트
    location_counts = {}
    
    for _, row in df.iterrows():
        text = f"{row['title']} {row['abstract']}".lower()
        
        for city in CITY_COORDS.keys():
            pattern = r'\b' + re.escape(city) + r'\b'
            if re.search(pattern, text):
                location_counts[city] = location_counts.get(city, 0) + 1
    
    result = []
    for city, count in location_counts.items():
        lat, lon = CITY_COORDS[city]
        result.append({
            'city': city.title(),
            'count': count,
            'lat': lat,
            'lon': lon
        })
    
    return pd.DataFrame(result).sort_values('count', ascending=False)


def render_location_map(location_df: pd.DataFrame):
    """사례 지역 지도 시각화"""
    if not FOLIUM_AVAILABLE:
        st.warning("folium 라이브러리가 설치되지 않았습니다.")
        return
    
    if location_df.empty:
        st.info("지역 데이터가 없습니다.")
        return
    
    m = folium.Map(location=[20, 0], zoom_start=2, tiles='cartodbpositron')
    
    max_count = location_df['count'].max()
    
    for _, row in location_df.iterrows():
        radius = 5 + (row['count'] / max_count) * 25
        
        folium.CircleMarker(
            location=[row['lat'], row['lon']],
            radius=radius,
            popup=f"{row['city']}: {row['count']}회",
            color='#ff4b4b',
            fill=True,
            fill_color='#ff4b4b',
            fill_opacity=0.6
        ).add_to(m)
    
    folium_static(m, width=700, height=400)


def render_statistics(db: DashboardDB):
    """통계 화면"""
    st.title("📈 통계")
    
    tab1, tab2, tab3 = st.tabs(["📊 트렌드", "📰 저널", "🏷️ 키워드"])
    
    with tab1:
        st.subheader("일별 수집 현황")
        
        days = st.slider("기간 (일)", 7, 90, 30)
        daily = db.get_daily_counts(days)
        
        if not daily.empty:
            fig = go.Figure()
            
            fig.add_trace(go.Scatter(
                x=daily['date'],
                y=daily['count'],
                mode='lines+markers',
                name='전체',
                line=dict(color='#4A90D9', width=2)
            ))
            
            fig.add_trace(go.Bar(
                x=daily['date'],
                y=daily['high'],
                name='High',
                marker_color='#ff4b4b'
            ))
            
            fig.add_trace(go.Bar(
                x=daily['date'],
                y=daily['medium'],
                name='Medium',
                marker_color='#ffa500'
            ))
            
            fig.update_layout(
                xaxis_title="날짜",
                yaxis_title="논문 수",
                barmode='stack',
                height=400
            )
            
            st.plotly_chart(fig, use_container_width=True)
        else:
            st.info("데이터가 없습니다.")
    
    with tab2:
        st.subheader("저널별 논문 수")
        
        journal_dist = db.get_journal_distribution()
        
        if not journal_dist.empty:
            fig = px.bar(
                journal_dist,
                x='count',
                y='journal',
                orientation='h',
                color='high',
                color_continuous_scale='Reds'
            )
            fig.update_layout(
                yaxis={'categoryorder': 'total ascending'},
                height=600,
                xaxis_title="논문 수",
                yaxis_title=""
            )
            st.plotly_chart(fig, use_container_width=True)
        else:
            st.info("데이터가 없습니다.")
    
    with tab3:
        st.subheader("매칭된 키워드 빈도")
        
        keyword_stats = db.get_keyword_stats()
        
        if not keyword_stats.empty:
            fig = px.bar(
                keyword_stats.head(20),
                x='count',
                y='keyword',
                orientation='h',
                color='count',
                color_continuous_scale='Blues'
            )
            fig.update_layout(
                yaxis={'categoryorder': 'total ascending'},
                height=500,
                xaxis_title="빈도",
                yaxis_title=""
            )
            st.plotly_chart(fig, use_container_width=True)
        else:
            st.info("키워드 데이터가 없습니다.")


def render_settings():
    """설정 화면"""
    st.title("⚙️ 설정")
    
    config = load_config()
    
    # 키워드 설정 섹션
    st.subheader("🏷️ 키워드 설정")
    
    st.markdown("""
    논문 우선순위 분류에 사용되는 키워드를 관리합니다.
    - **🔴 High Priority**: 핵심 연구 키워드 (번역 및 요약 대상)
    - **🟡 Medium Priority**: 관심 키워드 (번역 대상)
    """)
    
    # 현재 키워드 가져오기
    keywords_config = config.get('keywords', {})
    high_keywords = keywords_config.get('priority_high', [])
    medium_keywords = keywords_config.get('priority_medium', [])
    
    col1, col2 = st.columns(2)
    
    with col1:
        st.markdown("#### 🔴 High Priority 키워드")
        
        # 현재 키워드 표시 (삭제 가능)
        st.caption(f"현재 {len(high_keywords)}개")
        
        # 태그 형태로 표시
        if high_keywords:
            cols = st.columns(3)
            for i, kw in enumerate(high_keywords):
                with cols[i % 3]:
                    if st.button(f"❌ {kw}", key=f"del_high_{i}", help=f"'{kw}' 삭제"):
                        high_keywords.remove(kw)
                        config['keywords']['priority_high'] = high_keywords
                        save_config(config)
                        st.rerun()
        
        # 새 키워드 추가
        st.markdown("---")
        new_high = st.text_input("새 High 키워드 추가", key="new_high", placeholder="키워드 입력 후 Enter")
        if new_high and new_high.strip():
            new_kw = new_high.strip().lower()
            if new_kw not in high_keywords:
                if st.button("➕ 추가", key="add_high"):
                    high_keywords.append(new_kw)
                    config['keywords']['priority_high'] = high_keywords
                    save_config(config)
                    st.success(f"'{new_kw}' 추가됨!")
                    st.rerun()
            else:
                st.warning("이미 존재하는 키워드입니다.")
    
    with col2:
        st.markdown("#### 🟡 Medium Priority 키워드")
        
        st.caption(f"현재 {len(medium_keywords)}개")
        
        if medium_keywords:
            cols = st.columns(3)
            for i, kw in enumerate(medium_keywords):
                with cols[i % 3]:
                    if st.button(f"❌ {kw}", key=f"del_med_{i}", help=f"'{kw}' 삭제"):
                        medium_keywords.remove(kw)
                        config['keywords']['priority_medium'] = medium_keywords
                        save_config(config)
                        st.rerun()
        
        st.markdown("---")
        new_medium = st.text_input("새 Medium 키워드 추가", key="new_medium", placeholder="키워드 입력 후 Enter")
        if new_medium and new_medium.strip():
            new_kw = new_medium.strip().lower()
            if new_kw not in medium_keywords:
                if st.button("➕ 추가", key="add_medium"):
                    medium_keywords.append(new_kw)
                    config['keywords']['priority_medium'] = medium_keywords
                    save_config(config)
                    st.success(f"'{new_kw}' 추가됨!")
                    st.rerun()
            else:
                st.warning("이미 존재하는 키워드입니다.")
    
    st.divider()
    
    # 이메일 설정
    st.subheader("📧 이메일 알림")
    
    col1, col2 = st.columns(2)
    with col1:
        st.text_input("받을 이메일", value="dw.gimm@gmail.com", disabled=True)
    with col2:
        st.toggle("이메일 알림 활성화", value=True, disabled=True)
    
    st.caption("💡 이메일 설정은 GitHub Secrets에서 관리됩니다.")
    
    st.divider()
    
    # 전체 설정 보기 (접기)
    with st.expander("📄 전체 설정 파일 보기 (config.yaml)"):
        config_path = Path("./config.yaml")
        if config_path.exists():
            with open(config_path, 'r', encoding='utf-8') as f:
                st.code(f.read(), language='yaml')
        else:
            st.warning("config.yaml을 찾을 수 없습니다.")


if __name__ == "__main__":
    main()
