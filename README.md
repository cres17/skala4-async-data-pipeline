# 비동기 데이터 수집 미니 파이프라인 제작 실습

![Python 3.14](https://img.shields.io/badge/Python-3.14-3776AB?logo=python&logoColor=white)

세 API에서 날씨·국가·IP 위치 데이터를 동시에 가져와 검증하고, CSV와 Parquet로 저장하는 실습이다. 저장 후에는 파일을 다시 읽어 데이터가 빠지지 않았는지 확인하고 형식별 처리 시간도 비교한다.

## 수집 데이터

| API | 수집 내용 |
|---|---|
| Open-Meteo | 서울 3일간 시간대별 기온과 강수 확률 |
| Countries.dev | 대한민국 국가명, 국가 코드, 수도, 인구 |
| ip-api | `8.8.8.8`의 국가, 도시, 위도, 경도 |

## 주요 기능

- `asyncio.gather()`를 이용한 API 3개 동시 요청
- `raise_for_status()`를 이용한 HTTP 오류 확인
- Pydantic v2를 이용한 타입·필수값·범위 검증
- CSV·Parquet 읽기와 쓰기 시간 5회 측정 후 중앙값 비교
- 저장 전후 행 수와 컬럼 일치 여부 확인
- DNS 또는 SSL 연결이 멈출 때 수집 작업을 10초 후 종료

## 프로젝트 구조

```text
async_data_pipeline/
├── main.py                 # 전체 실행 흐름
├── collectors.py           # 비동기 API 수집과 응답 변환
├── collector_worker.py     # 네트워크 수집 작업 프로세스
├── models.py               # Pydantic 검증 모델
├── storage.py              # CSV·Parquet 저장과 성능 측정
├── test_pipeline.py        # 검증 규칙 테스트
├── requirements.txt        # 설치 패키지
└── data/                   # 실행 결과 파일
```

## 실행 방법

처음 실행할 때만 가상환경을 만들고 패키지를 설치한다.

```bash
python3 -m venv .venv
.venv/bin/python -m pip install -r requirements.txt
```

메인 프로그램을 실행한다.

```bash
.venv/bin/python -u main.py
```

코드 테스트와 스타일 검사는 아래 명령으로 확인한다.

```bash
.venv/bin/python -m pytest -q
.venv/bin/python -m ruff check .
```

## 실행 결과

실제 실행에서는 날씨 72건, 국가 정보 1건, IP 위치 정보 1건을 합쳐 총 74건을 저장했다.

```text
INFO | [핵심 확인] 세 API 응답 3건을 모두 정상 수집했습니다.
INFO | [핵심 확인] Pydantic 검증 통과: 날씨 72건, 국가 1건, IP 위치 1건

=== CSV·Parquet 무결성 검증 완료 ===
저장 전후 행 수: 74건 (CSV / Parquet 모두 일치)
```

생성 파일:

- `data/collected_data.csv`
- `data/collected_data.parquet`

## 참고 사항

폴더명을 변경해도 실행 파일이 이전 가상환경 경로를 참조하지 않도록 `.venv/bin/python -m ...` 형식으로 실행한다. `main.py`를 시스템 Python으로 실행해도 현재 프로젝트의 `.venv`로 한 번만 자동 전환한다.

`ip-api` 무료 주소는 HTTP를 사용하므로 실행 환경에서 HTTP 연결을 차단하면 해당 요청이 실패할 수 있다. 이 경우 프로그램은 실패한 수집 작업과 원인을 로그로 출력한다.
