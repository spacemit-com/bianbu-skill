#!/usr/bin/env python3
"""Portable fixed VPU entrypoint. Host-independent subprocess interface."""
from pathlib import Path
import json
import os
import signal
import shutil
import subprocess
import sys
import tempfile

sys.dont_write_bytecode = True
from tooling import missing_mvx_tools


VERSION = '0.13.12'
TIMEOUT_SECONDS = 1500
DEPENDENCY_PACKAGE = 'k3x-vpu-test'
SCHEMA = {
    'type': 'object', 'additionalProperties': False,
    'description': '可选 VPU 性能用例筛选。省略条件跑所有匹配项；空对象跑默认 13 项。无匹配则报错。',
    'properties': {
        'codec': {'type': 'string', 'enum': ['h264', 'h265', 'vp8', 'vp9', 'mjpeg']},
        'operation': {'type': 'string', 'enum': ['encode', 'decode']},
        'sessions': {'type': 'integer', 'minimum': 1, 'maximum': 32, 'description': '路数；单路填 1'},
        'resolution': {'type': 'string', 'enum': ['4k', '1080p']},
    },
}


def select_cases(filters, cases):
    if not isinstance(filters, dict) or set(filters) - set(SCHEMA['properties']):
        raise ValueError('筛选仅接受 codec、operation、sessions、resolution 对象。')
    for key, value in filters.items():
        if key == 'sessions':
            if type(value) is not int or not 1 <= value <= 32:
                raise ValueError('sessions 必须是 1 到 32 的整数。')
        elif value not in SCHEMA['properties'][key]['enum']:
            raise ValueError(f'{key} 必须是 {SCHEMA["properties"][key]["enum"]}')
    selected = []
    for case in cases:
        values = dict(codec=case['codec'], operation=case['operation'], sessions=case['sessions'],
                      resolution=case.get('asset_variant', '1080p'))
        if all(values[key] == value for key, value in filters.items()):
            selected.append(case['id'])
    if not selected:
        raise ValueError('没有匹配的已注册用例；未执行测试。可用用例：' + '；'.join(c['label'] for c in cases))
    return selected


def failure(status, reason, directory=None):
    # JSON quoting keeps untrusted diagnostics on one line, not as Markdown instructions.
    reason = json.dumps(str(reason)[:2000], ensure_ascii=False)
    return (f'# VPU Benchmark\n\n状态：{status}\n\n'
            f'## 测试版本\n\n- Skill: {VERSION}\n- Python: {sys.version.split()[0]}\n'
            '- 板卡及组件版本：未取得完整结果，请查看运行日志。\n\n'
            '## 性能结果\n\n未完成完整测试，不推断性能或验收结论。\n\n'
            f'## 异常\n\n{reason}\n\n'
            f'## 报告\n\n日志目录：{directory or "未创建"}\n')


def stop_group(proc):
    # Workload descendants share the session; do not leave FFmpeg/MVX running.
    try:
        os.killpg(proc.pid, signal.SIGTERM)
    except ProcessLookupError:
        return
    try:
        proc.wait(timeout=5)
    except subprocess.TimeoutExpired:
        pass
    try:
        os.killpg(proc.pid, signal.SIGKILL)
    except ProcessLookupError:
        pass
    proc.wait()


def ensure_mvx_dependency():
    missing = missing_mvx_tools()
    if not missing:
        return

    apt_get = shutil.which('apt-get')
    command = None
    if apt_get and hasattr(os, 'geteuid') and os.geteuid() == 0:
        command = [apt_get, 'install', '-y', DEPENDENCY_PACKAGE]
    elif apt_get and (sudo := shutil.which('sudo')):
        command = [sudo, '-n', apt_get, 'install', '-y', DEPENDENCY_PACKAGE]

    install_detail = 'Agent 环境没有可用的无交互 sudo。'
    if command:
        try:
            call = subprocess.run(command, text=True, capture_output=True, timeout=180, check=False)
            if call.returncode == 0 and not missing_mvx_tools():
                return
            install_detail = f'自动安装失败（退出码 {call.returncode}）。'
        except subprocess.TimeoutExpired:
            install_detail = '自动安装超过 180 秒，已停止等待。'
        except OSError as exc:
            install_detail = f'自动安装无法启动：{exc}。'

    missing_text = ', '.join(missing_mvx_tools() or missing)
    raise RuntimeError(
        f'缺少依赖包 {DEPENDENCY_PACKAGE} 提供的命令：{missing_text}。{install_detail}'
        f'请用户在板端手动执行 `sudo apt install {DEPENDENCY_PACKAGE}`；'
        f'如果使用已下载的 DEB，执行 `sudo apt install ./k3x-vpu-test_*.deb`，安装完成后重新运行测试。'
    )


def execute(runner, timeout=TIMEOUT_SECONDS, filters=None):
    directory = None
    proc = None
    try:
        filters = {} if filters is None else filters
        cases = json.loads((Path(runner).resolve().parents[1]/'references/default-baselines.json').read_text(encoding='utf-8'))['cases']
        selected = select_cases(filters, cases)
        if os.name != 'posix':
            return failure('ERROR', 'VPU hardware execution requires Linux.'), 2
        ensure_mvx_dependency()
        state = Path(os.environ.get('XDG_STATE_HOME', Path.home()/'.local/state'))/'vpu-benchmark/results'
        state.mkdir(parents=True, exist_ok=True)
        directory = Path(tempfile.mkdtemp(prefix='entry-', dir=state))
        (directory/'request.json').write_text(json.dumps({'filters': filters, 'selected_cases': selected}, ensure_ascii=False, indent=2), encoding='utf-8')
        argv = [sys.executable, '-B', str(runner), 'run', '--output-dir', str(directory)]
        for case_id in selected:
            argv += ['--case', case_id]
        with (directory/'runner.stdout').open('w', encoding='utf-8') as output:
            proc = subprocess.Popen(argv,
                                    stdout=output, stderr=None, start_new_session=True,
                                    env={**os.environ, 'PYTHONIOENCODING': 'utf-8',
                                         'PYTHONDONTWRITEBYTECODE': '1'})
            try:
                code = proc.wait(timeout=timeout)
            except subprocess.TimeoutExpired:
                stop_group(proc)
                return failure('TIMEOUT', f'超过 {timeout} 秒，已终止本次测试进程组。', directory), 124
            except KeyboardInterrupt:
                stop_group(proc)
                return failure('CANCELLED', '用户中断，已终止本次测试进程组。', directory), 130
        raw = (directory/'runner.stdout').read_text(encoding='utf-8')
        try:
            result = json.loads(raw)
        except (ValueError, TypeError):
            result = {}
        if (isinstance(result, dict) and code in (0, 1)
                and result.get('status') in ('PASS', 'WARN', 'FAIL', 'MEASURED')
                and isinstance(result.get('display_markdown'), str)
                and result['display_markdown'].strip()):
            return result['display_markdown'].rstrip() + '\n', code
        reason = result.get('error', f'执行器退出码 {code}；未产生有效报告。') if isinstance(result, dict) else '执行器未产生有效报告。'
        return failure('ERROR', reason, directory), 2
    except Exception as exc:
        if proc is not None and proc.poll() is None:
            stop_group(proc)
        return failure('ERROR', f'{type(exc).__name__}: {exc}', directory), 2


def read_available_stdin(limit=8192, timeout=0.1):
    """Read an already-present stdin request without waiting for a host pipe EOF."""
    if sys.stdin.isatty():
        return ''
    try:
        import select
        ready, _, _ = select.select([sys.stdin], [], [], timeout)
    except (OSError, ValueError):
        return ''
    if not ready:
        return ''
    raw = os.read(sys.stdin.fileno(), limit + 1)
    if len(raw) > limit:
        raise ValueError(f'输入超过 {limit} 字符。')
    return raw.decode('utf-8')


def parse_request(argv):
    if not argv:
        raw = read_available_stdin()
    elif len(argv) == 2 and argv[0] == '--request-json':
        raw = argv[1]
    else:
        raise ValueError('仅接受 --describe 或 --request-json JSON；也可通过 stdin JSON 输入。')
    filters = json.loads(raw) if raw.strip() else {}
    if not isinstance(filters, dict):
        raise ValueError('输入必须是 JSON 对象。')
    return filters


def main():
    if sys.argv[1:] == ['--describe']:
        print(json.dumps(SCHEMA, ensure_ascii=False))
        return 0
    try:
        filters = parse_request(sys.argv[1:])
        report, code = execute(Path(__file__).resolve().with_name('regression.py'), filters=filters)
    except (ValueError, OSError, UnicodeError) as exc:
        report, code = failure('ERROR', str(exc)), 2
    sys.stdout.write(report)
    return code

if __name__ == '__main__':
    raise SystemExit(main())
