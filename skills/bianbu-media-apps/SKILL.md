---
schema_version: 2
name_zh: 多媒体应用使用与测试
name_en: Bianbu Media Apps
name: bianbu-media-apps
version: v0.0.3
description: "Use or test the MPV, VLC, Totem and Snapshot (camera) applications on the Bianbu desktop. Covers opening and playback, application control, player feature testing and reporting; Snapshot testing only documents the current automation interface limits. Not for VPU/V2D performance benchmarking or custom media pipelines."
description_zh: 使用或测试 Bianbu 桌面的 MPV、VLC、Totem 和 Snapshot（相机）应用。用于打开播放、应用控制、播放器功能测试及报告；Snapshot 测试仅说明当前自动化接口限制。不用于 VPU/V2D 性能基准或自定义媒体流水线。
metadata:
  version: "0.0.3"
---

# 多媒体应用使用与测试

保持用户指定的应用及平台默认配置。按当前请求区分日常使用与测试，不因历史对话做过测试就自动启动验收。

## 选择流程

| 请求 | 处理 |
|---|---|
| 打开应用、播放文件、暂停/继续、音量、跳转、全屏、关闭 | 日常使用，按 [应用入口](references/applications.md) 和 [播放操作](references/playback.md) 执行；不建测试报告 |
| 打开相机、拍照、录制 | 读 [Snapshot](references/snapshot.md)，按实际可用能力处理；不当作测试 |
| 测试 Snapshot／相机应用，或要求其测试报告 | 直接说明下面的接口限制，不运行测试 |
| 简测、测试、验收 MPV/VLC/Totem | 按下列测试流程执行 |
| 明确要求真实 GUI 点击/拖拽验收 | 读 [验收流程](references/acceptance.md) 和 [GUI 证据](references/execution.md)；缺少能力则 BLOCKED，不用 CLI 冒充 |

**Snapshot 限制**：当前未提供拍照、开始录像、停止录像的原生 CLI／已导出 D-Bus 控制接口，因此本次未执行自动化测试（BLOCKED：控制接口不足），不代表相机功能故障。普通测试请求不打开相机、不拍摄，不运行 `run.py --app snapshot`，不尝试模拟按键、无障碍接口或 FFmpeg/GStreamer 代测，不引用旧作品或虚构报告。原用例和探测脚本保留；只有用户明确要求重新探测、启动诊断或人工/GUI验收时再按该范围处理。

## 播放器测试

1. 确定应用和测试范围。默认当前全部12项；用户指定子集则只测子集。先读 [CLI 流程与判据](references/cli.md)，不预加载所有用例表、GUI指南或脚本源码。
2. 获取实际媒体路径；未指定时在已知媒体目录有限查找合适素材。一次调用只接收一个文件；不同容器分别执行，缺素材如实 BLOCKED。
3. 用当前 Agent 的命令执行能力运行固定入口。将 `SKILL_DIR` 设为本次加载的 Skill 实际根目录，不能假定工具工作目录或写死安装位置；它是示例变量，不要求宿主提供特定环境变量。

```bash
python3 "$SKILL_DIR/scripts/run.py" --app vlc --mode acceptance --cases all --input "/实际视频路径.mp4"
# 简测播放、暂停、双向跳转
python3 "$SKILL_DIR/scripts/run.py" --app mpv --mode quick --cases 3,4,5 --input "/实际视频路径.mp4"
```

4. 以本轮脚本返回的 cases、summary_text 和报告路径回复。完成所选素材/项目后结束，不为凑 PASS 反复运行或临时编写测试程序。多次运行汇总须引用各自证据，不修改原始结果。

`quick` 与 `acceptance` 共用判据，只切换报告详细程度。12项保留编号1、3—13：打开关闭、本地播放、暂停继续、双向跳转、音量、全屏，以及MP4/MKV/AVI/MOV/WebM/FLV；第2项窗口大小已移除。明确编号时直接执行，只有编号不清楚才用 `--list`。原表由脚本读取：[MPV](references/cases.json)、[VLC](references/cases-vlc.json)、[Totem](references/cases-totem.json)；[相机8项](references/cases-snapshot.json)仅保留，不自动执行。

## 结果与操作边界

- 保留平台默认解码器和输出，不追加或修改 hwdec/vo/ao、系统配置、插件开关。日常播放使用应用名加媒体路径；测试所需 IPC 和日志参数由脚本处理。
- 只操作本次实例；不全局杀进程，不终止用户正在播放或录像的会话。日常播放结束本轮操作时保留窗口；测试脚本负责结束本次进程。
- 依赖缺失或桌面不可用时说明原因，不自动安装组件，也不以无界面解码冒充可见播放。
- PASS/FAIL 依据脚本判据；BLOCKED 是条件/接口/素材不足；NOT_RUN 是未执行。REPORTED 或退出码0仅代表报告生成。
- CLI PASS 不证明真实 GUI 手势、画质、听感或物理音画同步。保留无音轨、未验证同步及日志告警说明，不把告警自行解释为无害。
- 输出简明结果表和真实报告路径；完整报告保留原表字段及证据。不增加测试项，不把硬解日志等辅助证据计入用例通过率。
