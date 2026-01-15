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
import yaml
import json

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


def render_article_card(article: pd.Series):
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
                    st.markdown(f"**DOI:** `{article['doi']}`")
        
        st.divider()


def render_today_keywords(db: DashboardDB):
    """오늘의 키워드 인포그래픽"""
    today_kw = db.get_today_keywords()
    
    if today_kw.empty:
        st.info("오늘 수집된 논문에서 매칭된 키워드가 없습니다.")
        return
    
    # 상위 10개 키워드
    top_keywords = today_kw.head(10)
    
    # 두 가지 시각화: 버블 뱃지 + 가로 막대
    col1, col2 = st.columns([1, 1])
    
    with col1:
        # 키워드 버블 뱃지 (HTML)
        st.markdown("#### 🏷️ 오늘의 연구 키워드")
        
        badges_html = '<div style="display: flex; flex-wrap: wrap; gap: 8px; padding: 15px; background: linear-gradient(135deg, #f5f7fa 0%, #e4e8ec 100%); border-radius: 12px;">'
        
        max_count = top_keywords['count'].max() if not top_keywords.empty else 1
        
        for _, row in top_keywords.iterrows():
            kw = row['keyword']
            count = row['count']
            priority = row.get('priority', 'normal')
            
            # 크기 계산 (count에 비례)
            size_ratio = count / max_count
            font_size = int(12 + size_ratio * 6)  # 12px ~ 18px
            
            # 색상: high=빨강계열, medium=주황계열, 기타=파랑계열
            if priority == 'high':
                bg_color = f"rgba(255, 75, 75, {0.6 + size_ratio * 0.4})"
                text_color = "white"
            elif priority == 'medium':
                bg_color = f"rgba(255, 165, 0, {0.6 + size_ratio * 0.4})"
                text_color = "#333"
            else:
                bg_color = f"rgba(74, 144, 217, {0.5 + size_ratio * 0.4})"
                text_color = "white"
            
            badges_html += f'''
                <span style="
                    background: {bg_color};
                    color: {text_color};
                    padding: 6px 14px;
                    border-radius: 20px;
                    font-size: {font_size}px;
                    font-weight: 500;
                    display: inline-flex;
                    align-items: center;
                    gap: 6px;
                    box-shadow: 0 2px 4px rgba(0,0,0,0.1);
                ">
                    {kw}
                    <span style="
                        background: rgba(255,255,255,0.3);
                        padding: 2px 6px;
                        border-radius: 10px;
                        font-size: 11px;
                    ">{count}</span>
                </span>
            '''
        
        badges_html += '</div>'
        st.markdown(badges_html, unsafe_allow_html=True)
        
        # 범례
        st.caption("🔴 High Priority · 🟡 Medium Priority · 🔵 기타")
    
    with col2:
        # 가로 막대 차트
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
                height=300,
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
    
    with st.sidebar:
        st.title("📚 Journal Monitor")
        st.caption("케이의 학술논문 모니터링")
        
        st.divider()
        
        menu = st.radio(
            "메뉴",
            ["🏠 홈", "📑 논문 목록", "📈 통계", "⚙️ 설정"],
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
            render_article_card(article)
    else:
        st.info("High priority 논문이 없습니다.")


def render_articles(db: DashboardDB):
    """논문 목록 화면"""
    st.title("📑 논문 목록")
    
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
        search = st.text_input("🔍 검색", placeholder="제목, 초록 검색...")
    
    st.divider()
    
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
