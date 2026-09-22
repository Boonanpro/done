"""Run the user's qualitative revision through the actual editor production runtime."""
import copy,json,shutil,time,uuid
from pathlib import Path
from app.services import timeline_draft as td,editor_references
from app.services.timeline_agent import run_timeline_agent
from app.api.production_asset_routes import _append_job_event

source='2c1c50e1-61c4-44eb-99e5-8f78905ab200'
room='collage-acceptance-'+uuid.uuid4().hex[:8]
folder=td._room_dir(room);folder.mkdir(parents=True)
content=copy.deepcopy(td._read_contents_raw(source)[0]);cid=content['id']
content['editor_work']=[]
content['creative_brief']['constraints']='既存・無料素材、コード、契約済みクラウドGPUの音声、必要ならGPT Image 2。今回は新規の有料動画生成はしない。日本がブラジル→フランス→オランダを倒して優勝する架空の物語。'
content['creative_brief']['taste']='ユーザー提供の参考動画全体のコラージュ表現。単調な図解ではなく、写真素材と構図・動きに変化がある映像。'
(folder/'contents.json').write_text(json.dumps([content],ensure_ascii=False),encoding='utf-8')
shutil.copy2(td._room_dir(source)/'assets.json',folder/'assets.json')
src=editor_references._folder(source);dest=editor_references._folder(room)
dest.mkdir(parents=True,exist_ok=True)
for path in src.glob('*'):
    if path.is_file():shutil.copy2(path,dest/path.name)
job=uuid.uuid4().hex
state={'room_id':room,'content_id':cid,'job_id':job}
Path('uploads/collage-acceptance-latest.json').write_text(json.dumps(state),encoding='utf-8')
def emit(event):
    _append_job_event(room,job,event)
    if event.get('type')!='keepalive':print(event.get('type'),str(event.get('text',''))[:240],flush=True)
started=time.monotonic()
print('TEST',json.dumps(state),flush=True)
result=run_timeline_agent(room_id=room,user_id='2582a188-ff24-4a4f-b989-6063034d90b2',content_id=cid,job_id=job,
    instruction='下書きが単調です。同じ競技場写真と人物の図解を繰り返すだけでは、渡した参考動画のようになっていません。参考の良さをこのサッカーの題材に活かして直してください。紙の色やスコアの置き場所を変えるだけではなく、見せる素材と演出を考えてほしいです。まず違いを判断できる数秒分を、参考に近い仕上がりで見せてください。他の部分と音声は維持してください。顔を使わないという条件は私からは指定していません。',on_event=emit)
result['elapsed_seconds']=round(time.monotonic()-started,2)
(folder/'acceptance-result.json').write_text(json.dumps(result,ensure_ascii=False),encoding='utf-8')
print('RESULT',json.dumps(result,ensure_ascii=False),flush=True)
