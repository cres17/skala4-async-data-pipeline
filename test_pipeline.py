# -----------------------------------------------------------------------------
# test_pipeline.py
#
# 파일 역할
# - 정상 날씨 데이터가 Pydantic 검증을 통과하는지 확인한다.
# - 강수 확률 범위 초과와 문자열 온도 입력이 거부되는지 확인한다.
#
# 변경 이력
# - 2026-08-03: 정상·범위 오류·타입 오류 테스트 3건 최초 작성
# - 2026-08-03: 테스트별 기능 설명 주석 보강
# -----------------------------------------------------------------------------

from datetime import UTC, datetime

import pytest
from pydantic import ValidationError

from models import WeatherRecord


# 정상 날씨 데이터는 Pydantic 검증을 통과해야 한다.
def test_weather_record_accepts_valid_values() -> None:
    record = WeatherRecord(
        observed_at=datetime(2026, 8, 3, 9, 0, tzinfo=UTC),
        temperature_c=27.5,
        precipitation_probability=40,
    )

    assert record.temperature_c == 27.5
    assert record.precipitation_probability == 40.0


# 강수 확률은 0~100 범위를 벗어나면 실패해야 한다.
def test_weather_record_rejects_out_of_range_probability() -> None:
    with pytest.raises(ValidationError):
        WeatherRecord(
            observed_at="2026-08-03T09:00:00",
            temperature_c=27.5,
            precipitation_probability=101,
        )


# 자동 형변환 없이 문자열 온도를 잘못된 타입으로 처리해야 한다.
def test_weather_record_rejects_string_temperature() -> None:
    with pytest.raises(ValidationError):
        WeatherRecord(
            observed_at="2026-08-03T09:00:00",
            temperature_c="27.5",
            precipitation_probability=40,
        )


# 시간대별 배열이 비었거나 길이가 다르면 변환 단계에서 거부해야 한다.
def test_weather_rows_rejects_empty_or_mismatched_arrays() -> None:
    from collectors import weather_rows

    with pytest.raises(ValueError, match="비어"):
        weather_rows({"hourly": {"time": [], "temperature_2m": [], "precipitation_probability": []}})
    with pytest.raises(ValueError, match="길이"):
        weather_rows(
            {"hourly": {"time": ["t1", "t2"], "temperature_2m": [1.0], "precipitation_probability": [0, 0]}}
        )


# ip-api가 본문에서 실패를 알리면 저장하지 않아야 한다.
def test_ip_location_row_rejects_fail_status() -> None:
    from collectors import ip_location_row

    with pytest.raises(ValueError, match="ip-api"):
        ip_location_row({"status": "fail", "message": "reserved range"})
