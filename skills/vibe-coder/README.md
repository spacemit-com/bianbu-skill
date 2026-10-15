# vibe-coder 0.1.0

面向进迭时空 K3 的 Bianbu Agent Skill，用自然语言生成可离线运行的原生 HTML/CSS/JavaScript 应用。

开发环境中，将本目录放入待迁移项目的 `.bianbu-agent/skills/vibe-coder`；用户级安装则放入
`~/.bianbu-agent/skills/vibe-coder`。从配置对应的项目目录启动 Bianbu Agent，Skill 会根据请求描述自动发现。
验证脚本仅依赖 Python 标准库。

```sh
mkdir -p .bianbu-agent/skills
cp -a vibe-coder .bianbu-agent/skills/vibe-coder
uv run bianbu-agent --config .bianbu-agent/config.yaml
```
