# Reference

Background for running and interpreting the CPU compression benchmark.

## Dataset categories

`gen_dataset.sh` builds the input from a fixed seed, so the same seed always
produces the same bytes and two runs are comparable.

| Category | Shape | What it exposes |
| --- | --- | --- |
| `text` | English prose sentences | dictionary-heavy, high ratio, fast for LZ codecs |
| `source` | C-like declarations and comments | mixed structure and identifiers, realistic for build artifacts |
| `json` | one JSON record per line | very repetitive at the record level; favours zstd and gzip |
| `log` | timestamped log lines | repetitive prefix with a variable numeric tail |
| `binary` | pseudo-random bytes | incompressible floor; shows the per-codec overhead |
| `mixed` | cyclic mix of the above | default; avoids tuning for one shape |

Entropy is lowest in `text` and highest in `binary`. A codec that looks strong
on `text` alone has not been tested for real workloads.

## Threading model per codec

| Codec | Parallel mode | Notes |
| --- | --- | --- |
| `gzip` | none | single-threaded; `threads_applied` stays 1 |
| `pigz` | `-p N` | parallel gzip implementation, independent blocks |
| `zstd` | `--threads=N` | parallel across independent frames/blocks |
| `xz` | `-T N` | parallel filter with a larger block size; output size and ratio depend on the thread count |
| `bzip2` | none | single-threaded; `threads_applied` stays 1 |

`--threads 0` means one worker per logical CPU. For codecs without a parallel
mode the requested count is recorded and the applied count stays 1, so the
report shows the applied value with the requested one in parentheses rather
than a misleading number.

## Run cost

`benchmark.sh` defaults to one timed pass per configuration over 128 MiB, so a
default run over five codecs finishes in roughly a minute. Cost is roughly
proportional to `configurations x dataset size x repeats`, and slow codecs
dominate: `xz` at level 6 takes about 600 times longer to compress 1 GiB than
`zstd` at level 3, so adding `xz` to a level sweep is the expensive choice.

| Knob | Effect on run time | When it is worth paying |
| --- | --- | --- |
| `--repeats N` | xN | you need the spread, or two codecs are within noise of each other |
| `--threads "1,0"` | x2 | you want to know whether parallelism pays here |
| `--size-mib N` | linear | the dataset must exceed L3, or the payload is large |
| extra levels | x levels | the level/ratio curve is the actual question |
| extra codecs | x codecs | only when that codec is a real candidate |

A single pass gives throughput, ratio, CPU time, peak memory and round-trip
verification, all of which are exact for that run. What it cannot give is the
run-to-run spread, so `Wall spread` reads `0.00%` by construction; do not
mistake that for perfect stability. Determinism likewise reads `n/a` with one
pass, because one archive cannot be compared with itself.

## Keeping a run directory small

A run writes the dataset plus one archive per configuration, which is easily
several hundred megabytes. Once the numbers are reviewed, prune the regenerable
files:

```bash
scripts/prune.sh --run-dir ./benchmark-run
```

It writes `artifacts-manifest.sha256` with the dataset and artifact hashes
first, then deletes them, marks `meta.json` as pruned and re-renders the report
so the integrity section explains the missing files. The report, the summary and
the raw rows are never touched, and the dataset can be rebuilt from its seed
while any artifact can be rebuilt from the dataset plus its recorded codec,
level and thread count. Add `--keep-dataset` to retain the input file.

## Measurement definitions

- `wall_ms` brackets the process: it includes fork/exec and any scheduling
  delay, which is what a pipeline actually pays.
- `tool_seconds` and `rss_max_kib` come from `/usr/bin/time` and describe the
  tool process itself, excluding the wrapper.
- Compression throughput uses `in_bytes`; decompression throughput uses the same
  `in_bytes`, because decompression produces the original payload back.
- The ratio is `in_bytes / out_bytes` from the same run, never a quoted spec
  number.
- Decompression is timed with output to `/dev/null`; verification then decodes to
  a file and compares with `cmp`, so a fast-but-wrong codec cannot pass.
- Determinism compares the SHA-256 of every repeat at one configuration. A
  `false` value at equal level and thread count is a real finding.

## Interpreting a report

1. Check `Verified` first. Any row without a passing round trip is not a result.
2. Compare CPU MiB/s between codecs at the same thread count; compare wall MiB/s
   when the question is "what does the user wait for".
3. Read spread. With the default single pass it is `0.00%` and tells you
   nothing; with `--repeats 2+`, a spread above roughly 10% on a warm page cache
   means the host was busy or the clocks moved, so rerun before concluding.
4. Use the cost model table to price a 1 GiB transfer, then weigh it against the
   bytes-on-wire column for the network or storage path.
5. Quote the environment table with the numbers. A throughput figure without the
   CPU, kernel, governor and codec version is not reproducible evidence.

## Environment caveats worth recording

- A governor other than `performance` and an enabled turbo let clocks drift
  between repeats; the report states both.
- On a `tmpfs` run directory the archive writes never reach the disk; on a real
  filesystem the measured time includes write I/O.
- A dataset smaller than the last-level cache measures cache speed, not memory
  bandwidth. The report prints L3 size so the reader can tell which case it is.
- CPU affinity (`taskset`) reduces migration noise but changes which cores are
  used; record it in the report, as the run does.

## Troubleshooting

| Symptom | Cause | Fix |
| --- | --- | --- |
| A codec is missing from the report | its binary is not installed | install it or accept the skip; the report names skipped codecs |
| `failures` is non-zero and exit status is 4 | one configuration could not run | read `raw/measurements.jsonl` for the failing row, fix the codec invocation, rerun |
| Throughput far below expectation | host busy, or a few-core quota | rerun on an idle machine; check the load average and container CPU limits |
| Same codec, very different numbers between runs | governor/turbo or thermal drift | pin affinity, raise repeats, or set the governor to `performance` |
| `xz` archive size changes with `--threads` | expected: block size follows the thread count | compare `xz` only at equal thread counts |
| Peak RSS is `n/a` | `/usr/bin/time` unavailable | install GNU time; wall-clock and CPU time still work |
| `Wall spread` is `0.00%` everywhere | the run used the default single pass | pass `--repeats 3` or more if spread matters |
