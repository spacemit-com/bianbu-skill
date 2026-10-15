"""Short default-application launch and evidence collection for VLC/Totem/Snapshot."""
import json
import os
from pathlib import Path
import re
import shutil
import socket
import subprocess
import time

import acceptance
from check_mpv import Blocked, command, display_environment, write_json


def collect(app, media, run):
    checks, warnings, trace = {}, [], []
    environment=dict(application=app,host=socket.gethostname(),app_version='unavailable',
                     display_session='unavailable',gui_tool='grim capture only; GUI input/review not automated',media=[])
    process=None
    started=time.monotonic()
    error=None
    evidence=[]
    def event(action,**extra):
        trace.append(dict(at=acceptance.now(),action=action,**extra))
    try:
        if not shutil.which(app):
            raise Blocked(app+' is not installed')
        package='gnome-snapshot' if app=='snapshot' else app
        environment['app_version']=command(['dpkg-query','-W','-f=${Version}',package]).strip() or 'unavailable'
        # Single-instance apps can hand off to an existing user window. Never take it over.
        existing=[]
        for p in Path('/proc').iterdir():
            if p.name.isdigit():
                try:
                    if (p/'comm').read_text().strip()==app:
                        existing.append(int(p.name))
                except OSError:
                    pass
        if existing:
            raise Blocked('Existing '+app+' processes: '+str(existing)+'; leave user sessions untouched')
        if app!='snapshot':
            if media is None or not media.is_file():
                raise Blocked('A local input video is required')
            probe=json.loads(command(['ffprobe','-v','error','-show_format','-show_streams','-of','json',str(media)]))
            write_json(run/'evidence/media.json',probe)
            environment['media']=[dict(path=str(media),probe=probe)]
        env=display_environment()
        environment['display_session']='; '.join(k+'='+env.get(k,'') for k in ['XDG_RUNTIME_DIR','WAYLAND_DISPLAY','DISPLAY'])
        if app=='vlc':
            argv=['vlc','-vv',str(media)]
        elif app=='snapshot':
            argv=['snapshot','--debug']
            env.update(GST_DEBUG='2,spacemitdec:5',GST_DEBUG_NO_COLOR='1')
        else:
            argv=['totem',str(media)]
            env.update(GST_DEBUG='2,spacemitdec:5',GST_DEBUG_NO_COLOR='1')
        event('launch',argv=argv,observation_only_environment={k:env[k] for k in ['GST_DEBUG','GST_DEBUG_NO_COLOR'] if k in env})
        with (run/'evidence/application.log').open('w') as log:
            process=subprocess.Popen(argv,env=env,stdin=subprocess.DEVNULL,stdout=log,stderr=subprocess.STDOUT)
            event('spawned',pid=process.pid)
            for index in range(3):
                time.sleep(2)
                event('process_sample',pid=process.pid,alive=process.poll() is None)
                if process.poll() is not None:
                    raise Blocked('Application launcher exited; cannot assume another window belongs to this run')
                if env.get('WAYLAND_DISPLAY') and shutil.which('grim'):
                    name=f'screen-{index+1}.png'
                    try:
                        command(['grim',str(run/'evidence'/name)],timeout=3,env=env)
                        evidence.append((name,'screenshot','Real desktop; visual review still required','grim'))
                    except (Blocked,subprocess.TimeoutExpired) as exc:
                        warnings.append(str(exc))
            checks['process_alive']=dict(status='PASS',note='Process survived bounded observation; not proof of correct image or audio')
    except (Blocked,OSError,ValueError,subprocess.TimeoutExpired) as exc:
        error=str(exc)
    finally:
        if process is not None:
            if process.poll() is None:
                event('terminate_owned_pid',pid=process.pid,note='Test cleanup, not GUI close acceptance')
                process.terminate()
                try:
                    process.wait(timeout=3)
                except subprocess.TimeoutExpired:
                    process.kill()
                    process.wait(timeout=2)
                    warnings.append('Application required kill after termination timeout')
            checks['owned_process_cleanup']=dict(status='PASS' if process.poll() is not None else 'FAIL',exit_code=process.returncode)
    logfile=run/'evidence/application.log'
    text=logfile.read_text(errors='replace') if logfile.exists() else ''
    stcodecs=sorted(set(re.findall(r'codec \((\w+_stcodec)\) started',text)))
    frames=re.findall(r'finish frame return ok \((\d+),',text)
    checks['hardware_decoder']=dict(status='OBSERVED' if stcodecs else 'PASS' if frames else 'BLOCKED',
        codecs=stcodecs,completed_frame_counters=frames[-3:],
        note='VLC codec startup is observed; GStreamer completed-frame counters indicate active hardware decoding')
    checks['visual_gui_acceptance']=dict(status='BLOCKED',note='Needs real GUI actions and visual review; screenshots alone are not an automatic verdict')
    for line in text.splitlines():
        if ' error:' in line or '[MPP-ERROR]' in line or ' ERROR ' in line:
            warning=line.strip()[-400:]
            if warning not in warnings:
                warnings.append(warning)
            if len(warnings)>=10:
                break
    write_json(run/'evidence/actions.json',trace)
    evidence.extend([('actions.json','diagnostic','Exact actions and owned process tracking','app_probe.py'),
                     ('application.log','diagnostic','Application log; observations, not a complete GUI verdict','app_probe.py'),
                     ('media.json','media_probe','Input stream metadata','ffprobe')])
    return environment,dict(collection_status='BLOCKED' if error else 'COMPLETED',error=error,checks=checks,
                            warnings=warnings,elapsed_seconds=round(time.monotonic()-started,2)),evidence
