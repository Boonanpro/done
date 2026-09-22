"""Offline/shadow Jev evaluation. Never dispatches tools or changes live voice.

python -m scripts.voice_jev_eval --prepare
python -m scripts.voice_jev_eval --user-id UUID --credential typesafe
Results contain case IDs and decisions, never API keys or conversation bodies.
"""
import argparse
import asyncio
import json
import math
import re
import time
from pathlib import Path

import httpx

ROOT = Path(__file__).resolve().parents[1]
CASES = ROOT / 'tests/fixtures/voice_jev_cases.json'
QUESTIONS = {
    'speech': {
        'type': 'choice',
        'instructions': '会話と現在の状態を踏まえ、最新発言は音声出力・通話をどう扱う要求か。作業停止とは独立して判断する。引用や否定も考慮する。',
        'criteria': {
            'continue': '音声や通話を停止する要求はない',
            'pause': '説明・発話だけ止めて聞く。通話は維持する',
            'end': '通話を終了して呼びかけ待ちに戻す',
            'unclear': '文脈を含めても区別できない',
        },
    },
    'task': {
        'type': 'choice',
        'instructions': '最新発言が現在の仕事に求める変更は何か。状態を質問すること、相づち、話し方への要求だけでは仕事を変更しない。',
        'criteria': {
            'keep': '現在の仕事はそのまま。質問・雑談・相づち等',
            'start': '新しい仕事を依頼、または停止済みの仕事を再開',
            'update': '進行中の仕事の条件や対象を変更',
            'pause': '進行中の仕事を一時停止、または次の操作を保留',
            'cancel': '進行中の仕事を取りやめる',
            'unclear': '何を止める・変更するのか判断材料が不足',
        },
    },
    'notice': {
        'type': 'choice',
        'instructions': 'pending_noticeを今ユーザーへ伝える価値があるか。既に話した内容、ユーザーの現在の質問、発話を控えてほしい意図を考慮。通知がなければnone。',
        'criteria': {
            'none': '通知がない',
            'silent': '同じ意味の繰り返し、細かな進捗、または今は発話を控えるべき',
            'speak': '未通知の完了・失敗・本人の判断が必要、または現在の質問への答え',
            'unclear': '通知の意味や既に伝えたかが不明',
        },
    },
}


def payload(case):
    # Labels are deliberately excluded from model input.
    text=json.dumps(case['state'],ensure_ascii=False)
    if '\ufffd' in text or re.search(r'\?{3,}',text):
        raise ValueError('Evaluation input contains encoding loss')
    return {'model': 'jev-latest', 'state': case['state'], 'questions': QUESTIONS}


def validate(data):
    answers = data['answers']
    result = {}
    for name, question in QUESTIONS.items():
        answer = answers[name]
        options = question['criteria']
        probs = answer['probabilities']
        confidence = answer['confidence']
        if answer['type'] != 'choice' or answer['choice'] not in options or set(probs) != set(options):
            raise ValueError('invalid choice schema')
        if any(type(v) not in (float, int) or not math.isfinite(v) or not 0 <= v <= 1 for v in probs.values()):
            raise ValueError('invalid probability')
        if abs(sum(probs.values()) - 1) > .01:
            raise ValueError('probabilities do not sum to one')
        if type(confidence) not in (float, int) or not math.isfinite(confidence) or not 0 <= confidence <= 1:
            raise ValueError('invalid confidence')
        result[name] = {'choice': answer['choice'], 'confidence': confidence, 'probabilities': probs}
    return result


async def evaluate(client, key, case, timeout=3):
    started = time.monotonic()
    row = {'case_id': case['id'], 'status': 'unavailable'}
    try:
        response = await client.post('https://api.typesafe.ai/v1/systemone',
            headers={'Authorization': 'Bearer ' + key}, json=payload(case), timeout=timeout)
        if response.status_code != 200:
            row['error'] = 'http_' + str(response.status_code)
            return row
        data = response.json()
        answers = validate(data)
        row.update(status='ok', answers=answers, model=data.get('model'), usage=data.get('usage'))
        row['matches'] = {k: answers[k]['choice'] in expected for k, expected in case['expected'].items()}
    except (httpx.HTTPError, ValueError, KeyError, TypeError):
        # No response/error text: upstream errors can contain request contents.
        row['error'] = 'transport_or_schema'
    finally:
        row['elapsed_ms'] = round((time.monotonic() - started) * 1000, 1)
    return row


def summary(rows):
    ok = [r for r in rows if r['status'] == 'ok']
    times = sorted(r['elapsed_ms'] for r in ok)
    return {'cases': len(rows), 'successful': len(ok), 'unavailable': len(rows)-len(ok),
        'all_labels_correct': sum(all(r['matches'].values()) for r in ok),
        'p50_success_ms': times[math.ceil(.5*len(times))-1] if times else None,
        'p95_success_ms': times[math.ceil(.95*len(times))-1] if times else None,
        'timeouts_included_as_unavailable': True, 'changes_live_behavior': False}


async def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument('--prepare', action='store_true')
    parser.add_argument('--user-id')
    parser.add_argument('--credential', default='typesafe')
    parser.add_argument('--output', type=Path, default=ROOT/'.tmp/voice-jev-results.json')
    args = parser.parse_args()
    cases = json.loads(CASES.read_text(encoding='utf-8'))
    assert len({c['id'] for c in cases}) == len(cases)
    for case in cases:
        payload(case)
        for name, expected in case['expected'].items():
            assert expected and set(expected) <= set(QUESTIONS[name]['criteria'])
    if args.prepare:
        print(json.dumps({'prepared_cases':len(cases),'dimensions':list(QUESTIONS),'api_called':False}))
        return
    if not args.user_id:
        parser.error('--user-id is required to use the credential service')
    from app.services.credentials_service import CredentialsService
    credential = await CredentialsService().get_credential(args.user_id, args.credential)
    if not credential or credential.get('credential_type') != 'api_key' or not credential.get('password'):
        print(json.dumps({'status':'blocked','reason':'typesafe_api_key_missing','api_called':False}))
        return
    rows = []
    async with httpx.AsyncClient() as client:
        for case in cases:
            row = await evaluate(client, credential['password'], case)
            rows.append(row)
            print(json.dumps({k:row[k] for k in ('case_id','status','elapsed_ms')}),flush=True)
            if row.get('error') in ('http_401','http_403','http_429','http_529'):break
    result = {'summary':summary(rows),'planned_cases':len(cases),'rows':rows}
    args.output.parent.mkdir(parents=True,exist_ok=True)
    args.output.write_text(json.dumps(result,ensure_ascii=False,indent=2),encoding='utf-8')
    print(json.dumps(result['summary']))


if __name__ == '__main__':asyncio.run(main())
