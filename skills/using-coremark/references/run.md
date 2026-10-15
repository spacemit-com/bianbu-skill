# Running CoreMark and checking the result

A reportable result is two runs of the installed command: a performance run that produces the score, and a validation run that confirms the arithmetic. Both must validate.

## The two standard runs

```bash
coremark 0x0 0x0 0x66 0 7 1 2000          # performance run
coremark 0x3415 0x3415 0x66 0 7 1 2000    # validation run
```

The differences between them are only the seeds. Everything else is identical, and the same command serves both.

## Argument positions

```text
SEED1 SEED2 SEED3 ITERATIONS EXECS SEED5 SIZE
```

| Position | Value here | Meaning |
| --- | --- | --- |
| `SEED1 SEED2 SEED3` | `0x0 0x0 0x66` performance, `0x3415 0x3415 0x66` validation | Data initialization seeds. `SEED2` must equal `SEED1` for the iterations to be identical |
| `ITERATIONS` | `0` | Iterations to run. `0` sizes the run automatically to 10-100 seconds, which is the portable choice across machines of very different speed |
| `EXECS` | `7` | Which algorithms to run, as a bit mask; `7` runs all of list, matrix and state |
| `SEED5` | `1` | Unused by the standard algorithms, but occupies the position |
| `SIZE` | `2000` | Buffer size in bytes, divided among the enabled algorithms, which is why the report shows `CoreMark Size : 666` |

A pinned iteration count is machine-specific. `200000` took about 13 seconds on a SpacemiT X100; on faster hardware it can fall below the ten-second floor and become invalid. Prefer `0`, or re-check the reported time after every pinned run.

## Validity rules

1. **The run must last at least ten seconds.** Otherwise the output contains `ERROR! Must execute for at least 10 secs for a valid result!`.
2. **The validation pass must print `Correct operation validated.`** `Errors detected` means failure.
3. **Do not use the exit status.** CoreMark returns `0` in every case, including on error, so the command appearing to succeed proves nothing.

A run with too few iterations still prints its CRC values — they depend only on the data initialization, not on the iteration count — so a short run is a useful smoke test but never a reportable score.

## Expected anchors

The standard configuration produces fixed values. Use them to confirm the run is the intended one:

| Run | `seedcrc` | `crclist` | `crcmatrix` | `crcstate` |
| --- | --- | --- | --- | --- |
| Performance (`0x0 0x0 0x66`) | `0xe9f5` | `0xe714` | `0x1fd7` | `0x8e3a` |
| Validation (`0x3415 0x3415 0x66`) | `0x18f2` | `0xe3c1` | `0x0747` | `0x8d84` |

A mismatch in any of these, together with `Errors detected`, means the binary miscalculated rather than merely ran short — a genuine failure to report, not something to retry until it passes.

## Using the bundled script

`scripts/run-coremark.sh` runs both passes, checks the anchors, applies the validity rules and prints a summary. It installs nothing and changes nothing on the system.

```bash
sh scripts/run-coremark.sh                       # automatic sizing
sh scripts/run-coremark.sh -i 200000             # pinned iterations
sh scripts/run-coremark.sh -o ./coremark-logs    # keep the logs here
```

It exits non-zero when either pass fails, so a nonzero status is meaningful even though the benchmark's own is not.

## Recording the logs

Each run is already written to `$XDG_STATE_HOME/coremark/`, default `~/.local/state/coremark/`, one file per run plus a `latest.log` symlink; the command prints the path on standard error. Set `COREMARK_LOG_DIR` or `XDG_STATE_HOME` to direct them elsewhere, or pass `-o DIR` to the script.

Keep the logs with the report: they carry the compiler version, the flags and the CRC values that make the score checkable by someone else.
