"""Real Live/Jev audio conversation; financial executor is an isolated fixture.

No user room, physical audio device, or real reservation is changed.
Uses the production intake, shared client and real job confirmation state machine.
"""
import asyncio
import argparse
import json
import uuid
from pathlib import Path
from types import SimpleNamespace
from unittest.mock import patch, AsyncMock
from scripts import voice_conversation_trial as trial
from app.services import command_job_state as state
from scripts.report_voice_latency import report

PHRASES = {
 'qa_intro': '明日のテスト予約、青葉号の話をするね。まだ何もしなくていいよ。',
 'qa_cancel': 'じゃあ、その予約をキャンセルしてください。',
 'qa_status': '今は何を待ってるの？',
 'qa_approve': 'うん、その内容で払い戻してください。',
 'qa_result': '結局、キャンセルは完了したの？',
 'qa_no': 'いや、まだ確定しないで。手数料を教えて。',
 'qa_retract': 'うん、でも、まだ払い戻さないで。ちょっと考えたい。',
 'qa_change': 'その条件ならやめる。キャンセルの手続きを止めて。',
 'qa_smalltalk': 'ありがとう。ところで今日ちょっと早起きできたんだ。',
}

async def main(args):
 trial.PHRASES.update(PHRASES)
 root=trial.OUT/args.label/'jobs';root.mkdir(parents=True,exist_ok=True)
 room='audio-fixture-'+uuid.uuid4().hex
 tasks=[];actions=[]
 async def prepare(key):
  await asyncio.sleep(.8)
  j=state.read(key)
  if j['state'] in state.TERMINAL:return
  state.publish(key,'confirmation','明日の青葉号の予約を取り消します。手数料320円、返金額4,680円です。この内容で払い戻してよいですか？',state='awaiting_confirmation',
   confirmation={'id':str(uuid.uuid4()),'summary':'明日の青葉号の取消。手数料320円、返金4,680円。払い戻してよいですか？','revision':j['revision'],'created_at':state.now()},applied_revision=j['revision'])
 async def execute(name,a):
  if name=='enter_voice_standby':return {'ok':True}
  if name=='command_center' and a.get('action')=='jobs':return {'jobs':[state.public(j) for j in state.list_owned(trial.USER,room)]}
  actions.append({'name':name,'args':a,'at':state.now()})
  if name=='delegate_to_dan':
   key=str(uuid.uuid4());state.create(key,user_id=trial.USER,origin_room_id=room,room_id=room,task=a['task'])
   state.publish(key,'progress','予約内容と払戻条件を確認しています。',state='running')
   tasks.append(asyncio.create_task(prepare(key)))
   return {'accepted':True,'receipt':{'id':key}}
  if name=='control_dan_task':
   from app.services.command_center import execute as command
   with patch.object(trial.ChatService,'get_room',new=AsyncMock(return_value={'id':room})):
    await command({**a,'action':'control_job'},room,trial.USER)
   j=state.read(a['job_id'])
   if a['operation']=='confirm':
    state.publish(j['id'],'result','青葉号の取消が完了しました。手数料320円、返金額4,680円です。',state='completed',result='取消完了。返金4,680円。')
   elif a['operation']=='update':tasks.append(asyncio.create_task(prepare(j['id'])))
   return {'job':state.public(state.read(j['id']))}
  return {'error':'この試験の対象外の道具です。実際の予約サイトには接続していません。'}
 options=SimpleNamespace(cases=args.cases,wait=args.wait,label=args.label,interject=None,deployed=None,
  suppress_followup_delegation=False,speech_instructions=None,local_end_gate=False,history=[],intake_room=room,
  poll_jobs=True,tool_executor=execute)
 with patch.object(state,'ROOT',root):
  try:await trial.run(options)
  finally:
   for t in tasks:t.cancel()
   await asyncio.gather(*tasks,return_exceptions=True)
   for action in actions:
    if 'voice_approval' in action['args']:action['args']['voice_approval']='[redacted]'
   (trial.OUT/(args.label+'-actions.json')).write_text(json.dumps(actions,ensure_ascii=False,indent=2),encoding='utf-8')
 result=report(trial.OUT/(args.label+'.json'))
 (trial.OUT/(args.label+'-latency.json')).write_text(json.dumps(result,ensure_ascii=False,indent=2),encoding='utf-8')
 print(json.dumps(result,ensure_ascii=False))

if __name__=='__main__':
 p=argparse.ArgumentParser();p.add_argument('--label',required=True);p.add_argument('--wait',type=int,default=14)
 p.add_argument('--cases',default='qa_intro,qa_cancel,qa_status,qa_approve,qa_result,qa_smalltalk')
 asyncio.run(main(p.parse_args()))
