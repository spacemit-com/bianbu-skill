"""Command-line and JSON protocol adapter."""

from __future__ import annotations

import argparse
import json
import os
import sys
from typing import Any

from .capabilities import probe_capabilities
from .errors import RequestError
from .executor import execute
from .request import build_request
from .schema import RESOLUTIONS, SCENARIOS, schema


def emit(value: dict[str, Any]) -> None:
    print(json.dumps(value, ensure_ascii=False, separators=(",", ":")))


def error_envelope(code: str, message: str, request: Any) -> dict[str, Any]:
    scenario = request.get("scenario") if isinstance(request, dict) else None
    return {
        "status": "FAILED",
        "scenario": scenario if scenario in SCENARIOS else None,
        "backend": None,
        "pipeline": None,
        "pipeline_stages": None,
        "commands": None,
        "input": None,
        "output": None,
        "target_url": None,
        "streams": None,
        "duration_seconds": None,
        "processes": None,
        "output_bytes": None,
        "output_media_info": None,
        "media_info": None,
        "error_code": code,
        "summary": message,
    }


def read_request() -> Any:
    if sys.stdin.isatty():
        raise RequestError(
            "INVALID_REQUEST",
            "stdin 没有 JSON 请求；请改用 --scenario 等 CLI 参数或 --request-json",
        )
    payload = os.read(sys.stdin.fileno(), 65536)
    if not payload:
        raise RequestError("INVALID_REQUEST", "stdin 没有 JSON 请求")
    try:
        return json.loads(payload.decode("utf-8"))
    except (UnicodeDecodeError, json.JSONDecodeError) as exc:
        raise RequestError("INVALID_REQUEST", f"stdin JSON 无效：{exc}") from exc


def parser() -> argparse.ArgumentParser:
    result = argparse.ArgumentParser(description="Small, deterministic K3 media scenario runner.")
    result.add_argument("--describe", action="store_true")
    result.add_argument("--dry-run", action="store_true")
    result.add_argument("--probe", action="store_true")
    result.add_argument("--scenario", choices=SCENARIOS)
    result.add_argument("--input")
    result.add_argument("--input-codec", choices=("h264", "h265"))
    result.add_argument("--resolution", choices=tuple(RESOLUTIONS))
    result.add_argument("--output-resolution", choices=tuple(RESOLUTIONS))
    result.add_argument("--output")
    result.add_argument("--url")
    result.add_argument("--transport", choices=("tcp", "udp"))
    result.add_argument("--start-seconds", type=int)
    result.add_argument("--image-format", choices=("jpeg", "png"))
    result.add_argument("--output-codec", choices=("h264", "h265"))
    result.add_argument("--streams", type=int)
    result.add_argument("--duration-seconds", type=int)
    result.add_argument("--frame-rate", type=int)
    result.add_argument("--input-format", choices=("mjpeg", "yuyv422"))
    result.add_argument("--bitrate")
    result.add_argument("--request-json", help="完整请求 JSON；与 --scenario 等参数二选一")
    return result


def main() -> int:
    args = parser().parse_args()
    if args.describe:
        emit(schema())
        return 0
    if args.probe:
        emit(probe_capabilities())
        return 0
    request: Any = None
    try:
        cli_fields = {
            "scenario": args.scenario,
            "input": args.input,
            "input_codec": args.input_codec,
            "resolution": args.resolution,
            "output_resolution": args.output_resolution,
            "output": args.output,
            "url": args.url,
            "transport": args.transport,
            "start_seconds": args.start_seconds,
            "image_format": args.image_format,
            "output_codec": args.output_codec,
            "streams": args.streams,
            "duration_seconds": args.duration_seconds,
            "frame_rate": args.frame_rate,
            "input_format": args.input_format,
            "bitrate": args.bitrate,
        }
        has_cli_request = any(value is not None for value in cli_fields.values())
        if args.request_json and has_cli_request:
            raise RequestError("INVALID_REQUEST", "--request-json 不能与场景参数同时使用")
        if args.request_json:
            request = json.loads(args.request_json)
        elif has_cli_request:
            request = {key: value for key, value in cli_fields.items() if value is not None}
        else:
            request = read_request()
        if not isinstance(request, dict):
            raise RequestError("INVALID_REQUEST", "stdin 必须是 JSON object")
        response = execute(build_request(request), args.dry_run)
        emit(response)
        return 0 if response["status"] in {"SUCCESS", "DRY_RUN"} else 1
    except RequestError as exc:
        emit(error_envelope(exc.code, str(exc), request))
        return 2
    except (ValueError, TypeError, json.JSONDecodeError) as exc:
        emit(error_envelope("INVALID_REQUEST", str(exc), request))
        return 2
