"""12 predeclared goals; plain conversation to real Jev/CLI and actual renderer.
Expected IDs and tests never go into model context. No microphone or billing recharge.
"""
import asyncio,json,sys,time,uuid,statistics,argparse
from pathlib import Path
ROOT=Path(__file__).resolve().parents[1];sys.path.insert(0,str(ROOT))
CASES=[
 ('illustration-worried',['テレビの体験談みたいな絵の参考を見たいです。まだどういう絵か言えません。','笑顔じゃなくて、困っている感じ。写真みたいな絵より漫画っぽい方を見たい。'],['7456090a4f3b']),
 ('illustration-serious',['大人向けの体験談の見た目を相談したいので、絵の参考を二つ見せて。','かわいい漫画より、実際にありそうな重い場面のイラストがいいです。複数の人がいる緊張感のある感じ。'],['d751b8e01079']),
 ('illustration-face',['人物紹介の見た目が決まりません。まず顔の絵を比べてみたい。','周りの場面は要らなくて顔だけがいい。色もいらない。大げさな似顔絵の参考を見せて。'],['c82cfdff99c8']),
 ('video-nature',['落ち着ける実写の見本動画を見せてもらえる？','街より自然だけがいい。人はいなくて、近くからじっと見ているような動画の参考がいい。'],['mdn-flower']),
 ('video-outdoor',['現実の生活を感じるような映像の参考を見たい。','外の風景で、何かが行き交っている実写の動画を見たいです。イラストではなく。'],['samplelib-road']),
 ('video-motion',['動きの参考に短い映像を見せてほしい。','静止画だと分からないので、実写で何かが変わっていく様子を近くで撮った動画を見たい。人の動きでなくてもいい。'],['mdn-flower']),
 ('caption-gentle',['喫茶店の紹介動画の文字、どんな感じがいいか見せてもらえる？','穏やかに読みたいので跳ねる感じは嫌です。本みたいな文字が柔らかく出る字幕の動く見本を見せて。'],['5635b8785a8d','ec6dcb660f83']),
 ('caption-emphasis',['文字の見せ方をいくつか比べたいです。','全体を派手にするんじゃなく、言葉の一部分だけ色が変わる参考を見せて。落ち着いた雰囲気はそのままで。'],['ec6dcb660f83']),
 ('caption-two-line',['文章の出し方の見本が見たい。','一行全部が同時に出るより、二段にして下の言葉を少し後で大きく出す感じを見たいです。'],['e5c4eac9c3f2']),
 ('motion-comparison',['情報不足で何回も連絡するのと一回で済むのを、どう見せればいいか参考を見たい。','人の映像より、やり取りが動いて、上下で違いが見える図解の見本がいい。'],['e34609f1898f','6773c9ff7c1f','5456bbb95d3c']),
 ('motion-gather',['必要な情報を揃える良さを説明する動く見本を見せて。','五つがまず一つにまとまってから相手へ届く、そういう動きの参考を見たい。'],['6773c9ff7c1f','5456bbb95d3c']),
 ('motion-speed',['情報をまとめて届ける図解の動く参考を見せて。','五つが集まって相手に届く同じ内容で、届く所がゆっくりな参考を見たいです。'],['5456bbb95d3c']),
]
NEGATIVE=[
 'この動画を削除して。', '今は参考は要りません。今日は何日？',
 'この字幕の文字を赤に変えて。','YouTubeで新しい参考を探して。',
 'スマホを置いて取り直す人物の実写動画を見せて。静止画もCGも不要。検索も生成もしないで。',
 '病室で医師が手術している実写動画の参考を見せて。イラストは不要。',
 '実写の人物が踊っている映像を見せてほしい。花や道路の動画ではありません。',
 'グラフの棒がデータに合わせて伸びるアニメの参考を見たい。メッセージや人の往復の図は違います。',
 '字幕が激しく弾けて回転する見本を見たい。静かな出方の字幕はいらない。',
 'フォトリアルな女性の顔の3Dモデルを見せて。似顔絵や図解では判断できません。',
 '海中でサメが泳いでいる実写の映像を見たい。ほかの場所や生き物は違います。',
]

PARAPHRASES=[
 ['経験を語る動画に合うイラスト、候補を見ながら決めたい。','楽しそうな顔は違うんだよね。漫画のタッチで戸惑っている人のいる絵が近い。そういう参考ある？'],
 ['大人が見る回想に使えそうな絵の方向を比較したい。','デフォルメより現実っぽさがほしい。何人かが対峙している重たい雰囲気の参考が近そう。'],
 ['人物の紹介に合う描き方を見たいな。','顔だけの、モノクロで思い切って特徴を大きくした似顔絵を見せて。背景の場面はいらない。'],
 ['ほっとする実際の映像を参考に見たい。','人も交通も入らない、植物に近づいて変化を眺める感じの動画ってある？'],
 ['暮らしの気配がある映像を見て雰囲気を決めたい。','外で車が通っているような現実の風景の映像が近い。動くやつを見たい。'],
 ['短い動画で動き方の参考を出せる？','実際に撮ったものがいい。植物が開くみたいな、小さい変化が見える接写を見たい。'],
 ['カフェの動画に載せる文字を実物で見比べたい。','飛び跳ねず、ゆっくり浮かぶような文字がいい。本のような落ち着きがある案を見せて。'],
 ['文字の参考案を比較したい。','全部の色を変えるのは違う。特定の言葉だけ金色で目立つ、控えめな案ってある？'],
 ['文字をどう出すか、動く案を見せて。','上の行の後に下の大きな言葉が現れるような案を見たい。一行だけの案とは違う方。'],
 ['何度も聞き直す場合と一回で伝わる場合を、動く参考で比較したい。','実際の人を撮るのでなく、上と下でメッセージの往復の差が分かる図の方を見たい。'],
 ['必要なことをまとめる意味が分かるアニメの参考を見たい。','五個の情報が集まって、それから一まとめで届く案があるなら見せて。'],
 ['情報がまとまって届くような動く図の参考を見せて。','五個まとまる内容は同じで、運ばれる動きが遅い方を見たい。別内容にしたいわけではないよ。'],
]

async def main(tag,paraphrase=False):
 import httpx
 from playwright.async_api import async_playwright
 from app.services import timeline_draft as td
 out=ROOT/'scratch/reference-library-acceptance'/tag;out.mkdir(parents=True,exist_ok=True)
 room='library-acceptance-'+uuid.uuid4().hex[:8];cid='test';folder=td._room_dir(room);folder.mkdir(parents=True)
 seq={'format':'16:9','duration':3,'tracks':[{'id':'v','type':'video','clips':[]}]}
 (folder/'contents.json').write_text(json.dumps([{'id':cid,'timeline':{'format':'16:9','sequence':seq}}]),encoding='utf-8');(folder/'assets.json').write_text('[]',encoding='utf-8')
 token=(Path.home()/'.done/native_token.txt').read_text().strip();base='http://127.0.0.1:8012/api/v1/editor-assistant'
 results=[];negative=[]
 async with httpx.AsyncClient(timeout=70,headers={'Authorization':'Bearer '+token}) as client,async_playwright() as p:
  for attempt in range(20):
   try:
    r=await client.get(base+'/page');r.raise_for_status();break
   except httpx.HTTPError:
    if attempt==19:raise
    await asyncio.sleep(1)
  browser=await p.chromium.launch(channel='msedge',headless=True);page=await browser.new_page(viewport={'width':1440,'height':900},record_video_dir=str(out/'recording'),record_video_size={'width':1440,'height':900})
  await page.goto(base+'/page');await page.wait_for_function('typeof window.__updateEditorContext==="function"')
  await page.evaluate('({token,room,cid})=>{window.__editorBootstrap={token};window.__updateEditorContext({room_id:room,content_id:cid,playhead:0,selected:[]});}',{'token':token,'room':room,'cid':cid})
  for case_index,(name,utterances,expected) in enumerate(CASES):
   if paraphrase:utterances=PARAPHRASES[case_index]
   dialogue=[];items=[];turns=[]
   for n,text in enumerate(utterances):
    dialogue.append({'role':'user','text':text});start=time.perf_counter()
    r=await client.post(base+'/reference-library/decision',json={'dialogue':dialogue,'items':items});r.raise_for_status();d=r.json();decision_ms=round(1000*(time.perf_counter()-start));ids=d.get('selected_library_ids',[]);paint_ms=None;display={'ok':False}
    if d.get('handled') and ids:
     r=await client.post(base+'/begin',json={'room_id':room,'content_id':cid,'live_dialogue':dialogue});r.raise_for_status();turn=r.json()
     r=await client.post(base+'/tool',json={'room_id':room,'turn_id':turn['turn_id'],'name':'present_reference_examples','args':{'ids':ids}});r.raise_for_status();shown=r.json();items=shown['presentation']['items'];paint=time.perf_counter()
     display=await page.evaluate('async p=>{renderReferences(p);return await presentationReady(p);}',shown['presentation']);paint_ms=round(1000*(time.perf_counter()-paint))
     dialogue.append({'role':'assistant','text':'提示した実物: '+json.dumps([{'title':i['title'],'kind':i['kind']} for i in items],ensure_ascii=False)})
    else:dialogue.append({'role':'assistant','text':'条件に合う候補をまだ提示していません。'})
    entry={'turn':n+1,'request':text,'selected':ids,'handled':d.get('handled'),'backend':d.get('selection_backend'),'decision_ms':decision_ms,'selection_timing':d.get('selection_timing'),'ranking_failure':d.get('ranking_failure'),'total_ms':round(1000*(time.perf_counter()-start)),'paint_ms':paint_ms,'display':display,'scores':d.get('scores')};turns.append(entry)
    if n==len(utterances)-1:
     await page.screenshot(path=str(out/(name+'.png')))
     # Observe real motion, not just a rendered video element.
     if ids and any(i['kind']=='video' for i in items):
      videos=page.locator('[data-presentation="'+shown['presentation']['id']+'"] video');video=videos.first
      before=await video.evaluate('v=>{v.muted=true;v.play();return v.currentTime;}');await page.wait_for_timeout(400);after=await video.evaluate('v=>v.currentTime');entry['playback_advanced']=after>before+.1
    print(json.dumps({'case':name,**{k:v for k,v in entry.items() if k not in ('scores','request')}},ensure_ascii=False),flush=True)
   last=turns[-1];passed=bool(last['selected']) and set(last['selected']).issubset(expected) and last['display']['ok']
   if name.startswith('video'):passed=passed and last.get('playback_advanced',False)
   results.append({'case':name,'selection_pass':passed,'expected':expected,'turns':turns});(out/'results.json').write_text(json.dumps(results,ensure_ascii=False,indent=2),encoding='utf-8')
  for text in NEGATIVE:
   start=time.perf_counter();r=await client.post(base+'/reference-library/decision',json={'dialogue':[{'role':'user','text':text}]});r.raise_for_status();d=r.json();negative.append({'request':text,'selected':d.get('selected_library_ids',[]),'handled':d.get('handled'),'ms':round(1000*(time.perf_counter()-start))})
  assert td._find_content(td._read_contents_raw(room),cid)['timeline']['sequence']==seq
  await browser.close()
 times=sorted(t['total_ms'] for c in results for t in c['turns'] if t['display']['ok']);paints=[t['paint_ms'] for c in results for t in c['turns'] if t['paint_ms'] is not None]
 summary={'scope':'transcribed conversation / actual renderer; not audio','room':room,'selection_pass':sum(c['selection_pass'] for c in results),'cases':len(results),'displayed_turns':len(times),'median_ms':statistics.median(times) if times else None,'p90_ms':times[__import__('math').ceil(.9*len(times))-1] if times else None,'paint_max_ms':max(paints,default=0),'negative':negative,'timeline_unchanged':True}
 (out/'summary.json').write_text(json.dumps(summary,ensure_ascii=False,indent=2),encoding='utf-8');print(json.dumps(summary,ensure_ascii=False),flush=True)

if __name__=='__main__':
 parser=argparse.ArgumentParser();parser.add_argument('--tag',default='baseline');parser.add_argument('--paraphrase',action='store_true');args=parser.parse_args();asyncio.run(main(args.tag,args.paraphrase))
