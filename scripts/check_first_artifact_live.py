"""Live's real delegation with typed user input; not a microphone/acoustic test."""
import asyncio,json,time
from pathlib import Path
from playwright.async_api import async_playwright
from app.services.editor_consultation_sheet import empty,update

async def main():
 out=Path('scratch/first-artifact-milestone');out.mkdir(parents=True,exist_ok=True)
 sheet=update(empty(),[{'field':k,'status':'confirmed','value':v} for k,v in {
  'video_type':'文字と図形のローンチ動画','subject':'散らばった情報を一つにまとめるメモアプリ',
  'platform':'YouTube','purpose':'アプリを使ってみたいと思ってもらう','audience':'情報整理に困る社会人',
  'duration':'15秒','materials':'素材なし。画像や人物は使わない','references':'紺と白のミニマルな図形。配色は合意済み。集まる動きや間はまだ未確認。'}.items()],True)
 async with async_playwright() as p:
  browser=await p.chromium.launch(channel='msedge',headless=True)
  page=await browser.new_page(viewport={'width':1440,'height':1000})
  try:
   await page.goto('http://127.0.0.1:8000/api/v1/editor-assistant/page')
   await page.evaluate('v=>window.__setEditorAuth(v)',{'token':(Path.home()/'.done/native_token.txt').read_text().strip()})
   await page.evaluate('''async memo=>{
    const room='first-artifact-motion-20260924';
    const project=await api('/new',{room_id:room});context={room_id:room,content_id:project.content_id};
    localStorage.setItem(consultationMemoKey({editContext:context}),JSON.stringify(memo));
    window.trialEvents=[];window.trialPeer=new RTCPeerConnection();trialPeer.addTransceiver('audio',{direction:'sendrecv'});
    window.trialChannel=trialPeer.createDataChannel('oai-events');dc=trialChannel;
    const session={started:false,editContext:structuredClone(context),rows:{},views:[]};liveConnection=session;
    trialChannel.onmessage=e=>{const m=JSON.parse(e.data);trialEvents.push(m);
     if(m.type==='session.started'){session.started=true;session.id=m.session.id;}
     if(m.type==='response.event')handleLiveResponseEvent(m,session).catch(e=>trialEvents.push({type:'test_error',message:String(e)}));
    };
    await trialPeer.setLocalDescription(await trialPeer.createOffer());
    if(trialPeer.iceGatheringState!=='complete')await new Promise(resolve=>{const cb=()=>{if(trialPeer.iceGatheringState==='complete'){trialPeer.removeEventListener('icegatheringstatechange',cb);resolve();}};trialPeer.addEventListener('icegatheringstatechange',cb);});
    const reply=await api('/live/session',{sdp:trialPeer.localDescription.sdp,history:[
     {role:'user',text:'15秒のメモアプリのローンチ動画を作りたい。散らばった情報が一つにまとまる感じ。紺と白のミニマルな文字と図形で、写真や人物は使わない。用途や尺は相談メモに決めた通り。'},
     {role:'assistant',text:'配色は紺と白でいきましょう。情報が集まって一つになる方向ですね。'}]});
    await trialPeer.setRemoteDescription({type:'answer',sdp:reply.transport.sdp});
   }''',sheet)
   await page.wait_for_function('()=>liveConnection?.started',timeout=30000)
   started=time.perf_counter()
   await page.evaluate('''()=>{
    send({type:'response.item.create',event_id:crypto.randomUUID(),item:{type:'message',role:'user',content:[{type:'input_text',text:'うん、その方向でいい。色とかは良いけど、動いた時に気持ち良いかはまだ分からんな。'}]}});
    send({type:'response.create',event_id:crypto.randomUUID()});
   }''')
   await page.wait_for_function('()=>document.querySelectorAll(".reference-card").length>0',timeout=90000)
   elapsed=round(time.perf_counter()-started,2)
   await page.wait_for_timeout(3000)
   await page.screenshot(path=str(out/'live-motion.png'))
   events=await page.evaluate('()=>trialEvents')
   errors=[e for e in events if e.get('type') in ('error','test_error')]
   calls=[e['event']['item'] for e in events if e.get('event',{}).get('type')=='response.output_item.done' and e['event'].get('item',{}).get('type')=='function_call']
   report={'seconds_to_card':elapsed,'errors':errors,'calls':calls,'context':await page.evaluate('()=>context')}
   (out/'live-motion.json').write_text(json.dumps(report,ensure_ascii=False,indent=2),encoding='utf8')
   assert not errors,errors
   assert any(c['name']=='show_consultation_visual' for c in calls),calls
   print('PASS real Live delegation to visible artifact',elapsed,flush=True)
  finally:
   await page.evaluate("()=>{if(window.trialChannel?.readyState==='open')trialChannel.send(JSON.stringify({type:'session.close'}));window.trialPeer?.close();}")
   await browser.close()

if __name__=='__main__':asyncio.run(main())
