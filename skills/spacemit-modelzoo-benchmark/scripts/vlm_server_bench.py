#!/usr/bin/env python3
"""Measure official llama-server 'vision encode' timing; never substitute ONNX latency."""
import argparse
import base64
import copy
import json
import os
from pathlib import Path
import re
import socket
import statistics
import subprocess
import time
import urllib.request


def fetch(url, payload=None, timeout=300):
    data = None if payload is None else json.dumps(payload).encode()
    req = urllib.request.Request(url, data=data, headers={'Content-Type': 'application/json'})
    with urllib.request.urlopen(req, timeout=timeout) as r:
        return json.load(r)


def run(args):
    model_dir = args.model_dir.resolve()
    out = args.out.resolve()
    out.mkdir(parents=True, exist_ok=True)
    original = json.loads((model_dir / 'config.json').read_text())
    image = args.image.read_bytes()
    if image[:8] != b'\x89PNG\r\n\x1a\n':
        raise ValueError('Use a PNG image with the official dimensions')
    width, height = int.from_bytes(image[16:20], 'big'), int.from_bytes(image[20:24], 'big')
    if width != args.size or height != args.size:
        raise ValueError(f'Image {width}x{height} does not match required {args.size}')
    model_path = (model_dir / original['text_model']['model_path']).resolve()
    vision_path = args.vision_model.resolve() if args.vision_model else (model_dir / original['vision_model']['model_path']).resolve()
    if not model_path.is_file() or not vision_path.is_file():
        raise ValueError('Missing text or vision model')
    results = []
    for cores in args.cores:
        directory = out / f'{cores}core'
        directory.mkdir(exist_ok=True)
        config = copy.deepcopy(original)
        config['text_model']['model_path'] = str(model_path)
        config['vision_model'].update(model_path=str(vision_path), input_size=args.size,
            spacemit_ep_intra_thread_num=cores, spacemit_ep_inter_thread_num=1)
        (directory / 'config.json').write_text(json.dumps(config, indent=2))
        with socket.socket() as sock:
            sock.bind(('127.0.0.1', 0))
            port = sock.getsockname()[1]
        command = ['llama-server', '-m', str(model_path), '--media-backend', 'smt',
            '--smt-config-dir', str(directory), '-t', '8', '-c', '2048',
            '--host', '127.0.0.1', '--port', str(port), '--reasoning-budget', '0', '--reasoning', 'off']
        (directory / 'command.json').write_text(json.dumps(command))
        env = dict(os.environ)
        env.pop('SPACEMIT_EP_DENSE_ACCURACY_LEVEL', None)
        if args.dense_accuracy_level is not None:
            env['SPACEMIT_EP_DENSE_ACCURACY_LEVEL'] = str(args.dense_accuracy_level)
        (directory / 'environment.json').write_text(json.dumps({'SPACEMIT_EP_DENSE_ACCURACY_LEVEL': env.get('SPACEMIT_EP_DENSE_ACCURACY_LEVEL')}))
        log_path = directory / 'server.log'
        entry = dict(cores=cores, llm_threads=8, image_size=args.size, image=str(args.image.resolve()),
                     vision_model=str(vision_path), command=command, samples=[], status='runtime_failed')
        with log_path.open('w') as log:
            process = subprocess.Popen(command, stdout=log, stderr=subprocess.STDOUT, cwd=model_dir, env=env)
            try:
                url = f'http://127.0.0.1:{port}'
                deadline = time.monotonic() + 240
                while True:
                    if process.poll() is not None:
                        raise RuntimeError(f'llama-server exited: {process.returncode}')
                    try:
                        fetch(url + '/health', timeout=3)
                        break
                    except Exception:
                        if time.monotonic() >= deadline:
                            raise RuntimeError('Server readiness timed out')
                        time.sleep(1)
                for repeat in range(4):
                    offset = log_path.stat().st_size
                    payload = {'messages': [{'role': 'user', 'content': [
                        {'type': 'image_url', 'image_url': {'url': 'data:image/png;base64,' + base64.b64encode(image).decode()}},
                        {'type': 'text', 'text': f'Describe the image briefly. Run {repeat}.'}]}],
                        'max_tokens': 8, 'temperature': 0, 'cache_prompt': False, 'stream': False}
                    (directory / f'request-{repeat}.json').write_text(json.dumps(payload))
                    response = fetch(url + '/v1/chat/completions', payload)
                    (directory / f'response-{repeat}.json').write_text(json.dumps(response, ensure_ascii=False))
                    if response.get('error') or not response.get('choices'):
                        raise RuntimeError('Invalid model response')
                    deadline = time.monotonic() + 10
                    while True:
                        with log_path.open('rb') as f:
                            f.seek(offset)
                            segment = f.read().decode(errors='replace')
                        matches = re.findall(r'vision encode\s*=\s*([\d.]+)\s*ms', segment)
                        if matches or time.monotonic() >= deadline:
                            break
                        time.sleep(.2)
                    if not matches or float(matches[-1]) <= 0:
                        raise RuntimeError('No positive per-request vision encode timing; reject cached/substitute result')
                    if 'failed to open aidma list' in log_path.read_text(errors='replace'):
                        raise RuntimeError('Hardware access failed')
                    value = float(matches[-1])
                    print(f'cores={cores} repeat={repeat} vision_encode_ms={value}', flush=True)
                    if repeat:
                        entry['samples'].append(value)
                entry.update(status='measured', median_ms=statistics.median(entry['samples']))
            except Exception as exc:
                entry['reason'] = str(exc)
            finally:
                process.terminate()
                try:
                    process.wait(timeout=15)
                except subprocess.TimeoutExpired:
                    process.kill()
                    process.wait()
        results.append(entry)
        (out / 'measurements.json').write_text(json.dumps(results, ensure_ascii=False, indent=2))
        print(json.dumps(entry, ensure_ascii=False), flush=True)
    return 0 if all(r['status'] == 'measured' for r in results) else 1


if __name__ == '__main__':
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument('--model-dir', type=Path, required=True)
    parser.add_argument('--vision-model', type=Path)
    parser.add_argument('--image', type=Path, required=True)
    parser.add_argument('--size', type=int, required=True)
    parser.add_argument('--dense-accuracy-level', type=int, choices=[0, 1])
    parser.add_argument('--cores', type=int, nargs='+', default=[4, 8])
    parser.add_argument('--out', type=Path, required=True)
    raise SystemExit(run(parser.parse_args()))
