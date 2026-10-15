#!/usr/bin/env python3
"""Full workflow layered on benchmark.py: recipes, history, recovery, locking and VLM."""
import contextlib
import csv
import datetime
import fcntl
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
import tarfile
import time
import urllib.parse
import urllib.request
import zlib

import benchmark as core

ROOT = Path(__file__).resolve().parent.parent
RECIPES = ROOT / 'references' / 'recipes.json'
TERMINAL = {'within_threshold', 'confirmed_regression', 'review_required', 'environment_mismatch',
            'baseline_mismatch', 'skipped_size', 'skipped_user', 'skipped_policy', 'blocked_method',
            'blocked_recipe_review', 'blocked_size_unknown'}


def now():
    return datetime.datetime.now(datetime.timezone.utc).isoformat()


def atomic(path, data):
    path.parent.mkdir(parents=True, exist_ok=True)
    temp = path.with_suffix(path.suffix + '.tmp')
    temp.write_text(json.dumps(data, ensure_ascii=False, indent=2) + '\n')
    temp.replace(path)


def hash_file(path):
    digest = hashlib.sha256()
    with path.open('rb') as stream:
        for block in iter(lambda: stream.read(4 * 1024 * 1024), b''):
            digest.update(block)
    return digest.hexdigest()


def packages(names):
    answer = {}
    for name in names:
        try:
            result = subprocess.run(['dpkg-query', '-W', '-f=${Version}', name], capture_output=True, text=True)
            answer[name] = result.stdout.strip() if result.returncode == 0 else None
        except FileNotFoundError:
            answer[name] = None
    return answer


def interference():
    targets, found = {'llama-bench', 'llama-server', 'onnxruntime_perf_test', 'benchmark.py', 'vlm_server_bench.py'}, []
    for proc in Path('/proc').glob('[0-9]*'):
        if int(proc.name) == os.getpid(): continue
        try:
            args = [value.decode(errors='replace') for value in (proc / 'cmdline').read_bytes().split(b'\0') if value]
        except (OSError, ValueError):
            continue
        names = {Path(value).name for value in args[:2]}
        if names & targets: found.append({'pid': int(proc.name), 'command': args})
    return found


def environment(out, package_names=()):
    frequencies = {}
    for policy in sorted(Path('/sys/devices/system/cpu/cpufreq').glob('policy*')):
        frequencies[policy.name] = {key: (policy / key).read_text().strip()
            for key in ['scaling_cur_freq', 'scaling_min_freq', 'scaling_max_freq', 'scaling_governor']
            if (policy / key).exists()}
    memory, meminfo = {}, Path('/proc/meminfo')
    for line in (meminfo.read_text().splitlines() if meminfo.exists() else []):
        if ':' in line and line.split(':', 1)[0] in {'MemTotal', 'MemAvailable', 'SwapTotal', 'SwapFree'}:
            key, value = line.split(':', 1); memory[key] = value.strip()
    disk = shutil.disk_usage(out)
    return {'at': now(), 'loadavg': list(os.getloadavg()), 'frequencies': frequencies,
            'memory': memory, 'disk_free': disk.free, 'packages': packages(package_names),
            'interfering_benchmarks': interference(), 'pid': os.getpid()}


@contextlib.contextmanager
def locked(out, operation):
    out.mkdir(parents=True, exist_ok=True)
    lock_path = out / '.benchmark.lock'
    handle = lock_path.open('a+')
    try:
        try:
            fcntl.flock(handle, fcntl.LOCK_EX | fcntl.LOCK_NB)
        except BlockingIOError:
            handle.seek(0)
            raise RuntimeError('已有任务持有工作区锁：' + handle.read())
        owner = {'pid': os.getpid(), 'operation': operation, 'started_at': now()}
        handle.seek(0); handle.truncate(); handle.write(json.dumps(owner)); handle.flush()
        atomic(out / 'active-operation.json', owner)
        yield
    finally:
        (out / 'active-operation.json').unlink(missing_ok=True)
        fcntl.flock(handle, fcntl.LOCK_UN); handle.close()


def ledger(out):
    path = out / 'cache-ledger.json'
    return json.loads(path.read_text()) if path.exists() else {'schema_version': 1, 'artifacts': {}, 'cleanup_history': []}


def record_cache(out, path, model, url, size, digest, state='downloaded'):
    data = ledger(out)
    data['artifacts'][str(path.resolve())] = {'model_id': model['id'], 'url': url, 'bytes': size,
        'sha256': digest, 'state': state, 'owned_by_skill': True, 'updated_at': now()}
    atomic(out / 'cache-ledger.json', data)


def mark_cache(out, paths, state):
    data = ledger(out)
    for path in paths:
        item = data['artifacts'].get(str(path.resolve()))
        if item:
            item.update(state=state, updated_at=now())
    atomic(out / 'cache-ledger.json', data)


def cache_path(out, raw):
    path, root = Path(raw), (out / 'models').resolve()
    try:
        path.resolve().relative_to(root)
    except ValueError:
        return None
    return path if not path.is_symlink() else None


def clean(out, execute=False, need=0, exclude=()):
    data, candidates, reclaimed = ledger(out), [], 0
    excluded = {str(Path(path).resolve()) for path in exclude}
    for raw, item in sorted(data['artifacts'].items(), key=lambda pair: pair[1].get('updated_at', '')):
        path = cache_path(out, raw)
        if not path or raw in excluded or not path.exists() or not item.get('owned_by_skill') or item.get('state') != 'measured':
            continue
        size = path.stat().st_size if path.is_file() else sum(p.stat().st_size for p in path.rglob('*') if p.is_file())
        candidates.append({'path': raw, 'bytes': size, 'model_id': item['model_id']})
        if execute:
            shutil.rmtree(path) if path.is_dir() else path.unlink()
            reclaimed += size
            item.update(state='cleaned', cleaned_at=now())
            data['cleanup_history'].append({'path': raw, 'bytes': size, 'model_id': item['model_id'], 'at': now()})
            if reclaimed >= need:
                break
    if execute:
        atomic(out / 'cache-ledger.json', data)
    result = {'execute': execute, 'candidates': candidates, 'reclaimed_bytes': reclaimed}
    print(json.dumps(result, ensure_ascii=False, indent=2))
    return reclaimed


def clean_selected(out, paths):
    data, reclaimed = ledger(out), 0
    for path in paths:
        raw, safe = str(path.resolve()), cache_path(out, str(path.resolve()))
        item = data['artifacts'].get(raw)
        if not safe or not safe.exists() or not item or not item.get('owned_by_skill') or item.get('state') != 'measured':
            continue
        size = safe.stat().st_size if safe.is_file() else sum(p.stat().st_size for p in safe.rglob('*') if p.is_file())
        shutil.rmtree(safe) if safe.is_dir() else safe.unlink()
        reclaimed += size; item.update(state='cleaned', cleaned_at=now())
        data['cleanup_history'].append({'path': raw, 'bytes': size, 'model_id': item['model_id'], 'at': now(), 'reason': 'remove-downloads'})
    atomic(out / 'cache-ledger.json', data)
    return reclaimed


def require_space(out, amount, authorized, exclude=()):
    if shutil.disk_usage(out).free >= amount:
        return
    if authorized:
        clean(out, True, amount - shutil.disk_usage(out).free, exclude)
    if shutil.disk_usage(out).free < amount:
        raise RuntimeError(f'blocked_resource: 需要 {amount} 字节，当前空闲 {shutil.disk_usage(out).free}')


def open_url(url, headers=None):
    return urllib.request.urlopen(urllib.request.Request(url,
        headers={'User-Agent': 'SpaceMIT-modelzoo-validation/2.0', 'Accept-Encoding': 'identity', **(headers or {})}), timeout=45)


def persistent_download(url, target, expected, limit, out, model):
    target.parent.mkdir(parents=True, exist_ok=True)
    if target.exists() and target.stat().st_size == expected:
        digest = hash_file(target); record_cache(out, target, model, url, expected, digest); return digest
    part = target.with_suffix(target.suffix + '.part')
    state_file = target.with_suffix(target.suffix + '.part.json')
    state = json.loads(state_file.read_text()) if state_file.exists() else {}
    invalid = state.get('url') != url or state.get('expected') != expected
    if part.exists() and part.stat().st_size > expected: invalid = True
    if invalid:
        part.unlink(missing_ok=True); state_file.unlink(missing_ok=True); state = {}
    last = None
    for attempt in range(3):
        count, etag = (part.stat().st_size if part.exists() else 0), state.get('etag')
        if count and not etag:
            part.unlink(); count = 0
        headers = {'Range': f'bytes={count}-', 'If-Range': etag} if count else {}
        try:
            with open_url(url, headers) as response:
                if 'text/html' in response.headers.get('Content-Type', ''):
                    raise RuntimeError('收到 HTML 而非模型')
                response_etag = response.headers.get('ETag')
                strong = response_etag if response_etag and not response_etag.startswith('W/') else None
                if count and (response.status != 206 or not response.headers.get('Content-Range', '').startswith(f'bytes {count}-') or strong != etag):
                    part.unlink(missing_ok=True); state_file.unlink(missing_ok=True)
                    raise OSError('服务端不满足安全续传条件，重置分片')
                state = {'url': url, 'expected': expected, 'etag': strong, 'updated_at': now()}
                atomic(state_file, state)
                with part.open('ab' if count else 'wb') as stream:
                    while True:
                        block = response.read(1024 * 1024)
                        if not block: break
                        count += len(block)
                        if count > expected or count > limit:
                            raise RuntimeError('下载超过声明大小或限制')
                        stream.write(block)
                if count != expected: raise OSError(f'下载不完整 {count}/{expected}')
            with part.open('rb') as stream: prefix = stream.read(64)
            if prefix.lstrip().startswith((b'<html', b'<!DOCTYPE')): raise RuntimeError('模型内容为网页')
            if target.suffix == '.gguf' and prefix[:4] != b'GGUF': raise RuntimeError('GGUF magic 不符')
            digest = hash_file(part); part.replace(target); state_file.unlink(missing_ok=True)
            record_cache(out, target, model, url, expected, digest); return digest
        except (OSError, TimeoutError, http.client.IncompleteRead) as exc:
            last = exc
            print(f'Download retry {attempt + 1}/3, saved={part.stat().st_size if part.exists() else 0}: {exc}', flush=True)
            if attempt < 2: time.sleep(2)
        except Exception:
            part.unlink(missing_ok=True); state_file.unlink(missing_ok=True); raise
    raise RuntimeError(f'download_failed: 保留安全分片供下次续传：{last}')


def safe_extract(archive, destination, out, model, digest, reserve):
    marker = destination / '.extract-complete.json'
    if marker.exists() and json.loads(marker.read_text()).get('archive_sha256') == digest:
        metadata = json.loads(marker.read_text())
        record_cache(out, destination, model, model['download_url'] + '#extracted', metadata['declared_unpacked_bytes'], digest)
        return
    if destination.exists():
        raise RuntimeError('目标解包目录已存在但没有匹配的完成标记，不自动删除')
    temporary = destination.with_name(destination.name + '.extracting')
    if temporary.exists(): shutil.rmtree(temporary)
    temporary.mkdir(parents=True)
    with tarfile.open(archive, 'r:*') as bundle:
        members, total = bundle.getmembers(), 0
        for member in members:
            try: (temporary / member.name).resolve().relative_to(temporary.resolve())
            except ValueError: raise RuntimeError('归档包含路径穿越')
            if member.issym() or member.islnk() or member.isdev(): raise RuntimeError('归档包含链接或设备节点')
            total += max(member.size, 0)
        if total + reserve > shutil.disk_usage(temporary).free: raise RuntimeError('blocked_resource: 解包空间不足')
        bundle.extractall(temporary, members=members)
    atomic(temporary / '.extract-complete.json', {'archive_sha256': digest, 'declared_unpacked_bytes': total, 'completed_at': now()})
    temporary.replace(destination)
    record_cache(out, destination, model, model['download_url'] + '#extracted', total, digest)


def make_png(path, size):
    if path.exists(): return
    path.parent.mkdir(parents=True, exist_ok=True)
    raw = bytearray()
    for y in range(size):
        raw.append(0)
        for x in range(size): raw.extend(((x * 255) // max(1, size - 1), (y * 255) // max(1, size - 1), ((x + y) * 127) // max(1, size - 1)))
    def chunk(kind, data):
        return len(data).to_bytes(4, 'big') + kind + data + (zlib.crc32(kind + data) & 0xffffffff).to_bytes(4, 'big')
    header = size.to_bytes(4, 'big') * 2 + bytes([8, 2, 0, 0, 0])
    path.write_bytes(b'\x89PNG\r\n\x1a\n' + chunk(b'IHDR', header) + chunk(b'IDAT', zlib.compress(bytes(raw), 9)) + chunk(b'IEND', b''))


def one_file(root, patterns):
    files = sorted({p.resolve() for pattern in patterns for p in root.rglob(pattern) if p.is_file()})
    if len(files) != 1: raise RuntimeError(f'配方未唯一匹配 {patterns}：{files}')
    return files[0]


def performance(actual, baseline, higher, threshold):
    delta = (actual - baseline) / baseline * 100
    degradation = -delta if higher else delta
    status = 'regression_candidate' if degradation > threshold else ('review_required' if degradation < -threshold else 'within_threshold')
    return {'actual': actual, 'baseline': baseline, 'delta_pct': delta,
            'regression_pct': degradation, 'performance_status': status}


def direct_measure(model, artifact, directory, threshold):
    (directory / 'logs').mkdir(parents=True, exist_ok=True)
    measurements = core.measure(model, artifact, directory, threshold)
    for item in measurements:
        old = item.pop('status')
        if old not in {'ok', 'regression', 'baseline_mismatch'}:
            raise RuntimeError(f'{old}: {item.get("reason", "直接模型测试失败")}')
        item['performance_status'] = {'ok': 'within_threshold', 'regression': 'regression_candidate'}.get(old, old)
        item['log_dir'] = str(directory / 'logs')
    return measurements


def vlm_measure(model, package, recipe, directory, threshold):
    directory.mkdir(parents=True, exist_ok=True)
    configs = list(package.rglob('config.json'))
    if len(configs) != 1: raise RuntimeError(f'配方要求唯一 config.json：{configs}')
    model_dir = configs[0].parent
    text_model, vision_model = one_file(model_dir, recipe['text_model_globs']), one_file(model_dir, recipe['vision_model_globs'])
    image = directory.parents[3] / 'inputs' / f'vlm-{recipe["input_size"]}.png'; make_png(image, recipe['input_size'])
    command = ['python3', str(ROOT / 'scripts' / 'vlm_server_bench.py'), '--model-dir', str(model_dir), '--vision-model', str(vision_model),
        '--image', str(image), '--size', str(recipe['input_size']), '--cores', *map(str, recipe['cores']), '--out', str(directory / 'vlm')]
    if recipe.get('dense_accuracy_level') is not None: command += ['--dense-accuracy-level', str(recipe['dense_accuracy_level'])]
    core.execute(command, directory / 'adapter.log', 3600)
    raw, answer = json.loads((directory / 'vlm' / 'measurements.json').read_text()), []
    for entry in raw:
        if entry['status'] != 'measured': raise RuntimeError(entry.get('reason', 'VLM 运行失败'))
        metric = f'LLM 8 Core + VisionEncoder {entry["cores"]} Core/ms'
        baseline = float(model['cells'][model['headers'].index(metric)])
        item = {'metric': metric, 'unit': 'ms', 'samples': entry['samples'], 'command': entry['command'],
            'log_dir': str(directory / 'vlm' / f'{entry["cores"]}core'), 'input_sha256': hash_file(image),
            'text_model': str(text_model), 'vision_model': str(vision_model)}
        item.update(performance(entry['median_ms'], baseline, False, threshold)); answer.append(item)
    return answer


def recipe_for(model, recipes):
    exact = recipes['models'].get(model['section'] + '/' + model['name'])
    if exact: return exact
    path = urllib.parse.urlsplit(model['download_url']).path.lower()
    for recipe in recipes['handlers'].values():
        if any(path.endswith(suffix) for suffix in recipe['match_extensions']): return recipe
    return {'kind': 'unknown', 'adapter': 'unsupported', 'official_packages': {}}


def quant_mismatch(model):
    table = next((v for h, v in zip(model['headers'], model['cells']) if h.lower() in {'type', '量化'}), '')
    mentioned = re.findall(r'Q\d(?:_[A-Z0-9]+)?', model['download_url'], re.I)
    return bool(table and mentioned and all(value.lower() not in table.lower() for value in mentioned))


def comparison(recipe):
    expected = recipe.get('official_packages', {}); actual = packages(expected)
    mismatches = {name: {'expected': value, 'actual': actual.get(name)} for name, value in expected.items() if actual.get(name) != value}
    return {'status': 'matched' if not mismatches else 'limited', 'expected': expected, 'actual': actual, 'mismatches': mismatches}


def select(first, retest, mismatch, comparable):
    if mismatch: return 'baseline_mismatch', '下载模型量化与表格量化不一致，仅作探索'
    if retest is not None:
        before = {item['metric']: item for item in first}
        confirmed = [item for item in retest if item['performance_status'] == 'regression_candidate'
            and before.get(item['metric'], {}).get('performance_status') == 'regression_candidate']
        return ('confirmed_regression', '初测和自动复测均超过退化阈值') if confirmed else ('review_required', '初测异常但自动复测未确认')
    if any(item['performance_status'] == 'review_required' for item in first): return 'review_required', '性能明显快于官方值，需核对环境和测量边界'
    if comparable['status'] == 'limited': return 'environment_mismatch', '软件包版本与官方基准环境不同'
    return 'within_threshold', '全部配置在阈值内'


def combine(first, retest):
    if retest is None: return first
    before = {item['metric']: item for item in first}; answer = []
    for item in retest:
        item, initial = dict(item), before.get(item['metric'])
        item['initial'] = initial
        if initial and initial['performance_status'] == item['performance_status'] == 'regression_candidate': item['performance_status'] = 'confirmed_regression'
        elif initial and initial['performance_status'] == 'regression_candidate': item['performance_status'] = 'review_required'
        answer.append(item)
    return answer


def result_path(out, args):
    return out / (f'results-large-{args.model}.json' if args.allow_large else 'results.json')


def store_result(path, row):
    rows = json.loads(path.read_text()) if path.exists() else []
    old = next((item for item in rows if item['id'] == row['id']), None)
    if old: row['attempts'] = old.get('attempts', []) + row['attempts']
    atomic(path, [item for item in rows if item['id'] != row['id']] + [row])


def run_model(model, recipe, args, out, run_id):
    path = result_path(out, args)
    old = next((item for item in json.loads(path.read_text()) if item['id'] == model['id']), None) if path.exists() else None
    if old and not args.rerun and old.get('status') in TERMINAL:
        print('RESUME-SKIP', model['id'], old['status']); return
    row = {**model, 'recipe': recipe, 'run_id': run_id, 'attempts': [], 'size_limit_bytes': args.size_limit}
    attempt_dir = out / 'runs' / run_id / model['id']; names = recipe.get('official_packages', {})
    attempt = {'run_id': run_id, 'started_at': now(), 'environment_before': environment(out, names)}
    artifacts = []
    try:
        if recipe['kind'] == 'audio':
            row.update(status='skipped_policy', reason='当前 skill 策略过滤音频模型，不检查大小、下载或测试')
        elif recipe['kind'] in args.skip_kind: row.update(status='skipped_user', reason=f'用户通过 --skip-kind 跳过 {recipe["kind"]}')
        elif not model['download_url']: row.update(status='blocked_method', reason='官方表没有下载链接')
        else:
            size = core.size_of(model['download_url']); row['bytes'] = size
            if size is None: row.update(status='blocked_size_unknown', reason='无法可靠取得模型包大小')
            elif size > args.size_limit and not args.allow_large: row.update(status='skipped_size', reason=f'{size} 字节超过 {args.size_limit}')
            elif recipe['adapter'] in {'vlm_server', 'asr_server'} and json.loads((out / 'source.json').read_text()).get('commit') != json.loads(RECIPES.read_text())['validated_source_commit']:
                row.update(status='blocked_recipe_review', reason='ModelZoo commit 已变化，专用配方需要复核')
            elif recipe['adapter'] in {'unsupported', 'asr_server'}: row.update(status='blocked_method', reason='v2 尚未实现该专用适配器')
            else:
                reserve = json.loads(RECIPES.read_text())['defaults']['reserve_disk_bytes']
                require_space(out, size * (3 if recipe['adapter'] == 'vlm_server' else 1) + reserve, args.cleanup_old_models)
                url_path = urllib.parse.urlsplit(model['download_url']).path.lower()
                suffix = '.tar.gz' if url_path.endswith('.tar.gz') else Path(url_path).suffix
                artifact = out / 'models' / (model['id'] + suffix); artifacts.append(artifact)
                digest = persistent_download(model['download_url'], artifact, size, size if args.allow_large else args.size_limit, out, model)
                row.update(artifact=str(artifact), artifact_sha256=digest)
                if recipe['adapter'] == 'vlm_server':
                    package = out / 'models' / (model['id'] + '.package'); artifacts.append(package)
                    safe_extract(artifact, package, out, model, digest, reserve)
                    conflicts = interference()
                    if conflicts: raise RuntimeError('blocked_resource: 发现并发性能进程 ' + json.dumps(conflicts, ensure_ascii=False))
                    first = vlm_measure(model, package, recipe, attempt_dir / 'initial', args.threshold)
                else:
                    conflicts = interference()
                    if conflicts: raise RuntimeError('blocked_resource: 发现并发性能进程 ' + json.dumps(conflicts, ensure_ascii=False))
                    first = direct_measure(model, artifact, attempt_dir / 'initial', args.threshold)
                retest = None
                if any(item['performance_status'] == 'regression_candidate' for item in first):
                    attempt['environment_before_retest'] = environment(out, names)
                    retest = vlm_measure(model, package, recipe, attempt_dir / 'retest', args.threshold) if recipe['adapter'] == 'vlm_server' else direct_measure(model, artifact, attempt_dir / 'retest', args.threshold)
                comparable = comparison(recipe); status, reason = select(first, retest, quant_mismatch(model), comparable)
                row.update(status=status, reason=reason, comparability=comparable, measurements=combine(first, retest),
                    selected_run_id=run_id, selection_reason=reason)
                attempt.update(initial_measurements=first, retest_measurements=retest, selected_measurements=row['measurements'])
                mark_cache(out, artifacts, 'measured')
                if args.remove_downloads: clean_selected(out, artifacts)
        attempt.update(status=row['status'], reason=row.get('reason'), finished_at=now(), environment_after=environment(out, names))
    except Exception as exc:
        reason = str(exc)
        status = 'blocked_hardware_access' if 'blocked_hardware_access' in reason else ('download_failed' if not artifacts or not artifacts[0].exists() else 'runtime_failed')
        row.update(status=status, reason=reason); attempt.update(status=status, reason=reason, finished_at=now(), environment_after=environment(out, names))
    row['attempts'].append(attempt); store_result(path, row); print('END', model['id'], row['status'], flush=True)


def serial(value):
    return json.dumps(value, ensure_ascii=False) if isinstance(value, (dict, list)) else value


def report(out, path=None):
    path = path or out / 'results.json'; rows = json.loads(path.read_text())
    manifest, source = json.loads((out / 'manifest.json').read_text()), json.loads((out / 'source.json').read_text())
    flat = []
    for row in rows:
        for measurement in row.get('measurements') or [{}]:
            base = {key: row.get(key) for key in ['id', 'chip', 'name', 'section', 'family', 'source_line', 'url', 'download_url', 'bytes',
                'artifact_sha256', 'status', 'reason', 'run_id', 'selected_run_id', 'selection_reason']}
            base.update(source_commit=source.get('commit'), source_sha256=source.get('sha256'), recipe=row.get('recipe'),
                comparability=row.get('comparability'), attempts=row.get('attempts'))
            flat.append({**base, **measurement})
    fields = ['id', 'chip', 'name', 'section', 'family', 'source_line', 'source_commit', 'source_sha256', 'url', 'download_url', 'bytes',
        'artifact_sha256', 'metric', 'unit', 'baseline', 'actual', 'delta_pct', 'regression_pct', 'performance_status', 'status', 'reason',
        'samples', 'command', 'log_dir', 'input_sha256', 'recipe', 'comparability', 'run_id', 'selected_run_id', 'selection_reason', 'initial', 'attempts']
    stem = 'report' if path.name == 'results.json' else path.stem
    with (out / f'{stem}.csv').open('w', newline='') as stream:
        writer = csv.DictWriter(stream, fields, extrasaction='ignore'); writer.writeheader()
        writer.writerows([{key: serial(value) for key, value in item.items()} for item in flat])
    counts = {status: sum(row['status'] == status for row in rows) for status in sorted({row['status'] for row in rows})}
    lines = ['# SpaceMIT ModelZoo 性能验证 v2', '', f'适用 {len(manifest)} 项，记录 {len(rows)} 项。状态：`{counts}`。', '',
        '## 已确认性能告警', '', '|模型|指标|官方|实测|退化%|', '|---|---|---:|---:|---:|']
    for row in rows:
        for item in row.get('measurements', []):
            if item.get('performance_status') == 'confirmed_regression': lines.append(f'|{row["name"]}|{item["metric"]}|{item["baseline"]}|{item["actual"]:.4f}|{item["regression_pct"]:.2f}|')
    lines += ['', '## 需复核', '', '|模型|状态|原因|', '|---|---|---|']
    for row in rows:
        if row['status'] in {'review_required', 'environment_mismatch', 'baseline_mismatch', 'blocked_recipe_review'}:
            lines.append(f'|{row["name"]}|{row["status"]}|{row.get("reason", "")}|')
    lines += ['', '## 完整覆盖清单', '', '|模型ID|状态|字节数|原因|', '|---|---|---:|---|']
    for row in sorted(rows, key=lambda item: item['id']): lines.append(f'|{row["id"]}|{row["status"]}|{row.get("bytes", "")}|{str(row.get("reason", "")).replace("|", "/")}|')
    lines += ['', '## >5GB 独立补测', '']
    for row in rows:
        if row['status'] == 'skipped_size': lines += [f'- `{row["id"]}`：{row.get("bytes")} 字节，{row["download_url"]}', f'  `python3 scripts/benchmark.py run-all --out {out} --model {row["id"]} --allow-large`']
    (out / f'{stem}.md').write_text('\n'.join(lines) + '\n')


def run_all(args, out):
    with locked(out, 'run-all'):
        if args.refresh_source or not (out / 'manifest.json').exists(): core.discover(out)
        models = json.loads((out / 'manifest.json').read_text()); chip, _ = core.chip_detect()
        if any(model['chip'] != chip for model in models): raise RuntimeError('清单芯片与设备不一致')
        if args.allow_large and not args.model: raise RuntimeError('--allow-large 必须指定单个 --model')
        if args.model and args.model not in {model['id'] for model in models}: raise RuntimeError('未知 model ID')
        recipes = json.loads(RECIPES.read_text()); run_id = datetime.datetime.now().strftime('%Y%m%dT%H%M%S') + f'-{os.getpid()}'
        arguments = {key: (str(value) if isinstance(value, Path) else value) for key, value in vars(args).items()}
        atomic(out / 'runs' / run_id / 'run.json', {'run_id': run_id, 'started_at': now(), 'arguments': arguments, 'pid': os.getpid()})
        for model in models:
            if args.model and model['id'] != args.model: continue
            run_model(model, recipe_for(model, recipes), args, out, run_id); report(out, result_path(out, args))
        metadata = json.loads((out / 'runs' / run_id / 'run.json').read_text()); metadata['finished_at'] = now(); atomic(out / 'runs' / run_id / 'run.json', metadata)


def cleanup(args, out):
    with locked(out, 'cleanup-cache'): clean(out, args.execute_cleanup)
