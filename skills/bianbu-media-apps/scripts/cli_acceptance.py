"""CLI acceptance for existing MPV rows; never claims GUI gestures occurred."""
import json

PROFILE = 'mpv-cli-v1'
SCOPE = ('CLI 功能验证：不验收鼠标点击、拖拽、画面质量或扬声器听感；'
         '无音轨时音画同步不适用。有音轨时仅检查播放器 A/V 时钟差。')


def profile_for(app):
    return app + '-cli-v1'


def scope_for(app):
    return SCOPE if app == 'mpv' else ('CLI 功能验证：通过应用原生接口操作并回读状态；不验收鼠标点击、拖拽、'
        '画面质量或扬声器听感；播放进度通过不代表音画同步已验证。')


def method_for(app):
    return {'mpv': 'mpv-ipc', 'vlc': 'mpris', 'totem': 'mpris-gactions'}[app]


def evaluate(case_id, automatic, media, app='mpv'):
    checks = automatic.get('checks', {})
    keys = {
        '1': ['playback_position_advances', 'process_exit'],
        '3': ['playback_position_advances', 'av_sync_clock'] if app == 'mpv' else ['playback_position_advances'],
        '4': ['pause_resume_interface'], '5': ['seek_interface'],
        '6': ['volume_interface'], '7': ['fullscreen_interface'],
    }.get(case_id, ['container_matches', 'playback_position_advances'])
    if int(case_id) >= 8 and checks.get('container_matches', {}).get('case_id') != case_id:
        return 'BLOCKED', '未提供本项对应容器的测试素材。', keys
    results = [checks.get(key, {'status': 'BLOCKED', 'note': '未取得采样'}) for key in keys]
    states = [r['status'] for r in results]
    status = 'FAIL' if 'FAIL' in states else 'BLOCKED' if any(s not in {'PASS', 'NOT_APPLICABLE'} for s in states) else 'PASS'
    if app == 'mpv' and case_id == '3' and states[-1] == 'NOT_APPLICABLE':
        # N/A is only legitimate for a probed video without any audio track.
        if not media or media[0].get('audio_codec'):
            status = 'BLOCKED'
    detail = '; '.join(key + '=' + json.dumps(value, ensure_ascii=False, separators=(',', ':'))
                       for key, value in zip(keys, results))
    labels = {
        '1': '命令行打开并播放，正常退出',
        '3': '本地视频播放进度与 A/V 时钟' if app == 'mpv' else '本地视频播放进度（未验证音画同步）', '4': '暂停时进度停止，恢复后推进',
        '5': '向前/向后跳转至目标位置并恢复播放', '6': '音量属性调整与恢复（非听感验证）',
        '7': '全屏进入/退出状态回读（非截图验收）',
    }
    text = labels.get(case_id, '实际容器匹配且播放进度推进') + '：' + status
    if app == 'mpv' and case_id == '3' and states[-1] == 'NOT_APPLICABLE':
        text += '；素材无音轨，音画同步不适用，未验证有声播放'
    if status == 'BLOCKED':
        text += '；' + (automatic.get('error') or next((r.get('note', '缺少运行证据') for r in results if r['status'] == 'BLOCKED'), '缺少运行证据'))
    return status, text + '\n' + detail, keys


def apply(data, selected):
    app = data.get('application', 'mpv')
    data['acceptance_profile'] = profile_for(app)
    data['acceptance_scope'] = scope_for(app)
    media = data['environment'].get('media', [])
    for row in data['cases']:
        requested = row['id'] in selected
        status, result, keys = evaluate(row['id'], data['automatic_checks'], media, app) if requested else ('NOT_RUN', '', [])
        row.update(status=status, actual_result=result.split('\n', 1)[0],
                   reason_code='CLI_' + status if status in {'BLOCKED', 'FAIL'} else '',
                   cli=dict(method=method_for(app), checks=keys, detail=result,
                            evidence=['automatic', 'actions'] if requested else []))
        # The source GUI steps are retained as provenance, not falsely marked executed.
        for step in row['steps']:
            step.update(status='NOT_RUN', method='', action='', action_evidence=[], observations=[],
                        reason='使用 CLI 等效功能验证；未执行原表 GUI 手势。' if requested else '')


def validate_row(row, data, automatic, evidence):
    errors = []
    requested = row['id'] in data.get('requested_cases', [])
    app = data.get('application', 'mpv')
    status, detail, keys = evaluate(row['id'], automatic, data['environment'].get('media', []), app) if requested else ('NOT_RUN', '', [])
    if row['status'] != status:
        errors.append('CLI result disagrees with captured checks: ' + row['id'])
    cli = row.get('cli', {})
    if cli.get('method') != method_for(app) or cli.get('checks') != keys or cli.get('detail') != detail:
        errors.append('CLI criteria/detail mismatch: ' + row['id'])
    if row.get('actual_result') != detail.split('\n', 1)[0]:
        errors.append('CLI summary mismatch: ' + row['id'])
    if requested:
        if cli.get('evidence') != ['automatic', 'actions']:
            errors.append('CLI evidence missing: ' + row['id'])
        if evidence.get('automatic', {}).get('kind') != 'diagnostic' or evidence.get('actions', {}).get('kind') != 'cli_trace':
            errors.append('CLI evidence types invalid: ' + row['id'])
    if any(s['status'] != 'NOT_RUN' for s in row['steps']):
        errors.append('CLI mode must not claim original GUI steps executed: ' + row['id'])
    return errors
