#!/usr/bin/env python3
"""Deterministic SpacemiT K3 VPU benchmark runner."""

from __future__ import annotations

import argparse
import json
import os
import re
import shutil
import subprocess
import tempfile
import time
import uuid
from pathlib import Path
from typing import Any

SCRIPT_DIR = Path(__file__).resolve().parent
if str(SCRIPT_DIR) not in os.sys.path:
    os.sys.path.insert(0, str(SCRIPT_DIR))
from benchmark_common import (
    DdrPerfError, DdrPerfMonitor, collect_environment, compare_baseline,
    input_descriptor, summarize_ddr, write_result_and_report,
)
from tooling import tool_path

try:
    import resource
except ImportError:  # Windows unit tests
    resource = None


NAME_RE = re.compile(r"^[a-z0-9][a-z0-9_-]{0,63}$")
CODEC_FORMAT = {'h264': 'h264', 'h265': 'hevc', 'vp8': 'vp8', 'vp9': 'vp9', 'mjpeg': 'jpeg'}
CODEC_SUFFIX = {'h264': '.264', 'h265': '.265', 'vp8': '.ivf', 'vp9': '.ivf', 'mjpeg': '.mjpg'}
ROOT_KEYS = {
    "version", "name", "operation", "codec", "device", "input", "output",
    "width", "height", "frames", "fps", "sessions", "profiling", "min_fps", "baseline_fps",
    "warmup_iterations", "warmup_frames", "overwrite", "timeout_seconds", "result_path", "report_path",
    "baseline_result", "measure_ddr", "ddr_baseline_seconds", "ddr_capacity_mbps",
}
STATE_DIR = Path(os.environ.get("VPU_BENCHMARK_STATE_DIR", Path.home() / ".local/state/vpu-benchmark"))
DDR_PERF_DEVICE = Path("/dev/ddr_perf")
DDR_PERF_DEVICE = Path("/dev/ddr_perf")
FPS_RE = re.compile(r"Average Framerate:\s*([0-9]+(?:\.[0-9]+)?)")
DONE_RE = re.compile(r"frames_processed:\s*(\d+),\s*cost time:\s*(\d+)\s*us")
SIZE_RE = re.compile(r"Total size\s+(\d+)")
PROFILE_RE = re.compile(
    r"avg_write_bw=(\d+),\s*avg_read_bw=(\d+),\s*30fps_write_bw=(\d+),\s*30fps_read_bw=(\d+)"
)


class BenchmarkError(Exception):
    pass


def emit(data: dict[str, Any], code: int = 0) -> None:
    print(json.dumps(data, ensure_ascii=False, indent=2))
    raise SystemExit(code)


def fail(message: str, code: int = 2) -> None:
    emit({"ok": False, "error": message}, code)


def positive_int(value: Any, name: str, low: int, high: int, *, even: bool = False) -> int:
    if isinstance(value, bool) or not isinstance(value, int) or not low <= value <= high:
        raise BenchmarkError(f"{name} must be an integer from {low} through {high}")
    if even and value % 2:
        raise BenchmarkError(f"{name} must be even")
    return value


def positive_number(value: Any, name: str, low: float, high: float) -> float:
    if isinstance(value, bool) or not isinstance(value, (int, float)) or not low <= value <= high:
        raise BenchmarkError(f"{name} must be a number from {low} through {high}")
    return float(value)


def positive_number(value: Any, name: str, low: float, high: float) -> float:
    if isinstance(value, bool) or not isinstance(value, (int, float)) or not low <= value <= high:
        raise BenchmarkError(f"{name} must be a number from {low} through {high}")
    return float(value)


def unknown_keys(spec: dict[str, Any]) -> None:
    extra = sorted(set(spec) - ROOT_KEYS)
    if extra:
        raise BenchmarkError(f"unknown field(s): {', '.join(extra)}")


def mvx_devices() -> list[str]:
    devices: list[str] = []
    for path in sorted(Path("/dev").glob("video*"), key=lambda item: int(item.name[5:]) if item.name[5:].isdigit() else 9999):
        if not tool_path("v4l2-ctl"):
            continue
        result = subprocess.run(["v4l2-ctl", "--info", "-d", str(path)], text=True, capture_output=True, check=False)
        if result.returncode == 0 and re.search(r"Driver name\s*:\s*mvx\b", result.stdout):
            devices.append(str(path))
    return devices


def resolve_device(value: Any) -> str:
    if value in {None, "auto"}:
        devices = mvx_devices()
        if not devices:
            raise BenchmarkError("no V4L2 device with the mvx driver was found")
        return devices[0]
    if not isinstance(value, str) or not re.fullmatch(r"/dev/video\d+", value):
        raise BenchmarkError("device must be auto or /dev/videoN")
    if value not in mvx_devices():
        raise BenchmarkError(f"device is not an accessible mvx VPU device: {value}")
    return value


def normalize(raw: Any) -> dict[str, Any]:
    if not isinstance(raw, dict):
        raise BenchmarkError("spec must be an object")
    unknown_keys(raw)
    if raw.get("version", 1) != 1:
        raise BenchmarkError("version must be 1")
    name = raw.get("name")
    if not isinstance(name, str) or not NAME_RE.fullmatch(name):
        raise BenchmarkError("name must match ^[a-z0-9][a-z0-9_-]{0,63}$")
    operation = raw.get("operation")
    if operation not in {"encode", "decode"}:
        raise BenchmarkError("operation must be encode or decode")
    codec = raw.get("codec", "h264")
    if codec not in CODEC_FORMAT:
        raise BenchmarkError('codec must be one of ' + ', '.join(CODEC_FORMAT))
    device_value = raw.get("device", "auto")
    if device_value == "auto":
        resolve_device("auto")
        device = "auto"
    else:
        device = resolve_device(device_value)
    input_path = raw.get("input")
    if not isinstance(input_path, str) or not Path(input_path).expanduser().is_file():
        raise BenchmarkError(f"input file does not exist: {input_path}")
    input_path = str(Path(input_path).expanduser().resolve())
    sessions = positive_int(raw.get("sessions", 1), "sessions", 1, 32)
    if sessions > 1 and codec not in {'h264', 'h265'}:
        raise BenchmarkError('VP8/VP9/MJPEG benchmarks currently support single-session only')
    width, height = raw.get("width"), raw.get("height")
    if operation == "encode":
        width = positive_int(width, "width", 16, 8192, even=True)
        height = positive_int(height, "height", 16, 8192, even=True)
    elif width is not None or height is not None:
        raise BenchmarkError("width and height are inferred from decode input and must be omitted")
    frames = raw.get("frames")
    if frames in {None, 0}:
        frames = None
    else:
        frames = positive_int(frames, "frames", 1, 1000000)
    fps = raw.get("fps")
    if fps is not None:
        fps = positive_int(fps, "fps", 1, 240)
    profiling = raw.get("profiling", False)
    if not isinstance(profiling, bool):
        raise BenchmarkError("profiling must be boolean")
    if profiling and sessions != 1:
        raise BenchmarkError("profiling is supported only for a single session")
    if profiling and fps is None:
        raise BenchmarkError("profiling requires fps so bandwidth can be normalized")
    measure_ddr = raw.get("measure_ddr", False)
    if not isinstance(measure_ddr, bool):
        raise BenchmarkError("measure_ddr must be boolean")
    ddr_baseline_seconds = positive_number(
        raw.get("ddr_baseline_seconds", 2.0), "ddr_baseline_seconds", 0.2, 60.0
    )
    ddr_capacity_mbps = raw.get("ddr_capacity_mbps")
    if ddr_capacity_mbps is not None:
        ddr_capacity_mbps = positive_number(ddr_capacity_mbps, "ddr_capacity_mbps", 1.0, 1_000_000.0)
    measure_ddr = raw.get("measure_ddr", False)
    if not isinstance(measure_ddr, bool):
        raise BenchmarkError("measure_ddr must be boolean")
    ddr_baseline_seconds = positive_number(
        raw.get("ddr_baseline_seconds", 2.0), "ddr_baseline_seconds", 0.2, 60.0
    )
    ddr_capacity_mbps = raw.get("ddr_capacity_mbps")
    if ddr_capacity_mbps is not None:
        ddr_capacity_mbps = positive_number(
            ddr_capacity_mbps, "ddr_capacity_mbps", 1.0, 1_000_000.0
        )
    output = raw.get("output")
    if sessions > 1 and output is not None:
        raise BenchmarkError("multi-session benchmarks do not accept an output path")
    if operation == "encode" and sessions == 1 and not isinstance(output, str):
        raise BenchmarkError("single-session encode requires output")
    if output is not None:
        if not isinstance(output, str) or not output:
            raise BenchmarkError("output must be a non-empty path")
        suffixes = {'h264': {'.264', '.h264'}, 'h265': {'.265', '.h265', '.hevc'}, 'vp8': {'.ivf'}, 'vp9': {'.ivf'}, 'mjpeg': {'.mjpg', '.mjpeg'}}[codec]
        if operation == "encode" and Path(output).suffix.lower() not in suffixes:
            raise BenchmarkError(f"{codec} encode output must use an elementary stream suffix")
        if operation == "decode" and Path(output).suffix.lower() != ".yuv":
            raise BenchmarkError("decode output must end in .yuv")
        output = str(Path(output).expanduser().resolve())
    overwrite = raw.get("overwrite", False)
    if not isinstance(overwrite, bool):
        raise BenchmarkError("overwrite must be boolean")
    timeout = raw.get("timeout_seconds", 600)
    if isinstance(timeout, bool) or not isinstance(timeout, int) or not 1 <= timeout <= 3600:
        raise BenchmarkError("timeout_seconds must be an integer from 1 through 3600")
    min_fps = raw.get("min_fps")
    if min_fps is not None and (isinstance(min_fps, bool) or not isinstance(min_fps, (int, float)) or min_fps <= 0):
        raise BenchmarkError("min_fps must be a positive number")
    baseline_fps = raw.get("baseline_fps")
    if baseline_fps is not None and (isinstance(baseline_fps, bool) or not isinstance(baseline_fps, (int, float)) or baseline_fps <= 0):
        raise BenchmarkError("baseline_fps must be a positive number")
    baseline_result = raw.get("baseline_result")
    if baseline_result is not None:
        if not isinstance(baseline_result, str) or not Path(baseline_result).expanduser().is_file():
            raise BenchmarkError(f"baseline_result does not exist: {baseline_result}")
        baseline_result = str(Path(baseline_result).expanduser().resolve())
    warmup_iterations = positive_int(raw.get("warmup_iterations", 1), "warmup_iterations", 0, 20)
    warmup_frames = raw.get("warmup_frames", frames)
    if warmup_frames is not None:
        warmup_frames = positive_int(warmup_frames, "warmup_frames", 1, 1000000)
        if frames is not None:
            warmup_frames = min(warmup_frames, frames)
    result_path = raw.get("result_path") or f"{name}-result.json"
    if not isinstance(result_path, str) or Path(result_path).suffix.lower() != ".json":
        raise BenchmarkError("result_path must end in .json")
    result_path = str(Path(result_path).expanduser().resolve())
    report_path = raw.get("report_path") or str(Path(result_path).with_suffix(".md"))
    if not isinstance(report_path, str) or Path(report_path).suffix.lower() != ".md":
        raise BenchmarkError("report_path must end in .md")
    report_path = str(Path(report_path).expanduser().resolve())
    if operation == "encode" and frames is not None:
        required = width * height * 3 // 2 * frames
        actual = Path(input_path).stat().st_size
        if actual < required:
            raise BenchmarkError(f"raw input is too small for {frames} complete I420 frames: need {required} bytes, found {actual}")
    return {
        "version": 1, "name": name, "operation": operation, "codec": codec,
        "device": device, "input": input_path, "output": output,
        "width": width, "height": height, "frames": frames, "fps": fps,
        "sessions": sessions, "profiling": profiling, "min_fps": min_fps,
        "baseline_fps": baseline_fps, "baseline_result": baseline_result,
        "measure_ddr": measure_ddr,
        "ddr_baseline_seconds": ddr_baseline_seconds,
        "ddr_capacity_mbps": ddr_capacity_mbps,
        "warmup_iterations": warmup_iterations, "warmup_frames": warmup_frames, "overwrite": overwrite,
        "measure_ddr": measure_ddr, "ddr_baseline_seconds": ddr_baseline_seconds,
        "ddr_capacity_mbps": ddr_capacity_mbps,
        "timeout_seconds": timeout, "result_path": result_path, "report_path": report_path,
    }


def load_spec(path: str) -> dict[str, Any]:
    try:
        return normalize(json.loads(Path(path).read_text(encoding="utf-8")))
    except (OSError, json.JSONDecodeError) as exc:
        raise BenchmarkError(f"cannot read spec: {exc}") from exc


def compile_argv(spec: dict[str, Any]) -> tuple[list[str], str]:
    operation, sessions = spec["operation"], spec["sessions"]
    resolved_device = resolve_device(spec["device"])
    binary = {"encode": "mvx_encoder", "decode": "mvx_decoder"}[operation]
    if sessions > 1:
        binary += "_multi"
    binary_path = tool_path(binary)
    if not binary_path:
        raise BenchmarkError(f"required tool is unavailable: {binary}")
    argv = [binary_path, "--dev", resolved_device]
    if sessions > 1:
        argv += ["-f", "raw", "-n", str(sessions)]
        if operation == "encode":
            argv += ["-w", str(spec["width"]), "-h", str(spec["height"])]
            if spec["codec"] == "h265":
                argv += ["-o", "hevc"]
            if spec["frames"] is not None:
                argv += ["-r", str(spec["frames"])]
        elif spec["codec"] == "h265":
            argv += ["-i", "hevc"]
        argv.append(spec["input"])
        return argv, resolved_device
    argv += ["-f", "ivf" if spec['codec'] in {'vp8', 'vp9'} else "raw"]
    if operation == "encode":
        argv += ["-w", str(spec["width"]), "-h", str(spec["height"])]
        if spec["codec"] != "h264":
            argv += ["-o", CODEC_FORMAT[spec['codec']]]
    else:
        argv += ["-i", CODEC_FORMAT[spec['codec']]]
    if spec["frames"] is not None:
        argv += ["--frames", str(spec["frames"])]
    if spec["fps"] is not None:
        argv += ["-v", str(spec["fps"])]
    if spec["profiling"]:
        argv += ["--profiling", "1"]
    argv.append(spec["input"])
    if spec["output"] is not None:
        argv.append(spec["output"])
    return argv, resolved_device


def journal_cursor() -> str | None:
    if not tool_path("journalctl"):
        return None
    result = subprocess.run(["journalctl", "-k", "-n", "0", "--show-cursor", "--no-pager"], text=True, capture_output=True, check=False)
    match = re.search(r"-- cursor:\s*(\S+)", result.stdout + result.stderr)
    return match.group(1) if result.returncode == 0 and match else None


def profiling_record(cursor: str | None, fps: int) -> tuple[dict[str, Any] | None, str | None]:
    if cursor is None:
        return None, "kernel journal cursor was unavailable; profiling bandwidth could not be collected"
    result = subprocess.run(["journalctl", "-k", "--after-cursor", cursor, "--no-pager"], text=True, capture_output=True, check=False)
    matches = list(PROFILE_RE.finditer(result.stdout))
    if result.returncode != 0 or not matches:
        return None, "no MVX bandwidth record was visible in the kernel journal after this run"
    avg_write, avg_read, reported_write_30, reported_read_30 = (int(item) for item in matches[-1].groups())
    write_bps, read_bps = avg_write * fps, avg_read * fps
    return {
        "avg_write_bytes_per_frame": avg_write,
        "avg_read_bytes_per_frame": avg_read,
        "requested_fps": fps,
        "write_mb_s": round(write_bps / 1_000_000, 3),
        "read_mb_s": round(read_bps / 1_000_000, 3),
        "total_mb_s": round((write_bps + read_bps) / 1_000_000, 3),
        "kernel_reported_30fps_write_bytes_s": reported_write_30,
        "kernel_reported_30fps_read_bytes_s": reported_read_30,
    }, None


def parse_metrics(text: str) -> dict[str, Any]:
    fps_values = [float(value) for value in FPS_RE.findall(text)]
    done = DONE_RE.findall(text)
    sizes = SIZE_RE.findall(text)
    return {
        "mvx_status": "pass" if re.search(r"\[Test Result\].*\bPASS\b", text) else "fail",
        "average_fps": fps_values[-1] if fps_values else None,
        "all_reported_fps": fps_values,
        "frames_processed": int(done[-1][0]) if done else None,
        "mvx_cost_time_us": int(done[-1][1]) if done else None,
        "total_size_bytes": int(sizes[-1]) if sizes else None,
    }


def output_checks(spec: dict[str, Any]) -> list[str]:
    errors: list[str] = []
    for path in [spec["output"], spec["result_path"], spec["report_path"]]:
        if path and Path(path).exists() and not spec["overwrite"]:
            errors.append(f"path exists and overwrite is false: {path}")
    return errors


def cmd_capabilities(_: argparse.Namespace) -> None:
    mem_available = None
    try:
        match = re.search(r"^MemAvailable:\s+(\d+)\s+kB", Path("/proc/meminfo").read_text(), re.MULTILINE)
        mem_available = int(match.group(1)) if match else None
    except OSError:
        pass
    cursor = journal_cursor()
    ddr_available = DDR_PERF_DEVICE.exists() and os.access(DDR_PERF_DEVICE, os.R_OK | os.W_OK)
    emit({
        "ok": True,
        "platform": os.uname().machine,
        "kernel": os.uname().release,
        "tools": {name: tool_path(name) for name in ["mvx_encoder", "mvx_decoder", "mvx_encoder_multi", "mvx_decoder_multi", "ffmpeg", "v4l2-ctl", "journalctl"]},
        "mvx_devices": mvx_devices(),
        "kernel_journal_readable": cursor is not None,
        "ddr_bandwidth": {
            "available": ddr_available,
            "source": str(DDR_PERF_DEVICE),
            "system_wide": True,
            "multi_session_supported": True,
            "requires_elevated_privilege": DDR_PERF_DEVICE.exists() and not ddr_available,
        },
        "mem_available_kib": mem_available,
        "state_dir": str(STATE_DIR),
    })


def cmd_prepare(args: argparse.Namespace) -> None:
    if not tool_path("ffmpeg"):
        raise BenchmarkError("ffmpeg is required to generate raw test input")
    width = positive_int(args.width, "width", 16, 8192, even=True)
    height = positive_int(args.height, "height", 16, 8192, even=True)
    frames = positive_int(args.frames, "frames", 1, 1000000)
    fps = positive_int(args.fps, "fps", 1, 240)
    output = Path(args.output).expanduser().resolve()
    if output.suffix.lower() != ".yuv":
        raise BenchmarkError("prepared raw input must end in .yuv")
    expected = width * height * 3 // 2 * frames
    if expected > args.max_size_mib * 1024 * 1024:
        raise BenchmarkError(f"requested raw asset is {expected / 1024 / 1024:.1f} MiB, above --max-size-mib {args.max_size_mib}")
    if output.exists() and not args.overwrite:
        raise BenchmarkError(f"output exists and overwrite is false: {output}")
    output.parent.mkdir(parents=True, exist_ok=True)
    argv = ["ffmpeg", "-hide_banner", "-loglevel", "error", "-y" if args.overwrite else "-n", "-f", "lavfi", "-i", f"testsrc2=size={width}x{height}:rate={fps}", "-frames:v", str(frames), "-pix_fmt", "yuv420p", "-f", "rawvideo", str(output)]
    result = subprocess.run(argv, check=False)
    actual = output.stat().st_size if output.is_file() else 0
    emit({"ok": result.returncode == 0 and actual == expected, "output": str(output), "width": width, "height": height, "frames": frames, "fps": fps, "expected_bytes": expected, "actual_bytes": actual}, 0 if result.returncode == 0 and actual == expected else 1)


def cmd_create(args: argparse.Namespace) -> None:
    raw = {
        "version": 1, "name": args.name, "operation": args.operation, "codec": args.codec,
        "device": args.device, "input": args.input, "output": args.output,
        "width": args.width, "height": args.height, "frames": args.frames,
        "fps": args.fps, "sessions": args.sessions, "profiling": args.profiling,
        "min_fps": args.min_fps, "baseline_fps": args.baseline_fps,
        "baseline_result": args.baseline_result, "warmup_iterations": args.warmup,
        "measure_ddr": args.measure_ddr,
        "ddr_baseline_seconds": args.ddr_baseline_seconds,
        "ddr_capacity_mbps": args.ddr_capacity_mbps,
        "overwrite": args.overwrite, "timeout_seconds": args.timeout,
        "result_path": args.result, "report_path": args.report,
    }
    spec = normalize(raw)
    path = Path(args.spec or f"{args.name}.json")
    if path.exists() and not args.replace_spec:
        raise BenchmarkError(f"spec already exists: {path}; use --replace-spec")
    path.write_text(json.dumps(spec, ensure_ascii=False, indent=2), encoding="utf-8")
    emit({"ok": True, "spec_path": str(path.resolve()), "spec": spec})


def cmd_validate(args: argparse.Namespace) -> None:
    spec = load_spec(args.spec)
    errors = output_checks(spec)
    if errors:
        raise BenchmarkError("; ".join(errors))
    raw_size = Path(spec["input"]).stat().st_size
    warnings: list[str] = []
    if spec["sessions"] > 1:
        warnings.append("multi-session capacity depends on reserved memory and concurrent system load")
    if spec["fps"] is not None:
        warnings.append("fps is paced mode; omit fps to measure maximum throughput")
    if spec["measure_ddr"] and not DDR_PERF_DEVICE.exists():
        warnings.append(f"DDR measurement requested but {DDR_PERF_DEVICE} is absent")
    elif spec["measure_ddr"] and not os.access(DDR_PERF_DEVICE, os.R_OK | os.W_OK):
        warnings.append(f"DDR measurement requested but {DDR_PERF_DEVICE} is not readable/writable by this user")
    if spec["measure_ddr"]:
        warnings.append("DDR counters are system-wide; do not run another /dev/ddr_perf reader during this benchmark")
    argv, resolved_device = compile_argv(spec)
    emit({"ok": True, "spec": spec, "resolved_device": resolved_device, "argv": argv, "input_size_bytes": raw_size, "warnings": warnings})


def cmd_compile(args: argparse.Namespace) -> None:
    spec = load_spec(args.spec)
    argv, resolved_device = compile_argv(spec)
    emit({"ok": True, "device_selector": spec["device"], "resolved_device": resolved_device, "argv": argv})


def cmd_run(args: argparse.Namespace) -> None:
    spec = load_spec(args.spec)
    errors = output_checks(spec)
    if errors:
        raise BenchmarkError("; ".join(errors))
    argv, resolved_device = compile_argv(spec)
    if spec["output"]:
        Path(spec["output"]).parent.mkdir(parents=True, exist_ok=True)
    Path(spec["result_path"]).parent.mkdir(parents=True, exist_ok=True)
    STATE_DIR.joinpath("logs").mkdir(parents=True, exist_ok=True)
    log_path = STATE_DIR / "logs" / f"{spec['name']}-{int(time.time())}.log"
    warmup_runs: list[dict[str, Any]] = []
    warmup_logs: list[str] = []
    with tempfile.TemporaryDirectory(prefix="vpu-benchmark-warmup-") as temp_dir:
        warm_spec = dict(spec, frames=spec['warmup_frames'])
        for index in range(spec["warmup_iterations"]):
            warm_argv, _ = compile_argv(warm_spec)
            if spec["output"] and spec["sessions"] == 1:
                if spec["operation"] == "encode":
                    warm_argv[-1] = str(Path(temp_dir) / f"warmup-{index}{Path(spec['output']).suffix}")
                else:
                    warm_argv = warm_argv[:-1]
            warm_started = time.monotonic()
            try:
                warm = subprocess.run(
                    warm_argv, text=True, capture_output=True, check=False,
                    timeout=spec["timeout_seconds"],
                )
            except subprocess.TimeoutExpired as exc:
                raise BenchmarkError(f"warmup {index + 1} timed out") from exc
            warm_text = warm.stdout + warm.stderr
            warm_metrics = parse_metrics(warm_text)
            if warm.returncode != 0 or warm_metrics["mvx_status"] != "pass":
                raise BenchmarkError(f"warmup {index + 1} failed with return code {warm.returncode}")
            warmup_runs.append({
                "iteration": index + 1,
                "elapsed_seconds": round(time.monotonic() - warm_started, 4),
                "average_fps": warm_metrics["average_fps"],
                "frames_processed": warm_metrics["frames_processed"],
            })
            warmup_logs.append(warm_text)
    ddr_monitor = None
    ddr_baseline = None
    ddr_formal = None
    ddr_perf_bandwidth = None
    if spec["measure_ddr"]:
        try:
            ddr_monitor = DdrPerfMonitor(DDR_PERF_DEVICE)
            baseline_start = ddr_monitor.mark()
            time.sleep(spec["ddr_baseline_seconds"])
            baseline_end = ddr_monitor.mark()
            ddr_baseline = ddr_monitor.window(baseline_start, baseline_end)
        except DdrPerfError as exc:
            if ddr_monitor:
                ddr_monitor.close()
            raise BenchmarkError(str(exc)) from exc
    cursor = journal_cursor() if spec["profiling"] else None
    before = resource.getrusage(resource.RUSAGE_CHILDREN)
    formal_start = ddr_monitor.mark() if ddr_monitor else None
    started = time.time()
    timed_out = False
    try:
        process = subprocess.run(argv, text=True, capture_output=True, check=False, timeout=spec["timeout_seconds"])
        returncode, combined = process.returncode, process.stdout + process.stderr
    except subprocess.TimeoutExpired as exc:
        timed_out = True
        returncode = 124
        stdout = exc.stdout.decode(errors="replace") if isinstance(exc.stdout, bytes) else (exc.stdout or "")
        stderr = exc.stderr.decode(errors="replace") if isinstance(exc.stderr, bytes) else (exc.stderr or "")
        combined = stdout + stderr
    elapsed = time.time() - started
    if ddr_monitor and formal_start and ddr_baseline:
        try:
            formal_end = ddr_monitor.mark()
            ddr_formal = ddr_monitor.window(formal_start, formal_end)
            ddr_perf_bandwidth = summarize_ddr(
                ddr_monitor, ddr_baseline, ddr_formal, spec["ddr_capacity_mbps"]
            )
        except DdrPerfError as exc:
            raise BenchmarkError(str(exc)) from exc
        finally:
            ddr_monitor.close()
    after = resource.getrusage(resource.RUSAGE_CHILDREN)
    cpu_seconds = (after.ru_utime + after.ru_stime) - (before.ru_utime + before.ru_stime)
    metrics = parse_metrics(combined)
    average_fps = metrics["average_fps"]
    threshold = "not_configured" if spec["min_fps"] is None else ("pass" if average_fps is not None and average_fps >= spec["min_fps"] else "fail")
    mvx_profiling_bandwidth, profile_warning = profiling_record(cursor, spec["fps"]) if spec["profiling"] else (None, None)
    bandwidth = ddr_perf_bandwidth or mvx_profiling_bandwidth
    device_info = None
    if tool_path("v4l2-ctl"):
        probe = subprocess.run(
            ["v4l2-ctl", "--info", "-d", resolved_device], text=True,
            capture_output=True, timeout=5, check=False,
        )
        device_info = (probe.stdout + probe.stderr).strip() or None
    environment = collect_environment(
        "vpu-benchmark", "0.13.12",
        ["mvx_encoder", "mvx_decoder", "mvx_encoder_multi", "mvx_decoder_multi", "ffmpeg", "v4l2-ctl"],
        devices={
            "vpu": {"path": resolved_device, "v4l2_info": device_info},
            "ddr_perf": {
                "path": str(DDR_PERF_DEVICE), "exists": DDR_PERF_DEVICE.exists(),
                "readable": os.access(DDR_PERF_DEVICE, os.R_OK),
                "writable": os.access(DDR_PERF_DEVICE, os.W_OK),
            },
        },
    )
    baseline = None
    if average_fps is not None:
        try:
            baseline = compare_baseline(
                average_fps, "vpu",
                baseline_rate=spec["baseline_fps"],
                baseline_result_path=spec["baseline_result"],
            )
        except ValueError as exc:
            raise BenchmarkError(str(exc)) from exc
    warnings = [warning for warning in [profile_warning] if warning]
    if ddr_perf_bandwidth:
        warnings.append("DDR counters are system-wide; incremental values subtract the adjacent idle baseline but may include unrelated traffic")
    if ddr_formal and ddr_formal["elapsed_seconds"] < 1.0:
        warnings.append("formal DDR window is shorter than 1 second; use a longer input or paced run for stable bandwidth percentiles")
    if ddr_formal and ddr_formal["invalid_samples"]:
        warnings.append(f"discarded {ddr_formal['invalid_samples']} DDR sample(s) containing the 0xFFFFFFFF saturation sentinel")
    if ddr_perf_bandwidth and mvx_profiling_bandwidth:
        warnings.append("resources.ddr_bandwidth uses /dev/ddr_perf; MVX profiling remains available under details.mvx_profiling_bandwidth")
    if elapsed < 1:
        warnings.append("CPU percentage from a sub-second run is noisy; use a longer paced run for resource measurement")
    log_path.write_text("\n".join(warmup_logs + [combined]), encoding="utf-8")
    tool_ok = returncode == 0 and metrics["mvx_status"] == "pass" and not timed_out
    benchmark_ok = tool_ok and threshold != "fail"
    frame_time = round(1000 / average_fps, 4) if average_fps else None
    cpu_percent = round(cpu_seconds / elapsed * 100, 2) if elapsed > 0 else None
    result = {
        "schema": "k3-benchmark-result",
        "schema_version": 3,
        "component": "vpu",
        "provider": "vpu-benchmark",
        "ok": benchmark_ok,
        "benchmark": {"name": "vpu-benchmark", "version": "0.13.12", "run_id": str(uuid.uuid4())},
        "status": {
            "execution": "passed" if tool_ok else "failed",
            "acceptance": "passed" if benchmark_ok else "failed",
            "evidence": "complete" if spec["warmup_iterations"] > 0 else "partial",
        },
        "environment": environment,
        "sampling": {
            "warmup": {"iterations": spec["warmup_iterations"], "requested_frames": spec['warmup_frames'], "excluded_from_formal": True},
            "formal": {"elapsed_seconds": round(elapsed, 4), "frames": metrics["frames_processed"]},
        },
        "workload": {
            "name": spec["name"], "operation": spec["operation"], "codec": spec["codec"],
            "sessions": spec["sessions"], "width": spec["width"], "height": spec["height"],
            "frames": spec["frames"], "requested_fps": spec["fps"],
            "input": input_descriptor(spec["input"]),
            "output": spec["output"],
        },
        "measurement": {
            "mode": "paced-resource" if spec["fps"] is not None else "maximum-throughput",
            "scope": "mvx-native-report", "rate_unit": "frames_per_second",
            "measured_rate_per_second": average_fps,
            "throughput_equivalent_ms_per_operation": frame_time,
            "elapsed_seconds": round(elapsed, 4), "samples": metrics["frames_processed"],
        },
        "capacity": {
            "measured_rate_per_second": average_fps,
            "planning_rate_per_second": average_fps,
            "rate_unit": "frames_per_second", "scope": "mvx-native-report",
        },
        "resources": {
            "cpu_seconds": round(cpu_seconds, 4), "cpu_percent": cpu_percent,
            "peak_rss_bytes": after.ru_maxrss * 1024, "ddr_bandwidth": bandwidth,
            "availability": {
                "cpu": True, "memory": True,
                "ddr": {"available": bandwidth is not None,
                        "reason": None if bandwidth is not None else (profile_warning or "neither measure_ddr nor MVX profiling was requested")},
            },
        },
        "thresholds": {
            "status": threshold, "minimum_rate_per_second": spec["min_fps"],
            "rate_unit": "frames_per_second", "passed": threshold != "fail",
        },
        "summary": {
            "status": "pass" if benchmark_ok else "fail",
            "measured_rate_per_second": average_fps,
            "planning_rate_per_second": average_fps,
            "rate_unit": "frames_per_second",
            "latency_ms_per_operation": frame_time,
        },
        "artifacts": {
            "result": spec["result_path"], "raw_log": str(log_path),
            "output": spec["output"], "report": spec["report_path"],
        },
        "limitations": warnings,
        "details": {
            "device_selector": spec["device"], "resolved_device": resolved_device,
            "argv": argv, "returncode": returncode, "timed_out": timed_out,
            "mvx_status": metrics["mvx_status"], "baseline_comparison": baseline,
            "mvx_profiling_bandwidth": mvx_profiling_bandwidth,
            "warmup_runs": warmup_runs,
            "frames_processed": metrics["frames_processed"],
            "mvx_cost_time_us": metrics["mvx_cost_time_us"],
            "total_size_bytes": metrics["total_size_bytes"],
            "output_size_bytes": Path(spec["output"]).stat().st_size if spec["output"] and Path(spec["output"]).is_file() else None,
        },
    }
    write_result_and_report(result, spec["result_path"], spec["report_path"])
    emit(result, 0 if benchmark_ok else 1)


def build_parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(description=__doc__)
    sub = parser.add_subparsers(dest="command", required=True)
    sub.add_parser("capabilities").set_defaults(func=cmd_capabilities)
    prepare = sub.add_parser("prepare")
    prepare.add_argument("--output", required=True)
    prepare.add_argument("--width", type=int, required=True)
    prepare.add_argument("--height", type=int, required=True)
    prepare.add_argument("--frames", type=int, required=True)
    prepare.add_argument("--fps", type=int, default=30)
    prepare.add_argument("--max-size-mib", type=int, default=1024)
    prepare.add_argument("--overwrite", action="store_true")
    prepare.set_defaults(func=cmd_prepare)
    create = sub.add_parser("create")
    create.add_argument("--name", required=True)
    create.add_argument("--operation", choices=["encode", "decode"], required=True)
    create.add_argument("--codec", choices=list(CODEC_FORMAT), default="h264")
    create.add_argument("--device", default="auto")
    create.add_argument("--input", required=True)
    create.add_argument("--output")
    create.add_argument("--width", type=int)
    create.add_argument("--height", type=int)
    create.add_argument("--frames", type=int)
    create.add_argument("--fps", type=int)
    create.add_argument("--sessions", type=int, default=1)
    create.add_argument("--profiling", action="store_true")
    create.add_argument("--measure-ddr", action="store_true")
    create.add_argument("--ddr-baseline-seconds", type=float, default=2.0)
    create.add_argument("--ddr-capacity-mbps", type=float)
    create.add_argument("--min-fps", type=float)
    create.add_argument("--baseline-fps", type=float)
    create.add_argument("--baseline-result")
    create.add_argument("--warmup", type=int, default=1)
    create.add_argument("--overwrite", action="store_true")
    create.add_argument("--timeout", type=int, default=600)
    create.add_argument("--result")
    create.add_argument("--report")
    create.add_argument("--spec")
    create.add_argument("--replace-spec", action="store_true")
    create.set_defaults(func=cmd_create)
    for command, function in [("validate", cmd_validate), ("compile", cmd_compile), ("run", cmd_run)]:
        item = sub.add_parser(command)
        item.add_argument("--spec", required=True)
        item.set_defaults(func=function)
    return parser


def main() -> None:
    try:
        args = build_parser().parse_args()
        args.func(args)
    except BenchmarkError as exc:
        fail(str(exc))
    except KeyboardInterrupt:
        fail("interrupted", 130)


if __name__ == "__main__":
    main()
