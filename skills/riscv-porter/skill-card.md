---
schema_version: 2
---
# Skill Card: riscv-porter

## Capability

将有源码的 x86_64 / ARM / AArch64 项目迁移到 SpacemiT K3（Bianbu）原生 `riscv64` 环境：在项目工作区内完成基线探测、平台识别、依赖可用性诊断、架构守卫与最小补丁修改、本地构建与测试验证、RISC-V ELF 产物检查，并产出可审查的 `riscv-port-report.md`。脚本 `scripts/riscv_probe.sh` / `scripts/run_attempt.sh` / `scripts/audit_changes.sh` 分别承担探测、有界构建/测试循环和交付前证据审计。

## Use Cases

- 维护者拿到一份第三方 C/C++ 项目源码，需要在 K3 / Bianbu `riscv64` 上完成首次可重现构建与运行。
- 上游项目在 `riscv64` 上构建/链接失败，根因集中在架构标识、内联汇编、SIMD（x86 SSE/AVX 或 ARM NEON）不兼容、字节序/对齐、ABI、原子或系统调用差异。
- 项目依赖链中存在 riscv64 缺失的预编译包，需要在不提权的前提下通过 vendored 源码或项目内解包二进制解决。
- 需要在 K3 上对一份已构建产物做最小可移植性 / SIMD 回退 / RVV 路径决策，并给出有差分证据的报告。
- 仅做正确性移植，不主动追求 RVV 性能优化，除非用户明确要求或存在已证实且阻断使用的性能问题。

## Inputs and Outputs

- **Inputs**:
  - 用户传入的项目根路径（必须可读源码；不接受纯二进制交付物）。
  - 构建与测试命令（优先采用项目 CI / 当前构建文件给出的权威路径；缺省时由 Skill 选定并标注推断依据）。
  - 可选：性能目标、SIMD 兼容性要求、明确允许的依赖注入方式。
- **Outputs**:
  - 工作区修改：保留在 `<项目>/` 下，绝不覆盖原始压缩包或干净副本。
  - 探针与日志：`<项目>/.riscv-porter/` 下的 `analysis-checkpoint.md`、`logs/` 等中间产物。
  - 移植报告：`riscv-port-report.md`，含基线/最终证据、修改文件清单、错误分类、剩余风险与精确复现命令。
  - 原生 `riscv64` ELF 产物及其上游测试或确定性 smoke 测试通过证据。

## Dependencies

- 宿主平台必须是 SpacemiT K3 / Bianbu `riscv64`（通过 `uname -m` 验证）。
- 可用工具链：`gcc` / `clang`（riscv64 交叉或原生）、`make` / `cmake` / `ninja` / 项目自带构建系统、`file`、`readelf`、`timeout`、Bash、`rg`。
- 项目所需的运行时依赖通过以下顺序解决：已安装的 riscv64 兼容版本 → 项目内解包预编译包 → 固定版本源码构建。**不**使用 `sudo` / 系统包安装 / 未授权的联网脚本。
- 报告与面向用户的过程说明使用中文；命令、文件名、API 名和机器可解析日志键保持原样。

## Limitations

- 仅处理有源码的项目；纯二进制交付物不在覆盖范围，遇到时停止并说明。
- 单次任务以 8 分钟 / 12 次工具调用为补丁设计软上限；可选基准等长任务单项最多 120 秒。连续两轮同一根因、累计六轮未完成或需要新的用户授权/外部依赖时停止并报告。
- 性能优化是独立模式：默认只记录优化机会，未做重复计时与差分证据前不交付手写 RVV。
- Sanitizer 告警即使来自上游既有代码也不能忽略，必须分类为「本次引入 / 本次路径触发的上游问题 / 无关既有问题」并修复或列为未解决风险。
- 跨架构结论仅在「已在该架构构建/运行验证」「仅由条件守卫保留」「上游本就缺失或不可构建」三档之内做出区分；不允许把后两档写成已验证。
- 修改范围严格限于项目工作区，不写入凭据；不调用 `mount` / `umount2` / `reboot` / `init_module` 等敏感 syscall 或破坏性清理操作。

## Maintainer
Owner: dec
Contact: decheng.liu@spacemit.com