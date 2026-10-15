"""Stable request schema and backend component mappings."""

from __future__ import annotations

from typing import Any


SCENARIOS = (
    "media-info",
    "play-file",
    "decode-null",
    "multi-decode",
    "decode-raw",
    "encode-raw",
    "camera-preview",
    "record-camera",
    "camera-record-preview",
    "camera-encode-null",
    "transcode-file",
    "transcode-scale",
    "camera-snapshot",
    "extract-frame",
    "file-stream",
    "camera-stream",
    "rtsp-play",
    "rtsp-record",
)
VIDEO_EXTENSIONS = {
    ".264", ".h264", ".avc", ".265", ".h265", ".hevc",
    ".mp4", ".mkv", ".mov", ".avi", ".ts", ".m2ts", ".webm",
}
RAW_VIDEO_EXTENSIONS = {".nv12", ".yuv", ".raw"}
DECODERS = {"h264": "h264_stcodec", "h265": "hevc_stcodec"}
ENCODERS = {"h264": "h264_stcodec", "h265": "hevc_stcodec"}
GST_ENCODERS = {"h264": "spacemith264enc", "h265": "spacemith265enc"}
PARSERS = {"h264": "h264parse", "h265": "h265parse"}
RESOLUTIONS = {
    "720p": (1280, 720),
    "1080p": (1920, 1080),
    "4k": (3840, 2160),
}


def schema() -> dict[str, Any]:
    return {
        "type": "object",
        "additionalProperties": False,
        "description": (
            "K3常用媒体任务。选择一个固定scenario并复制用户参数；"
            "不要生成Pipeline、步骤或命令。处理媒体使用本Skill，性能测试使用benchmark。"
        ),
        "properties": {
            "scenario": {
                "type": "string",
                "enum": list(SCENARIOS),
                "description": (
                    "media-info查看媒体信息；play-file播放；decode-null单路纯解码；"
                    "multi-decode多路纯解码；decode-raw解码为NV12；encode-raw编码NV12；"
                    "camera-preview摄像头预览；record-camera摄像头录制；"
                    "camera-record-preview预览并录制；camera-encode-null只编码不保存；"
                    "transcode-file硬件转码；transcode-scale缩放转码；"
                    "camera-snapshot摄像头拍照；extract-frame从文件提取一帧；"
                    "file-stream文件循环推流；camera-stream摄像头推流；"
                    "rtsp-play拉取RTSP并硬解码显示；rtsp-record录制RTSP且不重新编码。"
                ),
            },
            "input": {
                "type": "string",
                "default": "~/Videos",
                "description": "视频文件、素材目录或摄像头设备；摄像头场景不填时自动探测/dev/video*采集设备。Videos下填写~/Videos。",
            },
            "input_codec": {
                "type": "string",
                "enum": ["h264", "h265"],
                "description": "用户指定了输入编码或input是目录时填写。",
            },
            "resolution": {
                "type": "string",
                "enum": list(RESOLUTIONS),
                "description": "目录素材筛选、原始NV12输入尺寸或摄像头采集分辨率。",
            },
            "output_resolution": {
                "type": "string",
                "enum": list(RESOLUTIONS),
                "description": "transcode-scale的目标分辨率，默认1080p。",
            },
            "output": {
                "type": "string",
                "description": "解码原始帧、编码、录制或转码的输出文件；省略时自动命名。",
            },
            "url": {
                "type": "string",
                "description": "RTSP输入地址，或RTSP/RTMP/UDP推流目标地址；推流省略时默认UDP组播udp://239.1.1.1:5004，无需任何流媒体服务器。",
            },
            "transport": {
                "type": "string",
                "enum": ["tcp", "udp"],
                "default": "tcp",
                "description": "RTSP传输方式，默认tcp。",
            },
            "start_seconds": {
                "type": "integer",
                "minimum": 0,
                "maximum": 86400,
                "default": 0,
                "description": "extract-frame提取帧的起始秒数。",
            },
            "image_format": {
                "type": "string",
                "enum": ["jpeg", "png"],
                "default": "jpeg",
                "description": "camera-snapshot或extract-frame的图片格式。",
            },
            "output_codec": {
                "type": "string",
                "enum": ["h264", "h265"],
                "default": "h264",
                "description": "录制、原始帧编码或转码场景的硬件编码格式。",
            },
            "streams": {
                "type": "integer",
                "minimum": 1,
                "maximum": 8,
                "default": 1,
                "description": "multi-decode并发路数；其余场景必须为1。",
            },
            "duration_seconds": {
                "type": "integer",
                "minimum": 1,
                "maximum": 3600,
                "default": 10,
                "description": "运行时间，默认10秒（推流场景默认300秒），防止Agent任务无限阻塞。",
            },
            "frame_rate": {
                "type": "integer",
                "minimum": 1,
                "maximum": 120,
                "default": 30,
                "description": "原始NV12输入或摄像头的帧率，默认30。",
            },
            "input_format": {
                "type": "string",
                "enum": ["mjpeg", "yuyv422"],
                "description": "camera-stream场景的摄像头采集格式；高分辨率(720p/1080p)高帧率需mjpeg。",
            },
            "bitrate": {
                "type": "string",
                "pattern": "^[1-9][0-9]*[kKmM]$",
                "default": "8M",
                "description": "FFmpeg硬件编码目标码率，例如4M、8000k。",
            },
        },
        "required": ["scenario"],
    }
