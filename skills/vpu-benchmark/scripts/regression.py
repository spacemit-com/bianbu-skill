#!/usr/bin/env python3
"""Run the fixed K3 VPU regression suite and compare it with certified baselines."""

from __future__ import annotations

import argparse
import json
import os
import re
import statistics
import subprocess
import sys
import tempfile
import time
from pathlib import Path
from typing import Any

import assets
import vpu_mvx_bandwidth as mvx_bw


ROOT = Path(__file__).resolve().parents[1]
BASELINES_PATH = ROOT / "references" / "default-baselines.json"
BENCHMARK = ROOT / "scripts" / "benchmark.py"
SKILL_VERSION = "0.13.12"


def default_output_dir() -> Path:
    state_home = Path(os.environ.get("XDG_STATE_HOME", Path.home() / ".local" / "state"))
    return state_home / "vpu-benchmark" / "results"


def emit_progress(enabled: bool, event: str, **fields: Any) -> None:
    if enabled:
        print(json.dumps({"event": event, **fields}, ensure_ascii=False, separators=(",", ":")), file=sys.stderr, flush=True)


def load_baselines(path: Path = BASELINES_PATH) -> dict[str, Any]:
    data = json.loads(path.read_text(encoding="utf-8"))
    if data.get("schema") != "vpu-benchmark-baselines" or data.get("schema_version") != 2:
        raise ValueError("unsupported baseline file")
    return data


def comparison_environment(environment: dict[str, Any]) -> dict[str, Any]:
    """Platform versions for reporting only; never a comparison gate."""
    info = environment.get("devices", {}).get("vpu", {}).get("v4l2_info", "")
    driver = re.search(r"Driver name\s*:\s*([^\n]+)", info)
    version = re.search(r"Driver version\s*:\s*([^\n]+)", info)
    return {
        "board_model": environment.get("board_model"),
        "os": environment.get("os", {}).get("pretty_name"),
        "kernel": environment.get("kernel"),
        "vpu_driver": driver.group(1).strip() if driver else None,
        "mvx_driver": version.group(1).strip() if version else None,
        "ffmpeg": environment.get("packages", {}).get("ffmpeg"),
        "k3x_vpu_test": environment.get("packages", {}).get("k3x-vpu-test"),
        "python": environment.get("python"),
    }


def classify(current_fps: float | None, current_bandwidth: float | None, case: dict[str, Any], thresholds: dict[str, Any], *, execution_ok: bool = True) -> dict[str, Any]:
    if not execution_ok:
        return {"status": "FAIL", "reason": "benchmark execution failed"}
    if current_fps is None:
        return {"status": "FAIL", "reason": "FPS was not reported"}
    if current_bandwidth is None:
        return {"status": "FAIL", "reason": "MVX session bandwidth was not measured"}
    if not case.get("baseline", {}).get("fps"):
        return {"status": "MEASURED", "reason": "仅实测，未设置基准"}
    baseline = case["baseline"]
    if current_fps is None:
        return {"status": "FAIL", "reason": "FPS was not reported"}
    fps_regression = (baseline["fps"] - current_fps) / baseline["fps"] * 100
    bandwidth_increase = None
    if current_bandwidth is not None and baseline.get("mvx_bandwidth_mbps"):
        bandwidth_increase = (current_bandwidth - baseline["mvx_bandwidth_mbps"]) / baseline["mvx_bandwidth_mbps"] * 100
    status, reasons = "PASS", []
    if fps_regression > thresholds["fps_fail_regression_percent"]:
        status, reasons = "FAIL", [f"FPS 低于规格基准 {fps_regression:.2f}%，超过失败阈值"]
    elif fps_regression > thresholds["fps_warn_regression_percent"]:
        status, reasons = "WARN", [f"FPS 低于规格基准 {fps_regression:.2f}%，超过告警阈值"]
    if bandwidth_increase is not None:
        if bandwidth_increase > thresholds["mvx_bandwidth_fail_increase_percent"]:
            status = "FAIL"
            reasons.append(f"MVX bandwidth increase {bandwidth_increase:.2f}% exceeds fail threshold")
        elif bandwidth_increase > thresholds["mvx_bandwidth_warn_increase_percent"] and status == "PASS":
            status = "WARN"
            reasons.append(f"MVX bandwidth increase {bandwidth_increase:.2f}% exceeds warning threshold")
    return {"status": status, "reason": "; ".join(reasons) or "within thresholds", "fps_regression_percent": round(fps_regression, 4), "mvx_bandwidth_increase_percent": round(bandwidth_increase, 4) if bandwidth_increase is not None else None}


def execute_case(case: dict[str, Any], input_path: str, output_dir: Path, sequence: int) -> dict[str, Any]:
    name = f"regression-{case['id']}-{sequence}"
    result_path = output_dir / f"{name}.json"
    report_path = output_dir / f"{name}.md"
    spec_path = output_dir / f"{name}-spec.json"
    spec = {
        "version": 1, "name": name, "operation": case["operation"], "codec": case["codec"],
        "device": "auto", "input": input_path, "frames": case["frames"], "sessions": case["sessions"],
        "warmup_iterations": case["warmup_iterations"] if case['sessions'] == 1 else 0, "warmup_frames": 30, "profiling": False,
        "measure_ddr": False,
        "overwrite": True, "timeout_seconds": 600,
        "result_path": str(result_path), "report_path": str(report_path),
    }
    if case["operation"] == "encode":
        spec.update(width=case["width"], height=case["height"])
        if case["sessions"] == 1:
            spec["output"] = str(output_dir / f"{name}{mvx_bw.b.CODEC_SUFFIX[case['codec']]}")
    spec_path.write_text(json.dumps(spec, ensure_ascii=False, indent=2), encoding="utf-8")
    call = subprocess.run([sys.executable, str(BENCHMARK), "run", "--spec", str(spec_path)], text=True, capture_output=True, check=False)
    if not result_path.is_file():
        return {"execution_ok": False, "error": (call.stderr or call.stdout).strip()[-2000:], "result_path": str(result_path)}
    result = json.loads(result_path.read_text(encoding="utf-8"))
    bandwidth = {"ok": False, "error": "FPS workload did not complete"}
    if result.get("ok"):
        if case.get("mvx_bandwidth_method") != mvx_bw.METHOD:
            raise ValueError("Default MVX bandwidth baseline method must be mvx-session-profile-v1")
        bandwidth = mvx_bw.measure(case, input_path, output_dir / f"{name}-bandwidth")
    return {
        "execution_ok": bool(result.get("ok")) and bandwidth["ok"],
        "fps": result.get("measurement", {}).get("measured_rate_per_second"),
        "mvx_bandwidth_mbps": bandwidth.get("total_mbps"),
        "mvx_bandwidth_method": mvx_bw.METHOD,
        "mvx_bandwidth_result": str(output_dir / f"{name}-bandwidth" / "bandwidth.json"),
        "mvx_bandwidth_error": bandwidth.get("error"),
        "test_versions": comparison_environment(result.get("environment", {})),
        "result_path": str(result_path), "report_path": str(report_path),
    }


def version_lines(document: dict[str, Any]) -> list[str]:
    lines = ["", "### 测试版本", "", f"- Skill: {document.get('skill_version', SKILL_VERSION)}"]
    snapshots = []
    for row in document["cases"]:
        for run in row["runs"]:
            versions = run.get("test_versions", {})
            if versions not in snapshots:
                snapshots.append(versions)
    for index, versions in enumerate(snapshots, 1):
        lines.append(f"- 环境 {index}: " + "; ".join(f"{key}={value or '未获取'}" for key, value in versions.items()))
    lines.append("- 素材集: " + json.dumps(document.get("asset_sets", {}), ensure_ascii=False))
    lines.append("- 版本与素材仅记录，不做一致性校验；有基准直接计算偏差，无基准仅展示实测。")
    lines.append("- 单路 FPS 与带宽各预热一次、30 帧；多路不预热。正式测试仍请求每路 200 帧。FPS 基准来自 4cores@1GHz 产品规格；MVX 带宽使用对应路数的实际并发标定值。")
    lines.append("- FPS 为不限速测试的平均每路吞吐；MVX 带宽另测：4K 每路 60 FPS、1080p 每路 30 FPS，汇总实际并发会话计数。")
    lines.append("- MVX 带宽不是系统 DDR 增量；单位 MB/s=1,000,000 Bytes/s。解码不保存 YUV；带宽证据见各轮 bandwidth.json。")
    return lines


def bandwidth_context(row: dict[str, Any]) -> str:
    resolution = "4K" if "4K" in row['label'] else "1080p"
    return f"{resolution}、每路 {row['mvx_bandwidth_target_fps']} FPS、{row['sessions']} 路"


def result_table(document: dict[str, Any]) -> list[str]:
    lines = ["| 场景 | 规格基准 FPS | 实测平均每路 FPS | MVX 总带宽 |",
             "|---|---:|---:|---:|"]
    def number(value: Any) -> str:
        return "-" if value is None else f"{value:.2f}"
    for row in document["cases"]:
        lines.append(
            f"| {row['label']} | {number(row['baseline_fps'])} FPS | {number(row['measured_fps'])} FPS | "
            f"{number(row['measured_mvx_bandwidth_mbps'])} MB/s（{bandwidth_context(row)}） |"
        )
    return lines


def result_conclusion(document: dict[str, Any]) -> list[str]:
    if document['status'] == 'PASS':
        return ["现有测试项性能均达到规格基准。"]
    return ["存在性能偏差、执行异常或未设置基准的用例："] + [
        f"- {row['label']}: {row['reason']}" for row in document['cases'] if row['status'] != 'PASS'
    ]


def render_report(document: dict[str, Any]) -> str:
    lines = ["# VPU 默认回归测试", "", f"- Suite: `{document['suite']}`",
             f"- Asset set: `{document['asset_set_id']}`", ""]
    lines += result_table(document)
    lines += [""] + result_conclusion(document)
    lines += version_lines(document)
    return "\n".join(lines)


def compact_result(document: dict[str, Any]) -> dict[str, Any]:
    display = ["VPU 性能测试结果", ""] + result_table(document)
    if any(row['status'] == 'MEASURED' for row in document['cases']):
        display += ["", "MEASURED：仅实测，未设置基准；不代表验收通过。"]
    display += [""] + result_conclusion(document)
    display += version_lines(document)
    display += ["", f"报告：`{document['artifacts']['report']}`"]
    return {
        "status": document["status"], "suite": document["suite"],
        "skill_version": document.get("skill_version", SKILL_VERSION),
        "test_versions": [{"id": row["id"], "runs": [run.get("test_versions", {}) for run in row["runs"]]} for row in document["cases"]],
        "asset_set_id": document["asset_set_id"],
        "asset_sets": document.get("asset_sets", {}),
        "units": {"fps": "FPS", "mvx_bandwidth": "MB/s", "delta": "%"},
        "mvx_bandwidth_method": mvx_bw.METHOD,
        "cases": [{
            "id": row["id"], "label": row["label"], "status": row["status"],
            "asset_set_id": row.get("asset_set_id", document["asset_set_id"]),
            "standard_fps": row["baseline_fps"], "fps": row["measured_fps"], "fps_delta_percent": row.get("fps_regression_percent"),
            "mvx_bandwidth_mb_s": row["measured_mvx_bandwidth_mbps"], "mvx_bandwidth_delta_percent": row.get("mvx_bandwidth_increase_percent"),
            "mvx_bandwidth_method": mvx_bw.METHOD, "mvx_bandwidth_context": bandwidth_context(row),
            "mvx_bandwidth_target_fps_per_session": row['mvx_bandwidth_target_fps'],
            "mvx_bandwidth_sessions": row['sessions'],
            "reason": row["reason"] if row["status"] != "PASS" else None,
        } for row in document["cases"]],
        "display_markdown": "\n".join(display),
        "result": document["artifacts"]["json"], "report": document["artifacts"]["report"],
    }


def cmd_list(baselines: dict[str, Any]) -> None:
    print(json.dumps({"suite": baselines["suite"], "asset_set_id": baselines["asset_set_id"], "thresholds": baselines["thresholds"], "cases": [{"id": c["id"], "label": c["label"], **c["baseline"]} for c in baselines["cases"]]}, ensure_ascii=False, indent=2))


def cmd_run(args: argparse.Namespace, baselines: dict[str, Any]) -> None:
    emit_progress(args.progress, "accepted", suite=baselines["suite"])
    manifest = assets.load_manifest()
    output_dir = Path(args.output_dir).expanduser().resolve()
    output_dir.mkdir(parents=True, exist_ok=True)
    output_dir = Path(tempfile.mkdtemp(prefix="suite-", dir=output_dir))
    selected = [c for c in baselines["cases"] if not args.case or c["id"] in args.case]
    if not selected:
        raise ValueError("no matching baseline case")
    prepared = {}
    rows = []
    for case in selected:
        variant = case.get("asset_variant", "1080p")
        case_manifest = assets.variant_manifest(manifest, variant)
        if variant not in prepared:
            prepared[variant] = assets.ensure(case_manifest)
            emit_progress(args.progress, "assets_ready", asset_set_id=case_manifest["asset_set_id"], changed=prepared[variant]["changed"])
        artifact = case_manifest["artifacts"][case.get("input_artifact", baselines["input_artifact"])]["filename"]
        if case.get('input_artifact') in {'vp8', 'vp9', 'mjpeg'}:
            assets.ensure_codec(case_manifest, case['input_artifact'])
        input_path = str(Path(prepared[variant]["cache"]) / artifact)
        emit_progress(args.progress, "case_started", id=case["id"], label=case["label"])
        runs = [execute_case(case, input_path, output_dir, 1)]
        first = runs[0]
        verdict = classify(first.get("fps"), first.get("mvx_bandwidth_mbps"), case, baselines["thresholds"], execution_ok=first["execution_ok"])
        if verdict["status"] in {"WARN", "FAIL"} and first["execution_ok"]:
            for sequence in range(2, 2 + int(baselines["thresholds"].get("confirmation_runs_on_alert", 0))):
                runs.append(execute_case(case, input_path, output_dir, sequence))
            valid = [r for r in runs if r["execution_ok"]]
            fps = statistics.median(r["fps"] for r in valid) if valid else None
            bandwidth_values = [r["mvx_bandwidth_mbps"] for r in valid if r.get("mvx_bandwidth_mbps") is not None]
            bandwidth = statistics.median(bandwidth_values) if bandwidth_values else None
            verdict = classify(fps, bandwidth, case, baselines["thresholds"], execution_ok=len(valid) == len(runs))
        else:
            fps, bandwidth = first.get("fps"), first.get("mvx_bandwidth_mbps")
        if not all(run['execution_ok'] for run in runs):
            verdict['reason'] += ': ' + '; '.join(run.get('mvx_bandwidth_error') or run.get('error') or 'workload failed' for run in runs if not run['execution_ok'])
        rows.append({"id": case["id"], "label": case["label"], "asset_set_id": case_manifest["asset_set_id"], "baseline_fps": case["baseline"].get("fps"), "measured_fps": fps, "baseline_mvx_bandwidth_mbps": case["baseline"].get("mvx_bandwidth_mbps"), "measured_mvx_bandwidth_mbps": bandwidth, "mvx_bandwidth_target_fps": case['mvx_bandwidth_target_fps'], "sessions": case['sessions'], "mvx_bandwidth_method": mvx_bw.METHOD, **verdict, "runs": runs})
        emit_progress(args.progress, "case_completed", id=case["id"], status=verdict["status"], fps=fps, mvx_bandwidth_mbps=bandwidth)
    rank = {"PASS": 0, "MEASURED": 1, "WARN": 2, "FAIL": 3}
    overall = max((r["status"] for r in rows), key=rank.get)
    stamp = time.strftime("%Y%m%d-%H%M%S")
    json_path, report_path = output_dir / f"vpu-regression-{stamp}.json", output_dir / f"vpu-regression-{stamp}.md"
    document = {"schema": "vpu-regression-result", "schema_version": 3, "mvx_bandwidth_method": mvx_bw.METHOD, "suite": baselines["suite"], "asset_set_id": manifest["asset_set_id"], "status": overall, "thresholds": baselines["thresholds"], "cases": rows, "artifacts": {"json": str(json_path), "report": str(report_path)}}
    document["asset_sets"] = {variant: value["asset_set_id"] for variant, value in prepared.items()}
    document["skill_version"] = SKILL_VERSION
    json_path.write_text(json.dumps(document, ensure_ascii=False, indent=2), encoding="utf-8")
    report_path.write_text(render_report(document), encoding="utf-8")
    compact = compact_result(document)
    (output_dir / "latest-summary.json").write_text(json.dumps(compact, ensure_ascii=False, indent=2), encoding="utf-8")
    emit_progress(args.progress, "completed", status=overall, report=str(report_path))
    if args.stdout_format == "markdown":
        print(compact["display_markdown"])
    else:
        print(json.dumps(document if args.verbose else compact, ensure_ascii=False, indent=2 if args.verbose else None, separators=None if args.verbose else (",", ":")))
    if overall == "FAIL":
        raise SystemExit(1)


def main() -> None:
    parser = argparse.ArgumentParser(description=__doc__)
    sub = parser.add_subparsers(dest="command", required=True)
    sub.add_parser("list")
    run_parser = sub.add_parser("run")
    run_parser.add_argument("--case", action="append", help="case id; repeat to select multiple")
    run_parser.add_argument("--output-dir", default=str(default_output_dir()))
    run_parser.add_argument("--verbose", action="store_true", help="print the full result instead of compact JSON")
    run_parser.add_argument("--stdout-format", choices=("json", "markdown"), default="json", help="format written to stdout")
    run_parser.add_argument("--no-progress", action="store_false", dest="progress", help="disable JSONL progress on stderr")
    run_parser.set_defaults(progress=True)
    args = parser.parse_args()
    try:
        baselines = load_baselines()
        cmd_list(baselines) if args.command == "list" else cmd_run(args, baselines)
    except (OSError, ValueError, json.JSONDecodeError, assets.AssetError) as exc:
        print(json.dumps({"ok": False, "error": str(exc)}, ensure_ascii=False, indent=2))
        raise SystemExit(2)


if __name__ == "__main__":
    main()
