# riscv-porter

面向 Bianbu Agent 文件系统的 Skill，用于把有源码的 x86/ARM 项目迁移到进迭时空 K3 `riscv64` 系统。

## 安装

开发环境中，将本目录放入待迁移项目的 `.bianbu-agent/skills/riscv-porter`；用户级安装则放入
`~/.bianbu-agent/skills/riscv-porter`。从配置对应的项目目录启动 Bianbu Agent，Skill 会根据请求描述自动发现：

```sh
mkdir -p .bianbu-agent/skills
cp -a riscv-porter .bianbu-agent/skills/riscv-porter
uv run bianbu-agent --config .bianbu-agent/config.yaml
```

当用户请求与描述明确匹配时，模型也可以自动调用该 Skill。

0.5.0 根据 StreamVByte、utf8_range 和 base64 三项目 A/B 实测，新增基线成功停止门、当前权威构建路径与文档漂移判定、正确性/性能模式分流、可重放 SIMD 差分证据、严格 120 秒外层预算、同一 fallback 识别，以及自动修改规模审计。目标是在保持通过率的同时减少不必要的架构重写和不可复核证据。
