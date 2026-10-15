#!/usr/bin/env python3
"""SpacemiT stability-test.sh 的限定范围稳定性测试控制器。"""

import argparse
import datetime as dt
import hashlib
import json
import os
import re
import shutil
import signal
import subprocess
import sys
import time
import urllib.error
import urllib.request
import uuid
from pathlib import Path

DEFAULT_STATE = Path.home() / ".local/state/spacemit-k-stability"
ERROR_RE = re.compile(r"(?i)(segmentation fault|segfault|out of memory|oom-kill|kernel panic|i/o error|input/output error|fatal|fail(?:ed|ure)?|\berror\b)")
TEMP_WARN_C = 85
TEMP_CRIT_C = 95
DISK_WARN = 2 * 1024**3
VENDOR_SCRIPT_PAGE_URL = "https://gitee.com/spacemit-buildroot/factorytest/blob/k3-br-v1.0.y/common/stability-test.sh"
VENDOR_SCRIPT_RAW_URL = "https://gitee.com/spacemit-buildroot/factorytest/raw/k3-br-v1.0.y/common/stability-test.sh"
VENDOR_SCRIPT_MAX_BYTES = 2 * 1024**2
VENDOR_SCRIPT_DOWNLOAD_TIMEOUT = 20
GRAPHICAL_ENV_KEYS = (
    "DISPLAY", "WAYLAND_DISPLAY", "XDG_RUNTIME_DIR", "XDG_SESSION_TYPE",
    "DBUS_SESSION_BUS_ADDRESS", "XAUTHORITY", "PULSE_SERVER", "PIPEWIRE_REMOTE",
)
GRAPHICAL_SESSION_NAMES = (
    "lxqt-session", "labwc", "gnome-shell", "kwin_wayland", "weston",
    "sway", "mate-session", "xfce4-session", "Xwayland",
)


def now():
    return dt.datetime.now(dt.timezone.utc).isoformat()


def atomic_json(path, data):
    path = Path(path)
    path.parent.mkdir(parents=True, exist_ok=True)
    tmp = path.with_suffix(path.suffix + ".tmp")
    tmp.write_text(json.dumps(data, ensure_ascii=False, indent=2) + "\n")
    os.replace(tmp, path)


def load_json(path, default=None):
    try:
        return json.loads(Path(path).read_text())
    except (OSError, json.JSONDecodeError):
        return default


def sha256_bytes(data):
    return hashlib.sha256(data).hexdigest()


def validate_vendor_script(data):
    if len(data) < 256:
        raise ValueError("下载内容过短，不像完整的稳定性测试脚本")
    if len(data) > VENDOR_SCRIPT_MAX_BYTES:
        raise ValueError("下载内容超过 2 MiB 限制")
    if b"\0" in data:
        raise ValueError("下载内容包含 NUL 字节")
    first_line = data.splitlines()[0] if data.splitlines() else b""
    if not first_line.startswith(b"#!") or b"sh" not in first_line.lower():
        raise ValueError("下载内容不是带 shebang 的 Shell 脚本")


def fetch_vendor_script(destination, opener=urllib.request.urlopen):
    request = urllib.request.Request(
        VENDOR_SCRIPT_RAW_URL,
        headers={"User-Agent": "spacemit-k-stability/1.0"},
    )
    with opener(request, timeout=VENDOR_SCRIPT_DOWNLOAD_TIMEOUT) as response:
        data = response.read(VENDOR_SCRIPT_MAX_BYTES + 1)
    validate_vendor_script(data)
    destination = Path(destination)
    tmp = destination.with_suffix(destination.suffix + ".tmp")
    tmp.write_bytes(data)
    tmp.chmod(0o755)
    os.replace(tmp, destination)
    return {"path": str(destination), "sha256": sha256_bytes(data)}


def resolve_vendor_script(run_dir):
    """优先获取 Gitee 版本，失败时返回技能内置脚本。"""
    bundled = Path(__file__).with_name("stability-test.sh").resolve()
    downloaded = Path(run_dir) / "stability-test.sh"
    try:
        result = fetch_vendor_script(downloaded)
        return downloaded, {
            "source": "gitee",
            "source_page": VENDOR_SCRIPT_PAGE_URL,
            "source_url": VENDOR_SCRIPT_RAW_URL,
            "sha256": result["sha256"],
            "fetch_error": None,
        }
    except (OSError, ValueError, urllib.error.URLError) as exc:
        if not bundled.is_file():
            raise RuntimeError(f"Gitee 脚本获取失败且内置脚本不存在：{exc}") from exc
        data = bundled.read_bytes()
        validate_vendor_script(data)
        return bundled, {
            "source": "bundled_fallback",
            "source_page": VENDOR_SCRIPT_PAGE_URL,
            "source_url": VENDOR_SCRIPT_RAW_URL,
            "sha256": sha256_bytes(data),
            "fetch_error": f"{type(exc).__name__}: {exc}",
        }


def parse_duration(value):
    text = str(value).strip().lower()
    match = re.fullmatch(r"(\d+)([smhd]?)", text)
    if not match:
        raise argparse.ArgumentTypeError("duration must be an integer followed by s, m, h, or d")
    factor = {"": 1, "s": 1, "m": 60, "h": 3600, "d": 86400}[match.group(2)]
    return int(match.group(1)) * factor


def process_environment(pid):
    try:
        raw = Path(f"/proc/{pid}/environ").read_bytes()
    except OSError:
        return {}
    result = {}
    for entry in raw.split(b"\0"):
        if b"=" not in entry:
            continue
        key, value = entry.split(b"=", 1)
        key = key.decode(errors="replace")
        if key in GRAPHICAL_ENV_KEYS:
            result[key] = value.decode(errors="replace")
    return result


def process_command(pid):
    try:
        return Path(f"/proc/{pid}/cmdline").read_bytes().replace(b"\0", b" ").decode(errors="replace").strip()
    except OSError:
        return ""


def process_uid(pid):
    try:
        for line in Path(f"/proc/{pid}/status").read_text().splitlines():
            if line.startswith("Uid:"):
                return int(line.split()[1])
    except (OSError, ValueError, IndexError):
        pass
    return None


def discover_graphical_session_env(base_env=None):
    """从当前环境或同 UID 桌面进程恢复图形与音频会话变量。"""
    env = dict(base_env or os.environ)
    try:
        target_uid = int(env.get("SUDO_UID", os.getuid()))
    except (TypeError, ValueError):
        target_uid = os.getuid()
    selected = {key: env[key] for key in GRAPHICAL_ENV_KEYS if env.get(key)}
    source_pid = None
    source_command = None
    best_score = -1
    try:
        proc_entries = list(Path("/proc").iterdir())
    except OSError:
        proc_entries = []
    for entry in proc_entries:
        if not entry.name.isdigit() or process_uid(entry.name) != target_uid:
            continue
        command = process_command(entry.name)
        if not any(name in command for name in GRAPHICAL_SESSION_NAMES):
            continue
        candidate = process_environment(entry.name)
        score = 4 * bool(candidate.get("WAYLAND_DISPLAY")) + 3 * bool(candidate.get("DISPLAY"))
        score += 2 * bool(candidate.get("XDG_RUNTIME_DIR")) + bool(candidate.get("DBUS_SESSION_BUS_ADDRESS"))
        if score > best_score:
            best_score = score
            source_pid = int(entry.name)
            source_command = command[:300]
            for key, value in candidate.items():
                if not selected.get(key) or key in ("DISPLAY", "WAYLAND_DISPLAY", "XDG_SESSION_TYPE"):
                    selected[key] = value

    runtime_dir = selected.get("XDG_RUNTIME_DIR") or f"/run/user/{target_uid}"
    runtime_path = Path(runtime_dir)
    if runtime_path.is_dir():
        selected["XDG_RUNTIME_DIR"] = runtime_dir
        if not selected.get("WAYLAND_DISPLAY"):
            sockets = sorted(path.name for path in runtime_path.glob("wayland-*") if path.is_socket())
            if sockets:
                selected["WAYLAND_DISPLAY"] = sockets[0]
        if not selected.get("DBUS_SESSION_BUS_ADDRESS") and (runtime_path / "bus").exists():
            selected["DBUS_SESSION_BUS_ADDRESS"] = f"unix:path={runtime_path}/bus"
        if not selected.get("PULSE_SERVER") and (runtime_path / "pulse/native").exists():
            selected["PULSE_SERVER"] = f"unix:{runtime_path}/pulse/native"
    if not selected.get("DISPLAY") and Path("/tmp/.X11-unix/X0").exists():
        selected["DISPLAY"] = ":0"
    if selected.get("WAYLAND_DISPLAY"):
        selected["XDG_SESSION_TYPE"] = "wayland"
    elif selected.get("DISPLAY"):
        selected["XDG_SESSION_TYPE"] = "x11"

    env.update(selected)
    wayland_socket = runtime_path / selected.get("WAYLAND_DISPLAY", "") if selected.get("WAYLAND_DISPLAY") else None
    info = {
        "available": bool(selected.get("DISPLAY") or (wayland_socket and wayland_socket.exists())),
        "source_pid": source_pid,
        "source_command": source_command,
        "variables": selected,
        "wayland_socket_exists": bool(wayland_socket and wayland_socket.exists()),
        "x11_socket_exists": Path("/tmp/.X11-unix/X0").exists(),
    }
    return env, info


def proc_identity(pid):
    try:
        raw = Path(f"/proc/{pid}/stat").read_text()
        tail = raw[raw.rfind(")") + 2:].split()
        return {"pid": pid, "state": tail[0], "pgrp": int(tail[2]), "start_ticks": int(tail[19])}
    except (OSError, ValueError, IndexError):
        return None


def same_process(pid, start_ticks):
    ident = proc_identity(pid)
    return bool(ident and ident["state"] != "Z" and ident["start_ticks"] == start_ticks)


def group_processes(pgid):
    found = []
    for entry in Path("/proc").iterdir():
        if not entry.name.isdigit():
            continue
        ident = proc_identity(int(entry.name))
        if not ident or ident["pgrp"] != pgid or ident["state"] == "Z":
            continue
        try:
            command = Path(f"/proc/{entry.name}/cmdline").read_bytes().replace(b"\0", b" ").decode(errors="replace").strip()
        except OSError:
            command = ""
        found.append({"pid": ident["pid"], "command": command or "[unknown]"})
    return sorted(found, key=lambda item: item["pid"])


def detect_chip():
    cpuinfo = Path("/proc/cpuinfo").read_text(errors="replace")
    if "Spacemit(R) X60" in cpuinfo:
        return "K1"
    if "Spacemit(R) X100" in cpuinfo:
        return "K3"
    return "unknown"


def graphics_devices(chip):
    dri = Path("/dev/dri")
    nodes = []
    try:
        nodes = sorted(path.name for path in dri.iterdir() if path.name.startswith(("card", "renderD")))
    except OSError:
        pass
    return {
        "nodes": nodes,
        "k3_card2_exists": (dri / "card2").exists(),
        "render_node_exists": any(name.startswith("renderD") for name in nodes),
        "suitable": (dri / "card2").exists() if chip == "K3" else bool(nodes),
    }


def temperatures():
    values = []
    for path in Path("/sys/class/thermal").glob("thermal_zone*/temp"):
        try:
            raw = int(path.read_text().strip())
            celsius = raw / 1000 if raw > 1000 else float(raw)
            type_path = path.parent / "type"
            label = type_path.read_text().strip() if type_path.exists() else path.parent.name
            values.append({"zone": label, "c": round(celsius, 1)})
        except (OSError, ValueError):
            pass
    return values


def mem_info():
    data = {}
    try:
        for line in Path("/proc/meminfo").read_text().splitlines():
            key, value = line.split(":", 1)
            if key in ("MemTotal", "MemAvailable", "SwapTotal", "SwapFree"):
                data[key] = int(value.split()[0]) * 1024
    except (OSError, ValueError, IndexError):
        pass
    return data


def cpu_counter():
    try:
        values = [int(x) for x in Path("/proc/stat").read_text().splitlines()[0].split()[1:]]
        idle = values[3] + (values[4] if len(values) > 4 else 0)
        return sum(values), idle
    except (OSError, ValueError, IndexError):
        return None


def sample(previous_cpu=None):
    current_cpu = cpu_counter()
    busy = None
    if previous_cpu and current_cpu:
        total_delta = current_cpu[0] - previous_cpu[0]
        idle_delta = current_cpu[1] - previous_cpu[1]
        if total_delta > 0:
            busy = round(100 * (total_delta - idle_delta) / total_delta, 2)
    try:
        load = [round(x, 2) for x in os.getloadavg()]
    except OSError:
        load = []
    disk = shutil.disk_usage(Path.home())
    return {
        "timestamp": now(), "cpu_busy_percent": busy, "load_1_5_15": load,
        "memory": mem_info(), "temperatures": temperatures(), "disk_free_bytes": disk.free,
    }, current_cpu


def latest_vendor_log(before=None):
    candidates = [p for p in (Path.home() / "logs").glob("*") if p.is_dir()]
    if before:
        candidates = [p for p in candidates if str(p) not in before]
    return str(max(candidates, key=lambda p: p.stat().st_mtime)) if candidates else None


def current_record(state_dir):
    return load_json(Path(state_dir).expanduser() / "current.json")


def derive_status(record):
    if not record:
        return {"status": "idle", "message": "没有已记录的测试任务"}
    run_dir = Path(record["run_dir"])
    metadata = load_json(run_dir / "metadata.json", record)
    status = load_json(run_dir / "status.json", {})
    status.update({"run_id": metadata.get("run_id"), "run_dir": str(run_dir)})
    supervisor = metadata.get("supervisor") or {}
    if status.get("status") in ("finished", "failed"):
        return status
    visible = same_process(supervisor.get("pid", -1), supervisor.get("start_ticks", -2))
    status["supervisor_visible"] = visible
    if not visible:
        try:
            updated = dt.datetime.fromisoformat(status["updated_at"])
            age_s = (dt.datetime.now(dt.timezone.utc) - updated).total_seconds()
        except (KeyError, TypeError, ValueError):
            age_s = float("inf")
        stale_after = max(30, int(metadata.get("interval_s", 60)) * 3)
        status["status_age_s"] = round(age_s, 1) if age_s != float("inf") else None
        status["supervisor_visibility"] = "宿主 PID 在当前命名空间不可见；以状态文件新鲜度判断"
        if age_s > stale_after:
            status.update(status="failed", reason="supervisor_lost", observed_at=now())
    return status


def emit(data, as_json):
    if as_json:
        print(json.dumps(data, ensure_ascii=False, indent=2))
        return
    print(f"status={data.get('status', 'unknown')} run_id={data.get('run_id', '-')} phase={data.get('phase', '-')}")
    if data.get("reason"):
        print(f"reason={data['reason']}")
    if data.get("report"):
        print(f"report={data['report']}")


def preflight(args):
    existing = derive_status(current_record(args.state_dir))
    first = cpu_counter()
    time.sleep(0.2)
    metrics, _ = sample(first)
    chip = detect_chip()
    device_info = graphics_devices(chip)
    _, graphical_session = discover_graphical_session_env()
    result = {
        "chip": chip, "supported": chip in ("K1", "K3"),
        "vendor_script_preferred_page": VENDOR_SCRIPT_PAGE_URL,
        "vendor_script_preferred_raw_url": VENDOR_SCRIPT_RAW_URL,
        "bundled_vendor_script": str(Path(__file__).with_name("stability-test.sh")),
        "bundled_vendor_script_executable": os.access(Path(__file__).with_name("stability-test.sh"), os.X_OK),
        "graphical_session": graphical_session, "graphics_devices": device_info,
        "existing_run": existing, "metrics": metrics,
    }
    emit(result, args.json)
    return 0 if result["supported"] else 2


def start(args):
    state_dir = Path(args.state_dir).expanduser().resolve()
    existing = derive_status(current_record(state_dir))
    if existing.get("status") in ("starting", "running", "stopping"):
        print(json.dumps({"error": "run_already_active", "existing": existing}, ensure_ascii=False))
        return 3
    chip = detect_chip()
    if chip not in ("K1", "K3"):
        print(json.dumps({"error": "unsupported_chip", "detected": chip}, ensure_ascii=False))
        return 2
    device_info = graphics_devices(chip)
    if not device_info["suitable"]:
        print(json.dumps({
            "error": "gpu_device_unavailable",
            "message": "当前执行环境缺少稳定性图形负载所需的 GPU 设备；在 Harness 中请使用 host-start",
            "graphics_devices": device_info,
        }, ensure_ascii=False))
        return 8
    launch_env, graphical_session = discover_graphical_session_env()
    if not graphical_session["available"]:
        print(json.dumps({
            "error": "graphical_session_unavailable",
            "message": "未发现可用的 DISPLAY 或 Wayland socket；无法可靠启动 mpv/glmark2",
            "graphical_session": graphical_session,
        }, ensure_ascii=False))
        return 6
    run_id = time.strftime("%Y%m%dT%H%M%SZ", time.gmtime()) + "-" + uuid.uuid4().hex[:6]
    run_dir = state_dir / "runs" / run_id
    run_dir.mkdir(parents=True, exist_ok=False)
    try:
        script, script_info = resolve_vendor_script(run_dir)
    except RuntimeError as exc:
        print(json.dumps({"error": "vendor_script_unavailable", "message": str(exc)}, ensure_ascii=False))
        return 5
    cmd = [sys.executable, str(Path(__file__).resolve()), "_watch", "--state-dir", str(state_dir), "--run", run_id,
           "--duration", str(args.duration), "--interval", str(args.interval), "--update", str(args.update)]
    out = open(run_dir / "supervisor.log", "ab", buffering=0)
    proc = subprocess.Popen(cmd, stdin=subprocess.DEVNULL, stdout=out, stderr=subprocess.STDOUT,
                            start_new_session=True, close_fds=True, env=launch_env)
    ident = proc_identity(proc.pid)
    metadata = {
        "run_id": run_id, "run_dir": str(run_dir), "chip": chip, "created_at": now(),
        "duration_s": args.duration, "interval_s": args.interval, "update_s": args.update,
        "vendor_script": str(script), "vendor_script_source": script_info["source"],
        "vendor_script_source_page": script_info["source_page"],
        "vendor_script_source_url": script_info["source_url"],
        "vendor_script_sha256": script_info["sha256"],
        "vendor_script_fetch_error": script_info["fetch_error"],
        "graphical_session": graphical_session,
        "graphics_devices": device_info,
        "supervisor": ident, "skip_llama": args.skip_llama,
    }
    atomic_json(run_dir / "metadata.json", metadata)
    atomic_json(run_dir / "status.json", {"status": "starting", "phase": "supervisor_start", "updated_at": now()})
    atomic_json(state_dir / "current.json", metadata)
    time.sleep(0.4)
    result = derive_status(metadata)
    emit(result, True)
    return 0 if result.get("status") != "failed" else 1


def scan_alerts(run_dir, vendor_log, seen):
    alerts = []
    files = [run_dir / "launcher.log"]
    if vendor_log:
        files.extend(Path(vendor_log).glob("*.log*"))
    for path in files:
        try:
            with open(path, "rb") as handle:
                handle.seek(max(0, path.stat().st_size - 131072))
                lines = handle.read().decode(errors="replace").splitlines()
        except OSError:
            continue
        for line in lines:
            if ERROR_RE.search(line) and not re.search(r"(?i)0\s+(errors?|failures?)|without errors?", line):
                key = f"{path}:{line[:300]}"
                if key not in seen:
                    seen.add(key)
                    alerts.append({"timestamp": now(), "severity": "error", "source": str(path), "message": line[:500]})
    return alerts


def stop_group(pgid):
    result = {"pgid": pgid, "signals": [], "remaining_processes": []}
    if not pgid:
        return result
    for sig, wait_s in ((signal.SIGINT, 5), (signal.SIGTERM, 5), (signal.SIGKILL, 1)):
        if not group_processes(pgid):
            break
        try:
            os.killpg(pgid, sig)
            result["signals"].append(signal.Signals(sig).name)
        except ProcessLookupError:
            break
        deadline = time.time() + wait_s
        while time.time() < deadline and group_processes(pgid):
            time.sleep(0.2)
    result["remaining_processes"] = group_processes(pgid)
    return result


def write_report(run_dir, status, metadata):
    try:
        samples = [json.loads(line) for line in (run_dir / "samples.jsonl").read_text().splitlines() if line.strip()]
    except (OSError, json.JSONDecodeError):
        samples = []
    try:
        alerts = [json.loads(line) for line in (run_dir / "alerts.jsonl").read_text().splitlines() if line.strip()]
    except (OSError, json.JSONDecodeError):
        alerts = []
    cpus = [s["cpu_busy_percent"] for s in samples if s.get("cpu_busy_percent") is not None]
    temps = [t["c"] for s in samples for t in s.get("temperatures", [])]
    last = samples[-1] if samples else {}
    started = status.get("load_started_epoch")
    ended = status.get("ended_epoch", time.time())
    effective = max(0, ended - started) if started else 0
    serious = [a for a in alerts if a.get("severity") in ("error", "critical")]
    verdict = "通过" if status.get("status") == "finished" and not serious else "需复核"
    lines = [
        "# SpacemiT K 系列芯片稳定性测试报告", "", f"- 任务 ID：`{metadata.get('run_id')}`",
        f"- 芯片：`{metadata.get('chip')}`", f"- 结论：**{verdict}**",
        f"- 终态：`{status.get('status')}` / `{status.get('reason', '')}`",
        f"- 指定时长：`{metadata.get('duration_s', 0)} 秒`（`0` 表示无限时长）",
        f"- 有效负载时间：`{effective:.1f} 秒`",
        f"- 厂商脚本来源：`{metadata.get('vendor_script_source', 'unknown')}`",
        f"- 厂商脚本页面：`{metadata.get('vendor_script_source_page', '')}`",
        f"- 厂商脚本 SHA256：`{metadata.get('vendor_script_sha256', '')}`",
        f"- 图形会话环境：`{metadata.get('graphical_session', {}).get('variables', {})}`",
        f"- 厂商日志目录：`{status.get('vendor_log_dir') or '未知'}`", "", "## 负载摘要", "",
        f"- 采样数：{len(samples)}",
        f"- CPU 忙碌率：平均 {sum(cpus)/len(cpus):.1f}% / 峰值 {max(cpus):.1f}%" if cpus else "- CPU 忙碌率：不可用",
        f"- 峰值温度：{max(temps):.1f}°C" if temps else "- 峰值温度：不可用",
        f"- 结束时磁盘剩余：{last.get('disk_free_bytes', 0)/1024**3:.2f} GiB" if last else "- 结束时磁盘剩余：不可用",
        "", "## 异常", "",
    ]
    lines.extend([f"- [{a.get('severity')}] {a.get('source')}：{a.get('message')}" for a in alerts[-50:]] or ["- 未记录到监控异常。"])
    cleanup = status.get("cleanup", {})
    lines += ["", "## 资源清理", "", f"- 使用的信号：`{cleanup.get('signals', [])}`",
              f"- 剩余的本次测试进程：`{cleanup.get('remaining_processes', [])}`",
              f"- 已删除的本次测试资源：`{cleanup.get('removed_resources', [])}`", "", "## 结果说明", "",
              "“通过”表示受监管测试周期正常结束，并且未检测到 error 或 critical 级告警。用于产品或量产判定前仍应复核各组件日志；本报告属于运行证据，不等同于芯片认证结论。", ""]
    path = run_dir / "report.md"
    path.write_text("\n".join(lines))
    return path


STOP = False


def request_stop(_sig=None, _frame=None):
    global STOP
    STOP = True


def watch(args):
    global STOP
    signal.signal(signal.SIGTERM, request_stop)
    signal.signal(signal.SIGINT, request_stop)
    state_dir = Path(args.state_dir)
    run_dir = state_dir / "runs" / args.run
    metadata_path = run_dir / "metadata.json"
    deadline = time.time() + 10
    while not metadata_path.exists() and time.time() < deadline:
        time.sleep(0.05)
    metadata = load_json(metadata_path, {})
    script = Path(metadata["vendor_script"])
    launch_env, graphical_session = discover_graphical_session_env()
    metadata["graphical_session"] = graphical_session
    run_script = script
    if metadata.get("skip_llama"):
        run_script = run_dir / "vendor-run.sh"
        configured = script.read_text().replace("LLAMA_ENABLE=true", "LLAMA_ENABLE=false", 1)
        run_script.write_text(configured)
        run_script.chmod(0o755)
    home = Path.home()
    tracked = [home / "testfile.bin", run_dir / "Qwen3-0.6B-BF16_Q4.gguf", Path("/tmp/llama-test.sh"), Path("/tmp/.stability-test-running")]
    existed = {str(path): path.exists() for path in tracked}
    logs_before = {str(path) for path in (home / "logs").glob("*")}
    launcher_log = open(run_dir / "launcher.log", "ab", buffering=0)
    launcher = subprocess.Popen(["bash", str(run_script), "-l"], cwd=run_dir, stdin=subprocess.DEVNULL,
                                stdout=launcher_log, stderr=subprocess.STDOUT, start_new_session=True,
                                close_fds=True, env=launch_env)
    launcher_ident = proc_identity(launcher.pid)
    metadata.update({"launcher": launcher_ident, "owned_pgid": launcher.pid, "resource_existed_before": existed})
    atomic_json(metadata_path, metadata)
    load_started = None
    reason = None
    previous_cpu = None
    seen = set()
    last_update = 0
    sample_no = 0
    status = {"status": "starting", "phase": "vendor_setup", "updated_at": now(), "owned_pgid": launcher.pid}
    atomic_json(run_dir / "status.json", status)
    try:
        while True:
            vendor_log = latest_vendor_log(logs_before)
            rc = launcher.poll()
            try:
                launcher_text = (run_dir / "launcher.log").read_text(errors="replace")[-65536:]
            except OSError:
                launcher_text = ""
            if load_started is None and rc == 0 and "All tests started" in launcher_text:
                load_started = time.time()
            if rc not in (None, 0) and load_started is None:
                reason = f"vendor_launcher_exit_{rc}"
            metrics, previous_cpu = sample(previous_cpu)
            metrics.update(sample_no=sample_no, owned_processes=group_processes(launcher.pid))
            with open(run_dir / "samples.jsonl", "a") as handle:
                handle.write(json.dumps(metrics, ensure_ascii=False) + "\n")
            new_alerts = scan_alerts(run_dir, vendor_log, seen)
            hottest = max((item["c"] for item in metrics["temperatures"]), default=None)
            if hottest is not None and hottest >= TEMP_WARN_C:
                severity = "critical" if hottest >= TEMP_CRIT_C else "warning"
                new_alerts.append({"timestamp": now(), "severity": severity, "source": "thermal", "message": f"峰值温度 {hottest}°C"})
            if metrics["disk_free_bytes"] < DISK_WARN:
                new_alerts.append({"timestamp": now(), "severity": "critical", "source": "disk", "message": "磁盘剩余空间低于 2 GiB"})
            if new_alerts:
                with open(run_dir / "alerts.jsonl", "a") as handle:
                    for alert in new_alerts:
                        handle.write(json.dumps(alert, ensure_ascii=False) + "\n")
            elapsed = time.time() - load_started if load_started else 0
            status = {
                "status": "running" if load_started else "starting", "phase": "load_running" if load_started else "vendor_setup",
                "reason": None, "updated_at": now(), "elapsed_s": round(elapsed, 1), "duration_s": args.duration,
                "load_started_epoch": load_started, "owned_pgid": launcher.pid, "live_processes": metrics["owned_processes"],
                "latest_metrics": metrics, "new_alerts": new_alerts, "vendor_log_dir": vendor_log,
            }
            atomic_json(run_dir / "status.json", status)
            if time.time() - last_update >= args.update:
                with open(run_dir / "updates.jsonl", "a") as handle:
                    handle.write(json.dumps(status, ensure_ascii=False) + "\n")
                last_update = time.time()
            if STOP or (run_dir / "stop.request").exists():
                reason = "user_stopped"
            if args.duration and load_started and elapsed >= args.duration:
                reason = "duration_reached"
            if any(alert["severity"] == "critical" for alert in new_alerts):
                reason = "safety_alert"
            if load_started and not metrics["owned_processes"]:
                reason = "workloads_exited"
            if reason:
                break
            sample_no += 1
            time.sleep(max(1, args.interval))
    except Exception as exc:
        reason = "supervisor_exception"
        with open(run_dir / "supervisor.log", "a") as handle:
            handle.write(f"{now()} {type(exc).__name__}: {exc}\n")
    cleanup = stop_group(launcher.pid)
    removed = []
    for item, was_present in existed.items():
        path = Path(item)
        if not was_present and path.exists():
            try:
                if path.is_file() or path.is_symlink():
                    path.unlink()
                    removed.append(item)
            except OSError:
                pass
    cleanup["removed_resources"] = removed
    terminal = dict(status)
    failure_reasons = ("supervisor_exception", "vendor_launcher_exit_1", "workloads_exited", "safety_alert")
    terminal.update(status="failed" if reason in failure_reasons else "finished", reason=reason, phase="terminal",
                    updated_at=now(), ended_epoch=time.time(), cleanup=cleanup, live_processes=cleanup["remaining_processes"])
    atomic_json(run_dir / "status.json", terminal)
    terminal["report"] = str(write_report(run_dir, terminal, metadata))
    atomic_json(run_dir / "status.json", terminal)
    return 0 if terminal["status"] == "finished" else 1


def status_cmd(args):
    status = derive_status(current_record(args.state_dir))
    emit(status, args.json)
    return 0 if status.get("status") != "failed" else 1


def stop_cmd(args):
    record = current_record(args.state_dir)
    if not record:
        emit({"status": "idle", "message": "没有需要停止的测试任务"}, args.json)
        return 0
    run_dir = Path(record["run_dir"])
    metadata = load_json(run_dir / "metadata.json", record)
    if args.run and args.run != metadata.get("run_id"):
        print(json.dumps({"error": "run_id_mismatch", "current": metadata.get("run_id")}, ensure_ascii=False))
        return 4
    current = derive_status(record)
    if current.get("status") in ("finished", "failed", "idle"):
        emit(current, args.json)
        return 0
    (run_dir / "stop.request").touch()
    supervisor = metadata.get("supervisor") or {}
    if same_process(supervisor.get("pid", -1), supervisor.get("start_ticks", -2)):
        os.kill(supervisor["pid"], signal.SIGTERM)
    deadline = time.time() + args.wait
    while time.time() < deadline:
        current = derive_status(record)
        if current.get("status") in ("finished", "failed"):
            break
        time.sleep(0.5)
    emit(current, args.json)
    return 0 if current.get("status") == "finished" else 1


def report_cmd(args):
    record = current_record(args.state_dir)
    if not record:
        print("没有已记录的测试任务", file=sys.stderr)
        return 2
    run_dir = Path(record["run_dir"])
    path = write_report(run_dir, derive_status(record), load_json(run_dir / "metadata.json", record))
    print(path)
    return 0


def run_via_user_manager(action, forwarded_args):
    """通过用户级 systemd 管理器在宿主命名空间执行限定的控制器动作。"""
    systemd_run = shutil.which("systemd-run")
    launch_env, graphical_session = discover_graphical_session_env()
    if not systemd_run or not graphical_session.get("variables", {}).get("DBUS_SESSION_BUS_ADDRESS"):
        print(json.dumps({
            "error": "host_executor_unavailable",
            "message": "无法连接用户级 systemd 管理器；请从宿主终端执行对应命令",
        }, ensure_ascii=False))
        return 7
    unit = f"spacemit-k-stability-{action}-{uuid.uuid4().hex[:8]}"
    command = [
        systemd_run, "--user", "--wait", "--collect", "--pipe", "--quiet",
        f"--unit={unit}", sys.executable, str(Path(__file__).resolve()), action,
        *forwarded_args,
    ]
    try:
        return subprocess.run(command, env=launch_env, check=False).returncode
    except OSError as exc:
        print(json.dumps({
            "error": "host_executor_failed", "message": f"{type(exc).__name__}: {exc}",
        }, ensure_ascii=False))
        return 7


def host_service_cmd(args):
    """由用户级 systemd unit 托管 supervisor，直到本次测试进入终态。"""
    rc = start(args)
    if rc:
        return rc
    record = current_record(args.state_dir)
    metadata = load_json(Path(record["run_dir"]) / "metadata.json", record) if record else {}
    supervisor = metadata.get("supervisor") or {}
    while same_process(supervisor.get("pid", -1), supervisor.get("start_ticks", -2)):
        time.sleep(2)
    return 0


def host_start_cmd(args):
    state_dir = Path(args.state_dir).expanduser()
    existing = derive_status(current_record(state_dir))
    if existing.get("status") in ("starting", "running", "stopping"):
        print(json.dumps({"error": "run_already_active", "existing": existing}, ensure_ascii=False))
        return 3
    systemd_run = shutil.which("systemd-run")
    launch_env, graphical_session = discover_graphical_session_env()
    if not systemd_run or not graphical_session.get("variables", {}).get("DBUS_SESSION_BUS_ADDRESS"):
        print(json.dumps({
            "error": "host_executor_unavailable",
            "message": "无法连接用户级 systemd 管理器；请从宿主终端执行 start",
        }, ensure_ascii=False))
        return 7
    previous_run_id = existing.get("run_id")
    forwarded = [
        "--state-dir", str(state_dir),
        "--duration", str(args.duration), "--interval", str(args.interval),
        "--update", str(args.update),
    ]
    if args.skip_llama:
        forwarded.append("--skip-llama")
    unit = f"spacemit-k-stability-run-{uuid.uuid4().hex[:8]}"
    command = [
        systemd_run, "--user", "--wait", "--collect", "--pipe", "--quiet", f"--unit={unit}",
        sys.executable, str(Path(__file__).resolve()), "_host_service", *forwarded,
    ]
    try:
        dispatcher = subprocess.Popen(
            command, env=launch_env, stdin=subprocess.DEVNULL,
            stdout=subprocess.DEVNULL, stderr=subprocess.DEVNULL,
            start_new_session=True, close_fds=True,
        )
    except OSError as exc:
        print(json.dumps({
            "error": "host_executor_failed", "message": f"{type(exc).__name__}: {exc}",
        }, ensure_ascii=False))
        return 7
    deadline = time.time() + 10
    while time.time() < deadline:
        record = current_record(state_dir)
        if record and record.get("run_id") != previous_run_id:
            emit(derive_status(record), True)
            return 0
        if dispatcher.poll() is not None:
            print(json.dumps({
                "error": "host_dispatch_failed", "message": "systemd-run 在创建运行记录前退出",
                "exit_code": dispatcher.returncode, "unit": unit,
            }, ensure_ascii=False))
            return dispatcher.returncode or 7
        time.sleep(0.2)
    print(json.dumps({
        "error": "host_dispatch_timeout", "message": "宿主 unit 已派发，但 10 秒内未生成新的运行记录",
        "unit": unit,
    }, ensure_ascii=False))
    return 7


def host_stop_cmd(args):
    forwarded = ["--state-dir", str(Path(args.state_dir).expanduser()), "--wait", str(args.wait), "--json"]
    if args.run:
        forwarded.extend(["--run", args.run])
    return run_via_user_manager("stop", forwarded)


def host_report_cmd(args):
    return run_via_user_manager("report", ["--state-dir", str(Path(args.state_dir).expanduser())])


def parser():
    root = argparse.ArgumentParser(description=__doc__)
    sub = root.add_subparsers(dest="command", required=True)
    for name in ("preflight", "status", "stop", "report"):
        cmd = sub.add_parser(name)
        cmd.add_argument("--state-dir", default=str(DEFAULT_STATE))
        if name != "report":
            cmd.add_argument("--json", action="store_true")
        if name == "stop":
            cmd.add_argument("--run")
            cmd.add_argument("--wait", type=int, default=20)
    cmd = sub.add_parser("start")
    cmd.add_argument("--state-dir", default=str(DEFAULT_STATE))
    cmd.add_argument("--duration", type=parse_duration, default=0)
    cmd.add_argument("--interval", type=int, default=60)
    cmd.add_argument("--update", type=int, default=300)
    cmd.add_argument("--skip-llama", action="store_true")
    cmd = sub.add_parser("host-start")
    cmd.add_argument("--state-dir", default=str(DEFAULT_STATE))
    cmd.add_argument("--duration", type=parse_duration, default=0)
    cmd.add_argument("--interval", type=int, default=60)
    cmd.add_argument("--update", type=int, default=300)
    cmd.add_argument("--skip-llama", action="store_true")
    cmd = sub.add_parser("host-stop")
    cmd.add_argument("--state-dir", default=str(DEFAULT_STATE))
    cmd.add_argument("--run")
    cmd.add_argument("--wait", type=int, default=20)
    cmd = sub.add_parser("host-report")
    cmd.add_argument("--state-dir", default=str(DEFAULT_STATE))
    hidden = sub.add_parser("_host_service")
    hidden.add_argument("--state-dir", required=True)
    hidden.add_argument("--duration", type=int, required=True)
    hidden.add_argument("--interval", type=int, required=True)
    hidden.add_argument("--update", type=int, required=True)
    hidden.add_argument("--skip-llama", action="store_true")
    hidden = sub.add_parser("_watch")
    hidden.add_argument("--state-dir", required=True)
    hidden.add_argument("--run", required=True)
    hidden.add_argument("--duration", type=int, required=True)
    hidden.add_argument("--interval", type=int, required=True)
    hidden.add_argument("--update", type=int, required=True)
    return root


def main():
    args = parser().parse_args()
    actions = {"preflight": preflight, "start": start, "_watch": watch, "status": status_cmd,
               "stop": stop_cmd, "report": report_cmd, "host-start": host_start_cmd,
               "host-stop": host_stop_cmd, "host-report": host_report_cmd,
               "_host_service": host_service_cmd}
    return actions[args.command](args)


if __name__ == "__main__":
    raise SystemExit(main())
