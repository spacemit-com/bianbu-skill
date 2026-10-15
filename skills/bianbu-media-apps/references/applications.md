# 板端应用选择

以下入口于 2026-09-21 在 `10.0.91.170` 从安装包、可执行文件和 `.desktop` 读取确认。迁移到其他机器时重新确认，不把此 IP 写死为执行目标。

| 用户名称/上下文 | 应用 | 启动命令（参数数组） | 桌面入口 | 适用操作 |
|---|---|---|---|---|
| mpv | mpv | `["mpv", "实际媒体路径"]` | `mpv.desktop` | 视频/音频播放与控制 |
| Totem、GNOME Videos、明确指向 Totem 的“视频”应用 | Totem | `["totem", "实际媒体路径"]` | `org.gnome.Totem.desktop` | 视频播放与控制 |
| VLC | VLC | `["vlc", "实际媒体路径"]` | `vlc.desktop` | 视频/音频播放与控制 |
| Snapshot、相机、Camera | GNOME Snapshot | `["snapshot"]` | `org.gnome.Snapshot.desktop` | 相机预览、拍照、录像；当前 UI 可提供二维码识别 |

只打开应用时省略媒体参数或使用现有桌面入口。`.desktop` 自带参数由系统启动器处理，不把它们复制成日常命令的“优化”参数，也不改 `.desktop`。尤其 mpv 不追加硬解或输出参数。

现场包版本：Totem `43.2-8ubuntu1bb5`；GNOME Snapshot `49.0-1ubuntu1bb15`；VLC `3.0.23-1bb1`。这是安装探测，不是各功能已通过测试。mpv 的平台默认硬解已由用户确认；其他应用的硬解状态没有据此得到证明。

用户指定某个应用时，不能通过 `xdg-open` 把文件交给不确定的默认播放器。只有未指定应用且上下文无偏好时，才可使用系统默认关联。普通“播放视频”里的“视频”通常是媒体类型，不自动解释为 Totem 应用名称。

Snapshot 的本机帮助只列出调试等通用选项；不能臆造 `snapshot --record` / `--capture`。已安装 GSettings schema 有 picture/video/qr-detection 模式，以及录音和硬件编码设置；**schema 存在不证明 UI 功能正常，也不授权修改设置**。尤其其硬件编码 schema 默认 false，不把 mpv 的硬解默认策略套用到它。

Totem 本机帮助提供 play/pause、seek、volume、fullscreen 等控制选项。普通控制可以在目标实例明确且语义核实后使用已支持的控制接口；这是执行用户要求的控制动作，不是启动时追加硬解优化参数。默认测试使用 cli.md 的原生接口功能判据；只有用户明确要求真实点击/按键验收时才走 GUI 流程。
