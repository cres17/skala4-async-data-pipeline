# -----------------------------------------------------------------------------
# storage.py
#
# 파일 역할
# - 검증 데이터를 CSV와 Parquet 형식으로 저장한다.
# - 각 형식의 읽기·쓰기 시간을 반복 측정해 중앙값을 계산한다.
# - 파일 생성 여부와 재로딩 후 행 수·컬럼 일치를 확인한다.
#
# 변경 이력
# - 2026-08-03: CSV·Parquet 저장 및 성능 측정 함수 최초 작성
# - 2026-08-03: 5회 중앙값 측정과 재로딩 무결성 검사 추가
# - 2026-08-03: 함수·기능 설명 주석 보강
# -----------------------------------------------------------------------------

from dataclasses import dataclass
from pathlib import Path
from statistics import median
from time import perf_counter

import pandas as pd


# 한 파일 형식의 중앙값 기반 성능 측정 결과
@dataclass(frozen=True)
class FormatBenchmark:
    write_seconds: float
    read_seconds: float
    size_bytes: int


# 전달받은 파일 작업을 반복 실행하고 경과 시간의 중앙값을 반환한다.
def _median_duration(operation, repeats: int) -> float:
    durations = []

    # perf_counter()로 각 실행의 고해상도 경과 시간을 측정한다.
    for _ in range(repeats):
        start = perf_counter()
        operation()
        durations.append(perf_counter() - start)
    return median(durations)


# ★ 양쪽 파일의 행·열을 재확인하고 읽기/쓰기 중앙값을 반환한다.
def save_and_benchmark(frame: pd.DataFrame, output_dir: Path, repeats: int = 5) -> dict[str, FormatBenchmark]:
    if repeats < 1:
        raise ValueError("반복 횟수는 1 이상이어야 합니다.")

    # 1) 출력 폴더를 준비하고 두 형식의 저장 경로를 결정한다.
    output_dir.mkdir(parents=True, exist_ok=True)
    csv_path = output_dir / "collected_data.csv"
    parquet_path = output_dir / "collected_data.parquet"

    # 2) 동일 조건으로 읽기·쓰기를 반복해 형식별 중앙값을 구한다.
    csv_write = _median_duration(lambda: frame.to_csv(csv_path, index=False), repeats)
    parquet_write = _median_duration(lambda: frame.to_parquet(parquet_path, index=False), repeats)
    csv_read = _median_duration(lambda: pd.read_csv(csv_path), repeats)
    parquet_read = _median_duration(lambda: pd.read_parquet(parquet_path), repeats)

    # 3) 파일 생성 여부를 확인한 뒤 다시 읽어 행 수와 컬럼을 비교한다.
    if not csv_path.is_file() or not parquet_path.is_file():
        raise RuntimeError("CSV 또는 Parquet 파일이 생성되지 않았습니다.")

    csv_frame = pd.read_csv(csv_path)
    parquet_frame = pd.read_parquet(parquet_path)
    expected_columns = list(frame.columns)
    for format_name, reloaded in (("CSV", csv_frame), ("Parquet", parquet_frame)):
        if len(reloaded) != len(frame):
            raise RuntimeError(f"{format_name} 재로딩 행 수가 저장 전과 다릅니다.")
        if list(reloaded.columns) != expected_columns:
            raise RuntimeError(f"{format_name} 재로딩 컬럼이 저장 전과 다릅니다.")

    # 4) 실행 파일 크기까지 포함한 형식별 측정 결과를 반환한다.
    return {
        "CSV": FormatBenchmark(csv_write, csv_read, csv_path.stat().st_size),
        "Parquet": FormatBenchmark(
            parquet_write,
            parquet_read,
            parquet_path.stat().st_size,
        ),
    }
