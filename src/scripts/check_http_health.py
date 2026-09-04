from __future__ import annotations

import argparse
import json
import sys
from collections.abc import Callable
from typing import Protocol
from urllib.parse import urlparse
from urllib.request import urlopen


class HealthResponse(Protocol):
    status: int

    def read(self) -> bytes: ...

    def __enter__(self) -> HealthResponse: ...

    def __exit__(self, *args: object) -> None: ...


HealthOpener = Callable[..., HealthResponse]


class HealthCheckError(RuntimeError):
    pass


def check_health_endpoint(
    label: str,
    url: str,
    *,
    opener: HealthOpener = urlopen,
) -> dict[str, object]:
    parsed = urlparse(url)
    if parsed.scheme != "http" or parsed.hostname not in {"127.0.0.1", "localhost", "::1"}:
        raise HealthCheckError(f"{label} 健康检查只允许本机 HTTP 地址：{url}")

    try:
        with opener(url, timeout=10) as response:
            if response.status != 200:
                raise HealthCheckError(f"{label} 健康检查返回 HTTP {response.status}")
            payload = json.loads(response.read())
    except HealthCheckError:
        raise
    except (OSError, UnicodeDecodeError, json.JSONDecodeError) as exc:
        raise HealthCheckError(f"{label} 健康检查请求或 JSON 解析失败：{exc}") from exc

    if not isinstance(payload, dict) or payload.get("status") != "ok":
        status = payload.get("status") if isinstance(payload, dict) else None
        raise HealthCheckError(f"{label} 健康检查 status 不是 ok：{status!r}")
    return payload


def parse_endpoint(value: str) -> tuple[str, str]:
    label, separator, url = value.partition("=")
    if not separator or not label.strip() or not url.strip():
        raise argparse.ArgumentTypeError("endpoint 必须使用 LABEL=http://127.0.0.1/path 格式")
    return label.strip(), url.strip()


def build_parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(description="验证 HomeCare Twin 本地 JSON 健康端点")
    parser.add_argument(
        "--endpoint",
        action="append",
        required=True,
        type=parse_endpoint,
        metavar="LABEL=URL",
    )
    return parser


def main() -> int:
    args = build_parser().parse_args()
    try:
        for label, url in args.endpoint:
            payload = check_health_endpoint(label, url)
            print(f"{label}: status={payload['status']} url={url}")
    except HealthCheckError as exc:
        print(str(exc), file=sys.stderr)
        return 1
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
