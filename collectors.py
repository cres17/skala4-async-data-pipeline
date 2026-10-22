# -----------------------------------------------------------------------------
# collectors.py
#
# 파일 역할
# - Open-Meteo, Countries.dev, ip-api 요청을 동시에 실행한다.
# - HTTP 상태 코드, 타임아웃, JSON 형식과 API 자체 실패 응답을 확인한다.
# - 서로 다른 API 응답을 Pydantic 검증에 필요한 공통 딕셔너리로 변환한다.
#
# 변경 이력
# - 2026-08-03: 비동기 API 수집 및 응답 변환 함수 최초 작성
# - 2026-08-03: DNS 지연 대응용 요청 제한과 지연 import 추가
# - 2026-08-03: 함수·기능 설명 주석 보강
# -----------------------------------------------------------------------------

import asyncio
import logging
from typing import Any

LOGGER = logging.getLogger(__name__)

WEATHER_URL = (
    "https://api.open-meteo.com/v1/forecast?latitude=37.5665&longitude=126.9780&"
    "hourly=temperature_2m,precipitation_probability&forecast_days=3&timezone=Asia/Seoul"
)
COUNTRY_URL = "https://countries.dev/alpha/KOR"
IP_LOCATION_URL = "http://ip-api.com/json/8.8.8.8"
# DNS 조회처럼 HTTP 클라이언트의 기본 타임아웃만으로 제어하기 어려운 상황까지 막는다.
REQUEST_DEADLINE_SECONDS = 8.0


# 하나 이상의 API를 수집하지 못했을 때 발생하는 예외
class CollectionError(RuntimeError):
    pass

# HTTP 오류와 JSON 형식 오류를 확인한 뒤 API 응답을 반환한다.
async def fetch_json(client: Any, name: str, url: str) -> dict[str, Any]:
    # httpx의 SSL 초기화는 수집 작업 프로세스에서만 수행한다.
    import httpx

    # 요청, HTTP 상태 코드 확인, JSON 변환을 하나의 예외 처리 범위로 묶는다.
    try:
        # ★ API 한 곳이 DNS/연결 단계에서 멈춰도 8초 안에 전체 요청을 종료한다.
        response = await asyncio.wait_for(
            client.get(url),
            timeout=REQUEST_DEADLINE_SECONDS,
        )
        response.raise_for_status()  # ★ HTTP 4xx/5xx를 성공으로 처리하지 않는다.
        payload = response.json()
    except (asyncio.TimeoutError, httpx.HTTPError, ValueError) as error:
        raise CollectionError(f"{name} 수집 실패: {error}") from error

    if not isinstance(payload, dict):
        raise CollectionError(f"{name} 수집 실패: JSON 객체가 아닙니다.")

    LOGGER.info("[수집 성공] %s", name)
    return payload


# ★ asyncio.gather()로 세 API 요청을 같은 시점에 시작한다.
async def collect_all() -> dict[str, dict[str, Any]]:
    import httpx

    LOGGER.info("[수집 시작] 세 API를 동시에 요청합니다. 최대 대기 시간: %.0f초", REQUEST_DEADLINE_SECONDS)
    timeout = httpx.Timeout(REQUEST_DEADLINE_SECONDS, connect=3.0)

    # 1) 하나의 AsyncClient에서 세 요청을 만들고 gather()로 동시에 실행한다.
    async with httpx.AsyncClient(timeout=timeout, follow_redirects=True) as client:
        results = await asyncio.gather(
            fetch_json(client, "Open-Meteo", WEATHER_URL),
            fetch_json(client, "Countries.dev", COUNTRY_URL),
            fetch_json(client, "ip-api", IP_LOCATION_URL),
            return_exceptions=True,
        )

    # 2) 개별 요청의 예외를 API 이름과 연결해 한 번에 확인할 수 있게 한다.
    names = ("Open-Meteo", "Countries.dev", "ip-api")
    failures = [
        f"{name}: {result}"
        for name, result in zip(names, results, strict=True)
        if isinstance(result, Exception)
    ]
    if failures:
        raise CollectionError("세 API 수집을 완료하지 못했습니다. " + " | ".join(failures))

    # 3) 세 정상 응답을 용도별 키로 묶고 누락 여부를 마지막으로 확인한다.
    payloads = dict(zip(("weather", "country", "ip_location"), results, strict=True))
    if len(payloads) != 3 or not all(isinstance(item, dict) for item in payloads.values()):
        raise CollectionError("세 API의 정상 응답을 확인하지 못했습니다.")

    LOGGER.info("[핵심 확인] 세 API 응답 3건을 모두 정상 수집했습니다.")
    return payloads


# Open-Meteo 배열을 시간대별 검증 레코드로 펼친다.
def weather_rows(payload: dict[str, Any]) -> list[dict[str, Any]]:
    # 시간, 기온, 강수 확률 배열이 모두 존재하고 길이가 같은지 확인한다.
    hourly = payload.get("hourly")
    if not isinstance(hourly, dict):
        raise TypeError("Open-Meteo hourly 객체가 없습니다.")

    times = hourly.get("time")
    temperatures = hourly.get("temperature_2m")
    probabilities = hourly.get("precipitation_probability")
    if not all(isinstance(values, list) for values in (times, temperatures, probabilities)):
        raise ValueError("Open-Meteo 시간대별 배열 형식이 올바르지 않습니다.")
    if not times:
        raise ValueError("Open-Meteo 시간대별 배열이 비어 있습니다.")
    if len({len(times), len(temperatures), len(probabilities)}) != 1:
        raise ValueError("Open-Meteo 시간대별 배열 길이가 일치하지 않습니다.")

    return [
        {
            "observed_at": observed_at,
            "temperature_c": temperature,
            "precipitation_probability": probability,
        }
        for observed_at, temperature, probability in zip(times, temperatures, probabilities, strict=True)
    ]


# Countries.dev의 필드명 차이를 흡수해 필요한 국가 정보만 반환한다.
def country_row(payload: dict[str, Any]) -> dict[str, Any]:
    name = payload.get("name")
    if isinstance(name, dict):
        name = name.get("common")
    capital = payload.get("capital")
    if isinstance(capital, list):
        capital = capital[0] if capital else ""

    return {
        "country_name": name,
        "country_code": payload.get("cca3") or payload.get("alpha3Code") or "KOR",
        "capital": capital,
        "population": payload.get("population"),
    }


# ip-api가 응답 본문에서 실패를 알린 경우도 명확히 실패 처리한다.
def ip_location_row(payload: dict[str, Any]) -> dict[str, Any]:
    if payload.get("status") == "fail":
        raise ValueError(f"ip-api 응답 실패: {payload.get('message', '알 수 없는 오류')}")

    return {
        "ip": payload.get("query"),
        "country_name": payload.get("country"),
        "city": payload.get("city"),
        "latitude": payload.get("lat"),
        "longitude": payload.get("lon"),
    }
