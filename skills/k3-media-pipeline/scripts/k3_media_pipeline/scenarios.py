"""Deterministic scenario-to-command planning."""

from __future__ import annotations

from pathlib import Path
from typing import Any

from .capabilities import ffmpeg_capability, gst_elements, require_program
from .errors import RequestError
from .inputs import demux_for, ensure_output, probe_rtsp, resolve_camera_device, resolve_input, resolve_raw_input
from .schema import DECODERS, ENCODERS, GST_ENCODERS, PARSERS, RESOLUTIONS


def gst_display_stage() -> tuple[list[str], list[str], str]:
    """Return the fixed GTK display stage used by all preview scenarios."""
    return (
        ["glsinkbin", "sink=gtkglsink"],
        ["glsinkbin", "gtkglsink"],
        "glsinkbin(gtkglsink)",
    )


def gst_play(path: Path, info: dict[str, Any]) -> tuple[list[str], str]:
    codec = info["codec"]
    if codec not in PARSERS:
        raise RequestError("CODEC_UNSUPPORTED", f"播放仅支持 H.264/H.265，输入为 {codec}")
    demux = demux_for(info, path)
    display_argv, display_elements, display_flow = gst_display_stage()
    required = [PARSERS[codec], "spacemitdec", *display_elements]
    if demux:
        required.append(demux)
    gst_elements(*required)
    argv = [require_program("gst-launch-1.0"), "-e", "-q", "filesrc", f"location={path}", "!"]
    flow = ["文件", demux or "裸码流", PARSERS[codec], "spacemitdec(硬件解码)", display_flow, "显示"]
    if demux:
        argv += [demux, "!", "queue", "!"]
    argv += [PARSERS[codec], "!", "spacemitdec", "!", "queue", "!", *display_argv]
    return argv, " → ".join(flow)


def _camera_plan(request: dict[str, Any]) -> dict[str, Any]:
    scenario = request["scenario"]
    device = Path(resolve_camera_device(request.get("input")))
    frame_rate = request["frame_rate"]
    frame_count = request["duration_seconds"] * frame_rate
    source = ["v4l2src", f"device={device}", f"num-buffers={frame_count}"]
    if request["resolution"]:
        width, height = RESOLUTIONS[request["resolution"]]
        capture_format = f"video/x-raw,width={width},height={height},framerate={frame_rate}/1"
    else:
        capture_format = f"video/x-raw,framerate={frame_rate}/1"
    capture_caps = ["!", capture_format]
    output: Path | None = None
    if scenario == "camera-snapshot":
        image_format = request["image_format"]
        encoder = "jpegenc" if image_format == "jpeg" else "pngenc"
        suffix = ".jpg" if image_format == "jpeg" else ".png"
        gst_elements("v4l2src", "videoconvert", encoder, "filesink")
        output = ensure_output(request.get("output"), image_format, "snapshot", suffix)
        argv = [
            require_program("gst-launch-1.0"), "-e", "-q", *source,
            *capture_caps, "!", "videoconvert", "!", encoder,
            "snapshot=true", "!", "filesink", f"location={output}",
        ]
        pipeline = f"摄像头 → v4l2src → videoconvert → {encoder} → 图片文件"
    elif scenario == "camera-preview":
        display_argv, display_elements, display_flow = gst_display_stage()
        gst_elements("v4l2src", *display_elements)
        argv = [
            require_program("gst-launch-1.0"), "-e", "-q", *source,
            *capture_caps, "!", "videoconvert", "!", *display_argv,
        ]
        pipeline = f"摄像头 → v4l2src → videoconvert → {display_flow} → 显示"
    elif scenario == "camera-encode-null":
        encoder = GST_ENCODERS[request["output_codec"]]
        gst_elements("v4l2src", "videoconvert", encoder, "fakesink")
        argv = [
            require_program("gst-launch-1.0"), "-e", "-q", *source,
            *capture_caps, "!", "videoconvert", "!", "video/x-raw,format=NV12",
            "!", encoder, "!", "fakesink",
        ]
        pipeline = f"摄像头 → v4l2src → videoconvert → {encoder}(硬件编码) → Null"
    else:
        codec = request["output_codec"]
        encoder = GST_ENCODERS[codec]
        parser = PARSERS[codec]
        elements = ["v4l2src", "videoconvert", encoder, parser, "mp4mux", "filesink"]
        if scenario == "camera-record-preview":
            display_argv, display_elements, display_flow = gst_display_stage()
            elements += ["tee", "queue", *display_elements]
        gst_elements(*elements)
        output = ensure_output(request.get("output"), codec, "capture")
        prefix = [
            require_program("gst-launch-1.0"), "-e", "-q", *source,
            *capture_caps,
        ]
        encode_branch = [
            "!", encoder, "!", parser, "!", "mp4mux", "!", "filesink", f"location={output}",
        ]
        if scenario == "camera-record-preview":
            argv = prefix + [
                "!", "tee", "name=t",
                "t.", "!", "queue", "!", "videoconvert", "!", *display_argv,
                "t.", "!", "queue", "!", "videoconvert", "!", "video/x-raw,format=NV12",
            ] + encode_branch
            pipeline = (
                f"摄像头 → v4l2src → tee → [{display_flow} → 显示] + "
                f"[videoconvert → {encoder}(硬件编码) → {parser} → MP4 → 文件]"
            )
        else:
            argv = prefix + ["!", "videoconvert", "!", "video/x-raw,format=NV12"] + encode_branch
            pipeline = f"摄像头 → v4l2src → videoconvert → {encoder}(硬件编码) → {parser} → MP4 → 文件"
    return {
        "backend": "gstreamer",
        "argvs": [argv],
        "pipeline": pipeline,
        "input": str(device),
        "output": str(output) if output else None,
        "bounded": True,
    }


def _stream_output_args(url: str, transport: str) -> list[str]:
    scheme = url.split(":", 1)[0].lower()
    if scheme in {"rtsp", "rtsps"}:
        return ["-f", "rtsp", "-rtsp_transport", transport, url]
    if scheme in {"rtmp", "rtmps"}:
        return ["-f", "flv", url]
    return ["-f", "mpegts", url]


def _file_stream_plan(request: dict[str, Any]) -> dict[str, Any]:
    path, info = resolve_input(request["input"], request["input_codec"], request["resolution"])
    codec = info["codec"]
    if codec not in DECODERS:
        raise RequestError("CODEC_UNSUPPORTED", f"仅支持 H.264/H.265，输入为 {codec}")
    decoder = DECODERS[codec]
    encoder = ENCODERS[request["output_codec"]]
    ffmpeg_capability("decoders", decoder)
    ffmpeg_capability("encoders", encoder)
    url = request["url"]
    argv = [
        require_program("ffmpeg"), "-hide_banner", "-nostdin", "-loglevel", "error",
        "-re", "-stream_loop", "-1", "-c:v", decoder, "-i", str(path),
        "-map", "0:v:0", "-an", "-t", str(request["duration_seconds"]),
        "-c:v", encoder, "-b:v", request["bitrate"],
        *_stream_output_args(url, request["transport"]),
    ]
    return {
        "backend": "ffmpeg", "argvs": [argv],
        "pipeline": f"文件 → {decoder}(硬件解码) → {encoder}(硬件编码) → {url.split(':', 1)[0].upper()} 推流",
        "input": str(path), "output": None, "target_url": url, "bounded": True,
    }


def _camera_stream_plan(request: dict[str, Any]) -> dict[str, Any]:
    device = Path(resolve_camera_device(request.get("input")))
    encoder = ENCODERS[request["output_codec"]]
    ffmpeg_capability("encoders", encoder)
    url = request["url"]
    input_format = request.get("input_format")
    argv = [
        require_program("ffmpeg"), "-hide_banner", "-nostdin", "-loglevel", "error",
        "-f", "v4l2", "-framerate", str(request["frame_rate"]),
    ]
    if input_format:
        argv += ["-input_format", str(input_format)]
    if request["resolution"]:
        width, height = RESOLUTIONS[request["resolution"]]
        argv += ["-video_size", f"{width}x{height}"]
    argv += [
        "-i", str(device), "-map", "0:v:0", "-an", "-t", str(request["duration_seconds"]),
        "-vf", "format=nv12", "-c:v", encoder, "-b:v", request["bitrate"],
        *_stream_output_args(url, request["transport"]),
    ]
    fmt_desc = f"/{input_format}" if input_format else ""
    return {
        "backend": "ffmpeg", "argvs": [argv],
        "pipeline": f"摄像头{fmt_desc} → V4L2 → {encoder}(硬件编码) → {url.split(':', 1)[0].upper()} 推流",
        "input": str(device), "output": None, "target_url": url, "bounded": True,
    }


def _rtsp_plan(request: dict[str, Any]) -> dict[str, Any]:
    url = request["url"]
    info = probe_rtsp(url, request["transport"])
    codec = info["codec"]
    if codec not in PARSERS:
        raise RequestError("CODEC_UNSUPPORTED", f"RTSP 播放仅支持 H.264/H.265，输入为 {codec}")
    if request["scenario"] == "rtsp-record":
        output = ensure_output(request.get("output"), codec, "rtsp-record")
        argv = [
            require_program("ffmpeg"), "-hide_banner", "-nostdin", "-loglevel", "error",
            "-rtsp_transport", request["transport"], "-i", url,
            "-map", "0:v:0", "-an", "-t", str(request["duration_seconds"]),
            "-c:v", "copy", "-movflags", "+faststart", str(output),
        ]
        return {
            "backend": "ffmpeg", "argvs": [argv],
            "pipeline": "RTSP → depay/demux → parser → MP4封装(不重新编码) → 文件",
            "input": url, "output": str(output), "bounded": True,
        }
    depay = "rtph264depay" if codec == "h264" else "rtph265depay"
    parser = PARSERS[codec]
    display_argv, display_elements, display_flow = gst_display_stage()
    gst_elements("rtspsrc", depay, parser, "spacemitdec", *display_elements)
    protocols = "tcp" if request["transport"] == "tcp" else "udp"
    argv = [
        require_program("gst-launch-1.0"), "-e", "-q", "rtspsrc", f"location={url}",
        f"protocols={protocols}", "latency=200", "!", depay, "!", parser, "!",
        "spacemitdec", "!", "queue", "!", *display_argv,
    ]
    return {
        "backend": "gstreamer", "argvs": [argv],
        "pipeline": f"RTSP → {depay} → {parser} → spacemitdec(硬件解码) → {display_flow} → 显示",
        "input": url, "output": None, "bounded": False,
    }


def _extract_frame_plan(request: dict[str, Any]) -> dict[str, Any]:
    path, info = resolve_input(request["input"], request["input_codec"], request["resolution"])
    codec = info["codec"]
    if codec not in DECODERS:
        raise RequestError("CODEC_UNSUPPORTED", f"仅支持 H.264/H.265，输入为 {codec}")
    decoder = DECODERS[codec]
    ffmpeg_capability("decoders", decoder)
    image_format = request["image_format"]
    suffix = ".jpg" if image_format == "jpeg" else ".png"
    output = ensure_output(request.get("output"), image_format, "frame", suffix)
    image_encoder = "mjpeg" if image_format == "jpeg" else "png"
    argv = [
        require_program("ffmpeg"), "-hide_banner", "-nostdin", "-loglevel", "error",
        "-c:v", decoder, "-i", str(path), "-ss", str(request["start_seconds"]),
        "-map", "0:v:0", "-frames:v", "1", "-c:v", image_encoder, str(output),
    ]
    return {
        "backend": "ffmpeg", "argvs": [argv],
        "pipeline": f"文件 → {decoder}(硬件解码) → 定位 {request['start_seconds']} 秒 → {image_format.upper()} → 图片文件",
        "input": str(path), "output": str(output), "bounded": True,
    }


def _raw_encode_plan(request: dict[str, Any]) -> dict[str, Any]:
    path = resolve_raw_input(request["input"], request["resolution"])
    width, height = RESOLUTIONS[request["resolution"]]
    encoder = ENCODERS[request["output_codec"]]
    ffmpeg_capability("encoders", encoder)
    output = ensure_output(request.get("output"), request["output_codec"], "encoded")
    argv = [
        require_program("ffmpeg"), "-hide_banner", "-nostdin", "-loglevel", "error",
        "-f", "rawvideo", "-pixel_format", "nv12", "-video_size", f"{width}x{height}",
        "-framerate", str(request["frame_rate"]), "-i", str(path), "-an", "-t",
        str(request["duration_seconds"]), "-c:v", encoder, "-b:v", request["bitrate"], str(output),
    ]
    return {
        "backend": "ffmpeg",
        "argvs": [argv],
        "pipeline": f"NV12 → FFmpeg → {encoder}(硬件编码) → MP4 → 文件",
        "input": str(path),
        "output": str(output),
        "bounded": True,
    }


def plan(request: dict[str, Any]) -> dict[str, Any]:
    scenario = request["scenario"]
    duration = request["duration_seconds"]
    if scenario in {"camera-preview", "record-camera", "camera-record-preview", "camera-encode-null", "camera-snapshot"}:
        return _camera_plan(request)
    if scenario == "camera-stream":
        return _camera_stream_plan(request)
    if scenario == "file-stream":
        return _file_stream_plan(request)
    if scenario in {"rtsp-play", "rtsp-record"}:
        return _rtsp_plan(request)
    if scenario == "extract-frame":
        return _extract_frame_plan(request)
    if scenario == "encode-raw":
        return _raw_encode_plan(request)

    path, info = resolve_input(request["input"], request["input_codec"], request["resolution"])
    if scenario == "media-info":
        return {
            "backend": "ffprobe", "argvs": [], "pipeline": "文件 → ffprobe → 媒体信息",
            "input": str(path), "output": None, "bounded": True, "media_info": info,
        }
    codec = info["codec"]
    if codec not in DECODERS:
        raise RequestError("CODEC_UNSUPPORTED", f"仅支持 H.264/H.265，输入为 {codec}")
    if scenario == "play-file":
        argv, pipeline = gst_play(path, info)
        return {
            "backend": "gstreamer", "argvs": [argv], "pipeline": pipeline,
            "input": str(path), "output": None, "bounded": False,
        }

    decoder = DECODERS[codec]
    ffmpeg_capability("decoders", decoder)
    common = [
        require_program("ffmpeg"), "-hide_banner", "-nostdin", "-loglevel", "error",
        "-c:v", decoder, "-i", str(path), "-map", "0:v:0", "-an", "-t", str(duration),
    ]
    if scenario in {"decode-null", "multi-decode"}:
        argv = common + ["-f", "null", "-"]
        count = request["streams"] if scenario == "multi-decode" else 1
        return {
            "backend": "ffmpeg", "argvs": [argv[:] for _ in range(count)],
            "pipeline": f"文件 → FFmpeg → {decoder}(硬件解码) → Null",
            "input": str(path), "output": None, "bounded": True,
        }
    if scenario == "decode-raw":
        output = ensure_output(request.get("output"), "nv12", "decoded", ".nv12")
        argv = common + ["-pix_fmt", "nv12", "-f", "rawvideo", str(output)]
        return {
            "backend": "ffmpeg", "argvs": [argv],
            "pipeline": f"文件 → FFmpeg → {decoder}(硬件解码) → NV12 → 文件",
            "input": str(path), "output": str(output), "bounded": True,
        }

    out_codec = request["output_codec"]
    encoder = ENCODERS[out_codec]
    ffmpeg_capability("encoders", encoder)
    output = ensure_output(request.get("output"), out_codec, "transcoded")
    encode_options = ["-c:v", encoder, "-b:v", request["bitrate"]]
    if scenario == "transcode-scale":
        target = request["output_resolution"] or "1080p"
        width, height = RESOLUTIONS[target]
        encode_options = ["-vf", f"scale={width}:{height}", *encode_options]
        pipeline = (
            f"文件 → FFmpeg → {decoder}(硬件解码) → scale({width}x{height}) → "
            f"{encoder}(硬件编码) → MP4 → 文件"
        )
    else:
        pipeline = f"文件 → FFmpeg → {decoder}(硬件解码) → {encoder}(硬件编码) → MP4 → 文件"
    return {
        "backend": "ffmpeg", "argvs": [common + encode_options + [str(output)]],
        "pipeline": pipeline, "input": str(path), "output": str(output), "bounded": True,
    }
