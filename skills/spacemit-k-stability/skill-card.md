---
schema_version: 2
---
# Skill Card: SpacemiT K Stability

## Capability

在 SpacemiT K 系列开发板上运行并监管稳定性测试。控制器 `scripts/stability.py` 优先从 SpacemiT Gitee 仓库获取厂商 `stability-test.sh`，获取失败或校验不通过时回退到技能内置版本，并在元数据与报告中记录来源与 SHA256；同时负责记录设备指标与日志、限制测试时长、生成 Markdown 报告，且只停止由本次测试启动的进程组。

## Use Cases

- 在本地或可通过 SSH 访问的 Bianbu K1/K3 设备上执行默认无限时长或指定时长的稳定性测试。
- 测试期间的实时进度与负载监控、异常检测与周期汇报。
- 测试结束后的报告汇总，以及限定在本次 run 的资源清理。
- 从 DeepSeek Harness 等非图形终端发起受控的启动、停止与报告。

## Inputs and Outputs

- Input: `scripts/stability.py` 的 `preflight --json`、`start`、`status --json`、`stop`、`report`；时长用 `--duration`（支持 `s`/`m`/`h`/`d`，无单位按秒），另有 `--interval`、`--update`、`--state-dir`；Harness 场景使用 `host-start`、`host-stop`、`host-report`。
- Output: `status --json` 的结构化状态，Markdown 最终报告，以及 `run_id` 与状态目录（默认 `~/.local/state/spacemit-k-stability`），供回合中断后恢复管理。

## Dependencies

- 目标 K1/K3 设备与设备上的 Python 3；无 Python 3 时降级为 `bash scripts/stability-test.sh -l`。
- 图形负载需要当前用户的桌面会话环境（Wayland/X11 socket 与白名单会话变量），K3 还需要可访问 `/dev/dri/card2`。
- 在 Harness 中需要用户级 systemd 与 D-Bus（`systemd-run --user`）才能执行 host-* 入口。
- 网络可选：用于从 Gitee raw 获取厂商脚本，20 秒超时、2 MiB 上限，并要求内容为带 Shell shebang 的脚本。

## Limitations

- 启动测试会实际改变设备状态，只有用户要求在该设备上测试时才可启动，不得静默复用或终止无关测试。
- 未发现可用图形会话时必须以 `graphical_session_unavailable` 停止；缺少 `/dev/dri/card2` 时必须以 `gpu_device_unavailable` 停止，不得把 Mesa softpipe 结果当作 GPU 稳定性负载。
- 清理范围限定在已登记的本次 run；除限定范围清理失败且用户明确授权紧急清理外，不得使用厂商脚本 `-k` 或广泛 `pkill`。
- `--skip-llama` 仅用于短时控制器或 harness 验证，完整稳定性测试不得使用。
- 降级到内置脚本时无法精确追踪进程归属，使用 `-k` 停止前必须获得用户明确确认。
- 只有真正建立了定时器或监控任务时才能承诺后续主动汇报。

## Maintainer

Owner: fuqiang
Contact: qiang.fu@spacemit.com
