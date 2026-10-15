#!/usr/bin/env python3
"""Evidence/report gate. Never drives a player or infers a test PASS."""
import argparse,collections,datetime,hashlib,json,pathlib,sys
sys.dont_write_bytecode = True

CATALOG=pathlib.Path(__file__).resolve().parents[1]/'references'/'cases.json'
CATALOGS={'mpv':CATALOG,**{app:CATALOG.parent/('cases-'+app+'.json') for app in ['totem','vlc','snapshot']}}
STATUSES={'PASS','FAIL','BLOCKED','NOT_RUN'}
KINDS={'gui_trace','screen_recording','screenshot','time_series','process_state','window_geometry','av_sync_measurement','human_observation','binding_dump','property_samples','audio_measurement','media_probe','diagnostic','file_stat','captured_photo','captured_video','device_state'}
KINDS.add('cli_trace')
def read(path):return json.loads(path.read_text(encoding='utf-8'))
def sha(path):return hashlib.sha256(path.read_bytes()).hexdigest()
def now():return datetime.datetime.now(datetime.timezone.utc).isoformat()
def nonempty(v):return isinstance(v,str) and bool(v.strip())
def catalog_for(app):
    if app not in CATALOGS:raise ValueError('Unsupported application: '+str(app))
    return CATALOGS[app]
def init(run,app='mpv'):
    catalog=catalog_for(app)
    run.mkdir(parents=True,exist_ok=False);(run/'evidence').mkdir()
    cat=read(catalog)
    result=dict(schema_version=1,application=app,suite_id=cat['suite_id'],suite_version=cat['version'],catalog_sha256=sha(catalog),started_at=now(),finished_at=None,
      environment=dict(application=app,host=None,app_version=None,mpv_version=None,display_session=None,gui_tool=None,media=[]),evidence=[],cases=[])
    for c in cat['cases']:
        result['cases'].append(dict(id=c['id'],title=c['title'],priority=c['priority'],status='NOT_RUN',actual_result='',reason_code='',
          steps=[dict(id=s['id'],source_step=s['source_step'],status='NOT_RUN',method='',action='',action_evidence=[],observations=[],reason='') for s in c['steps']]))
    (run/'results.json').write_text(json.dumps(result,ensure_ascii=False,indent=2)+'\n',encoding='utf-8')
    print('Created NOT_RUN template:',run/'results.json')
def validate(run,app=None):
    data=read(run/'results.json');selected=data.get('application','mpv');catalog=catalog_for(selected);cat=read(catalog);errors=[]
    def need(ok,msg):
        if not ok:errors.append(msg)
    need(data.get('schema_version')==1,'schema_version must be 1')
    need(app is None or selected==app,'requested application differs from the recorded application')
    need(data.get('catalog_sha256')==sha(catalog),'catalog changed: create a new run for a changed baseline')
    need(data.get('suite_id')==cat['suite_id'] and data.get('suite_version')==cat['version'],'suite identity mismatch')
    for k in ['started_at','finished_at']:
        try:
            dt=datetime.datetime.fromisoformat(data.get(k) or '')
            need(dt.utcoffset() is not None,k+' must include timezone')
        except (ValueError,TypeError):need(False,k+' must be a valid ISO timestamp')
    env=data.get('environment',{})
    if not isinstance(env,dict):raise ValueError('environment must be an object')
    need(env.get('application',selected)==selected,'environment application mismatch')
    version=env.get('app_version') or (env.get('mpv_version') if selected=='mpv' else None)
    need(nonempty(version),'environment.app_version required for the target application')
    for k in ['host','display_session','gui_tool']:
        need(nonempty(env.get(k)),f'environment.{k} required (record unavailable and reason if blocked)')
    need(isinstance(env.get('media'),list),'environment.media must be an array')
    rows=data.get('cases',[])
    if not isinstance(rows,list):raise ValueError('cases must be an array')
    need([r.get('id') for r in rows]==[c['id'] for c in cat['cases']],f'all {len(cat["cases"])} case IDs required once, in source order')
    evidence={};evrows=data.get('evidence',[])
    if not isinstance(evrows,list):raise ValueError('evidence must be an array')
    for ev in evrows:
        eid=ev.get('id');need(nonempty(eid) and eid not in evidence,'empty/duplicate evidence id: '+str(eid));evidence[eid]=ev
        need(ev.get('kind') in KINDS,'unknown evidence kind: '+str(eid))
        for k in ['path','captured_at','producer','description']:need(nonempty(ev.get(k)),f'evidence {eid}: {k} required')
        try:
            dt=datetime.datetime.fromisoformat(ev.get('captured_at') or '');need(dt.utcoffset() is not None,f'evidence {eid}: timezone required')
        except (ValueError,TypeError):need(False,f'evidence {eid}: invalid capture time')
        try:
            rel=pathlib.Path(ev.get('path') or '')
            need(not rel.is_absolute(),f'evidence {eid}: relative path required')
            path=(run/rel).resolve();need(path.is_relative_to(run.resolve()),f'evidence {eid}: path escapes run')
            if not path.is_relative_to(run.resolve()):continue
            need(path.is_file() and path.stat().st_size>0,f'evidence {eid}: missing/empty file')
            if path.is_file() and ev.get('sha256'):need(ev['sha256']==sha(path),f'evidence {eid}: hash mismatch')
        except (ValueError,OSError,TypeError):need(False,f'evidence {eid}: invalid file path')
    def refs(ids,label):
        if not isinstance(ids,list):need(False,label+': evidence IDs must be an array');return []
        need(bool(ids),label+': evidence required')
        need(len(ids)==len(set(ids)),label+': duplicate evidence references')
        for eid in ids:need(eid in evidence,label+': missing evidence '+str(eid))
        return [evidence[e] for e in ids if e in evidence]
    for r,c in zip(rows,cat['cases']):
        label='case '+c['id'];status=r.get('status');need(status in STATUSES,label+': unknown status')
        for key in ['title','priority']:need(r.get(key)==c[key],label+': baseline '+key+' changed')
        if status!='NOT_RUN':need(nonempty(r.get('actual_result')),label+': actual_result required')
        if status in {'FAIL','BLOCKED'}:need(nonempty(r.get('reason_code')),label+': reason_code required')
        steps=r.get('steps',[])
        if not isinstance(steps,list):need(False,label+': steps must be array');continue
        need([s.get('id') for s in steps]==[s['id'] for s in c['steps']],label+': missing/changed source steps')
        if data.get('acceptance_profile') in {'mpv-cli-v1', 'vlc-cli-v1', 'totem-cli-v1'}:
            import cli_acceptance
            need(selected in {'mpv','vlc','totem'} and data['acceptance_profile'] == cli_acceptance.profile_for(selected), 'CLI profile/application mismatch')
            need(data.get('acceptance_scope') == cli_acceptance.scope_for(selected), 'CLI scope must be explicit')
            for s,cs in zip(steps,c['steps']):
                need(s.get('source_step') == cs['source_step'], label+': source step changed')
            captured = read(run/'evidence/automatic.json')
            need(captured == data.get('automatic_checks'), 'CLI checks differ from captured evidence')
            errors.extend(cli_acceptance.validate_row(r,data,captured,evidence))
            continue
        if status=='PASS':need(all(s.get('status')=='PASS' for s in steps),label+': PASS requires every step PASS')
        if status=='FAIL':need(any(s.get('status')=='FAIL' for s in steps),label+': FAIL requires a failed step')
        if status=='BLOCKED':need(any(s.get('status')=='BLOCKED' for s in steps),label+': BLOCKED requires a blocked step')
        if status=='NOT_RUN':need(any(s.get('status')=='NOT_RUN' for s in steps),label+': NOT_RUN requires an unfinished step')
        if any(s.get('status')=='FAIL' for s in steps):need(status=='FAIL',label+': do not conceal failed steps')
        for s,cs in zip(steps,c['steps']):
            tag=label+' step '+cs['id'];ss=s.get('status');need(ss in STATUSES,tag+': invalid status')
            need(s.get('source_step')==cs['source_step'],tag+': source step changed')
            if ss in {'FAIL','BLOCKED'}:need(nonempty(s.get('reason')),tag+': reason required')
            if ss not in {'PASS','FAIL'}:continue
            need(s.get('method') in cs['allowed_methods'],tag+': method is not the required GUI action')
            need(nonempty(s.get('action')),tag+': actual GUI action required')
            acts=refs(s.get('action_evidence',[]),tag+' action')
            need(any(e.get('kind') in {'gui_trace','screen_recording'} for e in acts),tag+': GUI trace/recording required')
            obs=s.get('observations',[])
            if not isinstance(obs,list):need(False,tag+': observations must be array');continue
            bykey={o.get('key'):o for o in obs}
            need(len(bykey)==len(obs),tag+': duplicate observation keys')
            for o in obs:
                need(nonempty(o.get('actual')),tag+': actual observation text required')
                refs(o.get('evidence',[]),tag+' '+str(o.get('key')))
            if ss=='PASS':
                for req in cs['required_observations']:
                    o=bykey.get(req['key']);need(o is not None,tag+': missing '+req['key'])
                    if o is None:continue
                    evs=refs(o.get('evidence',[]),tag+' '+req['key'])
                    for group in req['evidence_kinds']:
                        need(any(e.get('kind') in group for e in evs),tag+': '+req['key']+' needs '+str(group))
                    if req['key'] in {'video_advances','camera_frames'} and not any(e.get('kind')=='screen_recording' for e in evs):
                        need(len({e.get('path') for e in evs if e.get('kind')=='screenshot'})>=2,tag+': video advance requires two distinct screenshots or a recording')
    return data,errors
def esc(value):return str(value).replace('|','\\|').replace('\n','<br>')
def report(run,data):
    counts=collections.Counter(c['status'] for c in data['cases']);complete=counts['NOT_RUN']==0
    app=data.get('application','mpv');cat=read(catalog_for(app))
    scope=cat.get('scope_description','用户截图可见的 13 项')
    lines=[f'# {app} 桌面验收报告','',f"运行：{data['started_at']} → {data['finished_at']}",'',
      f'范围：{scope}。'+('所有项均已有结论。' if complete else '未完成，仍有 NOT_RUN 项。'),
      '校验器只校验结果结构与证据引用，不证明媒体播放或 GUI 动作真实正确。','',
      ' / '.join(f'{s}: {counts[s]}' for s in ['PASS','FAIL','BLOCKED','NOT_RUN']),'',
      '## 环境','', '```json',json.dumps(data['environment'],ensure_ascii=False,indent=2),'```','',
      '## 用例结果','', '| 用例编号 | 测试模块 | 测试项 | 优先级 | 前置条件 | 测试步骤 | 预期结果 | 实际结果 | 状态 |','|---|---|---|---|---|---|---|---|---|']
    for c,base in zip(data['cases'],cat['cases']):
        values=[c['id'],base.get('module',''),c['title'],c['priority'],base.get('source_precondition',''),
                '\n'.join(s['id']+'、'+s['source_step'] for s in base['steps']),
                '\n'.join(base.get('expected',[])),c.get('actual_result',''),c['status']]
        lines.append('| '+' | '.join(esc(value) for value in values)+' |')
    if data.get('acceptance_profile'):
        lines+=['','## CLI 验证口径','',data['acceptance_scope'],
                '原表步骤保留作来源，下面 NOT_RUN 表示未执行 GUI 手势；主表结论采用 CLI 功能判据。','']
        for c in data['cases']:
            if c.get('cli',{}).get('detail'):
                lines += ['### 用例 '+c['id'], '', c['cli']['detail'], '']
    lines+=['','## 执行记录','']
    for c,base in zip(data['cases'],cat['cases']):
        lines+=[f"### {c['id']} · {c['title']}",'']
        if base.get('user_authorized_adaptation'):lines+=[base['user_authorized_adaptation'],'']
        for s in c['steps']:
            lines+=[f"- 源步骤 {s['id']}：{s['source_step']}",f"  - {s['status']}；方式：{s['method']}；动作：{s['action']}；原因：{s['reason']}",f"  - 动作证据：{', '.join(s['action_evidence'])}"]
            for o in s['observations']:lines.append(f"  - {o['key']}：{o['actual']}；证据：{', '.join(o['evidence'])}")
        lines.append('')
    lines+=['## 证据清单','','| ID | 类型 | 文件 | SHA-256 |','|---|---|---|---|']
    hashes={}
    for e in data['evidence']:
        h=sha(run/e['path']);hashes[e['path']]=h
        lines.append(f"| {esc(e['id'])} | {e['kind']} | [{esc(e['path'])}](<{e['path']}>) | {h} |")
    (run/'report.md').write_text('\n'.join(lines)+'\n',encoding='utf-8')
    (run/'evidence-sha256.json').write_text(json.dumps(hashes,ensure_ascii=False,indent=2)+'\n',encoding='utf-8')
    print('Report:',run/'report.md')
def main():
    parser=argparse.ArgumentParser(description=__doc__);parser.add_argument('command',choices=['init','validate','report']);parser.add_argument('--run-dir',type=pathlib.Path,required=True);parser.add_argument('--app',choices=list(CATALOGS),help='init defaults to mpv; validate/report infer the recorded application');a=parser.parse_args()
    try:
        if a.command=='init':init(a.run_dir,a.app or 'mpv');return 0
        data,errors=validate(a.run_dir,a.app)
        if errors:print(json.dumps({'valid':False,'errors':errors},ensure_ascii=False,indent=2));return 2
        print(json.dumps({'valid':True,'test_status_counts':dict(collections.Counter(c['status'] for c in data['cases']))},ensure_ascii=False))
        if a.command=='report':report(a.run_dir,data)
        return 0
    except (OSError,ValueError,TypeError,KeyError,AttributeError) as e:print('Invalid input: '+str(e),file=sys.stderr);return 2
if __name__=='__main__':sys.exit(main())
