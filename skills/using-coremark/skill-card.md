---
schema_version: 2
---
# Skill Card: CoreMark Benchmark Guide

## Capability

Install CoreMark from the distribution package on Bianbu and other riscv64 Linux systems, run the performance and validation passes with parameters the reporting rules accept, verify that the result is valid, and report the score together with the conditions that produced it.

## Use Cases

A user asks to benchmark a Bianbu or riscv64 board with CoreMark, to install the CoreMark package, to explain or repair a CoreMark run that failed validation or finished too quickly, or to report and compare CoreMark scores between machines or package versions.

## Inputs and Outputs

Input: The target system (riscv64, Bianbu or compatible), whether the `coremark` command is already installed, the user's consent to install the package, and any requested iteration count.

Output: A completed pair of runs (performance and validation) with their logs, a validity verdict derived from the benchmark's own output, and a report quoting the `CoreMark 1.0 : N / C [/ P] [/ M]` line with the iteration count, elapsed time, compiler flags and validation outcome.

## Dependencies

The `coremark` command from the distribution package, which installs `/usr/bin/coremark` and needs no build tools. Installing it needs `sudo` and network access to the configured archive. Reading CPU frequency for a CoreMark/MHz figure needs `lscpu` or `/proc/cpuinfo`.

## Limitations

Installs only from the configured distribution archive, and builds nothing from source: when the archive carries no `coremark` candidate, the gap is reported rather than worked around with a third-party repository, download URL or local build. Cannot fabricate, estimate or transfer a score, and reports only what the current session measured. A result is only valid when the run lasted at least ten seconds and the validation pass printed `Correct operation validated.`, and CoreMark's exit status cannot be used as a success signal. Installing packages is presented to the user for consent rather than performed unilaterally.

## Maintainer

Owner: liangjunzhao
Contact: junzhao.liang@spacemit.com
