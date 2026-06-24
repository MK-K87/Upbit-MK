
from __future__ import annotations

import html
from datetime import datetime
from zoneinfo import ZoneInfo

import pandas as pd
import streamlit as st

from excel_export import build_excel_bytes
from strategy_engine import KST, STRATEGY_REGISTRY, run_analysis


st.set_page_config(
    page_title="UPBIT V22 Mobile",
    page_icon="🛡️",
    layout="wide",
    initial_sidebar_state="collapsed",
)

st.markdown(
    """
    <style>
    .block-container {
        padding-top: .8rem;
        padding-bottom: 5rem;
        max-width: 1120px;
    }
    .hero {
        padding: 18px 18px 15px 18px;
        border-radius: 19px;
        background: linear-gradient(135deg, #17365D 0%, #2F75B5 70%, #4F81BD 100%);
        color: white;
        margin-bottom: 12px;
        box-shadow: 0 8px 24px rgba(23,54,93,.22);
    }
    .hero h1 {font-size: 1.62rem; margin: 0 0 5px 0;}
    .hero p {font-size: .86rem; opacity: .92; margin: 0;}
    .candidate-card {
        border: 1px solid rgba(49,91,135,.18);
        border-radius: 18px;
        padding: 15px;
        margin: 10px 0;
        background: white;
        box-shadow: 0 5px 17px rgba(23,54,93,.08);
    }
    .candidate-top {
        display:flex;
        justify-content:space-between;
        align-items:flex-start;
        gap:8px;
    }
    .coin-name {font-size:1.18rem; font-weight:850; color:#17365D;}
    .coin-code {font-size:.76rem; color:#7A869A; margin-top:2px;}
    .score {font-size:1.62rem; font-weight:900; color:#2F75B5;}
    .tag {
        display:inline-block;
        border-radius:999px;
        padding:4px 9px;
        font-size:.72rem;
        font-weight:750;
        margin:3px 3px 3px 0;
    }
    .tag-green {background:#E2F0D9;color:#3B6B22;}
    .tag-blue {background:#D9EAF7;color:#17365D;}
    .tag-orange {background:#FCE4D6;color:#9E480E;}
    .tag-red {background:#F4CCCC;color:#9C0006;}
    .tag-gray {background:#E7E6E6;color:#595959;}
    .tag-purple {background:#E4DFEC;color:#5F497A;}
    .entry-box {
        background:#F6F8FB;
        border-radius:12px;
        padding:10px 12px;
        margin-top:10px;
        font-weight:750;
        color:#17365D;
    }
    .small-grid {
        display:grid;
        grid-template-columns:repeat(3,1fr);
        gap:7px;
        margin-top:11px;
    }
    .small-stat {
        background:#F8FAFC;
        border-radius:11px;
        padding:8px;
        text-align:center;
    }
    .small-stat b {display:block;color:#17365D;font-size:.94rem;}
    .small-stat span {font-size:.69rem;color:#7A869A;}
    .reason {
        font-size:.75rem;
        color:#667085;
        margin-top:9px;
        padding-top:8px;
        border-top:1px dashed #D9E2F3;
    }
    .notice {
        padding:11px 13px;
        background:#FFF8E1;
        border-left:4px solid #ED7D31;
        border-radius:10px;
        font-size:.81rem;
        color:#595959;
        margin:10px 0;
    }
    .pass-box {
        padding:12px 14px;
        background:#E2F0D9;
        border:1px solid #A9D18E;
        border-radius:12px;
        color:#3B6B22;
        font-weight:800;
        margin:8px 0;
    }
    .locked {
        padding:10px 12px;
        background:#EDF4FA;
        border-radius:12px;
        font-size:.79rem;
        color:#17365D;
        margin:8px 0;
    }
    div[data-testid="stMetric"] {
        background:white;
        border:1px solid rgba(49,91,135,.15);
        padding:10px;
        border-radius:14px;
        box-shadow:0 3px 12px rgba(23,54,93,.06);
    }
    .stButton>button, .stDownloadButton>button {
        width:100%;
        border-radius:12px;
        font-weight:800;
        min-height:46px;
    }
    @media (max-width: 640px) {
        .block-container {
            padding-left:.78rem;
            padding-right:.78rem;
            padding-top:.55rem;
        }
        .hero {padding:15px 13px;border-radius:15px;}
        .hero h1 {font-size:1.32rem;}
        .candidate-card {border-radius:15px;padding:13px;}
        [data-testid="stMetricValue"] {font-size:1.22rem;}
    }
    </style>
    """,
    unsafe_allow_html=True,
)


def tag_class(value: str) -> str:
    return {
        "핵심매수": "tag-green",
        "일반매수": "tag-blue",
        "전술매수": "tag-purple",
        "주의매수": "tag-red",
        "관찰": "tag-orange",
        "낮음": "tag-green",
        "보통": "tag-orange",
        "높음": "tag-red",
    }.get(value, "tag-gray")


def safe_float(value, digits=1, default=0.0) -> str:
    try:
        if pd.isna(value):
            return f"{default:.{digits}f}"
        return f"{float(value):.{digits}f}"
    except (TypeError, ValueError):
        return f"{default:.{digits}f}"


def candidate_card(row: pd.Series, *, watch: bool = False):
    name = html.escape(str(row["korean_name"]))
    code = html.escape(str(row["market"]).replace("KRW-", ""))
    v22_class = "관찰" if watch else html.escape(str(row["v22_class"]))
    risk = html.escape(str(row["risk_level"]))
    entry = html.escape(str(row["entry_strategy"]))
    reason = html.escape(str(row["selection_reason"]))
    heat = html.escape(str(row.get("overheat_reason", "") or "과열감점 없음"))
    score = safe_float(row["v22_score"], 1)
    rsi = safe_float(row["RSI14"], 1)
    hit_rate = safe_float(row["hit20_rate"], 1)
    rank = int(row["volume_rank"]) if pd.notna(row["volume_rank"]) else 0

    v17_tag = (
        f'<span class="tag tag-purple">V17 {html.escape(str(row["v17_grade"]))}</span>'
        if bool(row["v17_candidate"])
        else '<span class="tag tag-gray">V17 미선정</span>'
    )
    v20_tag = (
        f'<span class="tag tag-blue">V20 {html.escape(str(row["v20_grade"]))}</span>'
        if bool(row["v20_buy_candidate"]) or bool(row["v20_watch_candidate"])
        else '<span class="tag tag-gray">V20 미선정</span>'
    )
    track_tag = (
        '<span class="tag tag-green">전일 성공추적</span>'
        if bool(row["success_track_candidate"])
        else ""
    )

    st.markdown(
        f"""
        <div class="candidate-card">
          <div class="candidate-top">
            <div>
              <div class="coin-name">{name}</div>
              <div class="coin-code">{code} · 거래대금 {rank}위</div>
            </div>
            <div style="text-align:right">
              <div class="score">{score}</div>
              <div class="coin-code">V22 점수</div>
            </div>
          </div>
          <div style="margin-top:8px">
            <span class="tag {tag_class(v22_class)}">{v22_class}</span>
            {v17_tag}{v20_tag}{track_tag}
            <span class="tag {tag_class(risk)}">리스크 {risk}</span>
          </div>
          <div class="entry-box">📍 {entry}</div>
          <div class="small-grid">
            <div class="small-stat"><b>{rsi}</b><span>RSI14</span></div>
            <div class="small-stat"><b>{hit_rate}%</b><span>20일 도달률</span></div>
            <div class="small-stat"><b>{rank}위</b><span>거래대금</span></div>
          </div>
          <div class="reason">선정: {reason}<br>주의: {heat}</div>
        </div>
        """,
        unsafe_allow_html=True,
    )


st.markdown(
    """
    <div class="hero">
      <h1>🛡️ UPBIT 전략 V22 Mobile</h1>
      <p>V17·V20·V21 독립 보존 · 전일 성공추적 · 자동 누락방지 검증</p>
    </div>
    """,
    unsafe_allow_html=True,
)

with st.expander("⚙️ 실행 설정", expanded=False):
    backtest_days = st.slider("백테스트 일수", 30, 120, 90, 10)
    target_profit_pct = st.slider("목표수익률", 1.5, 5.0, 2.5, 0.1)
    limit_drop_pct = st.slider("지정가 하락폭", 0.0, 4.0, 2.0, 0.5)
    reconstruct = st.toggle("08:30 스냅샷 재구성", value=True)
    exclude_eth = st.toggle("KRW-ETH 제외", value=True)

    st.markdown(
        """
        <div class="locked">
        🔒 보존전략 잠금: V17 거래대금 상위30 · V20 거래대금 상위50 ·
        V17 유동성 조건 · V20 A/A+/A- 기준은 모바일에서 변경할 수 없습니다.
        </div>
        """,
        unsafe_allow_html=True,
    )

overrides = {
    "BACKTEST_DAYS": backtest_days,
    "TARGET_PROFIT": target_profit_pct / 100,
    "LIMIT_BUY_DROP": limit_drop_pct / 100,
    "RECONSTRUCT_0830_SNAPSHOT": reconstruct,
    "EXCLUDE_MARKETS": ["KRW-ETH"] if exclude_eth else [],
}

if st.button("🔄 오늘 V22 분석 실행", type="primary"):
    try:
        st.session_state.pop("v22_excel", None)
        with st.status(
            "V22 데이터를 수집하고 기존 전략을 교차검증하고 있습니다.",
            expanded=True,
        ) as status:
            st.write("① 업비트 KRW 일봉 수집")
            st.write("② 08:30 스냅샷 재구성")
            st.write("③ V17·V20·V21 독립 엔진 실행")
            st.write("④ 누락방지 회귀검증")
            st.write("⑤ 90일 백테스트")
            result = run_analysis(overrides, run_at=datetime.now(KST))
            st.session_state["v22_result"] = result
            status.update(
                label=(
                    f"{result['selection_date']} 기준 분석 완료 · "
                    f"매수 {len(result['today_buy'])}개 / "
                    f"관찰 {len(result['today_watch'])}개"
                ),
                state="complete",
                expanded=False,
            )
    except Exception as exc:
        st.error(f"분석 중 오류가 발생했습니다: {exc}")

result = st.session_state.get("v22_result")
if result is None:
    st.info("위의 **오늘 V22 분석 실행** 버튼을 누르면 모바일 대시보드가 생성됩니다.")
    st.markdown(
        """
        <div class="notice">
        최초 실행은 전체 KRW 종목의 일봉과 08:30 스냅샷을 조회합니다.
        공개 시세 API만 사용하므로 업비트 API 키는 필요하지 않습니다.
        </div>
        """,
        unsafe_allow_html=True,
    )
    st.stop()

today_buy = result["today_buy"]
today_watch = result["today_watch"]
metrics = result["v22_metrics"]
recent30 = result["recent30_metrics"]
snapshot = result["snapshot_info"]
checks = result["regression_checks"]

metric_cols = st.columns(2)
metric_cols[0].metric("V22 매수후보", f"{len(today_buy)}개")
metric_cols[1].metric("관찰후보", f"{len(today_watch)}개")
metric_cols = st.columns(2)
metric_cols[0].metric("V22 90일", f"{metrics['시가매수성공률']:.1%}")
metric_cols[1].metric("최근 30일", f"{recent30['시가매수성공률']:.1%}")

st.caption(
    f"선정일 {result['selection_date']} · "
    f"스냅샷 {snapshot['mode']} ({snapshot['success_rate']:.1%}) · "
    f"누락방지 {int((checks['결과'] == 'PASS').sum())}/{len(checks)} PASS"
)

tab_today, tab_modules, tab_backtest, tab_preserve, tab_download = st.tabs(
    ["오늘", "모듈 비교", "백테스트", "누락방지", "다운로드"]
)

with tab_today:
    st.subheader("오늘 최종 매수후보")
    if today_buy.empty:
        st.warning("현재 V22 매수후보가 없습니다.")
    else:
        for _, candidate in today_buy.iterrows():
            candidate_card(candidate)

    st.subheader("오늘 관찰후보")
    if today_watch.empty:
        st.caption("현재 관찰후보가 없습니다.")
    else:
        for _, candidate in today_watch.iterrows():
            candidate_card(candidate, watch=True)

with tab_modules:
    st.subheader("종목별 기존 엔진 판단")
    relevant = result["today_all"][
        (result["today_all"]["v22_class"] != "비대상")
        | result["today_all"]["v17_candidate"]
        | result["today_all"]["v20_candidate"]
        | result["today_all"]["success_track_candidate"]
    ].copy()

    module_view = relevant[
        [
            "market", "korean_name", "volume_rank",
            "v17_grade", "v17_entry_score", "v17_candidate",
            "v20_grade", "v20_score", "v20_buy_candidate",
            "v20_watch_candidate", "success_track_candidate",
            "module_votes", "risk_level", "v22_score",
            "v22_class", "selection_reason",
        ]
    ].copy()
    module_view.columns = [
        "종목", "한글명", "거래대금순위",
        "V17판정", "V17점수", "V17선정",
        "V20판정", "V20점수", "V20매수",
        "V20관찰", "성공추적",
        "투표", "리스크", "V22점수",
        "V22구분", "선정근거",
    ]
    st.dataframe(module_view, hide_index=True, use_container_width=True)

    st.subheader("후보 선택 상세")
    if not relevant.empty:
        options = {
            f"{row['korean_name']} ({row['market'].replace('KRW-', '')})": index
            for index, row in relevant.iterrows()
        }
        selected = st.selectbox("종목 선택", list(options))
        row = relevant.loc[options[selected]]
        candidate_card(row, watch=row["v22_class"] == "관찰")

        detail_cols = st.columns(2)
        detail_cols[0].metric("V17 진입점수", f"{row['v17_entry_score']:.1f}")
        detail_cols[1].metric("V20 점수", f"{row['v20_score']:.1f}")
        detail_cols = st.columns(2)
        detail_cols[0].metric("최근 10일 도달", f"{int(row['hit10_count'])}회")
        detail_cols[1].metric("최근 5일 도달", f"{int(row['hit5_count'])}회")

with tab_backtest:
    module_perf = result["module_performance"].copy()
    chart_data = module_perf.set_index("전략/모듈")[["시가매수성공률"]]
    st.bar_chart(chart_data, height=310)

    module_display = module_perf[
        [
            "전략/모듈", "평가수", "성공수",
            "시가매수성공률", "지정가체결률", "체결후목표도달률",
        ]
    ].copy()
    for column in ["시가매수성공률", "지정가체결률", "체결후목표도달률"]:
        module_display[column] = module_display[column].map(lambda value: f"{value:.1%}")
    st.dataframe(module_display, hide_index=True, use_container_width=True)

    daily = result["daily_performance"]
    if not daily.empty:
        st.subheader("V22 일별 성공률")
        chart = daily.set_index("매매일")[["V22성공률", "V22_7일평균"]]
        st.line_chart(chart, height=280)

    st.markdown(
        """
        <div class="notice">
        과거 90일 백테스트는 완료 일봉 기반의 08:30 프록시입니다.
        -2% 지정가 목표도달률은 일봉 내 고가·저가 발생 순서를 알 수 없어 참고용입니다.
        </div>
        """,
        unsafe_allow_html=True,
    )

with tab_preserve:
    if (checks["결과"] == "PASS").all():
        st.markdown(
            '<div class="pass-box">✅ V17·V20·성공추적 누락방지 검증 전체 PASS</div>',
            unsafe_allow_html=True,
        )
    else:
        st.error("누락방지 검증에 실패한 항목이 있습니다.")

    st.dataframe(checks, hide_index=True, use_container_width=True)

    st.subheader("보존후보 상세")
    preserve = result["preservation_detail"].copy()
    st.dataframe(preserve, hide_index=True, use_container_width=True)

    st.subheader("잠금 전략 모듈")
    registry = pd.DataFrame([
        {
            "모듈": name,
            "잠금": module["locked"],
            "보존목적": module["purpose"],
        }
        for name, module in STRATEGY_REGISTRY.items()
    ])
    st.dataframe(registry, hide_index=True, use_container_width=True)

with tab_download:
    st.subheader("V22 Excel")
    st.caption(
        "Dashboard, 최종후보, 모듈비교, 누락방지검증, 백테스트를 포함한 Excel을 생성합니다."
    )

    if "v22_excel" not in st.session_state:
        if st.button("📊 V22 Excel 생성"):
            with st.spinner("V22 Excel을 생성하고 있습니다."):
                st.session_state["v22_excel"] = build_excel_bytes(result)

    if "v22_excel" in st.session_state:
        filename = (
            "upbit_strategy_v22_MOBILE_PRESERVATION_"
            f"{datetime.now(ZoneInfo('Asia/Seoul')).strftime('%Y%m%d_%H%M')}.xlsx"
        )
        st.download_button(
            "⬇️ V22 Excel 다운로드",
            data=st.session_state["v22_excel"],
            file_name=filename,
            mime="application/vnd.openxmlformats-officedocument.spreadsheetml.sheet",
            type="primary",
        )

    candidate_csv = result["today_all"].to_csv(index=False).encode("utf-8-sig")
    st.download_button(
        "⬇️ 후보 전체 CSV",
        data=candidate_csv,
        file_name=f"v22_candidates_{result['selection_date']}.csv",
        mime="text/csv",
    )

st.markdown(
    """
    <div class="notice">
    본 앱은 투자 판단을 보조하는 통계 도구이며 수익을 보장하지 않습니다.
    실제 주문 전 호가·거래대금·시장 급변 여부를 다시 확인하세요.
    </div>
    """,
    unsafe_allow_html=True,
)
