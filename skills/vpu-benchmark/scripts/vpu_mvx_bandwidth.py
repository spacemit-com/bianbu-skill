"""Paced MVX session bandwidth. No DDR controller reader or single-stream extrapolation."""
import contextlib
import fcntl
import json
import os
from pathlib import Path
import re
import subprocess
import tempfile
import time

import benchmark as b

METHOD = 'mvx-session-profile-v1'
RECORD = re.compile(r'MVX session:\s*(\S+).*?bus_write_bytes_total=(\d+)\.\s*bus_read_bytes_total=(\d+)\.\s*avg_write_bw=(\d+),\s*avg_read_bw=(\d+)')


def parse_records(text, count, fps):
    records = []
    for match in RECORD.finditer(text):
        sid, wt, rt, wa, ra = match.groups()
        records.append(dict(session=sid, write_bytes_total=int(wt), read_bytes_total=int(rt),
                            write_bytes_per_frame=int(wa), read_bytes_per_frame=int(ra)))
    if len(records) != count or len({r['session'] for r in records}) != count:
        raise b.BenchmarkError(f'Expected {count} distinct MVX session records, received {len(records)}; no bandwidth inferred')
    for r in records:
        if r['read_bytes_per_frame'] + r['write_bytes_per_frame'] <= 0:
            raise b.BenchmarkError('Empty MVX bandwidth record')
        r['mbps'] = (r['read_bytes_per_frame'] + r['write_bytes_per_frame']) * fps / 1_000_000
    return records


def group(case, input_path, directory, phase):
    count, fps = case['sessions'], case['mvx_bandwidth_target_fps']
    cursor = b.journal_cursor()
    if not cursor:
        raise b.BenchmarkError('MVX profiling requires a readable kernel journal cursor')
    directory.mkdir(parents=True, exist_ok=True)
    workers = []
    with contextlib.ExitStack() as stack:
        # Keep output handling bounded. Decoder frames are consumed/discarded by MVX;
        # profiling counts the hardware bus, not filesystem traffic.
        temp = Path(stack.enter_context(tempfile.TemporaryDirectory(prefix='vpu-mvx-bandwidth-')))
        try:
            for index in range(count):
                spec = dict(version=1, name=f'mvx-bw-{index}', operation=case['operation'],
                            codec=case['codec'], device='auto', input=input_path, frames=case['frames'],
                            sessions=1, fps=fps, profiling=True, overwrite=True)
                if case['operation'] == 'encode':
                    spec.update(width=case['width'], height=case['height'],
                                output=str(temp/f'output-{index}{b.CODEC_SUFFIX[case["codec"]]}'))
                argv, device = b.compile_argv(b.normalize(spec))
                logpath = directory/f'{phase}-channel-{index+1:02d}.log'
                log = stack.enter_context(logpath.open('w'))
                workers.append(dict(handle=log, argv=argv, log=str(logpath), device=device, channel=index+1))
            deadline = time.monotonic() + 120
            for w in workers:
                w['process'] = subprocess.Popen(w['argv'], stdout=w.pop('handle'), stderr=subprocess.STDOUT)
                w['start'] = time.monotonic()
            while any('end' not in w for w in workers):
                for w in workers:
                    if 'end' not in w and w['process'].poll() is not None:
                        w['end'] = time.monotonic()
                if time.monotonic() > deadline:
                    raise b.BenchmarkError('MVX profiling group timed out')
                time.sleep(.01)
            for w in workers:
                w['returncode'] = w.pop('process').returncode
                w['metrics'] = b.parse_metrics(Path(w['log']).read_text(errors='replace'))
                m = w['metrics']
                if w['returncode'] or m['mvx_status'] != 'pass' or not m['average_fps']:
                    raise b.BenchmarkError(f'MVX profiling channel {w["channel"]} failed; see {w["log"]}')
                if phase == 'formal' and m['average_fps'] < fps * .95:
                    raise b.BenchmarkError(f'MVX channel {w["channel"]} missed target {fps} FPS: {m["average_fps"]}')
            overlap = min(w['end'] for w in workers) - max(w['start'] for w in workers)
            overlap_ratio = overlap / min(w['end']-w['start'] for w in workers)
            if count > 1 and overlap_ratio < .9:
                raise b.BenchmarkError('MVX channels did not overlap for 90% of the shortest run')
            journal = subprocess.run(['journalctl','-k','--after-cursor',cursor,'--no-pager','-o','cat'],
                                     capture_output=True,text=True,timeout=10)
            (directory/f'{phase}-kernel.log').write_text(journal.stdout)
            if journal.returncode:
                raise b.BenchmarkError('Cannot read MVX profile records')
            records = parse_records(journal.stdout, count, fps)
            return dict(workers=workers, records=records, overlap_ratio=overlap_ratio,
                        total_mbps=round(sum(r['mbps'] for r in records),4))
        finally:
            for w in workers:
                p = w.get('process')
                if p is not None and p.poll() is None:
                    p.terminate()
                    try: p.wait(timeout=3)
                    except subprocess.TimeoutExpired:
                        p.kill(); p.wait()


def measure(case, input_path, directory):
    directory = Path(directory)
    directory.mkdir(parents=True, exist_ok=True)
    result = dict(method=METHOD, scope='sum of measured MVX sessions', units='MB/s',
                  sessions=case['sessions'], target_fps_per_session=case['mvx_bandwidth_target_fps'],
                  frames_per_session=case['frames'], source='MVX kernel profiling',
                  formula='sum((avg_write_bytes_per_frame + avg_read_bytes_per_frame) * target_fps) / 1000000',
                  output_policy='encode elementary stream to temporary file; decode without YUV file',
                  ok=False)
    state = Path(os.environ.get('XDG_STATE_HOME', Path.home()/'.local/state'))/'vpu-benchmark'
    state.mkdir(parents=True, exist_ok=True)
    try:
        with (state/'mvx-bandwidth.lock').open('a') as lock:
            fcntl.flock(lock, fcntl.LOCK_EX | fcntl.LOCK_NB)
            active = subprocess.run(['pgrep','-f',r'(^|/)(mvx_encoder|mvx_decoder|mvx_encoder_multi|mvx_decoder_multi)( |$)'],capture_output=True,text=True)
            if active.returncode == 0:
                raise b.BenchmarkError('Another MVX workload is running; cannot attribute profiling records')
            result['warmup_frames_per_session'] = min(30, case['frames'])
            warm_case = dict(case, frames=result['warmup_frames_per_session'])
            result['warmup_iterations'] = case['warmup_iterations'] if case['sessions'] == 1 else 0
            result['warmup'] = [group(warm_case,input_path,directory,f'warmup-{i+1}') for i in range(result['warmup_iterations'])]
            result['formal'] = group(case,input_path,directory,'formal')
            result['total_mbps'] = result['formal']['total_mbps']
            result['ok'] = True
    except (OSError, b.BenchmarkError, subprocess.SubprocessError) as exc:
        result['error'] = str(exc)
    (directory/'bandwidth.json').write_text(json.dumps(result,ensure_ascii=False,indent=2))
    return result
