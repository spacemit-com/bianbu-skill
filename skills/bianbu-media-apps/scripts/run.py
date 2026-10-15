#!/usr/bin/env python3
"""Unified quick checks and baseline-compatible reports. No agent-specific API."""
import argparse
import contextlib
import datetime
import io
import json
import os
from pathlib import Path
import subprocess
import sys

sys.dont_write_bytecode = True
import acceptance
from check_mpv import write_json


def main():
    parser=argparse.ArgumentParser(description=__doc__)
    parser.add_argument('--app',choices=list(acceptance.CATALOGS),required=True)
    parser.add_argument('--mode',choices=['quick','acceptance'],default='quick',help='Same baseline; concise or full report')
    parser.add_argument('--cases',default='all',help='Original baseline IDs only, e.g. 1,4,5 or all')
    parser.add_argument('--input',type=Path)
    parser.add_argument('--run-dir',type=Path)
    parser.add_argument('--list',action='store_true',help='List case IDs without running applications')
    args=parser.parse_args()
    catalog=acceptance.read(acceptance.catalog_for(args.app))
    if args.list:
        print(json.dumps({'app':args.app,'cases':[{'id':c['id'],'title':c['title']} for c in catalog['cases']]},ensure_ascii=False))
        return 0
    valid={c['id'] for c in catalog['cases']}
    selected=valid if args.cases=='all' else set(filter(None,args.cases.split(',')))
    if selected-valid:
        parser.error('Unknown case IDs: '+','.join(sorted(selected-valid)))
    media=args.input.expanduser().resolve() if args.input else None
    if args.run_dir:
        run=args.run_dir.expanduser().resolve()
    else:
        root=Path(os.environ.get('XDG_STATE_HOME',str(Path.home()/'.local/state')))/'bianbu-media-apps'
        root.mkdir(parents=True,exist_ok=True)
        run=root/(args.app+'-'+datetime.datetime.now().strftime('%Y%m%d-%H%M%S')+'-'+os.urandom(4).hex())
    if run.exists():
        parser.error('Run directory already exists; previous evidence is preserved')
    if args.app=='mpv' and media is not None:
        format_cases=sorted(selected & {'8','9','10','11','12','13'},key=int)
        chosen=format_cases[0] if len(format_cases)==1 else {'mkv':'9','avi':'10','mov':'11','webm':'12','flv':'13'}.get(media.suffix.lower().lstrip('.'),'8')
        controls=[control for case,control in [('4','pause'),('5','seek'),('6','volume'),('7','fullscreen')] if case in selected]
        cmd=[sys.executable,str(Path(__file__).with_name('check_mpv.py')),'--input',str(media),'--case',chosen,'--run-dir',str(run)]
        if controls:
            cmd+=['--controls',','.join(controls)]
        # Child has its own collection deadline and exact-PID cleanup.
        result=subprocess.run(cmd,capture_output=True,text=True)
        if result.returncode or not (run/'results.json').is_file():
            print(json.dumps({'status':'ERROR','error':result.stdout[-1500:]+result.stderr[-1500:]},ensure_ascii=False))
            return 2
        data=acceptance.read(run/'results.json')
        automatic=data['automatic_checks']
    else:
        with contextlib.redirect_stdout(io.StringIO()):
            acceptance.init(run,args.app)
        data=acceptance.read(run/'results.json')
        if args.app=='mpv':
            data['environment'].update(host=os.uname().nodename,app_version='unavailable (no media selected)',
                                      display_session='not checked',gui_tool='not available for this request')
            automatic=dict(collection_status='BLOCKED',error='Input video required',checks={},warnings=[],elapsed_seconds=0)
        else:
            if args.app in {'vlc', 'totem'}:
                from check_mpris import collect
                environment,automatic,evs=collect(args.app,media,run,selected)
            else:
                from app_probe import collect
                environment,automatic,evs=collect(args.app,media,run)
            data['environment']=environment
            for filename,kind,description,producer in evs:
                path=run/'evidence'/filename
                if path.is_file() and path.stat().st_size:
                    data['evidence'].append(dict(id=path.stem,path='evidence/'+filename,kind=kind,
                        description=description,producer=producer,captured_at=acceptance.now()))
    # Keep the original cases intact. Automatic diagnostics never fabricate GUI PASS.
    for row in data['cases']:
        requested=row['id'] in selected
        actual='原表 GUI 操作及观察证据未齐。'
        checks=automatic['checks']
        control_key={'4':'pause_resume_interface','5':'seek_interface','6':'volume_interface','7':'fullscreen_interface'}.get(row['id']) if args.app=='mpv' else None
        if control_key in checks:
            actual='辅助接口取证 '+checks[control_key]['status']+'；原表点击/按键及效果尚未验收。'
        elif 'playback_position_advances' in checks and row['id'] in {'1','3','8','9','10','11','12','13'}:
            actual='已采集所提供素材的播放进度；本项指定操作、素材和画面仍需原表证据。'
        if automatic.get('error'):
            actual=automatic['error']
        row.update(status='BLOCKED' if requested else 'NOT_RUN',
            actual_result=actual if requested else '',
            reason_code=('COLLECTION_BLOCKED' if automatic.get('error') else 'GUI_ACCEPTANCE_PENDING') if requested else '')
        for step in row['steps']:
            step.update(status='BLOCKED' if requested else 'NOT_RUN',method='',action='',action_evidence=[],observations=[],
                        reason='需要本应用的真实 GUI 操作与观察证据，自动接口检查不能替代。' if requested else '')
    data.update(finished_at=acceptance.now(),automatic_checks=automatic,requested_cases=sorted(selected,key=int),test_mode=args.mode)
    if args.app in {'mpv', 'vlc', 'totem'}:
        import cli_acceptance
        if not (run/'evidence/automatic.json').exists():
            write_json(run/'evidence/automatic.json',automatic)
            write_json(run/'evidence/actions.json',[])
            for name,kind in [('automatic','diagnostic'),('actions','cli_trace')]:
                data['evidence'].append(dict(id=name,path='evidence/'+name+'.json',kind=kind,
                    description='CLI collection unavailable',producer='run.py',captured_at=acceptance.now()))
        cli_acceptance.apply(data,selected)
    write_json(run/'results.json',data)
    write_json(run/'automatic.json',automatic)
    _,errors=acceptance.validate(run,args.app)
    if errors:
        print(json.dumps({'status':'ERROR','errors':errors,'run_dir':str(run)},ensure_ascii=False))
        return 2
    with contextlib.redirect_stdout(io.StringIO()):
        acceptance.report(run,data)
    lines=[f'# {args.app} 简明测试','',f"取证：{automatic['collection_status']}；耗时 {automatic['elapsed_seconds']} 秒。",'',
           '| 用例编号 | 测试项 | 状态 | 实际结果 |','|---|---|---|---|']
    for row in data['cases']:
        lines.append('| '+' | '.join(acceptance.esc(row[k]) for k in ['id','title','status','actual_result'])+' |')
    if automatic.get('error'):
        lines+=['','阻塞原因：'+automatic['error']]
    scope=data.get('acceptance_scope','本应用尚未实现对应 CLI 操作，缺少证据的项目保持 BLOCKED。')
    lines+=['',scope]
    if selected:
        lines+=['','本次原表项目：'+','.join(sorted(selected,key=int))+'；未选择项 NOT_RUN，证据不足 BLOCKED。']
    if automatic.get('warnings'):
        lines+=['','运行警告：','']+['- '+w for w in automatic['warnings']]
    lines+=['', '[完整用例和证据报告](report.md)']
    (run/'summary.md').write_text('\n'.join(lines)+'\n',encoding='utf-8')
    with (run/'report.md').open('a',encoding='utf-8') as report:
        report.write('\n## 证据说明\n\n'+scope+'\n\n硬解状态不计为额外用例。详见 automatic.json 与 evidence/。\n')
        if automatic['warnings']:
            report.write('\n运行告警（影响尚未判定）：\n\n'+'\n'.join('- '+w for w in automatic['warnings'])+'\n')
    case_brief=[{k:row[k] for k in ['id','title','status','actual_result']} for row in data['cases'] if row['id'] in selected]
    summary_lines=[f"{args.app} 原表测试报告已生成，取证 {automatic['elapsed_seconds']} 秒。",
        '| 用例编号 | 测试项 | 状态 |','|---|---|---|']
    summary_lines.extend('| '+row['id']+' | '+row['title']+' | '+row['status']+' |' for row in case_brief)
    summary_lines+=[scope,'未选择项 NOT_RUN。BLOCKED 表示素材或接口证据不足。']
    if automatic.get('error'):
        summary_lines.append('阻塞原因：'+automatic['error'])
    if automatic['warnings']:
        summary_lines.append(f"日志含 {len(automatic['warnings'])} 条告警，影响尚未判定，详见报告。")
    summary_lines.append('报告：'+str(run/('summary.md' if args.mode=='quick' else 'report.md')))
    print(json.dumps(dict(status='REPORTED',app=args.app,mode=args.mode,requested_cases=sorted(selected,key=int),
        elapsed_seconds=automatic['elapsed_seconds'],collection_status=automatic['collection_status'],
        cases=case_brief,evidence_note='Only original baseline rows are test cases. Runtime diagnostics remain in evidence/ and automatic.json.',
        warnings=automatic['warnings'],error=automatic.get('error'),
        baseline_counts={status:sum(r['status']==status for r in data['cases']) for status in ['PASS','FAIL','BLOCKED','NOT_RUN']},
        report=str(run/('summary.md' if args.mode=='quick' else 'report.md')),summary=str(run/'summary.md'),
        summary_text='\n'.join(summary_lines),
        next_action='Return concise results and report path now. Do not rerun or write new test scripts.'),ensure_ascii=False))
    return 0


if __name__=='__main__':
    sys.exit(main())
