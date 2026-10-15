#!/usr/bin/env python3
"""Offline behavior tests for recovery, recipes, locking, cleanup, selection and reports."""
import contextlib
from http.server import BaseHTTPRequestHandler, HTTPServer
import json
from pathlib import Path
import sys
import tempfile
import threading
from types import SimpleNamespace

sys.path.insert(0, str(Path(__file__).parent))
import workflow
import audit_results


def check(condition, message):
    if not condition: raise AssertionError(message)


def downloader_test(root):
    content = (b'GGUF' + bytes(range(256)) * 8192)[:2_000_000]
    state = {'requests': 0, 'ranges': []}
    class Handler(BaseHTTPRequestHandler):
        def log_message(self, *args): pass
        def do_GET(self):
            state['requests'] += 1
            start = int(self.headers.get('Range', 'bytes=0-').split('=')[1].split('-')[0])
            state['ranges'].append(start)
            self.send_response(206 if start else 200)
            self.send_header('ETag', '"fixed-v1"')
            self.send_header('Content-Type', 'application/octet-stream')
            if start: self.send_header('Content-Range', f'bytes {start}-{len(content)-1}/{len(content)}')
            self.send_header('Content-Length', str(len(content) - start)); self.end_headers()
            if state['requests'] <= 3:
                self.wfile.write(content[start:start + 200_000]); self.wfile.flush(); self.close_connection = True
            else: self.wfile.write(content[start:])
    server = HTTPServer(('127.0.0.1', 0), Handler)
    thread = threading.Thread(target=server.serve_forever, daemon=True); thread.start()
    out, target = root / 'download', root / 'download' / 'models' / 'fixture.gguf'
    model = {'id': 'fixture'}; url = f'http://127.0.0.1:{server.server_port}/model'
    try:
        try: workflow.persistent_download(url, target, len(content), len(content), out, model)
        except RuntimeError: pass
        else: raise AssertionError('first interrupted invocation should fail')
        check(target.with_suffix('.gguf.part').exists(), 'safe partial was not preserved')
        digest = workflow.persistent_download(url, target, len(content), len(content), out, model)
        check(target.read_bytes() == content and digest == workflow.hash_file(target), 'resumed file mismatch')
        check(state['ranges'][:4] == [0, 200000, 400000, 600000], f'unexpected ranges {state["ranges"]}')
    finally:
        server.shutdown(); thread.join()
    return out, target


def main():
    with tempfile.TemporaryDirectory() as temp:
        root = Path(temp)
        recipes = json.loads(workflow.RECIPES.read_text())
        vlm = {'section': '多模态大模型', 'name': 'Qwen3.5-0.8B', 'download_url': 'x.tar.gz'}
        llm = {'section': '大模型', 'name': 'Qwen3.5-0.8B', 'download_url': 'x.gguf'}
        check(workflow.recipe_for(vlm, recipes)['adapter'] == 'vlm_server', 'VLM recipe routing failed')
        check(workflow.recipe_for(llm, recipes)['adapter'] == 'gguf', 'same-name GGUF routing failed')

        out, target = downloader_test(root)
        workflow.mark_cache(out, [target], 'measured')
        external = root / 'external.gguf'; external.write_bytes(b'keep')
        data = workflow.ledger(out)
        data['artifacts'][str(external.resolve())] = {'model_id': 'external', 'state': 'measured', 'owned_by_skill': True, 'updated_at': workflow.now()}
        workflow.atomic(out / 'cache-ledger.json', data)
        workflow.clean(out, False); check(target.exists(), 'dry-run deleted cache')
        workflow.clean(out, True); check(not target.exists(), 'eligible cache was not deleted')
        check(external.exists(), 'cleanup escaped models directory')

        lock_out = root / 'lock'
        with workflow.locked(lock_out, 'outer'):
            try:
                with workflow.locked(lock_out, 'inner'): pass
            except RuntimeError: pass
            else: raise AssertionError('second process lock was not rejected')

        first = [{'metric': '2 Core/ms', 'performance_status': 'regression_candidate'}]
        retest = [{'metric': '2 Core/ms', 'performance_status': 'regression_candidate'}]
        status, _ = workflow.select(first, retest, False, {'status': 'matched'})
        check(status == 'confirmed_regression', 'two-run regression was not confirmed')
        check(workflow.combine(first, retest)[0]['initial'] == first[0], 'initial evidence not retained')

        pipeline = root / 'pipeline'; pipeline.mkdir()
        model = {'id': 'skip-model', 'chip': 'K3', 'section': '基础模型', 'family': 'fixture',
            'name': 'skip-model', 'source_line': 1, 'headers': ['模型名', 'type', '1 Core/ms'],
            'cells': ['skip-model', 'int8', '10'], 'url': 'https://invalid/model.onnx',
            'download_url': 'https://invalid/model.onnx', 'baseline_mismatch': False}
        workflow.atomic(pipeline / 'manifest.json', [model])
        workflow.atomic(pipeline / 'source.json', {'commit': recipes['validated_source_commit'], 'sha256': 'fixture'})
        args = SimpleNamespace(action='run-all', out=pipeline, model=None, allow_large=False, rerun=False,
            remove_downloads=False, threshold=10.0, refresh_source=False, skip_kind=['vision'],
            cleanup_old_models=False, execute_cleanup=False, size_limit=5_000_000_000)
        original_chip = workflow.core.chip_detect
        workflow.core.chip_detect = lambda: ('K3', {'fixture': True})
        try:
            workflow.run_all(args, pipeline)
            skipped = json.loads((pipeline / 'results.json').read_text())[0]
            check(skipped['status'] == 'skipped_user' and len(skipped['attempts']) == 1, 'run-all skip/history failed')
            workflow.run_all(args, pipeline)
            check(len(json.loads((pipeline / 'results.json').read_text())[0]['attempts']) == 1, 'resume did not skip terminal row')
            args.rerun = True; workflow.run_all(args, pipeline)
            check(len(json.loads((pipeline / 'results.json').read_text())[0]['attempts']) == 2, 'rerun did not append history')
        finally:
            workflow.core.chip_detect = original_chip

        audio_out = root / 'audio-policy'; audio_out.mkdir()
        audio = {**model, 'id': 'audio-model', 'section': '多模态大模型', 'name': 'Qwen3-ASR 0.6B',
            'download_url': 'https://invalid/audio.tar.gz', 'url': 'https://invalid/audio.tar.gz'}
        workflow.atomic(audio_out / 'manifest.json', [audio])
        workflow.atomic(audio_out / 'source.json', {'commit': recipes['validated_source_commit'], 'sha256': 'fixture'})
        audio_args = SimpleNamespace(**{**vars(args), 'out': audio_out, 'rerun': False, 'skip_kind': []})
        original_chip = workflow.core.chip_detect
        original_size = workflow.core.size_of
        workflow.core.chip_detect = lambda: ('K3', {'fixture': True})
        workflow.core.size_of = lambda _url: (_ for _ in ()).throw(AssertionError('audio size must not be queried'))
        try:
            workflow.run_all(audio_args, audio_out)
        finally:
            workflow.core.chip_detect = original_chip
            workflow.core.size_of = original_size
        audio_result = json.loads((audio_out / 'results.json').read_text())[0]
        check(audio_result['status'] == 'skipped_policy', 'audio model was not policy-filtered')
        check(not audio_result.get('artifact') and not audio_result.get('measurements'), 'filtered audio produced test evidence')
        check(audit_results.audit(audio_out) == 0, 'audio policy result audit failed')

        report_out = root / 'report'; logs = report_out / 'runs' / 'r1' / 'm1' / 'logs'; logs.mkdir(parents=True)
        workflow.atomic(report_out / 'manifest.json', [{'id': 'm1'}])
        workflow.atomic(report_out / 'source.json', {'commit': 'c', 'sha256': 's'})
        row = {'id': 'm1', 'chip': 'K3', 'name': 'fixture', 'section': '基础模型', 'family': 'fixture',
            'source_line': 1, 'url': 'u', 'download_url': 'u', 'bytes': 4, 'artifact_sha256': 'h',
            'status': 'within_threshold', 'reason': 'ok', 'run_id': 'r1', 'selected_run_id': 'r1',
            'selection_reason': 'ok', 'recipe': {}, 'comparability': {'status': 'matched'},
            'attempts': [{'run_id': 'r1'}], 'measurements': [{'metric': '1 Core/ms', 'unit': 'ms',
            'baseline': 10.0, 'actual': 10.0, 'delta_pct': 0.0, 'regression_pct': 0.0,
            'performance_status': 'within_threshold', 'samples': [10.0, 10.0, 10.0], 'command': ['fixture'],
            'log_dir': str(logs)}]}
        workflow.atomic(report_out / 'results.json', [row]); workflow.report(report_out)
        check('source_commit' in (report_out / 'report.csv').read_text().splitlines()[0], 'audit columns missing')
        check(audit_results.audit(report_out) == 0, 'result audit failed')
    print('SELF TEST PASS')
    return 0


if __name__ == '__main__': raise SystemExit(main())
