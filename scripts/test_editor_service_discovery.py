"""Exercise normal Dan service discovery from an editor-owned production draft."""
import copy,json,uuid
from app.services import timeline_draft as td,timeline_live as tl
from app.services.timeline_agent import run_timeline_agent
from app.api.production_asset_routes import _append_job_event
r='editor-service-discovery-'+uuid.uuid4().hex[:8];cid=uuid.uuid4().hex;job=uuid.uuid4().hex
source,_=tl.live_sequence('assistant-complete-test-8e96bdba','a65ccfdd-6304-4dee-9fa4-c06d79ab921c')
content=copy.deepcopy(source);content['id']=cid
folder=td._room_dir(r);folder.mkdir(parents=True,exist_ok=True)
(folder/'contents.json').write_text(json.dumps([content],ensure_ascii=False),encoding='utf-8')
(folder/'assets.json').write_text(json.dumps(list(tl._assets('assistant-complete-test-8e96bdba').values()),ensure_ascii=False),encoding='utf-8')
def emit(e):
    _append_job_event(r,job,e)
    print(e.get('type'),e.get('name',''),str(e.get('text',''))[:250],flush=True)
print('ROOM',r,'JOB',job,flush=True)
result=run_timeline_agent(room_id=r,user_id='2582a188-ff24-4a4f-b989-6063034d90b2',content_id=cid,job_id=job,
    expected_hash=td.sequence_hash(td._content_sequence(content)),model='fable',on_event=emit,
    instruction='エディターからの外部サービス調査の実地テストです。HeyGenで本人の自然なクローン音声を作りたい。まず利用可能なスキル・ブラウザー等を自分で調べて、既存HeyGenアカウントや接続の有無と、必要な本人音声素材を確認してください。ログイン済みのブラウザがあるならHeyGenの画面で利用できる機能を確認してください。調査結果と実行に足りないものだけ短く報告してください。このテストでは登録・契約・支払い・音声のアップロードや生成はまだ行わず、他のユーザー作業タブは閉じたり操作したりしない。タイムラインは変更しない。Qwenへ代替しない。機密情報をログに出さない。')
(folder/'discovery-result.json').write_text(json.dumps(result,ensure_ascii=False),encoding='utf-8')
print('RESULT',json.dumps(result,ensure_ascii=False),flush=True)
