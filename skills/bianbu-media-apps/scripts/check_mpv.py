#!/usr/bin/env python3
"""Bounded MPV evidence collection; never equates CLI playback with GUI acceptance."""
import argparse
import contextlib
import datetime
import io
import json
import os
from pathlib import Path
import shutil
import signal
import socket
import subprocess
import sys
import tempfile
import time

sys.dont_write_bytecode = True
import acceptance


class Blocked(Exception):
    pass


def write_json(path, value):
    path.write_text(json.dumps(value, ensure_ascii=False, indent=2) + '\n', encoding='utf-8')


def command(argv, timeout=8, env=None):
    result = subprocess.run(argv, env=env, stdin=subprocess.DEVNULL,
                            capture_output=True, text=True, timeout=timeout)
    if result.returncode:
        raise Blocked(f'{argv[0]} failed ({result.returncode}): {result.stderr[-600:]}')
    return result.stdout


def display_environment():
    env = os.environ.copy()
    # A terminal agent may lack the desktop environment (notably XWayland DISPLAY).
    # Read only selected variables from our own real desktop session, never invent :0.
    sessions=[]
    for entry in Path('/proc').iterdir():
        if not entry.name.isdigit():
            continue
        try:
            if entry.stat().st_uid != os.getuid() or (entry/'comm').read_text().strip() not in {'lxqt-session','gnome-session-b','xfce4-session','plasmashell'}:
                continue
            values={}
            for item in (entry/'environ').read_bytes().split(b'\0'):
                key,sep,value=item.partition(b'=')
                if sep and key in {b'DISPLAY',b'WAYLAND_DISPLAY',b'XDG_RUNTIME_DIR',b'DBUS_SESSION_BUS_ADDRESS',b'XAUTHORITY'}:
                    values[key.decode()]=value.decode(errors='replace')
            if env.get('WAYLAND_DISPLAY') and values.get('WAYLAND_DISPLAY') not in {None,env['WAYLAND_DISPLAY']}:
                continue
            sessions.append(values)
        except OSError:
            continue
    for key in ['DISPLAY','WAYLAND_DISPLAY','XDG_RUNTIME_DIR','DBUS_SESSION_BUS_ADDRESS','XAUTHORITY']:
        choices={s[key] for s in sessions if s.get(key)}
        if not env.get(key) and len(choices)==1:
            env[key]=choices.pop()
    runtime = Path(env.get('XDG_RUNTIME_DIR') or f'/run/user/{os.getuid()}')
    wayland = env.get('WAYLAND_DISPLAY')
    if wayland:
        if not (runtime / wayland).is_socket():
            raise Blocked('WAYLAND_DISPLAY does not point to a live socket')
    else:
        sockets = sorted(p for p in runtime.glob('wayland-*') if p.is_socket())
        if len(sockets) == 1:
            wayland = sockets[0].name
        elif len(sockets) > 1:
            raise Blocked('Multiple Wayland sessions; specify the target WAYLAND_DISPLAY')
    if wayland:
        env.update(XDG_RUNTIME_DIR=str(runtime), WAYLAND_DISPLAY=wayland)
    elif not env.get('DISPLAY'):
        raise Blocked('No accessible graphical display; no headless fallback')
    if (runtime / 'bus').is_socket():
        env.setdefault('DBUS_SESSION_BUS_ADDRESS', 'unix:path=' + str(runtime / 'bus'))
    return env


class IPC:
    def __init__(self, path):
        self.sock = socket.socket(socket.AF_UNIX, socket.SOCK_STREAM)
        self.sock.settimeout(2)
        self.sock.connect(str(path))
        self.buffer = b''
        self.request_id = 0

    def call(self, args):
        self.request_id += 1
        self.sock.sendall((json.dumps({'command': args, 'request_id': self.request_id}) + '\n').encode())
        deadline = time.monotonic() + 2
        while time.monotonic() < deadline:
            while b'\n' in self.buffer:
                line, self.buffer = self.buffer.split(b'\n', 1)
                reply = json.loads(line)
                if reply.get('request_id') == self.request_id:
                    return reply
            self.sock.settimeout(max(.01, deadline - time.monotonic()))
            chunk = self.sock.recv(65536)
            if not chunk:
                raise Blocked('MPV IPC closed; stop sampling instead of retrying playback')
            self.buffer += chunk
        raise Blocked('MPV IPC response timeout')

    def close(self):
        self.sock.close()


def container_matches(case, probe):
    names = set(probe.get('format', {}).get('format_name', '').split(','))
    brand = probe.get('format', {}).get('tags', {}).get('major_brand', '').strip()
    if case == '8':
        return 'mp4' in names and brand not in {'', 'qt'}
    if case == '11':
        return 'mov' in names and brand == 'qt'
    if case in {'9', '12'}:
        # ffprobe shares a demuxer for Matroska/WebM; inspect EBML DocType separately.
        return False
    return {'10': 'avi', '13': 'flv'}[case] in names


def observe_seek(get, target, before, timeout=5.0):
    """Wait for the landing, then any forward progress; no minimum playback rate."""
    started = time.monotonic()
    landing = continued = None
    samples = []
    while time.monotonic() - started < timeout:
        seeking = get('seeking')
        position = get('time-pos')
        elapsed = time.monotonic() - started
        samples.append(dict(elapsed_seconds=round(elapsed,3),seeking=seeking,position=position))
        if seeking is False and isinstance(position,(int,float)):
            if landing is None:
                # Keep a loose landing sanity check so ordinary playback is not a seek.
                correct_direction = position > before if target > before else position < before
                if abs(position-target) < 2 and correct_direction:
                    landing = position
            elif position > landing:
                continued = position
                break
        time.sleep(.2)
    return dict(before=before,target=target,actual=landing,continued=continued,
                jumped=landing is not None,resumed=continued is not None,
                timeout_seconds=timeout,elapsed_seconds=round(time.monotonic()-started,3),samples=samples)


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument('--input', required=True, type=Path)
    parser.add_argument('--case', choices=['8', '9', '10', '11', '12', '13'], default='8')
    parser.add_argument('--run-dir', type=Path)
    parser.add_argument('--controls', default='', help='CLI controls: pause,seek,volume,fullscreen')
    args = parser.parse_args()
    controls = set(filter(None, args.controls.split(',')))
    if controls - {'pause','seek','volume','fullscreen'}:
        parser.error('Unknown control diagnostic')
    media = args.input.expanduser().resolve()
    if args.run_dir:
        run = args.run_dir.expanduser().resolve()
    else:
        base = Path(os.environ.get('XDG_STATE_HOME', str(Path.home()/'.local/state'))) / 'bianbu-media-apps'
        base.mkdir(parents=True, exist_ok=True)
        run = base / ('mpv-' + datetime.datetime.now().strftime('%Y%m%d-%H%M%S') + '-' + os.urandom(4).hex())
    with contextlib.redirect_stdout(io.StringIO()):
        acceptance.init(run, 'mpv')
    data = acceptance.read(run/'results.json')
    envinfo = data['environment']
    envinfo.update(host=socket.gethostname(), app_version='unavailable', display_session='unavailable',
                   gui_tool='No GUI input automation; grim screenshots if available')
    checks, samples, trace, warnings = {}, [], [], []
    process = ipc = logfile = temporary = None
    error = None
    started = time.monotonic()

    def event(action, **extra):
        trace.append(dict(at=acceptance.now(), action=action, **extra))

    def evidence(filename, kind, description, producer):
        path = run/'evidence'/filename
        if path.is_file() and path.stat().st_size:
            data['evidence'].append(dict(id=path.stem, path='evidence/'+filename, kind=kind,
                captured_at=datetime.datetime.fromtimestamp(path.stat().st_mtime, datetime.timezone.utc).isoformat(),
                producer=producer, description=description))

    def deadline(signum, frame):
        raise Blocked('Collection stopped at the time limit or by cancellation')

    old_handlers = {sig: signal.signal(sig, deadline) for sig in (signal.SIGALRM, signal.SIGTERM, signal.SIGINT)}
    signal.alarm(45)
    try:
        if not media.is_file():
            raise Blocked('Input file is missing: '+str(media))
        if not shutil.which('mpv') or not shutil.which('ffprobe'):
            raise Blocked('mpv and ffprobe must already be installed')
        envinfo['app_version'] = command(['mpv', '--version']).splitlines()[0]
        probe = json.loads(command(['ffprobe','-v','error','-show_format','-show_streams','-of','json',str(media)]))
        write_json(run/'evidence/media.json', probe)
        streams = probe.get('streams', [])
        video = next((s for s in streams if s.get('codec_type') == 'video'), None)
        if video is None:
            raise Blocked('No video stream in the selected file')
        audio = next((s for s in streams if s.get('codec_type') == 'audio'), {})
        fmt = probe.get('format', {})
        envinfo['media'] = [dict(path=str(media), container=fmt.get('format_name'), video_codec=video.get('codec_name'),
            audio_codec=audio.get('codec_name'), width=video.get('width'), height=video.get('height'),
            fps=video.get('avg_frame_rate'), duration=fmt.get('duration'), size=media.stat().st_size)]
        matches = container_matches(args.case, probe)
        if args.case in {'9','12'}:
            with media.open('rb') as source:
                header = source.read(4096)
            # EBML DocType element 0x4282 followed by a one-byte length.
            doc_type = b'matroska' if args.case == '9' else b'webm'
            matches = b'\x42\x82'+bytes([0x80+len(doc_type)])+doc_type in header
        checks['container_matches'] = dict(status='PASS' if matches else 'BLOCKED', case_id=args.case, format=fmt.get('format_name'))
        if not matches:
            raise Blocked('Selected file does not establish the requested container type')
        env = display_environment()
        envinfo['display_session'] = '; '.join(f'{k}={env.get(k, "")}' for k in ['XDG_RUNTIME_DIR','WAYLAND_DISPLAY','DISPLAY'])
        temporary = tempfile.TemporaryDirectory(prefix='media-app-ipc-')
        sockpath = Path(temporary.name)/'mpv.sock'
        argv = ['mpv', '--input-ipc-server='+str(sockpath), str(media)]
        event('launch', argv=argv, purpose='Graphical playback collection; not a GUI-click/drag action')
        logfile = (run/'evidence/mpv.log').open('w', encoding='utf-8')
        process = subprocess.Popen(argv, env=env, stdin=subprocess.DEVNULL, stdout=logfile, stderr=subprocess.STDOUT)
        event('spawned', pid=process.pid)
        wait_until = time.monotonic()+10
        while not sockpath.exists():
            if process.poll() is not None:
                raise Blocked(f'MPV exited before IPC startup ({process.returncode})')
            if time.monotonic() >= wait_until:
                raise Blocked('MPV startup exceeded 10 seconds')
            time.sleep(.1)
        ipc = IPC(sockpath)
        ready_until = time.monotonic()+8
        while ipc.call(['get_property','time-pos']).get('data') is None:
            if time.monotonic() >= ready_until:
                raise Blocked('Playback position unavailable after startup')
            time.sleep(.1)
        for index in range(3):
            time.sleep(1 if index == 0 else 2)
            sample = {'at': acceptance.now()}
            for key in ['time-pos','pause','hwdec-current','current-vo','video-params','frame-drop-count',
                        'decoder-frame-drop-count','display-fps','container-fps','avsync','audio-params','current-ao']:
                reply = ipc.call(['get_property',key])
                sample[key] = reply.get('data') if reply.get('error') == 'success' else {'error': reply.get('error')}
            samples.append(sample)
            write_json(run/'evidence/samples.json', samples)
            event('sample', index=index+1, position=sample.get('time-pos'))
        def get(key):
            reply = ipc.call(['get_property',key])
            if reply.get('error') != 'success':
                raise Blocked('Control property unavailable: '+key)
            return reply['data']
        def set_value(key,value):
            reply = ipc.call(['set_property',key,value])
            event('ipc_control', property=key, value=value, response=reply.get('error'))
            if reply.get('error') != 'success':
                raise Blocked('Control operation failed: '+key)
        if 'pause' in controls:
            original = get('pause')
            try:
                set_value('pause',True)
                before = get('time-pos')
                time.sleep(1)
                paused = get('time-pos')
                set_value('pause',False)
                time.sleep(1)
                resumed = get('time-pos')
                checks['pause_resume_interface'] = dict(status='PASS' if abs(paused-before)<.1 and resumed>paused+.5 else 'FAIL',
                    positions=[before,paused,resumed],note='IPC interface only; no GUI button validation')
            finally:
                set_value('pause',original)
        if 'seek' in controls:
            duration = get('duration')
            if not isinstance(duration,(int,float)) or duration<5:
                checks['seek_interface'] = dict(status='BLOCKED',note='Media too short or duration unknown')
            else:
                points=[]
                for target in [duration*.65,duration*.2]:
                    before=get('time-pos')
                    reply=ipc.call(['seek',target,'absolute+exact'])
                    event('ipc_seek',target=target,response=reply.get('error'))
                    point=observe_seek(get,target,before) if reply.get('error')=='success' else dict(target=target,before=before,jumped=False,resumed=False)
                    point['response']=reply.get('error')
                    points.append(point)
                checks['seek_interface']=dict(status='PASS' if all(p['response']=='success' and p['jumped'] and p['resumed'] for p in points) else 'FAIL',
                    points=points,note='Confirm seek landing then any playback progress within 5 seconds; no minimum progress amount or rate; IPC only')
        for key in ['volume','fullscreen']:
            if key not in controls:
                continue
            original=get(key)
            target=max(0,original-10) if key=='volume' and original>0 else 10 if key=='volume' else not original
            try:
                set_value(key,target)
                time.sleep(.3)
                observed=get(key)
                set_value(key,original)
                time.sleep(.3)
                restored=get(key)
                checks[key+'_interface']=dict(status='PASS' if observed==target and restored==original else 'FAIL',before=original,requested=target,observed=observed,restored=restored,
                    note='Property control only; actual sound/visual GUI effect still requires review')
            finally:
                set_value(key,original)
    except (Blocked, OSError, ValueError, subprocess.TimeoutExpired) as exc:
        error = str(exc)
    finally:
        signal.alarm(0)
        try:
            if process is not None:
                if process.poll() is None:
                    if ipc is not None:
                        try:
                            ipc.call(['quit'])
                            event('quit', pid=process.pid, mechanism='IPC cleanup; not GUI close acceptance')
                        except (Blocked, OSError, ValueError):
                            pass
                    try:
                        process.wait(timeout=3)
                    except subprocess.TimeoutExpired:
                        event('terminate_owned_pid', pid=process.pid)
                        process.terminate()
                        try:
                            process.wait(timeout=2)
                        except subprocess.TimeoutExpired:
                            event('kill_owned_pid', pid=process.pid)
                            process.kill()
                            process.wait(timeout=2)
                checks['process_exit'] = dict(status='PASS' if process.returncode == 0 else 'FAIL', exit_code=process.returncode)
                event('exited', pid=process.pid, exit_code=process.returncode)
        finally:
            if ipc is not None:
                ipc.close()
            if logfile is not None:
                logfile.close()
            if temporary is not None:
                temporary.cleanup()
            for sig, handler in old_handlers.items():
                signal.signal(sig, handler)

    positions = [s['time-pos'] for s in samples if isinstance(s.get('time-pos'), (int,float))]
    checks['playback_position_advances'] = dict(status='PASS' if len(positions)>=2 and positions[-1]>positions[0]+.5
        else 'BLOCKED' if error else 'FAIL', positions=positions)
    hw = [s.get('hwdec-current') for s in samples]
    checks['hardware_decoder'] = dict(status='PASS' if hw and all(v=='stcodec' for v in hw) else 'BLOCKED', observed=hw,
        note='PASS means stcodec observed at every sample; other values require interpretation, not assumed failure')
    has_audio=bool(envinfo['media'] and envinfo['media'][0].get('audio_codec'))
    av=[s.get('avsync') for s in samples if isinstance(s.get('avsync'),(int,float))]
    checks['av_sync_clock']=dict(status=('NOT_APPLICABLE' if not has_audio and envinfo['media'] else
        'BLOCKED' if len(av)<3 else 'PASS' if max(abs(v) for v in av)<=.1 else 'FAIL'),
        values=av,tolerance_seconds=.1,note='No audio track' if not has_audio else 'Player A/V clock only, provisional 100 ms tolerance; not physical sound/image synchrony')
    if samples:
        checks['display'] = dict(status='OBSERVED', vo=samples[-1].get('current-vo'),
            fps=samples[-1].get('display-fps'), source_fps=samples[-1].get('container-fps'),
            dropped=samples[-1].get('frame-drop-count'), decoder_dropped=samples[-1].get('decoder-frame-drop-count'))
    logpath = run/'evidence/mpv.log'
    if logpath.exists():
        for line in logpath.read_text(encoding='utf-8',errors='replace').splitlines():
            if '[MPP-ERROR]' in line or 'Error opening' in line:
                message = line.strip()[-400:]
                if message not in warnings:
                    warnings.append(message)
                if len(warnings) >= 12:
                    break
    automatic = dict(collection_status='BLOCKED' if error else 'COMPLETED', error=error,
                     elapsed_seconds=round(time.monotonic()-started,2), checks=checks, warnings=warnings)
    write_json(run/'evidence/samples.json',samples)
    write_json(run/'evidence/actions.json',trace)
    write_json(run/'evidence/automatic.json',automatic)
    for filename, kind in [('media.json','media_probe'),('samples.json','time_series'),('actions.json','cli_trace'),
                           ('automatic.json','diagnostic'),('mpv.log','diagnostic')]:
        evidence(filename,kind,'Bounded collector evidence; does not substitute for required GUI actions','check_mpv.py')
    selected = next(row for row in data['cases'] if row['id'] == args.case)
    reason = error or 'Automatic playback evidence collected; original GUI action and visual acceptance require review'
    selected.update(status='BLOCKED', actual_result=reason, reason_code='COLLECTION_BLOCKED' if error else 'GUI_ACCEPTANCE_PENDING')
    for step in selected['steps']:
        step.update(status='BLOCKED', reason=reason)
    data['finished_at'] = acceptance.now()
    data['automatic_checks'] = automatic
    write_json(run/'results.json',data)
    _, errors = acceptance.validate(run,'mpv')
    if errors:
        print(json.dumps({'status':'ERROR','errors':errors,'run_dir':str(run)},ensure_ascii=False))
        return 2
    with contextlib.redirect_stdout(io.StringIO()):
        acceptance.report(run,data)
    with (run/'report.md').open('a',encoding='utf-8') as report:
        report.write('\n## 自动播放检查（独立于原表 GUI 验收）\n\n')
        report.write('自动取证不代替文件管理器打开、拖拽、点击和画面审阅。原表项目保留 BLOCKED，其余项目 NOT_RUN。\n\n')
        report.write('| 检查 | 状态 | 证据 |\n|---|---|---|\n')
        for name,check in checks.items():
            report.write('| '+acceptance.esc(name)+' | '+check['status']+' | '+acceptance.esc(json.dumps(check,ensure_ascii=False))+' |\n')
        report.write('\n耗时：'+str(automatic['elapsed_seconds'])+' 秒。\n')
        if warnings:
            report.write('\n运行警告：\n\n'+'\n'.join('- '+w for w in warnings)+'\n')
    print(json.dumps(dict(status='REPORTED', collection_status=automatic['collection_status'],
        application='mpv',case=args.case,case_status='BLOCKED',reason_code=selected['reason_code'],
        checks=checks,warnings=warnings,error=error,elapsed_seconds=automatic['elapsed_seconds'],
        run_dir=str(run),report=str(run/'report.md'),
        next_action='Return these results and the report now. Do not rerun, reconstruct scripts or infer GUI PASS.'),ensure_ascii=False))
    return 0


if __name__ == '__main__':
    try:
        sys.exit(main())
    except (OSError, ValueError) as exc:
        print(json.dumps({'status':'ERROR','error':str(exc)},ensure_ascii=False))
        sys.exit(2)
