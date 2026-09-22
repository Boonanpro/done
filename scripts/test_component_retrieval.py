"""Actual expanded-library selection to decoded editor media, original Japanese requests."""
import asyncio,json,sys,time,uuid,statistics,math
from pathlib import Path
ROOT=Path(__file__).resolve().parents[1];sys.path.insert(0,str(ROOT))
OUT=ROOT/'scratch/component-expansion'
CASES=[
 ('chart','棒グラフと折れ線が順に出て、数字の変化を見せられる動く参考が見たいです。',['hf-data-chart']),
 ('flight','地図の上を飛行機が進んで、二つの都市の間を移動する見本を見たい。',['hf-nyc-paris-flight']),
 ('particles','プログラムの文字が、ばらばらの粒から集まって形になる映像を見せて。',['hf-code-particle-assemble']),
 ('glass','透けたガラスみたいな通知が重なって出てくる参考を見たい。背景が透ける感じ。',['hf-liquid-glass-notification','hf-ios26-liquid-glass']),
 ('depth','アプリの画面を斜めに傾けて奥行きがあるように紹介する動画の見本を見たい。',['hf-ui-3d-reveal','hf-app-showcase']),
 ('camcorder','実写の上に録画中の赤い印や時刻が出る、昔のビデオカメラっぽい見本を見たい。',['hf-camcorder-hud']),
 ('shatter','画面が破片に砕けて次の画面に切り替わる演出の見本を見せて。',['hf-vfx-shatter','hf-transitions-mechanical']),
 ('karaoke','喋っている単語を丸い背景で順に強調する、カラオケみたいな字幕の動く見本はある？',['hf-caption-pill-karaoke']),
 ('decode','字幕が最初はランダムな記号で、解読されて正しい文字になる参考が見たい。',['hf-caption-matrix-decode']),
 ('emphasis','重要な言葉だけ大胆に大きくして、書体も変える字幕の参考を見たい。',['hf-caption-editorial-emphasis']),
 ('social','Xの投稿そのものをカードみたいに映像に出す動く参考を見せて。',['hf-x-post']),
 ('logo','動画の最後にロゴが現れて、短い言葉で締める動く見本を見たい。',['hf-logo-outro']),
]

async def main():
 import httpx
 from playwright.async_api import async_playwright
 from app.services import timeline_draft as td
 room='component-retrieval-'+uuid.uuid4().hex[:8];cid='test';folder=td._room_dir(room);folder.mkdir(parents=True)
 sequence={'format':'16:9','duration':3,'tracks':[{'id':'v','type':'video','clips':[]}]}
 (folder/'contents.json').write_text(json.dumps([{'id':cid,'timeline':{'format':'16:9','sequence':sequence}}]),encoding='utf-8');(folder/'assets.json').write_text('[]')
 token=(Path.home()/'.done/native_token.txt').read_text().strip();base='http://127.0.0.1:8012/api/v1/editor-assistant';results=[]
 async with httpx.AsyncClient(timeout=60,headers={'Authorization':'Bearer '+token}) as client,async_playwright() as p:
  browser=await p.chromium.launch(channel='msedge',headless=True);page=await browser.new_page(viewport={'width':1440,'height':900})
  await page.goto(base+'/page');await page.wait_for_function('typeof window.__updateEditorContext==="function"')
  await page.evaluate('({token,room,cid})=>{window.__editorBootstrap={token};window.__updateEditorContext({room_id:room,content_id:cid,playhead:0,selected:[]});}',{'token':token,'room':room,'cid':cid})
  for name,request,expected in CASES:
   start=time.perf_counter();r=await client.post(base+'/reference-library/decision',json={'dialogue':[{'role':'user','text':request}]});r.raise_for_status();decision=r.json();ids=decision.get('selected_library_ids',[]);ready={'ok':False};source_ok=False
   if ids:
    r=await client.post(base+'/begin',json={'room_id':room,'content_id':cid});r.raise_for_status();turn=r.json()
    r=await client.post(base+'/tool',json={'room_id':room,'turn_id':turn['turn_id'],'name':'present_reference_examples','args':{'ids':ids}});r.raise_for_status();shown=r.json()
    ready=await page.evaluate('async p=>{renderReferences(p);return await presentationReady(p);}',shown['presentation'])
    elapsed=round((time.perf_counter()-start)*1000)
    # Model can retrieve source for the exact item the user just saw.
    ident=shown['presentation']['items'][0]['library_id']
    r=await client.post(base+'/tool',json={'room_id':room,'turn_id':turn['turn_id'],'name':'read_reference_component','args':{'id':ident}});r.raise_for_status();listing=r.json()
    primary=next(f['file'] for f in listing['files'] if f['file'].endswith('.html'))
    r=await client.post(base+'/tool',json={'room_id':room,'turn_id':turn['turn_id'],'name':'read_reference_component','args':{'id':ident,'file':primary}});r.raise_for_status();source_ok=len(r.json().get('source',''))>100
    await page.screenshot(path=str(OUT/(name+'-editor.png')))
   else:elapsed=round((time.perf_counter()-start)*1000)
   result={'case':name,'request':request,'ids':ids,'pass':bool(ids) and set(ids).issubset(expected) and ready['ok'] and source_ok,'total_ms':elapsed,'source_ok':source_ok,'decision':decision};results.append(result)
   (OUT/'retrieval.json').write_text(json.dumps(results,ensure_ascii=False,indent=2),encoding='utf-8');print(json.dumps({k:v for k,v in result.items() if k not in ('decision','request')}),flush=True)
  await browser.close()
 times=sorted(r['total_ms'] for r in results)
 summary={'cases':len(results),'passed':sum(r['pass'] for r in results),'median_ms':statistics.median(times),'p90_ms':times[math.ceil(.9*len(times))-1],'room':room,'timeline_unchanged':td._find_content(td._read_contents_raw(room),cid)['timeline']['sequence']==sequence}
 (OUT/'retrieval-summary.json').write_text(json.dumps(summary,indent=2),encoding='utf-8');print(json.dumps(summary))

if __name__=='__main__':asyncio.run(main())
