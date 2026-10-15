---
schema_version: 2
name: cpu-compress-benchmark
name_zh: CPU解压缩性能基准
name_en: CPU Compression Benchmark
version: "v1.0.1"
description: Use when the user wants to measure CPU compression or decompression performance on this machine — throughput, compression ratio, CPU time or peak memory of gzip/pigz/zstd/xz/bzip2 — or asks for a benchmark, performance comparison or tuning result for compressors, and expects a structured report with reproducible evidence.
description_zh: 当用户需要在本机对 CPU 压缩/解压缩性能（吞吐、压缩比、内存占用）做基准测试并生成结构化报告时使用。
---
# CPU Compression Benchmark

Measure how fast this machine compresses and decompresses data, then hand back a
structured report whose every number traces to a raw measurement file.

## When to use this skill

Trigger it when the user wants any of the following:

- compare compressors (gzip, pigz, zstd, xz, bzip2) on the current machine;
- measure compression ratio, throughput, CPU time or peak memory of a codec;
- pick a default codec or level for a backup, build artifact, log or transfer path;
- check whether parallelism (pigz, `zstd -T`, `xz -T`) actually helps here;
- produce benchmark evidence for a review, a bug report or a release decision.

Do not use it to compress the user's real data, to benchmark disk or network
throughput, or to compare machines against each other. It measures CPU work on
a synthetic dataset and never touches user files.

## Workflow

1. Confirm the machine is idle enough to measure. A benchmark on a busy host
   produces numbers that must not be quoted; ask the user to wait, or record the
   load in the report as a caveat.
2. Decide the run shape with the user when the choice matters: dataset size,
   categories, codec and level set, thread counts, repeats. The defaults are
   deliberately cheap — a 128 MiB dataset, each codec's default level, all
   logical CPUs, and one timed pass per configuration — so a first run finishes
   in well under a minute.
3. Collect the environment, then time every configuration:

   ```bash
   scripts/benchmark.sh --run-dir ./benchmark-run
   ```

   Add `--repeats 3` (or more) only when the run-to-run spread matters; that is
   the one quantity a single pass cannot report.

4. Read the result. `report.md` is the deliverable; `summary.json`,
   `summary.csv`, `env.json` and `raw/measurements.jsonl` are the evidence a
   reader can re-check.
5. Report the outcome with the caveats the run actually hit — governor, turbo,
   filesystem, failed configurations — instead of quoting a bare MiB/s figure.
6. Prune large files once the numbers are settled. The dataset and archives are
   regenerable, and pruning keeps the hashes:

   ```bash
   scripts/prune.sh --run-dir ./benchmark-run
   ```

## Defaults and useful variations

A default run is one pass over 128 MiB with each codec's own level. Every
variation below trades time for a question the default run does not answer.

| Goal | Command shape | Cost |
| --- | --- | --- |
| Quick first look (default) | `--run-dir ./benchmark-run` | ~1 min |
| Codec comparison | `--codecs "gzip pigz zstd xz bzip2" --levels default` | seconds |
| Parallel speedup | `--threads "1,0"` (0 = one worker per logical CPU) | 2x default |
| Level sweep | `--codecs zstd --levels "1,3,6,9"` | 4x per codec |
| Spread / noise check | `--repeats 3 --affinity 2-5` | 3x default |
| Larger, cache-exceeding | `--size-mib 1024` | grows with size |
| Text-like payloads | `--category text` | same as default |
| Already-compressed data | `--category binary` (incompressible floor) | same as default |

Pin `--affinity` to keep the scheduler from migrating threads, and size the
dataset well above the last-level cache when you want memory-bandwidth-bound
numbers rather than cache-resident ones. When a single-pass number is close
between two codecs, rerun those two with `--repeats 5` before choosing.

## Reading the numbers

The [reference guide](references/guide.md) documents the dataset categories, the
per-codec threading model, the exact measurement definitions and a
troubleshooting table.

- With the default single pass, `Wall spread` is `0.00%` and carries no
  information; treat it as available only when the run used `--repeats 2+`.
- Wall MiB/s is what the user experiences end to end; CPU MiB/s normalizes for
  thread count and is the fair comparison between codecs.
- Ratio is `input / archive`. A codec that is 10x faster but half the ratio may
  still be the wrong default for a network path.
- Peak RSS matters for embedded or memory-capped targets; `xz -T` is expensive
  here because its block size grows with the thread count.

## Limitations

- Numbers are valid only for this machine, these codec versions and this
  dataset; the report states all three.
- `xz -T` changes its block size with the thread count, so its archive bytes and
  ratio legitimately differ from a single-threaded run.
- The dataset is generated from a fixed seed and is synthetic; real payload
  entropy and record structure can change the answer.
- The skill only measures codecs already installed on the machine and reports
  the ones it skipped. It does not install packages.
- It reports `/usr/bin/time` peak RSS for the tool process; it does not measure
  page-cache or end-to-end application memory.
