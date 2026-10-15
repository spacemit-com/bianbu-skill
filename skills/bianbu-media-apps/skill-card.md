---
schema_version: 2
---
# Skill Card: Bianbu Media Apps

## Capability

在 Bianbu 桌面按平台默认方式使用 MPV、VLC、Totem（视频播放器）与 Snapshot（相机）应用，并在用户明确要求时对其做分应用功能验收。唯一入口是本 Skill 根目录下的 `scripts/run.py`：脚本按固定用例表组装启动命令、控制接口与判据，模型只负责选择应用、测试范围与媒体路径，不生成播放器命令、不改系统或应用配置。

- 日常使用：打开应用或播放指定媒体，以及暂停/继续、双向跳转、音量、全屏、关闭。
- 功能验收：对 MPV / VLC / Totem 执行保留原编号 1、3—13 的共 12 项用例（第 2 项窗口大小已移除），输出可追溯报告。
- Snapshot：说明当前自动化接口限制，不代为执行测试。

## Use Cases

- 用户要求用 MPV、VLC、Totem 打开播放某个本地视频或音频，或做暂停/继续、跳转、音量、全屏、关闭等日常控制。
- 用户明确要求“测试/验收/简测 MPV、VLC 或 Totem”，或要求出具这些播放器的测试报告。
- 用户要求打开相机、拍照或录像，或询问 Snapshot 能否自动化测试。
- 需要一次调用同时完成“实际容器对应的格式项 + 基础控制项”的回归验证，并按各自证据目录汇总多次运行结果。

## Inputs and Outputs

- Input: `--app mpv|vlc|totem|snapshot`（必填）、`--mode quick|acceptance`（默认 quick，仅切换报告详细程度，不改变范围与判据）、`--cases all` 或原编号如 `3,4,5`（默认当前全部 12 项）、`--input <实际媒体路径>`（一次只传一个文件）、可选 `--run-dir <尚不存在的目录>`、`--list` 只列编号不运行应用。
- Output: 每轮运行目录下的 `results.json`、`automatic.json`、`summary.md`、`report.md`、`evidence/` 与 `evidence-sha256.json`，默认写入 `${XDG_STATE_HOME:-~/.local/state}/bianbu-media-apps/`；回复使用脚本返回的 `cases`、`summary_text` 与报告路径。PASS/FAIL 按脚本判据，BLOCKED 表示条件或素材不足，NOT_RUN 表示未执行，退出码 0 或 REPORTED 只代表报告已生成。

## Dependencies

- Python 3.9+ 运行 `scripts/run.py`；无需 MCP、Bibit 专有工具或固定用户路径。
- 目标播放器本身、`ffprobe`，以及可访问的真实桌面会话。
- VLC 与 Totem 的控制还需 Python GI/Gio 与桌面会话 D-Bus（MPRIS / GApplication）；已有同名应用在运行时脚本会阻塞，避免接管用户播放。
- 验收需要 Skill 外真实的本地媒体素材：一次调用只验证对应容器，全格式需分别提供 MP4/MKV/AVI/MOV/WebM/FLV。
- 摄像头相关能力需要 `/dev/video*` 与桌面会话。

## Limitations

- Snapshot 当前未提供拍照、开始录像、停止录像的原生 CLI 或已导出 D-Bus 控制接口，无法自动化测试（BLOCKED：控制接口不足），这不代表相机功能故障；脚本不模拟按键或无障碍接口，也不用 FFmpeg/GStreamer 代测。
- 不用于 VPU/V2D 性能基准或自定义媒体流水线，此类请求应改用对应 Skill。
- 本 Skill 是原生接口功能验证，不是 GUI 手势验收：CLI PASS 不证明真实点击/拖拽、画质、听感或物理音画同步；原始 GUI 步骤保留为 NOT_RUN。
- 保留平台默认解码器与输出，不追加或修改 hwdec/vo/ao、系统配置或插件开关；硬解日志只作辅助证据，不计入用例通过率。
- 只操作本次实例，不全局杀进程，不终止用户正在播放或录像的会话；应用自身可能保存历史记录，Skill 不手工写其配置。
- 不自动安装依赖、不提权；依赖缺失或桌面不可用时如实说明，不以无界面解码冒充可见播放；缺素材报告 BLOCKED，不无限搜索。
- 不增加用户未要求的测试项，不用退出码 0 代替测试通过。

## Maintainer

Owner: wumingjie
Contact: mingjie.wu@spacemit.com
