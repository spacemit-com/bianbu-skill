---
schema_version: 2
name_zh: K3 媒体处理流水线
name_en: K3 Media Pipeline
name: k3-media-pipeline
version: v1.0.2
description: "Use GStreamer or FFmpeg on a K3 board to inspect media information and perform video playback, hardware encode and decode, multi-session hardware decoding, camera preview/recording/photo capture, frame extraction, RTSP playback/recording, and file or camera streaming. Use it only for a specified video, raw NV12, directory, camera or stream URL; not for performance, FPS, throughput or benchmarking, and not to test, diagnose or drive standalone players such as mpv, VLC or ffplay."
description_zh: 在 K3 板卡上使用 GStreamer 或 FFmpeg 查看媒体信息，执行视频播放、硬件编解码、 多路硬件解码、摄像头预览/录制/拍照、抽帧、RTSP播放/录制以及文件或摄像头推流。 仅用于处理指定视频、原始 NV12、目录、摄像头或流地址；不要用于性能、FPS、吞吐或 Benchmark， 也不要用于测试、诊断或操作 mpv、VLC、ffplay 等独立播放器应用或命令。
metadata:
  version: "1.0.2"
  target: "spacemit-k3"
  input_protocol: "cli-v1, stdin-json-v1"
---

# K3 Media Pipeline

这是自包含的固定场景执行 Skill，唯一入口是本目录下的 `scripts/run.py`，
不依赖 MCP、插件或任何特定 Agent 的适配器，任何具备终端执行能力的 Agent
均可直接使用。Agent 只需选择 `scenario` 并复制用户给出的少量参数；后端按
场景确定性组装命令。不要让模型生成 GStreamer Pipeline、FFmpeg 命令或内部步骤。

## 选择边界

只有用户要求使用本 Skill 的固定场景处理媒体数据或验证 K3 硬件媒体链路时，才选择本 Skill。
用户明确点名 `mpv`、VLC、ffplay 或其他现成应用/命令并要求测试、诊断、查看版本、配置或功能时，
不要查看或调用本 Skill；应直接通过终端或对应应用能力测试该目标。明确点名的应用优先于泛化的
“视频播放”意图。例如“测试 MPV 这个应用，并输出测试报告”不属于本 Skill。

## 快速开始

用户要求"用 Videos 下的 H.265 1080P 视频跑 4 路硬解，不显示不保存"：

```bash
python3 scripts/run.py \
  --scenario multi-decode \
  --input ~/Videos \
  --input-codec h265 \
  --resolution 1080p \
  --streams 4 \
  --duration-seconds 10
```

成功后向用户展示返回 JSON 的 `summary`；需要说明实际数据流时引用
`pipeline_stages`（实际使用的元件链/语义段）。所有场景返回统一结构的
JSON，详见 `references/output.md`。

## 调用协议

- CLI 参数（推荐）：`--scenario` + 参数
- `--request-json '<json>'`，或将单个 JSON 写入 stdin（需要程序化集成时
  先用 `--describe` 获取 Schema）；stdin 为终端且无参数时立即报错，不会挂起
- `--dry-run` 只输出计划不执行；`--probe` 输出硬件能力探测结果
- 所有路径相对本 Skill 目录解析，不假定宿主安装位置

## 关键默认值（用户未提及时代为补齐，不要追问）

- 摄像头：自动探测 `/dev/video*` 采集设备并选择；无需用户指定设备号
- 输出文件：省略 `output` 时写到 `~/Videos` 自动命名，不覆盖已有文件
- 时长：默认 10 秒，推流场景默认 300 秒；合法范围 1–3600 秒
- 推流地址：`file-stream`/`camera-stream` 不指定 `url` 时默认
  `rtsp://127.0.0.1:8554/live`，并在结果 `summary` 中标注"（默认地址）"
- 编码：默认 H.264 硬编；RTMP 推流仅支持 H.264；RTSP 拉流默认 TCP
- 显示：所有播放和预览场景固定使用 `glsinkbin sink=gtkglsink`，不再根据
  `WAYLAND_DISPLAY` 回退 `autovideosink`

## 执行纪律

- 不要添加用户未要求的处理步骤
- 推流前不要自行安装或搭建 RTSP 服务器等接收环境：直接执行，目标不可达时
  将返回的连接错误原样反馈给用户，由用户决定接收端的部署方式
- 本 Skill 不安装依赖、不提权、不回退软件编解码；硬件或素材不可用时，
  将错误原样告知用户

## 详细参考（按需加载，不要一次性全读）

- `references/scenarios.md`：18 个场景完整说明、自然语言示例与参数约束
- `references/output.md`：标准输出结构、pipeline_stages 语义、错误码与退出码
