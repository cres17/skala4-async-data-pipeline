# -----------------------------------------------------------------------------
# SKALA 2) AI의 서비스화 데이터분석 및 AIOps
# 1. 데이터 분석을 위한 Python 이해
# [Day 1 종합 실습] 비동기 API 수집 · Pydantic v2 검증 · 파일 성능 비교
#
# 문제 구성
# 1) 서로 다른 세 API의 데이터를 asyncio와 httpx로 동시에 수집
# 2) API별 필수 필드를 Pydantic v2 모델로 검증
# 3) 검증 데이터를 CSV와 Parquet 형식으로 저장
# 4) 두 형식의 읽기·쓰기 시간과 파일 크기 비교
# 5) 저장 파일 재로딩을 통한 행 수와 컬럼 무결성 확인
#
# 프로그램 설명
# - Open-Meteo에서 서울의 3일간 시간대별 기온과 강수 확률을 수집한다.
# - Countries.dev에서 대한민국 국가 정보를 수집한다.
# - ip-api에서 8.8.8.8의 국가·도시·위도·경도 정보를 수집한다.
# - 세 API 요청은 asyncio.gather()로 동시에 처리한다.
# - Pydantic v2로 타입, 필수값, 허용 범위를 검증한 데이터만 저장한다.
# - CSV와 Parquet를 각각 5회 읽고 쓰며 중앙값으로 성능을 비교한다.
# - 저장한 파일을 다시 읽어 74건의 데이터와 컬럼이 유지됐는지 확인한다.
# - DNS 또는 SSL 초기화가 멈추면 별도 수집 프로세스를 10초 후 종료한다.
#
# 변경 이력
# - 2026-08-03: 최초 작성
# -----------------------------------------------------------------------------

import asyncio
import json
import logging
import os
import subprocess
import sys
from pathlib import Path
from typing import Any

# ★ 시스템 Python으로 직접 실행해도 프로젝트 가상환경으로 자동 전환한다.
#    따라서 `python main.py` 실행 시 pandas 등의 패키지를 찾지 못하는 문제를 막는다.
PROJECT_DIR = Path(__file__).resolve().parent
VENV_PYTHON = PROJECT_DIR / ".venv" / "bin" / "python"
VENV_REEXEC_FLAG = "DAY1_VENV_REEXECUTED"
if __name__ == "__main__" and VENV_PYTHON.is_file():
    # macOS 한글 경로는 NFC/NFD 표기가 달라질 수 있으므로 문자열로 비교하지 않는다.
    # samefile()로 실제 동일 폴더인지 확인하고, 환경 변수로 재실행을 한 번만 허용한다.
    venv_dir = PROJECT_DIR / ".venv"
    try:
        using_project_venv = os.path.samefile(sys.prefix, venv_dir)
    except OSError:
        using_project_venv = False

    if not using_project_venv and os.environ.get(VENV_REEXEC_FLAG) != "1":
        print("[준비] 프로젝트 가상환경으로 전환합니다.", flush=True)
        child_environment = os.environ.copy()
        child_environment[VENV_REEXEC_FLAG] = "1"
        os.execve(
            str(VENV_PYTHON),
            [str(VENV_PYTHON), str(Path(__file__).resolve()), *sys.argv[1:]],
            child_environment,
        )

import pandas as pd
from pydantic import ValidationError

from collectors import country_row, ip_location_row, weather_rows
from models import CountryInfo, IpLocation, WeatherRecord
from storage import save_and_benchmark

DATA_DIR = PROJECT_DIR / "data"
LOGGER = logging.getLogger(__name__)
COLLECTOR_WORKER = PROJECT_DIR / "collector_worker.py"
WORKER_TIMEOUT_SECONDS = 10.0

logging.basicConfig(level=logging.INFO, format="%(levelname)s | %(message)s", stream=sys.stdout)


# API 응답이 Pydantic 스키마 검증에 실패한 경우의 예외
class DataValidationError(RuntimeError):
    pass


# 외부 API 수집 작업이 제한 시간 안에 끝나지 않았을 때의 예외
class CollectionWorkerError(RuntimeError):
    pass


# ★ 네트워크·SSL 초기화가 멈춰도 자식 프로세스를 10초 안에 종료한다.
def collect_in_worker() -> dict[str, dict[str, Any]]:
    LOGGER.info("[수집 시작] 세 API를 동시에 요청합니다. 최대 대기 시간: %.0f초", WORKER_TIMEOUT_SECONDS)

    # 1) 네트워크 수집 전용 Python 프로세스를 실행하고 표준 출력을 받는다.
    try:
        completed = subprocess.run(
            [sys.executable, "-u", str(COLLECTOR_WORKER)],
            capture_output=True,
            check=True,
            text=True,
            timeout=WORKER_TIMEOUT_SECONDS,
        )

    # 2) 제한 시간 초과와 작업 프로세스 자체 오류를 구분해 알기 쉽게 전달한다.
    except subprocess.TimeoutExpired as error:
        raise CollectionWorkerError(
            f"API 수집이 {WORKER_TIMEOUT_SECONDS:.0f}초 안에 끝나지 않아 안전하게 종료했습니다. "
            "네트워크 또는 DNS 연결 상태를 확인하세요."
        ) from error
    except subprocess.CalledProcessError as error:
        lines = error.stderr.strip().splitlines()
        detail = lines[-1] if lines else "알 수 없는 오류"
        raise CollectionWorkerError(f"API 수집 실패: {detail}") from error

    # 3) 작업 프로세스가 전달한 JSON 문자열을 검증용 딕셔너리로 복원한다.
    try:
        payloads = json.loads(completed.stdout)
    except json.JSONDecodeError as error:
        raise CollectionWorkerError("API 수집 결과를 JSON으로 읽지 못했습니다.") from error
    if not isinstance(payloads, dict):
        raise CollectionWorkerError("API 수집 결과 형식이 올바르지 않습니다.")

    LOGGER.info("[핵심 확인] 세 API 응답 3건을 모두 정상 수집했습니다.")
    return payloads


# Pydantic의 상세 오류 위치와 원인을 한 줄 로그 메시지로 정리한다.
def _validation_message(source: str, error: ValidationError) -> str:
    details = "; ".join(
        f"{'.'.join(str(part) for part in item['loc'])}: {item['msg']}"
        for item in error.errors()
    )
    return f"{source} Pydantic 검증 실패 - {details}"


# 필요한 값만 모델 검증하고, 저장용 공통 컬럼 형태로 합친다.
def validate_payloads(payloads: dict[str, dict[str, Any]]) -> pd.DataFrame:
    # 1) API별 변환 함수를 거친 값을 해당 Pydantic 모델로 검증한다.
    try:
        weather = [WeatherRecord.model_validate(row) for row in weather_rows(payloads["weather"])]
        country = CountryInfo.model_validate(country_row(payloads["country"]))
        location = IpLocation.model_validate(ip_location_row(payloads["ip_location"]))
    except ValidationError as error:
        LOGGER.error("%s", _validation_message("API 응답", error))
        raise DataValidationError(_validation_message("API 응답", error)) from error
    except (KeyError, TypeError, ValueError) as error:
        raise DataValidationError(f"API 응답 구조 검증 실패 - {error}") from error

    # 2) 서로 다른 세 데이터 유형을 동일한 저장 컬럼 구조로 맞춘다.
    rows = [
        {
            "record_type": "weather",
            "observed_at": record.observed_at.isoformat(),
            "temperature_c": record.temperature_c,
            "precipitation_probability": record.precipitation_probability,
            "country_name": None,
            "country_code": None,
            "capital": None,
            "population": None,
            "ip": None,
            "city": None,
            "latitude": None,
            "longitude": None,
        }
        for record in weather
    ]
    rows.append(
        {
            "record_type": "country",
            "observed_at": None,
            "temperature_c": None,
            "precipitation_probability": None,
            **country.model_dump(),
            "ip": None,
            "city": None,
            "latitude": None,
            "longitude": None,
        }
    )
    rows.append(
        {
            "record_type": "ip_location",
            "observed_at": None,
            "temperature_c": None,
            "precipitation_probability": None,
            "country_code": None,
            "capital": None,
            "population": None,
            **location.model_dump(mode="json"),
        }
    )

    # 3) DataFrame 생성 후 검증 모델 수와 최종 행 수가 같은지 확인한다.
    frame = pd.DataFrame(rows)
    if len(frame) != len(weather) + 2:
        raise DataValidationError("검증된 데이터 행 수가 예상과 다릅니다.")
    LOGGER.info("[핵심 확인] Pydantic 검증 통과: 날씨 %d건, 국가 1건, IP 위치 1건", len(weather))
    return frame


# 전체 파이프라인을 실행하고 결과를 사람이 읽기 쉽게 출력한다.
async def run_pipeline() -> None:
    print("\n=== Day 1 데이터 파이프라인 시작 ===", flush=True)

    # 1) 별도 프로세스에서 세 API를 동시에 수집한다.
    payloads = await asyncio.to_thread(collect_in_worker)

    # 2) 수집한 원본 JSON을 Pydantic으로 검증해 저장용 DataFrame으로 만든다.
    frame = validate_payloads(payloads)

    # 3) CSV·Parquet 저장, 재로딩 검증, 반복 성능 측정을 수행한다.
    benchmarks = save_and_benchmark(frame, DATA_DIR)

    # 4) 제출 화면에서 핵심 결과를 한눈에 확인할 수 있도록 출력한다.
    print("\n=== ★ CSV·Parquet 무결성 검증 완료 ===")
    print(f"저장 전후 행 수: {len(frame)}건 (CSV / Parquet 모두 일치)")
    print("측정 기준: 동일 조건 5회 반복의 중앙값")
    for format_name, result in benchmarks.items():
        print(
            f"{format_name:<7} | 쓰기 {result.write_seconds:.6f}초 | "
            f"읽기 {result.read_seconds:.6f}초 | {result.size_bytes:,} bytes"
        )
    print(f"\n생성 파일: {DATA_DIR / 'collected_data.csv'}")
    print(f"생성 파일: {DATA_DIR / 'collected_data.parquet'}")


# 명령줄 실행 진입점
def main() -> None:
    # 전체 비동기 흐름을 실행하고 예상 가능한 오류를 한 곳에서 처리한다.
    try:
        asyncio.run(run_pipeline())
    except (RuntimeError, ValidationError, OSError) as error:
        LOGGER.error("프로그램 실행 실패: %s", error)
        raise SystemExit(1) from error


if __name__ == "__main__":
    main()
