# CLI 功能验证（默认）

## 执行入口与环境

适用于 MPV/VLC/Totem 默认功能测试；不是 GUI 手势验收。无需读取脚本实现或先初始化报告目录。

- 环境：Bianbu/Linux、Python 3.9+、目标播放器、ffprobe、可访问的真实桌面；VLC/Totem 还需 Python GI/Gio 与会话 D-Bus。板端版本可从 applications.md 核对；迁移时重新检查依赖。无需 MCP、Bibit 专有工具或固定用户路径。
- 入口：`python3 "$SKILL_DIR/scripts/run.py" --app mpv|vlc|totem --mode quick|acceptance --cases all --input /实际视频`。这里的 `|` 表示可选值，实际调用只填写一个应用/模式。`SKILL_DIR` 是调用方确定的当前 Skill 根目录。
- 默认选择当前全部12项。子集如 `--cases 3,4,5`；`--list` 仅列编号。`--run-dir` 可指定一个尚不存在的结果目录，不覆盖旧结果。
- 单文件只验证对应真实容器。全部格式测试需分别传入 MP4/MKV/AVI/MOV/WebM/FLV；一次执行基础控制与该素材的格式项，其他素材仅执行各自格式项，顺序运行同一应用以免互相占用。不要把首次缺素材的 BLOCKED 改写为通过，补充运行须保留各自目录与来源。
- 素材留在 Skill 外。优先复用可访问的合适本地视频，控制测试需足够时长供双向跳转。不存在对应素材时报告 BLOCKED，不无限搜索；普通单素材请求不升级为全格式测试。

## 报告与结束条件

输出包括 `results.json`、`automatic.json`、`summary.md`、`report.md` 和 `evidence/`；默认写到 `${XDG_STATE_HOME:-~/.local/state}/bianbu-media-apps/` 下独立运行目录。`evidence-sha256.json` 是结果证据摘要，不是测试素材下载校验要求。

简明报告显示原编号、测试项、状态、实际结果；完整报告前七列保留用例编号、测试模块、测试项、优先级、前置条件、测试步骤、预期结果，追加本次实际结果与状态。`quick` 与 `acceptance` 不改变测试范围和通过判据。

所选项目/素材执行完成并返回 REPORTED 后，直接使用 cases、summary_text 和 report 回复。已完成的项目不重复运行；不能用退出码0代替测试通过。CLI 原始 GUI 步骤的 NOT_RUN 只是没有执行鼠标手势，不能据此覆盖 CLI 主表判定。详细判据如下，仅解释时才需要展开，不将它们新增为测试项。

## MPV

用户允许使用 CLI/命令替代 GUI 手势。MPV 已按用户要求移除原第2项窗口大小调节，保留12项及原编号1、3—13；不再执行该项或在报告中占位。其余判据不变。`run.py` 是通用 Python CLI，无 Bibit 专有依赖，不改变系统、应用或 Agent 配置。

MPV 启动：`mpv --input-ipc-server=<本次私有临时socket> <实际素材>`。通过 JSON IPC 读写本次实例的属性，结束时 quit 并确认 PID 退出。窗口、音量改动只影响该实例；不保存配置。无需 GUI 操作工具，也不采用 null 视频输出；仍需正常桌面服务和默认播放链路。

| 原表编号 | CLI 判据 |
|---|---|
| 1 | 本次 MPV 播放进度推进，quit 后退出码为 0 |
| 3 | 至少两次 time-pos 跨度 >0.5 秒；有音轨时三个 avsync 采样绝对值均 ≤0.1 秒（暂定 CLI 阈值）；无音轨则同步不适用，明确未验证有声播放 |
| 4 | 暂停 1 秒，进度差 <0.1 秒；恢复 1 秒后推进 >0.5 秒 |
| 5 | 向时长 65% 和 20% 分别 seek；每次最多观察 5 秒，每 0.2 秒采样。确认 seeking=false、位置沿预期方向跳至目标附近（2 秒范围内），之后播放位置再次增加即通过，不要求最低推进量或播放速率 |
| 6 | 修改 volume 后回读目标值，恢复后回读原值；不声称实际响度变化 |
| 7 | fullscreen 切换并回读，再恢复并回读；不声称屏幕布局已验收 |
| 8—13 | 实际容器匹配对应项目，并且播放进度推进；缺少的格式 BLOCKED |

官方属性说明：[MPV manual](https://mpv.io/manual/stable/)。A/V 时钟不是物理音画同步证明，渲染尺寸不是画质证明，进度不是画面审阅。

结果 `acceptance_profile=mpv-cli-v1`：主表状态按上述判据得出。原 GUI 步骤保留为 NOT_RUN，仅表示未执行鼠标/拖拽操作，不能据此覆盖 CLI 主表结果。CLI 证据包括真实命令/IPC 轨迹、属性采样、退出码、素材探测和运行日志。

## VLC / Totem

同样12项（1、3—13），不测窗口大小。统一入口改用 `--app vlc` 或 `--app totem`，传入真实素材。使用已安装的 Python GI/Gio 连接真实桌面的会话 D-Bus；无需 playerctl，不自动安装依赖或启用插件。已有同名应用运行则阻塞，避免接管用户播放。

| 应用 | 控制与回读 | 启动方式 |
|---|---|---|
| VLC | MPRIS：Pause/Play/Seek、Position、Volume、Fullscreen、Quit | `vlc -vv 视频路径`（仅增加日志） |
| Totem | MPRIS：Pause/Play/Seek、Position、Volume、Quit；全屏用自身 GApplication fullscreen action 及状态 | `totem 视频路径`（仅用 GST_DEBUG 增加日志） |

每次操作前核对 D-Bus 唯一连接的 PID，仅操作本次实例。结束时恢复音量/全屏并正常退出。应用自身可能保存历史记录，Skill 不手工写入其配置。

- 1、3、8—13：三次状态和位置采样，间隔0.6秒；均为 Playing 且最后位置大于首次。1还要求正常Quit、退出码0；格式项还要求实际容器匹配。3仅验证播放进度，不验证音画同步。
- 4：Pause 后回读 Paused；间隔1秒的位置差小于0.15秒；Play 后5秒内状态Playing且位置增加。
- 5：分别跳到时长65%、20%附近（2秒范围），5秒内有跳转且继续推进。用相对 Seek，因为 Totem 可能不提供有效 trackid。
- 6：调整 Volume 并回读，恢复原值后再回读，容差0.015；不验证听感。
- 7：切换全屏并回读状态，恢复原状态后再回读；不是截图或布局验收。
- Totem Quit 可能在返回前断开总线；只有本次进程正常退出0才算关闭通过。

profile 分别为 `vlc-cli-v1`、`totem-cli-v1`。接口缺失/权限不足为 BLOCKED，有接口但结果不符合判据为 FAIL。硬解日志只作辅助证据，不增设用例。Snapshot 保持原探测，不套用播放器控制。

只有用户明确要求 GUI 操作验收时，才使用 acceptance.md / execution.md 的 GUI 判据。默认 CLI 路径不读取或强制这些 GUI 要求。
