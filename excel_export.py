
from __future__ import annotations

from io import BytesIO
import pandas as pd


def _width(series: pd.Series, header: str, minimum=9, maximum=38) -> int:
    values = series.astype(str).replace("nan", "")
    maximum_length = max(
        [len(str(header))] + [len(value) for value in values.head(300)]
    )
    return max(minimum, min(maximum, maximum_length + 2))


def build_excel_bytes(result: dict) -> bytes:
    buffer = BytesIO()

    with pd.ExcelWriter(
        buffer,
        engine="xlsxwriter",
        datetime_format="yyyy-mm-dd",
        date_format="yyyy-mm-dd",
        engine_kwargs={
            "options": {
                "nan_inf_to_errors": True,
                "strings_to_urls": False,
            }
        },
    ) as writer:
        workbook = writer.book

        NAVY = "#17365D"
        BLUE = "#2F75B5"
        LIGHT_BLUE = "#D9EAF7"
        PALE_BLUE = "#EDF4FA"
        GREEN = "#70AD47"
        LIGHT_GREEN = "#E2F0D9"
        ORANGE = "#ED7D31"
        RED = "#C00000"
        LIGHT_RED = "#F4CCCC"
        DARK_GRAY = "#595959"
        WHITE = "#FFFFFF"
        YELLOW = "#FFF2CC"
        FONT = "맑은 고딕"

        title_fmt = workbook.add_format({
            "font_name": FONT, "font_size": 20, "bold": True,
            "font_color": WHITE, "bg_color": NAVY,
            "align": "left", "valign": "vcenter",
        })
        subtitle_fmt = workbook.add_format({
            "font_name": FONT, "font_size": 10, "italic": True,
            "font_color": DARK_GRAY, "bg_color": PALE_BLUE,
            "align": "left", "valign": "vcenter",
        })
        section_fmt = workbook.add_format({
            "font_name": FONT, "font_size": 12, "bold": True,
            "font_color": NAVY, "bg_color": LIGHT_BLUE,
        })
        header_fmt = workbook.add_format({
            "font_name": FONT, "font_size": 10, "bold": True,
            "font_color": WHITE, "bg_color": BLUE,
            "border": 1, "align": "center", "valign": "vcenter",
            "text_wrap": True,
        })
        dark_header_fmt = workbook.add_format({
            "font_name": FONT, "font_size": 10, "bold": True,
            "font_color": WHITE, "bg_color": DARK_GRAY,
            "border": 1, "align": "center", "valign": "vcenter",
            "text_wrap": True,
        })
        body_fmt = workbook.add_format({
            "font_name": FONT, "font_size": 10,
            "border": 1, "border_color": "#D9E2F3",
            "valign": "vcenter",
        })
        center_fmt = workbook.add_format({
            "font_name": FONT, "font_size": 10,
            "border": 1, "border_color": "#D9E2F3",
            "align": "center", "valign": "vcenter",
        })
        pct_fmt = workbook.add_format({
            "font_name": FONT, "font_size": 10,
            "num_format": "0.0%", "border": 1,
            "border_color": "#D9E2F3", "align": "center",
        })
        num_fmt = workbook.add_format({
            "font_name": FONT, "font_size": 10,
            "num_format": "#,##0.00", "border": 1,
            "border_color": "#D9E2F3",
        })
        int_fmt = workbook.add_format({
            "font_name": FONT, "font_size": 10,
            "num_format": "#,##0", "border": 1,
            "border_color": "#D9E2F3", "align": "center",
        })
        wrap_fmt = workbook.add_format({
            "font_name": FONT, "font_size": 10,
            "border": 1, "border_color": "#D9E2F3",
            "valign": "vcenter", "text_wrap": True,
        })
        note_fmt = workbook.add_format({
            "font_name": FONT, "font_size": 10, "bold": True,
            "font_color": DARK_GRAY, "bg_color": YELLOW,
            "border": 1, "text_wrap": True, "valign": "vcenter",
        })

        def write_table(
            name: str,
            frame: pd.DataFrame,
            title: str,
            subtitle: str,
            *,
            header_row: int = 4,
            freeze_cols: int = 0,
            dark_header: bool = False,
            percent_columns: list[str] | None = None,
            numeric_columns: list[str] | None = None,
            integer_columns: list[str] | None = None,
            wrap_columns: list[str] | None = None,
            custom_widths: dict[str, int] | None = None,
        ):
            frame.to_excel(writer, sheet_name=name, startrow=header_row, index=False)
            sheet = writer.sheets[name]
            sheet.hide_gridlines(2)
            sheet.set_zoom(90)
            last_column = max(len(frame.columns) - 1, 3)
            sheet.merge_range(0, 0, 1, last_column, title, title_fmt)
            sheet.merge_range(2, 0, 2, last_column, subtitle, subtitle_fmt)
            sheet.set_row(header_row, 31)

            header_format = dark_header_fmt if dark_header else header_fmt
            for column_index, column in enumerate(frame.columns):
                sheet.write(header_row, column_index, column, header_format)

            if len(frame):
                sheet.autofilter(
                    header_row, 0,
                    header_row + len(frame),
                    len(frame.columns) - 1,
                )
            sheet.freeze_panes(header_row + 1, freeze_cols)

            percent_columns = set(percent_columns or [])
            numeric_columns = set(numeric_columns or [])
            integer_columns = set(integer_columns or [])
            wrap_columns = set(wrap_columns or [])
            custom_widths = custom_widths or {}

            for column_index, column in enumerate(frame.columns):
                width = custom_widths.get(column, _width(frame[column], column))
                fmt = body_fmt
                if column in percent_columns:
                    fmt = pct_fmt
                elif column in numeric_columns:
                    fmt = num_fmt
                elif column in integer_columns:
                    fmt = int_fmt
                elif column in wrap_columns:
                    fmt = wrap_fmt
                sheet.set_column(column_index, column_index, width, fmt)

            return sheet

        today_buy = result["today_buy"].copy()
        today_watch = result["today_watch"].copy()
        today_all = result["today_all"].copy()
        config = result["config"]
        snapshot = result["snapshot_info"]

        # Dashboard
        dashboard = workbook.add_worksheet("Dashboard")
        writer.sheets["Dashboard"] = dashboard
        dashboard.hide_gridlines(2)
        dashboard.set_zoom(90)
        dashboard.set_column("A:P", 11)
        dashboard.merge_range(
            "A1:P2",
            "UPBIT 단기 진입전략 V22 Mobile | Legacy Preservation",
            title_fmt,
        )
        dashboard.merge_range(
            "A3:P3",
            (
                f"선정일 {result['selection_date']} · {snapshot['mode']} · "
                "V17/V20/V21 보존 · 누락방지 검증"
            ),
            subtitle_fmt,
        )

        def card(row, first_col, last_col, label, value, subtext, color, percent=False):
            label_format = workbook.add_format({
                "font_name": FONT, "bold": True, "font_color": WHITE,
                "bg_color": color, "align": "center", "border": 1,
            })
            value_format = workbook.add_format({
                "font_name": FONT, "font_size": 20, "bold": True,
                "font_color": color, "align": "center", "valign": "vcenter",
                "num_format": "0.0%" if percent else "#,##0",
                "border": 1, "border_color": "#D9E2F3",
            })
            sub_format = workbook.add_format({
                "font_name": FONT, "font_size": 9,
                "font_color": DARK_GRAY, "bg_color": PALE_BLUE,
                "align": "center", "text_wrap": True, "border": 1,
            })
            dashboard.merge_range(row, first_col, row, last_col, label, label_format)
            dashboard.merge_range(row + 1, first_col, row + 2, last_col, value, value_format)
            dashboard.merge_range(row + 3, first_col, row + 4, last_col, subtext, sub_format)

        checks = result["regression_checks"]
        card(4, 0, 3, "V22 매수후보", len(today_buy), "기존 전략 누락 없이 통합", GREEN)
        card(
            4, 4, 7, "핵심매수",
            int((today_buy["v22_class"] == "핵심매수").sum()),
            "V17·V20 합의 우선", BLUE,
        )
        card(
            4, 8, 11, "V22 90일 성공률",
            result["v22_metrics"]["시가매수성공률"],
            f"{result['v22_metrics']['성공수']} / {result['v22_metrics']['평가수']}건",
            NAVY, True,
        )
        card(
            4, 12, 15, "최근 30일",
            result["recent30_metrics"]["시가매수성공률"],
            f"{result['recent30_metrics']['성공수']} / {result['recent30_metrics']['평가수']}건",
            ORANGE, True,
        )
        card(
            10, 0, 3, "V17 보존",
            int(today_all["v17_candidate"].sum()),
            "상위30 + 성공추적", DARK_GRAY,
        )
        card(
            10, 4, 7, "V20 A/A+ 보존",
            int(today_all["v20_buy_candidate"].sum()),
            "상위50 Core", BLUE,
        )
        card(
            10, 8, 11, "성공추적",
            int(today_all["success_track_candidate"].sum()),
            "상위50 밖도 유지", GREEN,
        )
        card(
            10, 12, 15, "검증 PASS",
            int((checks["결과"] == "PASS").sum()),
            f"총 {len(checks)}개 검사", RED,
        )

        dashboard.merge_range("A17:J17", "오늘 최종 매수후보", section_fmt)
        headers = [
            "구분", "종목", "한글명", "V22점수", "V17", "V20",
            "성공추적", "리스크", "추천진입", "선정근거",
        ]
        for column, header in enumerate(headers):
            dashboard.write(17, column, header, header_fmt)

        for row_index, (_, row) in enumerate(today_buy.iterrows(), start=18):
            values = [
                row["v22_class"],
                row["market"].replace("KRW-", ""),
                row["korean_name"],
                row["v22_score"],
                row["v17_grade"] if row["v17_candidate"] else "-",
                row["v20_grade"] if row["v20_candidate"] else "-",
                "Y" if row["success_track_candidate"] else "N",
                row["risk_level"],
                row["entry_strategy"],
                row["selection_reason"],
            ]
            for column, value in enumerate(values):
                dashboard.write(
                    row_index, column, value,
                    wrap_fmt if column in [8, 9] else center_fmt,
                )

        dashboard.set_column("A:A", 12)
        dashboard.set_column("B:B", 10)
        dashboard.set_column("C:C", 15)
        dashboard.set_column("D:H", 10)
        dashboard.set_column("I:I", 26)
        dashboard.set_column("J:J", 34)

        note_row = 20 + max(len(today_buy), 5)
        dashboard.merge_range(
            note_row, 0, note_row + 2, 15,
            (
                "V22는 V17·V20 후보를 삭제하지 않습니다. 한쪽 엔진에서만 선정된 종목도 "
                "일반/전술/주의매수로 보존하고, V20 A-와 성공추적은 최소 관찰로 남깁니다. "
                "현재 후보는 08:30 재구성, 과거 백테스트는 완료 일봉 프록시입니다."
            ),
            note_fmt,
        )

        # Candidate output
        candidate_columns = [
            "market", "korean_name", "v22_class", "v22_score",
            "volume_rank", "prev_volume_rank", "rank_improvement",
            "v17_grade", "v17_raw_score", "v17_entry_score", "v17_candidate",
            "v20_grade", "v20_score", "v20_buy_candidate", "v20_watch_candidate",
            "success_track_candidate", "module_votes", "risk_level",
            "overheat_penalty", "overheat_reason", "RSI14", "hit20_rate",
            "hit10_count", "hit5_count", "hit3_count", "rise3_pct",
            "avg_high5_pct", "turnover", "turnover_5_avg",
            "turnover_ratio_5_20", "entry_strategy", "selection_reason",
            "preservation_status", "snapshot_source",
        ]
        rename = {
            "korean_name": "한글명", "v22_class": "V22최종구분",
            "v22_score": "V22점수", "volume_rank": "거래대금순위",
            "prev_volume_rank": "전일순위", "rank_improvement": "순위개선",
            "v17_grade": "V17판정", "v17_raw_score": "V17원점수",
            "v17_entry_score": "V17진입점수", "v17_candidate": "V17선정",
            "v20_grade": "V20판정", "v20_score": "V20점수",
            "v20_buy_candidate": "V20매수선정",
            "v20_watch_candidate": "V20관찰선정",
            "success_track_candidate": "전일성공추적",
            "module_votes": "모듈투표", "risk_level": "리스크",
            "overheat_penalty": "과열감점", "overheat_reason": "과열사유",
            "hit20_rate": "20일도달률%", "hit10_count": "최근10일",
            "hit5_count": "최근5일", "hit3_count": "최근3일",
            "rise3_pct": "최근3일상승률%",
            "avg_high5_pct": "평균고가상승률5일%",
            "turnover": "거래대금(억)", "turnover_5_avg": "5일평균(억)",
            "turnover_ratio_5_20": "거래대금비율",
            "entry_strategy": "추천진입", "selection_reason": "선정근거",
            "preservation_status": "보존상태",
            "snapshot_source": "데이터시점",
        }

        def candidate_frame(frame: pd.DataFrame) -> pd.DataFrame:
            output = frame[candidate_columns].copy()
            output["turnover"] /= 1e8
            output["turnover_5_avg"] /= 1e8
            return output.rename(columns=rename)

        buy_out = candidate_frame(today_buy)
        watch_out = candidate_frame(today_watch)

        buy_sheet = write_table(
            "최종매수후보", buy_out,
            "V22 최종 매수후보",
            "V17·V20·성공추적을 보존하고 V21 리스크로 진입가격 조정",
            freeze_cols=3,
            numeric_columns=[
                "V22점수", "V17원점수", "V17진입점수", "V20점수",
                "RSI14", "거래대금(억)", "5일평균(억)", "거래대금비율",
            ],
            integer_columns=[
                "거래대금순위", "전일순위", "순위개선",
                "모듈투표", "과열감점", "최근10일", "최근5일", "최근3일",
            ],
            wrap_columns=["과열사유", "추천진입", "선정근거"],
            custom_widths={
                "한글명": 15, "market": 15, "추천진입": 27,
                "선정근거": 35, "과열사유": 28,
            },
        )
        if len(buy_out):
            score_column = buy_out.columns.get_loc("V22점수")
            buy_sheet.conditional_format(
                5, score_column, 4 + len(buy_out), score_column,
                {"type": "data_bar", "bar_color": BLUE},
            )

        write_table(
            "오늘관찰후보", watch_out,
            "V22 오늘 관찰후보",
            "V20 A-·성공추적·V17 근접후보를 최소 관찰로 보존",
            freeze_cols=3, dark_header=True,
            numeric_columns=[
                "V22점수", "V17원점수", "V17진입점수", "V20점수",
                "RSI14", "거래대금(억)", "5일평균(억)", "거래대금비율",
            ],
            wrap_columns=["과열사유", "추천진입", "선정근거"],
            custom_widths={
                "한글명": 15, "market": 15, "추천진입": 27,
                "선정근거": 35, "과열사유": 28,
            },
        )

        module_compare = today_all[
            [
                "market", "korean_name", "volume_rank",
                "v17_grade", "v17_entry_score", "v17_candidate",
                "v20_grade", "v20_score", "v20_buy_candidate",
                "v20_watch_candidate", "success_track_candidate",
                "module_votes", "risk_level", "v22_score",
                "v22_class", "selection_reason", "preservation_status",
            ]
        ].copy()
        module_compare = module_compare[
            (module_compare["v22_class"] != "비대상")
            | module_compare["v17_candidate"]
            | module_compare["v20_buy_candidate"]
            | module_compare["v20_watch_candidate"]
            | module_compare["success_track_candidate"]
        ]
        write_table(
            "모듈별후보", module_compare,
            "V17·V20·V21·V22 모듈별 후보 비교",
            "최종 결과뿐 아니라 각 기존 엔진의 독립 판단을 보존",
            freeze_cols=3,
            numeric_columns=["v17_entry_score", "v20_score", "v22_score"],
            integer_columns=["volume_rank", "module_votes"],
            wrap_columns=["selection_reason"],
            custom_widths={"korean_name": 15, "market": 15, "selection_reason": 35},
        )

        checks_sheet = write_table(
            "누락방지검증", result["regression_checks"],
            "기존 전략 누락방지 회귀검증",
            "하나라도 FAIL이면 분석 단계에서 자동 중단",
            dark_header=True,
            integer_columns=["기존선정수", "V22보존수"],
            wrap_columns=["검증항목", "설명"],
            custom_widths={"검증항목": 26, "설명": 48},
        )
        if len(checks):
            result_column = checks.columns.get_loc("결과")
            checks_sheet.conditional_format(
                5, result_column, 4 + len(checks), result_column,
                {
                    "type": "text", "criteria": "containing", "value": "PASS",
                    "format": workbook.add_format({
                        "bg_color": LIGHT_GREEN,
                        "font_color": GREEN,
                        "bold": True,
                    }),
                },
            )

        write_table(
            "보존후보상세", result["preservation_detail"],
            "기존 전략 보존후보 상세",
            "V17·V20·성공추적 후보의 V22 유지 상태",
            freeze_cols=3,
            numeric_columns=["v17_entry_score", "v20_score"],
            integer_columns=["volume_rank"],
            wrap_columns=["selection_reason"],
            custom_widths={"korean_name": 15, "market": 15, "selection_reason": 35},
        )

        backtest = result["backtest"].copy()
        backtest["시가대비고가상승률%"] = (
            backtest["next_high"] / backtest["next_open"] - 1
        ) * 100
        write_table(
            "백테스트상세", backtest,
            "V22 백테스트 상세",
            "전날 선정 → 다음날 시가 대비 +2.5% · 과거 일봉은 08:30 프록시",
            freeze_cols=4,
            wrap_columns=["selection_reason", "backtest_timing"],
            custom_widths={
                "korean_name": 15, "market": 15,
                "selection_reason": 35, "backtest_timing": 28,
            },
        )

        percent_columns = [
            "시가매수성공률", "지정가체결률",
            "체결후목표도달률", "전체후보대비도달률",
        ]
        write_table(
            "모듈별성과", result["module_performance"],
            "V17·V20·V22 모듈별 성과",
            "동일한 다음날 시가매수 +2.5% 기준 비교",
            percent_columns=percent_columns,
            integer_columns=[
                "평가수", "성공수", "실패수",
                "지정가체결수", "지정가목표도달수",
            ],
        )
        write_table(
            "V22구분별성과", result["class_performance"],
            "V22 최종구분별 성과",
            "핵심·일반·전술·주의매수 성과 분리",
            percent_columns=percent_columns,
            integer_columns=[
                "평가수", "성공수", "실패수",
                "지정가체결수", "지정가목표도달수",
            ],
        )
        write_table(
            "일별성과", result["daily_performance"],
            "V17·V20·V22 일별 성과",
            "같은 날짜에서 각 전략의 성공률 변화 비교",
            percent_columns=[
                "V17성공률", "V20성공률", "V22성공률", "V22_7일평균",
            ],
            integer_columns=[
                "V17평가", "V17성공", "V20평가",
                "V20성공", "V22평가", "V22성공",
            ],
        )

        settings = pd.DataFrame([
            ["기준", "전략버전", "V22_MOBILE_PRESERVATION", "기존 엔진 독립 보존"],
            ["기준", "선정일", str(result["selection_date"]), "08:30 기준"],
            ["기준", "데이터모드", snapshot["mode"], "30분 캔들 재구성"],
            ["기준", "스냅샷 성공률", snapshot["success_rate"], "재구성 비율"],
            ["V17", "후보군", "상위30 + 전일 성공추적", "잠금"],
            ["V20", "후보군", "상위50 + 75점 이상", "잠금"],
            ["V22", "매수후보", len(today_buy), "핵심/일반/전술/주의"],
            ["V22", "관찰후보", len(today_watch), "A-와 성공추적"],
            ["성과", "90일 성공률", result["v22_metrics"]["시가매수성공률"], "전체매수"],
            ["성과", "최근30일", result["recent30_metrics"]["시가매수성공률"], "최근 흐름"],
            ["제외", "마켓", ", ".join(config["EXCLUDE_MARKETS"]), "설정값"],
        ], columns=["구분", "항목", "값", "설명"])
        write_table(
            "설정및요약", settings,
            "V22 설정 및 요약",
            "모바일 앱 실행 결과",
            wrap_columns=["설명"],
            custom_widths={"항목": 25, "값": 32, "설명": 48},
        )

        guide = pd.DataFrame([
            ["V17 보존", "상위30+성공추적+80점+유동성", "최소 주의매수"],
            ["V20 보존", "상위50+75점", "A/A+ 매수, A- 관찰"],
            ["성공추적", "직전 일봉 +2.5% 도달", "상위50 밖도 최소 관찰"],
            ["합의후보", "V17·V20 동시선정", "핵심매수"],
            ["단독후보", "한쪽 엔진만 선정", "일반/전술매수"],
            ["고위험", "과열·윗꼬리·RSI", "삭제 대신 주의매수"],
            ["08:30", "30분 캔들 재구성", "확정종가 혼입 방지"],
            ["백테스트", "완료 일봉 프록시", "현재 스냅샷과 구분"],
        ], columns=["구분", "기준", "V22 처리"])
        write_table(
            "전략가이드", guide,
            "V22 전략 가이드",
            "기존 모듈 보존과 08:30 기준",
            wrap_columns=["기준", "V22 처리"],
            custom_widths={"구분": 18, "기준": 42, "V22 처리": 55},
        )

        # Charts
        module_perf = result["module_performance"]
        if len(module_perf):
            chart = workbook.add_chart({"type": "column"})
            rate_column = module_perf.columns.get_loc("시가매수성공률")
            chart.add_series({
                "name": "성공률",
                "categories": [
                    "모듈별성과", 5, 0,
                    4 + len(module_perf), 0,
                ],
                "values": [
                    "모듈별성과", 5, rate_column,
                    4 + len(module_perf), rate_column,
                ],
                "fill": {"color": BLUE},
                "data_labels": {"value": True, "num_format": "0.0%"},
            })
            chart.set_title({"name": "모듈별 시가매수 성공률"})
            chart.set_legend({"none": True})
            chart.set_y_axis({"num_format": "0%", "min": 0, "max": 1})
            chart.set_size({"width": 590, "height": 280})
            dashboard.insert_chart("K17", chart)

        daily = result["daily_performance"]
        if not daily.empty:
            line = workbook.add_chart({"type": "line"})
            rate_column = daily.columns.get_loc("V22성공률")
            avg_column = daily.columns.get_loc("V22_7일평균")
            line.add_series({
                "name": "V22 일별",
                "categories": ["일별성과", 5, 0, 4 + len(daily), 0],
                "values": ["일별성과", 5, rate_column, 4 + len(daily), rate_column],
                "line": {"color": BLUE, "width": 2},
            })
            line.add_series({
                "name": "7일 평균",
                "categories": ["일별성과", 5, 0, 4 + len(daily), 0],
                "values": ["일별성과", 5, avg_column, 4 + len(daily), avg_column],
                "line": {"color": ORANGE, "width": 2},
            })
            line.set_title({"name": "V22 성공률 추이"})
            line.set_legend({"position": "bottom"})
            line.set_y_axis({"num_format": "0%", "min": 0, "max": 1})
            line.set_x_axis({"date_axis": True, "num_format": "mm-dd"})
            line.set_size({"width": 590, "height": 270})
            dashboard.insert_chart("K33", line)

        dashboard.freeze_panes(3, 0)

    return buffer.getvalue()
