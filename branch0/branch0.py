from pathlib import Path

import pandas as pd


# branch0/data 폴더의 Excel 파일을 각각 확인합니다.
data_folder = Path(__file__).resolve().parent / "data"

# 이상치를 다시 확인할 때만 True로 바꿉니다. 값은 제거하지 않습니다.
show_outliers = False

# 모든 검사가 끝난 뒤 이상치 값을 한 번에 보여주기 위한 목록입니다.
outlier_details = []


def collect_outliers(mask, values, lower, upper, rule):
    # 현재 검사 중인 파일·시트·계절과 해당 행의 정보를 함께 기록합니다.
    for index in values.index[mask]:
        row = season_data.loc[index]
        outlier_details.append({
            "파일": file.name,
            "관측소": sheet,
            "계절": season,
            "Excel행": index + 2,  # 첫 행은 컬럼 이름이므로 2를 더합니다.
            "발표시각": row["issue_time_kst"],
            "대상시각": row["time"],
            "선행시간": row["lead_hour"],
            "변수": variable,
            "구분": label,
            "값": values.loc[index],
            "하한": lower,
            "상한": upper,
            "판정기준": rule,
        })

for file in sorted(data_folder.glob("*.xlsx")):
    # Excel이 열려 있을 때 생기는 임시 잠금파일은 건너뜁니다.
    if file.name.startswith("~$"):
        continue

    print(f"\n파일: {file.name}", flush=True)

    with pd.ExcelFile(file) as excel:
        for sheet in excel.sheet_names:
            # 설명·요약은 안내용 시트이므로 검사에서 제외합니다.
            if sheet in ["설명", "요약"]:
                continue

            df = pd.read_excel(excel, sheet_name=sheet)

            # 일사량 열은 결측 검사에서 제외합니다. Excel 원본은 그대로입니다.
            df = df.drop(columns=["actual_solar_mj_m2"], errors="ignore")

            # 빈 셀(NaN)과 공백만 들어 있는 셀을 결측으로 확인합니다.
            # 메모리 안에서만 처리하며 Excel 원본은 변경하지 않습니다.
            df = df.replace(r"^\s*$", float("nan"), regex=True)
            print(f"\n  시트: {sheet} / 데이터 {len(df):,}행")

            # 변수별로 예보·관측이 모두 있는 행만 분석에 사용합니다.
            # df에서 행을 지우지 않고, 분석용 데이터를 따로 만듭니다.
            temperature_data = df.dropna(
                subset=["air_temperature", "actual_air_temperature"]
            )
            wind_speed_data = df.dropna(
                subset=["wind_speed", "actual_wind_speed"]
            )
            wind_direction_data = df.dropna(
                subset=["wind_direction", "actual_wind_direction"]
            )

            # 현재는 결측만 제외하고, 기존 수치와 이상치 후보는 그대로 사용합니다.
            if show_outliers:
                # time(KST)의 월로 계절을 나눕니다. 겨울은 12·1·2월입니다.
                season_by_month = {
                    3: "봄", 4: "봄", 5: "봄",
                    6: "여름", 7: "여름", 8: "여름",
                    9: "가을", 10: "가을", 11: "가을",
                    12: "겨울", 1: "겨울", 2: "겨울",
                }

                # 같은 관측이 여러 예보에 대응된 경우도 각 예보 행으로 셉니다.
                # 중복 제거·이상치 제거 없이 변수별 분석용 데이터만 사용합니다.
                analysis_groups = [
                    ("기온", temperature_data, "air_temperature", "actual_air_temperature"),
                    ("풍속", wind_speed_data, "wind_speed", "actual_wind_speed"),
                    ("풍향", wind_direction_data, "wind_direction", "actual_wind_direction"),
                ]

                print("\n  계절별 이상치 개수 (삭제하지 않음)")
                print("  기온·풍속: 평균 ±5σ (표본 표준편차, ddof=1)")
                print("  음수 개수는 풍속만 별도 출력합니다.")
                print("  풍향: 0~360° 범위 밖만 집계 (0°·360° 포함 정상)")
                for variable, data, forecast_column, actual_column in analysis_groups:
                    seasons = pd.to_datetime(data["time"], errors="raise").dt.month.map(season_by_month)
                    if seasons.isna().any():
                        raise ValueError("계절을 판단할 수 없는 time 값이 있습니다.")

                    for season in ["봄", "여름", "가을", "겨울"]:
                        season_data = data.loc[seasons == season]
                        print(f"\n  {variable} / {season} / {len(season_data):,}행")
                        outside_by_column = []
                        for label, column in [("예보", forecast_column), ("관측", actual_column)]:
                            values = pd.to_numeric(season_data[column], errors="raise")
                            if variable == "풍향":
                                outside = ~values.between(0, 360, inclusive="both")
                                outside_by_column.append(outside)
                                print(f"    {label}: 0~360° 범위 밖 {outside.sum():,}개")
                                collect_outliers(outside, values, 0, 360, "풍향 0~360° 범위 밖")
                                continue

                            if variable == "풍속":
                                print(f"    {label} 음수 풍속: {(values < 0).sum():,}개")

                            mean = values.mean()
                            std = values.std(ddof=1)
                            if len(values) < 2:
                                print(f"    {label}: 표본 2개 미만이므로 5σ 판정 불가")
                                if variable == "풍속":
                                    collect_outliers(values < 0, values, None, None, "음수 풍속")
                                continue

                            lower = mean - 5 * std
                            upper = mean + 5 * std
                            below = values < lower
                            above = values > upper
                            outside_by_column.append(below | above)
                            # 음수이면서 5σ 밖인 풍속도 같은 값은 한 번만 기록합니다.
                            flagged = below | above
                            if variable == "풍속":
                                flagged = flagged | (values < 0)
                            collect_outliers(
                                flagged, values, lower, upper,
                                "평균 ±5σ 밖 또는 음수 풍속" if variable == "풍속" else "평균 ±5σ 밖"
                            )
                            print(
                                f"    {label}: 평균 {mean:.3f}, σ {std:.3f}, "
                                f"범위 [{lower:.3f}, {upper:.3f}] / "
                                f"하한 미만 {below.sum():,}개, 상한 초과 {above.sum():,}개, "
                                f"합계 {(below | above).sum():,}개"
                            )

                        if len(outside_by_column) == 2:
                            either_outside = outside_by_column[0] | outside_by_column[1]
                            print(f"    예보 또는 관측이 범위 밖인 행: {either_outside.sum():,}행")

            # 이후 해당 파일·시트의 분석/plot 코드는 이 위치에 추가합니다.
            # 시간·발표시각·선행시간과 기존 행 인덱스는 그대로 유지됩니다.
            # 시계열 분석 시 제외된 시간을 연속된 시간으로 취급하면 안 됩니다.

# 주의: -999 같은 숫자형 결측 코드는 별도 정의를 확인해야 합니다.

if show_outliers:
    print("\n===== 이상치 값 전체 목록 (삭제하지 않음) =====")
    if outlier_details:
        details = pd.DataFrame(outlier_details)
        print(f"총 {len(details):,}건 (예보·관측의 개별 값 기준)")
        print(details.to_string(index=False, max_rows=None, max_cols=None, max_colwidth=None))
    else:
        print("현재 기준으로 잡힌 이상치가 없습니다.")
