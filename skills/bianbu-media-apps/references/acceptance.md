# 分应用验收

仅用于用户明确要求测试、验收或回归。普通打开/播放/拍照请求走日常使用，不进入此流程。默认 MPV/VLC/Totem 使用 [cli.md](cli.md) 的 CLI 功能验证；本文后半部分的 GUI 约束只在用户明确要求真实 GUI 验收时适用。

## 统一简明检查与按项验收

Snapshot 例外：普通相机测试请求先按 SKILL.md 直接说明原生拍照/录像控制接口不足、本次未执行测试（BLOCKED）；不启动统一入口或自动尝试 GUI。其既有用例表保留，仅供用户以后明确要求的专项诊断或人工/GUI验收。以下播放器 CLI 流程不套用到 Snapshot。

统一入口为 `scripts/run.py --app mpv|vlc|totem|snapshot --mode quick|acceptance`。播放器附加 `--input 实际路径`，按表选择用例附加 `--cases 1,4,5` 或 `--cases all`。两种模式默认选择当前用例表全部项目；用户指定子集则只选择对应编号。MPV/Totem/VLC各12项（原编号1、3—13，不测窗口大小调节），Snapshot原有8项另表保留。`--list` 查看编号而不运行。简明模式只缩短结果说明；完整模式按原表七列追加实际结果和状态。两种模式都不新增硬解/IPC/性能测试行。未选择项 NOT_RUN、缺素材或接口证据的已选项 BLOCKED；已删除项不占报告行。播放器 CLI 证据齐全则按判据给 PASS/FAIL，不再强制 GUI 证据。

脚本自动生成 results.json、summary.md 和 report.md，不先 init、不手写采样程序。REPORTED 后交付结果。MPV IPC 是默认功能控制与观测接口，动作日志标为 cli_trace，不伪装 gui_trace；不修改 hwdec/vo/ao。CLI PASS 不等于按钮、键位、真实听感或画质验收。VLC 使用 MPRIS，Totem 使用 MPRIS 和 GApplication 全屏 action；Snapshot 保持既有探测。接口不可用时 BLOCKED，不套用其他应用结论。不要重复提取源帧、算截图相关性或打印 ASCII 图像。若用户另行要求真实 GUI 验收，请新建 GUI 结果目录，不混用 CLI 验证配置与 GUI 步骤。

## 基线选择

| 应用 | 基线 | 项数 | 来源与证据指南 |
|---|---|---|---|
| mpv | [cases.json](cases.json) | 12 | 原截图删除第2项后的项目，保留原编号；读 [execution.md](execution.md) |
| Totem | [cases-totem.json](cases-totem.json) | 12 | 根据 mpv 原表适配；读 execution.md 的播放器证据规则，按 Totem 控件操作 |
| VLC | [cases-vlc.json](cases-vlc.json) | 12 | 根据 mpv 原表适配；读 execution.md 的播放器证据规则，按 VLC 控件操作 |
| Snapshot | [cases-snapshot.json](cases-snapshot.json) | 8 | 新增基础相机基线；读 [snapshot.md](snapshot.md) 的验收观察项 |

只加载当前目标基线。报告应明确原表/适配/新增来源，不能称为完整应用功能覆盖。用户选择多个应用时各建运行目录；不得复用其他应用的结论或把旧素材作为本轮拍摄结果。

## 仅限真实 GUI 验收的执行约束

1. 记录实际主机、应用版本、图形会话、工具和素材/设备条件，确认操作的是板端桌面。既有窗口、播放和录制会话先辨识，不能拿 SSH 客户端窗口代替。
2. 保持用户配置。mpv 不追加 hwdec/vo/ao 等参数；其他应用也不换解码器、GStreamer/音频设置或 Snapshot 的 GSettings。无界面输出、Xvfb、FFmpeg 测试只能另列诊断。
3. 各步骤规定的打开方式、拖拽、点击、按键、窗口调整均需目标应用真实 GUI 操作完成。IPC/loadfile/CLI 控制、FFmpeg 解码、直接写属性不等价于指定的 GUI 验收动作。已有只读接口可以辅助观测。缺真实 GUI 能力时写 BLOCKED，不能改成无界面测试后写 PASS。
4. 每步区分动作轨迹与预期观察。仅命令退出码为 0、窗口存在、工具返回成功，不能证明画面更新、声音、音画同步、录像保存或容器兼容。每步必须满足基线 `required_observations`；证据类型组的每一组至少满足一种。
5. 键位和控件以目标应用真实行为为准。mpv 原表 ↑↓ 调音量已获用户授权适配；Totem/VLC 适配基线允许实际音量键或控件。保留来源并记录实际动作，不把 mpv 快捷键强加给其他应用，不因已授权键位差异再次询问。
6. 全基线按顺序执行；用户指定子集则只做指定项，其他项 NOT_RUN。可复用状态作为前置但每项须独立证据。单步等待通常最多 15 秒；仅对实际明确的倒计时、文件写入延迟有界延长并记录原因。同一步最多重试 1 次且保留首次失败，不无限重试或自动安装依赖。
7. PASS：所有步骤和预期都有本轮证据。FAIL：条件具备、按步骤执行后不符合预期。BLOCKED：设备/素材/权限/验证能力不足，或功能入口无法确认。NOT_RUN：尚未执行。FAIL 不以重试成功覆盖；复测另建目录关联旧结果。
8. 只关闭本次创建的目标窗口/进程。Snapshot 验收可以按用例拍照及短录像，结束时停止本次录像并确认写入；不终止其他相机使用者、不改录音/编码默认值、不上传作品。缺第二摄像头、二维码卡等前置时明确 BLOCKED。

## 结果与报告

`$SKILL_DIR` 是当前实际 skill 安装目录。下述 `acceptance.py` 只生成模板、校验记录、输出报告，不操作应用、不自动判 PASS。上述 `run.py` 已调用它完成报告，无需再次初始化。

```bash
python3 "$SKILL_DIR/scripts/acceptance.py" init --app totem --run-dir /tmp/totem-acceptance-YYYYMMDD-HHMMSS
```

按实际目标替换 app 为 mpv、totem、vlc 或 snapshot，并使用本次真实时间命名目录。填写 `environment.application`、`app_version`、主机、会话、工具和素材/设备信息。mpv 旧结果的 `mpv_version` 仍兼容。步骤填 method/action/status/observations；证据填写实际采集工具、时刻、用途、运行目录内的相对文件路径。PASS/FAIL 步骤都要动作轨迹；观察项引用顶层 evidence ID。证据结构见 execution.md 的结果填写格式（Snapshot 也采用相同结构）。

```bash
python3 "$SKILL_DIR/scripts/acceptance.py" validate --run-dir /tmp/totem-acceptance-YYYYMMDD-HHMMSS
python3 "$SKILL_DIR/scripts/acceptance.py" report --run-dir /tmp/totem-acceptance-YYYYMMDD-HHMMSS
```

校验和报告从 results.json 读取应用，匹配该应用基线，不按默认 mpv 重解释结果。可额外传 `--app` 检查目标一致性。存在 NOT_RUN 时报告标明未完成；FAIL/BLOCKED 是有效结论，仍应生成报告。保留所有行，不删用例、不改源步骤、不伪造证据、不修改校验器规避失败。

校验成功只说明结构和文件引用满足约束，不证明截图、录屏或观察内容真实。Skill 是执行约定，不是操作系统安全边界；若要强制防绕过，由 agent 外部 Runtime/CI 执行受控校验器，本 skill 不修改 Runtime 策略。
