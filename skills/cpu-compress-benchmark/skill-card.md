---
schema_version: 2
---
# Skill Card: CPU Compression Benchmark
## Capability

Benchmark CPU compression and decompression on the local machine for gzip, pigz, zstd, xz and bzip2. It times compression and decompression separately at pinned levels and thread counts, records compression ratio, wall-clock and CPU throughput, peak resident memory and artifact hashes, verifies each archive by a byte-for-byte round trip, and renders a structured Markdown report next to its machine-readable evidence.

## Use Cases

- Compare compressors or levels before choosing a default for backups, build artifacts, logs or transfers.
- Check whether parallel modes (pigz, `zstd -T`, `xz -T`) actually improve throughput on this machine.
- Quantify the ratio/CPU/memory tradeoff of a configuration for a review, a bug report or a release decision.
- Produce a reproducible benchmark report with raw measurements a reviewer can re-check.

## Inputs and Outputs

Input: run parameters — codec list, levels, thread counts, dataset size and category, repeats, seed, optional CPU affinity, output directory. All are optional: the defaults are a 128 MiB mixed dataset, each codec's own level, all logical CPUs and a single timed pass, which completes in about a minute.

Output: a run directory containing `report.md` (the deliverable), `summary.json` and `summary.csv` (per-configuration medians), `env.json` and `env-snapshot.txt` (machine and toolchain facts), `raw/measurements.jsonl` (one record per timed phase per repeat), and `artifacts/` with the compressed outputs and their SHA-256 hashes. `prune.sh` can then delete the regenerable dataset and archives, keeping `artifacts-manifest.sha256` and the measured numbers intact.

## Dependencies

Requires bash, Python 3, coreutils (`date`, `stat`, `nproc`, `sha256sum`, `cmp`) and GNU `/usr/bin/time`. At least one measured codec must be installed: gzip, pigz, zstd, xz or bzip2. Missing codecs are skipped and named in the report instead of failing the run. No network access and no third-party Python packages.

## Limitations

- Results are valid only for the machine, codec versions and dataset reported in the same run.
- The dataset is synthetic and generated from a fixed seed; real payload entropy and record structure can change the outcome.
- The default single pass reports no run-to-run spread; use `--repeats 2` or more when noise or a close comparison matters.
- `xz -T` selects its block size from the thread count, so its archive bytes and ratio legitimately differ between thread counts.
- Reported memory is the peak resident set of the tool process, not page cache or full application memory.
- The skill does not install packages, does not compress user data and does not compare separate machines with each other.

## Maintainer

Owner: liangjunzhao
Contact: junzhao.liang@spacemit.com
