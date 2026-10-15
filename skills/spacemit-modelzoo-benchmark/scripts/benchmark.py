#!/usr/bin/env python3
"""Source-backed SpaceMIT benchmark helpers; Python 3 standard library only."""
import argparse
import csv
import datetime
import hashlib
import http.client
import json
import math
import os
from pathlib import Path
import re
import shutil
import statistics
import subprocess
import time
import urllib.request

SOURCE = 'https://raw.githubusercontent.com/spacemit-com/docs-ai/main/zh/compute_stack/ai_compute_stack/modelzoo.md'
LIMIT = 5_000_000_000


def save(path, obj):
    path.parent.mkdir(parents=True, exist_ok=True)
    temp = path.with_suffix(path.suffix + '.tmp')
    temp.write_text(json.dumps(obj, ensure_ascii=False, indent=2))
    temp.replace(path)


def request(url, method='GET', headers=None):
    return urllib.request.urlopen(urllib.request.Request(url, method=method,
        headers={'User-Agent': 'SpaceMIT-modelzoo-validation/1.0', **(headers or {})}), timeout=45)


def chip_detect():
    evidence = {}
    for name in ['/proc/device-tree/compatible', '/proc/device-tree/model', '/sys/devices/soc0/soc_id']:
        p = Path(name)
        if p.exists():
            evidence[name] = p.read_bytes().decode(errors='replace').replace('\x00', ' ')
    found = set(re.findall(r'\bk([0-9]+)(?=[^0-9]|$)', ' '.join(evidence.values()), re.I))
    if len(found) != 1:
        raise RuntimeError('无法唯一识别芯片: ' + repr(evidence))
    return 'K' + found.pop(), evidence


def parse(text, chip):
    section = family = current_chip = ''
    headers = []
    models = []
    fenced = False
    for lineno, line in enumerate(text.splitlines(), 1):
        if line.startswith(('```', '~~~')):
            fenced = not fenced
            continue
        if fenced:
            continue
        if line.startswith('## '):
            section = line[3:].strip()
            current_chip = ''
            headers = []
        elif line.startswith('### '):
            family = line[4:].strip()
            headers = []
        m = re.fullmatch(r'\s*-\s+(K\d+)\s*', line)
        if m:
            current_chip = m[1]
        if not line.startswith('|'):
            continue
        cols = [v.strip() for v in line.strip().strip('|').split('|')]
        if cols[0] == '模型名':
            headers = cols
            continue
        if not headers or re.fullmatch(r'[-: ]+', cols[0]) or current_chip != chip:
            continue
        link = re.search(r'\[([^]]+)\]\(([^)]+)\)', cols[0])
        name, url = link.groups() if link else (cols[0], '')
        direct = re.sub(r'/file/view/', '/resolve/', url).split('?')[0]
        identity = f'{chip}/{section}/{family}/{name}/' + '/'.join(cols[1:3])
        mid = re.sub('[^a-zA-Z0-9_.-]+', '-', name).strip('-') + '-' + hashlib.sha256(identity.encode()).hexdigest()[:8]
        models.append(dict(id=mid, chip=chip, section=section, family=family, name=name,
            source_line=lineno, headers=headers[:], cells=cols, url=url, download_url=direct,
            baseline_mismatch=('Q4_0' in direct and len(cols) > 1 and cols[1] == 'Q4_1')))
    if not models:
        raise RuntimeError('没有找到适用模型；检查 Markdown 格式或芯片支持情况')
    if len({m['id'] for m in models}) != len(models):
        raise RuntimeError('模型 ID 冲突')
    return models


def discover(out):
    chip, evidence = chip_detect()
    out.mkdir(parents=True, exist_ok=True)
    source = SOURCE
    commit = None
    try:
        with request('https://api.github.com/repos/spacemit-com/docs-ai/commits/main') as r:
            commit = json.load(r)['sha']
        if not re.fullmatch('[0-9a-f]{40}', commit):
            raise ValueError('invalid commit')
        source = SOURCE.replace('/main/', '/' + commit + '/')
    except Exception:
        commit = None
    with request(source) as response:
        raw = response.read()
    (out / 'modelzoo.md').write_bytes(raw)
    models = parse(raw.decode(), chip)
    meta = dict(source=source, commit=commit, sha256=hashlib.sha256(raw).hexdigest(),
        fetched_at=datetime.datetime.now(datetime.timezone.utc).isoformat(), chip=chip, evidence=evidence)
    save(out / 'source.json', meta)
    save(out / 'manifest.json', models)
    commands = ['uname -a', 'cat /etc/os-release', 'lscpu', 'free -h', 'df -h .',
        'dpkg-query -W llama.cpp-tools-spacemit spacemit-onnxruntime python3-spacemit-ort',
        'cat /sys/devices/system/cpu/cpufreq/policy*/scaling_governor /sys/devices/system/cpu/cpufreq/policy*/scaling_cur_freq',
        'cat /sys/class/thermal/thermal_zone*/temp', 'uptime']
    with (out / 'environment.txt').open('w') as f:
        for command in commands:
            f.write('\n$ ' + command + '\n')
            f.flush()
            subprocess.run(command, shell=True, stdout=f, stderr=f)
    print(json.dumps(dict(chip=chip, models=len(models)), ensure_ascii=False))


def size_of(url):
    try:
        with request(url, 'HEAD') as r:
            if r.headers.get('Content-Length') and 'text/html' not in r.headers.get('Content-Type', ''):
                return int(r.headers['Content-Length'])
    except Exception:
        pass
    with request(url, headers={'Range': 'bytes=0-0', 'Accept-Encoding': 'identity'}) as r:
        content_range = r.headers.get('Content-Range', '')
        if '/' in content_range and content_range.split('/')[-1].isdigit():
            return int(content_range.split('/')[-1])
        if r.headers.get('Content-Length') and 'text/html' not in r.headers.get('Content-Type', ''):
            return int(r.headers['Content-Length'])
    return None


def download(url, target, expected, limit):
    if target.exists() and target.stat().st_size == expected:
        digest = hashlib.sha256()
        with target.open('rb') as f:
            for block in iter(lambda: f.read(1024 * 1024), b''):
                digest.update(block)
        return digest.hexdigest()
    part = target.with_suffix(target.suffix + '.part')
    digest = hashlib.sha256()
    count = 0
    etag = None
    try:
        with part.open('wb') as f:
            for attempt in range(3):
                headers = {'Accept-Encoding': 'identity'}
                if count and etag:
                    headers.update({'Range': f'bytes={count}-', 'If-Range': etag})
                elif count:
                    f.seek(0)
                    f.truncate()
                    count, digest = 0, hashlib.sha256()
                try:
                    with request(url, headers=headers) as r:
                        if 'text/html' in r.headers.get('Content-Type', ''):
                            raise RuntimeError('收到 HTML 而非模型')
                        if count:
                            if r.status == 200:
                                f.seek(0)
                                f.truncate()
                                count, digest = 0, hashlib.sha256()
                            elif r.status != 206 or not r.headers.get('Content-Range', '').startswith(f'bytes {count}-'):
                                raise RuntimeError('断点续传范围不匹配')
                        response_etag = r.headers.get('ETag')
                        if count and response_etag and response_etag != etag:
                            raise RuntimeError('续传期间 ETag 改变')
                        etag = response_etag if response_etag and not response_etag.startswith('W/') else None
                        while True:
                            block = r.read(1024 * 1024)
                            if not block:
                                break
                            count += len(block)
                            if count > limit or count > expected:
                                raise RuntimeError('下载超过声明大小或限制')
                            f.write(block)
                            digest.update(block)
                    if count == expected:
                        break
                    if attempt == 2:
                        raise RuntimeError(f'下载不完整 {count}/{expected}')
                except (OSError, TimeoutError, http.client.IncompleteRead) as exc:
                    if attempt == 2:
                        raise
                    print(f'Download retry {attempt+1}/2 at {count} bytes: {type(exc).__name__}', flush=True)
                time.sleep(2)
        if count != expected:
            raise RuntimeError(f'大小不符 {count} != {expected}')
        with part.open('rb') as f:
            prefix = f.read(64)
        if prefix.lstrip().startswith((b'<html', b'<!DOCTYPE')):
            raise RuntimeError('模型内容为网页')
        if target.suffix == '.gguf' and prefix[:4] != b'GGUF':
            raise RuntimeError('GGUF magic 不符')
        part.replace(target)
        return digest.hexdigest()
    finally:
        if part.exists():
            part.unlink()


def compare(actual, baseline, higher=False, threshold=10):
    if not math.isfinite(actual) or not math.isfinite(baseline) or baseline <= 0 or actual <= 0:
        raise ValueError('无效指标')
    delta = (actual - baseline) / baseline * 100
    regression = -delta if higher else delta
    return dict(actual=actual, baseline=baseline, delta_pct=delta, regression_pct=regression,
                status='regression' if regression > threshold else 'ok')


def execute(command, log, timeout):
    start = time.time()
    with log.open('w') as f:
        f.write('$ ' + json.dumps(command) + '\n')
        f.flush()
        try:
            proc = subprocess.run(command, stdout=f, stderr=subprocess.STDOUT, timeout=timeout)
            code = proc.returncode
        except subprocess.TimeoutExpired:
            code = 124
        f.write(f'\nexit_code={code} elapsed_seconds={time.time()-start:.3f}\n')
    text = log.read_text(errors='replace')
    if code:
        raise RuntimeError(f'exit={code}; log={log}')
    return text


def measure(m, path, out, threshold):
    entries = []
    if path.suffix == '.onnx':
        for header, value in zip(m['headers'], m['cells']):
            match = re.fullmatch(r'(\d+) Core/ms', header)
            if not match or not re.fullmatch(r'\d+(\.\d+)?', value):
                continue
            cores = int(match[1])
            command = ['onnxruntime_perf_test', str(path), '-e', 'spacemit', '-r', '10', '-x', '1', '-S', '1', '-s', '-c', '1', '-i', f'SPACEMIT_EP_INTRA_THREAD_NUM|{cores}', '-I']
            entry = dict(metric=header, unit='ms', command=command)
            try:
                samples = []
                hardware_limited = False
                for repeat in range(4):
                    log = out / 'logs' / f'{m["id"]}-{cores}core-{repeat}.log'
                    text = execute(command, log, 600)
                    if not re.search(r'using SpaceMITExecutionProvider', text, re.I):
                        raise RuntimeError('未确认 SpaceMITExecutionProvider')
                    hardware_limited |= 'failed to open aidma list' in text
                    match_value = re.search(r'Average inference time cost total:\s*([\d.eE+-]+)\s*ms', text)
                    if not match_value:
                        raise RuntimeError('缺少官方毫秒计时字段')
                    if repeat:
                        samples.append(float(match_value[1]))
                entry.update(compare(statistics.median(samples), float(value), threshold=threshold), samples=samples)
                if hardware_limited:
                    entry.update(status='blocked_hardware_access', reason='aidma 访问失败，数值为受限环境结果，不能正式判断退化')
            except Exception as exc:
                entry.update(status='runtime_failed', reason=str(exc))
            entries.append(entry)
    elif path.suffix == '.gguf':
        for tokens in (128, 1280):
            expected = {}
            for header, value in zip(m['headers'], m['cells']):
                match = re.fullmatch(r'(PP|TG)' + str(tokens) + r' \(token/s\)', header)
                if match and re.fullmatch(r'\d+(\.\d+)?', value):
                    expected[match[1].lower() + str(tokens)] = float(value)
            if not expected:
                continue
            command = ['llama-bench', '-m', str(path), '-t', '8', '-p', str(tokens), '-n', str(tokens), '-mmp', '0', '-fa', '1', '-ub', '128']
            try:
                samples = {key: [] for key in expected}
                for repeat in range(4):
                    text = execute(command, out / 'logs' / f'{m["id"]}-{tokens}-{repeat}.log', 1800)
                    if 'CPU_RISCV64_SPACEMIT' not in text:
                        raise RuntimeError('未确认 SpaceMIT 后端；需要检查日志与构建')
                    for key in expected:
                        result = re.search(r'\|\s*' + key + r'\s*\|\s*([\d.]+)', text)
                        if not result:
                            raise RuntimeError('未发现计时字段 ' + key)
                        if repeat:
                            samples[key].append(float(result[1]))
                for key, baseline in expected.items():
                    entry = dict(metric=key, unit='token/s', command=command, samples=samples[key])
                    entry.update(compare(statistics.median(samples[key]), baseline, True, threshold))
                    if m['baseline_mismatch']:
                        entry.update(status='baseline_mismatch', reason='链接与表格量化不同，百分比仅供探索')
                    entries.append(entry)
            except Exception as exc:
                entries.extend(dict(metric=key, unit='token/s', command=command, status='runtime_failed', reason=str(exc)) for key in expected)
    return entries


def run(args, out):
    if args.allow_large and not args.model:
        raise RuntimeError('--allow-large 必须指定单个 --model')
    manifest = json.loads((out / 'manifest.json').read_text())
    chip, _ = chip_detect()
    if any(m['chip'] != chip for m in manifest):
        raise RuntimeError('清单芯片与当前设备不符')
    if args.model and args.model not in {m['id'] for m in manifest}:
        raise RuntimeError('未知 model ID')
    result_path = out / ('results-large-' + args.model + '.json' if args.allow_large else 'results.json')
    results = json.loads(result_path.read_text()) if result_path.exists() else []
    (out / 'models').mkdir(exist_ok=True)
    (out / 'logs').mkdir(exist_ok=True)
    for m in manifest:
        if args.model and m['id'] != args.model:
            continue
        if any(r['id'] == m['id'] for r in results) and not args.rerun:
            continue
        row = dict(m, measurements=[])
        print('START', m['id'], flush=True)
        try:
            if not m['download_url']:
                row.update(status='blocked_method', reason='官方表无模型下载链接；须查关联文档')
            else:
                size = size_of(m['download_url'])
                row['bytes'] = size
                if size is None:
                    row.update(status='blocked_size_unknown')
                elif size > LIMIT and not args.allow_large:
                    row.update(status='skipped_size', reason='超过 5,000,000,000 字节；独立补测须 --model ID --allow-large')
                elif not m['download_url'].endswith(('.onnx', '.gguf')):
                    row.update(status='needs_adapter', reason='归档模型需要专用音频/多模态流程，按 SKILL.md 继续')
                elif shutil.disk_usage(out).free < size + 2_000_000_000:
                    row.update(status='blocked_resource', reason='保留 2GB 磁盘余量后空间不足')
                else:
                    path = out / 'models' / (m['id'] + Path(m['download_url']).suffix)
                    row['sha256'] = download(m['download_url'], path, size, size if args.allow_large else LIMIT)
                    row['artifact'] = str(path)
                    row['measurements'] = measure(m, path, out, args.threshold)
                    statuses = {r['status'] for r in row['measurements']}
                    row['status'] = next((s for s in ['runtime_failed', 'blocked_hardware_access', 'baseline_mismatch', 'regression'] if s in statuses), 'ok')
                    if not statuses:
                        row.update(status='blocked_method', reason='没有可用基准配置')
                    if args.remove_downloads:
                        path.unlink()
        except Exception as exc:
            row.update(status='download_failed', reason=str(exc))
        results = [r for r in results if r['id'] != m['id']] + [row]
        save(result_path, results)
        print('END', m['id'], row['status'], flush=True)
        report(out, result_path)


def report(out, result_path=None):
    result_path = result_path or out / 'results.json'
    results = json.loads(result_path.read_text())
    manifest = json.loads((out / 'manifest.json').read_text())
    flat = []
    for row in results:
        for metric in row.get('measurements') or [{}]:
            flat.append({**dict(id=row['id'], model=row['name'], section=row['section'], status=row['status'], bytes=row.get('bytes'), reason=row.get('reason', '')), **metric})
    stem = 'report' if result_path.name == 'results.json' else result_path.stem
    columns = ['id', 'model', 'section', 'metric', 'unit', 'baseline', 'actual', 'delta_pct', 'regression_pct', 'status', 'bytes', 'reason', 'samples', 'command']
    with (out / (stem + '.csv')).open('w', newline='') as f:
        writer = csv.DictWriter(f, columns, extrasaction='ignore')
        writer.writeheader()
        writer.writerows(flat)
    counts = {s: sum(r['status'] == s for r in results) for s in sorted({r['status'] for r in results})}
    lines = ['# SpaceMIT ModelZoo 性能验证', '', '状态为动态实测快照；needs_adapter 和缺失条目必须继续处理，不能宣称全部完成。', '',
        f'适用模型 {len(manifest)}；已记录 {len(results)}；未记录 {len(manifest)-len(results)}。状态：{counts}', '',
        '差异=(实测-官方)/官方×100%；ms/RTF 正数为变慢，token/s 负数为变慢。默认退化阈值10%。环境与官方版本差异见 environment.txt 和 modelzoo.md。', '',
        '## 性能告警', '', '|模型|指标|官方|实测|退化%|', '|---|---|---:|---:|---:|']
    for r in sorted(flat, key=lambda x: x.get('regression_pct', -1e9), reverse=True):
        if r['status'] == 'regression':
            lines.append(f'|{r["model"]}|{r["metric"]}|{r["baseline"]}|{r["actual"]:.4f}|{r["regression_pct"]:.2f}|')
    lines += ['', '## 完整覆盖清单', '', '|模型ID|状态|下载字节数|原因|', '|---|---|---:|---|']
    for r in results:
        reason = str(r.get('reason', '')).replace('|', '/')
        lines.append(f'|{r["id"]}|{r["status"]}|{r.get("bytes", "未知")}|{reason}|')
    lines += ['', '## 超大模型独立补测', '']
    for r in results:
        if r['status'] == 'skipped_size':
            lines += [f'- {r["id"]}：{r["bytes"]} 字节；[下载]({r["download_url"]})。',
                f'  `python3 scripts/benchmark.py run --out {out} --model {r["id"]} --allow-large`；归档模型须按 SKILL.md 核实专用适配方法，独立结果不覆盖本批次。']
    (out / (stem + '.md')).write_text('\n'.join(lines) + '\n')


def main():
    p = argparse.ArgumentParser(description=__doc__)
    p.add_argument('action', choices=['discover', 'run', 'run-all', 'report', 'cleanup-cache'])
    p.add_argument('--out', type=Path, default=Path('results'))
    p.add_argument('--model')
    p.add_argument('--allow-large', action='store_true')
    p.add_argument('--rerun', action='store_true')
    p.add_argument('--remove-downloads', action='store_true', help='仅删除本工具缓存的当前模型')
    p.add_argument('--threshold', type=float, default=10)
    p.add_argument('--refresh-source', action='store_true')
    p.add_argument('--skip-kind', action='append', default=[], choices=['audio', 'vlm', 'llm', 'vision'])
    p.add_argument('--cleanup-old-models', action='store_true',
        help='表示本次已获用户授权，可按 cache-ledger.json 清理已测缓存')
    p.add_argument('--execute-cleanup', action='store_true',
        help='cleanup-cache 实际执行；省略时只预览')
    p.add_argument('--size-limit', type=int, default=LIMIT)
    args = p.parse_args()
    out = args.out.resolve()
    if args.action == 'run-all':
        import workflow
        workflow.run_all(args, out)
    elif args.action == 'cleanup-cache':
        import workflow
        workflow.cleanup(args, out)
    elif args.action == 'discover':
        discover(out)
    elif args.action == 'run':
        run(args, out)
    else:
        import workflow
        workflow.report(out)


if __name__ == '__main__':
    main()
