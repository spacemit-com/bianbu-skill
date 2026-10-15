"""Media probing, input selection, and output path handling."""

from __future__ import annotations

import datetime as dt
import fcntl
import json
import os
import struct
from pathlib import Path
from typing import Any

from .capabilities import require_program, run_capture
from .errors import RequestError
from .schema import DECODERS, RAW_VIDEO_EXTENSIONS, RESOLUTIONS, VIDEO_EXTENSIONS


V4L2_QUERYCAP = 0x80685600
V4L2_CAP_VIDEO_CAPTURE = 0x00000001


def _is_capture_device(path: Path) -> bool:
    try:
        with open(path, "rb") as handle:
            caps = fcntl.ioctl(handle, V4L2_QUERYCAP, b"\x00" * 104)
    except OSError:
        return False
    capabilities = struct.unpack_from("<I", caps, 84)[0]
    return bool(capabilities & V4L2_CAP_VIDEO_CAPTURE)


def resolve_camera_device(raw: str | None) -> str:
    """Pick the first /dev/video* capture node, or validate an explicit one."""
    devices = [str(item) for item in sorted(Path("/dev").glob("video*")) if _is_capture_device(item)]
    if raw:
        device = str(Path(os.path.expandvars(os.path.expanduser(raw))).resolve())
        if device in devices:
            return device
        hint = f"可用采集设备：{', '.join(devices)}" if devices else "未发现可用采集设备"
        raise RequestError("INPUT_NOT_FOUND", f"{device} 不是摄像头采集设备；{hint}")
    if not devices:
        raise RequestError("INPUT_NOT_FOUND", "未发现可用的摄像头采集设备（已扫描 /dev/video*）")
    return devices[0]


def probe_file(path: Path) -> dict[str, Any]:
    ffprobe = require_program("ffprobe")
    result = run_capture([
        ffprobe, "-v", "error", "-select_streams", "v:0",
        "-show_entries", "stream=codec_name,width,height,avg_frame_rate,nb_frames:format=format_name,duration",
        "-of", "json", str(path),
    ], timeout=15)
    if result.returncode != 0:
        raise RequestError("INPUT_PROBE_FAILED", f"无法识别视频：{path}")
    try:
        data = json.loads(result.stdout)
        stream = data["streams"][0]
    except (ValueError, KeyError, IndexError, TypeError) as exc:
        raise RequestError("INPUT_PROBE_FAILED", f"视频没有可识别的视频流：{path}") from exc
    codec = str(stream.get("codec_name", "")).lower().replace("hevc", "h265")
    duration = data.get("format", {}).get("duration")
    return {
        "codec": codec,
        "width": int(stream.get("width") or 0),
        "height": int(stream.get("height") or 0),
        "format": str(data.get("format", {}).get("format_name", "")),
        "duration": float(duration) if duration not in {None, "N/A"} else None,
        "frame_rate": str(stream.get("avg_frame_rate") or ""),
        "frame_count": int(stream["nb_frames"]) if str(stream.get("nb_frames", "")).isdigit() else None,
    }


def probe_rtsp(url: str, transport: str) -> dict[str, Any]:
    ffprobe = require_program("ffprobe")
    result = run_capture([
        ffprobe, "-v", "error", "-rtsp_transport", transport,
        "-select_streams", "v:0",
        "-show_entries", "stream=codec_name,width,height,avg_frame_rate",
        "-of", "json", url,
    ], timeout=20)
    if result.returncode != 0:
        detail = result.stderr.strip().splitlines()
        suffix = f"：{detail[-1]}" if detail else ""
        raise RequestError("INPUT_PROBE_FAILED", f"无法读取 RTSP 视频流{suffix}")
    try:
        stream = json.loads(result.stdout)["streams"][0]
    except (ValueError, KeyError, IndexError, TypeError) as exc:
        raise RequestError("INPUT_PROBE_FAILED", "RTSP 地址没有可识别的视频流") from exc
    codec = str(stream.get("codec_name", "")).lower().replace("hevc", "h265")
    return {
        "codec": codec,
        "width": int(stream.get("width") or 0),
        "height": int(stream.get("height") or 0),
        "frame_rate": str(stream.get("avg_frame_rate") or ""),
    }


def resolution_matches(info: dict[str, Any], requested: str | None) -> bool:
    if not requested:
        return True
    width, height = info["width"], info["height"]
    requested_width, requested_height = RESOLUTIONS[requested]
    if requested == "4k":
        return width >= requested_width and height >= requested_height
    return width == requested_width and height == requested_height


def resolve_input(raw: str, codec: str | None, resolution: str | None) -> tuple[Path, dict[str, Any]]:
    path = Path(os.path.expandvars(os.path.expanduser(raw))).resolve()
    if path.is_file():
        info = probe_file(path)
        if codec and info["codec"] != codec:
            raise RequestError("INPUT_MISMATCH", f"输入实际为 {info['codec']}，不是请求的 {codec}")
        if not resolution_matches(info, resolution):
            raise RequestError(
                "INPUT_MISMATCH",
                f"输入分辨率为 {info['width']}x{info['height']}，不符合 {resolution}",
            )
        return path, info
    if not path.is_dir():
        raise RequestError("INPUT_NOT_FOUND", f"输入不存在：{path}")
    candidates = sorted(
        item for item in path.rglob("*")
        if item.is_file() and item.suffix.lower() in VIDEO_EXTENSIONS
    )
    for candidate in candidates:
        try:
            info = probe_file(candidate)
        except RequestError:
            continue
        if codec and info["codec"] != codec:
            continue
        if info["codec"] not in DECODERS or not resolution_matches(info, resolution):
            continue
        return candidate, info
    detail = "、".join(item for item in (codec, resolution) if item) or "H.264/H.265"
    raise RequestError("INPUT_NOT_FOUND", f"目录 {path} 中没有匹配 {detail} 的视频")


def resolve_raw_input(raw: str, resolution: str | None) -> Path:
    if not resolution:
        raise RequestError("INVALID_REQUEST", "encode-raw 必须指定 resolution")
    path = Path(os.path.expandvars(os.path.expanduser(raw))).resolve()
    if path.is_file():
        return path
    if not path.is_dir():
        raise RequestError("INPUT_NOT_FOUND", f"输入不存在：{path}")
    width, height = RESOLUTIONS[resolution]
    markers = (resolution, f"{width}x{height}", f"{width}_{height}")
    candidates = sorted(
        item for item in path.rglob("*")
        if item.is_file() and item.suffix.lower() in RAW_VIDEO_EXTENSIONS
    )
    matching = [item for item in candidates if any(marker in item.name.lower() for marker in markers)]
    if not matching:
        raise RequestError(
            "INPUT_NOT_FOUND",
            f"目录 {path} 中没有文件名包含 {resolution} 或 {width}x{height} 的 NV12/YUV 素材",
        )
    return matching[0]


def demux_for(info: dict[str, Any], path: Path) -> str | None:
    fmt = info["format"]
    suffix = path.suffix.lower()
    if suffix in {".264", ".h264", ".avc", ".265", ".h265", ".hevc"}:
        return None
    if "mov" in fmt or suffix in {".mp4", ".mov"}:
        return "qtdemux"
    if "matroska" in fmt or suffix in {".mkv", ".webm"}:
        return "matroskademux"
    if "mpegts" in fmt or suffix in {".ts", ".m2ts"}:
        return "tsdemux"
    if "avi" in fmt or suffix == ".avi":
        return "avidemux"
    raise RequestError("CONTAINER_UNSUPPORTED", f"GStreamer 播放暂不支持容器：{fmt or suffix}")


def default_output(codec: str, prefix: str, suffix: str = ".mp4") -> Path:
    stamp = dt.datetime.now().strftime("%Y%m%d-%H%M%S")
    return Path.home() / "Videos" / f"{prefix}-{stamp}-{codec}{suffix}"


def ensure_output(raw: Any, codec: str, prefix: str, suffix: str = ".mp4") -> Path:
    path = (
        Path(os.path.expandvars(os.path.expanduser(str(raw))))
        if raw else default_output(codec, prefix, suffix)
    )
    path = path.resolve()
    path.parent.mkdir(parents=True, exist_ok=True)
    if path.exists():
        raise RequestError("OUTPUT_EXISTS", f"输出已存在，不会覆盖：{path}")
    return path
