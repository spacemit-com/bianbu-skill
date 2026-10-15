"""Runtime dependency and hardware capability checks."""

from __future__ import annotations

import shutil
import subprocess
from typing import Any

from .errors import RequestError
from .schema import DECODERS, ENCODERS


def run_capture(argv: list[str], timeout: float = 10) -> subprocess.CompletedProcess[str]:
    return subprocess.run(
        argv,
        stdin=subprocess.DEVNULL,
        stdout=subprocess.PIPE,
        stderr=subprocess.PIPE,
        text=True,
        timeout=timeout,
        check=False,
    )


def require_program(name: str) -> str:
    path = shutil.which(name)
    if not path:
        raise RequestError("PROGRAM_UNAVAILABLE", f"未找到 {name}")
    return path


def ffmpeg_capability(kind: str, name: str) -> None:
    ffmpeg = require_program("ffmpeg")
    result = run_capture([ffmpeg, "-hide_banner", f"-{kind}"], timeout=15)
    if result.returncode != 0 or name not in result.stdout:
        raise RequestError("HARDWARE_CODEC_UNAVAILABLE", f"FFmpeg 未提供硬件编解码器 {name}")


def gst_elements(*names: str) -> None:
    inspect = require_program("gst-inspect-1.0")
    for name in names:
        result = run_capture([inspect, name], timeout=10)
        if result.returncode != 0:
            raise RequestError("GSTREAMER_ELEMENT_UNAVAILABLE", f"GStreamer 元件不可用：{name}")


def probe_capabilities() -> dict[str, Any]:
    values: dict[str, Any] = {
        "ffmpeg": shutil.which("ffmpeg"),
        "ffprobe": shutil.which("ffprobe"),
        "gstreamer": shutil.which("gst-launch-1.0"),
        "ffmpeg_hardware": {},
        "gstreamer_elements": {},
    }
    for name in sorted(set(DECODERS.values()) | set(ENCODERS.values())):
        values["ffmpeg_hardware"][name] = {}
        for kind in ("decoders", "encoders"):
            try:
                ffmpeg_capability(kind, name)
                values["ffmpeg_hardware"][name][kind] = True
            except RequestError:
                values["ffmpeg_hardware"][name][kind] = False
    for name in (
        "spacemitdec", "spacemith264enc", "spacemith265enc",
        "autovideosink", "glsinkbin", "gtkglsink", "v4l2src", "rtspsrc", "rtph264depay",
        "rtph265depay", "jpegenc", "pngenc",
    ):
        try:
            gst_elements(name)
            values["gstreamer_elements"][name] = True
        except RequestError:
            values["gstreamer_elements"][name] = False
    return values
