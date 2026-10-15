"""Shared result, environment, baseline, and report helpers for K3 benchmarks."""

from __future__ import annotations

import json
import os
import platform
import shutil
import struct
import subprocess
import threading
import time
from pathlib import Path
from typing import Any

from tooling import tool_path

try:
    import fcntl
except ImportError:  # Windows unit tests
    fcntl = None


DDR_POLL_SECONDS = 0.05
DDR_STAT = struct.Struct("=7I")
DDR_INIT_PORT = 0x40044401  # _IOW('D', 1, int)
DDR_GET_STAT = 0xC01C4402  # _IOWR('D', 2, struct ddr_perf_stat)
DDR_COUNTER_SATURATED = 0xFFFFFFFF


class DdrPerfError(RuntimeError):
    pass


class DdrPerfMonitor:
    """Accumulate K3 system-wide DDR deltas from /dev/ddr_perf."""

    def __init__(self, device: str | Path = "/dev/ddr_perf") -> None:
        if fcntl is None:
            raise DdrPerfError("DDR measurement requires Linux fcntl.ioctl")
        self.device = str(device)
        try:
            self.fd = os.open(self.device, os.O_RDWR | getattr(os, "O_CLOEXEC", 0))
        except OSError as exc:
            raise DdrPerfError(f"cannot open {self.device} for DDR measurement: {exc}") from exc
        self._io_lock = threading.Lock()
        self._data_lock = threading.Lock()
        self._stop = threading.Event()
        self._error: OSError | None = None
        self._totals = {"read_bytes": 0, "write_bytes": 0}
        self._port_totals: dict[int, dict[str, int]] = {}
        self._records: list[dict[str, float | int]] = []
        self._invalid_samples = 0
        self._last_poll = time.monotonic()
        try:
            self.ports = self._discover_ports()
            if not self.ports:
                raise DdrPerfError(f"{self.device} returned no valid DDR ports")
            self._port_totals = {port: {"read_bytes": 0, "write_bytes": 0} for port in self.ports}
        except Exception:
            os.close(self.fd)
            raise
        self._thread = threading.Thread(target=self._poll_loop, name="vpu-ddr-perf", daemon=True)
        self._thread.start()

    def _get_stat(self, port: int) -> tuple[int, ...]:
        buffer = bytearray(DDR_STAT.pack(port, 0, 0, 0, 0, 0, 0))
        fcntl.ioctl(self.fd, DDR_GET_STAT, buffer, True)
        return DDR_STAT.unpack(buffer)

    def _discover_ports(self) -> list[int]:
        ports: list[int] = []
        for port in range(16):
            try:
                fcntl.ioctl(self.fd, DDR_INIT_PORT, struct.pack("=i", port))
                self._get_stat(port)
            except OSError:
                break
            ports.append(port)
        return ports

    def _poll_once_locked(self) -> None:
        values: dict[int, tuple[int, int]] = {}
        for port in self.ports:
            fields = self._get_stat(port)
            values[port] = (fields[2], fields[3])
        now = time.monotonic()
        if any(counter == DDR_COUNTER_SATURATED for pair in values.values() for counter in pair):
            with self._data_lock:
                self._last_poll = now
                self._invalid_samples += 1
            return
        read_bytes = sum(value[0] for value in values.values())
        write_bytes = sum(value[1] for value in values.values())
        with self._data_lock:
            elapsed = max(now - self._last_poll, 1e-9)
            self._last_poll = now
            self._totals["read_bytes"] += read_bytes
            self._totals["write_bytes"] += write_bytes
            for port, (read_value, write_value) in values.items():
                self._port_totals[port]["read_bytes"] += read_value
                self._port_totals[port]["write_bytes"] += write_value
            self._records.append({
                "time": now, "elapsed": elapsed,
                "read_bytes": read_bytes, "write_bytes": write_bytes,
            })

    def _poll_once(self) -> None:
        with self._io_lock:
            self._poll_once_locked()

    def _poll_loop(self) -> None:
        while not self._stop.wait(DDR_POLL_SECONDS):
            try:
                self._poll_once()
            except OSError as exc:
                self._error = exc
                self._stop.set()

    def mark(self) -> dict[str, Any]:
        if self._error is not None:
            raise DdrPerfError(f"DDR counter read failed: {self._error}")
        try:
            self._poll_once()
        except OSError as exc:
            raise DdrPerfError(f"DDR counter read failed: {exc}") from exc
        with self._data_lock:
            return {
                "time": time.monotonic(), "record_index": len(self._records),
                "read_bytes": self._totals["read_bytes"],
                "write_bytes": self._totals["write_bytes"],
                "invalid_samples": self._invalid_samples,
                "ports": {str(port): dict(values) for port, values in self._port_totals.items()},
            }

    def window(self, start: dict[str, Any], end: dict[str, Any]) -> dict[str, Any]:
        elapsed = max(end["time"] - start["time"], 1e-9)
        read_bytes = end["read_bytes"] - start["read_bytes"]
        write_bytes = end["write_bytes"] - start["write_bytes"]
        with self._data_lock:
            records = self._records[start["record_index"]:end["record_index"]]
        sampled_elapsed = sum(float(item["elapsed"]) for item in records)
        rate_elapsed = max(sampled_elapsed, 1e-9)
        rates = [
            (int(item["read_bytes"]) + int(item["write_bytes"])) / float(item["elapsed"]) / 1_000_000
            for item in records if float(item["elapsed"]) > 0
        ]
        ports = {}
        for port in self.ports:
            key = str(port)
            ports[key] = {
                "read_bytes": end["ports"][key]["read_bytes"] - start["ports"][key]["read_bytes"],
                "write_bytes": end["ports"][key]["write_bytes"] - start["ports"][key]["write_bytes"],
            }
        return {
            "elapsed_seconds": round(elapsed, 6),
            "sampled_elapsed_seconds": round(sampled_elapsed, 6), "samples": len(records),
            "invalid_samples": end["invalid_samples"] - start["invalid_samples"],
            "read_bytes": read_bytes, "write_bytes": write_bytes,
            "read_mbps": round(read_bytes / rate_elapsed / 1_000_000, 4),
            "write_mbps": round(write_bytes / rate_elapsed / 1_000_000, 4),
            "total_mbps": round((read_bytes + write_bytes) / rate_elapsed / 1_000_000, 4),
            "p95_total_mbps": round(_percentile(rates, 0.95), 4) if rates else None,
            "peak_total_mbps": round(max(rates), 4) if rates else None,
            "ports": ports,
        }

    def close(self) -> None:
        self._stop.set()
        self._thread.join(timeout=1.0)
        os.close(self.fd)


def _percentile(values: list[float], fraction: float) -> float:
    ordered = sorted(values)
    index = max(0, min(len(ordered) - 1, int(len(ordered) * fraction + 0.999999) - 1))
    return ordered[index]


def summarize_ddr(
    monitor: DdrPerfMonitor,
    baseline: dict[str, Any],
    formal: dict[str, Any],
    capacity_mbps: float | None,
) -> dict[str, Any]:
    incremental_read = max(0.0, formal["read_mbps"] - baseline["read_mbps"])
    incremental_write = max(0.0, formal["write_mbps"] - baseline["write_mbps"])
    incremental_total = incremental_read + incremental_write
    utilization = incremental_total / capacity_mbps * 100 if capacity_mbps else None
    return {
        "requested": True,
        "source": monitor.device,
        "scope": "system-wide during the formal VPU invocation window",
        "attribution": "adjacent-idle-subtracted estimate; counters are not tagged by VPU master",
        "ports": monitor.ports,
        "sampling_interval_ms": int(DDR_POLL_SECONDS * 1000),
        "baseline": baseline,
        "formal": formal,
        "incremental": {
            "read_mbps": round(incremental_read, 4),
            "write_mbps": round(incremental_write, 4),
            "total_mbps": round(incremental_total, 4),
            "p95_total_mbps": round(max(0.0, (formal["p95_total_mbps"] or 0.0) - baseline["total_mbps"]), 4),
            "peak_total_mbps": round(max(0.0, (formal["peak_total_mbps"] or 0.0) - baseline["total_mbps"]), 4),
        },
        "capacity_mbps": capacity_mbps,
        "incremental_utilization_percent": round(utilization, 4) if utilization is not None else None,
        "utilization_status": "calculated" if capacity_mbps else "capacity_not_configured",
    }


def input_descriptor(path: str | None) -> dict[str, Any] | None:
    if not path:
        return None
    item = Path(path)
    try:
        stat = item.stat()
    except OSError:
        return {"path": str(item), "available": False}
    return {
        "path": str(item), "available": True, "size_bytes": stat.st_size,
        "mtime_ns": stat.st_mtime_ns,
    }


def _read_optional(path: str) -> str | None:
    try:
        return Path(path).read_text(encoding="utf-8", errors="replace").replace("\x00", "").strip() or None
    except OSError:
        return None


def _os_release() -> dict[str, str]:
    result: dict[str, str] = {}
    text = _read_optional("/etc/os-release") or ""
    for line in text.splitlines():
        if "=" not in line or line.startswith("#"):
            continue
        key, value = line.split("=", 1)
        result[key.lower()] = value.strip().strip('"')
    return result


def _command_version(name: str) -> dict[str, Any]:
    path = tool_path(name)
    if not path:
        return {"available": False, "path": None, "version": None}
    version = None
    for flag in ("--version", "-version", "-V"):
        try:
            call = subprocess.run([path, flag], text=True, capture_output=True, timeout=3, check=False)
            text = (call.stdout + call.stderr).strip()
            if text:
                version = text.splitlines()[0][:300]
                break
        except (OSError, subprocess.TimeoutExpired):
            continue
    return {"available": True, "path": path, "version": version}


def _package_versions(names: list[str]) -> dict[str, str | None]:
    result: dict[str, str | None] = {}
    query = shutil.which("dpkg-query")
    for name in names:
        value = None
        if query:
            try:
                call = subprocess.run(
                    [query, "-W", "-f=${Version}", name], text=True,
                    capture_output=True, timeout=3, check=False,
                )
                if call.returncode == 0:
                    value = call.stdout.strip() or None
            except (OSError, subprocess.TimeoutExpired):
                pass
        result[name] = value
    return result


def collect_environment(
    provider: str,
    provider_version: str,
    tools: list[str],
    *,
    devices: dict[str, Any] | None = None,
    extra_static: dict[str, Any] | None = None,
    observations: dict[str, Any] | None = None,
) -> dict[str, Any]:
    static = {
        "hostname": platform.node(),
        "board_model": _read_optional("/proc/device-tree/model"),
        "machine": platform.machine(),
        "kernel": platform.release(),
        "python": platform.python_version(),
        "os": _os_release(),
        "firmware": (firmware := {
            path: value for path in (
                "/etc/bianbu-release", "/etc/spacemit-release", "/etc/image-release"
            ) if (value := _read_optional(path)) is not None
        }) or {"available": False, "reason": "no independently versioned firmware release file is exposed"},
        "packages": _package_versions(["ffmpeg", "k3x-vpu-test"]),
        "tools": {name: _command_version(name) for name in tools},
        "devices": devices or {},
        "provider": {"name": provider, "version": provider_version},
    }
    if extra_static:
        static["provider_details"] = extra_static
    return {
        **static,
        "observations": observations or {},
    }


def compare_baseline(
    current_rate: float,
    component: str,
    *,
    baseline_rate: float | None = None,
    baseline_result_path: str | None = None,
) -> dict[str, Any] | None:
    source = "scalar"
    path = None
    if baseline_result_path:
        source = "result"
        path = str(Path(baseline_result_path).expanduser().resolve())
        try:
            document = json.loads(Path(path).read_text(encoding="utf-8"))
        except (OSError, json.JSONDecodeError) as exc:
            raise ValueError(f"cannot read baseline_result: {exc}") from exc
        if document.get("schema") != "k3-benchmark-result" or document.get("component") != component:
            raise ValueError(f"baseline_result must be a k3-benchmark-result for component {component}")
        baseline_rate = document.get("measurement", {}).get("measured_rate_per_second")
    if baseline_rate is None:
        return None
    baseline_rate = float(baseline_rate)
    if baseline_rate <= 0:
        raise ValueError("baseline rate must be positive")
    reason = "Direct numerical comparison; environment and input consistency are not checked"
    delta = current_rate - baseline_rate
    comparison = "above" if delta > 0 else ("below" if delta < 0 else "equal")
    return {
        "source": source, "path": path, "baseline_rate_per_second": baseline_rate,
        "current_rate_per_second": current_rate, "delta_rate_per_second": round(delta, 4),
        "delta_percent": round(delta / baseline_rate * 100, 4),
        "ratio": round(current_rate / baseline_rate, 6), "status": comparison,
        "consistency_checked": False, "reason": reason,
    }


def render_markdown(result: dict[str, Any]) -> str:
    benchmark = result.get("benchmark", {})
    status = result.get("status", {})
    summary = result.get("summary", {})
    environment = result.get("environment", {})
    resources = result.get("resources", {})
    lines = [
        f"# {benchmark.get('name', result.get('provider', 'K3 benchmark'))}", "",
        f"- Run ID: `{benchmark.get('run_id', '')}`",
        f"- Execution: **{status.get('execution', 'unknown')}**",
        f"- Acceptance: **{status.get('acceptance', 'unknown')}**",
        f"- Evidence: **{status.get('evidence', 'unknown')}**",
        f"- Rate: `{summary.get('measured_rate_per_second')}` {summary.get('rate_unit', '')}",
        f"- Latency: `{summary.get('latency_ms_per_operation')}` ms/operation",
        "", "## Environment", "",
        f"- Board: `{environment.get('board_model')}`",
        f"- Kernel: `{environment.get('kernel')}`",
        "", "## Resources", "",
        f"- CPU: `{resources.get('cpu_percent')}` %",
        f"- Peak RSS: `{resources.get('peak_rss_bytes')}` bytes",
        f"- DDR: `{json.dumps(resources.get('ddr_bandwidth'), ensure_ascii=False)}`",
    ]
    baseline = result.get("details", {}).get("baseline_comparison")
    if baseline:
        lines += ["", "## Baseline", "", f"- Status: `{baseline.get('status')}`",
                  f"- Consistency checked: `{baseline.get('consistency_checked')}`",
                  f"- Delta: `{baseline.get('delta_percent')}` %",
                  f"- Note: {baseline.get('reason') or 'Direct numerical comparison'}"]
    limitations = result.get("limitations") or []
    if limitations:
        lines += ["", "## Limitations", ""] + [f"- {item}" for item in limitations]
    return "\n".join(lines) + "\n"


def write_result_and_report(result: dict[str, Any], result_path: str, report_path: str) -> None:
    report = str(Path(report_path).expanduser().resolve())
    result["artifacts"]["report"] = report
    Path(result_path).parent.mkdir(parents=True, exist_ok=True)
    Path(report).parent.mkdir(parents=True, exist_ok=True)
    Path(result_path).write_text(json.dumps(result, ensure_ascii=False, indent=2), encoding="utf-8")
    Path(report).write_text(render_markdown(result), encoding="utf-8")
