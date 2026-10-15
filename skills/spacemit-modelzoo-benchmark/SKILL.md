---
schema_version: 2
name_zh: ModelZoo 性能验证
name_en: SpaceMIT ModelZoo Benchmark
name: spacemit-modelzoo-benchmark
version: v2.0.2
description: "Orchestrate the complete official ModelZoo performance validation on SpacemiT K-series devices: detect the chip automatically, download and test ONNX/GGUF/VLM models serially from versioned recipes, automatically re-run anomalies, keep history and produce an auditable report. Audio models are filtered out by default and packages larger than 5 GB are skipped."
description_zh: 在进迭时空 SpaceMIT K 系列设备上完整编排官方 ModelZoo 性能验证；自动识别芯片、按版本化配方串行下载和测试 ONNX/GGUF/VLM、自动复测异常、保存历史并生成可审计报告。默认过滤音频模型，并跳过大于 5GB 的包。
metadata:
  version: 2.0.2
---

# SpaceMIT ModelZoo 性能验证 v2

从官方 ModelZoo 取证到结果审计执行完整闭环。这只验证性能，不验证精度。每个适用模型必须得到测量结果或明确的跳过/阻塞状态。音频模型保留在覆盖清单中并自动记为 `skipped_policy`，不检查大小、不下载、不解包、不测试；用户额外排除的类别记为 `skipped_user`。

## 首选入口

```bash
python3 <skill目录>/scripts/benchmark.py run-all --out results
python3 <skill目录>/scripts/audit_results.py --out results
```

`run-all` 在清单不存在时自动 discover，然后串行完成大小检查、下载、测试、异常复测、结果选择和报告。使用 `--refresh-source` 强制刷新官方清单，`--skip-kind vlm` 等参数遵守用户明确的范围，`--model <精确ID>` 只运行一项。重新执行会跳过已有终态；使用 `--rerun` 创建新 run ID 并保留旧 attempts，不覆盖历史。

运行前读取 `references/recipes.json`。配方键使用“表格类别/模型名”，避免同名 GGUF 与 VLM 混淆。专用配方绑定已验证的 ModelZoo commit；官方 commit 变化时标记 `blocked_recipe_review`，核实关联文档和模型包后更新配方，不能继续套用旧参数。直接 ONNX/GGUF 仍从表头动态读取配置。

## 数据和环境

1. 从 `/proc/device-tree/compatible`、`/proc/device-tree/model`、`/sys/devices/soc0/` 唯一识别 K 系列芯片；不能根据主机名或 CPU 数量猜测。
2. 固定官方 Markdown commit，保存原文、SHA256、来源行和配方版本。下载后保存模型包 SHA256；量化从表格、URL 和运行时元数据交叉核对。
3. 每次测量前后记录时间、负载、可用内存/磁盘、CPU policy 当前/最小/最大频率、governor 和相关包版本。不要自动调频或终止其他用户进程。
4. 检查 `llama.cpp-tools-spacemit`、`spacemit-onnxruntime`、`python3-spacemit-ort`。缺失时可针对性 apt 安装这三项，避免全系统升级。实际版本与官方基线不同则 `comparability.status=limited`。
5. 正式日志必须确认 SpaceMITExecutionProvider 或 `CPU_RISCV64_SPACEMIT`，且不得出现 `failed to open aidma list`。Harness 硬件访问规则见 `references/harness.md`。

## 下载、锁和磁盘

- 工作区使用 `.benchmark.lock` 和 `active-operation.json`；锁被占用时停止，不启动第二个下载或推理。下载与测量在一个所有者下串行执行。
- 默认上限 5,000,000,000 字节。先以 HEAD/Range 核实大小；无法核实记 `blocked_size_unknown`。分片模型按全部必需文件合计。
- `.part.json` 保存 URL、预期大小和强 ETag。网络中断保留安全分片，下一进程只在 ETag 和 Content-Range 一致时续传；条件不满足从头下载。最终核实大小、格式和 SHA256 后原子改名。
- tar 解包拒绝路径穿越、符号/硬链接和设备节点，并在解包前累计声明大小检查空间。
- `cache-ledger.json` 只登记本 skill 创建的模型缓存。空间不足且本次用户明确授权清理时传 `--cleanup-old-models`；只删除台账中 `measured` 的缓存并记录路径、大小和时间。不要把一次授权写成永久默认。
- 单独预览清理：`benchmark.py cleanup-cache --out results`；得到本次明确授权后才加 `--execute-cleanup`。`--remove-downloads` 只清理本次模型的已测缓存。

## 测量和自动复测

- ONNX 使用 `onnxruntime_perf_test MODEL -e spacemit -r 10 -x 1 -S 1 -s -c 1 -i 'SPACEMIT_EP_INTRA_THREAD_NUM|N' -I`，按表中核数运行。取 `Average inference time cost total`。
- GGUF 使用 `llama-bench -m MODEL -t 8 -p N -n N -mmp 0 -fa 1 -ub 128`，分别对齐 PP/TG 128 或 1280。
- VLM 由配方自动安全解包并调用 `vlm_server_bench.py`。固定生成的图片 SHA256、尺寸、LLM 8 线程和视觉核数；只解析每次请求的 `vision encode`，不能用普通 ONNX、`vision prefill` 或端到端时间代替。默认清除 dense accuracy 变量；仅配方明确要求时设置并保存在 `environment.json`。
- 每项先预热一次，再测三次取中位数。出现退化候选时保存当时环境并自动完整复测一次。初测和复测同一指标都超过阈值才成为 `confirmed_regression`；不一致则 `review_required`。不无限重试。
- 音频模型由默认策略在下载前过滤，状态为 `skipped_policy`。报告仍列出模型和来源用于覆盖对账，但不得探测文件大小、下载、解包、启动服务或生成性能结论。

## 状态和报告

默认阈值 10%，属于筛查规则而非厂商承诺。差异=`(实测-官方)/官方×100%`；ms/RTF 正数变慢，token/s 负数变慢。

- `within_threshold`：可比环境且配置均在阈值内。
- `confirmed_regression`：初测和自动复测均确认退化。
- `review_required`：复测不一致，或比官方快超过阈值，需核对环境/边界。
- `environment_mismatch`：性能未告警，但软件环境与官方基线不同。
- `baseline_mismatch`：量化或测量边界不一致，百分比仅探索。
- `skipped_policy`：音频模型由当前测试策略过滤，且不存在下载产物或测量记录。
- `skipped_user`、`skipped_size`、`blocked_*`、`download_failed`、`runtime_failed`：分别保留具体原因。

每次运行写入 `runs/<run-id>/`，保存参数、环境、初测、复测和日志。顶层结果记录 `attempts`、`selected_run_id` 和 `selection_reason`。CSV 每个配置包含芯片、类别、模型、源行/commit/SHA、下载 URL/字节/SHA、配方、环境可比性、命令、样本、日志、初测与最终选择。报告先列确认告警，再列需复核项和完整覆盖清单。

结束必须运行 `audit_results.py`。只有覆盖相等、每配置至少三次样本、中位数/百分比正确、日志存在、确认告警含初测证据时才可声明完成。

## >5GB 独立补测

默认批次保留 `skipped_size`。用户明确选择单项后：

```bash
python3 <skill目录>/scripts/benchmark.py run-all --out results --model <精确ID> --allow-large
```

先核算下载、解包、完整权重和运行时缓冲；结果写入独立 `results-large-<ID>.json`，不覆盖默认跳过记录。VLM 沿用其专用配方。

## DeepSeek Harness

优先安装到实际运行 Harness 用户的 `~/.dsh/skills/spacemit-modelzoo-benchmark-v2/`；项目隔离需要时放到 `<工作区>/.dsh/skills/`。SSH 为 root 而 Harness 以 bianbu 运行时，两者的 `~` 不同。安装后用 skill 工具调用记录确认发现成功。版本 `0.1.1-rc.2` 的启动、长任务等待及一次性硬件访问 patch 见 `references/harness.md`。
