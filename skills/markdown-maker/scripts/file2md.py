#!/usr/bin/env python3
"""Local File2MD client: drives the local file2md service on this device."""
from __future__ import annotations

import argparse
import json
import os
import re
import shlex
import shutil
import subprocess
import sys
import tempfile
import time
import zipfile
from pathlib import Path
from typing import Any
from xml.etree import ElementTree

PACKAGE = "file2md"
SUPPORTED = {".pdf", ".ppt", ".pptx", ".doc", ".docx", ".xls", ".xlsx", ".txt",
             ".png", ".jpg", ".jpeg", ".jp2", ".webp", ".gif", ".bmp", ".tiff"}
DEFAULT_OUTPUT_DIR = Path.home() / "File2MD"
API_HOST = os.getenv("FILE2MD_WEB_HOST", "127.0.0.1")
API_PORT = os.getenv("FILE2MD_WEB_PORT", "8070")
API_BASE = os.getenv("FILE2MD_API_BASE", f"http://{API_HOST}:{API_PORT}")

ERROR_MESSAGES = {
    "SERVICE_UNREACHABLE": "File2MD 服务当前不可访问。",
    "FILE2MD_API_STALLED": "File2MD API 在转换期间持续无响应。",
    "FILE2MD_SERVICE_RESTARTED": "File2MD 服务在转换期间发生了重启。",
    "WORKER_OOM_KILLED": "文档推理进程因系统内存不足被终止。",
    "SPACEMIT_TCM_ACQUIRE_FAILED": "SpaceMIT 推理运行时无法申请 TCM。",
    "TCM_STALE_ALLOCATION": "检测到已经退出的进程仍占用 TCM。",
    "TCM_BUSY": "TCM 正在被其他有效推理进程使用。",
    "TCM_RECOVERY_FAILED": "清理 TCM 后资源仍未恢复。",
    "CONVERSION_STALLED": "文档转换长时间没有产生新进展，已确认工作进程也没有活动。",
    "CLIENT_WAIT_LIMIT_REACHED": "Bibit 已达到本次等待上限，但 File2MD 任务仍在运行。",
    "UPSTREAM_OPERATION_TIMEOUT": "File2MD 的底层依赖主动报告操作超时。",
    "FORMULA_RESULT_NOT_CACHED": "XLSX 中存在没有缓存计算结果的公式。",
    "FORMULA_CACHE_RECALC_FAILED": "XLSX 公式自动重算失败，转换结果中的公式值可能为空。",
    "LIBREOFFICE_RECALC_FAILED": "LibreOffice 无法重算 XLSX 公式。",
    "OUTPUT_MISSING": "转换任务没有生成 Markdown 结果。",
    "MARKDOWN_EMPTY": "转换生成的 Markdown 内容为空。",
    "MODEL_NOT_READY": "File2MD 模型尚未就绪。",
    "MODEL_LOAD_FAILED": "File2MD 模型加载失败。",
    "MODEL_PREPARE_FAILED": "File2MD EP 推理线程切换失败。",
    "UPLOAD_FAILED": "文档提交到 File2MD 失败。",
    "CONVERSION_FAILED": "文档转换失败。",
    "INVALID_DOCUMENT": "输入文件已损坏，或其内容与文件扩展名不符。",
    "INVALID_FILE_SIGNATURE": "输入文件不是有效的文档容器。",
    "INVALID_XLSX": "XLSX 文件结构不完整或已损坏。",
}

ERROR_REMEDIATION = {
    "WORKER_OOM_KILLED": ["等待设备释放内存后重试", "拆分较大的文档", "关闭流程图和图注等可选阶段", "联系设备管理员处理系统内存压力"],
    "SPACEMIT_TCM_ACQUIRE_FAILED": ["等待当前推理任务结束后重试", "检查 TCM owner PID 是否仍然存在", "仅在没有有效占用者时清理 TCM"],
    "TCM_STALE_ALLOCATION": ["确认没有其他 NPU 推理任务", "清理死亡进程遗留的 TCM block", "重新启动 File2MD 工作进程后重试一次"],
    "TCM_BUSY": ["等待当前 NPU 推理任务完成", "不要在有效进程占用 TCM 时强制清理"],
    "TCM_RECOVERY_FAILED": ["停止 File2MD 推理任务后重新检查 TCM", "由设备管理员清理 TCM 或重启设备"],
    "FILE2MD_API_STALLED": ["保留任务编号并检查 File2MD 日志", "终止卡住的 File2MD 工作进程", "确认 TCM 和内存状态后再重试"],
    "FILE2MD_SERVICE_RESTARTED": ["检查任务开始后的 File2MD 日志", "确认是否发生 OOM 或原生推理崩溃", "服务恢复就绪后重新提交任务"],
    "CONVERSION_STALLED": ["查看任务返回的内存和 TCM 诊断", "确认后调用任务取消接口结束该 worker", "排除根因后再重新提交文档"],
    "CLIENT_WAIT_LIMIT_REACHED": ["使用任务编号继续查询状态", "不要把客户端停止等待误判为转换失败", "需要结束任务时调用取消接口"],
    "FORMULA_RESULT_NOT_CACHED": ["安装 LibreOffice Calc 后重新转换", "先用表格软件打开并保存文件以生成公式缓存"],
    "LIBREOFFICE_RECALC_FAILED": ["确认 LibreOffice Calc 已安装", "检查临时目录权限", "手动打开并保存 XLSX 后重试"],
    "OUTPUT_MISSING": ["保留结果 ZIP 和任务编号", "检查 File2MD 输出目录和服务日志"],
    "INVALID_DOCUMENT": ["确认文件扩展名与实际内容一致", "用原始应用重新导出或另存后再试", "如果文件来自网盘或聊天工具，重新下载以排除截断"],
    "INVALID_FILE_SIGNATURE": ["确认文件扩展名与实际内容一致", "用原始应用重新导出后再试"],
    "CONVERSION_FAILED": ["查看服务日志中该任务的完整异常", "保留任务编号以便进一步定位", "确认输入文件可被原始应用正常打开后重试"],
    "UNSUPPORTED_FORMAT": ["改用 PDF、PPTX、DOCX、XLSX、PNG、JPG 等受支持格式", "或先转换为 PDF 再提交"],
    "FILE_TOO_LARGE": ["压缩或拆分输入文件后再试", "必要时由管理员调高上传大小上限"],
    "MODEL_NOT_READY": ["等待 /api/models 返回 ready 后重试", "检查 File2MD 服务日志确认模型加载状态"],
    "MODEL_LOAD_FAILED": ["检查模型文件是否完整", "检查磁盘空间是否充足", "重新安装 File2MD 运行时"],
    "MODEL_PREPARE_FAILED": ["确认当前没有其它转换任务在运行", "查看 worker 与 TCM 诊断后再重试"],
    "UPLOAD_FAILED": ["检查 File2MD 服务是否可用", "检查磁盘空间与上传大小限制"],
    "MARKDOWN_EMPTY": ["确认源文件包含可识别内容", "检查识别日志后重试"],
    "OUTPUT_DOWNLOAD_FAILED": ["保留任务编号", "服务恢复就绪后重新下载结果"],
    "SERVICE_UNREACHABLE": ["检查 systemctl status file2md.service", "检查服务端口与日志后重试"],
}

# Fallback advice for any code without an explicit entry above.  Returning an
# empty list here is what made "文档转换失败。" appear with no next step.
GENERIC_REMEDIATION = ["查看任务返回的 stage、root_cause 与 raw_message", "按任务编号检查 File2MD 服务日志", "排除原因后重新提交文档"]


class SkillError(RuntimeError):
    def __init__(
        self,
        code: str,
        message: str,
        remediation: list[str] | None = None,
        *,
        stage: str = "",
        root_cause: str = "",
        retryable: bool = False,
        details: dict[str, Any] | None = None,
    ):
        self.code = code
        self.message = message
        self.remediation = remediation or []
        self.stage = stage
        self.root_cause = root_cause
        self.retryable = retryable
        self.details = details or {}
        super().__init__(message)

    def payload(self) -> dict[str, Any]:
        return {
            "status": "failed",
            "code": self.code,
            "message": ERROR_MESSAGES.get(self.code, self.message),
            "stage": self.stage or None,
            "root_cause": self.root_cause or None,
            "raw_message": self.message,
            "retryable": self.retryable,
            "remediation": self.remediation or ERROR_REMEDIATION.get(self.code, GENERIC_REMEDIATION),
            "details": self.details or None,
        }


def run(command: str, timeout: int = 120) -> tuple[int, str, str]:
    try:
        proc = subprocess.run(
            command,
            shell=True,
            check=False,
            capture_output=True,
            text=True,
            timeout=timeout,
        )
    except subprocess.TimeoutExpired as exc:
        raise SkillError(
            "LOCAL_COMMAND_TIMEOUT",
            f"{command[:160]} exceeded {timeout}s",
            ["Retry after the device is responsive", "Inspect stuck jobs or sudo prompts"],
        ) from exc
    except FileNotFoundError as exc:
        raise SkillError(
            "LOCAL_COMMAND_NOT_FOUND",
            f"{command[:160]}: {exc}",
            ["Install the missing binary", "Check PATH for curl/systemctl/dpkg/apt-get/journalctl"],
        ) from exc
    return proc.returncode, proc.stdout, proc.stderr


def memory_snapshot() -> dict[str, int]:
    values: dict[str, int] = {}
    try:
        for line in Path("/proc/meminfo").read_text(encoding="utf-8").splitlines():
            name, separator, raw = line.partition(":")
            if separator and name in {"MemTotal", "MemAvailable", "SwapTotal", "SwapFree"}:
                match = re.search(r"\d+", raw)
                if match:
                    values[f"{name.lower()}_kb"] = int(match.group())
    except OSError:
        pass
    return values


def pid_details(pid: int) -> dict[str, Any]:
    path = Path("/proc") / str(pid)
    alive = path.is_dir()
    command = ""
    if alive:
        try:
            command = (path / "comm").read_text(encoding="utf-8", errors="replace").strip()
        except OSError:
            pass
    return {"pid": pid, "alive": alive, "command": command}


def tcm_snapshot() -> dict[str, Any]:
    code, out, err = run("spacemit-tcm-smi 2>&1", timeout=15)
    raw = (out or err).strip()
    if code:
        return {"available": False, "raw": raw, "owners": []}
    summary = re.search(r"available_blocks=(\d+)/(\d+)", raw)
    owners: list[dict[str, Any]] = []
    blocks: list[dict[str, Any]] = []
    for line in raw.splitlines():
        match = re.match(r"^\s*(\d+)\s+(\S+)\s+(\d+)\s+\S+\s+\S+\s+(\S+)\s*$", line)
        if not match:
            continue
        block = {"id": int(match.group(1)), "state": match.group(2), "pid": None}
        pid_text = match.group(4)
        if pid_text.isdigit():
            details = pid_details(int(pid_text))
            block["pid"] = details["pid"]
            if details not in owners:
                owners.append(details)
        blocks.append(block)
    return {
        "available": True,
        "available_blocks": int(summary.group(1)) if summary else None,
        "total_blocks": int(summary.group(2)) if summary else None,
        "owners": owners,
        "blocks": blocks,
        "raw": raw,
    }


def recover_stale_tcm(snapshot: dict[str, Any]) -> dict[str, Any]:
    live = [owner for owner in snapshot.get("owners", []) if owner.get("alive")]
    if live:
        raise SkillError(
            "TCM_BUSY",
            f"TCM owners are still alive: {live}",
            stage="preflight",
            root_cause="TCM_OWNED_BY_LIVE_PROCESS",
            retryable=True,
            details={"tcm": snapshot},
        )
    busy_blocks = [block for block in snapshot.get("blocks", []) if block.get("state") != "free"]
    if not busy_blocks:
        return snapshot
    unowned_busy = [block for block in busy_blocks if block.get("pid") is None]
    if unowned_busy or not snapshot.get("owners"):
        raise SkillError(
            "TCM_BUSY",
            f"busy TCM blocks have no verifiable owner: {unowned_busy or busy_blocks}",
            stage="recovery",
            root_cause="TCM_OWNER_UNKNOWN",
            retryable=True,
            details={"tcm": snapshot},
        )
    code, out, err = run("spacemit-tcm-smi -c", timeout=30)
    if code:
        code, out, err = run("sudo -n -p '' spacemit-tcm-smi -c", timeout=30)
    if code:
        raise SkillError(
            "TCM_RECOVERY_FAILED",
            (err or out or "spacemit-tcm-smi -c failed")[-1200:],
            stage="recovery",
            root_cause="TCM_CLEAR_COMMAND_FAILED",
            details={"before": snapshot},
        )
    after = tcm_snapshot()
    total = after.get("total_blocks")
    if not after.get("available") or total is None or after.get("available_blocks") != total:
        raise SkillError(
            "TCM_RECOVERY_FAILED",
            "TCM blocks were not fully released",
            stage="recovery",
            root_cause="TCM_BLOCKS_REMAIN_BUSY",
            details={"before": snapshot, "after": after},
        )
    return after


def tcm_preflight(*, auto_recover: bool, required: bool) -> tuple[dict[str, Any], list[dict[str, Any]]]:
    snapshot = tcm_snapshot()
    warnings: list[dict[str, Any]] = []
    if not snapshot.get("available"):
        warnings.append({"code": "TCM_STATUS_UNAVAILABLE", "message": "无法读取 TCM 状态，将继续由 File2MD 判断。"})
        return snapshot, warnings
    if not required:
        return snapshot, warnings
    live = [owner for owner in snapshot.get("owners", []) if owner.get("alive")]
    dead = [owner for owner in snapshot.get("owners", []) if not owner.get("alive")]
    busy_blocks = [block for block in snapshot.get("blocks", []) if block.get("state") != "free"]
    unowned_busy = [block for block in busy_blocks if block.get("pid") is None]
    if live:
        raise SkillError(
            "TCM_BUSY",
            f"live TCM owners: {live}",
            stage="preflight",
            root_cause="TCM_OWNED_BY_LIVE_PROCESS",
            retryable=True,
            details={"tcm": snapshot},
        )
    if unowned_busy:
        raise SkillError(
            "TCM_BUSY",
            f"busy TCM blocks have no verifiable owner: {unowned_busy}",
            stage="preflight",
            root_cause="TCM_OWNER_UNKNOWN",
            retryable=True,
            details={"tcm": snapshot},
        )
    if dead:
        if not auto_recover:
            raise SkillError(
                "TCM_STALE_ALLOCATION",
                f"dead TCM owners: {dead}; unowned busy blocks: {unowned_busy}",
                stage="preflight",
                root_cause="TCM_OWNER_PID_NOT_FOUND",
                retryable=True,
                details={"tcm": snapshot},
            )
        after = recover_stale_tcm(snapshot)
        warnings.append({"code": "TCM_STALE_ALLOCATION_RECOVERED", "message": "已清理死亡进程遗留的 TCM，并验证全部 block 可用。", "before": snapshot, "after": after})
        snapshot = after
    return snapshot, warnings


def cleanup_oom_tcm_residue(worker_pid: Any, *, enabled: bool) -> dict[str, Any]:
    result: dict[str, Any] = {
        "checked": True,
        "cleanup_attempted": False,
        "cleanup_succeeded": False,
        "worker_pid": worker_pid,
    }
    before = tcm_snapshot()
    result["before"] = before
    if not before.get("available"):
        result.update(reason="TCM_STATUS_UNAVAILABLE", recommendation="由设备管理员检查 TCM 状态后再转换")
        return result
    busy = [block for block in before.get("blocks", []) if block.get("state") != "free"]
    if not busy:
        result.update(cleanup_succeeded=True, reason="NO_TCM_RESIDUE")
        return result
    owners = before.get("owners", [])
    live = [owner for owner in owners if owner.get("alive")]
    unknown = [block for block in busy if block.get("pid") is None]
    dead_pids = {owner.get("pid") for owner in owners if not owner.get("alive")}
    try:
        normalized_worker_pid = int(worker_pid)
    except (TypeError, ValueError):
        normalized_worker_pid = 0
    foreign_dead = [pid for pid in dead_pids if pid != normalized_worker_pid]
    if live or unknown or not normalized_worker_pid or normalized_worker_pid not in dead_pids or foreign_dead:
        result.update(
            reason="TCM_OWNERSHIP_NOT_EXCLUSIVE_TO_OOM_WORKER",
            live_owners=live,
            unknown_blocks=unknown,
            foreign_dead_owners=foreign_dead,
            recommendation="不要自动清理；确认没有其他 NPU 任务后由设备管理员处理",
        )
        return result
    if not enabled:
        result.update(reason="AUTO_CLEANUP_DISABLED", recommendation="启用安全清理或由设备管理员清理该死亡 worker 的 TCM 残留")
        return result
    result["cleanup_attempted"] = True
    try:
        after = recover_stale_tcm(before)
    except SkillError as exc:
        result.update(
            reason="TCM_CLEANUP_FAILED",
            cleanup_error=exc.payload(),
            recommendation="停止新的 NPU 任务，由设备管理员清理 TCM 或重启设备",
        )
        return result
    result.update(cleanup_succeeded=True, reason="OOM_WORKER_TCM_RESIDUE_CLEARED", after=after)
    return result


def xlsx_cached_value_present(cell: Any) -> bool:
    """Report whether one formula cell carries a usable cached result.

    A cell counts as cached only when its ``<v>`` node exists *and* holds
    non-empty text.  Writers differ on how they express "no result stored
    yet": some omit the node, others emit an empty ``<v></v>``.  Both mean the
    cached value is unusable, so the cell still needs recalculation.  Keep this
    in step with the same helper in the File2MD service.
    """
    value = cell.find("{*}v")
    if value is None:
        return False
    return bool((value.text or "").strip())


XLSX_REQUIRED_PARTS = ("[Content_Types].xml", "xl/workbook.xml")


def xlsx_uncached_formula_cells(path: Path) -> list[str]:
    """Return formula cells without a usable cached value in an XLSX file."""
    missing: list[str] = []
    try:
        with zipfile.ZipFile(path) as archive:
            names = set(archive.namelist())
            absent = [part for part in XLSX_REQUIRED_PARTS if part not in names]
            if absent:
                raise SkillError(
                    "INVALID_FILE_SIGNATURE",
                    f"XLSX 缺少必要部件：{', '.join(absent)}",
                    ["确认文件扩展名与内容一致", "用 Excel 或 LibreOffice 重新导出后再试"],
                    stage="xlsx_preflight",
                    root_cause="INVALID_XLSX_CONTAINER",
                )
            worksheets = sorted(name for name in names if re.fullmatch(r"xl/worksheets/sheet\d+\.xml", name))
            if not worksheets:
                raise SkillError(
                    "INVALID_FILE_SIGNATURE",
                    "XLSX 缺少工作表部件",
                    ["确认文件扩展名与内容一致", "用 Excel 或 LibreOffice 重新导出后再试"],
                    stage="xlsx_preflight",
                    root_cause="INVALID_XLSX_CONTAINER",
                )
            for worksheet in worksheets:
                root = ElementTree.fromstring(archive.read(worksheet))
                sheet_name = Path(worksheet).stem
                for cell in root.findall(".//{*}c"):
                    if cell.find("{*}f") is None:
                        continue
                    if not xlsx_cached_value_present(cell):
                        missing.append(f"{sheet_name}!{cell.attrib.get('r', '?')}")
    except SkillError:
        raise
    except (OSError, zipfile.BadZipFile, ElementTree.ParseError) as exc:
        raise SkillError(
            "INVALID_FILE_SIGNATURE",
            str(exc),
            ["确认 XLSX 文件没有损坏"],
            stage="xlsx_preflight",
            root_cause="INVALID_XLSX_CONTAINER",
        ) from exc
    return missing


def recalculate_xlsx(source: Path, destination: Path, cells: list[str]) -> dict[str, Any]:
    executable = shutil.which("libreoffice") or shutil.which("soffice")
    if not executable:
        raise SkillError(
            "FORMULA_RESULT_NOT_CACHED",
            f"uncached formula cells: {cells[:100]}",
            stage="xlsx_preflight",
            root_cause="LIBREOFFICE_NOT_INSTALLED",
            details={"formula_cells": cells},
        )
    with tempfile.TemporaryDirectory(prefix="file2md-xlsx-") as temporary:
        root = Path(temporary)
        input_dir = root / "input"
        output_dir = root / "output"
        profile = root / "profile"
        input_dir.mkdir()
        output_dir.mkdir()
        profile.mkdir()
        staged = input_dir / source.name
        shutil.copy2(source, staged)
        command = [
            executable,
            f"-env:UserInstallation={profile.resolve().as_uri()}",
            "--headless",
            "--nologo",
            "--nodefault",
            "--nolockcheck",
            "--convert-to",
            "xlsx",
            "--outdir",
            str(output_dir),
            str(staged),
        ]
        environment = os.environ.copy()
        environment.update(
            HOME=str(root),
            XDG_CACHE_HOME=str(root / "cache"),
            XDG_CONFIG_HOME=str(root / "config"),
            XDG_RUNTIME_DIR=str(root / "runtime"),
            SAL_USE_VCLPLUGIN="svp",
            QT_QPA_PLATFORM="offscreen",
        )
        for directory in (root / "cache", root / "config", root / "runtime"):
            directory.mkdir(mode=0o700)
        try:
            proc = subprocess.run(command, check=False, capture_output=True, text=True, timeout=180, env=environment)
        except (OSError, subprocess.TimeoutExpired) as exc:
            raise SkillError(
                "LIBREOFFICE_RECALC_FAILED",
                str(exc),
                stage="xlsx_preflight",
                root_cause="LIBREOFFICE_EXECUTION_FAILED",
                details={"formula_cells": cells},
            ) from exc
        converted = output_dir / staged.name
        if proc.returncode or not converted.is_file():
            raise SkillError(
                "LIBREOFFICE_RECALC_FAILED",
                (proc.stderr or proc.stdout or "LibreOffice did not produce an XLSX file")[-1200:],
                stage="xlsx_preflight",
                root_cause="LIBREOFFICE_CONVERSION_FAILED",
                details={"formula_cells": cells},
            )
        remaining = xlsx_uncached_formula_cells(converted)
        if remaining:
            raise SkillError(
                "LIBREOFFICE_RECALC_FAILED",
                f"formula cache is still empty: {remaining[:100]}",
                stage="xlsx_preflight",
                root_cause="FORMULA_CACHE_REMAINED_EMPTY",
                details={"formula_cells": remaining},
            )
        shutil.copy2(converted, destination)
    return {"code": "FORMULA_CACHE_REBUILT", "message": "已在临时副本中重算 XLSX 公式，原文件未修改。", "formula_cells": cells}


def package_state() -> dict[str, str]:
    """Read installed/candidate versions without assuming a package release."""
    code, raw, _ = run("dpkg-query -W -f='${Status}\\t${Version}\\t${Architecture}' file2md 2>/dev/null || true")
    fields = raw.strip().split("\t")
    installed = fields[1] if len(fields) > 1 and fields[0] == "install ok installed" else ""
    architecture = fields[2] if len(fields) > 2 else ""
    _, candidate, _ = run("LC_ALL=C apt-cache policy file2md 2>/dev/null | awk '/Candidate:/ {print $2; exit}'")
    return {"installed": installed, "candidate": candidate.strip(), "architecture": architecture, "raw": raw.strip()}


def version_is_newer(old: str, new: str) -> bool:
    if not old or not new or old == new:
        return False
    code, _, _ = run(f"dpkg --compare-versions {shlex.quote(new)} gt {shlex.quote(old)}")
    return code == 0


def apt_update() -> tuple[bool, str]:
    code, out, err = run("sudo -n -p '' apt-get update", timeout=300)
    if code != 0:
        return False, (err or out).strip()[-1200:]
    return True, ""


def install_latest_package(upgrade_only: bool = False) -> None:
    mode = "--only-upgrade " if upgrade_only else ""
    code, out, err = run(f"sudo -n -p '' apt-get install -y {mode}{PACKAGE}", timeout=600)
    if code:
        detail = (err or out).strip()[-1200:]
        if "password" in detail.lower() or "not allowed" in detail.lower() or "may not run" in detail.lower():
            raise SkillError(
                "PRIVILEGE_REQUIRED",
                detail,
                ["Run the command under sudo or as root", "Configure passwordless sudo for apt-get / dpkg"],
            )
        raise SkillError(
            "APT_INSTALL_FAILED",
            detail,
            ["Confirm sudo permission", "Confirm the APT source has a riscv64 file2md package", "Check dependencies and disk space"],
        )


def get_json(url: str, *, attempts: int = 2, curl_timeout: int = 10) -> dict[str, Any]:
    last_error = "File2MD API unavailable"
    for attempt in range(max(1, attempts)):
        code, out, err = run(f"curl -fsS --max-time {curl_timeout} {shlex.quote(url)}", timeout=curl_timeout + 5)
        if code == 0:
            try:
                value = json.loads(out)
            except json.JSONDecodeError as exc:
                raise SkillError("API_INVALID_RESPONSE", out[:500], ["Inspect file2md.service logs and package version"]) from exc
            if isinstance(value, dict):
                return value
            raise SkillError("API_INVALID_RESPONSE", "API returned a non-object JSON value", ["Inspect the File2MD API version"])
        last_error = err.strip() or out.strip() or last_error
        if attempt + 1 < attempts:
            time.sleep(2)
    raise SkillError("SERVICE_UNREACHABLE", last_error, ["Check file2md.service state and configured API port"])


def prepare_model_threads(threads: int) -> dict[str, Any]:
    payload = shlex.quote(json.dumps({"threads": max(1, int(threads))}))
    command = (
        "curl -fsS --max-time 240 -X POST -H "
        + shlex.quote("Content-Type: application/json")
        + f" --data {payload} {shlex.quote(API_BASE + '/api/models/prepare')}"
    )
    code, out, err = run(command, timeout=250)
    if code:
        raise SkillError(
            "MODEL_PREPARE_FAILED",
            (err or out or "model worker preparation failed")[-1200:],
                ["确认当前没有正在转换的任务", "检查 File2MD 模型 worker 日志", "等待模型 worker 恢复 ready 后重试"],
                stage="model",
                root_cause="EP_THREAD_UPDATE_FAILED",
            retryable=True,
        )
    try:
        result = json.loads(out)
    except json.JSONDecodeError as exc:
        raise SkillError("API_INVALID_RESPONSE", out[:1200], ["检查 /api/models/prepare 返回值"]) from exc
    if not isinstance(result, dict) or result.get("status") != "ready":
        raise SkillError(
            "MODEL_PREPARE_FAILED",
            json.dumps(result, ensure_ascii=False),
            ["检查模型文件、TCM 和 File2MD 日志"],
            stage="model",
            root_cause="MODEL_WORKER_NOT_READY",
            retryable=True,
        )
    return result


def service_diagnostics(since_epoch: int | None = None) -> tuple[str, str]:
    state = ""
    try:
        _, state, _ = run("systemctl show file2md.service -p ActiveState -p SubState -p MainPID -p NRestarts -p ExecMainStatus 2>/dev/null", timeout=20)
    except SkillError as exc:
        state = f"diagnostics_error={exc.message}"
    journal = ""
    try:
        since = f"--since=@{since_epoch} " if since_epoch else "-n 120 "
        _, journal, _ = run(f"journalctl -u file2md.service {since}--no-pager 2>/dev/null", timeout=30)
    except SkillError as exc:
        journal = f"diagnostics_error={exc.message}"
    return state.strip(), journal[-12000:]


def kernel_diagnostics(since_epoch: int | None = None) -> str:
    since = f"--since=@{since_epoch} " if since_epoch else "-n 120 "
    code, out, _ = run(f"journalctl -k {since}--no-pager 2>/dev/null", timeout=30)
    if code != 0:
        _, out, _ = run("dmesg --ctime 2>/dev/null | tail -n 120", timeout=30)
    relevant = [
        line for line in out.splitlines()
        if re.search(r"(out of memory|oom-kill|killed process|memory cgroup out of memory)", line, re.IGNORECASE)
    ]
    return "\n".join(relevant)[-8000:]


def systemd_snapshot(state: str) -> dict[str, str]:
    return {key.lower(): value.strip() for key, value in re.findall(r"^([A-Za-z]+)=(.*)$", state, re.MULTILINE)}


def service_state() -> tuple[str, dict[str, str]]:
    state, _ = service_diagnostics()
    return state, systemd_snapshot(state)


def service_command_error(action: str, detail: str) -> SkillError:
    low = detail.lower()
    if any(term in low for term in ("authentication", "password", "not allowed", "not in the sudoers", "may not run")):
        return SkillError(
            "PRIVILEGE_REQUIRED",
            detail,
            [
                f"Grant the user passwordless sudo for `systemctl {action} file2md.service`",
                f"Run the command manually under sudo: sudo systemctl {action} file2md.service",
            ],
        )
    return SkillError(
        f"SERVICE_{action.upper()}_FAILED",
        detail,
        ["Inspect systemctl status file2md.service", "Inspect journalctl -u file2md.service"],
    )


def invoke_service_action(action: str) -> None:
    code, out, err = run(f"sudo -n -p '' systemctl {action} file2md.service", timeout=90)
    if code:
        raise service_command_error(action, (err or out or f"systemctl {action} failed")[:1200])


def wait_for_service(action: str, wait_seconds: int) -> dict[str, Any]:
    deadline = time.time() + max(1, wait_seconds)
    last_state = ""
    last_health: dict[str, Any] | None = None
    while time.time() < deadline:
        last_state, parsed = service_state()
        if action == "stop":
            if parsed.get("activestate") == "inactive" or (parsed.get("activestate") == "failed" and parsed.get("mainpid") == "0"):
                return {"service": parsed, "model_status": "stopped", "forced": parsed.get("activestate") == "failed"}
        elif parsed.get("activestate") == "active" and parsed.get("substate") == "running":
            try:
                health = get_json(API_BASE + "/api/health", attempts=1, curl_timeout=5)
                models = get_json(API_BASE + "/api/models", attempts=1, curl_timeout=5)
                last_health = {"health": health, "models": models}
                if health.get("engine_ready") and health.get("model_status") == "ready" and models.get("status") == "ready":
                    return {"service": parsed, **last_health}
                if str(models.get("status", "")).lower() in {"failed", "error"}:
                    raise SkillError(
                        "MODEL_LOAD_FAILED",
                        json.dumps(models, ensure_ascii=False),
                        ["Inspect model files and disk space", "Inspect journalctl -u file2md.service", "Repair or reinstall the runtime"],
                    )
            except SkillError as exc:
                if exc.code == "MODEL_LOAD_FAILED":
                    raise
        time.sleep(2)
    if action == "stop":
        raise SkillError("SERVICE_STOP_TIMEOUT", last_state, ["Inspect systemctl status file2md.service", "Check whether systemd is waiting for a worker to exit"])
    raise SkillError(
        "MODEL_NOT_READY",
        json.dumps({"systemd": last_state, "last_health": last_health}, ensure_ascii=False),
        ["Inspect journalctl -u file2md.service", "Confirm local model files are complete", "Increase --wait if model initialization is still progressing"],
    )


def manage_service(args: argparse.Namespace) -> None:
    if args.action == "status":
        state, parsed = service_state()
        result: dict[str, Any] = {"status": "ok", "action": "status", "service": parsed}
        if parsed.get("activestate") == "active" and parsed.get("substate") == "running":
            try:
                result["health"] = get_json(API_BASE + "/api/health", attempts=1, curl_timeout=5)
                result["models"] = get_json(API_BASE + "/api/models", attempts=1, curl_timeout=5)
            except SkillError as exc:
                result.update(status="degraded", code=exc.code, message=exc.message)
        else:
            result.update(status="stopped", model_status="stopped", raw_state=state)
        print(json.dumps(result, ensure_ascii=False, indent=2))
        return
    invoke_service_action(args.action)
    result = wait_for_service(args.action, args.wait)
    print(json.dumps({"status": "completed", "action": args.action, **result}, ensure_ascii=False, indent=2))


def classify_service_failure(job_id: str, original: SkillError, baseline_state: str = "", last_progress: Any = None, since_epoch: int | None = None) -> SkillError:
    state, journal = service_diagnostics(since_epoch)
    kernel = kernel_diagnostics(since_epoch)
    low = (state + " " + journal + " " + kernel).lower()
    before = systemd_snapshot(baseline_state)
    after = systemd_snapshot(state)
    restarted = ((before.get("mainpid") and after.get("mainpid") and before["mainpid"] != after["mainpid"]) or (before.get("nrestarts", "").isdigit() and after.get("nrestarts", "").isdigit() and int(after["nrestarts"]) > int(before["nrestarts"])))
    tcm = tcm_snapshot()
    dead_owners = [owner for owner in tcm.get("owners", []) if not owner.get("alive")]
    if "tcm buffer acquire failed" in low or "spacemitexecutionprovider" in low and "tcm" in low:
        return SkillError("SPACEMIT_TCM_ACQUIRE_FAILED", journal[-1200:], stage="layout", root_cause="TCM_BUFFER_UNAVAILABLE", retryable=True, details={"job_id": job_id, "tcm": tcm})
    if dead_owners:
        return SkillError("TCM_STALE_ALLOCATION", f"dead TCM owners: {dead_owners}", stage="layout", root_cause="TCM_OWNER_PID_NOT_FOUND", retryable=True, details={"job_id": job_id, "tcm": tcm})
    oom_evidence = re.search(r"(out of memory|oom-kill|killed process\s+\d+.*(?:python|file2md)|memoryerror|exit (?:code )?137)", low)
    if oom_evidence:
        return SkillError("WORKER_OOM_KILLED", (kernel or journal)[-1200:] or f"job={job_id}; {original.message}; {state}", stage="inference", root_cause="SYSTEM_OOM", details={"job_id": job_id, "memory": memory_snapshot()})
    if restarted:
        return SkillError("FILE2MD_SERVICE_RESTARTED", f"job={job_id}; {original.message}; before={baseline_state}; after={state}", stage="service", root_cause="SERVICE_PID_CHANGED", retryable=True)
    if after.get("activestate") == "active" and after.get("substate") == "running":
        return SkillError("FILE2MD_API_STALLED", f"job={job_id}; no API response during inference; progress={last_progress}; {state}", stage="api", root_cause="API_UNRESPONSIVE", retryable=True, details={"tcm": tcm, "memory": memory_snapshot()})
    return SkillError("SERVICE_UNREACHABLE", f"job={job_id}; {original.message}; {state}", ["Check systemctl status file2md.service and the configured API port", "Inspect journalctl -u file2md.service", "Retry after the service is active and model_status is ready"])


def classify_job_failure(job: dict[str, Any], journal: str = "") -> SkillError:
    code = str(job.get("code", "")).strip()
    if code:
        remediation = job.get("remediation")
        return SkillError(
            code,
            str(job.get("raw_message") or job.get("error") or job.get("message") or code),
            remediation if isinstance(remediation, list) else [],
            stage=str(job.get("stage", "")),
            root_cause=str(job.get("root_cause", "")),
            retryable=bool(job.get("retryable", False)),
            details={"worker_pid": job.get("worker_pid")},
        )
    job_raw = " ".join(str(job.get(key, "")) for key in ("error", "logs", "status", "message"))
    raw = job_raw + " " + journal
    low = raw.lower()
    job_low = job_raw.lower()
    if "tcm buffer acquire failed" in low or "spacemitexecutionprovider" in low and "tcm" in low:
        return SkillError("SPACEMIT_TCM_ACQUIRE_FAILED", raw[:1200], stage="layout", root_cause="TCM_BUFFER_UNAVAILABLE", retryable=True)
    if re.search(r"(out of memory|oom-kill|killed process\s+\d+.*(?:python|file2md)|memoryerror|exit (?:code )?137)", low):
        return SkillError("WORKER_OOM_KILLED", raw[:1200], stage="inference", root_cause="SYSTEM_OOM")
    if any(term in job_low for term in ("libreoffice", "soffice", "convert-to", "dconf", "fatal error")):
        return SkillError("LIBREOFFICE_CONVERSION_FAILED", raw[:1200], ["Check that LibreOffice is installed", "Check temporary directory permissions and fonts", "Retry Office conversion"])
    if "table" in job_low:
        return SkillError("TABLE_FAILED", raw[:1200], ["Keep any partial output", "Retry with a clearer table image and lower load"])
    if any(term in job_low for term in ("formula", "mfr")):
        return SkillError("FORMULA_FAILED", raw[:1200], ["Keep any partial output", "Retry with a clearer formula image and suitable DPI"])
    if any(term in job_low for term in ("ocr", "paddleocr", "text detection", "text recognition", "layout")):
        return SkillError("OCR_FAILED", raw[:1200], ["Check image quality and language", "Retry with a suitable DPI or clearer input"])
    if "recognition" in job_low:
        return SkillError("RECOGNITION_PARTIAL_FAILED", raw[:1200], ["Keep any partial output", "Retry with a clearer input and lower load"])
    if any(term in low for term in ("model", "onnx", "session", "weights", "模型")):
        return SkillError("MODEL_LOAD_FAILED", raw[:1200], ["Check /api/models and model files", "Check disk space and model checksums", "Reinstall or repair the File2MD runtime"])
    if any(term in low for term in ("libreoffice", "soffice", "convert-to")):
        return SkillError("LIBREOFFICE_CONVERSION_FAILED", raw[:1200], ["Check that LibreOffice is installed", "Check temporary directory permissions and fonts", "Retry Office conversion"])
    if any(term in low for term in ("ocr", "layout", "det", "rec")):
        return SkillError("OCR_FAILED", raw[:1200], ["Check image quality and language", "Retry with a suitable DPI or clearer input"])
    if any(term in low for term in ("table", "formula", "recognition", "公式", "表格")):
        return SkillError("RECOGNITION_PARTIAL_FAILED", raw[:1200], ["Keep any partial output", "Retry with a clearer input and lower load"])
    if any(term in low for term in ("timeout", "timed out", "超时")):
        return SkillError("UPSTREAM_OPERATION_TIMEOUT", raw[:1200], stage="inference", root_cause="DEPENDENCY_REPORTED_TIMEOUT", retryable=True)
    if any(term in low for term in ("data format error", "failed to load document", "not a zip file", "no item named", "content_types", "unsupported format", "invalid pdf")):
        return SkillError(
            "INVALID_DOCUMENT",
            raw[:1200],
            stage=str(job.get("stage", "")) or "initialization",
            root_cause="DOCUMENT_CONTAINER_UNREADABLE",
        )
    return SkillError("CONVERSION_FAILED", raw[:1200] or "Conversion failed", ["Inspect the job and service logs, then retry"])


def validate_file(path: Path, max_bytes: int | None = None) -> str:
    if max_bytes is None:
        max_mb = os.getenv("FILE2MD_WEB_MAX_UPLOAD_MB", "").strip()
        max_bytes = int(max_mb) * 1024 * 1024 if max_mb.isdigit() else 100 * 1024 * 1024
    if not path.is_file():
        raise SkillError("INPUT_NOT_FOUND", str(path), ["Provide an existing local file"])
    suffix = path.suffix.lower()
    if not suffix:
        raise SkillError(
            "UNSUPPORTED_FORMAT",
            f"{path.name} has no extension",
            [
                "Add a supported extension such as .pdf, .pptx, .docx, .xlsx, .png, or .jpg",
                "Or rename the file to include the correct extension before running convert",
            ],
        )
    if suffix not in SUPPORTED:
        raise SkillError("UNSUPPORTED_FORMAT", suffix, ["Use PDF, PPTX, Word, XLSX, PNG, JPG, or another supported format"])
    size = path.stat().st_size
    if size > max_bytes:
        raise SkillError("FILE_TOO_LARGE", f"{size} bytes > {max_bytes} bytes", ["Compress or split the input"])
    with path.open("rb") as stream:
        head = stream.read(16)
    valid = True
    if suffix == ".pdf": valid = head.startswith(b"%PDF-")
    elif suffix == ".png": valid = head.startswith(b"\x89PNG\r\n\x1a\n")
    elif suffix in {".jpg", ".jpeg"}: valid = head.startswith(b"\xff\xd8\xff")
    elif suffix in {".docx", ".pptx", ".xlsx"}: valid = zipfile.is_zipfile(path)
    if not valid:
        raise SkillError("INVALID_FILE_SIGNATURE", path.name, ["Confirm the extension matches the file contents", "Export the file again"])
    return suffix


def route_for_suffix(suffix: str) -> str:
    if suffix in {".xlsx", ".xls"}:
        return "电子表格直接解析为 Markdown 表格"
    if suffix in {".ppt", ".pptx", ".doc", ".docx"}:
        return "LibreOffice 转 PDF，再执行版面/OCR/公式/表格识别"
    if suffix == ".pdf":
        return "PDF 版面/OCR/公式/表格识别"
    return "图片版面/OCR/公式/表格识别"


def ensure_runtime(args: argparse.Namespace) -> None:
    state = package_state()
    install_source = "none"
    if not state["installed"]:
        if args.deb_source:
            deb_path = Path(args.deb_source)
            if not deb_path.is_file():
                raise SkillError(
                    "PACKAGE_NOT_FOUND",
                    args.deb_source,
                    ["Provide a path to a riscv64 .deb on the local filesystem"],
                )
            code, out, err = run(f"sudo -n -p '' dpkg -i {shlex.quote(str(deb_path))}", timeout=300)
            if code:
                detail = (err or out).strip()[-1200:]
                if "password" in detail.lower() or "not allowed" in detail.lower():
                    raise SkillError("PRIVILEGE_REQUIRED", detail, ["Run the command under sudo or as root"])
                raise SkillError("PACKAGE_INSTALL_FAILED", detail, ["Confirm sudo permission", "Confirm the .deb is riscv64", "Check dependencies and disk space"])
            install_source = "deb-source"
        else:
            ok, detail = apt_update()
            if not ok:
                raise SkillError("APT_UPDATE_FAILED", detail, ["Check network and APT sources", "Confirm the device is riscv64", "Use --deb-source for an offline package"])
            install_latest_package()
            install_source = "apt-install"
        state = package_state()
        if not state["installed"]:
            raise SkillError("RUNTIME_NOT_INSTALLED", state["raw"], ["Inspect dpkg status and file2md.service logs"])
    elif args.update:
        ok, detail = apt_update()
        if ok:
            state = package_state()
            if state["candidate"] and version_is_newer(state["installed"], state["candidate"]):
                install_latest_package(upgrade_only=True)
                install_source = "apt-upgrade"
                state = package_state()
        else:
            install_source = f"apt-check-skipped: {detail}"
    package_info = {"installed": state["installed"], "candidate": state["candidate"], "architecture": state["architecture"], "install_action": install_source}
    _, parsed_state = service_state()
    if parsed_state.get("activestate") != "active" or parsed_state.get("substate") != "running":
        invoke_service_action("start")
    deadline = time.time() + args.wait
    last_health: Any = None
    while time.time() < deadline:
        try:
            health = get_json(API_BASE + "/api/health")
            models = get_json(API_BASE + "/api/models")
            last_health = {"health": health, "models": models}
            if health.get("engine_ready") and health.get("model_status") == "ready" and models.get("status") == "ready":
                print(json.dumps({"runtime": package_info, **last_health}, ensure_ascii=False))
                return
            if str(models.get("status", "")).lower() in {"failed", "error"}:
                raise SkillError("MODEL_LOAD_FAILED", json.dumps(models, ensure_ascii=False), ["Inspect model files and disk space", "Check journalctl -u file2md.service", "Repair or reinstall the runtime"])
        except SkillError as exc:
            if exc.code == "MODEL_LOAD_FAILED":
                raise
        time.sleep(2)
    raise SkillError("MODEL_NOT_READY", json.dumps(last_health, ensure_ascii=False), ["Check systemctl status file2md.service", "Inspect journalctl -u file2md.service", "Confirm local quantized models are complete"])


def markdown_features(text: str) -> list[str]:
    features = []
    if re.search(r"^#{1,6}\s", text, re.MULTILINE): features.append("headings")
    if re.search(r"^\s*(?:[-*+]\s|\d+[.]\s)", text, re.MULTILINE): features.append("lists")
    if "```" in text: features.append("code_blocks")
    if "$$" in text or re.search(r"\\\(|\\\[", text): features.append("formulas")
    if "|" in text and re.search(r"^\s*\|?.*\|.*$", text, re.MULTILINE): features.append("tables")
    return features


def job_metrics(job: dict[str, Any]) -> dict[str, Any]:
    logs = "\n".join(str(line) for line in job.get("logs", []))
    page_match = re.search(r"(?:共|total)\s*(\d+)\s*(?:页|pages?)", logs, re.IGNORECASE)
    model_match = re.search(r"(?:所有模型加载完成|models? loaded).*?\(([0-9.]+)s\)", logs, re.IGNORECASE)
    page_count = int(page_match.group(1)) if page_match else None
    model_load_seconds = float(model_match.group(1)) if model_match else None
    elapsed = job.get("inference_seconds")
    seconds_per_page = round(float(elapsed) / page_count, 3) if elapsed is not None and page_count else None
    return {
        "page_count": page_count,
        "model_load_seconds": model_load_seconds,
        "model_load_target_lt_2s": model_load_seconds < 2 if model_load_seconds is not None else None,
        "seconds_per_page": seconds_per_page,
        "pdf_page_target_lt_5s": seconds_per_page < 5 if seconds_per_page is not None else None,
    }


def safe_extract(archive: zipfile.ZipFile, target: Path) -> None:
    target_root = target.resolve()
    for member in archive.infolist():
        destination = (target / member.filename).resolve()
        try:
            destination.relative_to(target_root)
        except ValueError as exc:
            raise SkillError("OUTPUT_ARCHIVE_INVALID", member.filename, ["Keep the ZIP for diagnosis", "Reject result archives containing paths outside the output directory"]) from exc
    archive.extractall(target)


def result_directory(output_dir: Path, source: Path, job_id: str) -> Path:
    """Create a readable, unique directory without trusting server-supplied ids."""
    source_name = re.sub(r'[<>:"/\\|?\x00-\x1F]+', "_", source.stem).strip(" ._") or "document"
    safe_job_id = re.sub(r"[^0-9A-Za-z._-]+", "_", job_id).strip("._") or "job"
    return output_dir / f"{source_name}-{safe_job_id}"


def conversion_attempt(args: argparse.Namespace, path: Path, upload_source: Path, suffix: str, output_dir: Path) -> dict[str, Any]:
    baseline_state, _ = service_diagnostics()
    job_since_epoch = int(time.time())
    remote_zip: Path | None = None
    try:
        models = get_json(API_BASE + "/api/models")
        if models.get("status") != "ready":
            raise SkillError("MODEL_NOT_READY", json.dumps(models, ensure_ascii=False), ["Wait for model_status=ready and inspect service logs"])
        effective_threads = int(models.get("effective_threads") or 0)
        if effective_threads and effective_threads != int(args.threads):
            models = prepare_model_threads(int(args.threads))
        form = [f"-F file=@{shlex.quote(str(upload_source))}", f"-F threads={int(args.threads)}", f"-F flowchart={'true' if args.flowchart else 'false'}", f"-F image_ocr_caption={'true' if args.image_caption else 'false'}", f"-F xlsx_recalc={'true' if args.xlsx_recalc else 'false'}"]
        code, out, err = run("curl -fsS --max-time 60 " + " ".join(form) + " " + shlex.quote(API_BASE + "/api/jobs"), timeout=90)
        if code:
            raise SkillError("UPLOAD_FAILED", err[:1200], ["Check API health, disk space, and upload limits"])
        try:
            payload = json.loads(out)
        except json.JSONDecodeError as exc:
            raise SkillError("API_INVALID_RESPONSE", out[:1200], ["检查 File2MD 服务版本和日志"]) from exc
        job = payload.get("job", payload)
        job_id = job["id"]
        print(json.dumps({"filename": path.name, "size_bytes": path.stat().st_size, "format": suffix, "validation": "passed", "route": route_for_suffix(suffix), "model_status": "ready", "job_id": job_id, "status": "submitted"}, ensure_ascii=False))
        deadline = time.time() + args.wait if args.wait > 0 else None
        transient_failures = 0
        unresponsive_since: float | None = None
        last_progress: Any = 0
        current: dict[str, Any] = {}
        legacy_fingerprint: str | None = None
        legacy_last_change = time.monotonic()
        legacy_suspected_at: float | None = None
        while True:
            try:
                current = get_json(API_BASE + f"/api/jobs/{job_id}", attempts=1, curl_timeout=8).get("job", {})
                transient_failures = 0
                unresponsive_since = None
            except SkillError as exc:
                if exc.code != "SERVICE_UNREACHABLE":
                    raise
                transient_failures += 1
                if unresponsive_since is None:
                    unresponsive_since = time.time()
                unavailable_seconds = time.time() - unresponsive_since
                print(f"status API unavailable for {unavailable_seconds:.0f}s; retry {transient_failures}", file=sys.stderr)
                if unavailable_seconds < args.stall_timeout:
                    time.sleep(3)
                    continue
                raise classify_service_failure(job_id, exc, baseline_state, last_progress, job_since_epoch)
            last_progress = current.get("progress", last_progress)
            health = str(current.get("health", "ok"))
            has_server_liveness = "health" in current and "last_activity_at" in current
            if not has_server_liveness:
                fingerprint = json.dumps(
                    {
                        "status": current.get("status"),
                        "progress": current.get("progress"),
                        "stage": current.get("stage"),
                        "nodes": current.get("nodes"),
                        "last_log": (current.get("logs") or [None])[-1],
                    },
                    ensure_ascii=False,
                    sort_keys=True,
                )
                if fingerprint != legacy_fingerprint:
                    legacy_fingerprint = fingerprint
                    legacy_last_change = time.monotonic()
                    legacy_suspected_at = None
                legacy_idle = time.monotonic() - legacy_last_change
                if legacy_idle >= args.no_progress_seconds and legacy_suspected_at is None:
                    legacy_suspected_at = time.monotonic()
                    health = "suspected_stall"
                elif legacy_suspected_at is not None:
                    health = "suspected_stall"
                    if time.monotonic() - legacy_suspected_at >= args.stall_confirm_seconds:
                        state, journal = service_diagnostics(job_since_epoch)
                        raise SkillError(
                            "CONVERSION_STALLED",
                            f"legacy File2MD job={job_id}; progress={last_progress}; no progress for {legacy_idle:.0f}s",
                            stage=str(current.get("stage", "")),
                            root_cause="NO_PROGRESS_REPORTED_BY_LEGACY_SERVER",
                            retryable=False,
                            details={
                                "job_id": job_id,
                                "task_continues_running": True,
                                "server_upgrade_required_for_worker_cancel": True,
                                "systemd": systemd_snapshot(state),
                                "journal_tail": journal[-2000:],
                                "memory": memory_snapshot(),
                                "tcm": tcm_snapshot(),
                            },
                        )
            print(json.dumps({"job_id": job_id, "status": current.get("status"), "progress": last_progress, "stage": current.get("stage"), "health": health, "no_progress_seconds": current.get("no_progress_seconds", 0)}, ensure_ascii=False))
            if current.get("status") == "completed":
                break
            if current.get("status") == "failed":
                _, journal = service_diagnostics(job_since_epoch)
                classified = classify_job_failure(current, journal)
                if classified.code == "WORKER_OOM_KILLED":
                    cleanup = cleanup_oom_tcm_residue(current.get("worker_pid"), enabled=args.auto_recover_tcm)
                    classified.details.update(
                        worker_pid=current.get("worker_pid"),
                        server_diagnostics=current.get("diagnostics", {}),
                        tcm_cleanup=cleanup,
                    )
                    if cleanup.get("cleanup_succeeded") and cleanup.get("cleanup_attempted"):
                        classified.remediation = [
                            "已清理该 OOM worker 遗留的 TCM；本任务不会自动重试",
                            "等待设备释放足够内存后再重新提交",
                            "拆分大文档或关闭流程图、图注等可选阶段",
                            "联系设备管理员处理持续的系统内存压力",
                        ]
                    elif not cleanup.get("cleanup_succeeded"):
                        classified.remediation = [
                            "本任务不会自动重试",
                            str(cleanup.get("recommendation") or "检查并清理 TCM 残留"),
                            "等待设备释放足够内存，拆分文档或关闭可选阶段",
                        ]
                raise classified
            if health == "confirmed_stall":
                raise SkillError(
                    "CONVERSION_STALLED",
                    f"job={job_id}; stage={current.get('stage')}; no_progress_seconds={current.get('no_progress_seconds')}",
                    stage=str(current.get("stage", "")),
                    root_cause="NO_PROGRESS_AND_NO_PROCESS_ACTIVITY",
                    retryable=False,
                    details={
                        "job_id": job_id,
                        "worker_pid": current.get("worker_pid"),
                        "diagnostics": current.get("diagnostics", {}),
                        "cancel_endpoint": f"POST {API_BASE}/api/jobs/{job_id}/cancel",
                        "task_continues_running": True,
                    },
                )
            if deadline is not None and time.time() >= deadline:
                raise SkillError(
                    "CLIENT_WAIT_LIMIT_REACHED",
                    f"job={job_id}; progress={last_progress}; File2MD task was not cancelled",
                    stage=str(current.get("stage", "")),
                    root_cause="CLIENT_STOPPED_WAITING",
                    retryable=False,
                    details={"job_id": job_id, "task_continues_running": True},
                )
            time.sleep(args.poll)
        remote_zip = Path("/tmp") / f"file2md-result-{job_id}.zip"
        code, _, err = run(f"curl -fsSL --max-time 120 -o {shlex.quote(str(remote_zip))} {shlex.quote(API_BASE + f'/api/jobs/{job_id}/download')}", timeout=150)
        if code:
            raise SkillError("OUTPUT_DOWNLOAD_FAILED", err[:1200], ["Keep the job id and inspect service logs", "Retry the download after the service is ready"])
        target = result_directory(output_dir, path, job_id)
        target.mkdir(parents=True, exist_ok=True)
        local_zip = target / f"{path.stem}.zip"
        shutil.copyfile(remote_zip, local_zip)
        with zipfile.ZipFile(local_zip) as archive:
            safe_extract(archive, target)
        markdown = sorted(target.rglob("*.md"))
        if not markdown:
            raise SkillError("OUTPUT_MISSING", str(local_zip), ["Keep the ZIP and inspect service output and logs"])
        md = markdown[0]
        text = md.read_text(encoding="utf-8", errors="replace")
        if not text.strip():
            raise SkillError("MARKDOWN_EMPTY", str(md), ["Check source content and recognition logs"])
        elapsed = current.get("inference_seconds")
        return {"status": "completed", "filename": path.name, "size_bytes": path.stat().st_size, "format": suffix, "job_id": job_id, "markdown_path": str(md), "zip_path": str(local_zip), "images_dir": str(md.parent / "images") if (md.parent / "images").is_dir() else None, "markdown_features": markdown_features(text), "elapsed_seconds": elapsed, "xlsx_target_lt_1s": float(elapsed) < 1 if suffix in {".xlsx", ".xls"} and elapsed is not None else None, "warnings": current.get("warnings", []), "server_diagnostics": current.get("diagnostics", {}), **job_metrics(current)}
    finally:
        if remote_zip is not None and remote_zip.exists():
            try:
                remote_zip.unlink()
            except OSError:
                pass


def convert(args: argparse.Namespace) -> None:
    path = Path(args.input).resolve()
    suffix = validate_file(path)
    output_dir = Path(args.output_dir).resolve()
    output_dir.mkdir(parents=True, exist_ok=True)
    local_staging = Path("/tmp") / f"file2md-skill-{os.getpid()}-{path.name}"
    warnings: list[dict[str, Any]] = []
    try:
        requires_tcm = suffix not in {".txt", ".xls", ".xlsx"}
        initial_tcm, tcm_warnings = tcm_preflight(auto_recover=args.auto_recover_tcm, required=requires_tcm)
        warnings.extend(tcm_warnings)
        server_handles_xlsx_recalc = False
        if suffix == ".xlsx":
            try:
                model_state = get_json(API_BASE + "/api/models")
                capabilities = model_state.get("capabilities") or {}
                server_handles_xlsx_recalc = capabilities.get("xlsx_formula_recalc") is True
            except SkillError:
                pass
        if suffix == ".xlsx" and not server_handles_xlsx_recalc:
            formula_cells = xlsx_uncached_formula_cells(path)
            if formula_cells:
                if not args.xlsx_recalc:
                    warnings.append({
                        "code": "FORMULA_RESULT_NOT_CACHED",
                        "message": "检测到未缓存公式且本次未启用自动重算；已使用原文件继续转换，公式结果可能为空。",
                        "stage": "xlsx_preflight",
                        "root_cause": "XLSX_RECALC_DISABLED",
                        "formula_cells": formula_cells,
                        "formula_values_may_be_empty": True,
                        "continued_with_original": True,
                        "remediation": ["启用 XLSX 公式重算后重新转换", "使用 Excel 或 LibreOffice 打开并保存文件后重试"],
                    })
                    shutil.copy2(path, local_staging)
                else:
                    try:
                        warnings.append(recalculate_xlsx(path, local_staging, formula_cells))
                    except SkillError as exc:
                        if exc.code not in {"FORMULA_RESULT_NOT_CACHED", "LIBREOFFICE_RECALC_FAILED"}:
                            raise
                        warnings.append({
                            "code": "FORMULA_CACHE_RECALC_FAILED",
                            "message": "XLSX 公式自动重算失败；已使用原文件继续转换，公式结果可能为空。",
                            "stage": "xlsx_preflight",
                            "root_cause": exc.root_cause or exc.code,
                            "raw_message": exc.message,
                            "formula_cells": formula_cells,
                            "formula_values_may_be_empty": True,
                            "continued_with_original": True,
                            "remediation": exc.remediation or ERROR_REMEDIATION.get(exc.code, []),
                        })
                        shutil.copy2(path, local_staging)
            else:
                shutil.copy2(path, local_staging)
        else:
            shutil.copy2(path, local_staging)

        result: dict[str, Any] | None = None
        for attempt in range(2):
            try:
                result = conversion_attempt(args, path, local_staging, suffix, output_dir)
                break
            except SkillError as exc:
                recoverable_tcm = exc.code in {"SPACEMIT_TCM_ACQUIRE_FAILED", "TCM_STALE_ALLOCATION"}
                if attempt or not args.auto_recover_tcm or not recoverable_tcm:
                    raise
                before = tcm_snapshot()
                busy_blocks = [block for block in before.get("blocks", []) if block.get("state") != "free"]
                if not busy_blocks:
                    raise
                after = recover_stale_tcm(before)
                warnings.append({"code": "TCM_RECOVERED_AND_RETRIED", "message": "已安全清理 TCM，并自动重试一次转换。", "before": before, "after": after})
        if result is None:
            raise SkillError("CONVERSION_FAILED", "conversion returned no result")
        server_warnings = result.get("warnings") if isinstance(result.get("warnings"), list) else []
        result["warnings"] = [*warnings, *server_warnings]
        diagnostics = {
            "memory": memory_snapshot(),
            "tcm": {key: value for key, value in initial_tcm.items() if key != "raw"},
        }
        server_diagnostics = result.pop("server_diagnostics", {})
        if server_diagnostics:
            diagnostics["server"] = server_diagnostics
        result["diagnostics"] = diagnostics
        print(json.dumps(result, ensure_ascii=False, indent=2))
    except SkillError as exc:
        print(json.dumps(exc.payload(), ensure_ascii=False, indent=2), file=sys.stderr)
        raise SystemExit(2)
    finally:
        if local_staging.exists():
            try:
                local_staging.unlink()
            except OSError:
                pass


def parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(description="File2MD local runtime wrapper")
    sub = parser.add_subparsers(dest="command", required=True)
    ensure = sub.add_parser("ensure-runtime")
    ensure.add_argument("--deb-source", help="local riscv64 .deb used when APT is unavailable or the package is absent")
    ensure.add_argument("--update", dest="update", action="store_true", help="refresh APT metadata and install a newer candidate version when available (default)")
    ensure.add_argument("--no-update", dest="update", action="store_false", help="do not contact APT; use the installed runtime")
    ensure.add_argument("--wait", type=int, default=1800)
    ensure.set_defaults(func=ensure_runtime, update=True)
    service = sub.add_parser("service")
    service.add_argument("action", choices=("status", "start", "stop", "restart"))
    service.add_argument("--wait", type=int, default=1800)
    service.set_defaults(func=manage_service)
    convert_parser = sub.add_parser("convert")
    convert_parser.add_argument("input")
    convert_parser.add_argument("--output-dir", default=str(DEFAULT_OUTPUT_DIR), help="result root (default: ~/File2MD)")
    convert_parser.add_argument("--threads", type=int, default=4)
    convert_parser.add_argument("--poll", type=float, default=2.0)
    convert_parser.add_argument("--stall-timeout", type=float, default=60, help="seconds of continuous API unresponsiveness before classifying a running job as stalled")
    convert_parser.add_argument("--no-progress-seconds", type=float, default=180, help="legacy-server fallback: seconds without job progress before entering observation")
    convert_parser.add_argument("--stall-confirm-seconds", type=float, default=120, help="legacy-server fallback: additional observation seconds before reporting a confirmed stall")
    convert_parser.add_argument("--wait", type=int, default=0, help="optional client-side wait limit in seconds; 0 waits until completion or a confirmed no-progress state and never cancels the server task")
    convert_parser.add_argument("--flowchart", action="store_true", help="enable flowchart recognition (server-side, default off)")
    convert_parser.add_argument("--image-caption", action="store_true", help="enable image OCR captioning (server-side, default off)")
    convert_parser.add_argument("--auto-recover-tcm", action=argparse.BooleanOptionalAction, default=True, help="clear only stale TCM allocations whose owner PIDs no longer exist, then retry once")
    convert_parser.add_argument("--xlsx-recalc", action=argparse.BooleanOptionalAction, default=True, help="use LibreOffice on a temporary copy when XLSX formula results are not cached")
    convert_parser.set_defaults(func=convert)
    return parser


if __name__ == "__main__":
    namespace = parser().parse_args()
    try:
        namespace.func(namespace)
    except SkillError as exc:
        print(json.dumps(exc.payload(), ensure_ascii=False, indent=2), file=sys.stderr)
        raise SystemExit(2)
