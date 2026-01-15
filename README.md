# 📚 Journal Monitor

케이의 학술저널 RSS 모니터링 시스템

## 🎯 기능

- **RSS 자동 수집**: 68개 학술저널에서 신규 논문 수집
- **AI 번역/요약**: Claude API로 제목·초록 번역 및 핵심 요약
- **우선순위 분류**: 통치성, 어셈블리지 등 관심 키워드 기반 자동 분류
- **일일 보고서**: 마크다운 보고서 자동 생성
- **Craft 연동**: Daily Note에 추가할 수 있는 형식 제공

---

## 📦 설치

### 1. 프로젝트 폴더 생성

```bash
# 원하는 위치에 폴더 생성
mkdir -p ~/Documents/JournalMonitor
cd ~/Documents/JournalMonitor

# 이 프로젝트 파일들을 복사
```

### 2. 의존성 설치

```bash
# pip로 설치
pip install -r requirements.txt

# 또는 개별 설치
pip install feedparser pyyaml jinja2 anthropic python-dateutil
```

### 3. 환경 변수 설정

```bash
# ~/.zshrc 또는 ~/.bash_profile에 추가
export ANTHROPIC_API_KEY="your-api-key-here"

# 적용
source ~/.zshrc
```

### 4. OPML 파일 복사

```bash
# Reeder에서 export한 OPML 파일을 복사
cp ~/Downloads/Feeds.opml ~/Documents/JournalMonitor/Feeds.opml
```

### 5. 설정 파일 수정

`config.yaml`에서 경로를 본인 환경에 맞게 수정:

```yaml
paths:
  opml_file: "~/Documents/JournalMonitor/Feeds.opml"
  database: "~/Documents/JournalMonitor/data/journals.db"
  reports_dir: "~/Documents/JournalMonitor/reports"
```

---

## 🚀 사용법

### 기본 실행

```bash
cd ~/Documents/JournalMonitor

# 기본 실행 (최근 24시간)
python main.py

# 48시간 내 논문 수집
python main.py --hours 48

# 번역 없이 수집만
python main.py --no-translate

# 통계 확인
python main.py --stats

# Craft용 콘텐츠 출력
python main.py --craft
```

### 보고서 확인

실행 후 `reports/` 폴더에서 확인:
- `journal_brief_YYYYMMDD.md`: 전체 보고서
- `craft_YYYYMMDD.md`: Craft Daily Note용 간결 버전

---

## ⏰ 자동 실행 설정 (macOS)

### 1. plist 파일 수정

`com.kay.journalmonitor.plist` 파일에서:
- `YOUR_USERNAME`을 본인 사용자명으로 변경
- `YOUR_API_KEY_HERE`를 실제 API 키로 변경

### 2. plist 파일 복사

```bash
cp com.kay.journalmonitor.plist ~/Library/LaunchAgents/
```

### 3. 로그 폴더 생성

```bash
mkdir -p ~/Documents/JournalMonitor/logs
```

### 4. launchd 등록

```bash
# 등록
launchctl load ~/Library/LaunchAgents/com.kay.journalmonitor.plist

# 즉시 실행 테스트
launchctl start com.kay.journalmonitor

# 상태 확인
launchctl list | grep journalmonitor

# 제거 (필요시)
launchctl unload ~/Library/LaunchAgents/com.kay.journalmonitor.plist
```

---

## 🔗 Craft 연동

### 방법 1: 수동 복사

1. `python main.py --craft` 실행
2. 출력된 내용을 복사
3. Craft Daily Note에 붙여넣기

### 방법 2: 파일에서 복사

1. `reports/craft_YYYYMMDD.md` 파일 열기
2. 내용 복사 후 Craft에 붙여넣기

### 방법 3: Claude에게 요청 (MCP 연동)

Claude와 대화 중에:
> "오늘 저널 브리핑을 Craft Daily Note에 추가해줘"

---

## 📁 프로젝트 구조

```
JournalMonitor/
├── config.yaml              # 설정 파일
├── main.py                  # 메인 실행
├── requirements.txt         # 의존성
├── Feeds.opml               # RSS 피드 목록
├── src/
│   ├── __init__.py
│   ├── database.py          # SQLite 관리
│   ├── rss_parser.py        # RSS 파싱
│   ├── summarizer.py        # Claude API 번역/요약
│   └── report_generator.py  # 보고서 생성
├── templates/
│   └── daily_report.md.j2   # 보고서 템플릿
├── data/
│   └── journals.db          # SQLite DB
├── reports/                 # 생성된 보고서
├── logs/                    # 로그 파일
└── com.kay.journalmonitor.plist  # launchd 설정
```

---

## ⚙️ 설정 옵션

### config.yaml

```yaml
# 우선순위 키워드 추가
keywords:
  priority_high:
    - "새로운 키워드"
  priority_medium:
    - "중간 우선순위 키워드"

# 수집 시간 변경
rss:
  fetch_hours: 48  # 48시간으로 변경
```

---

## 🐛 문제 해결

### API 키 오류

```bash
# 환경 변수 확인
echo $ANTHROPIC_API_KEY
```

### RSS 파싱 오류

```bash
# 특정 피드 테스트
python -c "from src.rss_parser import RSSParser; p = RSSParser('Feeds.opml'); print(len(p.feeds))"
```

### 데이터베이스 초기화

```bash
# DB 파일 삭제 후 재실행
rm data/journals.db
python main.py
```

---

## 📝 향후 계획

- [ ] 5단계: 키워드 추출 (keybert)
- [ ] 6단계: 토픽 모델링 (BERTopic)
- [ ] 월간 분석 보고서
- [ ] 웹 대시보드

---

