import asyncio
import sys

from proxy_core import handle_proxy_request


async def main() -> None:
    checks = [
        ("GET", "/healthz", 200, "application/json"),
        ("GET", "/stations/KPHX.TXT", 200, "text/plain"),
        ("GET", "/tgftp/stations/KDEN.TXT", 200, "text/plain"),
        ("HEAD", "/stations/KPHX.TXT", 200, "text/plain"),
        ("GET", "/not-a-route", 404, "application/json"),
    ]

    for method, path, expected_status, expected_content_type in checks:
        result = await handle_proxy_request(method=method, path=path)
        actual_type = result["headers"].get("content-type", "")
        if result["status"] != expected_status:
            raise SystemExit(f"{method} {path} -> expected {expected_status}, got {result['status']}")
        if not actual_type.startswith(expected_content_type):
            raise SystemExit(f"{method} {path} -> expected {expected_content_type}, got {actual_type}")
        print(f"{method} {path} -> {result['status']} {actual_type}")


if __name__ == "__main__":
    try:
        asyncio.run(main())
    except Exception as exc:
        print(str(exc), file=sys.stderr)
        raise
