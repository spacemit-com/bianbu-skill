# 场景参考

18 个固定场景。Agent 根据用户意图选择场景，未提及的参数由 Skill 自动补齐
（见 SKILL.md 关键默认值）。

## 媒体信息与播放

| 场景 | 行为 | 典型输入 |
|---|---|---|
| `media-info` | 读取编码、分辨率、时长、帧率、容器信息 | "看一下这个视频的编码和分辨率" |
| `play-file` | 硬件解码并显示 | "播放 xxx.mp4" |
| `decode-null` | 单路硬件解码，不显示、不保存 | "纯解码跑一下" |
| `multi-decode` | 多路并发硬件解码（唯一支持 `streams` 1–8） | "4 路硬解压测，不显示不保存" |
| `decode-raw` | 硬解并保存 NV12 原始帧 | "解码存成 NV12" |
| `extract-frame` | 文件硬解，`start_seconds` 处抽一帧存图片 | "抽第 3 秒的一帧存 PNG" |

## 编码与转码

| 场景 | 行为 | 典型输入 |
|---|---|---|
| `encode-raw` | NV12 原始帧硬件编码（必须给 `resolution`） | "把这段 NV12 编码成 H.264" |
| `transcode-file` | 文件硬解后硬件编码 | "转码成 H.265" |
| `transcode-scale` | 硬解、缩放、硬件编码（默认 1080p） | "转码并缩放到 720p" |

## 摄像头（设备自动探测，无需指定设备号）

| 场景 | 行为 | 典型输入 |
|---|---|---|
| `camera-preview` | 摄像头预览 | "打开摄像头预览" |
| `record-camera` | 摄像头硬件编码并保存 MP4（时长精确校验） | "录 5 秒视频" |
| `camera-record-preview` | 预览与录制同时进行（tee 双路） | "边预览边录" |
| `camera-encode-null` | 硬件编码后丢弃（fakesink） | "纯编码测试，不显示不保存" |
| `camera-snapshot` | 采集一帧存 JPEG/PNG | "拍一张照片" |

## 推流（时长默认 300 秒，地址缺省 rtsp://127.0.0.1:8554/live）

| 场景 | 行为 | 典型输入 |
|---|---|---|
| `camera-stream` | 摄像头采集、硬件编码、推流 | "摄像头编码后推流出去" |
| `file-stream` | 文件循环读取、硬解、硬编、推流 | "把这个视频循环推流到 xxx" |

## RTSP 拉流（必须指定 `url`）

| 场景 | 行为 | 典型输入 |
|---|---|---|
| `rtsp-play` | 拉流、H.264/H.265 自动识别、硬解、显示 | "拉这个地址播放" |
| `rtsp-record` | 拉流纯重封装存 MP4（`-c copy`，不重编码） | "把这个流录下来" |

## 参数约束

- `streams`：仅 `multi-decode` 允许 >1（范围 1–8），其余场景必须为 1
- `encode-raw`：必须指定 `resolution`（720p/1080p/4k）
- `duration_seconds`：1–3600 秒；摄像头采集帧数 = 时长 × `frame_rate`，
  等待自然 EOS
- `bitrate`：格式如 `4M`、`8000k`；默认 `8M`
- 网络场景协议限制：`rtsp-play`/`rtsp-record` 仅接受 rtsp(s)；
  推流另接受 rtmp(s)/udp；RTMP 仅 H.264
- `image_format`：jpeg（默认）/png；`extract-frame` 默认第 0 秒
- 输入可以是文件或目录：目录时按 `input_codec` + `resolution` 自动挑选素材

## 后端映射

- GStreamer 路径：播放、摄像头（除推流）、rtsp-play；硬解 `spacemitdec`，
  硬编 `spacemith264enc`/`spacemith265enc`，显示 `glsinkbin`/`autovideosink`
- FFmpeg 路径：解码/编码/转码/推流/rtsp-record；`h264_stcodec`/`hevc_stcodec`
- ffprobe 路径：`media-info` 与全部输入/产物探测
