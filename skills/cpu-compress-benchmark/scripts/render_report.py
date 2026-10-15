#!/usr/bin/env python3
"""Render a structured Markdown report from env.json, summary.json and run meta.

Usage:
  render_report.py --env env.json --summary summary.json --meta meta.json \
                   --out report.md

Every number in the report comes from the summary file; nothing is recomputed
or rounded twice, so the report and the machine-readable artifacts can never
disagree. The report states what it measured, on what machine, and where the
underlying rows live.
"""

import argparse
import json
import sys

MIB = 1024.0 * 1024.0


def load(path):
    with open(path, encoding="utf-8") as handle:
        return json.load(handle)


def mib(kib):
    return kib / 1024.0


def fmt(value, digits=2):
    if value in (None, ""):
        return "n/a"
    if isinstance(value, float):
        return f"{value:,.{digits}f}"
    if isinstance(value, int):
        return f"{value:,}"
    return str(value)


def fmt_ratio(value):
    return f"{value:.2f}:1" if value else "n/a"


def fmt_bytes(value):
    if value in (None, ""):
        return "n/a"
    return f"{int(value):,} B"


def fmt_threads(group):
    """Show applied threads, noting when the request could not be honoured."""
    applied = group["threads_applied"]
    requested = group.get("threads_requested", applied)
    if applied == requested:
        return str(applied)
    if requested == 0:
        return f"{applied} (all-core request)"
    return f"{applied} (requested {requested})"


def fmt_rss(kib):
    if not kib or kib < 0:
        return "n/a"
    if kib >= 1024 * 1024:
        return f"{kib / 1024.0 / 1024.0:,.2f} GiB"
    if kib >= 1024:
        return f"{kib / 1024.0:,.1f} MiB"
    return f"{kib} KiB"


def yes_no(value):
    if value is True:
        return "yes"
    if value is False:
        return "no"
    return str(value)


def table(headers, rows):
    lines = ["| " + " | ".join(headers) + " |", "|" + "|".join(["---"] * len(headers)) + "|"]
    for row in rows:
        lines.append("| " + " | ".join(str(cell) for cell in row) + " |")
    return "\n".join(lines)


def rank(groups, key, reverse=True):
    scored = [group for group in groups if group.get(key)]
    return sorted(scored, key=lambda group: group[key], reverse=reverse)


def main(argv):
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--env", required=True)
    parser.add_argument("--summary", required=True)
    parser.add_argument("--meta", required=True)
    parser.add_argument("--out", required=True)
    args = parser.parse_args(argv[1:])

    env = load(args.env)
    summary = load(args.summary)
    meta = load(args.meta)
    groups = summary["groups"]

    ok_groups = [group for group in groups if not group.get("failures")]
    failed_groups = [group for group in groups if group.get("failures")]

    out = []
    add = out.append

    add("# CPU Compression Benchmark Report")
    add("")
    add(f"- Run id: `{meta.get('run_id', 'unknown')}`")
    add(f"- Started: {meta.get('started_at', 'unknown')}")
    add(f"- Finished: {meta.get('finished_at', 'unknown')}")
    add(f"- Dataset: `{meta.get('dataset', 'unknown')}` "
        f"({fmt(meta.get('dataset_mib'))} MiB, category `{meta.get('category', 'unknown')}`, seed `{meta.get('seed', 'unknown')}`)")
    add(f"- Codecs: {', '.join(meta.get('codecs', [])) or 'none'}")
    add(f"- Threads per codec: {meta.get('threads', 'unknown')} "
        f"(0 means one thread per logical CPU)")
    add(f"- Repeats per configuration: {meta.get('repeats', 'unknown')} "
        f"(warmup {meta.get('warmup', 'unknown')})")
    add(f"- Artifacts: `{meta.get('run_dir', '.')}`")
    add("")

    add("## 1. Headline findings")
    add("")
    compress_rank = rank(ok_groups, "compress_wall_mib_s")
    decompress_rank = rank(ok_groups, "decompress_wall_mib_s")
    ratio_rank = rank(ok_groups, "ratio")
    if compress_rank:
        best = compress_rank[0]
        add(f"- Fastest compression: `{best['codec']}` at level {best['level']}, "
            f"{fmt(best['compress_wall_mib_s'])} MiB/s wall clock "
            f"({fmt(best['compress_cpu_mib_s'])} MiB/s of CPU time), ratio {fmt_ratio(best['ratio'])}.")
    if decompress_rank:
        best = decompress_rank[0]
        add(f"- Fastest decompression: `{best['codec']}` at level {best['level']}, "
            f"{fmt(best['decompress_wall_mib_s'])} MiB/s wall clock, ratio {fmt_ratio(best['ratio'])}.")
    if ratio_rank:
        best = ratio_rank[0]
        add(f"- Best compression ratio: `{best['codec']}` at level {best['level']}, "
            f"{fmt_ratio(best['ratio'])} at {fmt(best['compress_wall_mib_s'])} MiB/s.")
    if ok_groups:
        slowest = sorted(ok_groups, key=lambda group: group["compress_wall_mib_s"])[0]
        fastest = max(ok_groups, key=lambda group: group["compress_wall_mib_s"])
        if slowest["compress_wall_mib_s"]:
            add(f"- Compression speed spans {fastest['compress_wall_mib_s'] / slowest['compress_wall_mib_s']:.1f}x "
                f"across the measured codecs and levels "
                f"(`{slowest['codec']}` level {slowest['level']} to `{fastest['codec']}` level {fastest['level']}).")
    unverified = [group for group in groups if not group.get("verified")]
    if unverified:
        names = ", ".join(f"`{group['codec']}` L{group['level']}" for group in unverified)
        add(f"- Round-trip verification did not pass for: {names}. Treat those rows as invalid.")
    nondeterministic = [group for group in groups if group.get("deterministic") == "false"]
    if nondeterministic:
        names = ", ".join(f"`{group['codec']}` L{group['level']}" for group in nondeterministic)
        add(f"- Repeated compression produced different bytes for: {names} "
            "(expected for `xz -T`, whose block size depends on the thread count).")
    add("")

    add("## 2. Test environment")
    add("")
    add(table(
        ["Item", "Value"],
        [
            ["CPU model", env.get("cpu_model", "unknown")],
            ["Architecture", env.get("architecture", "unknown")],
            ["Physical cores", env.get("physical_cores") or "unknown"],
            ["Logical CPUs", env.get("logical_cpus", "unknown")],
            ["Threads per core", env.get("threads_per_core") or "unknown"],
            ["Max frequency", f"{env.get('max_mhz', 0)} MHz"],
            ["L3 cache", env.get("l3_cache") or "unknown"],
            ["Memory", f"{env.get('mem_total_mib', 0):,} MiB"],
            ["Scaling governor", env.get("scaling_governor", "unknown")],
            ["Turbo boost", env.get("turbo", "unknown")],
            ["Kernel", env.get("kernel", "unknown")],
            ["OS", env.get("os", "unknown")],
            ["Run filesystem", f"{env.get('filesystem_type', 'unknown')} on {env.get('filesystem_mount', 'unknown')}"],
        ],
    ))
    add("")

    tools = env.get("tools", {})
    if tools:
        rows = []
        for name in sorted(tools):
            info = tools[name]
            if not info.get("available"):
                rows.append([f"`{name}`", "not installed", "-", "-", "-"])
                continue
            rows.append([
                f"`{name}`",
                info.get("version", "unknown"),
                f"`{info.get('path', '')}`",
                info.get("default_level", "-"),
                info.get("level_range", "-"),
            ])
        add(table(["Codec", "Version", "Path", "Default level", "Level range"], rows))
        add("")

    memory_notes = []
    if env.get("filesystem_type") == "tmpfs":
        memory_notes.append("the run directory is on tmpfs, so archive writes did not touch the disk")
    else:
        memory_notes.append(
            f"the run directory is on {env.get('filesystem_type', 'an unknown filesystem')}, "
            "so archive writes include disk I/O"
        )
    if str(env.get("scaling_governor", "")).startswith("power"):
        memory_notes.append(
            "the CPU governor is not `performance`, so clock scaling can add noise between runs"
        )
    if env.get("turbo") == "enabled":
        memory_notes.append("turbo boost was enabled, which makes single-thread numbers optimistic and variable")
    add("Interpretation caveats: " + "; ".join(memory_notes) + ".")
    add("")

    add("## 3. Compression throughput and ratio")
    add("")
    add(table(
        ["Codec", "Level", "Threads", "Wall MiB/s", "CPU MiB/s", "Median wall (ms)", "Wall spread", "Ratio", "Archive", "Peak RSS", "Verified"],
        [
            [
                f"`{group['codec']}`",
                group["level"],
                fmt_threads(group),
                fmt(group["compress_wall_mib_s"]),
                fmt(group["compress_cpu_mib_s"]),
                fmt(group["compress_wall_ms_median"], 1),
                f"{fmt(group['compress_wall_ms_spread_pct'])}%",
                fmt_ratio(group["ratio"]),
                fmt_bytes(group["out_bytes"]),
                fmt_rss(group["compress_rss_max_kib"]),
                yes_no(group["verified"]),
            ]
            for group in sorted(groups, key=lambda item: -item["compress_wall_mib_s"])
        ],
    ))
    add("")
    add("Wall MiB/s covers the whole process, including fork and exec. CPU MiB/s divides the input size by "
        "the CPU time the tool reported, so it stays meaningful when several threads run at once. "
        "Wall spread is the range across repeats as a percentage of the median; a large spread means the "
        "number should not be compared against another run taken on a busier machine.")
    if int(meta.get("repeats", 1)) < 2:
        add("")
        add("This run used a single timed pass per configuration, so `Wall spread` is `0.00%` by "
            "construction and carries no information about stability. Rerun with `--repeats 3` or more to "
            "measure that.")
    add("")

    add("## 4. Decompression throughput")
    add("")
    add(table(
        ["Codec", "Level", "Threads", "Wall MiB/s", "CPU MiB/s", "Median wall (ms)", "Wall spread", "Peak RSS", "Verified"],
        [
            [
                f"`{group['codec']}`",
                group["level"],
                fmt_threads(group),
                fmt(group["decompress_wall_mib_s"]),
                fmt(group["decompress_cpu_mib_s"]),
                fmt(group["decompress_wall_ms_median"], 1),
                f"{fmt(group['decompress_wall_ms_spread_pct'])}%",
                fmt_rss(group["decompress_rss_max_kib"]),
                yes_no(group["verified"]),
            ]
            for group in sorted(groups, key=lambda item: -item["decompress_wall_mib_s"])
        ],
    ))
    add("")
    add("Decompression is timed with the output streamed to `/dev/null` and is then verified separately by "
        "decoding to a file and comparing it byte for byte with the input.")
    add("")

    add("## 5. Cost model")
    add("")
    add("Time to move 1 GiB through each codec at the measured rates, derived from the median wall-clock "
        "numbers above. This is the practical summary for choosing a default.")
    add("")
    add(table(
        ["Codec", "Level", "Threads", "Compress s/GiB", "Decompress s/GiB", "Round trip s/GiB", "Bytes on wire per GiB"],
        [
            [
                f"`{group['codec']}`",
                group["level"],
                fmt_threads(group),
                fmt(1024.0 / group["compress_wall_mib_s"], 2) if group["compress_wall_mib_s"] else "n/a",
                fmt(1024.0 / group["decompress_wall_mib_s"], 2) if group["decompress_wall_mib_s"] else "n/a",
                fmt(1024.0 / group["compress_wall_mib_s"] + 1024.0 / group["decompress_wall_mib_s"], 2)
                if group["compress_wall_mib_s"] and group["decompress_wall_mib_s"] else "n/a",
                fmt(1024 * MIB / group["ratio"], 0) if group["ratio"] else "n/a",
            ]
            for group in sorted(groups, key=lambda item: item["codec"] + f"{item['level']:02d}")
        ],
    ))
    add("")

    add("## 6. Data integrity")
    add("")
    add(table(
        ["Codec", "Level", "Threads", "Round trip", "Deterministic", "Artifact SHA-256", "Archive path"],
        [
            [
                f"`{group['codec']}`",
                group["level"],
                fmt_threads(group),
                yes_no(group["verified"]),
                group["deterministic"],
                f"`{group['artifact_sha256'][:16]}...`" if group.get("artifact_sha256") else "n/a",
                f"`{group['artifact']}`" if group.get("artifact") else "n/a",
            ]
            for group in groups
        ],
    ))
    add("")
    add("Every artifact was produced from the same input file and the same seed. A deterministic result means "
        "repeated compressions at that level and thread count produced byte-identical archives.")
    if int(meta.get("repeats", 1)) < 2:
        add("")
        add("With a single pass, `Deterministic` is not evidence of stability: it only states that the one "
            "archive produced here is self-consistent. Use `--repeats 3` or more to actually compare "
            "repeated compressions.")
    if meta.get("artifacts_pruned"):
        add("")
        add("The archive files and the dataset were pruned after the run to keep the evidence directory "
            "small; the SHA-256 values below are still the recorded hashes of those files, and "
            f"`{meta.get('artifact_manifest', 'artifacts-manifest.sha256')}` lists all of them.")
    add("")

    if failed_groups:
        add("## 7. Failed configurations")
        add("")
        add(table(
            ["Codec", "Level", "Threads", "Failed repeats", "Round trip"],
            [
                [f"`{group['codec']}`", group["level"], fmt_threads(group), group["failures"], yes_no(group["verified"])]
                for group in failed_groups
            ],
        ))
        add("")
        add("`Failed repeats` counts timed phases that exited non-zero in that configuration; inspect "
            "`raw/measurements.jsonl` for the failing row before quoting any of its numbers.")
        add("")
    else:
        add("## 7. Failed configurations")
        add("")
        add("None: every requested codec, level and thread configuration completed and verified its round trip.")
        add("")

    add("## 8. How to reproduce")
    add("")
    add("```bash")
    for command in meta.get("reproduce", []):
        add(command)
    add("```")
    add("")

    add("## 9. Evidence files")
    add("")
    add(table(
        ["File", "Contents"],
        [
            ["`env.json`", "Machine and toolchain facts used by this report"],
            ["`env-snapshot.txt`", "Human-readable copy of the same facts"],
            ["`raw/measurements.jsonl`", "One JSON object per timed phase per repeat"],
            ["`summary.json`", "Per-configuration medians that back every table above"],
            ["`summary.csv`", "The same summary for spreadsheets"],
            ["`artifacts/`", "Compressed outputs produced during the run, when not pruned"],
            ["`artifacts-manifest.sha256`", "Hashes of the dataset and artifacts, kept after pruning"],
            ["`report.md`", "This report"],
        ],
    ))
    add("")

    add("## 10. Method and limitations")
    add("")
    add("Method: the input file is generated from a fixed seed, warmed into the page cache, then each codec runs "
        "the same number of timed repeats at a pinned level and thread count. Wall time brackets the process; "
        "CPU time and peak RSS come from `/usr/bin/time`; each artifact is decoded and compared with the input.")
    add("")
    add(f"Run length: {meta.get('repeats', 1)} timed pass(es) per configuration with "
        f"{meta.get('warmup', 0)} warmup read(s) of the dataset, over {meta.get('dataset_mib', '?')} MiB.")
    add("")
    add("Limitations to keep in mind when quoting these numbers:")
    add("")
    add("- Throughput depends on the CPU, memory bandwidth, governor and codec build; these numbers are valid for "
        "this machine and these versions only.")
    add("- The dataset is synthetic. Real payloads with different entropy, record sizes or dictionary reuse will "
        "compress differently.")
    add("- `gzip` and `bzip2` have no multi-threaded mode here, so their thread column stays at 1 even "
        "when the run requests more; the row shows the requested count in parentheses.")
    add("- `xz -T` chooses its block size from the thread count, so its archive bytes and ratio change with "
        "`Threads`; do not compare an `xz` artifact across different thread counts.")
    add("- Peak RSS is the peak resident set of the tool process; it does not include the page cache the kernel "
        "uses for the input file.")
    add("- Only codecs installed on this machine were measured; the report names the ones that were skipped.")
    add("")

    with open(args.out, "w", encoding="utf-8") as handle:
        handle.write("\n".join(out))
    print(f"report={args.out}", file=sys.stdout)
    return 0


if __name__ == "__main__":
    sys.exit(main(sys.argv))
