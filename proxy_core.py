from __future__ import annotations

import json
import os
import re
from datetime import datetime, timedelta, timezone

import httpx

AWC_API_BASE = "https://aviationweather.gov/api/data/metar"
TGFTP_BASE_URL = "https://tgftp.nws.noaa.gov/data/observations/metar/stations"
DEFAULT_USER_AGENT = "weather_app/1.0 (github.com/weather-arb-dev)"


def env(name: str, fallback: str) -> str:
    return os.getenv(name, fallback)


def json_result(payload: dict, status: int = 200, headers: dict | None = None) -> dict:
    return {
        "status": status,
        "headers": {"content-type": "application/json; charset=utf-8", **(headers or {})},
        "body": json.dumps(payload, indent=2),
    }


def text_result(body: str, status: int = 200, headers: dict | None = None) -> dict:
    return {
        "status": status,
        "headers": {"content-type": "text/plain; charset=utf-8", **(headers or {})},
        "body": body,
    }


def extract_station_request(pathname: str) -> dict | None:
    match = re.match(r"^/(?:(tgftp)/)?stations/([A-Za-z0-9]{4})\.TXT$", pathname)
    if not match:
        return None

    return {
        "upstream": "tgftp" if match.group(1) == "tgftp" else "awc",
        "station": match.group(2).upper(),
    }


def format_header_time(value: datetime) -> str:
    return value.astimezone(timezone.utc).strftime("%Y/%m/%d %H:%M")


def parse_metar_observation_time(raw_text: str, now: datetime | None = None) -> datetime | None:
    match = re.search(r"\b(\d{2})(\d{2})(\d{2})Z\b", raw_text or "")
    if not match:
        return None

    now = now or datetime.now(timezone.utc)
    day = int(match.group(1))
    hour = int(match.group(2))
    minute = int(match.group(3))
    candidates: list[datetime] = []

    month_starts = []
    base = now.replace(day=1, hour=0, minute=0, second=0, microsecond=0)
    for month_delta in (-1, 0, 1):
        shifted = (base + timedelta(days=32 * month_delta)).replace(day=1)
        month_starts.append(shifted)

    for month_start in month_starts:
        try:
            candidate = month_start.replace(day=day, hour=hour, minute=minute)
        except ValueError:
            continue
        candidates.append(candidate)

    if not candidates:
        return None

    return min(candidates, key=lambda candidate: abs(candidate.timestamp() - now.timestamp()))


def parse_header_observation_time(header_line: str | None) -> datetime | None:
    match = re.match(r"^(\d{4})/(\d{2})/(\d{2}) (\d{2}):(\d{2})$", (header_line or "").strip())
    if not match:
        return None

    year, month, day, hour, minute = map(int, match.groups())
    try:
        return datetime(year, month, day, hour, minute, tzinfo=timezone.utc)
    except ValueError:
        return None


def first_metar_line(body_text: str) -> str | None:
    for line in (body_text or "").splitlines():
        value = line.strip()
        if value:
            return value
    return None


def extract_fallback_metar_from_json_body(body_text: str) -> str | None:
    trimmed = (body_text or "").strip()
    if not trimmed:
        return None

    payload = json.loads(trimmed)
    rows = payload if isinstance(payload, list) else []
    for row in rows:
        raw_ob = str((row or {}).get("rawOb", "")).strip()
        if raw_ob:
            return raw_ob
    return None


def extract_station_txt_payload(body_text: str) -> dict:
    lines = [
        line.rstrip()
        for line in (body_text or "").replace("\r\n", "\n").split("\n")
        if line.strip()
    ]

    if not lines:
        return {"header_line": None, "metar_line": None, "body_text": ""}

    if len(lines) == 1:
        metar_line = lines[0].strip()
        return {"header_line": None, "metar_line": metar_line, "body_text": metar_line}

    header_line = lines[0].strip()
    metar_line = next((line.strip() for line in lines[1:] if line.strip()), None)
    return {
        "header_line": header_line,
        "metar_line": metar_line,
        "body_text": f"{header_line}\n{metar_line}" if metar_line else header_line,
    }


def upstream_headers() -> dict:
    return {"User-Agent": env("UPSTREAM_USER_AGENT", DEFAULT_USER_AGENT)}


async def fetch_awc(client: httpx.AsyncClient, station: str, fmt: str) -> str:
    upstream_url = httpx.URL(env("AWC_API_BASE", AWC_API_BASE)).copy_merge_params(
        {"ids": station, "format": fmt, "hours": env("AWC_API_HOURS", "1")}
    )
    response = await client.get(upstream_url, headers=upstream_headers())
    response.raise_for_status()
    return response.text


async def fetch_awc_metar(client: httpx.AsyncClient, station: str) -> dict:
    raw_body = await fetch_awc(client, station, "raw")
    raw_metar = first_metar_line(raw_body)
    if raw_metar:
        return {"metar_line": raw_metar, "upstream_source": "aviationweather-api-raw"}

    json_body = await fetch_awc(client, station, "json")
    fallback_metar = extract_fallback_metar_from_json_body(json_body)
    return {
        "metar_line": fallback_metar,
        "upstream_source": (
            "aviationweather-api-json-fallback" if fallback_metar else "aviationweather-api-empty"
        ),
    }


async def fetch_tgftp_metar(client: httpx.AsyncClient, station: str) -> dict:
    base_url = env("TGFTP_BASE_URL", TGFTP_BASE_URL).rstrip("/")
    response = await client.get(f"{base_url}/{station}.TXT", headers=upstream_headers())
    response.raise_for_status()

    payload = extract_station_txt_payload(response.text)
    observation_date = parse_header_observation_time(payload["header_line"]) or parse_metar_observation_time(
        payload["metar_line"] or payload["body_text"]
    )
    return {
        "body_text": payload["body_text"],
        "metar_line": payload["metar_line"],
        "observation_date": observation_date,
        "upstream_source": "tgftp-station-txt",
    }


async def handle_proxy_request(method: str = "GET", path: str = "/healthz") -> dict:
    method = (method or "GET").upper()
    path = path or "/healthz"

    if method not in {"GET", "HEAD"}:
        return text_result("Method Not Allowed", status=405)

    if path == "/healthz":
        result = json_result(
            {
                "ok": True,
                "source": "awc-api-worker",
                "runtime": "prefect-cloud-flow",
            }
        )
        if method == "HEAD":
            result["body"] = ""
        return result

    station_request = extract_station_request(path)
    if not station_request:
        return json_result(
            {
                "ok": False,
                "error": "Use /stations/<ICAO>.TXT or /tgftp/stations/<ICAO>.TXT, for example /tgftp/stations/KDEN.TXT",
            },
            status=404,
        )

    async with httpx.AsyncClient(timeout=15.0, follow_redirects=True) as client:
        try:
            station = station_request["station"]
            upstream = station_request["upstream"]

            if upstream == "tgftp":
                payload = await fetch_tgftp_metar(client, station)
                if not payload["metar_line"]:
                    return text_result(f"No METAR found for station {station}", status=404)

                headers = {
                    "Cache-Control": "no-store",
                    "X-Upstream-Source": payload["upstream_source"],
                }
                if payload["observation_date"]:
                    headers["Last-Modified"] = payload["observation_date"].strftime("%a, %d %b %Y %H:%M:%S GMT")

                return text_result("" if method == "HEAD" else payload["body_text"], headers=headers)

            payload = await fetch_awc_metar(client, station)
            if not payload["metar_line"]:
                return text_result(f"No METAR found for station {station}", status=404)

            observation_date = parse_metar_observation_time(payload["metar_line"])
            body = (
                f"{format_header_time(observation_date)}\n{payload['metar_line']}"
                if observation_date
                else payload["metar_line"]
            )
            headers = {
                "Cache-Control": "no-store",
                "X-Upstream-Source": payload["upstream_source"],
            }
            if observation_date:
                headers["Last-Modified"] = observation_date.strftime("%a, %d %b %Y %H:%M:%S GMT")

            return text_result("" if method == "HEAD" else body, headers=headers)
        except httpx.HTTPStatusError as exc:
            return json_result({"ok": False, "error": f"Upstream returned {exc.response.status_code}"}, status=502)
        except Exception as exc:
            return json_result({"ok": False, "error": str(exc)}, status=502)
