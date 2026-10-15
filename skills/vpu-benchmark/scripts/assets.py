#!/usr/bin/env python3
"""Download and prepare the external, cached VPU benchmark asset set."""

from __future__ import annotations

import argparse
import copy
import json
import os
import shutil
import subprocess
import sys
import tempfile
import urllib.request
from pathlib import Path
from typing import Any

from tooling import tool_path


ROOT = Path(__file__).resolve().parents[1]
MANIFEST_PATH = ROOT / "references" / "asset-manifest.json"


class AssetError(RuntimeError):
    pass


def load_manifest(path: Path = MANIFEST_PATH) -> dict[str, Any]:
    data = json.loads(path.read_text(encoding="utf-8"))
    if data.get("schema") != "vpu-benchmark-asset-manifest" or data.get("schema_version") != 1:
        raise AssetError("unsupported asset manifest")
    if not data.get("asset_set_id") or not data.get("source", {}).get("url"):
        raise AssetError("asset manifest is incomplete")
    return data


def cache_root(manifest: dict[str, Any]) -> Path:
    override = os.environ.get("VPU_BENCHMARK_CACHE")
    if override:
        base = Path(override).expanduser()
    else:
        data_home = Path(os.environ.get("XDG_DATA_HOME", Path.home() / ".local" / "share"))
        base = data_home / "benchmarks" / "vpu"
    return base / manifest["asset_set_id"]


def variant_manifest(manifest: dict[str, Any], name: str = "1080p") -> dict[str, Any]:
    if name == "1080p":
        return manifest
    variant = manifest.get("variants", {}).get(name)
    if variant is None:
        raise AssetError(f"unknown asset variant: {name}")
    result = copy.deepcopy(manifest)
    result["asset_set_id"] = variant["asset_set_id"]
    result["transform"].update(variant["transform"])
    result["artifacts"] = variant["artifacts"]
    if "source" in variant:
        result["source"] = copy.deepcopy(variant["source"])
    return result


def run(argv: list[str]) -> subprocess.CompletedProcess[str]:
    try:
        call = subprocess.run(argv, text=True, capture_output=True, check=False, timeout=180)
    except subprocess.TimeoutExpired as exc:
        raise AssetError('asset command timed out: ' + ' '.join(argv)) from exc
    if call.returncode:
        detail = (call.stderr or call.stdout).strip()[-2000:]
        raise AssetError(f"command failed ({call.returncode}): {' '.join(argv)}\n{detail}")
    return call


def nonempty(path: Path) -> bool:
    return path.is_file() and path.stat().st_size > 0


def validate(manifest: dict[str, Any], root: Path) -> dict[str, Any]:
    artifacts = manifest["artifacts"]
    result: dict[str, Any] = {"ready": True, "files": {}}
    for name in ("i420", "h264", "h265"):
        path = root / artifacts[name]["filename"]
        ok = nonempty(path)
        result["files"][name] = {"path": str(path), "ready": ok, "size_bytes": path.stat().st_size if path.is_file() else None}
        result["ready"] &= ok
    return result


def require_tools(manifest: dict[str, Any]) -> None:
    for name in ("ffmpeg", "curl"):
        if not shutil.which(name):
            raise AssetError(f"{name} is required")
    encoder_call = run(["ffmpeg", "-hide_banner", "-encoders"])
    decoder_call = run(["ffmpeg", "-hide_banner", "-decoders"])
    encoders = encoder_call.stdout + encoder_call.stderr
    decoders = decoder_call.stdout + decoder_call.stderr
    decoder = manifest["transform"]["decoder"]
    if decoder not in decoders:
        raise AssetError(f"required hardware decoder is unavailable: {decoder}")
    for encoder in manifest["transform"]["encoders"].values():
        if encoder not in encoders:
            raise AssetError(f"required hardware encoder is unavailable: {encoder}")


def download(url: str, target: Path) -> None:
    request = urllib.request.Request(url, headers={"User-Agent": "vpu-benchmark/0.13.12"})
    with urllib.request.urlopen(request, timeout=120) as response, target.open("wb") as output:
        shutil.copyfileobj(response, output)
    if target.stat().st_size == 0:
        raise AssetError("downloaded source is empty")


def ensure(manifest: dict[str, Any], *, force: bool = False) -> dict[str, Any]:
    root = cache_root(manifest)
    state = validate(manifest, root)
    if not force and state["ready"]:
        return {"changed": False, "asset_set_id": manifest["asset_set_id"], "cache": str(root), **state}
    require_tools(manifest)
    root.mkdir(parents=True, exist_ok=True)
    cfg, art = manifest["transform"], manifest["artifacts"]
    with tempfile.TemporaryDirectory(prefix=".vpu-assets-", dir=root.parent) as temp_name:
        temp = Path(temp_name)
        generated = []
        raw = root / art["i420"]["filename"]
        if force or not nonempty(raw):
            source = temp / manifest["source"]["filename"]
            if manifest['source'].get('clip_seconds'):
                url = manifest['source']['url']
                prefix_bytes = int(manifest['source'].get('download_prefix_bytes', 0))
                if prefix_bytes <= 0:
                    raise AssetError('download_prefix_bytes must be set for clipped remote sources')
                prefix = temp / ('prefix-' + manifest['source']['filename'])
                run(['curl', '--fail', '--location', '--silent', '--show-error',
                    '--range', f'0-{prefix_bytes - 1}', '--connect-timeout', '10',
                    '--max-time', '120', '--retry', '2', '--retry-all-errors',
                    '--output', str(prefix), url])
                if prefix.stat().st_size != prefix_bytes:
                    raise AssetError(f'partial source size mismatch: expected {prefix_bytes}, got {prefix.stat().st_size}')
                call = run(['ffmpeg', '-nostdin', '-hide_banner', '-loglevel', 'debug', '-y',
                    '-i', str(prefix), '-map', '0:v:0', '-an',
                    '-t', str(manifest['source']['clip_seconds']), '-c:v', 'copy',
                    '-movflags', '+faststart', str(source)])
                (root / 'source-clip.log').write_text(call.stdout + call.stderr)
            else:
                download(manifest["source"]["url"], source)
            if not nonempty(source):
                raise AssetError("downloaded source is missing or empty")
            raw = temp / art["i420"]["filename"]
            common = ["ffmpeg", "-hide_banner", "-loglevel", "warning", "-y", "-c:v", cfg["decoder"], "-i", str(source), "-an", "-vf", f"scale={cfg['width']}:{cfg['height']},fps={cfg['fps']}", "-frames:v", str(cfg["frames"]), "-pix_fmt", "yuv420p"]
            run(common + ["-f", "rawvideo", str(raw)])
            if not nonempty(raw):
                raise AssetError("generated raw input is missing or empty")
            generated.append(raw)
        raw_input = ["ffmpeg", "-hide_banner", "-loglevel", "warning", "-y", "-f", "rawvideo", "-pixel_format", "yuv420p", "-video_size", f"{cfg['width']}x{cfg['height']}", "-framerate", str(cfg["fps"]), "-i", str(raw), "-frames:v", str(cfg["frames"])]
        for codec, muxer in (("h264", "h264"), ("h265", "hevc")):
            target = root / art[codec]["filename"]
            if force or not nonempty(target):
                output = temp / target.name
                run(raw_input + ["-c:v", cfg["encoders"][codec], "-f", muxer, str(output)])
                if not nonempty(output):
                    raise AssetError(f"generated {codec} is missing or empty")
                generated.append(output)
        for item in generated:
            item.replace(root / item.name)
        metadata = {"asset_set_id": manifest["asset_set_id"], "source_url": manifest["source"]["url"],
                    "source_clip_seconds": manifest['source'].get('clip_seconds'),
                    "transform": cfg, "check_policy": "exists-and-nonempty",
                    "generated_files": [p.name for p in generated]}
        (root / "generated.json").write_text(json.dumps(metadata, ensure_ascii=False, indent=2), encoding="utf-8")
    return {"changed": True, "asset_set_id": manifest["asset_set_id"], "cache": str(root), **validate(manifest, root)}


def ensure_codec(manifest: dict[str, Any], codec: str) -> str:
    """Add a codec to an existing cache without rebuilding/deleting original assets."""
    if codec not in {'vp8', 'vp9', 'mjpeg'}:
        raise AssetError('unsupported extended asset codec')
    root = cache_root(manifest)
    cfg, art = manifest['transform'], manifest['artifacts']
    target = root/art[codec]['filename']
    if nonempty(target):
        return str(target)
    ensure(manifest)
    with tempfile.TemporaryDirectory(prefix='.extra-codec-', dir=root) as tmp:
        output = Path(tmp)/target.name
        raw = str(root/art['i420']['filename'])
        if codec == 'vp9':
            from benchmark import resolve_device
            encoder = tool_path('mvx_encoder')
            if not encoder:
                raise AssetError('required tool is unavailable: mvx_encoder')
            argv = [encoder, '--dev', resolve_device('auto'), '-f', 'ivf', '-o', 'vp9',
                    '-w', str(cfg['width']), '-h', str(cfg['height']), '--frames', str(cfg['frames']), raw, str(output)]
            generator = 'mvx_encoder hardware (FFmpeg vp9_stcodec timeout workaround approved)'
        else:
            argv = ['ffmpeg','-hide_banner','-loglevel','warning','-y','-f','rawvideo','-pixel_format','yuv420p',
                    '-video_size', f"{cfg['width']}x{cfg['height']}", '-framerate',str(cfg['fps']),'-i',raw,
                    '-frames:v',str(cfg['frames']),'-c:v',codec+'_stcodec','-f','ivf' if codec=='vp8' else 'mjpeg',str(output)]
            generator = 'FFmpeg ' + codec + '_stcodec hardware'
        call = run(argv)
        if not nonempty(output):
            raise AssetError(f'{codec} generated file is missing or empty')
        output.replace(target)
        (root/f'generated-{codec}.json').write_text(json.dumps({'codec':codec,'generator':generator,'argv':argv,
            'source_raw':raw,'width':cfg['width'],'height':cfg['height'],'frames':cfg['frames']},ensure_ascii=False,indent=2))
        (root/f'generated-{codec}.log').write_text(call.stdout+call.stderr)
    return str(target)


def main() -> None:
    parser = argparse.ArgumentParser(description=__doc__)
    sub = parser.add_subparsers(dest="command", required=True)
    sub.add_parser("status")
    ensure_parser = sub.add_parser("ensure")
    ensure_parser.add_argument("--force", action="store_true")
    sub.add_parser("paths")
    args = parser.parse_args()
    try:
        manifest = load_manifest()
        root = cache_root(manifest)
        if args.command == "status":
            result = {"asset_set_id": manifest["asset_set_id"], "cache": str(root), **validate(manifest, root)}
        elif args.command == "ensure":
            result = ensure(manifest, force=args.force)
        else:
            result = {name: str(root / spec["filename"]) for name, spec in manifest["artifacts"].items()}
        print(json.dumps(result, ensure_ascii=False, indent=2))
    except (AssetError, OSError, ValueError, json.JSONDecodeError) as exc:
        print(json.dumps({"ok": False, "error": str(exc)}, ensure_ascii=False, indent=2))
        raise SystemExit(2)


if __name__ == "__main__":
    main()
