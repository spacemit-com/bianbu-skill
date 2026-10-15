#!/bin/sh
#
# Run the CoreMark benchmark and print a validated summary.
#
# Part of the using-coremark Skill. It installs nothing and changes nothing on
# the system beyond writing its logs, and it uses the installed packaged
# command (/usr/bin/coremark), which keeps its own log and prints the path on
# standard error.
#
# Usage: run-coremark.sh [-i ITERATIONS] [-o OUTDIR]

set -eu

iterations=0
outdir=
tmpdir=

usage()
{
    cat <<'EOF'
usage: run-coremark.sh [OPTION]...

Run the CoreMark performance pass and validation pass, check both against the
documented validity rules, and print a summary.

Options:
  -i ITERATIONS  iterations to run; 0 sizes the run automatically to
                 10-100 seconds (default: 0)
  -o OUTDIR      directory for the logs (default: a fresh temporary directory)
  -h             show this help

Exit status is 0 only when both passes validated.
EOF
}

while [ $# -gt 0 ]; do
    case $1 in
        -i)
            [ $# -ge 2 ] || { echo "run-coremark.sh: -i needs a value" >&2; exit 2; }
            iterations=$2
            shift 2
            ;;
        -o)
            [ $# -ge 2 ] || { echo "run-coremark.sh: -o needs a value" >&2; exit 2; }
            outdir=$2
            shift 2
            ;;
        -h|--help)
            usage
            exit 0
            ;;
        *)
            echo "run-coremark.sh: unknown option $1" >&2
            echo "run-coremark.sh: try -h" >&2
            exit 2
            ;;
    esac
done

# The installed command is the only supported runner. Report the gap rather
# than looking for something else to run.
if ! command -v coremark >/dev/null 2>&1; then
    echo "run-coremark.sh: the coremark command is not installed." >&2
    echo "run-coremark.sh: install it with 'sudo apt install coremark'." >&2
    echo "run-coremark.sh: see references/install.md" >&2
    exit 1
fi
runner=$(command -v coremark)

[ -n "$outdir" ] || outdir=$(mktemp -d)
mkdir -p "$outdir"
tmpdir=$(mktemp -d)
trap 'rm -rf "$tmpdir"' EXIT HUP INT TERM

perf_log=$outdir/run1-performance.log
vali_log=$outdir/run2-validation.log

# Both passes use the standard parameters; only the seeds differ. An
# iteration count of 0 lets the benchmark size itself to the machine.
"$runner" 0x0 0x0 0x66 "$iterations" 7 1 2000 >"$perf_log" 2>"$tmpdir/perf.err" || true
"$runner" 0x3415 0x3415 0x66 "$iterations" 7 1 2000 >"$vali_log" 2>"$tmpdir/vali.err" || true

fail=0

# Check one pass. The exit status of CoreMark itself is useless (always 0),
# so validity is decided from the output, including the CRC anchors that are
# fixed for the standard configuration.
check_pass()
{
    log=$1
    label=$2
    seedcrc=$3
    crclist=$4
    crcmatrix=$5
    crcstate=$6
    ok=1

    if [ ! -s "$log" ]; then
        echo "run-coremark.sh: $label produced no output ($log)" >&2
        return 1
    fi

    if grep -q 'Must execute for at least 10 secs' "$log"; then
        echo "run-coremark.sh: $label ran for less than ten seconds and is not reportable" >&2
        ok=0
    fi
    if grep -q 'Errors detected' "$log"; then
        echo "run-coremark.sh: $label reported errors:" >&2
        grep -E 'ERROR|Errors detected' "$log" >&2 || true
        ok=0
    fi
    if ! grep -q 'Correct operation validated' "$log"; then
        echo "run-coremark.sh: $label did not print 'Correct operation validated.'" >&2
        ok=0
    fi

    for pair in "seedcrc:$seedcrc" "crclist:$crclist" "crcmatrix:$crcmatrix" "crcstate:$crcstate"; do
        key=${pair%%:*}
        want=${pair#*:}
        if ! grep -q "^\(\[0\]\)\?$key[[:space:]]*: $want" "$log"; then
            echo "run-coremark.sh: $label unexpected $key (expected $want)" >&2
            ok=0
        fi
    done

    [ "$ok" -eq 1 ]
}

check_pass "$perf_log" "performance run" 0xe9f5 0xe714 0x1fd7 0x8e3a || fail=1
check_pass "$vali_log" "validation run" 0x18f2 0xe3c1 0x0747 0x8d84 || fail=1

# Field labels contain a slash ("Iterations/Sec"), so use a delimiter that
# cannot appear in them.
field()
{
    sed -n "s|^$2[[:space:]]*:[[:space:]]*||p" "$1" | head -1
}

score=$(sed -n 's/^CoreMark 1\.0 : //p' "$perf_log" | head -1)
iters_sec=$(field "$perf_log" 'Iterations/Sec')
total_time=$(field "$perf_log" 'Total time (secs)')
iterations_run=$(field "$perf_log" 'Iterations')
compiler=$(field "$perf_log" 'Compiler version')
flags=$(field "$perf_log" 'Compiler flags')
memory=$(field "$perf_log" 'Memory location')
vali_seedcrc=$(field "$vali_log" 'seedcrc')

wrapper_log=
if [ -s "$tmpdir/perf.err" ]; then
    wrapper_log=$(sed -n 's/.*log saved to //p' "$tmpdir/perf.err" | head -1)
fi

echo
echo "=== CoreMark summary ==="
echo "runner         : $runner"
if [ "$iterations" -eq 0 ]; then
    echo "iterations     : $iterations_run (sized automatically)"
else
    echo "iterations     : $iterations_run (requested $iterations)"
fi
echo "total time     : ${total_time:-unknown} s"
if [ "$fail" -eq 0 ]; then
    echo "score          : ${iters_sec:-unknown} iterations/sec"
else
    echo "score          : ${iters_sec:-unknown} iterations/sec (NOT VALID - do not report)"
fi
echo "compiler       : ${compiler:-unknown}"
echo "compiler flags : ${flags:-unknown}"
# This port ships a placeholder in MEM_LOCATION; the memory field of the
# report line is the meaningful one. A failed run prints no report line.
case $memory in
    "")
        echo "memory         : unknown" ;;
    "Please put data memory location here"*)
        if [ -n "$score" ]; then
            echo "memory         : not set by this port; the report line records: ${score##* / }"
        else
            echo "memory         : not set by this port (no report line was printed)"
        fi ;;
    *)
        echo "memory         : $memory" ;;
esac
if [ "$fail" -eq 0 ]; then
    echo "validation     : passed (seedcrc $vali_seedcrc)"
else
    echo "validation     : FAILED - the result is not reportable"
fi
if [ -n "$score" ]; then
    echo "report         : CoreMark 1.0 : $score"
fi
echo "logs           : $perf_log"
echo "                 $vali_log"
if [ -n "$wrapper_log" ]; then
    echo "                 $wrapper_log (kept by the packaged command)"
fi

exit "$fail"
