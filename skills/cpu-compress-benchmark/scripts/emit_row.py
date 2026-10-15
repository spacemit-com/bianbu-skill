#!/usr/bin/env python3
"""Small JSON helper for the benchmark pipeline.

Modes
-----
  emit_row.py jsonl  <file> key=value [key=value ...]   append one JSON object
  emit_row.py object <file> key=value [key=value ...]   write one JSON object
  emit_row.py stats  <fn> <comma-separated-numbers>     print one statistic

Value typing for jsonl/object
  key=value    infer int, float, true/false, null; otherwise keep the string
  key:=value   always a string (identifiers, hashes, timestamps)
  key#=value   always a number (counters, durations)

Repeating a key replaces its earlier value. Statistics accept median, mean,
min, max, stddev and count. A malformed argument exits non-zero so a broken
caller fails loudly instead of writing junk into the report data.
"""

import json
import statistics
import sys


def coerce(raw: str):
    if raw == "null":
        return None
    if raw == "true":
        return True
    if raw == "false":
        return False
    try:
        return int(raw)
    except ValueError:
        pass
    try:
        return float(raw)
    except ValueError:
        pass
    return raw


def parse_pairs(argv):
    record = {}
    for pair in argv:
        key, sep, value = pair.partition("=")
        if not sep or not key:
            raise ValueError(f"argument is not key=value: {pair!r}")
        if key.endswith(":"):
            record[key[:-1]] = value
        elif key.endswith("#"):
            try:
                record[key[:-1]] = float(value) if ("." in value or "e" in value) else int(value)
            except ValueError:
                raise ValueError(f"{key} expects a number, got {value!r}") from None
        else:
            record[key] = coerce(value)
    return record


def print_stat(function, raw):
    values = [float(part) for part in raw.split(",") if part.strip() != ""]
    if not values:
        raise ValueError("stats needs at least one number")
    if function == "count":
        print(len(values))
        return
    result = {
        "median": statistics.median,
        "mean": statistics.fmean,
        "min": min,
        "max": max,
        "stddev": lambda items: statistics.stdev(items) if len(items) > 1 else 0.0,
    }[function](values)
    print(f"{result:.3f}" if isinstance(result, float) else result)


def main(argv):
    if len(argv) < 3:
        print(__doc__, file=sys.stderr)
        return 2
    mode, target = argv[1], argv[2]
    try:
        if mode == "stats":
            print_stat(target, argv[3] if len(argv) > 3 else "")
            return 0
        if mode not in ("jsonl", "object"):
            raise ValueError(f"unknown mode {mode!r}")
        record = parse_pairs(argv[3:])
    except ValueError as error:
        print(f"emit_row.py: {error}", file=sys.stderr)
        return 2

    line = json.dumps(record, ensure_ascii=False, sort_keys=True)
    if mode == "object":
        with open(target, "w", encoding="utf-8") as handle:
            handle.write(line + "\n")
    else:
        with open(target, "a", encoding="utf-8") as handle:
            handle.write(line + "\n")
    return 0


if __name__ == "__main__":
    sys.exit(main(sys.argv))
