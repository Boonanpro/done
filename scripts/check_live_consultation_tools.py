"""Real Live WebRTC + Responses functions; text inputs, no microphone capture."""
import asyncio,json
from pathlib import Path
from playwright.async_api import async_playwright

async def main():
    out=Path('scratch/live-consultation-sheet');out.mkdir(parents=True,exist_ok=True)
    token=(Path.home()/'.done/native_token.txt').read_text().strip()
    async with async_playwright() as p:
        browser=await p.chromium.launch(channel='msedge',headless=True)
        page=await browser.new_page(viewport={'width':1440,'height':1000})
        await page.goto('http://127.0.0.1:8000/api/v1/editor-assistant/page')
        await page.evaluate('v=>window.__setEditorAuth(v)',{'token':token})
        try:
            await page.evaluate('''async()=>{
              context={room_id:'sheet-native-test',content_id:'sheet-native-test'};
              window.sheetEvents=[];
              const peer=new RTCPeerConnection();window.sheetPeer=peer;
              peer.addTransceiver('audio',{direction:'sendrecv'});
              const channel=peer.createDataChannel('oai-events');window.sheetChannel=channel;dc=channel;
              const session={started:false,editContext:structuredClone(context),rows:{},views:[]};liveConnection=session;
              channel.onmessage=e=>{const m=JSON.parse(e.data);window.sheetEvents.push(m);
                if(m.type==='session.started'){session.started=true;session.id=m.session.id;}
                if(m.type==='response.event')handleLiveResponseEvent(m,session).catch(e=>window.sheetEvents.push({type:'test_error',message:String(e)}));
              };
              await peer.setLocalDescription(await peer.createOffer());
              if(peer.iceGatheringState!=='complete')await new Promise(resolve=>{const done=()=>{if(peer.iceGatheringState==='complete'){peer.removeEventListener('icegatheringstatechange',done);resolve();}};peer.addEventListener('icegatheringstatechange',done);});
              const reply=await api('/live/session',{sdp:peer.localDescription.sdp,history:[]});
              await peer.setRemoteDescription({type:'answer',sdp:reply.transport.sdp});
            }''')
            await page.wait_for_function('()=>liveConnection?.started',timeout=30000)
        except Exception:
            await page.evaluate("()=>{if(window.sheetChannel?.readyState==='open')window.sheetChannel.send(JSON.stringify({type:'session.close'}));window.sheetPeer?.close();}")
            await browser.close()
            raise
        try:
            cases=[
                ('都市伝説系のYouTubeチャンネルの一本目を作りたい。題材はシミュレーション仮説。今は参考を探さず、この情報を相談メモに整理して。','シミュレーション'),
                ('題材を訂正する。フェルミのパラドックスにしたい。公開先と動画の種類はそのまま。尺はまだ決めず、下書きを見て決める。素材は手持ちなし。まだ参考検索や制作はしないで。','フェルミ'),
            ]
            snapshots=[]
            for text,expected in cases:
                await page.evaluate('''text=>{
                  send({type:'response.item.create',event_id:crypto.randomUUID(),item:{type:'message',role:'user',content:[{type:'input_text',text}]}});
                  send({type:'response.create',event_id:crypto.randomUUID()});
                }''',text)
                await page.wait_for_function('''expected=>{
                  const memo=readConsultationMemo(liveConnection);return memo?.version===3&&memo.fields.subject.value.includes(expected)&&!liveConnection.responsePending;
                }''',arg=expected,timeout=60000)
                sheet=await page.evaluate('()=>readConsultationMemo(liveConnection)');snapshots.append(sheet)
            assert 'YouTube' in snapshots[-1]['fields']['platform']['value'],snapshots
            assert snapshots[-1]['fields']['duration']['status']=='undecided',snapshots
            assert snapshots[-1]['fields']['purpose']['status']=='unknown',snapshots
            assert snapshots[-1]['fields']['references']['status']=='unknown',snapshots
            assert not snapshots[-1]['ready_for_draft'],snapshots
            await page.evaluate('''text=>{
              send({type:'response.item.create',event_id:crypto.randomUUID(),item:{type:'message',role:'user',content:[{type:'input_text',text}]}});
              send({type:'response.create',event_id:crypto.randomUUID()});
            }''','目的は視聴者に宇宙の謎を面白いと思ってもらうこと。視聴者は都市伝説好きの大人。参考作品は今回は選ばず未定で進める。それも含め今話した方向で良い。まだ作り始めず、シートを更新して次の進め方だけ提案して。')
            await page.wait_for_function('()=>readConsultationMemo(liveConnection)?.ready_for_draft===true&&!liveConnection.responsePending',timeout=60000)
            snapshots.append(await page.evaluate('()=>readConsultationMemo(liveConnection)'))
            assert all(v['status']!='unknown' for v in snapshots[-1]['fields'].values())
            await page.screenshot(path=str(out/'sheet.png'))
            events=await page.evaluate('()=>window.sheetEvents')
            errors=[e for e in events if e.get('type') in ('error','test_error')]
            assert not errors,errors
            calls=[e['event']['item']['name'] for e in events if e.get('event',{}).get('type')=='response.output_item.done' and e['event'].get('item',{}).get('type')=='function_call']
            assert 'run_editor_task' not in calls,calls
            (out/'result.json').write_text(json.dumps({'sheets':snapshots,'errors':errors,'tool_calls':calls},ensure_ascii=False,indent=2),encoding='utf-8')
            print(json.dumps({'passed':True,'turns':3,'errors':errors}))
        finally:
            await page.evaluate("()=>{if(window.sheetChannel?.readyState==='open')window.sheetChannel.send(JSON.stringify({type:'session.close'}));}")
            await page.wait_for_timeout(1000)
            await page.evaluate('()=>{window.sheetChannel?.close();window.sheetPeer?.close();}')
            await browser.close()

if __name__=='__main__':asyncio.run(main())
