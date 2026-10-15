"""Offline regression tests; no player launch and no agent configuration changes."""
import copy
import contextlib
import io
import json
from pathlib import Path
import subprocess
import sys
import tempfile
import unittest
from unittest.mock import patch

sys.dont_write_bytecode = True
import acceptance
import cli_acceptance as cli
import check_mpv
import check_mpris
from mpris import Mpris


class CliTests(unittest.TestCase):
    def test_mpris_profiles_and_no_false_av_sync(self):
        for app in ['vlc','totem']:
            result=cli.evaluate('3',{'checks':{'playback_position_advances':{'status':'PASS'}}},[{'audio_codec':'aac'}],app)
            self.assertEqual(result[0],'PASS')
            self.assertIn('未验证音画同步',result[1])
            self.assertEqual(cli.profile_for(app),app+'-cli-v1')
            self.assertEqual(cli.evaluate('5',{'checks':{'seek_interface':{'status':'FAIL'}}},[],app)[0],'FAIL')

    def test_mpris_owner_must_match_exact_pid(self):
        client=object.__new__(Mpris)
        client.owner=':1.99'
        client.pid=123
        client.bus_call=lambda *args:(456,)
        with self.assertRaises(check_mpv.Blocked):
            client.assert_owned()
        client.bus_call=lambda *args:(123,)
        client.assert_owned()

    def test_mpris_seek_requires_progress_after_landing(self):
        for progresses in [True,False]:
            clock=[0.0]
            class Fake:
                def call(self,*args):pass
                def get(self,key):
                    if key=='PlaybackStatus':return 'Playing'
                    return (4.0+(.001 if progresses and clock[0]>.8 else 0))*1e6 if clock[0]>0 else 13e6
            def sleep(seconds):clock[0]+=seconds
            with patch.object(check_mpris.time,'monotonic',side_effect=lambda:clock[0]),patch.object(check_mpris.time,'sleep',side_effect=sleep):
                result=check_mpris.seek_point(Fake(),4)
            self.assertTrue(result['jumped'])
            self.assertEqual(result['resumed'],progresses)
            self.assertLess(clock[0],5.3)

    def test_players_missing_input_produce_valid_blocked_reports(self):
        for app in ['vlc','totem']:
            with tempfile.TemporaryDirectory() as folder:
                run=Path(folder)/'result'
                result=subprocess.run([sys.executable,str(Path(__file__).with_name('run.py')),
                    '--app',app,'--run-dir',str(run)],capture_output=True,text=True,timeout=8)
                self.assertEqual(result.returncode,0,result.stderr+result.stdout)
                data,errors=acceptance.validate(run,app)
                self.assertEqual(errors,[])
                self.assertEqual(len(data['cases']),12)
                self.assertTrue(all(r['status']=='BLOCKED' for r in data['cases']))
                data['acceptance_profile']='mpv-cli-v1'
                (run/'results.json').write_text(json.dumps(data))
                self.assertIn('CLI profile/application mismatch',acceptance.validate(run,app)[1])

    def observe_fixture(self, frames, target=4.0, before=13.0):
        clock=[0.0]
        def get(key):
            index=min(int(round(clock[0]/.2)),len(frames)-1)
            seeking,position=frames[index]
            return seeking if key=='seeking' else position
        def sleep(seconds):
            clock[0]+=seconds
        with patch.object(check_mpv.time,'monotonic',side_effect=lambda:clock[0]), patch.object(check_mpv.time,'sleep',side_effect=sleep):
            return check_mpv.observe_seek(get,target,before)

    def test_seek_delayed_resume_passes_without_minimum_advance(self):
        result=self.observe_fixture([(True,13.0)]*5+[(False,4.0)]*6+[(False,4.001)])
        self.assertTrue(result['jumped'] and result['resumed'])
        self.assertGreater(result['elapsed_seconds'],1)

    def test_seek_stuck_at_correct_landing_fails_bounded(self):
        result=self.observe_fixture([(False,4.0)])
        self.assertTrue(result['jumped'])
        self.assertFalse(result['resumed'])
        self.assertLess(result['elapsed_seconds'],5.3)

    def test_seek_progress_before_completion_is_not_pass(self):
        result=self.observe_fixture([(True,4.0),(True,4.01),(True,4.02)])
        self.assertFalse(result['jumped'] or result['resumed'])

    def test_seek_wrong_landing_is_not_pass(self):
        result=self.observe_fixture([(False,12.0),(False,12.1),(False,12.2)])
        self.assertFalse(result['jumped'] or result['resumed'])

    def test_seek_forward_progress_passes(self):
        result=self.observe_fixture([(False,13.0),(False,13.001)],target=13.0,before=4.0)
        self.assertTrue(result['jumped'] and result['resumed'])

    def test_missing_input_and_original_table(self):
        with tempfile.TemporaryDirectory() as folder:
            run = Path(folder)/'result'
            result = subprocess.run([sys.executable,str(Path(__file__).with_name('run.py')),
                '--app','mpv','--cases','1,4,5','--input',str(Path(folder)/'missing.mp4'),
                '--run-dir',str(run)], capture_output=True,text=True,timeout=12)
            self.assertEqual(result.returncode,0,result.stderr+result.stdout)
            data,errors=acceptance.validate(run,'mpv')
            self.assertEqual(errors,[])
            self.assertEqual(len(data['cases']),12)
            self.assertNotIn('2',[r['id'] for r in data['cases']])
            self.assertEqual([r['id'] for r in data['cases'] if r['status']=='BLOCKED'],['1','4','5'])
            self.assertNotIn('PASS',[r['status'] for r in data['cases']])
            self.assertIn('| 用例编号 | 测试模块 | 测试项 | 优先级 | 前置条件 | 测试步骤 | 预期结果 | 实际结果 | 状态 |',
                          (run/'report.md').read_text())

    def test_controls_failures_not_hidden(self):
        automatic={'checks':{'pause_resume_interface':{'status':'PASS'},'seek_interface':{'status':'FAIL'}}}
        self.assertEqual(cli.evaluate('4',automatic,[])[0],'PASS')
        self.assertEqual(cli.evaluate('5',automatic,[])[0],'FAIL')
        self.assertEqual(cli.evaluate('6',automatic,[])[0],'BLOCKED')

    def test_no_audio_not_claimed_sync(self):
        automatic={'checks':{'playback_position_advances':{'status':'PASS'},'av_sync_clock':{'status':'NOT_APPLICABLE'}}}
        result=cli.evaluate('3',automatic,[{'audio_codec':None}])
        self.assertEqual(result[0],'PASS')
        self.assertIn('未验证有声播放',result[1])
        self.assertEqual(cli.evaluate('3',automatic,[{'audio_codec':'aac'}])[0],'BLOCKED')
        automatic['checks']['av_sync_clock']={'status':'FAIL','values':[.3]}
        self.assertEqual(cli.evaluate('3',automatic,[{'audio_codec':'aac'}])[0],'FAIL')

    def test_container_is_not_inferred_from_other_case(self):
        automatic={'checks':{'playback_position_advances':{'status':'PASS'},'container_matches':{'status':'PASS','case_id':'8'}}}
        self.assertEqual(cli.evaluate('8',automatic,[])[0],'PASS')
        self.assertEqual(cli.evaluate('9',automatic,[])[0],'BLOCKED')

    def test_validator_rejects_fabricated_pass(self):
        with tempfile.TemporaryDirectory() as folder:
            run=Path(folder)/'run'
            with contextlib.redirect_stdout(io.StringIO()):
                acceptance.init(run,'mpv')
            data=acceptance.read(run/'results.json')
            data['environment'].update(host='unit-test',app_version='fixture',display_session='fixture',gui_tool='none')
            data.update(requested_cases=['4'],finished_at=acceptance.now(),automatic_checks={'checks':{'pause_resume_interface':{'status':'FAIL'}}})
            for name,kind,content in [('automatic','diagnostic',data['automatic_checks']),('actions','cli_trace',[])]:
                (run/'evidence'/f'{name}.json').write_text(json.dumps(content))
                data['evidence'].append(dict(id=name,kind=kind,path=f'evidence/{name}.json',captured_at=acceptance.now(),producer='unit-test-fixture',description='Synthetic offline fixture, not board evidence'))
            cli.apply(data,{'4'})
            (run/'results.json').write_text(json.dumps(data))
            self.assertEqual(acceptance.validate(run,'mpv')[1],[])
            next(r for r in data['cases'] if r['id']=='4')['status']='PASS'
            (run/'results.json').write_text(json.dumps(data))
            self.assertTrue(acceptance.validate(run,'mpv')[1])

    def test_app_catalogs_unchanged(self):
        for app,count in [('mpv',12),('vlc',12),('totem',12),('snapshot',8)]:
            self.assertEqual(len(acceptance.read(acceptance.catalog_for(app))['cases']),count)

    def test_removed_case_rejected_before_run(self):
        with tempfile.TemporaryDirectory() as folder:
            run=Path(folder)/'run'
            result=subprocess.run([sys.executable,str(Path(__file__).with_name('run.py')),
                '--app','mpv','--cases','2','--run-dir',str(run)],capture_output=True,text=True,timeout=5)
            self.assertEqual(result.returncode,2)
            self.assertFalse(run.exists())
            self.assertIn('Unknown case IDs: 2',result.stderr)

    def test_removed_resize_control_rejected(self):
        result=subprocess.run([sys.executable,str(Path(__file__).with_name('check_mpv.py')),
            '--input','/unused.mp4','--controls','resize'],capture_output=True,text=True,timeout=5)
        self.assertEqual(result.returncode,2)
        self.assertIn('Unknown control diagnostic',result.stderr)

    def test_default_report_has_only_remaining_twelve_rows(self):
        with tempfile.TemporaryDirectory() as folder:
            run=Path(folder)/'run'
            result=subprocess.run([sys.executable,str(Path(__file__).with_name('run.py')),
                '--app','mpv','--run-dir',str(run)],capture_output=True,text=True,timeout=5)
            self.assertEqual(result.returncode,0,result.stderr+result.stdout)
            output=json.loads(result.stdout)
            self.assertEqual(output['requested_cases'],['1']+[str(i) for i in range(3,14)])
            self.assertEqual(len(output['cases']),12)
            self.assertNotIn('mpv窗口大小调节',(run/'report.md').read_text())
            self.assertNotIn('resize_interface',json.dumps(acceptance.read(run/'automatic.json')))


if __name__=='__main__':
    unittest.main()
