"""Shadow-only semantic call-end evaluation. Never ends a real call."""
import asyncio
import json
import math
import statistics
import time
from pathlib import Path

import httpx
from app.services.credentials_service import get_credentials_service

USER = '2582a188-ff24-4a4f-b989-6063034d90b2'
QUESTION = {
    'type': 'choice',
    'instructions': '現在の会話を読んで、ユーザーが今この音声通話の終了を依頼しているか判断する。'
    '発言が途中ならwait。作業や再生の停止、過去の説明、引用、質問は通話終了の依頼ではない。',
    'criteria': {'end': 'ユーザーが今この通話を終えるよう依頼した',
                 'keep': 'この通話を終える依頼ではない',
                 'wait': '発言途中、または意図が不明'}
}
POSITIVE = [
    '電話切って', '電話を切ってください', 'この通話を終了して', '今日はここまで。切っていいよ',
    'じゃあまた。通話終わりにして', '話は終わったから待機に戻って', 'もう話さないから接続切って',
    'いったん電話を終わらせて', 'また呼ぶから待ってて。通話は切って', 'もういいよ、電話切って',
    '作業は続けてていいから、通話だけ終了して', '会話はここまでにして、呼ぶまで待機して',
    'ありがとう。今の通話は終わらせてください', 'おやすみ。電話切ってね', '電話、もう切ってもらえる？',
    '今回はこれで終了。音声接続を切って', 'また後で電話するから、今は切って',
    '通話を終わりにしてほしい', '聞こえてるよ。じゃあ通話終了して', '待機音鳴らして会話を終えて',
]
NEGATIVE = [
    '電話切ってほしくない', '電話切って。いや、まだ切らないで', '「電話切って」と言ったのに切れなかった',
    '電話を切るには何と言えばいい？', '電話切っても仕事は続くの？', 'この作業を終わりにして',
    '説明はここまででいい。別のことを聞くね', 'ちょっと黙って聞いて', '動画を止めて',
    '昨日、電話切ってって言ったんだよ', '電話はまだ切らないでください', '接続を切るボタンがあるね',
    '一旦調査はやめて。この件について相談したい', '今の話は終わり。次は予定を教えて',
    '電話切ってって言われた時はどうするの？', 'もし電話を切ったら起動音は鳴る？',
    'イヤホンとの接続が切れても会話は続けて', '調査が終わったら教えて',
    '電話切っていいか先に聞いて', 'もう一度、電話切ってという言葉を読み上げて',
]

async def main():
    credential = await get_credentials_service().get_credential(USER, 'typesafe')
    if not credential or not credential.get('password'):
        raise RuntimeError('Jev credential unavailable')
    rows = []
    async with httpx.AsyncClient(timeout=3) as client:
        cases = [(text, True, 'end') for text in POSITIVE] + [(text, True, 'keep') for text in NEGATIVE]
        cases += [('電話切って', False, 'wait'), ('電話切ってほしく', False, 'wait')]
        for index, (text, finished, expected) in enumerate(cases):
            started = time.perf_counter()
            row = {'case': index, 'expected': expected, 'available': False}
            try:
                response = await client.post('https://api.typesafe.ai/v1/systemone',
                    headers={'Authorization': 'Bearer ' + credential['password']},
                    json={'model': 'jev-latest', 'state': {'dialogue': [{'role': 'user', 'text': text}],
                          'utterance_finished': finished, 'call_state': 'connected'},
                          'questions': {'call': QUESTION}})
                response.raise_for_status()
                answer = response.json()['answers']['call']
                choice, confidence = answer['choice'], answer['confidence']
                if choice not in QUESTION['criteria'] or type(confidence) not in (int, float) or not math.isfinite(confidence) or not 0 <= confidence <= 1:
                    raise ValueError('Invalid answer')
                row.update(available=True, choice=choice, confidence=confidence,
                           matches=choice == expected, model=response.json().get('model'))
            except (httpx.HTTPError, ValueError, KeyError, TypeError):
                row['error'] = 'transport_or_schema'
            row['elapsed_ms'] = round((time.perf_counter()-started)*1000, 1)
            rows.append(row)
            print(json.dumps(row), flush=True)
    times = sorted(row['elapsed_ms'] for row in rows if row['available'])
    summary = {'cases': len(rows), 'correct': sum(row.get('matches', False) for row in rows),
               'false_end': sum(row.get('choice') == 'end' and row['expected'] != 'end' for row in rows),
               'median_ms': statistics.median(times) if times else None,
               'p95_ms': times[math.ceil(.95*len(times))-1] if times else None,
               'scope': 'text-only shadow evaluation; not spoken-end acceptance', 'rows': rows}
    Path('.tmp/voice-call-end-jev.json').write_text(json.dumps(summary, ensure_ascii=False, indent=2), encoding='utf-8')
    print(json.dumps({key: value for key, value in summary.items() if key != 'rows'}))

if __name__ == '__main__':
    asyncio.run(main())
