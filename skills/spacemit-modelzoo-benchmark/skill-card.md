---
schema_version: 2
---
# Skill Card: SpaceMIT ModelZoo Benchmark

## Capability

在进迭时空 SpaceMIT K 系列设备上完整编排官方 ModelZoo 性能验证：自动识别芯片，按版本化配方串行下载与测试 ONNX / GGUF / VLM 模型，对退化候选自动完整复测，保存每次运行历史并生成可审计报告。只验证性能，不验证精度。

## Use Cases

- 对官方 ModelZoo 做完整性能验证或性能回归跟踪。
- 需要覆盖清单闭环与结果审计的场景：每个适用模型必须得到测量结果或明确的跳过/阻塞状态。
- 针对单个模型（含大于 5GB 的包）做独立补测。

## Inputs and Outputs

- Input: `scripts/benchmark.py run-all --out results`；可选 `--refresh-source`、`--skip-kind`、`--model <精确ID>`、`--rerun`、`--allow-large`；配方见 `references/recipes.json`。清理预览用 `cleanup-cache`，本次明确授权后加 `--execute-cleanup`。
- Output: 每次运行写入 `runs/<run-id>/`（参数、环境、初测、复测与日志），顶层结果含 `attempts`、`selected_run_id`、`selection_reason`；CSV 每配置一行；结束必须运行 `scripts/audit_results.py --out results`。

## Dependencies

- SpacemiT K 系列设备；芯片类型从 `/proc/device-tree/compatible`、`/proc/device-tree/model`、`/sys/devices/soc0/` 唯一识别。
- `llama.cpp-tools-spacemit`、`spacemit-onnxruntime`、`python3-spacemit-ort`（缺失时可针对性 apt 安装）。
- 官方 ModelZoo Markdown 清单与模型包的网络下载；VLM 用例使用 `scripts/vlm_server_bench.py`。
- 在 DeepSeek Harness 中运行时，硬件访问规则见 `references/harness.md`。

## Limitations

- 音频模型默认按策略过滤为 `skipped_policy`：不探测大小、不下载、不解包、不启动服务、不生成性能结论。
- 默认跳过大于 5,000,000,000 字节的包（`skipped_size`），只有用户明确选择单项并加 `--allow-large` 才独立补测。
- 默认 10% 阈值是筛查规则，不是厂商承诺；`baseline_mismatch` 的百分比仅供参考。
- 官方 commit 变化时标记 `blocked_recipe_review`，核实后更新配方，不能继续套用旧参数。
- 不自动调频，不终止其他用户进程；不根据主机名或 CPU 数量猜测芯片型号。
- 锁被占用时停止，不启动第二个下载或推理；对退化的自动复测只做一次，不无限重试。

## Maintainer

Owner: fuqiang
Contact: qiang.fu@spacemit.com
