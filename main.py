from datetime import datetime, timedelta
from zoneinfo import ZoneInfo
import pandas as pd
import requests
import streamlit as st

st.set_page_config(page_title="박스오피스 대시보드", layout="wide")
st.title("🎬 일별 박스오피스 대시보드")

# 비밀 금고에서 인증키 꺼내기
KOBIS_KEY = st.secrets["KOBIS_KEY"]

# 한국 시간 기준 어제 날짜 계산 (선택 가능한 최신 날짜)
today_kr = datetime.now(ZoneInfo("Asia/Seoul")).date()
max_date = today_kr - timedelta(days=1)

# 1. 날짜 선택기 (기본값: 어제, 최대 선택 가능일: 어제)
selected_date = st.date_input(
    "조회할 날짜를 선택하세요",
    value=max_date,
    max_value=max_date,
)

target_dt = selected_date.strftime("%Y%m%d")

url = "https://www.kobis.or.kr/kobisopenapi/webservice/rest/boxoffice/searchDailyBoxOfficeList.json"
res = requests.get(
    url, params={"key": KOBIS_KEY, "targetDt": target_dt}, timeout=10
)

if res.status_code != 200:
    st.error(f"요청이 실패했습니다 (상태코드: {res.status_code})")
    st.stop()

data = res.json()

# 인증키 오류 처리
if "faultInfo" in data:
    st.error(
        "인증키가 올바르지 않습니다. 금고(Secrets)의 KOBIS_KEY를 확인해 주세요."
    )
    st.stop()

box_list = data.get("boxOfficeResult", {}).get("dailyBoxOfficeList", [])

# 2. 고른 날짜에 데이터가 없을 때의 안내 메시지 변경
if not box_list:
    st.warning("그날은 아직 집계 전입니다.")
    st.stop()

df = pd.DataFrame(box_list)

# 숫자로 변환 (rankInten 추가)
for col in ["rank", "rankInten", "audiCnt", "audiAcc", "scrnCnt", "showCnt"]:
    df[col] = pd.to_numeric(df[col])


# 3. 순위 변동(rankInten) 화살표 가공 함수
def format_rank_change(val):
    if val > 0:
        return f":red[▲ {val}]"  # 양수: 빨간 위 화살표
    elif val < 0:
        return f":blue[▼ {abs(val)}]"  # 음수: 파란 아래 화살표
    else:
        return "-"  # 변동 없음


# 4. 100만 관객 이상 트로피 이모지 추가 함수
def add_trophy(row):
    movie_name = row["movieNm"]
    if row["audiAcc"] >= 1_000_000:
        return f"🏆 {movie_name}"
    return movie_name


# 데이터 가공 적용
df["순위변동"] = df["rankInten"].apply(format_rank_change)
df["movieNm_display"] = df.apply(add_trophy, axis=1)

# 1위 영화 지표 카드 세 장
top = df.sort_values("rank").iloc[0]
c1, c2, c3 = st.columns(3)
c1.metric("선택일 1위", top["movieNm"])
c2.metric("당일 관객수", f"{top['audiCnt']:,}명")
c3.metric("누적 관객", f"{top['audiAcc']:,}명")

# 표 구성 및 열 이름 변경
table = df[
    [
        "rank",
        "순위변동",
        "movieNm_display",
        "openDt",
        "audiCnt",
        "audiAcc",
        "scrnCnt",
    ]
].copy()
table.columns = [
    "순위",
    "순위변동",
    "영화명",
    "개봉일",
    "관객수",
    "누적관객",
    "스크린수",
]
table = table.sort_values("순위").reset_index(drop=True)

st.subheader(f"📋 {selected_date.strftime('%Y년 %m월 %d일')} 박스오피스 TOP 10")

# 마크다운 색상 적용을 위한 st.dataframe column_config 설정
st.dataframe(
    table,
    column_config={
        "순위변동": st.column_config.TextColumn(
            "순위변동",
            help="전날 대비 순위 변동",
        )
    },
    hide_index=True,
)

st.subheader("📈 관객수 상위 5편")
top5 = table.sort_values("관객수", ascending=False).head(5)
st.bar_chart(top5.set_index("영화명")["관객수"])
