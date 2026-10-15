# DeepSeek Harness A/B 对比

## 公平性

- 同一模型、相同模型设置、相同用户提示、相同最大时间和全新工作目录。
- Baseline 通过 patch 禁用 `skill-filesystem`；Skill 组启用文件系统 Skill，并确保只安装本版本 `vibe-coder`。
- 不把 Skill 内容粘贴到 baseline 提示中，不对任一组人工修复。

## 推荐提示

`在当前目录生成1个中国象棋HTML网页应用。必须实际创建文件，完成后说明启动和验证方法。`

## 产物

每组保存 Harness 日志、生成目录、`validation.json`、`score.json`、耗时和退出码。使用 `scripts/score_app.py` 生成确定性结构评分。

## 结论边界

- 评分仅衡量可观察的结构、资源自包含、关键控件和危险模式，不等同于完整棋规正确性。
- 报告必须同时列出失败项和人工未验证项，不得只比较文件数量或代码行数。
