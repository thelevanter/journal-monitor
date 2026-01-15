"""
📚 Journal Monitor Dashboard
케이의 학술논문 모니터링 대시보드
"""

import streamlit as st
import sqlite3
import pandas as pd
from pathlib import Path
from datetime import datetime, timedelta
import plotly.express as px
import plotly.graph_objects as go

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
                     days: int = None, search: str = None, limit: int = 100) -> pd.DataFrame:
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
            query += " AND (a.title LIKE ? OR a.abstract LIKE ? OR a.title_ko LIKE ?)"
            search_term = f"%{search}%"
            params.extend([search_term, search_term, search_term])
        
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
    
    def get_keyword_stats(self) -> pd.DataFrame:
        """키워드 통계"""
        query = """
            SELECT keywords_matched
            FROM articles
            WHERE keywords_matched IS NOT NULL AND keywords_matched != ''
        """
        
        with self.get_connection() as conn:
            df = pd.read_sql_query(query, conn)
        
        # 키워드 파싱 및 집계
        import json
        keyword_counts = {}
        for _, row in df.iterrows():
            keywords = row['keywords_matched']
            if keywords:
                try:
                    # JSON 형식인 경우
                    kw_list = json.loads(keywords)
                    if isinstance(kw_list, list):
                        for kw in kw_list:
                            kw = str(kw).strip()
                            if kw:
                                keyword_counts[kw] = keyword_counts.get(kw, 0) + 1
                except (json.JSONDecodeError, TypeError):
                    # 콤마 구분 문자열인 경우
                    for kw in keywords.split(','):
                        kw = kw.strip()
                        if kw:
                            keyword_counts[kw] = keyword_counts.get(kw, 0) + 1
        
        result = pd.DataFrame([
            {'keyword': k, 'count': v} 
            for k, v in sorted(keyword_counts.items(), key=lambda x: -x[1])
        ])
        
        return result
    
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


def render_article_card(article: pd.Series):
    """논문 카드 렌더링"""
    priority = article.get('priority', 'normal') or 'normal'
    priority_emoji = {'high': '🔴', 'medium': '🟡', 'normal': '⚪', 'low': '⚪'}.get(priority, '⚪')
    
    # 제목: 한국어(영어) 형식
    title_en = article.get('title', 'No Title')
    title_ko = article.get('title_ko', '')
    
    if title_ko:
        display_title = f"{title_ko} ({title_en})"
    else:
        display_title = title_en
    
    # 저널 및 날짜
    journal = article.get('journal_name', 'Unknown')
    fetched = article.get('fetched_at', '')[:10] if article.get('fetched_at') else ''
    
    # 키워드
    keywords = article.get('keywords_matched', '')
    if keywords:
        try:
            import json
            kw_list = json.loads(keywords)
            if isinstance(kw_list, list):
                keywords = ', '.join(kw_list)
        except:
            pass
    
    with st.container():
        col1, col2 = st.columns([0.95, 0.05])
        
        with col1:
            st.markdown(f"### {priority_emoji} {display_title}")
            st.caption(f"📰 {journal} · 📅 {fetched}")
            
            if keywords:
                st.markdown(f"🏷️ `{keywords}`")
        
        with col2:
            if article.get('url'):
                st.link_button("🔗", article['url'], help="원문 보기")
        
        # 초록 (접기/펼치기) - 영문 + 한국어 병기
        abstract_en = article.get('abstract', '')
        abstract_ko = article.get('abstract_ko', '')
        summary_ko = article.get('summary_ko', '')
        
        if abstract_en or abstract_ko or summary_ko:
            with st.expander("📄 상세 보기"):
                # 요약이 있으면 먼저 표시
                if summary_ko:
                    st.markdown("**💡 요약:**")
                    st.markdown(summary_ko)
                    st.divider()
                
                # 영문 초록 전체
                if abstract_en:
                    st.markdown("**📝 Abstract (영문):**")
                    st.markdown(abstract_en)
                
                # 한국어 번역 초록
                if abstract_ko:
                    st.markdown("")
                    st.markdown("**📝 초록 (한국어 번역):**")
                    st.markdown(abstract_ko)
                
                # DOI
                if article.get('doi'):
                    st.divider()
                    st.markdown(f"**DOI:** `{article['doi']}`")
        
        st.divider()


def main():
    """메인 대시보드"""
    
    # 데이터베이스 경로 설정
    db_path = Path("./data/journals.db")
    
    if not db_path.exists():
        st.error(f"데이터베이스를 찾을 수 없습니다: {db_path}")
        st.info("JournalMonitor를 먼저 실행해주세요.")
        return
    
    db = DashboardDB(str(db_path))
    
    # 사이드바
    with st.sidebar:
        st.title("📚 Journal Monitor")
        st.caption("케이의 학술논문 모니터링")
        
        st.divider()
        
        # 메뉴 선택
        menu = st.radio(
            "메뉴",
            ["🏠 홈", "📑 논문 목록", "📈 통계", "⚙️ 설정"],
            label_visibility="collapsed"
        )
        
        st.divider()
        
        # 빠른 통계
        stats = db.get_stats()
        st.metric("총 논문", f"{stats['total']:,}편")
        
        col1, col2 = st.columns(2)
        with col1:
            st.metric("🔴 High", stats['high'])
        with col2:
            st.metric("🟡 Medium", stats['medium'])
        
        st.metric("오늘 수집", f"{stats['today']}편")
    
    # 메인 컨텐츠
    if menu == "🏠 홈":
        render_home(db, stats)
    elif menu == "📑 논문 목록":
        render_articles(db)
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
        st.metric(
            "오늘 수집",
            f"{stats['today']}편",
            delta=None
        )
    
    with col2:
        st.metric(
            "이번 주",
            f"{stats['week']}편"
        )
    
    with col3:
        st.metric(
            "🔴 High Priority",
            f"{stats['high']}편"
        )
    
    with col4:
        st.metric(
            "초록 보유율",
            f"{stats['with_abstract'] / stats['total'] * 100:.1f}%" if stats['total'] > 0 else "0%"
        )
    
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
            render_article_card(article)
    else:
        st.info("High priority 논문이 없습니다.")


def render_articles(db: DashboardDB):
    """논문 목록 화면"""
    st.title("📑 논문 목록")
    
    # 필터
    col1, col2, col3, col4 = st.columns(4)
    
    with col1:
        priority_filter = st.selectbox(
            "우선순위",
            ["전체", "high", "medium", "normal"]
        )
    
    with col2:
        journals = ["전체"] + db.get_journals()
        journal_filter = st.selectbox("저널", journals)
    
    with col3:
        days_options = [("전체", None), ("오늘", 1), ("최근 7일", 7), ("최근 30일", 30)]
        days_filter = st.selectbox(
            "기간",
            days_options,
            format_func=lambda x: x[0]
        )
    
    with col4:
        search = st.text_input("🔍 검색", placeholder="제목, 초록 검색...")
    
    st.divider()
    
    # 논문 목록
    articles = db.get_articles(
        priority=priority_filter if priority_filter != "전체" else None,
        journal=journal_filter if journal_filter != "전체" else None,
        days=days_filter[1],
        search=search if search else None,
        limit=50
    )
    
    st.caption(f"총 {len(articles)}편")
    
    if not articles.empty:
        for _, article in articles.iterrows():
            render_article_card(article)
    else:
        st.info("조건에 맞는 논문이 없습니다.")


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
    
    st.info("🚧 설정 기능은 추후 업데이트 예정입니다.")
    
    st.subheader("현재 설정")
    
    # config.yaml 읽기 시도
    config_path = Path("./config.yaml")
    if config_path.exists():
        with open(config_path, 'r', encoding='utf-8') as f:
            st.code(f.read(), language='yaml')
    else:
        st.warning("config.yaml을 찾을 수 없습니다.")
    
    st.divider()
    
    st.subheader("📧 이메일 알림")
    st.text_input("받을 이메일", value="dw.gimm@gmail.com", disabled=True)
    st.toggle("이메일 알림 활성화", value=True, disabled=True)
    
    st.divider()
    
    st.subheader("🏷️ 키워드 설정")
    st.text_area(
        "High Priority 키워드",
        value="governmentality, assemblage, new materialism, Foucault, Deleuze, Lefebvre",
        disabled=True
    )


if __name__ == "__main__":
    main()
