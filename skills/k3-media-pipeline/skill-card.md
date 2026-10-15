---
schema_version: 2
---
# Skill Card: K3 Media Pipeline

## Capability

在 SpacemiT K3 板卡上以固定场景驱动 GStreamer 或 FFmpeg 完成媒体处理：查看媒体信息、视频播放、硬件编解码、多路硬件解码、摄像头预览/录制/拍照、抽帧、RTSP 播放/录制，以及文件或摄像头推流。唯一入口是 `scripts/run.py`，由后端按场景确定性组装命令，模型只负责选择场景与复制用户给出的参数。

## Use Cases

- 处理用户指定的视频文件、原始 NV12 数据、目录、摄像头设备或流地址。
- 在 K3 上做多路硬件解码、硬件编解码验证、抽帧与 RTSP 拉流/推流。
- 需要统一 JSON 结果与可追溯元件链语义段的自动化调用。

## Inputs and Outputs

- Input: `--scenario` 加参数（推荐）；程序化集成用 `--request-json '<json>'` 或 stdin 单个 JSON，先用 `--describe` 获取 Schema；`--dry-run` 只输出计划，`--probe` 输出硬件能力探测。
- Output: 所有场景统一结构的 JSON，成功时展示 `summary`，需要说明数据流时引用 `pipeline_stages`；结构、错误码与退出码见 `references/output.md`。

## Dependencies

- Python 3 运行 `scripts/run.py`。
- SpacemiT K3 的硬件编解码能力，以及可用的 GStreamer / FFmpeg。
- 摄像头场景需要 `/dev/video*`；显示场景需要有 Wayland 或 X11 会话。
- 不依赖 MCP、插件或任何特定 Agent 适配器，具备终端执行能力的 Agent 即可使用。

## Limitations

- 不用于性能、FPS、吞吐或 Benchmark 请求，这些应改用 VPU Benchmark。
- 不用于测试或诊断 mpv、VLC、ffplay 等独立播放器应用或命令；用户明确点名应用时应直接测试该应用。
- 不安装依赖、不提权、不回退软件编解码；硬件或素材不可用时原样返回错误。
- 推流不代为搭建 RTSP 等接收端，目标不可达时把连接错误原样反馈给用户。
- 时长合法范围 1–3600 秒；RTMP 推流仅支持 H.264；RTSP 拉流默认 TCP。
- 不添加用户未要求的处理步骤，也不让模型自行生成 GStreamer Pipeline 或 FFmpeg 命令。

## Maintainer

Owner: wumingjie
Contact: mingjie.wu@spacemit.com
