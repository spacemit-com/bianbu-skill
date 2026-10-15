"""VLC/Totem functional evidence using the real application, MPRIS and GActions."""
import json
import os
from pathlib import Path
import re
import shutil
import signal
import socket
import subprocess
import time

import acceptance
from check_mpv import Blocked, command, container_matches, display_environment, write_json
from mpris import Mpris, ROOT


class Cancelled(Exception):
    pass


def wait_value(read, predicate, timeout=5):
    started=time.monotonic()
    samples=[]
    while time.monotonic()-started < timeout:
        value=read()
        samples.append(dict(elapsed_seconds=round(time.monotonic()-started,3),value=value))
        if predicate(value):
            return True,samples
        time.sleep(.2)
    return False,samples


def seek_point(client,target):
    before=client.get('Position')/1e6
    # Totem advertises NoTrack for local files; relative Seek is valid for both apps.
    client.call('Seek','(x)',(int((target-before)*1e6),))
    def state():
        return dict(position=client.get('Position')/1e6,status=client.get('PlaybackStatus'))
    landing=[None]
    def resumed(value):
        position=value['position']
        if landing[0] is None:
            direction=position>before if target>before else position<before
            if direction and abs(position-target)<2:
                landing[0]=position
            return False
        return value['status']=='Playing' and position>landing[0]
    ok,samples=wait_value(state,resumed)
    return dict(before=before,target=target,actual=landing[0],jumped=landing[0] is not None,
                resumed=ok,samples=samples,timeout_seconds=5)


def collect(app,media,run,selected):
    checks,warnings,trace,samples={},[],[],[]
    environment=dict(application=app,host=socket.gethostname(),app_version='unavailable',
        display_session='unavailable',gui_tool='CLI/MPRIS; Totem fullscreen uses GApplication; no GUI input',media=[])
    process=client=log=None
    error=None
    started=time.monotonic()
    def event(action,**extra):
        trace.append(dict(at=acceptance.now(),action=action,**extra))
    def cancel(signum,frame):
        raise Cancelled('Collection timeout or cancellation')
    old={s:signal.signal(s,cancel) for s in (signal.SIGALRM,signal.SIGINT,signal.SIGTERM)}
    signal.alarm(65)
    def control(key,operation):
        try:
            checks[key]=operation()
        except (Blocked,OSError,ValueError,TypeError,KeyError,subprocess.TimeoutExpired) as exc:
            checks[key]=dict(status='BLOCKED',note=str(exc))
            event('control_unavailable',check=key,error=str(exc))
    try:
        if not shutil.which(app):
            raise Blocked(app+' is not installed')
        environment['app_version']=command(['dpkg-query','-W','-f=${Version}',app]).strip()
        if media is None or not media.is_file():
            raise Blocked('A local input video is required')
        for proc in Path('/proc').iterdir():
            if not proc.name.isdigit():continue
            try:
                if (proc/'comm').read_text().strip()==app:
                    raise Blocked('Existing '+app+' process '+proc.name+'; leave user sessions untouched')
            except OSError:continue
        probe=json.loads(command(['ffprobe','-v','error','-show_format','-show_streams','-of','json',str(media)]))
        write_json(run/'evidence/media.json',probe)
        video=next((s for s in probe.get('streams',[]) if s.get('codec_type')=='video'),None)
        if video is None:raise Blocked('No video stream in the selected file')
        audio=next((s for s in probe.get('streams',[]) if s.get('codec_type')=='audio'),{})
        fmt=probe.get('format',{})
        environment['media']=[dict(path=str(media),container=fmt.get('format_name'),duration=fmt.get('duration'),
            video_codec=video.get('codec_name'),audio_codec=audio.get('codec_name'),width=video.get('width'),height=video.get('height'))]
        formats=sorted(selected&{'8','9','10','11','12','13'},key=int)
        case=formats[0] if len(formats)==1 else {'mkv':'9','avi':'10','mov':'11','webm':'12','flv':'13'}.get(media.suffix.lower().lstrip('.'),'8')
        matches=container_matches(case,probe)
        if case in {'9','12'}:
            with media.open('rb') as source:header=source.read(4096)
            doc=b'matroska' if case=='9' else b'webm'
            matches=b'\x42\x82'+bytes([0x80+len(doc)])+doc in header
        checks['container_matches']=dict(status='PASS' if matches else 'BLOCKED',case_id=case,format=fmt.get('format_name'))
        if not matches:raise Blocked('Input container does not match requested format')
        env=display_environment()
        environment['display_session']='; '.join(k+'='+env.get(k,'') for k in ['WAYLAND_DISPLAY','DISPLAY','XDG_RUNTIME_DIR'])
        argv=[app]+(['-vv'] if app=='vlc' else [])+[str(media)]
        if app=='totem':env.update(GST_DEBUG='2,spacemitdec:5',GST_DEBUG_NO_COLOR='1')
        log=(run/'evidence/application.log').open('w')
        event('launch',argv=argv)
        process=subprocess.Popen(argv,env=env,stdin=subprocess.DEVNULL,stdout=log,stderr=subprocess.STDOUT)
        event('spawned',pid=process.pid)
        client=Mpris(env['DBUS_SESSION_BUS_ADDRESS'],process.pid,event)
        until=time.monotonic()+12
        while not client.discover():
            if process.poll() is not None or time.monotonic()>=until:
                raise Blocked('No MPRIS interface owned by this test process; no takeover or plugin/config changes')
            time.sleep(.2)
        ready,_=wait_value(lambda:client.get('PlaybackStatus'),lambda state:state=='Playing',timeout=8)
        if not ready:raise Blocked('Application did not enter Playing state')
        for _ in range(3):
            time.sleep(.6)
            sample=dict(at=acceptance.now(),position=client.get('Position')/1e6,status=client.get('PlaybackStatus'))
            samples.append(sample)
        checks['playback_position_advances']=dict(status='PASS' if samples[-1]['position']>samples[0]['position'] and
            all(s['status']=='Playing' for s in samples) else 'FAIL',samples=samples)
        if '4' in selected:
            def pause_resume():
                if not client.get('CanPause'):raise Blocked('CanPause=false')
                original=client.get('PlaybackStatus')
                try:
                    client.call('Pause')
                    paused,states=wait_value(lambda:client.get('PlaybackStatus'),lambda s:s=='Paused')
                    before=client.get('Position')/1e6
                    time.sleep(1)
                    after=client.get('Position')/1e6
                    client.call('Play')
                    resumed,points=wait_value(lambda:dict(position=client.get('Position')/1e6,status=client.get('PlaybackStatus')),
                        lambda s:s['status']=='Playing' and s['position']>after)
                    return dict(status='PASS' if paused and abs(after-before)<.15 and resumed else 'FAIL',
                        paused_positions=[before,after],pause_states=states,resume_samples=points)
                finally:
                    client.call('Play' if original=='Playing' else 'Pause')
            control('pause_resume_interface',pause_resume)
        if '5' in selected:
            def seek():
                if not client.get('CanSeek'):raise Blocked('CanSeek=false')
                length=client.get('Metadata').get('mpris:length',0)/1e6
                if length<5:raise Blocked('Media too short or duration unavailable')
                points=[seek_point(client,length*f) for f in [.65,.2]]
                return dict(status='PASS' if all(p['jumped'] and p['resumed'] for p in points) else 'FAIL',points=points)
            control('seek_interface',seek)
        if '6' in selected:
            def volume():
                original=client.get('Volume')
                target=max(0,original-.1) if original>0 else .1
                try:
                    client.set('Volume','d',target)
                    ok,values=wait_value(lambda:client.get('Volume'),lambda v:abs(v-target)<.015)
                finally:
                    client.set('Volume','d',original)
                restored,back=wait_value(lambda:client.get('Volume'),lambda v:abs(v-original)<.015)
                return dict(status='PASS' if ok and restored else 'FAIL',before=original,target=target,values=values,restore_values=back)
            control('volume_interface',volume)
        if '7' in selected:
            def fullscreen():
                original=client.fullscreen(app)
                try:
                    client.set_fullscreen(app,not original)
                    ok,values=wait_value(lambda:client.fullscreen(app),lambda v:v is not original)
                finally:
                    client.set_fullscreen(app,original)
                restored,back=wait_value(lambda:client.fullscreen(app),lambda v:v is original)
                return dict(status='PASS' if ok and restored else 'FAIL',before=original,values=values,restore_values=back)
            control('fullscreen_interface',fullscreen)
    except (Cancelled,Blocked,OSError,ValueError,TypeError,KeyError,subprocess.TimeoutExpired) as exc:
        error=str(exc)
    finally:
        signal.alarm(0)
        normal_quit=False
        if process is not None:
            if process.poll() is None and client and client.owner:
                try:
                    event('quit_requested',pid=process.pid)
                    normal_quit=True
                    client.call('Quit',interface=ROOT)
                except Blocked as exc:
                    # Totem may disconnect before replying. Exit status is authoritative.
                    event('quit_reply',note=str(exc))
            try:process.wait(timeout=3)
            except subprocess.TimeoutExpired:
                normal_quit=False
                process.terminate()
                event('terminate_owned_pid',pid=process.pid)
                try:process.wait(timeout=2)
                except subprocess.TimeoutExpired:
                    process.kill();process.wait(timeout=2)
                    event('kill_owned_pid',pid=process.pid)
            checks['process_exit']=dict(status='PASS' if normal_quit and process.returncode==0 else 'FAIL',
                exit_code=process.returncode,normal_quit=normal_quit)
        if client:
            try:client.close()
            except Exception as exc:warnings.append('Bus cleanup: '+str(exc))
        if log:log.close()
        for sig,handler in old.items():signal.signal(sig,handler)
    logfile=run/'evidence/application.log'
    text=logfile.read_text(errors='replace') if logfile.exists() else ''
    stcodecs=sorted(set(re.findall(r'codec \((\w+_stcodec)\) started',text)))
    frames=re.findall(r'finish frame return ok \((\d+),',text)
    checks['hardware_decoder']=dict(status='OBSERVED' if stcodecs else 'PASS' if frames else 'BLOCKED',
        codecs=stcodecs,completed_frame_counters=frames[-3:],
        note='VLC codec startup observed; Totem completed-frame logs indicate active hardware decoding; no assumption from app name')
    for line in text.splitlines():
        if ' error:' in line or '[MPP-ERROR]' in line or ' ERROR ' in line:
            warning=line.strip()[-400:]
            if warning not in warnings:warnings.append(warning)
            if len(warnings)>=10:break
    automatic=dict(collection_status='BLOCKED' if error else 'COMPLETED',error=error,checks=checks,warnings=warnings,
                   elapsed_seconds=round(time.monotonic()-started,2))
    write_json(run/'evidence/automatic.json',automatic)
    write_json(run/'evidence/actions.json',trace)
    write_json(run/'evidence/samples.json',samples)
    evidence=[('automatic.json','diagnostic','Collected CLI check results','check_mpris.py'),
        ('actions.json','cli_trace','Commands and verified unique bus owner','check_mpris.py'),
        ('samples.json','time_series','Application playback status and position','MPRIS'),
        ('application.log','diagnostic','Real application log; warnings retained',app),
        ('media.json','media_probe','Actual input format and streams','ffprobe')]
    return environment,automatic,evidence
