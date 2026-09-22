"""Real Astra editor run: read reference/context and deliver an existing approved sample."""
import copy
import json
import shutil
import time
import uuid
from pathlib import Path
from app.services import timeline_draft as td, editor_references
from app.services.timeline_agent import run_timeline_agent
from app.api.production_asset_routes import _append_job_event

def main():
    source='2c1c50e1-61c4-44eb-99e5-8f78905ab200'
    room='google-handoff-'+uuid.uuid4().hex[:8]
    folder=td._room_dir(room);folder.mkdir(parents=True)
    content=copy.deepcopy(td._read_contents_raw(source)[0]);cid=content['id']
    content['editor_work']=[]
    content['timeline']={'format':'16:9','sequence':{'format':'16:9','frame_rate':30,'duration':0,
        'tracks':[{'id':'video','type':'video','clips':[]},{'id':'audio','type':'audio','clips':[]}]}}
    content['creative_brief']['constraints']='この確認では生成済みBを使う。追加生成・Higgsfieldクレジット消費なし。'
    content['creative_brief']['feedback']='ユーザーはAよりBのクオリティが高いと評価した。BはGoogle API直結で参考のテイストから別題材として制作した5秒の動画。'
    td._write_contents_raw(room,[content])
    shutil.copy2(td._room_dir(source)/'assets.json',folder/'assets.json')
    dest=editor_references._folder(room)
    for p in editor_references._folder(source).glob('*'):
        if p.is_file():shutil.copy2(p,dest/p.name)
    job=uuid.uuid4().hex
    state={'room_id':room,'content_id':cid,'job_id':job,'source_room':source}
    Path('uploads/google-handoff-latest.json').write_text(json.dumps(state),encoding='utf-8')
    def emit(e):
        _append_job_event(room,job,e)
        if e.get('type')!='keepalive':print(e.get('type'),str(e.get('text',''))[:220],flush=True)
    started=time.monotonic()
    result=run_timeline_agent(room_id=room,user_id='2582a188-ff24-4a4f-b989-6063034d90b2',
        content_id=cid,job_id=job,
        instruction='参考から別の題材を作ったBを気に入っています。保存した参考と今回の判断を読んだうえで、Bをこの空のエディターに音付きで置いてください。完成見本として全尺をそのまま再生したいです。Bは D:/done/exports/omni-direct-comparison/b_from_reference.mp4 に生成済みです。既存成果を使い、新規生成や課金はしないでください。動画を編集画面で見られるところまで行い、どこへ反映したか報告してください。元の長い動画へ上書きするテストではありません。',on_event=emit)
    result['elapsed_seconds']=round(time.monotonic()-started,2)
    (folder/'acceptance-result.json').write_text(json.dumps(result,ensure_ascii=False),encoding='utf-8')
    print('RESULT',json.dumps(result,ensure_ascii=False),flush=True)
    assert result['ok'] and result['committed'],result
    seq=td._content_sequence(td._read_contents_raw(room)[0])
    assert seq['format']=='16:9' and 4.9<=seq['duration']<=5.1
    assert any(t['type']=='audio' and t['clips'] for t in seq['tracks'])

if __name__=='__main__':main()
