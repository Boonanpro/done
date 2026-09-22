"""Spoken search -> real worker file task -> spoken result, in a test room."""
import argparse,asyncio,json
from pathlib import Path
from types import SimpleNamespace
import httpx
from scripts import voice_conversation_trial as trial
from app.services.auth_service import create_access_token
from app.services import command_job_state as state

async def main(args):
 room='6016ba78-bb79-440b-a8d7-110bcfd1037d'
 trial.TEST_ROOM=room
 trial.PHRASES['real_search']='日本交通の米子大阪線って当日でもネット予約できる？公式の案内を調べて。'
 trial.PHRASES['real_search_yonago']='日本交通の、よなご、大阪線って当日でもネット予約できる？公式の案内を調べて。'
 trial.PHRASES['real_followup']='つまり当日乗りたいときはどうすればいいの？短く教えて。'
 trial.PHRASES['real_remember']='さっき調べたバスの会社はどこだった？'
 folder=(trial.OUT/args.label).resolve();folder.mkdir(parents=True,exist_ok=True)
 jobs=[]
 async with httpx.AsyncClient(base_url='http://127.0.0.1:8000',headers={'Authorization':'Bearer '+create_access_token(trial.USER,'')},timeout=35) as client:
  async def execute(name,a):
   if name=='enter_voice_standby':return {'ok':True}
   if name=='web_search':path='search';body=a
   elif name=='read_room_history':
    return {'messages':await trial.ChatService().get_messages(room,trial.USER,limit=12)}
   elif name=='delegate_to_dan':
    path='command-center';body={'room_id':room,'args':{'action':'work','task':a['task']+f'\n今回の試験用フォルダーは {folder.as_posix()}。この中のローカルメモだけ変更可。外部への送信・購入・予約・取消を行わない。'}}
   elif name=='control_dan_task':path='command-center';body={'room_id':room,'args':{**a,'action':'control_job'}}
   elif name=='command_center' and a.get('action') in ('jobs','status','requests'):path='command-center';body={'room_id':room,'args':a}
   else:return {'error':'この試験は公開情報検索と試験用メモの作成だけです。'}
   r=await client.post('/api/v1/voicelog/'+path,json=body);r.raise_for_status();data=r.json()
   if data.get('accepted'):jobs.append(data['receipt']['id'])
   return data
  options=SimpleNamespace(cases=args.cases,wait=90,label=args.label,interject=None,deployed=args.deployed,
   suppress_followup_delegation=False,speech_instructions=None,local_end_gate=False,history=[],intake_room=room,
   poll_jobs=True,tool_executor=execute)
  await trial.run(options)
 result={'jobs':[{k:j.get(k) for k in ('id','state','result','events')} for key in jobs if (j:=state.read(key))],
  'files':[{ 'path':str(p),'text':p.read_text(encoding='utf-8')} for p in folder.glob('*.txt')]}
 (trial.OUT/(args.label+'-work.json')).write_text(json.dumps(result,ensure_ascii=False,indent=2),encoding='utf-8')
 print(json.dumps(result,ensure_ascii=False))

if __name__=='__main__':
 p=argparse.ArgumentParser();p.add_argument('--label',required=True);p.add_argument('--cases',default='real_search,real_followup,work,real_remember');p.add_argument('--deployed')
 asyncio.run(main(p.parse_args()))
