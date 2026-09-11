"""Browser regression: review is not editing; generated audio is not delivered audio.

Uses controlled status/data-channel fixtures, without starting a production job.
"""
from playwright.sync_api import sync_playwright


def main():
    with sync_playwright() as p:
        browser=p.chromium.launch(headless=True)
        page=browser.new_page()
        page.add_init_script('window.setInterval=()=>0;')
        page.goto('http://127.0.0.1:8000/api/v1/editor-assistant/page')
        page.evaluate("""() => {
            context={room_id:'notification-unit',content_id:'notification-unit'};
            window.commands=[];nativeCommand=c=>commands.push(c);
            window.sent=[];send=e=>sent.push(e);
            request=async()=>({text:'文字の変更が終わりました。'});
            window.job={id:'job',status:'running',created_at:'1',updated_at:'2',
              selected_clips:[{id:'caption'}],activity:[{tool:'set_clip',category:'editing',state:'running',clip_ids:['caption']}]};
            renderProductionStatus({jobs:[job]},context);
        }""")
        assert page.evaluate('productionSnapshot.highlights.length')==1
        page.evaluate("job.activity=[{tool:'watch_render',category:'review',state:'running'}];renderProductionStatus({jobs:[job]},context)")
        assert page.evaluate('productionSnapshot.highlights.length')==0
        assert page.evaluate('productionSnapshot.label')=='仕上がりを確認中'
        page.evaluate("job.status='done';job.result={committed:true,summary:'変更しました'};renderProductionStatus({jobs:[job]},context);renderProductionStatus({jobs:[job]},context)")
        assert page.locator('.production-card').count()==0
        assert page.evaluate('completionNotices.length')==1
        assert page.evaluate('productionSnapshot.active_count')==0
        # A disconnected session keeps its pending completion until speech is possible.
        page.evaluate('announceCompletion()')
        assert page.evaluate('completionNotices.length')==1
        page.evaluate("micOn=true;dc={readyState:'open'};announceCompletion()")
        page.evaluate("onEvent({type:'response.output_audio_transcript.done',transcript:'変更しました'})")
        page.evaluate("onEvent({type:'response.done',response:{status:'completed'}})")
        assert page.evaluate('!!activeNotice&&!activeNotice.spoken')
        assert page.evaluate("!audit.some(e=>e.type==='completion_spoken')")
        page.evaluate('activeNotice.audioStarted=true;activeNotice.audioEnded=true;finishNotice()')
        assert page.evaluate('activeNotice===null')
        assert page.evaluate("audit.filter(e=>e.type==='completion_spoken').length") == 1
        # Interrupted output is queued again, not marked as heard.
        page.evaluate("completionNotices.push({room_id:context.room_id,content_id:context.content_id,job_id:'second'});announceCompletion()")
        page.evaluate('interrupt()')
        assert page.evaluate("completionNotices.some(n=>n.job_id==='second')")
        browser.close()
    print('PASS status phases, terminal clearing, offline queue, actual audio delivery, interrupted notification retry')


if __name__=='__main__':main()

