---
schema_version: 2
name_zh: 离线 HTML 应用生成
name_en: Vibe Coder
name: vibe-coder
version: v0.1.1
description: Use when generating, editing, or validating an offline native HTML/CSS/JavaScript application for SpacemiT K3 riscv64/Bianbu, especially when the request mentions a web app or a K3 HTML artifact; do not use for cloud frameworks, external CDNs, or native mobile applications.
description_zh: 在当前工作目录内根据自然语言生成、修改并校验可直接运行的离线 HTML/CSS/JavaScript 应用，面向 SpacemiT K3 riscv64/Bianbu；不使用 CDN、远程字体、npm 构建链或运行时下载，产物归用户所有，没有验证证据时不得宣称应用可用。
---

# Vibe Coder

在当前工作目录内生成可直接运行的 HTML 应用。产物归用户所有；没有验证证据时不得声称应用已经可用。

目标平台为 SpacemiT K3 / Bianbu `riscv64`，运行时依赖 Python 3.14 标准库；本 Skill 以 Apache-2.0 发布，当前版本为 0.1.0。

## 强制边界

- 默认使用原生 HTML、CSS、JavaScript，不使用 CDN、远程字体、在线图片、npm 构建链或运行时下载。
- 所有产物写入用户指定目录；未指定时使用安全的短横线英文目录名。不要覆盖已有非空目录。
- 禁止写入目录外路径，禁止读取或输出凭据，禁止生成 `eval`、`new Function`、任意命令执行、路径穿越或不受控子进程。
- 预览只绑定 `127.0.0.1`，默认使用随机空闲端口。未经用户授权不监听外网地址。
- 优先满足可运行性和完整交互，再考虑装饰性视觉效果。

## 工作流

1. 将需求整理为应用名称、核心功能、交互、数据持久化、验收点。仅当缺失信息会改变产品形态时追问一次；否则采用合理默认值继续。
2. 阅读 [references/html-app-contract.md](references/html-app-contract.md)，按契约创建应用目录。
3. 若需求是中国象棋或棋类应用，再阅读 [references/chess-acceptance.md](references/chess-acceptance.md)。
4. 生成 `index.html`、`styles.css`、`app.js`、`README.md`。保持资源本地化，并为主要控件提供稳定的 `id` 或 `data-testid`。
5. 运行 `python3 <skill-dir>/scripts/validate_app.py <应用目录> --json <应用目录>/validation.json`。
6. 校验失败时，依据结构化错误修复一次并重新运行校验。第二次仍失败则停止，列出阻塞项，不得继续盲目重试。
7. 校验通过后，可运行 `python3 <skill-dir>/scripts/preview_app.py <应用目录> --smoke-test`。只做本机 HTTP 可访问性检查；需要人工视觉确认时明确说明。
8. 输出生成文件、验证结果、启动命令和已知限制。不要只回复代码片段而不落盘。

## 修改已有应用

- 先读取现有 README 和入口文件，保留已经工作的功能与数据格式。
- 修改后再次执行完整校验；不要用删除功能或弱化检查来换取通过。
- 若目录是 Git 仓库，展示修改摘要；不要自行提交，除非用户要求。

## Harness 对比

需要比较有/无 Skill 时，阅读 [references/harness-ab.md](references/harness-ab.md)。两组必须使用相同模型、提示、空目录和超时，并分别保存日志、校验 JSON 与评分 JSON。
