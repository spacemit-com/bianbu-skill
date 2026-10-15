# Reporting a CoreMark result

Report the line the benchmark printed, plus the conditions that produced it. A bare number is not a result.

## The reportable line

The performance run prints it; the validation run does not.

```text
CoreMark 1.0 : N / C [/ P] [/ M]
```

| Field | Meaning | Where it comes from |
| --- | --- | --- |
| `N` | Iterations per second | The `Iterations/Sec` line; this is the score |
| `C` | Compiler and flags | The `Compiler version` and `Compiler flags` lines |
| `P` | Memory configuration | The `Memory location` line, or the build's memory method |
| `M` | Parallel execution and context count | Present only when more than one context was used |

On this package the `Memory location` line prints the port's placeholder text rather than a real value; the memory field of the report line itself (`Heap`) is the meaningful one.

Example of a complete, honest report:

```text
CoreMark 1.0 : 13705.201124 / GCC15.2.0 -O2 -march=rv64gc -lrt / Heap

board:             SpacemiT X100 (riscv64), Bianbu 4.0.7
iterations:        200000 (pinned)
total time:        14.593 s
validation run:    passed (seedcrc 0x18f2)
logs:              ~/.local/state/coremark/coremark-20261012T113000-12345.log
```

## What must accompany the score

1. **The board and distribution**, since a score measures a specific machine.
2. **The iteration count**, or that it was sized automatically.
3. **The reported time**, which is what shows the run cleared the ten-second floor.
4. **The compiler and flags** exactly as printed, because they are part of the result and the only clue to whether two scores are comparable.
5. **The validation outcome.** Report a score only when the validation run printed `Correct operation validated.`

Never average runs, never drop an inconvenient one, and never present a run that failed validation.

## CoreMark/MHz

Divide by the clock frequency the benchmark actually ran at, and say how the frequency was obtained:

```bash
cat /sys/devices/system/cpu/cpu0/cpufreq/scaling_cur_freq 2>/dev/null   # kHz, if cpufreq is present
lscpu | grep -i mhz
cat /proc/cpuinfo | grep -i mhz
```

Do not divide by a nominal maximum. Frequencies move with DVFS, thermal limits and the governor, so a frequency-normalized figure is only meaningful with the observed frequency recorded next to it. If the frequency cannot be measured, report the raw score and say so.

## When the memory parameter may be omitted

`P` may be omitted when all data was allocated on the heap in RAM, and **must not** be omitted when reporting CoreMark/MHz. With all three algorithms enabled and a 2000-byte buffer, the report reads `Heap`.

## Where the logs live

Every run is written to `$XDG_STATE_HOME/coremark/`, default `~/.local/state/coremark/`: one file per run named with a timestamp and the process ID, plus a `latest.log` symlink to the most recent. The command prints the path on standard error.

Override the location with `COREMARK_LOG_DIR` or `XDG_STATE_HOME` when a defined directory is wanted. Keep the logs with the report — they carry the seed CRCs and flags that let someone else check the run.

## Comparing two results

Compare only runs that differ in exactly one thing. Two scores are not comparable when the package version, the compiler flags, the tuning, the iteration sizing or the memory configuration differ; the `Compiler flags` line is what tells you which build produced a number.
