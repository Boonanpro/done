"""Real Live/Jev/Astra/MCP/browser refund flow against a local transaction fixture."""
import asyncio,json,uuid,threading,argparse,time
from http.server import BaseHTTPRequestHandler,ThreadingHTTPServer
from types import SimpleNamespace
from scripts import voice_conversation_trial as trial
from scripts.voice_intake_audio_trial import PHRASES
from app.services import command_job_state as state,command_job_runner as runner
from app.services.command_center import execute as command
from app.services.project_service import ProjectService

async def main(args):
 config=trial.OUT/(args.label+'-room.json')
 if config.exists():project=json.loads(config.read_text(encoding='utf-8'))
 else:
  project=await ProjectService().create_project(trial.USER,'音声取消試験 '+args.label,description='ローカルの架空予約だけを操作する自動音声試験。実在予約には触れない。')
  config.write_text(json.dumps(project,ensure_ascii=False),encoding='utf-8')
 room=project['room_id'];trial.TEST_ROOM=room
 assert project
 transactions=[];jobs=[];tasks=[];started=time.monotonic()
 class Handler(BaseHTTPRequestHandler):
  def log_message(self,*a):pass
  def do_GET(self):
   body='''<!doctype html><meta charset="utf-8"><title>予約取消の試験</title><h1>予約一覧</h1><p>テスト予約 青葉号 手数料320円 返金4680円</p><button onclick="document.querySelector('main').hidden=false;this.hidden=true">払戻内容の確認に進む</button><main hidden><h2>払戻内容の確認</h2><p>青葉号 手数料320円 返金4680円。この操作で取消が確定します。</p><button onclick="fetch('/commit',{method:'POST'}).then(r=>r.json()).then(r=>{document.body.innerHTML='<h1>取消完了</h1><p>青葉号 手数料320円 返金4680円 受付番号 TEST-001</p>'})">払戻を確定</button></main>'''
   self.send_response(200);self.send_header('Content-Type','text/html; charset=utf-8');self.end_headers();self.wfile.write(body.encode())
  def do_POST(self):
   transactions.append({'at':time.monotonic()-started,'path':self.path})
   self.send_response(200);self.send_header('Content-Type','application/json');self.end_headers();self.wfile.write(b'{"ok":true}')
 server=ThreadingHTTPServer(('127.0.0.1',0),Handler);threading.Thread(target=server.serve_forever,daemon=True).start()
 url=f'http://127.0.0.1:{server.server_port}/'
 trial.PHRASES.update(PHRASES)
 trial.PHRASES['qa_cancel']='青葉号のテスト予約をキャンセルしてください。'
 async def execute(name,a):
  if name=='command_center':return {'jobs':[state.public(state.read(k)) for k in jobs]}
  if name=='delegate_to_dan':
   task=a['task']+'\n試験対象は '+url+' のローカル予約のみ。このページを開き、確認画面へ進み、対象・手数料・返金額を提示して承認を待つ。承認後だけ確定し、結果を読んで報告する。実在のサービスや他の予約にアクセスしない。ログインは不要。'
   if args.production:
    accepted=await command({'action':'work','task':task},room,trial.USER)
    jobs.append(accepted['receipt']['id']);return accepted
   key=str(uuid.uuid4());jobs.append(key)
   state.create(key,user_id=trial.USER,room_id=room,origin_room_id=room,origin_project_id=project['id'],queue_owner='isolated_audio_trial',task=task)
   tasks.append(asyncio.create_task(runner.run({'id':key,'user_id':trial.USER,'room_id':room,'spec':{'origin_room_id':room,'origin_project_id':project['id'],'task':task}})))
   return {'accepted':True,'receipt':{'id':key}}
  if name=='control_dan_task':return await command({**a,'action':'control_job'},room,trial.USER)
  if name=='enter_voice_standby':return {'ok':True}
  return {'error':'試験ではローカル予約作業とその状態確認だけを使う'}
 async def before_case(name):
  desired='awaiting_confirmation' if name in {'qa_status','qa_approve'} else 'completed' if name=='qa_result' else None
  if not desired:return
  deadline=time.monotonic()+120
  while time.monotonic()<deadline:
   if jobs:
    j=state.read(jobs[-1])
    if j['state']==desired:
     if name=='qa_status' and args.idle_seconds:
      for remaining in range(args.idle_seconds,0,-30):
       print(json.dumps({'idle_remaining':remaining,'job_state':state.read(jobs[-1])['state']}),flush=True)
       await asyncio.sleep(min(30,remaining))
     return
    if j['state'] in state.TERMINAL:raise RuntimeError('Unexpected job state: '+str(j))
   await asyncio.sleep(.25)
  raise TimeoutError('Job did not reach '+desired)
 options=SimpleNamespace(cases='qa_cancel,qa_status,qa_approve,qa_result',wait=18,label=args.label,
  interject=None,deployed='http://127.0.0.1:8000' if args.production else None,suppress_followup_delegation=False,speech_instructions=None,local_end_gate=False,
  history=[],intake_room=room,poll_jobs=True,tool_executor=execute,before_case=before_case,legacy_client=args.legacy_client)
 # The local trial owns these jobs. Do not place them in the production queue.
 original_mark=runner.mark_status
 runner.mark_status=lambda key,status:None if key in jobs else original_mark(key,status)
 try:
  await trial.run(options)
  assert len(transactions)==1,transactions
  assert all(state.read(k)['state']=='completed' for k in jobs)
 finally:
  report={'jobs':[state.read(k) for k in jobs],'transactions':transactions}
  (trial.OUT/(args.label+'-browser.json')).write_text(json.dumps(report,ensure_ascii=False,indent=2),encoding='utf-8')
  for task in tasks:
   if not task.done():task.cancel()
  await asyncio.gather(*tasks,return_exceptions=True)
  for key in jobs:
   if state.read(key)['state'] not in state.TERMINAL:state.control(key,trial.USER,room,'cancel')
  runner.mark_status=original_mark;server.shutdown()
 print(json.dumps({'transactions':len(transactions),'jobs':[state.read(k)['state'] for k in jobs]}))

if __name__=='__main__':
 p=argparse.ArgumentParser();p.add_argument('--label',required=True);p.add_argument('--idle-seconds',type=int,default=0);p.add_argument('--legacy-client',action='store_true');p.add_argument('--production',action='store_true');asyncio.run(main(p.parse_args()))
