"""Real Live + Dan backend through the telephone bridge, with a paced simulated Twilio peer.
No telephone number is dialed. The partner reacts to what Dan actually says.
"""
import argparse
import asyncio
import audioop
import base64
import json
import sys
import time
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))
from dotenv import load_dotenv
load_dotenv(Path.home() / 'done' / '.env')
from openai import AsyncOpenAI
from app.config import settings
from app.services.telephone import Bridge
from app.services.owner import resolve_owner_user_id
from app.services.project_service import ProjectService


class Phone:
    def __init__(self):
        self.incoming = asyncio.Queue()
        self.audio = bytearray()
        self.out_audio = bytearray()
        self.ended = False
    async def receive_json(self): return await self.incoming.get()
    async def send_json(self, event):
        if event['event'] == 'media':
            self.out_audio.extend(base64.b64decode(event['media']['payload']))
        elif event['event'] == 'mark':
            await self.incoming.put({'event':'mark', 'mark': event['mark']})
    async def clock(self):
        while not self.ended:
            data = bytes(self.audio[:160]); del self.audio[:160]
            data += b'\xff'*(160-len(data))
            await self.incoming.put({'event':'media','media':{'track':'inbound','payload':base64.b64encode(data).decode()}})
            await asyncio.sleep(.02)
    async def say(self, client, text):
        response = await client.audio.speech.create(model='gpt-4o-mini-tts', voice='ash', input=text,
            response_format='pcm', instructions='日本語で自然に会話してください。')
        pcm, _ = audioop.ratecv(response.content, 2, 1, 24000, 8000, None)
        self.audio.extend(audioop.lin2ulaw(pcm, 2))


async def run(case, out):
    owner = resolve_owner_user_id()
    projects = ProjectService()
    project = await projects.create_project(owner, '電話の確認 ' + case, description='自動確認専用、終了後削除')
    phone = Phone()
    provider_ended = False
    async def finish(sid):
        nonlocal provider_ended
        provider_ended = True
        phone.ended = True
    grant = {'peer':'owner', 'user_id':owner, 'room_id':project['room_id'], 'call_sid':'simulated', 'max_seconds':100}
    bridge = Bridge(phone, grant, finish)
    task = asyncio.create_task(bridge.run({'start':{'callSid':'simulated', 'accountSid':settings.TWILIO_ACCOUNT_SID,
        'streamSid':'simulated-stream','mediaFormat':{'encoding':'audio/x-mulaw','sampleRate':8000,'channels':1}}}))
    clock = asyncio.create_task(phone.clock())
    started = time.monotonic()
    first = ('これは会話の練習で、記録には保存しないで。この電話の中だけで予定を確認したい。明日は赤いシャツで行くつもり。何色だったか覚えてて。' if case=='color'
             else 'これは会話の練習で、記録には保存しないで。この電話の中だけで買い物の相談。りんごを三個買うつもりなんだけど、数を覚えておいて。')
    correction = ('やっぱり青いシャツに変える。明日何色を着ることにした？' if case=='color'
                  else 'ごめん、りんごは五個に変更する。今の予定は何個？')
    expected = ['青'] if case=='color' else ['五', '5']
    stage = 0
    said_at = 0
    hangup_at = None
    partner = []
    error = None
    closed_at = None
    try:
        async with AsyncOpenAI(api_key=settings.OPENAI_API_KEY) as client:
            while time.monotonic()-started < 95 and not task.done():
                elapsed = time.monotonic()-started
                assistant = [t for t in bridge.transcript if t['role']=='assistant']
                text = ''.join(t['text'] for t in assistant)
                if stage==0 and bridge.session_id:
                    await phone.say(client, first); partner.append(first); stage=1; said_at=time.monotonic()
                elif stage==1 and assistant and not phone.audio and time.monotonic()-said_at>8:
                    # Respond to Dan's acknowledgement, not a replay of a failed call.
                    await phone.say(client, correction); partner.append(correction); stage=2; said_at=time.monotonic()
                elif stage==2 and any(x in text for x in expected) and not phone.audio and time.monotonic()-said_at>7:
                    goodbye='うん、確認できた。ありがとう。電話を切って。'
                    await phone.say(client, goodbye); partner.append(goodbye); stage=3
                    hangup_at=time.monotonic()
                await asyncio.sleep(.2)
        if not task.done():
            await phone.incoming.put({'event':'stop'})
        await task
        closed_at = time.monotonic()
    except Exception as exc:
        error=type(exc).__name__ + ': ' + str(exc)[:250]
    finally:
        clock.cancel()
        if not task.done(): task.cancel()
        await asyncio.gather(clock, task, return_exceptions=True)
        await projects.delete_project(project['id'], owner)
    result = {'case':case, 'transcript':bridge.transcript, 'partner':partner, 'input_bytes':bridge.received,
        'output_bytes':bridge.sent,'finalized':bridge.finalized,'provider_ended':provider_ended,
        'hangup_seconds': round(closed_at-hangup_at,2) if hangup_at and closed_at else None, 'error':error}
    said = ''.join(t['text'] for t in bridge.transcript if t['role']=='assistant')
    result['passed'] = bool(stage==3 and any(x in said for x in expected) and bridge.finalized and provider_ended and not error and result['hangup_seconds'] is not None and result['hangup_seconds'] < 20)
    out.mkdir(parents=True,exist_ok=True)
    (out/'result.json').write_text(json.dumps(result,ensure_ascii=False,indent=2))
    (out/'dan.ulaw').write_bytes(phone.out_audio)
    print(json.dumps(result,ensure_ascii=False),flush=True)
    return result['passed']


if __name__=='__main__':
    p=argparse.ArgumentParser(); p.add_argument('case',choices=['color','count']); p.add_argument('out',type=Path)
    a=p.parse_args(); sys.exit(0 if asyncio.run(run(a.case,a.out)) else 1)
