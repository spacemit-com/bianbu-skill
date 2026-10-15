# 已验证的 DeepSeek Harness 集成注意事项

2026-09-04 设备上的 `@deepseek-ai/dsh` 为 `0.1.1-rc.2`。以下是该版本的实测注意事项，其他版本先读 `--help` 与本机文档。

- 用户级安装使用实际运行 Harness 用户的 `~/.dsh/skills/<name>/SKILL.md`；项目 `.dsh/skills/<name>/SKILL.md` 也可被发现。以 root 登录后再用 bianbu 启动 Harness 时，检查 `/home/bianbu/.dsh/skills`，不能检查 `/root/.dsh/skills` 后误判缺失。`dsh --profile headless "任务"` 创建一次性会话；项目级 skill 必须从对应工作区启动。
- 本次安装的启动器需要 Node `--expose-internals`，否则 HMR 初始化报错。可通过 `node --expose-internals <已确认的 dsh/lib/bin.js> --profile headless "任务"` 启动。
- 默认 bwrap 沙箱创建私有 `/dev`。硬件基准先检查 `/dev/aidma_list`、`/dev/tcm` 是否可见；不能把沙箱隐藏硬件导致的降速当作芯片退化。
- 用户明确批准本次完整硬件访问后，可使用工作区内的独立 patch，不修改用户全局 profile：

```yaml
- id: sandbox-policy
  config:
    mode: danger-full-access
- id: permission
  config:
    defaultPreset: danger-full-access
```

通过 `--patch ./hardware-access.patch.yml` 引用。仅改 sandbox-policy 会导致 “composed sandbox and approval defaults match no preset” 启动错误。权限预设也要匹配。授权仅作用于已批准范围，不能自动带入其他任务。

- 本次以设备普通用户运行 harness 即可访问硬件节点；不要仅为了跑分改成 root。包安装需要的权限单独遵守宿主机制。
- 一次性 bash 工具可能默认在 60 秒终止命令。长流程直接把 `run-all` 作为一个后台 job，并用该 job ID 等待；脚本内部的工作区锁负责防重。记录准确 PID/job ID，不重复启动同一批次。不要在含相同搜索字符串的 shell 中用 `pgrep -f` 反复找进程，它会匹配等待脚本自身而永不结束。
- 一个执行方负责模型下载/缓存。若外部协作者参与，应先明确记录进程 ID、缓存路径和所有权，不能把未识别的任务进程直接当作遗留进程删除。
- 核实会话中存在 `skill` 工具调用；需要硬件授权时同时核实会话 `sandbox/mode`。输出日志只提取相关事件，避免导出凭据或不相关历史。
