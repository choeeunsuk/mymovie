import calendar
from datetime import datetime, timedelta
import urllib.parse
from zoneinfo import ZoneInfo

import pandas as pd
import requests
import streamlit as st
import streamlit.components.v1 as components

# Plotly 라이브러리 사용 (설치되어 있지 않은 경우 자동 대비)
try:
    import plotly.express as px

    HAS_PLOTLY = True
except ImportError:
    HAS_PLOTLY = False

st.set_page_config(
    page_title="🎬 시네마 박스오피스 대시보드",
    page_icon="🎬",
    layout="wide",
)

st.title("🎬 시네마 박스오피스 대시보드")

# 비밀 금고에서 인증키 가져오기
KOBIS_KEY = st.secrets["KOBIS_KEY"]


# -------------------------------------------------------------------
# 1. 년 / 월 / 일 별 날짜 선택 UI 및 빠른 이동 버튼
# -------------------------------------------------------------------
st.subheader("📅 조회 날짜 선택")

today_kr = datetime.now(ZoneInfo("Asia/Seoul")).date()
max_date = today_kr - timedelta(days=1)  # 가장 최신 집계일 (어제)

if "query_date" not in st.session_state:
    st.session_state["query_date"] = max_date

# 빠른 날짜 선택 프리셋 버튼
p1, p2, p3, p4, _ = st.columns([1, 1, 1, 1, 2])
if p1.button("어제", use_container_width=True):
    st.session_state["query_date"] = max_date
if p2.button("7일 전", use_container_width=True):
    st.session_state["query_date"] = max_date - timedelta(days=6)
if p3.button("30일 전", use_container_width=True):
    st.session_state["query_date"] = max_date - timedelta(days=29)
if p4.button("1년 전", use_container_width=True):
    st.session_state["query_date"] = max_date - timedelta(days=365)

curr_date = st.session_state["query_date"]

# 년, 월, 일 셀렉트박스 레이아웃
c_yr, c_mo, c_day = st.columns(3)

years = list(range(max_date.year, 2003, -1))
selected_year = c_yr.selectbox(
    "년도 (Year)",
    years,
    index=years.index(curr_date.year) if curr_date.year in years else 0,
)

months = list(range(1, 13))
selected_month = c_mo.selectbox(
    "월 (Month)", months, index=curr_date.month - 1
)

max_days = calendar.monthrange(selected_year, selected_month)[1]
days = list(range(1, max_days + 1))
target_day_idx = (
    curr_date.day - 1 if curr_date.day <= max_days else max_days - 1
)
selected_day = c_day.selectbox("일 (Day)", days, index=target_day_idx)

# 최종 선택된 날짜 검증
try:
    selected_date = datetime(
        selected_year, selected_month, selected_day
    ).date()
except ValueError:
    selected_date = max_date

if selected_date > max_date:
    st.warning(
        f"⚠️ {selected_date.strftime('%Y년 %m월 %d일')}은 아직 집계 전입니다. 가장 최근 집계일({max_date.strftime('%Y-%m-%d')})로 조회합니다."
    )
    selected_date = max_date

st.session_state["query_date"] = selected_date
target_dt = selected_date.strftime("%Y%m%d")

st.caption(
    f"📌 **현재 조회 기준일:** {selected_date.strftime('%Y년 %m월 %d일')}"
)


# -------------------------------------------------------------------
# KOBIS API 데이터 요청
# -------------------------------------------------------------------
url = "https://www.kobis.or.kr/kobisopenapi/webservice/rest/boxoffice/searchDailyBoxOfficeList.json"
res = requests.get(
    url, params={"key": KOBIS_KEY, "targetDt": target_dt}, timeout=10
)

if res.status_code != 200:
    st.error(f"요청이 실패했습니다 (상태코드: {res.status_code})")
    st.stop()

data = res.json()

if "faultInfo" in data:
    st.error(
        "인증키가 올바르지 않습니다. 금고(Secrets)의 KOBIS_KEY를 확인해 주세요."
    )
    st.stop()

box_list = data.get("boxOfficeResult", {}).get("dailyBoxOfficeList", [])

if not box_list:
    st.warning("그날은 아직 집계 전입니다.")
    st.stop()

df = pd.DataFrame(box_list)

# 숫자형 변환
for col in ["rank", "rankInten", "audiCnt", "audiAcc", "scrnCnt", "showCnt"]:
    df[col] = pd.to_numeric(df[col])


# 가공 함수 정의
def format_rank_change(val):
    if val > 0:
        return f":red[▲ {val}]"
    elif val < 0:
        return f":blue[▼ {abs(val)}]"
    else:
        return "-"


def add_trophy(row):
    movie_name = row["movieNm"]
    if row["audiAcc"] >= 1_000_000:
        return f"🏆 {movie_name}"
    return movie_name


df["순위변동"] = df["rankInten"].apply(format_rank_change)
df["movieNm_display"] = df.apply(add_trophy, axis=1)


# -------------------------------------------------------------------
# 2. 1위 영화 대표 이미지(포스터) 및 트레일러(예고편) 가져오기
# -------------------------------------------------------------------
@st.cache_data(ttl=3600)
def fetch_movie_media(movie_name):
    """Secrets에 TMDB_KEY가 등록되어 있다면 TMDB에서 포스터와 공식 트레일러 URL을 가져옵니다."""
    tmdb_key = st.secrets.get("TMDB_KEY", None)
    poster_url = None
    trailer_url = None

    if tmdb_key:
        try:
            # TMDB 영화 검색
            s_url = "https://api.themoviedb.org/3/search/movie"
            r = requests.get(
                s_url,
                params={
                    "api_key": tmdb_key,
                    "query": movie_name,
                    "language": "ko-KR",
                },
                timeout=5,
            )
            if r.status_code == 200:
                results = r.json().get("results", [])
                if results:
                    movie_id = results[0]["id"]
                    if results[0].get("poster_path"):
                        poster_url = f"https://image.tmdb.org/t/p/w500{results[0]['poster_path']}"

                    # 예고편 비디오 조회
                    v_url = (
                        f"https://api.themoviedb.org/3/movie/{movie_id}/videos"
                    )
                    vr = requests.get(
                        v_url,
                        params={"api_key": tmdb_key, "language": "ko-KR"},
                        timeout=5,
                    )
                    if vr.status_code == 200:
                        v_list = vr.json().get("results", [])
                        for v in v_list:
                            if (
                                v.get("site") == "YouTube"
                                and v.get("type") == "Trailer"
                            ):
                                trailer_url = f"https://www.youtube.com/watch?v={v.get('key')}"
                                break
                        if not trailer_url and v_list:
                            trailer_url = f"https://www.youtube.com/watch?v={v_list[0].get('key')}"
        except Exception:
            pass

    return poster_url, trailer_url


st.markdown("---")
st.subheader("👑 오늘의 BOX OFFICE 1위 영화 히어로 갤러리")

top = df.sort_values("rank").iloc[0]
top_movie_name = top["movieNm"]
open_dt = top["openDt"]

poster_url, trailer_url = fetch_movie_media(top_movie_name)

col_poster, col_info, col_trailer = st.columns([1.2, 1.8, 2.5])

with col_poster:
    if poster_url:
        st.image(
            poster_url,
            caption=f"🎬 {top_movie_name}",
            use_container_width=True,
        )
    else:
        # 포스터 이미지 대체용 비주얼 카드
        st.markdown(
            f"""
            <div style="
                background: linear-gradient(135deg, #1e1e2f, #3a3a52);
                padding: 35px 20px;
                border-radius: 16px;
                text-align: center;
                color: #ffffff;
                box-shadow: 0 8px 20px rgba(0,0,0,0.2);
                border: 1px solid #4a4a6a;
            ">
                <div style="font-size: 50px; margin-bottom: 10px;">🍿</div>
                <div style="font-size: 12px; color: #ff4b4b; font-weight: bold;">BOX OFFICE #1</div>
                <h3 style="margin: 8px 0; font-size: 20px; color: #ffd700;">{top_movie_name}</h3>
                <p style="font-size: 13px; color: #b0b0d0; margin-top: 8px;">개봉일: {open_dt}</p>
            </div>
            """,
            unsafe_allow_html=True,
        )

with col_info:
    st.markdown(f"## 🏆 {top_movie_name}")
    st.markdown(f"**🗓️ 개봉일:** `{open_dt}`")
    st.markdown(f"**👥 당일 관객수:** `:red[{top['audiCnt']:,} 명]`")
    st.markdown(f"**🎟️ 누적 관객수:** **`{top['audiAcc']:,} 명`**")
    st.markdown(
        f"**📺 스크린 수:** {top['scrnCnt']:,} 개 | **🎬 상영 횟수:** {top['showCnt']:,} 회"
    )

    if top["audiAcc"] >= 1_000_000:
        st.success(f"🎉 누적 {top['audiAcc']//10000:,}만 관객 돌파 흥행 대작!")

with col_trailer:
    st.markdown("#### 🍿 메인 예고편 (Trailer)")
    if trailer_url:
        st.video(trailer_url)
    else:
        # TMDB 키가 없을 경우 유튜브 검색 결과를 자동 임베드
        search_query = urllib.parse.quote(f"{top_movie_name} 예고편")
        embed_html = f"""
        <iframe width="100%" height="280" src="https://www.youtube-nocookie.com/embed?listType=search&list={search_query}" 
                title="YouTube trailer search" frameborder="0" 
                allow="accelerometer; autoplay; clipboard-write; encrypted-media; gyroscope; picture-in-picture" 
                allowfullscreen style="border-radius: 12px; box-shadow: 0 4px 15px rgba(0,0,0,0.15);">
        </iframe>
        """
        components.html(embed_html, height=290)


# -------------------------------------------------------------------
# 3. 팬시하게 바뀐 관객수 TOP 5 하이라이트
# -------------------------------------------------------------------
st.markdown("---")
st.subheader("🔥 관객수 TOP 5 하이라이트")

# 표 구성 및 열 이름 변경
table = df[
    [
        "rank",
        "순위변동",
        "movieNm_display",
        "movieNm",
        "openDt",
        "audiCnt",
        "audiAcc",
        "scrnCnt",
    ]
].copy()
table.columns = [
    "순위",
    "순위변동",
    "영화명_이모지",
    "영화명",
    "개봉일",
    "관객수",
    "누적관객",
    "스크린수",
]
table = table.sort_values("순위").reset_index(drop=True)

top5_df = table.sort_values("관객수", ascending=False).head(5).copy()
total_top5_audi = top5_df["관객수"].sum()

tab1, tab2 = st.tabs(["📊 인터랙티브 시각화 차트", "🏆 비주얼 랭킹 카드"])

with tab1:
    if HAS_PLOTLY:
        col_chart1, col_chart2 = st.columns([1.8, 1.2])

        with col_chart1:
            # 수평 그라데이션 바 차트
            fig_bar = px.bar(
                top5_df,
                x="관객수",
                y="영화명",
                orientation="h",
                text="관객수",
                title="<b>당일 관객수 TOP 5 비교</b>",
                color="관객수",
                color_continuous_scale="Reds",
            )
            fig_bar.update_traces(
                texttemplate="<b>%{text:,}명</b>",
                textposition="outside",
                marker_line_color="#888",
                marker_line_width=1,
            )
            fig_bar.update_layout(
                yaxis=dict(autorange="reversed"),
                xaxis_title="관객수 (명)",
                yaxis_title="",
                height=350,
                margin=dict(l=10, r=40, t=40, b=10),
                coloraxis_showscale=False,
            )
            st.plotly_chart(fig_bar, use_container_width=True)

        with col_chart2:
            # 관객 점유율 도넛 차트
            fig_pie = px.pie(
                top5_df,
                values="관객수",
                names="영화명",
                title="<b>TOP 5 관객 점유율</b>",
                hole=0.4,
                color_discrete_sequence=px.colors.sequential.RdBu,
            )
            fig_pie.update_traces(
                textinfo="percent+label", textposition="inside"
            )
            fig_pie.update_layout(
                height=350,
                margin=dict(l=10, r=10, t=40, b=10),
                showlegend=False,
            )
            st.plotly_chart(fig_pie, use_container_width=True)
    else:
        st.bar_chart(top5_df.set_index("영화명")["관객수"])

with tab2:
    medals = ["🥇 1위", "🥈 2위", "🥉 3위", "4️⃣ 4위", "5️⃣ 5위"]
    cols = st.columns(5)

    for i, (_, row) in enumerate(top5_df.iterrows()):
        with cols[i]:
            share = (
                (row["관객수"] / total_top5_audi) if total_top5_audi > 0 else 0
            )
            st.markdown(
                f"""
                <div style="
                    background: #f8f9fa;
                    border: 1px solid #e9ecef;
                    border-radius: 12px;
                    padding: 15px;
                    text-align: center;
                    box-shadow: 0 2px 8px rgba(0,0,0,0.05);
                ">
                    <div style="font-size: 18px; font-weight: bold; margin-bottom: 5px;">{medals[i]}</div>
                    <div style="font-size: 15px; font-weight: bold; color: #1e293b; height: 42px; display: flex; align-items: center; justify-content: center; word-break: keep-all;">
                        {row['영화명']}
                    </div>
                    <div style="font-size: 16px; color: #e11d48; font-weight: bold; margin-top: 8px;">
                        {row['관객수']:,}명
                    </div>
                    <div style="font-size: 12px; color: #64748b;">
                        누적 {row['누적관객']:,}명
                    </div>
                </div>
                """,
                unsafe_allow_html=True,
            )
            st.caption(f"TOP5 점유율: {share*100:.1f}%")
            st.progress(float(share))


# -------------------------------------------------------------------
# 전체 TOP 10 데이터프레임
# -------------------------------------------------------------------
st.markdown("---")
st.subheader(
    f"📋 {selected_date.strftime('%Y년 %m월 %d일')} 박스오피스 TOP 10 상세"
)

display_table = table[
    ["순위", "순위변동", "영화명_이모지", "개봉일", "관객수", "누적관객", "스크린수"]
].copy()
display_table.columns = [
    "순위",
    "순위변동",
    "영화명",
    "개봉일",
    "관객수",
    "누적관객",
    "스크린수",
]

st.dataframe(
    display_table,
    column_config={
        "순위변동": st.column_config.TextColumn(
            "순위변동", help="전날 대비 순위 변동"
        )
    },
    hide_index=True,
    use_container_width=True,
)
