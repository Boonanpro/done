"""Free wall-clock regression: extraction 31 s, first enqueue 31 s, all five survive.
Real after_call and summary writer; model, queue, chat DB are mocks; private temp state.
"""
import asyncio,json,sys,time,tempfile
from pathlib import Path
from datetime import datetime,timezone
ROOT=Path(__file__).resolve().parents[1];sys.path.insert(0,str(ROOT))

async def main():
 import pytest
 from app.services import voice_sideband as S,voice_stage as V,command_center,command_job_state,api_job_providers,inbox
 from app.services.chat_service import ChatService
 began=time.monotonic();saved=[];started=[]
 with tempfile.TemporaryDirectory() as directory, pytest.MonkeyPatch.context() as m:
  m.setattr(S,'FOLLOWUP_ROOT',Path(directory)/'handoff');m.setattr(V,'ROOT',Path(directory)/'stage')
  m.setattr(command_job_state,'list_owned',lambda *a:[]);m.setattr(inbox,'_env',lambda:None)
  class Model:
   def start(self,*a):assert '最初の依頼' in a[2][0] and '最後の取消' in a[2][0] and len(a[2][0])>65000
   async def step(self):
    await asyncio.sleep(31)
    return {'text':json.dumps({'left':[{'task':f'資料{i}を作る'} for i in range(5)],'decisions':[{'text':'32GBにする。','evidence':'32GBでお願い'}]})}
  m.setattr(api_job_providers,'make',lambda *a:Model())
  async def execute(spec,*a):
   started.append({'at_s':time.monotonic()-began,'action':spec['action']})
   if len(started)==1:await asyncio.sleep(31)
   return {'accepted':True,'job_id':str(len(started))}
  m.setattr(command_center,'execute',execute);m.setattr(ChatService,'__init__',lambda self:None)
  async def write(self,*a,**kw):saved.append({'at_s':time.monotonic()-began,'text':a[2]});return {'id':'fixture'}
  m.setattr(ChatService,'send_message',write)
  d=S.Dialogue();d.add('user','最初の依頼。32GBでお願い')
  for i in range(110):d.add('assistant','長い相談の内容。'*80);d.add('user','続けて。')
  d.add('user','最後の取消。')
  stage=V.Stage('fixture-room','fixture-session',d,lambda *a,**kw:None)
  stage._apply('メモリ','root = Stat("メモリ", 32, "GB")');stage.close()
  await S.finish_call('test-user','fixture-room',d,datetime.now(timezone.utc),True,stage,lambda *a,**kw:None)
  assert len(saved)==1 and len(started)==5
  assert 31 <= saved[0]['at_s'] < started[-1]['at_s']-30
  snapshot=json.loads(next((Path(directory)/'handoff').rglob('*.json')).read_text())
  assert len(snapshot['receipts'])==5
  result={'elapsed_s':time.monotonic()-began,'model_delay_s':31,'first_enqueue_delay_s':31,'summary':saved,'handoffs':started,'transcript_chars':d.history_chars,'received':len(snapshot['receipts']),'type':'wall clock measured; model, queue and chat storage mocked'}
  out=ROOT/'.tmp/voice-early/revision/handoff-timeout.json';out.parent.mkdir(parents=True,exist_ok=True)
  out.write_text(json.dumps(result,ensure_ascii=False,indent=2));print(json.dumps(result,ensure_ascii=False))
if __name__=='__main__':asyncio.run(main())
