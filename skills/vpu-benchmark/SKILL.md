---
schema_version: 2
name_zh: VPU 硬件编解码基准
name_en: VPU Benchmark
name: vpu-benchmark
version: v0.13.14
description: "Benchmark the FPS, throughput and MVX bandwidth of the SpacemiT K3 VPU hardware video codec, covering the registered single- and multi-session H.264/H.265/VP8/VP9/MJPEG cases. Use it when the user asks about VPU or hardware codec performance or compares benchmarks; do not use it to process a user-specified video, directory or camera, and do not use it for scaling, inference or transcoding, since those requests belong to the media Pipeline skill."
description_zh: 测试 SpacemiT K3 VPU 硬件视频编解码器的基准性能、FPS、吞吐和 MVX 带宽， 支持已注册的 H.264/H.265/VP8/VP9/MJPEG 单路与多路用例。 用户询问 VPU、硬件编解码性能或基准比较时使用；不要用于处理用户指定的视频、 目录或摄像头，也不要用于缩放、推理或转码，这类请求应选择媒体 Pipeline Skill。
compatibility: >-
  Requires Linux on SpacemiT K3, Python 3.11+, the k3x-vpu-test Debian package, K3 MVX driver/devices, FFmpeg with SpacemiT hardware codecs, and network access when cached test assets are absent. This Skill contains no MVX binaries.
metadata:
  version: "0.13.14"
  entrypoint: "scripts/run.py"
  request_argument: "--request-json"
  timeout_seconds: "1500"
  output_protocol: "stdout-markdown-v1"
  target: "spacemit-k3"
---

# VPU Benchmark

## 执行

从当前 Skill 根目录调用 `metadata.entrypoint` 一次。入口路径相对于 Skill 根目录解析，
不依赖终端当前目录，也不要写死任何用户目录。

用户没有指定格式、操作、路数或分辨率时，直接运行默认 13 项：

```bash
python3 scripts/run.py --request-json '{}'
```

用户明确指定条件时，只传入其明确给出的字段，不补猜其他条件：

- `codec`: `h264`、`h265`、`vp8`、`vp9`、`mjpeg`
- `operation`: `encode`、`decode`
- `sessions`: 1～32 的整数
- `resolution`: `4k`、`1080p`

例如，用户要求测试 H.264 单路解码性能：

```bash
python3 scripts/run.py --request-json '{"codec":"h264","operation":"decode","sessions":1}'
```

无匹配时原样返回错误，不回退全量测试。入口负责素材准备、预热、性能测试、
带宽测试、基准比较和报告生成；不要读取脚本源码、搜索替代工具、手工下载素材，
也不要自行拼装 FFmpeg 或 MVX 命令。

入口依赖 Debian 包 `k3x-vpu-test` 提供 `mvx_encoder`、`mvx_decoder`、
`mvx_encoder_multi` 和 `mvx_decoder_multi`。缺少命令时，入口只尝试一次无交互安装；
若 Agent 没有免密 sudo 或安装失败，向用户原样展示手动安装提示并停止测试。不要反复尝试、
不要请求 sudo 密码，也不要从未知地址下载 DEB。

等待该次调用完成，最长 1500 秒。运行中继续等待同一进程；失败、超时或输出不完整时
不自动重跑，也不启动第二个测试进程。

## 输出

将 stdout 的完整 UTF-8 Markdown 原样作为最终回复，保留全部表格行、结论、版本信息、
指标说明和报告路径。不要改写为列表或摘要，不增加、删除或重新计算字段。

stderr 仅包含进度和诊断信息，不作为测试结果。即使退出码非零，也优先展示已有 stdout；
不得据此编造性能数据或成功结论。

MVX 带宽和不限速 FPS 是两个独立指标。最终回复必须保留脚本输出的带宽测试情景，
不得把 MVX 带宽称为系统 DDR 增量。

普通性能测试只执行入口，不需要读取其他文件。仅在开发高级用例、维护指标或接入宿主时，
读取 [完整规范](references/specification.md)。
