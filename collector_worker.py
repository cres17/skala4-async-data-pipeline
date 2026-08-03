# -----------------------------------------------------------------------------
# collector_worker.py
#
# 파일 역할
# - httpx와 SSL을 메인 프로그램과 분리된 프로세스에서 초기화한다.
# - collect_all()의 비동기 수집 결과를 JSON으로 부모 프로세스에 전달한다.
# - DNS 또는 SSL이 멈추면 main.py가 이 프로세스만 안전하게 종료할 수 있게 한다.
#
# 변경 이력
# - 2026-08-03: 네트워크 장기 대기 방지용 수집 작업 프로세스 최초 작성
# - 2026-08-03: 함수·기능 설명 주석 보강
# -----------------------------------------------------------------------------

import asyncio
import json
import sys

from collectors import collect_all


# 수집 결과는 표준 출력에 JSON 하나만 기록해 부모 프로세스로 전달한다.
def main() -> None:
    # 비동기 수집이 끝난 후 부모가 파싱할 수 있도록 JSON만 출력한다.
    payloads = asyncio.run(collect_all())
    json.dump(payloads, sys.stdout, ensure_ascii=False)


if __name__ == "__main__":
    main()
