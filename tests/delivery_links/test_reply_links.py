"""Owner must receive an openable delivery, never a workstation path as a link."""
import importlib.util
from pathlib import Path

ROOT = Path(__file__).resolve().parents[2]
spec = importlib.util.spec_from_file_location('reply_check', ROOT/'scripts/hook_reply_check.py')
mod = importlib.util.module_from_spec(spec)
spec.loader.exec_module(mod)


def test_reported_link_is_rejected():
    reply = '[検索成績の集計](/Users/mikihonda/dan-workspace/denki_seo/traffic-weeks-20261109.json)'
    assert any(h['id']=='local-delivery-link' for h in mod.check(reply))


def test_other_local_deliveries_are_rejected():
    for target in ['D:/done/report.pdf', 'file:///Users/name/report.pdf', 'http://localhost:8000/report', 'https://dan.paina.info/Users/name/report.pdf', '/home/user/report.pdf', '/tmp/report.pdf']:
        assert any(h['id']=='local-delivery-link' for h in mod.check(f'[報告書]({target})')), target


def test_reference_and_button_are_rejected():
    for reply in ['[集計][report]\n\n[report]: /Users/name/report.json', '```openui-lang\nroot = Button("集計", "/Users/name/report.json")\n```']:
        assert any(h['id']=='local-delivery-link' for h in mod.check(reply))


def test_public_attachment_and_code_are_preserved():
    for reply in ['[集計](https://denkiouen.com/reports/traffic)', '[資料](/api/v1/files/report.pdf)', '[画面](/preview/denki-knowledge)', '場所は `/Users/name/report.json` です。', '```md\n[例](/Users/name/report.json)\n```']:
        assert not any(h['id']=='local-delivery-link' for h in mod.check(reply)), reply


def test_real_stop_hook_requires_delivery_even_on_second_attempt(tmp_path):
    import json
    import subprocess
    import sys
    for active in (False, True):
        payload = {'hook_event_name':'Stop', 'session_id':'delivery-test', 'stop_hook_active':active, 'last_assistant_message':'[資料](/Users/someone/new-project/manual.pdf)'}
        run = subprocess.run([sys.executable, str(ROOT/'scripts/hook_reply_check.py')], input=json.dumps(payload), text=True, capture_output=True)
        assert run.returncode == 0
        result = json.loads(run.stdout)
        assert result['decision'] == 'block'
        assert 'attach_image' in result['reason']
    payload['last_assistant_message'] = '[資料](/api/v1/files/attached-manual.pdf)'
    run = subprocess.run([sys.executable, str(ROOT/'scripts/hook_reply_check.py')], input=json.dumps(payload), text=True, capture_output=True)
    assert run.returncode == 0 and not run.stdout
