"""Request normalization and validation."""

from __future__ import annotations

from typing import Any
import re
from urllib.parse import urlparse

from .errors import RequestError
from .schema import DECODERS, RESOLUTIONS, SCENARIOS, schema


def normalize_codec(value: Any, field: str) -> str | None:
    if value is None:
        return None
    codec = str(value).lower().replace("hevc", "h265").replace("avc", "h264")
    if codec not in DECODERS:
        raise RequestError("INVALID_REQUEST", f"{field} 仅支持 h264/h265")
    return codec


def build_request(request: dict[str, Any]) -> dict[str, Any]:
    allowed = set(schema()["properties"])
    unknown = sorted(set(request) - allowed)
    if unknown:
        raise RequestError("INVALID_REQUEST", f"不支持的参数：{', '.join(unknown)}")
    scenario = request.get("scenario")
    if scenario not in SCENARIOS:
        raise RequestError("INVALID_REQUEST", f"scenario 必须是：{', '.join(SCENARIOS)}")
    streams = int(request.get("streams", 1))
    if not 1 <= streams <= 8:
        raise RequestError("INVALID_REQUEST", "streams 必须在 1 到 8 之间")
    if scenario != "multi-decode" and streams != 1:
        raise RequestError("INVALID_REQUEST", "只有 multi-decode 支持 streams > 1")
    duration = int(request.get(
        "duration_seconds", 300 if scenario in {"file-stream", "camera-stream"} else 10
    ))
    if not 1 <= duration <= 3600:
        raise RequestError("INVALID_REQUEST", "duration_seconds 必须在 1 到 3600 之间")
    resolution = request.get("resolution")
    output_resolution = request.get("output_resolution")
    if resolution not in {None, *RESOLUTIONS}:
        raise RequestError("INVALID_REQUEST", "resolution 仅支持 720p/1080p/4k")
    if output_resolution not in {None, *RESOLUTIONS}:
        raise RequestError("INVALID_REQUEST", "output_resolution 仅支持 720p/1080p/4k")
    frame_rate = int(request.get("frame_rate", 30))
    if not 1 <= frame_rate <= 120:
        raise RequestError("INVALID_REQUEST", "frame_rate 必须在 1 到 120 之间")
    bitrate = str(request.get("bitrate", "8M"))
    if not re.fullmatch(r"[1-9][0-9]*[kKmM]", bitrate):
        raise RequestError("INVALID_REQUEST", "bitrate 格式应为4M或8000k")
    if scenario == "encode-raw" and not resolution:
        raise RequestError("INVALID_REQUEST", "encode-raw 必须指定 resolution")
    url = request.get("url")
    url_defaulted = False
    if scenario in {"file-stream", "camera-stream"} and not url:
        url = "udp://239.1.1.1:5004"
        url_defaulted = True
    if scenario in {"rtsp-play", "rtsp-record"} and not url:
        raise RequestError("INVALID_REQUEST", f"{scenario} 必须指定 url")
    if url:
        scheme = urlparse(str(url)).scheme.lower()
        allowed_schemes = (
            {"rtsp", "rtsps"}
            if scenario in {"rtsp-play", "rtsp-record"}
            else {"rtsp", "rtsps", "rtmp", "rtmps", "udp"}
        )
        if scheme not in allowed_schemes:
            raise RequestError(
                "INVALID_REQUEST",
                f"{scenario} 的 url 协议仅支持：{', '.join(sorted(allowed_schemes))}",
            )
    transport = str(request.get("transport", "tcp")).lower()
    if transport not in {"tcp", "udp"}:
        raise RequestError("INVALID_REQUEST", "transport 仅支持 tcp/udp")
    start_seconds = int(request.get("start_seconds", 0))
    if not 0 <= start_seconds <= 86400:
        raise RequestError("INVALID_REQUEST", "start_seconds 必须在 0 到 86400 之间")
    image_format = str(request.get("image_format", "jpeg")).lower().replace("jpg", "jpeg")
    if image_format not in {"jpeg", "png"}:
        raise RequestError("INVALID_REQUEST", "image_format 仅支持 jpeg/png")
    output_codec = normalize_codec(request.get("output_codec", "h264"), "output_codec")
    if url and urlparse(str(url)).scheme.lower() in {"rtmp", "rtmps"} and output_codec != "h264":
        raise RequestError("INVALID_REQUEST", "RTMP 推流仅支持 H.264")
    return {
        **request,
        "scenario": scenario,
        "input": (
            str(request["input"]) if request.get("input") is not None
            else (None if "camera" in scenario else "~/Videos")
        ),
        "input_codec": normalize_codec(request.get("input_codec"), "input_codec"),
        "output_codec": output_codec,
        "streams": streams,
        "duration_seconds": duration,
        "resolution": resolution,
        "output_resolution": output_resolution,
        "frame_rate": frame_rate,
        "bitrate": bitrate,
        "url": str(url) if url else None,
        "url_defaulted": url_defaulted,
        "transport": transport,
        "start_seconds": start_seconds,
        "image_format": image_format,
    }
