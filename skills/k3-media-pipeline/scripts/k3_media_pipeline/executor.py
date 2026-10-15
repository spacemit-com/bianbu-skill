"""Process lifecycle and output verification."""

from __future__ import annotations

import concurrent.futures
import os
from pathlib import Path
import signal
import subprocess
import sys
import time
from typing import Any

from .errors import RequestError
from .inputs import probe_file
from .scenarios import plan


def run_process(argv: list[str], timeout: int, bounded_by_command: bool = False) -> dict[str, Any]:
    started = time.monotonic()
    process = subprocess.Popen(
        argv,
        stdin=subprocess.DEVNULL,
        stdout=subprocess.PIPE,
        stderr=subprocess.PIPE,
        text=True,
        start_new_session=True,
    )
    timed_out = False
    try:
        stdout, stderr = process.communicate(timeout=timeout + (20 if bounded_by_command else 0))
    except subprocess.TimeoutExpired:
        timed_out = True
        os.killpg(process.pid, signal.SIGINT)
        try:
            stdout, stderr = process.communicate(timeout=10)
        except subprocess.TimeoutExpired:
            os.killpg(process.pid, signal.SIGTERM)
            stdout, stderr = process.communicate(timeout=5)
    acceptable = process.returncode == 0 or (timed_out and process.returncode in {-2, 130, 255})
    return {
        "pid": process.pid,
        "returncode": process.returncode,
        "ok": acceptable,
        "elapsed_seconds": round(time.monotonic() - started, 3),
        "stderr_tail": stderr[-2000:] if stderr and not acceptable else "",
    }



def _gst_stages(argv: list[str]) -> list[str]:
    tokens = argv[1:]
    while tokens and tokens[0].startswith("-"):
        tokens = tokens[1:]
    stages: list[str] = []
    group: list[str] = []
    for token in tokens:
        if token == "!" or (token.endswith(".") and "=" not in token):
            if group:
                stages.append(_gst_group(group))
                group = []
            if token != "!":
                stages.append(token)
        else:
            group.append(token)
    if group:
        stages.append(_gst_group(group))
    return stages


def _gst_group(group: list[str]) -> str:
    head = group[0]
    if "/" in head and head.split("/", 1)[0] in {"video", "audio", "application"}:
        return f"capsfilter({head})"
    return f"{head}({','.join(group[1:])})" if len(group) > 1 else head


def _ffmpeg_stages(argv: list[str]) -> list[str]:
    tokens = argv[1:]
    if "-i" not in tokens:
        return ["ffmpeg"]
    i_index = tokens.index("-i")
    pre = tokens[:i_index]
    source = tokens[i_index + 1]
    in_format = pre[pre.index("-f") + 1] if "-f" in pre else None
    input_desc = f"{in_format}:{source}" if in_format else source
    stages = [f"input({input_desc})"]
    if "-c:v" in pre:
        stages.append(f"decode({pre[pre.index('-c:v') + 1]})")
    post = tokens[i_index + 2:]
    valueless = {"-an", "-re", "-sn", "-dn", "-y", "-n"}
    encoder = mux = filter_desc = None
    target = post[-1] if post else ""
    j = 0
    while j < len(post) - 1:
        flag, value = post[j], post[j + 1]
        if flag in valueless:
            j += 1
            continue
        if flag == "-c:v":
            encoder = value
        elif flag == "-vf":
            filter_desc = value
        elif flag == "-f":
            mux = value
        j += 2
    if filter_desc:
        stages.append(f"filter({filter_desc})")
    if encoder == "copy":
        stages.append("stream-copy")
    elif encoder:
        stages.append(f"encode({encoder})")
    if target == "-":
        stages.append("output(null)")
        return stages
    if mux:
        stages.append(f"mux({mux})")
    stages.append(f"output({target})")
    return stages


def pipeline_stages(backend: str, argvs: list[list[str]]) -> list[str] | None:
    """Mechanical description of the pipeline components actually in use."""
    if backend == "ffprobe" and not argvs:
        return ["ffprobe"]
    if not argvs:
        return None
    first = argvs[0]
    if backend == "gstreamer":
        return _gst_stages(first)
    if backend == "ffmpeg":
        return _ffmpeg_stages(first)
    return None


def execute(request: dict[str, Any], dry_run: bool) -> dict[str, Any]:
    media_plan = plan(request)
    commands = [" ".join(argv) for argv in media_plan["argvs"]]
    base: dict[str, Any] = {
        "status": "DRY_RUN" if dry_run else "SUCCESS",
        "scenario": request["scenario"],
        "backend": media_plan["backend"],
        "pipeline": media_plan["pipeline"],
        "pipeline_stages": pipeline_stages(media_plan["backend"], media_plan["argvs"]),
        "commands": commands,
        "input": media_plan["input"],
        "output": media_plan["output"],
        "target_url": media_plan.get("target_url"),
        "streams": len(media_plan["argvs"]) or 1,
        "duration_seconds": request["duration_seconds"],
        "processes": None,
        "output_bytes": None,
        "output_media_info": None,
        "media_info": None,
        "error_code": None,
        "summary": "",
    }
    if dry_run:
        default_note = "（默认地址）" if request.get("url_defaulted") else ""
        base["summary"] = f"计划：{media_plan['pipeline']}{default_note}；输入：{media_plan['input']}；未执行。"
        return base
    if not media_plan["argvs"]:
        base["media_info"] = media_plan["media_info"]
        base["summary"] = f"媒体信息读取成功：{media_plan['input']}；{media_plan['media_info']}"
        return base
    print(f"执行 {request['scenario']}：{media_plan['pipeline']}", file=sys.stderr, flush=True)
    with concurrent.futures.ThreadPoolExecutor(max_workers=len(media_plan["argvs"])) as pool:
        futures = [
            pool.submit(
                run_process,
                argv,
                request["duration_seconds"],
                media_plan["bounded"],
            )
            for argv in media_plan["argvs"]
        ]
        processes = [future.result() for future in futures]
    base["processes"] = processes
    if not all(item["ok"] for item in processes):
        base["status"] = "FAILED"
        base["error_code"] = "PROCESS_FAILED"
        base["summary"] = f"执行失败：{media_plan['pipeline']}；请查看 processes 中的错误。"
        return base
    if media_plan["output"]:
        output_path = Path(media_plan["output"])
        if not output_path.is_file() or output_path.stat().st_size == 0:
            base["status"] = "FAILED"
            base["error_code"] = "OUTPUT_INVALID"
            base["summary"] = f"执行进程已结束，但输出文件不存在或为空：{output_path}"
            return base
        base["output_bytes"] = output_path.stat().st_size
        if output_path.suffix.lower() in {".mp4", ".jpg", ".jpeg", ".png"}:
            try:
                base["output_media_info"] = probe_file(output_path)
            except RequestError as exc:
                base["status"] = "FAILED"
                base["error_code"] = "OUTPUT_INVALID"
                base["summary"] = f"输出文件无法识别：{output_path}；{exc}"
                return base
            if request["scenario"] in {"record-camera", "camera-record-preview"}:
                actual_duration = base["output_media_info"].get("duration")
                expected_duration = request["duration_seconds"]
                tolerance = max(0.1, 2 / request["frame_rate"])
                if actual_duration is None or abs(actual_duration - expected_duration) > tolerance:
                    base["status"] = "FAILED"
                    base["error_code"] = "DURATION_MISMATCH"
                    base["summary"] = (
                        f"录像有效时长不符合请求：期望 {expected_duration} 秒，"
                        f"实际 {actual_duration} 秒，容差 {tolerance:.3f} 秒"
                    )
                    return base
    default_note = "（默认地址）" if request.get("url_defaulted") else ""
    base["summary"] = (
        f"执行成功。场景：{request['scenario']}；后端：{media_plan['backend']}；"
        f"完整 Pipeline：{media_plan['pipeline']}{default_note}；输入：{media_plan['input']}；"
        f"路数：{len(media_plan['argvs']) or 1}；时长：{request['duration_seconds']} 秒"
        + (f"；输出：{media_plan['output']}。" if media_plan["output"] else "；无文件输出。")
    )
    return base
