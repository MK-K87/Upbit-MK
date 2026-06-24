
# ============================================================
# 1. 환경설정 및 전략 보존 레지스트리
# ============================================================
import os
import time
import math
import warnings
from datetime import datetime, timedelta, time as dt_time, timezone
from zoneinfo import ZoneInfo
from collections import defaultdict

import numpy as np
import pandas as pd
import requests
from requests.adapters import HTTPAdapter
from urllib3.util.retry import Retry

warnings.filterwarnings("ignore")

KST = ZoneInfo("Asia/Seoul")
UTC = timezone.utc

CONFIG = {
    "LOOKBACK_DAYS": 200,
    "BACKTEST_DAYS": 90,
    "TARGET_PROFIT": 0.025,
    "LIMIT_BUY_DROP": 0.020,
    "V17_TOP_N_VOLUME": 30,
    "V20_TOP_N_VOLUME": 50,
    "V17_BUY_MIN": 80,
    "V17_A_PLUS_MIN": 85,
    "V20_A_PLUS_MIN": 90,
    "V20_A_MIN": 80,
    "V20_A_MINUS_MIN": 75,
    "MIN_CURRENT_TURNOVER": 1_000_000_000,
    "MIN_AVG5_TURNOVER": 2_000_000_000,
    "SELECTION_CUTOFF_HOUR": 8,
    "SELECTION_CUTOFF_MINUTE": 30,
    "RECONSTRUCT_0830_SNAPSHOT": True,
    "MIN_SNAPSHOT_SUCCESS_RATE": 0.90,
    "SLEEP_SEC": 0.13,
    "MAX_RETRIES": 7,
    "REQUEST_TIMEOUT": 15,
    "EXCLUDE_MARKETS": ["KRW-ETH"],
    "OUTPUT_DIR": "/content",
    "AUTO_DOWNLOAD": True,
}

STRATEGY_REGISTRY = {
    "V17_LEGACY": {
        "enabled": True,
        "locked": True,
        "purpose": "상위30 + 전일성공추적 + 단기목표도달 + 유동성 + 약한과열감점",
        "required_columns": [
            "v17_raw_score", "v17_entry_score", "v17_candidate",
            "v17_grade", "v17_universe", "liquidity_pass",
        ],
    },
    "V20_CORE": {
        "enabled": True,
        "locked": True,
        "purpose": "상위50 + 20/10/5일 도달 + 3일상승 + 평균고가 + 순위급상승 + 시장강도",
        "required_columns": [
            "v20_score", "v20_grade", "v20_candidate",
            "v20_buy_candidate", "v20_watch_candidate",
        ],
    },
    "V21_QUALITY": {
        "enabled": True,
        "locked": True,
        "purpose": "과열감점 + 리스크 + 추천진입 + A/A+와 A- 분리 + 장기검증",
        "required_columns": [
            "overheat_penalty", "overheat_reason",
            "risk_level", "entry_strategy",
        ],
    },
    "V22_PRESERVATION": {
        "enabled": True,
        "locked": True,
        "purpose": "기존 후보 자동누락 금지 + 모듈투표 + 회귀검증",
        "required_columns": [
            "module_votes", "legacy_selected", "v22_score",
            "v22_class", "selection_reason", "preservation_status",
        ],
    },
}




# ============================================================
# 2. 업비트 공개 시세 API 및 08:30 스냅샷 재구성
# ============================================================
UPBIT_BASE_URL = "https://api.upbit.com"

retry = Retry(
    total=CONFIG["MAX_RETRIES"],
    connect=CONFIG["MAX_RETRIES"],
    read=CONFIG["MAX_RETRIES"],
    backoff_factor=0.7,
    status_forcelist=[429, 500, 502, 503, 504],
    allowed_methods=["GET"],
)

SESSION = requests.Session()
SESSION.mount("https://", HTTPAdapter(max_retries=retry))
SESSION.headers.update({
    "Accept": "application/json",
    "User-Agent": "Mozilla/5.0 Upbit-V22-Preservation-Colab",
})


def api_get(path: str, params: dict | None = None):
    last_error = None
    for attempt in range(1, CONFIG["MAX_RETRIES"] + 1):
        try:
            response = SESSION.get(
                f"{UPBIT_BASE_URL}{path}",
                params=params,
                timeout=CONFIG["REQUEST_TIMEOUT"],
            )
            if response.status_code == 429:
                time.sleep(min(1.0 + attempt * 0.7, 6.0))
                continue
            response.raise_for_status()
            return response.json()
        except Exception as exc:
            last_error = exc
            time.sleep(min(attempt * 0.8, 6.0))
    raise RuntimeError(f"업비트 API 요청 실패: {path} / {last_error}")


def get_krw_markets() -> pd.DataFrame:
    raw = api_get("/v1/market/all", {"is_details": "false"})
    markets = pd.DataFrame(raw)
    if markets.empty:
        raise RuntimeError("업비트 마켓 목록을 받지 못했습니다.")

    markets = markets[markets["market"].str.startswith("KRW-", na=False)].copy()
    markets = markets[~markets["market"].isin(CONFIG["EXCLUDE_MARKETS"])].copy()

    required = ["market", "korean_name", "english_name"]
    missing = [column for column in required if column not in markets.columns]
    if missing:
        raise RuntimeError(f"마켓 응답 필드 부족: {missing}")

    return (
        markets[required]
        .drop_duplicates("market")
        .sort_values("market")
        .reset_index(drop=True)
    )


def fetch_day_candles(market: str, count: int) -> pd.DataFrame:
    raw = api_get(
        "/v1/candles/days",
        {"market": market, "count": min(int(count), 200)},
    )
    if not raw:
        return pd.DataFrame()

    frame = pd.DataFrame(raw).rename(columns={
        "candle_date_time_kst": "date",
        "opening_price": "open",
        "high_price": "high",
        "low_price": "low",
        "trade_price": "close",
        "candle_acc_trade_volume": "volume",
        "candle_acc_trade_price": "turnover",
    })

    needed = ["date", "open", "high", "low", "close", "volume", "turnover"]
    if not set(needed).issubset(frame.columns):
        return pd.DataFrame()

    frame = frame[needed].copy()
    frame["date"] = pd.to_datetime(frame["date"], errors="coerce")
    for column in ["open", "high", "low", "close", "volume", "turnover"]:
        frame[column] = pd.to_numeric(frame[column], errors="coerce")

    frame = (
        frame.dropna(subset=["date", "open", "high", "low", "close"])
        .drop_duplicates("date")
        .sort_values("date")
        .reset_index(drop=True)
    )
    frame["market"] = market
    return frame


def fetch_0830_snapshot(market: str, selection_date) -> dict | None:
    # 전일 09:00 KST부터 당일 08:30 KST 직전까지 30분 캔들을 합산
    session_start = datetime.combine(selection_date, dt_time(9, 0), tzinfo=KST)
    cutoff = datetime.combine(
        selection_date + timedelta(days=1),
        dt_time(CONFIG["SELECTION_CUTOFF_HOUR"], CONFIG["SELECTION_CUTOFF_MINUTE"]),
        tzinfo=KST,
    )
    to_utc = cutoff.astimezone(UTC).strftime("%Y-%m-%dT%H:%M:%SZ")

    raw = api_get(
        "/v1/candles/minutes/30",
        {"market": market, "to": to_utc, "count": 60},
    )
    if not raw:
        return None

    frame = pd.DataFrame(raw).rename(columns={
        "candle_date_time_kst": "date",
        "opening_price": "open",
        "high_price": "high",
        "low_price": "low",
        "trade_price": "close",
        "candle_acc_trade_volume": "volume",
        "candle_acc_trade_price": "turnover",
    })
    needed = ["date", "open", "high", "low", "close", "volume", "turnover"]
    if not set(needed).issubset(frame.columns):
        return None

    frame = frame[needed].copy()
    frame["date"] = pd.to_datetime(frame["date"], errors="coerce")
    for column in ["open", "high", "low", "close", "volume", "turnover"]:
        frame[column] = pd.to_numeric(frame[column], errors="coerce")

    start_naive = pd.Timestamp(session_start.replace(tzinfo=None))
    cutoff_naive = pd.Timestamp(cutoff.replace(tzinfo=None))
    frame = frame[
        (frame["date"] >= start_naive)
        & (frame["date"] < cutoff_naive)
    ].sort_values("date")

    if frame.empty:
        return None

    return {
        "market": market,
        "open": float(frame.iloc[0]["open"]),
        "high": float(frame["high"].max()),
        "low": float(frame["low"].min()),
        "close": float(frame.iloc[-1]["close"]),
        "volume": float(frame["volume"].sum()),
        "turnover": float(frame["turnover"].sum()),
        "snapshot_candle_count": int(len(frame)),
        "snapshot_source": "30MIN_RECONSTRUCTED_0830",
    }


def collect_daily_data(markets: pd.DataFrame) -> pd.DataFrame:
    frames = []
    total = len(markets)

    for index, row in markets.iterrows():
        market = row["market"]
        try:
            frame = fetch_day_candles(market, CONFIG["LOOKBACK_DAYS"])
            if not frame.empty:
                frame["korean_name"] = row["korean_name"]
                frame["english_name"] = row["english_name"]
                frames.append(frame)
        except Exception as exc:
            print(f"[일봉 경고] {market}: {exc}")

        if (index + 1) % 20 == 0 or index + 1 == total:
            print(f"일봉 수집 {index + 1}/{total}")
        time.sleep(CONFIG["SLEEP_SEC"])

    if not frames:
        raise RuntimeError("수집된 일봉 데이터가 없습니다.")

    result = pd.concat(frames, ignore_index=True)
    result["snapshot_source"] = "DAILY_API"
    result["snapshot_candle_count"] = np.nan
    return result.sort_values(["market", "date"]).reset_index(drop=True)


def apply_exact_0830_snapshot(
    daily_df: pd.DataFrame,
    markets: pd.DataFrame,
    run_at: datetime,
) -> tuple[pd.DataFrame, dict]:
    result = daily_df.copy()

    if not CONFIG["RECONSTRUCT_0830_SNAPSHOT"]:
        return result, {
            "mode": "RECONSTRUCTION_DISABLED",
            "success": 0,
            "attempted": 0,
            "success_rate": 0,
            "warning": "08:30 재구성이 비활성화되었습니다.",
        }

    if run_at < CUTOFF_AT:
        return result, {
            "mode": "EARLY_LIVE_PARTIAL",
            "success": 0,
            "attempted": 0,
            "success_rate": 0,
            "warning": "08:30 이전 실행이므로 아직 완성되지 않은 부분 일봉입니다.",
        }

    snapshots = []
    total = len(markets)
    for index, market in enumerate(markets["market"], start=1):
        try:
            snapshot = fetch_0830_snapshot(market, SELECTION_DATE)
            if snapshot:
                snapshots.append(snapshot)
        except Exception as exc:
            print(f"[08:30 경고] {market}: {exc}")

        if index % 20 == 0 or index == total:
            print(f"08:30 스냅샷 재구성 {index}/{total}")
        time.sleep(CONFIG["SLEEP_SEC"])

    snapshot_map = {item["market"]: item for item in snapshots}
    replaced = 0

    for market, snapshot in snapshot_map.items():
        mask = (
            (result["market"] == market)
            & (result["date"].dt.date == SELECTION_DATE)
        )
        if not mask.any():
            continue
        for column in ["open", "high", "low", "close", "volume", "turnover"]:
            result.loc[mask, column] = snapshot[column]
        result.loc[mask, "snapshot_source"] = snapshot["snapshot_source"]
        result.loc[mask, "snapshot_candle_count"] = snapshot["snapshot_candle_count"]
        replaced += 1

    success_rate = replaced / max(total, 1)
    warning = ""
    if success_rate < CONFIG["MIN_SNAPSHOT_SUCCESS_RATE"]:
        warning = (
            f"08:30 스냅샷 성공률이 {success_rate:.1%}로 기준 "
            f"{CONFIG['MIN_SNAPSHOT_SUCCESS_RATE']:.0%} 미만입니다."
        )

    return result, {
        "mode": "EXACT_0830_RECONSTRUCTED",
        "success": replaced,
        "attempted": total,
        "success_rate": success_rate,
        "warning": warning,
    }



# ============================================================
# 3. 공통 지표 및 V17 / V20 / V21 독립 엔진
# ============================================================
def calc_rsi(series: pd.Series, period: int = 14) -> pd.Series:
    delta = series.diff()
    gain = delta.clip(lower=0)
    loss = -delta.clip(upper=0)
    average_gain = gain.ewm(
        alpha=1 / period, adjust=False, min_periods=period
    ).mean()
    average_loss = loss.ewm(
        alpha=1 / period, adjust=False, min_periods=period
    ).mean()
    relative_strength = average_gain / average_loss.replace(0, np.nan)
    rsi = 100 - (100 / (1 + relative_strength))
    return rsi.where(average_loss != 0, 100).clip(0, 100)


def add_common_features(group: pd.DataFrame) -> pd.DataFrame:
    frame = group.sort_values("date").copy()
    frame["intraday_high_return"] = frame["high"] / frame["open"] - 1
    frame["day_return"] = frame["close"] / frame["open"] - 1
    frame["day_return_pct"] = frame["day_return"] * 100
    frame["target_hit"] = (
        frame["high"] >= frame["open"] * (1 + CONFIG["TARGET_PROFIT"])
    )
    frame["hit20_count"] = frame["target_hit"].rolling(20, min_periods=10).sum()
    frame["hit20_rate"] = (
        frame["target_hit"].rolling(20, min_periods=10).mean() * 100
    )
    frame["hit10_count"] = frame["target_hit"].rolling(10, min_periods=5).sum()
    frame["hit5_count"] = frame["target_hit"].rolling(5, min_periods=3).sum()
    frame["hit3_count"] = frame["target_hit"].rolling(3, min_periods=2).sum()
    frame["rise3_pct"] = (frame["close"] / frame["close"].shift(3) - 1) * 100
    frame["rise5_pct"] = (frame["close"] / frame["close"].shift(5) - 1) * 100
    frame["avg_high5_pct"] = (
        frame["intraday_high_return"].rolling(5, min_periods=3).mean() * 100
    )
    frame["turnover_5_avg"] = frame["turnover"].rolling(5, min_periods=3).mean()
    frame["turnover_20_avg"] = frame["turnover"].rolling(
        20, min_periods=10
    ).mean()
    frame["turnover_ratio_5_20"] = (
        frame["turnover_5_avg"]
        / frame["turnover_20_avg"].replace(0, np.nan)
    )
    frame["RSI14"] = calc_rsi(frame["close"], 14)
    body = (frame["close"] - frame["open"]).abs()
    upper_wick = frame["high"] - frame[["open", "close"]].max(axis=1)
    candle_range = frame["high"] - frame["low"]
    frame["upper_wick_body_ratio"] = upper_wick / body.replace(0, np.nan)
    frame["upper_wick_range_ratio"] = upper_wick / candle_range.replace(0, np.nan)
    frame["prev_target_hit"] = frame["target_hit"].shift(1).fillna(False)
    return frame


# ---------------- V17 Legacy Engine ----------------
def v17_hit20_score(value):
    return 0 if pd.isna(value) else min(float(value) / 6.0, 10.0)


def v17_hit5_score(value):
    return 0 if pd.isna(value) else min(float(value) * 6.0, 30.0)


def v17_hit3_score(value):
    return 0 if pd.isna(value) else min(float(value) * 5.0, 15.0)


def v17_avg_high_score(value):
    if pd.isna(value):
        return 0
    if value >= 4:
        return 8
    if value >= 3:
        return 6
    if value >= 2:
        return 4
    if value >= 1:
        return 2
    return 0


def v17_turnover_score(row):
    ratio = row["turnover_ratio_5_20"]
    current = row["turnover"]
    if pd.isna(ratio):
        return 0
    if ratio >= 1.5 and current >= 5_000_000_000:
        return 20
    if ratio >= 1.1 and current >= 3_000_000_000:
        return 18
    if ratio >= 0.9:
        return 15
    if ratio >= 0.7:
        return 13
    if ratio >= 0.5:
        return 5
    return 0


def v17_rsi_score(value):
    if pd.isna(value):
        return 0
    if 50 <= value <= 75:
        return 12
    if 45 <= value < 50 or 75 < value <= 80:
        return 7
    if 40 <= value < 45:
        return 4
    if value > 80:
        return 1
    return 0


def v17_candle_score(row):
    change = row["day_return_pct"]
    wick_body = row["upper_wick_body_ratio"]
    wick_range = row["upper_wick_range_ratio"]
    if (
        (pd.notna(wick_body) and wick_body >= 3)
        or (pd.notna(wick_range) and wick_range >= 0.65)
    ):
        return 0
    if pd.isna(change):
        return 0
    if change >= 18:
        return 5
    if change >= 10:
        return 7
    if change >= 3:
        return 10
    if change >= -3:
        return 13
    if change >= -10:
        return 10
    return 5


# ---------------- V20 Core Engine ----------------
def v20_hit20_score(value):
    if pd.isna(value):
        return 0
    for threshold, score in [
        (90, 35), (80, 30), (70, 25), (60, 20),
        (50, 15), (40, 10), (25, 5),
    ]:
        if value >= threshold:
            return score
    return 0


def v20_hit10_score(value):
    return 0 if pd.isna(value) else int(min(max(value, 0) * 2, 20))


def v20_hit5_score(value):
    return 0 if pd.isna(value) else int(min(max(value, 0) * 3, 15))


def v20_rise3_score(value):
    if pd.isna(value):
        return 0
    for threshold, score in [
        (20, 15), (15, 13), (10, 10), (5, 8), (2, 5), (0, 3),
    ]:
        if value >= threshold:
            return score
    return 0


def v20_avg_high_score(value):
    if pd.isna(value):
        return 0
    for threshold, score in [(8, 10), (6, 8), (5, 7), (4, 5), (3, 3)]:
        if value >= threshold:
            return score
    return 0


def v20_rank_jump_score(value):
    if pd.isna(value):
        return 0
    for threshold, score in [(100, 15), (60, 12), (30, 8), (20, 4), (10, 2)]:
        if value >= threshold:
            return score
    return 0


def v20_rsi_score(value):
    if pd.isna(value):
        return 0
    if 45 <= value <= 70:
        return 5
    if 40 <= value < 45 or 70 < value <= 75:
        return 3
    if 35 <= value < 40 or 75 < value <= 80:
        return 1
    return 0


def v20_market_score(value):
    if pd.isna(value):
        return 0
    if value >= 35:
        return 5
    if value >= 25:
        return 3
    if value >= 15:
        return 1
    return 0


def v20_grade(score):
    if score >= CONFIG["V20_A_PLUS_MIN"]:
        return "A+"
    if score >= CONFIG["V20_A_MIN"]:
        return "A"
    if score >= CONFIG["V20_A_MINUS_MIN"]:
        return "A-"
    return "관찰"


# ---------------- V21 Quality Engine ----------------
def overheat_penalty(row) -> tuple[int, str]:
    penalty = 0
    reasons = []
    rsi = row["RSI14"]
    change = row["day_return_pct"]
    ratio = row["turnover_ratio_5_20"]
    wick_body = row["upper_wick_body_ratio"]
    wick_range = row["upper_wick_range_ratio"]
    if pd.notna(rsi) and rsi >= 80:
        penalty += 2
        reasons.append("RSI과열")
    if pd.notna(change):
        if change >= 18:
            penalty += 5
            reasons.append("전일급등과다")
        elif change >= 10:
            penalty += 2
            reasons.append("전일급등")
    if pd.notna(ratio) and ratio >= 3:
        penalty += 2
        reasons.append("거래대금급증")
    if (
        (pd.notna(wick_body) and wick_body >= 5)
        or (pd.notna(wick_range) and wick_range >= 0.80)
    ):
        penalty += 7
        reasons.append("윗꼬리과다")
    elif (
        (pd.notna(wick_body) and wick_body >= 2)
        or (pd.notna(wick_range) and wick_range >= 0.55)
    ):
        penalty += 3
        reasons.append("윗꼬리주의")
    return penalty, ", ".join(dict.fromkeys(reasons))


def risk_level(row):
    if row["overheat_penalty"] >= 6:
        return "높음"
    if pd.notna(row["RSI14"]) and row["RSI14"] >= 80:
        return "높음"
    if (
        row["overheat_penalty"] >= 3
        or bool(row["overheat_reason"])
        or (pd.notna(row["turnover_ratio_5_20"]) and row["turnover_ratio_5_20"] >= 3)
        or (pd.notna(row["RSI14"]) and row["RSI14"] < 40)
    ):
        return "보통"
    return "낮음"


def entry_strategy(row):
    if row["risk_level"] == "높음":
        return "9시 시가 -2% 대기 / 추격금지"
    if row["risk_level"] == "보통":
        return "9시 시가 -1%~-2% 분할"
    return "9시 시가~-2% 분할"



# ============================================================
# 4. V22 합의 엔진 및 자동 누락방지 회귀검증
# ============================================================
def apply_all_engines(feature_df: pd.DataFrame) -> pd.DataFrame:
    frame = feature_df.copy()
    frame["volume_rank"] = frame.groupby("date")["turnover"].rank(
        method="min", ascending=False
    )
    frame = frame.sort_values(["market", "date"]).reset_index(drop=True)
    frame["prev_volume_rank"] = frame.groupby("market")["volume_rank"].shift(1)
    frame["rank_improvement"] = (
        frame["prev_volume_rank"] - frame["volume_rank"]
    )
    frame["is_v17_top30"] = frame["volume_rank"] <= CONFIG["V17_TOP_N_VOLUME"]
    frame["is_v20_top50"] = frame["volume_rank"] <= CONFIG["V20_TOP_N_VOLUME"]
    strength = (
        frame[frame["is_v20_top50"]]
        .groupby("date")["target_hit"]
        .sum()
    )
    frame["market_strength_top50"] = frame["date"].map(strength).fillna(0)

    penalties = frame.apply(overheat_penalty, axis=1, result_type="expand")
    frame["overheat_penalty"] = penalties[0].astype(int)
    frame["overheat_reason"] = penalties[1].fillna("")
    frame["risk_level"] = frame.apply(risk_level, axis=1)
    frame["entry_strategy"] = frame.apply(entry_strategy, axis=1)

    frame["v17_score_hit20"] = frame["hit20_rate"].apply(v17_hit20_score)
    frame["v17_score_hit5"] = frame["hit5_count"].apply(v17_hit5_score)
    frame["v17_score_hit3"] = frame["hit3_count"].apply(v17_hit3_score)
    frame["v17_score_avg_high"] = frame["avg_high5_pct"].apply(v17_avg_high_score)
    frame["v17_score_turnover"] = frame.apply(v17_turnover_score, axis=1)
    frame["v17_score_rsi"] = frame["RSI14"].apply(v17_rsi_score)
    frame["v17_score_candle"] = frame.apply(v17_candle_score, axis=1)
    v17_score_columns = [
        "v17_score_hit20", "v17_score_hit5", "v17_score_hit3",
        "v17_score_avg_high", "v17_score_turnover",
        "v17_score_rsi", "v17_score_candle",
    ]
    frame["v17_raw_score"] = frame[v17_score_columns].sum(axis=1).clip(0, 100)
    frame["v17_entry_score"] = (
        frame["v17_raw_score"] - frame["overheat_penalty"].clip(upper=7)
    ).clip(0, 100)
    frame["liquidity_pass"] = (
        (frame["turnover"] >= CONFIG["MIN_CURRENT_TURNOVER"])
        & (frame["turnover_5_avg"] >= CONFIG["MIN_AVG5_TURNOVER"])
    )
    frame["v17_universe"] = (
        frame["is_v17_top30"] | frame["prev_target_hit"]
    )
    frame["v17_candidate"] = (
        frame["v17_universe"]
        & frame["liquidity_pass"]
        & (frame["v17_entry_score"] >= CONFIG["V17_BUY_MIN"])
    )
    frame["v17_grade"] = np.select(
        [
            frame["v17_candidate"]
            & (frame["v17_entry_score"] >= CONFIG["V17_A_PLUS_MIN"]),
            frame["v17_candidate"],
            frame["v17_entry_score"] >= 75,
        ],
        ["A+", "A", "관찰"],
        default="제외",
    )

    frame["v20_score_hit20"] = frame["hit20_rate"].apply(v20_hit20_score)
    frame["v20_score_hit10"] = frame["hit10_count"].apply(v20_hit10_score)
    frame["v20_score_hit5"] = frame["hit5_count"].apply(v20_hit5_score)
    frame["v20_score_rise3"] = frame["rise3_pct"].apply(v20_rise3_score)
    frame["v20_score_avg_high"] = frame["avg_high5_pct"].apply(v20_avg_high_score)
    frame["v20_score_rank_jump"] = frame["rank_improvement"].apply(v20_rank_jump_score)
    frame["v20_score_rsi"] = frame["RSI14"].apply(v20_rsi_score)
    frame["v20_score_market"] = frame["market_strength_top50"].apply(v20_market_score)
    v20_score_columns = [
        "v20_score_hit20", "v20_score_hit10", "v20_score_hit5",
        "v20_score_rise3", "v20_score_avg_high",
        "v20_score_rank_jump", "v20_score_rsi", "v20_score_market",
    ]
    frame["v20_score"] = frame[v20_score_columns].sum(axis=1).clip(0, 100)
    frame["v20_grade"] = frame["v20_score"].apply(v20_grade)
    frame["v20_candidate"] = (
        frame["is_v20_top50"]
        & (frame["v20_score"] >= CONFIG["V20_A_MINUS_MIN"])
    )
    frame["v20_buy_candidate"] = (
        frame["v20_candidate"] & frame["v20_grade"].isin(["A+", "A"])
    )
    frame["v20_watch_candidate"] = (
        frame["v20_candidate"] & (frame["v20_grade"] == "A-")
    )

    frame["success_track_candidate"] = (
        frame["prev_target_hit"]
        & (frame["turnover"] >= CONFIG["MIN_CURRENT_TURNOVER"])
    )
    frame["quality_vote"] = (
        (frame["risk_level"] != "높음")
        & (
            (frame["v17_entry_score"] >= 75)
            | (frame["v20_score"] >= 75)
        )
    )
    frame["module_votes"] = (
        frame["v17_candidate"].astype(int)
        + frame["v20_buy_candidate"].astype(int)
        + frame["success_track_candidate"].astype(int)
        + frame["quality_vote"].astype(int)
    )
    frame["legacy_selected"] = (
        frame["v17_candidate"]
        | frame["v20_candidate"]
        | frame["success_track_candidate"]
    )
    consensus_bonus = (
        (frame["v17_candidate"] & frame["v20_buy_candidate"]).astype(int) * 5
        + frame["success_track_candidate"].astype(int) * 3
    )
    risk_deduction = np.select(
        [frame["risk_level"] == "높음", frame["risk_level"] == "보통"],
        [7, 2],
        default=0,
    )
    frame["v22_score"] = (
        frame["v17_entry_score"] * 0.45
        + frame["v20_score"] * 0.45
        + consensus_bonus
        - risk_deduction
    ).clip(0, 100)

    def classify_v22(row):
        v17_buy = bool(row["v17_candidate"])
        v20_buy = bool(row["v20_buy_candidate"])
        v20_watch = bool(row["v20_watch_candidate"])
        success = bool(row["success_track_candidate"])
        risk = row["risk_level"]
        votes = int(row["module_votes"])
        if v17_buy and v20_buy and risk != "높음":
            return "핵심매수"
        if votes >= 3 and (v17_buy or v20_buy) and risk != "높음":
            return "핵심매수"
        if (v17_buy or v20_buy) and risk == "높음":
            return "주의매수"
        if v17_buy and not v20_buy:
            return "전술매수" if risk != "높음" else "주의매수"
        if v20_buy and not v17_buy:
            return "일반매수" if risk != "높음" else "주의매수"
        if success and risk != "높음" and (
            row["v17_entry_score"] >= 75 or row["v20_score"] >= 72
        ):
            return "전술매수"
        if v20_watch or success or row["v17_entry_score"] >= 75:
            return "관찰"
        return "비대상"

    frame["v22_class"] = frame.apply(classify_v22, axis=1)
    frame["v22_buy_candidate"] = frame["v22_class"].isin(
        ["핵심매수", "일반매수", "전술매수", "주의매수"]
    )
    frame["v22_watch_candidate"] = frame["v22_class"] == "관찰"

    def selection_reason(row):
        reasons = []
        if row["v17_candidate"]:
            reasons.append("V17선정")
        if row["v20_buy_candidate"]:
            reasons.append(f"V20{row['v20_grade']}")
        elif row["v20_watch_candidate"]:
            reasons.append("V20A-")
        if row["success_track_candidate"]:
            reasons.append("전일성공추적")
        if row["risk_level"] == "높음":
            reasons.append("고위험진입조정")
        elif row["risk_level"] == "보통":
            reasons.append("리스크보통")
        if not reasons and row["v17_entry_score"] >= 75:
            reasons.append("V17근접")
        return " + ".join(reasons) if reasons else "선정근거없음"

    frame["selection_reason"] = frame.apply(selection_reason, axis=1)
    frame["preservation_status"] = np.where(
        frame["legacy_selected"] & (frame["v22_class"] == "비대상"),
        "누락",
        np.where(frame["legacy_selected"], "보존", "비대상"),
    )
    return frame


def build_regression_checks(frame: pd.DataFrame) -> tuple[pd.DataFrame, pd.DataFrame]:
    required_columns = []
    for module in STRATEGY_REGISTRY.values():
        required_columns.extend(module["required_columns"])
    missing_columns = sorted(set(required_columns) - set(frame.columns))
    checks = []

    def add_check(name, source_mask, target_mask, description):
        source_count = int(source_mask.sum())
        preserved_count = int((source_mask & target_mask).sum())
        checks.append({
            "검증항목": name,
            "기존선정수": source_count,
            "V22보존수": preserved_count,
            "결과": "PASS" if source_count == preserved_count else "FAIL",
            "설명": description,
        })

    included = frame["v22_class"] != "비대상"
    buy_included = frame["v22_buy_candidate"]
    add_check(
        "V17 매수후보 보존", frame["v17_candidate"], buy_included,
        "V17 후보는 V22에서 최소 주의매수 이상",
    )
    add_check(
        "V20 A/A+ 보존", frame["v20_buy_candidate"], buy_included,
        "V20 A/A+ 후보는 V22에서 최소 주의매수 이상",
    )
    add_check(
        "V20 A- 보존", frame["v20_watch_candidate"], included,
        "V20 A- 후보는 V22에서 최소 관찰",
    )
    add_check(
        "전일 성공추적 보존", frame["success_track_candidate"], included,
        "전일 성공추적은 최소 관찰",
    )
    checks.append({
        "검증항목": "필수 모듈 컬럼",
        "기존선정수": len(required_columns),
        "V22보존수": len(required_columns) - len(missing_columns),
        "결과": "PASS" if not missing_columns else "FAIL",
        "설명": (
            "모든 필수 모듈 컬럼 존재"
            if not missing_columns
            else "누락 컬럼: " + ", ".join(missing_columns)
        ),
    })
    checks_df = pd.DataFrame(checks)
    preserve_rows = frame[
        frame["v17_candidate"]
        | frame["v20_candidate"]
        | frame["success_track_candidate"]
    ][[
        "market", "korean_name", "volume_rank",
        "v17_candidate", "v17_grade", "v17_entry_score",
        "v20_candidate", "v20_grade", "v20_score",
        "success_track_candidate", "risk_level",
        "v22_class", "selection_reason", "preservation_status",
    ]].copy()
    failed = checks_df[checks_df["결과"] == "FAIL"]
    if not failed.empty:
        display(checks_df)
        raise AssertionError(
            "누락방지 회귀검증 실패: "
            + ", ".join(failed["검증항목"].tolist())
        )
    return checks_df, preserve_rows


def run_engine_self_test():
    test = pd.DataFrame([
        {
            "market": "KRW-TEST1", "korean_name": "V17전용",
            "v17_candidate": True, "v17_grade": "A+", "v17_entry_score": 88,
            "v20_candidate": False, "v20_buy_candidate": False,
            "v20_watch_candidate": False, "v20_grade": "관찰", "v20_score": 70,
            "success_track_candidate": False, "risk_level": "낮음",
            "module_votes": 2, "legacy_selected": True,
            "v22_score": 78, "v22_class": "전술매수",
            "v22_buy_candidate": True, "v22_watch_candidate": False,
            "selection_reason": "V17선정", "preservation_status": "보존",
            "volume_rank": 20, "overheat_penalty": 0, "overheat_reason": "",
            "entry_strategy": "테스트", "v17_raw_score": 88,
            "v17_universe": True, "liquidity_pass": True,
        },
        {
            "market": "KRW-TEST2", "korean_name": "V20A-",
            "v17_candidate": False, "v17_grade": "제외", "v17_entry_score": 65,
            "v20_candidate": True, "v20_buy_candidate": False,
            "v20_watch_candidate": True, "v20_grade": "A-", "v20_score": 77,
            "success_track_candidate": False, "risk_level": "보통",
            "module_votes": 1, "legacy_selected": True,
            "v22_score": 65, "v22_class": "관찰",
            "v22_buy_candidate": False, "v22_watch_candidate": True,
            "selection_reason": "V20A-", "preservation_status": "보존",
            "volume_rank": 40, "overheat_penalty": 3,
            "overheat_reason": "윗꼬리주의", "entry_strategy": "테스트",
            "v17_raw_score": 65, "v17_universe": False, "liquidity_pass": True,
        },
    ])
    for module in STRATEGY_REGISTRY.values():
        for column in module["required_columns"]:
            if column not in test.columns:
                test[column] = 0
    checks, _ = build_regression_checks(test)
    assert (checks["결과"] == "PASS").all()
    print("V22 엔진 자체 누락방지 테스트: PASS")





BASE_CONFIG = CONFIG.copy()
RUN_AT = datetime.now(KST)
SELECTION_DATE = RUN_AT.date() - timedelta(days=1)
CUTOFF_AT = datetime.combine(
    RUN_AT.date(),
    dt_time(CONFIG["SELECTION_CUTOFF_HOUR"], CONFIG["SELECTION_CUTOFF_MINUTE"]),
    tzinfo=KST,
)


def configure_runtime(overrides: dict | None = None, run_at: datetime | None = None):
    global CONFIG, RUN_AT, SELECTION_DATE, CUTOFF_AT
    CONFIG = BASE_CONFIG.copy()
    if overrides:
        CONFIG.update(overrides)
    RUN_AT = run_at or datetime.now(KST)
    SELECTION_DATE = RUN_AT.date() - timedelta(days=1)
    CUTOFF_AT = datetime.combine(
        RUN_AT.date(),
        dt_time(
            CONFIG["SELECTION_CUTOFF_HOUR"],
            CONFIG["SELECTION_CUTOFF_MINUTE"],
        ),
        tzinfo=KST,
    )
    return CONFIG.copy()


def calc_metrics(frame: pd.DataFrame) -> dict:
    evaluated = len(frame)
    succeeded = int(frame["next_success"].sum()) if evaluated else 0
    filled = int(frame["limit_filled"].sum()) if evaluated else 0
    limit_hit = int(frame["limit_target_hit"].sum()) if evaluated else 0
    return {
        "평가수": evaluated,
        "성공수": succeeded,
        "실패수": evaluated - succeeded,
        "시가매수성공률": succeeded / evaluated if evaluated else 0,
        "지정가체결수": filled,
        "지정가체결률": filled / evaluated if evaluated else 0,
        "지정가목표도달수": limit_hit,
        "체결후목표도달률": limit_hit / filled if filled else 0,
        "전체후보대비도달률": limit_hit / evaluated if evaluated else 0,
    }


def run_analysis(
    overrides: dict | None = None,
    *,
    run_at: datetime | None = None,
) -> dict:
    configure_runtime(overrides, run_at)
    run_engine_self_test()

    markets_df = get_krw_markets()
    raw_daily_df = collect_daily_data(markets_df)
    raw_daily_df, snapshot_info = apply_exact_0830_snapshot(
        raw_daily_df,
        markets_df,
        RUN_AT,
    )

    feature_frames = [
        add_common_features(group)
        for _, group in raw_daily_df.groupby("market", sort=False)
    ]
    feature_df = pd.concat(feature_frames, ignore_index=True)
    feature_df = apply_all_engines(feature_df)

    available_selection_dates = sorted(
        pd.Timestamp(value)
        for value in feature_df["date"].dropna().unique()
        if pd.Timestamp(value).date() <= SELECTION_DATE
    )
    if not available_selection_dates:
        raise RuntimeError("선정일 이전의 일봉을 찾지 못했습니다.")

    selection_ts = available_selection_dates[-1]
    actual_selection_date = selection_ts.date()

    today_all = feature_df[
        feature_df["date"] == selection_ts
    ].copy().sort_values(
        ["v22_buy_candidate", "v22_watch_candidate", "v22_score", "volume_rank"],
        ascending=[False, False, False, True],
    ).reset_index(drop=True)

    today_buy = today_all[today_all["v22_buy_candidate"]].copy()
    today_watch = today_all[
        (~today_all["v22_buy_candidate"]) & today_all["v22_watch_candidate"]
    ].copy()

    regression_checks, preservation_detail = build_regression_checks(today_all)

    feature_df = feature_df.sort_values(["market", "date"]).reset_index(drop=True)
    for column in ["date", "open", "high", "low", "close"]:
        feature_df[f"next_{column}"] = feature_df.groupby("market")[column].shift(-1)

    feature_df["next_success"] = (
        feature_df["next_high"]
        >= feature_df["next_open"] * (1 + CONFIG["TARGET_PROFIT"])
    )
    feature_df["limit_entry"] = (
        feature_df["next_open"] * (1 - CONFIG["LIMIT_BUY_DROP"])
    )
    feature_df["limit_filled"] = (
        feature_df["next_low"] <= feature_df["limit_entry"]
    )
    feature_df["limit_target"] = (
        feature_df["limit_entry"] * (1 + CONFIG["TARGET_PROFIT"])
    )
    feature_df["limit_target_hit"] = (
        feature_df["limit_filled"]
        & (feature_df["next_high"] >= feature_df["limit_target"])
    )

    backtest_date_candidates = sorted(
        pd.Timestamp(value)
        for value in feature_df.loc[
            (feature_df["date"] < selection_ts)
            & feature_df["next_open"].notna(),
            "date",
        ].dropna().unique()
    )
    backtest_dates = backtest_date_candidates[-CONFIG["BACKTEST_DAYS"]:]

    backtest_df = feature_df[
        feature_df["date"].isin(backtest_dates)
        & (
            feature_df["v17_candidate"]
            | feature_df["v20_candidate"]
            | feature_df["success_track_candidate"]
            | feature_df["v22_buy_candidate"]
        )
        & feature_df["next_open"].notna()
    ].copy()

    backtest_df["trade_result"] = np.where(
        backtest_df["next_success"], "성공", "실패"
    )
    backtest_df["backtest_timing"] = "완료 일봉 기반 08:30 프록시"

    missed_df = today_all[
        today_all["is_v20_top50"]
        & (today_all["v22_class"] == "비대상")
        & today_all["target_hit"]
    ].copy().sort_values(
        ["intraday_high_return", "volume_rank"],
        ascending=[False, True],
    )

    module_definitions = {
        "V17 Legacy": backtest_df["v17_candidate"],
        "V20 A/A+": backtest_df["v20_buy_candidate"],
        "V20 A-": backtest_df["v20_watch_candidate"],
        "전일 성공추적": backtest_df["success_track_candidate"],
        "V22 전체매수": backtest_df["v22_buy_candidate"],
        "V22 핵심매수": backtest_df["v22_class"] == "핵심매수",
        "V22 합의후보": (
            backtest_df["v17_candidate"] & backtest_df["v20_buy_candidate"]
        ),
        "V22 단독보존후보": (
            backtest_df["v22_buy_candidate"]
            & ~(
                backtest_df["v17_candidate"]
                & backtest_df["v20_buy_candidate"]
            )
        ),
    }
    module_performance = pd.DataFrame([
        {"전략/모듈": name, **calc_metrics(backtest_df[mask])}
        for name, mask in module_definitions.items()
    ])

    class_names = [
        "핵심매수", "일반매수", "전술매수",
        "주의매수", "관찰", "전체매수",
    ]
    class_rows = []
    for class_name in class_names:
        subset = (
            backtest_df[backtest_df["v22_buy_candidate"]]
            if class_name == "전체매수"
            else backtest_df[backtest_df["v22_class"] == class_name]
        )
        class_rows.append({"V22구분": class_name, **calc_metrics(subset)})
    class_performance = pd.DataFrame(class_rows)

    daily_rows = []
    for trade_date, day_df in backtest_df.groupby("next_date"):
        row = {"매매일": pd.Timestamp(trade_date)}
        for label, mask_column in [
            ("V17", "v17_candidate"),
            ("V20", "v20_buy_candidate"),
            ("V22", "v22_buy_candidate"),
        ]:
            metrics = calc_metrics(day_df[day_df[mask_column]])
            row[f"{label}평가"] = metrics["평가수"]
            row[f"{label}성공"] = metrics["성공수"]
            row[f"{label}성공률"] = metrics["시가매수성공률"]
        daily_rows.append(row)
    daily_performance = pd.DataFrame(daily_rows)
    if not daily_performance.empty:
        daily_performance = daily_performance.sort_values("매매일").reset_index(drop=True)
        daily_performance["V22_7일평균"] = (
            daily_performance["V22성공률"].rolling(7, min_periods=1).mean()
        )

    v22_metrics = calc_metrics(backtest_df[backtest_df["v22_buy_candidate"]])
    v22_core_metrics = calc_metrics(
        backtest_df[backtest_df["v22_class"] == "핵심매수"]
    )
    if backtest_df.empty:
        recent30_metrics = calc_metrics(backtest_df)
    else:
        latest_trade_date = pd.to_datetime(backtest_df["next_date"]).max()
        recent_cutoff = latest_trade_date - pd.Timedelta(days=29)
        recent30_metrics = calc_metrics(
            backtest_df[
                backtest_df["v22_buy_candidate"]
                & (pd.to_datetime(backtest_df["next_date"]) >= recent_cutoff)
            ]
        )

    return {
        "run_at": RUN_AT,
        "selection_date": actual_selection_date,
        "config": CONFIG.copy(),
        "snapshot_info": snapshot_info,
        "markets": markets_df,
        "feature_df": feature_df,
        "today_all": today_all,
        "today_buy": today_buy,
        "today_watch": today_watch,
        "regression_checks": regression_checks,
        "preservation_detail": preservation_detail,
        "backtest": backtest_df,
        "missed": missed_df,
        "module_performance": module_performance,
        "class_performance": class_performance,
        "daily_performance": daily_performance,
        "v22_metrics": v22_metrics,
        "v22_core_metrics": v22_core_metrics,
        "recent30_metrics": recent30_metrics,
    }
