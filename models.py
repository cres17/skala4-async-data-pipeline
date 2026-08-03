# -----------------------------------------------------------------------------
# models.py
#
# 파일 역할
# - 날씨, 국가, IP 위치 데이터의 Pydantic v2 스키마를 정의한다.
# - 필수 문자열, 숫자 타입, 값의 허용 범위와 좌표 조합을 검증한다.
# - 검증을 통과하지 못한 API 응답이 저장 단계로 전달되지 않게 한다.
#
# 변경 이력
# - 2026-08-03: API별 검증 모델과 필드 검증 함수 최초 작성
# - 2026-08-03: 문자열 숫자의 자동 형변환 방지와 좌표 교차 검증 추가
# - 2026-08-03: 함수·기능 설명 주석 보강
# -----------------------------------------------------------------------------

from datetime import datetime
from ipaddress import IPv4Address
from typing import Any

from pydantic import BaseModel, Field, field_validator, model_validator


# 공백만 있는 필수 문자열을 거부하고 앞뒤 공백을 제거한다.
def _required_text(value: str) -> str:
    if not isinstance(value, str) or not value.strip():
        raise ValueError("빈 문자열은 허용되지 않습니다.")
    return value.strip()


# bool·문자열을 숫자로 자동 변환하지 않아 API 타입 오류를 잡는다.
def _number(value: Any, field_name: str) -> float:
    if isinstance(value, bool) or not isinstance(value, (int, float)):
        # Pydantic가 ValidationError로 모으도록 ValueError를 사용한다.
        raise ValueError(f"{field_name}은(는) 숫자여야 합니다.")  # noqa: TRY004
    return float(value)


# Open-Meteo의 시간대별 날씨 한 건을 검증한다.
class WeatherRecord(BaseModel):
    observed_at: datetime
    temperature_c: float = Field(ge=-90, le=65)
    precipitation_probability: float = Field(ge=0, le=100)

    # 온도와 강수 확률이 실제 숫자 타입인지 Field 범위 검사 전에 확인한다.
    @field_validator("temperature_c", "precipitation_probability", mode="before")
    @classmethod
    def numeric_values_only(cls, value: Any, info) -> float:
        return _number(value, info.field_name)


# Countries.dev 응답에서 사용하는 대한민국 국가 정보다.
class CountryInfo(BaseModel):
    country_name: str
    country_code: str = Field(pattern=r"^[A-Z]{3}$")
    capital: str
    population: int = Field(gt=0)

    # 국가명과 수도에서 빈 문자열을 거부하고 앞뒤 공백을 제거한다.
    @field_validator("country_name", "capital")
    @classmethod
    def required_text(cls, value: str) -> str:
        return _required_text(value)

    # 국가 코드를 대문자 3자리 형식으로 정규화한다.
    @field_validator("country_code")
    @classmethod
    def normalized_country_code(cls, value: str) -> str:
        return _required_text(value).upper()

    # bool이나 문자열이 인구 정수로 자동 변환되지 않도록 원본 타입을 검사한다.
    @field_validator("population", mode="before")
    @classmethod
    def population_must_be_int(cls, value: Any) -> int:
        if isinstance(value, bool) or not isinstance(value, int):
            # Pydantic가 ValidationError로 모으도록 ValueError를 사용한다.
            raise ValueError("population은 정수여야 합니다.")  # noqa: TRY004
        return value


# ip-api 응답에서 사용하는 IP 기반 위치 정보다.
class IpLocation(BaseModel):
    ip: IPv4Address
    country_name: str
    city: str
    latitude: float = Field(ge=-90, le=90)
    longitude: float = Field(ge=-180, le=180)

    # 국가명과 도시명에서 빈 문자열을 거부하고 앞뒤 공백을 제거한다.
    @field_validator("country_name", "city")
    @classmethod
    def required_text(cls, value: str) -> str:
        return _required_text(value)

    # 위도와 경도가 실제 숫자 타입인지 Field 범위 검사 전에 확인한다.
    @field_validator("latitude", "longitude", mode="before")
    @classmethod
    def coordinate_must_be_numeric(cls, value: Any, info) -> float:
        return _number(value, info.field_name)

    # 0, 0은 위치를 찾지 못했을 때 흔히 쓰이는 기본값이라 거부한다.
    @model_validator(mode="after")
    def coordinates_are_not_both_zero(self) -> "IpLocation":
        if self.latitude == 0 and self.longitude == 0:
            raise ValueError("위도와 경도가 모두 0일 수 없습니다.")
        return self
