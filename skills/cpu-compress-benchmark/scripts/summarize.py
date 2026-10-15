#!/usr/bin/env python3
"""Aggregate raw JSONL measurements into summary.json and summary.csv.

Usage:
  summarize.py <measurements.jsonl> <summary.json> <summary.csv>

Per (codec, level, threads_applied, phase) group the script reports the median
and the spread across repeats of:
  wall_ms          wall-clock milliseconds around the process
  tool_seconds     /usr/bin/time reported user+system+wall for the process
  wall_mib_s       throughput from wall_ms
  cpu_mib_s        throughput from tool_seconds
  cpu_time_s       tool_seconds
  rss_max_kib      peak resident set of the tool process
  ratio            in_bytes / out_bytes
  out_bytes        archive size

Determinism and the decompression round-trip are carried over from the
verification row of the same codec/level/threads group. Groups with a failed
repeat are kept in the output and flagged, so a failure is visible in the
report instead of silently dropped.
"""

import csv
import json
import statistics
import sys
from collections import defaultdict

MIB = 1024.0 * 1024.0


def median(values):
    return statistics.median(values) if values else 0.0


def spread(values):
    if len(values) < 2:
        return 0.0
    return max(values) - min(values)


def relative_spread(values):
    if len(values) < 2:
        return 0.0
    center = statistics.median(values)
    if center == 0:
        return 0.0
    return spread(values) / center * 100.0


def load(path):
    rows = []
    with open(path, encoding="utf-8") as handle:
        for number, line in enumerate(handle, 1):
            line = line.strip()
            if not line:
                continue
            try:
                rows.append(json.loads(line))
            except json.JSONDecodeError as error:
                raise SystemExit(f"{path}:{number}: invalid JSON: {error}") from None
    return rows


def main(argv):
    if len(argv) != 4:
        print(__doc__, file=sys.stderr)
        return 2
    raw_path, json_path, csv_path = argv[1:]

    rows = load(raw_path)
    measurements = [row for row in rows if row.get("kind") == "measurement"]
    verifications = [row for row in rows if row.get("kind") == "verification"]
    if not measurements:
        print(f"summarize.py: no measurement rows in {raw_path}", file=sys.stderr)
        return 2

    groups = defaultdict(list)
    for row in measurements:
        key = (row["codec"], row["level"], row.get("threads", 0), row["threads_applied"])
        groups[key].append(row)

    verify_by_key = {
        (row["codec"], row["level"], row.get("threads", 0), row["threads_applied"]): row
        for row in verifications
    }

    summaries = []
    for key in sorted(groups, key=lambda item: (item[0], item[1], item[2], item[3])):
        codec, level, threads_requested, threads_applied = key
        rows_here = groups[key]
        compress = [row for row in rows_here if row.get("phase") == "compress" and row.get("status") == "ok"]
        decompress = [row for row in rows_here if row.get("phase") == "decompress" and row.get("status") == "ok"]
        failed = [row for row in rows_here if row.get("status") != "ok"]

        in_bytes = rows_here[0].get("in_bytes", 0)
        data_mib = in_bytes / MIB
        out_bytes = median([row.get("out_bytes", 0) for row in compress]) if compress else 0

        entry = {
            "codec": codec,
            "tool": rows_here[0].get("tool", ""),
            "level": level,
            "threads_requested": threads_requested,
            "threads_applied": threads_applied,
            "thread_note": rows_here[0].get("thread_note", ""),
            "label": rows_here[0].get("label", "default"),
            "dataset": rows_here[0].get("dataset", ""),
            "in_bytes": in_bytes,
            "data_mib": round(data_mib, 4),
            "out_bytes": out_bytes,
            "ratio": round(in_bytes / out_bytes, 3) if out_bytes else 0.0,
            "compress_repeats_ok": len(compress),
            "decompress_repeats_ok": len(decompress),
            "failures": len(failed),
            "verified": bool(verify_by_key.get(key, {}).get("verified") == "true"),
            "deterministic": verify_by_key.get(key, {}).get("deterministic", "n/a"),
            "artifact": verify_by_key.get(key, {}).get("artifact", ""),
            "artifact_sha256": verify_by_key.get(key, {}).get("artifact_sha256", ""),
        }

        if compress:
            wall = [row.get("wall_ms", 0) for row in compress]
            tool = [row.get("tool_seconds", 0) for row in compress]
            rss = [row.get("rss_max_kib", -1) for row in compress]
            entry["compress_wall_ms_median"] = round(median(wall), 1)
            entry["compress_wall_ms_spread"] = round(spread(wall), 1)
            entry["compress_wall_ms_spread_pct"] = round(relative_spread(wall), 2)
            entry["compress_cpu_time_s_median"] = round(median(tool), 4)
            entry["compress_wall_mib_s"] = round(data_mib / (median(wall) / 1000.0), 2) if median(wall) else 0.0
            entry["compress_cpu_mib_s"] = round(data_mib / median(tool), 2) if median(tool) else 0.0
            entry["compress_rss_max_kib"] = int(median(rss))
            entry["compress_cpu_seconds_per_mib"] = round(median(tool) / data_mib, 6) if data_mib else 0.0
        else:
            for field in (
                "compress_wall_ms_median", "compress_wall_ms_spread", "compress_wall_ms_spread_pct",
                "compress_cpu_time_s_median", "compress_wall_mib_s", "compress_cpu_mib_s",
                "compress_rss_max_kib", "compress_cpu_seconds_per_mib",
            ):
                entry[field] = 0

        if decompress:
            wall = [row.get("wall_ms", 0) for row in decompress]
            tool = [row.get("tool_seconds", 0) for row in decompress]
            rss = [row.get("rss_max_kib", -1) for row in decompress]
            entry["decompress_wall_ms_median"] = round(median(wall), 1)
            entry["decompress_wall_ms_spread"] = round(spread(wall), 1)
            entry["decompress_wall_ms_spread_pct"] = round(relative_spread(wall), 2)
            entry["decompress_cpu_time_s_median"] = round(median(tool), 4)
            entry["decompress_wall_mib_s"] = round(data_mib / (median(wall) / 1000.0), 2) if median(wall) else 0.0
            entry["decompress_cpu_mib_s"] = round(data_mib / median(tool), 2) if median(tool) else 0.0
            entry["decompress_rss_max_kib"] = int(median(rss))
        else:
            for field in (
                "decompress_wall_ms_median", "decompress_wall_ms_spread", "decompress_wall_ms_spread_pct",
                "decompress_cpu_time_s_median", "decompress_wall_mib_s", "decompress_cpu_mib_s",
                "decompress_rss_max_kib",
            ):
                entry[field] = 0

        summaries.append(entry)

    document = {
        "source": raw_path,
        "grain": "median over repeats, one row per codec/level/threads",
        "groups": summaries,
    }
    with open(json_path, "w", encoding="utf-8") as handle:
        json.dump(document, handle, ensure_ascii=False, sort_keys=True, indent=2)
        handle.write("\n")

    columns = [
        "codec", "level", "threads_requested", "threads_applied", "data_mib", "ratio", "out_bytes",
        "compress_wall_mib_s", "compress_cpu_mib_s", "compress_wall_ms_median",
        "compress_rss_max_kib", "decompress_wall_mib_s", "decompress_cpu_mib_s",
        "decompress_wall_ms_median", "decompress_rss_max_kib",
        "compress_wall_ms_spread_pct", "decompress_wall_ms_spread_pct",
        "verified", "deterministic", "failures",
    ]
    with open(csv_path, "w", encoding="utf-8", newline="") as handle:
        writer = csv.DictWriter(handle, fieldnames=columns, extrasaction="ignore")
        writer.writeheader()
        for entry in summaries:
            writer.writerow(entry)

    print(f"groups={len(summaries)} json={json_path} csv={csv_path}")
    return 0


if __name__ == "__main__":
    sys.exit(main(sys.argv))
