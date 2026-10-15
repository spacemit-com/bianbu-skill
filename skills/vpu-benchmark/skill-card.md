---
schema_version: 2
---
# Skill Card: VPU Benchmark

## Capability

测试 SpacemiT K3 VPU 硬件视频编解码器的基准性能、FPS、吞吐和 MVX 带宽，覆盖已注册的 H.264 / H.265 / VP8 / VP9 / MJPEG 单路与多路用例，产出可直接阅读的性能报告。

## Use Cases

- 用户询问 VPU 性能、硬件编解码基准或做基准比较时执行默认 13 项测试。
- 用户明确指定条件时按指定 `codec`、`operation`、`sessions`、`resolution` 运行单项用例。
- 需要长期跟踪同一设备性能回归并与内置基线比较的场景。

## Inputs and Outputs

- Input: 从 Skill 根目录调用 `scripts/run.py --request-json '{}'`；可选字段 `codec`（h264/h265/vp8/vp9/mjpeg）、`operation`（encode/decode）、`sessions`（1–32）、`resolution`（4k/1080p）。只传入用户明确给出的字段。
- Output: stdout 的完整 UTF-8 Markdown 报告，含表格行、结论、版本信息、指标说明与报告路径；单次调用最长等待 1500 秒。

## Dependencies

- SpacemiT K3 上的 Linux，Python 3.11+。
- Debian 包 `k3x-vpu-test`，提供四个 MVX 编解码测试命令；Skill 不包含二进制文件。
- 缺包时入口尝试一次无交互安装；没有免密 sudo 时提示用户手动执行 `sudo apt install k3x-vpu-test` 或安装本地 DEB。
- 板端需要 K3 MVX 驱动和设备节点。
- 带 SpacemiT 硬件编解码的 FFmpeg。
- 缓存测试素材缺失时需要网络访问。

## Limitations

- 不处理用户指定的视频、目录或摄像头，也不做缩放、推理或转码，这类请求应改用 K3 Media Pipeline。
- 无匹配用例时原样返回错误，不回退为全量测试。
- 失败、超时或输出不完整时不自动重跑，也不启动第二个测试进程。
- MVX 带宽与不限速 FPS 是两个独立指标，不得把 MVX 带宽称为系统 DDR 增量。
- 退出码非零时优先展示已有 stdout，但不得据此编造性能数据或成功结论。

## Maintainer

Owner: wumingjie
Contact: mingjie.wu@spacemit.com
