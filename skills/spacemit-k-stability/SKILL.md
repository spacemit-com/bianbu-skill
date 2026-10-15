---
schema_version: 2
name_zh: K 系列稳定性测试
name_en: SpacemiT K Stability
name: spacemit-k-stability
version: v0.1.2
description: "Run and supervise stability tests on SpacemiT K-series development boards. The controller prefers fetching stability-test.sh from the SpacemiT Gitee repository and falls back to the copy bundled with the skill when that fails; it works on local or SSH-reachable Bianbu K1/K3 devices and supports unlimited-duration or timed runs, live progress and load monitoring, anomaly detection, report summarisation and scoped resource cleanup."
description_zh: 在 SpacemiT K 系列开发板上运行和监管稳定性测试。优先获取 SpacemiT Gitee 仓库中的 stability-test.sh，获取失败时使用技能内置版本；适用于本地或可通过 SSH 访问的 Bianbu K1/K3 设备，支持默认无限时长或指定时长测试、实时进度与负载监控、异常检测、报告汇总和限定范围的资源清理。
---

# SpacemiT K 系列芯片稳定性测试

使用控制器 `scripts/stability.py`。启动时优先从 [SpacemiT factorytest 的 K3 分支](https://gitee.com/spacemit-buildroot/factorytest/blob/k3-br-v1.0.y/common/stability-test.sh)获取厂商脚本；获取不到或内容校验失败时，自动使用内置的 `scripts/stability-test.sh`。控制器负责记录设备指标与日志、执行可选的测试时长限制、生成 Markdown 报告，并且只停止由本次测试启动的进程组。

## 执行约定

- 用户未指定时长时，按无限时长处理（`0`）。例如“测试 24 小时”应传入 `--duration 24h`。
- 每次 `start` 都把优先获取的脚本保存到本次 run 目录，不覆盖技能内置脚本。下载使用 20 秒超时和 2 MiB 大小限制，并要求内容是带 Shell shebang 的脚本。无论使用在线版还是内置回退版，都在元数据和最终报告中记录来源、SHA256；回退时同时记录获取失败原因。
- Gitee 页面地址用于追溯，实际下载使用对应的 raw 地址：`https://gitee.com/spacemit-buildroot/factorytest/raw/k3-br-v1.0.y/common/stability-test.sh`。不得因为在线获取失败而直接中止，只要内置脚本校验通过就继续测试，并明确展示已发生回退。
- 使用循环模式运行负载，使已启用的测试项持续工作，直到达到指定时长或收到停止请求。不要为了修改测试时长而编辑厂商脚本。
- 启动前必须展示：识别到的芯片、当前 CPU 与系统负载、可用内存、温度、磁盘剩余空间、是否存在其他运行中的任务，以及本次计划时长。
- 从 SSH、Harness 或其他非图形终端启动时，控制器必须恢复当前用户的桌面会话环境。它会从同 UID 的 `lxqt-session`、`labwc`、Wayland/X11 会话进程读取限定白名单变量，并检查 Wayland/X11 socket；随后把 `DISPLAY`、`WAYLAND_DISPLAY`、`XDG_RUNTIME_DIR`、`DBUS_SESSION_BUS_ADDRESS`、`XDG_SESSION_TYPE` 以及可用的音频会话变量传递给 supervisor 和厂商脚本。不得把完整进程环境写入日志或报告。
- 如果未发现可用图形会话，`start` 必须以 `graphical_session_unavailable` 停止，而不是让 mpv/glmark2 静默回退到无权限的 DRM 路径。`preflight --json` 中的 `graphical_session` 用于确认变量来源及 Wayland/X11 socket 是否存在。
- K3 的图形负载还需要执行环境能够访问 `/dev/dri/card2`。`preflight --json` 中的 `graphics_devices` 用于核对；普通 `start` 缺少该设备时必须以 `gpu_device_unavailable` 停止，不能把 Mesa softpipe 软件渲染误报为 GPU 稳定性负载。
- 启动稳定性测试会实际改变远端设备状态。只有用户要求在该设备上测试时才可启动；不得静默复用或终止无关测试。
- 测试运行期间，按约定周期调用 `status --json`，简洁展示阶段与状态、已运行时间与目标时长、CPU/load、内存、温度、磁盘、活动负载进程和新增告警。默认每 5 分钟向用户汇报一次；短时验证应使用更短周期。
- 进程退出、OOM、段错误、I/O 错误、过温、磁盘空间不足或采样器停止均属于需要处理的异常。必须展示证据和严重程度，不能用整体 `running` 状态掩盖单个测试项失败。
- 达到指定时长、用户明确停止或出现致命安全告警时，调用 `stop` 并等待进入终态，然后调用 `report`。最后确认本次测试拥有的负载进程全部退出。
- 清理范围必须限定在已记录的本次 run。除非限定范围的清理失败且用户明确授权紧急清理，否则不得使用厂商脚本的 `-k` 参数或广泛 `pkill`。保留测试日志和最终报告，只删除本次 run 创建且已登记的临时文件或测试文件。
- 如果无限测试期间连接或 Agent 回合无法持续保持，应让独立监管进程继续运行，并向用户返回 `run_id` 和状态目录，明确说明如何使用 `status`、`stop` 和 `report` 恢复管理。只有真正建立了定时器或监控任务时，才能承诺后续主动汇报。

## 命令

在目标开发板的 Skill 目录中执行：

```bash
# 只做启动前检查
python3 scripts/stability.py preflight --json

# 默认无限时长测试
python3 scripts/stability.py start

# 指定测试 24 小时
python3 scripts/stability.py start --duration 24h

# 从 DeepSeek Harness 启动时：通过用户级 systemd 把受控动作交给宿主执行
python3 scripts/stability.py host-start --duration 24h

# 短时验证：缩短采样与进展摘要周期，并跳过耗时的 LLM 模型下载
python3 scripts/stability.py start --duration 2m --interval 10 --update 20 --skip-llama

# 查询进展与状态
python3 scripts/stability.py status --json

# 明确停止并生成报告
python3 scripts/stability.py stop
python3 scripts/stability.py report

# 从 DeepSeek Harness 停止或生成报告
python3 scripts/stability.py host-stop
python3 scripts/stability.py host-report
```

时长单位支持 `s`、`m`、`h` 和 `d`；不带单位的整数按秒处理。状态目录默认为 `~/.local/state/spacemit-k-stability`。只有需要隔离状态时才设置 `--state-dir`，并确保后续所有命令使用同一个目录。

`--skip-llama` 只用于短时控制器或 harness 验证，避免模型下载时间超过验证窗口。该选项会创建一份仅供本次 run 使用的配置副本，不会修改内置厂商脚本。除非用户明确要求排除 LLM 负载，否则完整稳定性测试不得使用此选项。

厂商脚本安装依赖或初始化负载时，控制器报告 `starting`。只有厂商启动器确认所有负载均已启动后，才开始累计用户指定的测试时长，因此环境准备时间不计入有效稳定性测试时间。

## DeepSeek harness 环境边界

部分 DeepSeek Harness shell 沙箱会把常规状态目录挂载为只读、隐藏 `/dev/dri/card2`，并在 headless 回合结束时销毁 PID 命名空间。此时直接执行 `start` 会导致 glmark2 回退为 Mesa softpipe，mpv 也可能初始化失败；不得把这种结果视为通过。

在 Harness 中应使用 `host-start`、`host-stop`、`host-report`。这些入口只通过当前用户的 D-Bus 调用 `systemd-run --user`，把白名单内的控制器动作交给宿主用户管理器执行；不需要把整个 Harness 改成 `danger-full-access`。`host-start` 非阻塞返回 run_id，但宿主临时 unit 会继续托管 supervisor，直到测试进入终态后自动回收。`status --json` 是只读查询，可直接执行；Harness 的 PID 命名空间可能看不到宿主 supervisor，此时控制器依据状态文件更新时间判断，只有状态超时未更新才报告 `supervisor_lost`。若返回 `host_executor_unavailable`，说明用户级 systemd/D-Bus 不可用，应要求从宿主终端执行对应的 `start`、`stop` 或 `report`，不能尝试自 SSH、硬编码密码或其他绕过沙箱的方式。

## 直接运行内置脚本的降级方案

如果设备没有 Python 3，控制器无法执行在线优先与自动回退逻辑。此时可明确使用内置脚本执行 `bash scripts/stability-test.sh -l`，记录日志目录并手动监控。该降级方案无法精确追踪进程归属；使用前应说明这一限制，而且在使用 `bash scripts/stability-test.sh -k` 停止测试前必须获得用户明确确认。
