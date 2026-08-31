import runpy
import sys
import time

import requests

import monitor


NETWORK_BACKOFF_SECONDS = [5, 15, 30]


def resilient_request_api(session: requests.Session, endpoint: str, params):
    """Retry only transient network/server failures without changing API parsing logic."""
    api_key = monitor.required_env("ASSEMBLY_API_KEY")
    query = {"KEY": api_key, "Type": "json", **params}
    url = f"{monitor.BASE_URL}/{endpoint}"
    total_attempts = len(NETWORK_BACKOFF_SECONDS) + 1
    last_error = None

    for attempt in range(1, total_attempts + 1):
        try:
            response = session.get(url, params=query, timeout=30)

            if response.status_code == 429 or response.status_code >= 500:
                raise requests.HTTPError(
                    f"transient HTTP {response.status_code}",
                    response=response,
                )

            response.raise_for_status()
            return response.json()

        except requests.HTTPError as exc:
            status = exc.response.status_code if exc.response is not None else None
            if status is not None and status != 429 and status < 500:
                raise RuntimeError(
                    f"국회 API 호출 실패(재시도 비대상 HTTP {status}): {endpoint}: {exc}"
                ) from exc
            last_error = exc

        except (requests.ConnectionError, requests.Timeout) as exc:
            last_error = exc

        except requests.RequestException as exc:
            last_error = exc

        except ValueError as exc:
            # 연결은 성공했지만 JSON이 깨진 경우도 일시적 응답 장애로 보고 재시도한다.
            last_error = exc

        if attempt < total_attempts:
            wait_seconds = NETWORK_BACKOFF_SECONDS[attempt - 1]
            print(
                f"[WARN] 국회 API 일시 장애: {endpoint} / "
                f"시도 {attempt}/{total_attempts} 실패 / {wait_seconds}초 후 재시도 / {last_error}"
            )
            time.sleep(wait_seconds)

    raise RuntimeError(
        f"국회 API 네트워크 재시도 소진: {endpoint} / "
        f"총 {total_attempts}회 시도 / 마지막 오류: {last_error}"
    )


def main() -> int:
    if len(sys.argv) != 2:
        raise SystemExit("사용법: python run_with_network_retry.py <script.py>")

    target = sys.argv[1]
    monitor.request_api = resilient_request_api
    print(
        "[INFO] 국회 API 네트워크 재시도 강화 적용: "
        "최대 4회 / 대기 5초 → 15초 → 30초"
    )
    runpy.run_path(target, run_name="__main__")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
