"""Browser lifecycle regressions; no production mic, model, or timeline writes."""
import os
from playwright.sync_api import sync_playwright

with sync_playwright() as p:
    browser=p.chromium.launch(headless=True)
    page=browser.new_page()
    page.add_init_script('window.setInterval=()=>0')
    page.goto(os.getenv('EDITOR_TEST_URL','http://127.0.0.1:8019')+'/api/v1/editor-assistant/page')
    page.evaluate('''()=>{
      flushAudit=async()=>{};cancelTurn=async()=>{};
      window.__updateEditorContext({room_id:'lifecycle',content_id:'one'});
      record('user_transcript',{text:'Make an inquiry guide using my recorded footage'});
      previousTurn='prior';saveConversation();micOn=true;connectedAt=Date.now();
      window.__updateEditorContext({room_id:'lifecycle',content_id:''});
    }''')
    assert page.evaluate("micOn && context.content_id==='one' && previousTurn==='prior' && conversationMemory.length===1")
    page.evaluate("window.__updateEditorContext({room_id:'lifecycle',content_id:'two'})")
    assert page.evaluate("micOn && previousTurn===null && conversationMemory.length===1")
    page.evaluate("saveConversation()")
    page.reload()
    page.evaluate("flushAudit=async()=>{};cancelTurn=async()=>{};window.__updateEditorContext({room_id:'lifecycle',content_id:'two'})")
    assert page.evaluate("conversationMemory[0].text.includes('inquiry guide')")
    page.evaluate('''async()=>{
      window.tones=0;endTone=()=>tones++;
      connect=async()=>{dc={readyState:'open',close(){}};connectedAt=Date.now();};
      toggleMic=async()=>{micOn=true;};micOn=true;
      await recoverConnection('test_drop');
    }''')
    assert page.evaluate("micOn && tones===1 && audit.some(e=>e.type==='connection_recovered')")
    page.evaluate('''async()=>{
      const pending=recoverConnection('test_stop');
      disconnect('user');await pending;
    }''')
    assert page.evaluate('!micOn && !renewing')
    page.evaluate('''async()=>{
      connect=async()=>{throw Error('offline');};micOn=true;
      await recoverConnection('test_offline');
    }''')
    assert page.evaluate("!micOn && document.getElementById('toast').textContent.includes('マイクを押す') && audit.filter(e=>e.type==='reconnect_failed').length===3")
    page.evaluate("window.__updateEditorContext({room_id:'other-room',content_id:'three'})")
    assert page.evaluate('conversationMemory.length===0')
    page.evaluate('''async()=>{
      send=()=>{};respond=()=>{};addContext=async()=>{};
      begin=async(c,mode,text)=>{window.capturedUtterance=text;return {turn_id:'joined',context:c};};
      await startSpeech('sentence-one');
      await onEvent({type:'conversation.item.input_audio_transcription.completed',item_id:'sentence-one',transcript:'People returning from work should feel welcome.'});
      await startSpeech('sentence-two');
      await onEvent({type:'conversation.item.input_audio_transcription.completed',item_id:'sentence-two',transcript:'They should want to stop by alone.'});
      await stopSpeech();
    }''')
    assert page.evaluate("capturedUtterance.includes('returning from work') && capturedUtterance.includes('stop by alone') && conversationMemory.length===2")
    page.evaluate('''()=>{
      micOn=true;dc={readyState:'open'};jobs.set('saved-job',{});
      renderProductionStatus({jobs:[{id:'saved-job',status:'done',result:{committed:true,
        outcome:{state:'achieved',summary:'Ready for the application to commit.'}}}]},context);
    }''')
    assert page.evaluate("completionNotices.at(-1).current_timeline.saved && completionNotices.at(-1).current_timeline.user_commit_required===false")
    assert page.evaluate("completionNotices.at(-1).production_report_before_save.summary.includes('commit')")
    page.evaluate('''()=>{
      jobs.set('export-job',{});
      renderProductionStatus({jobs:[{id:'export-job',status:'done',result:{message:'Video render completed.',
        output_url:'/movie.mp4',output_path:'movie.mp4',render_size:'1920x1080'}}]},context);
    }''')
    assert page.evaluate("completionNotices.at(-1).final_result.output_url==='/movie.mp4' && completionNotices.at(-1).current_timeline===undefined")
    page.evaluate("jobs.set('waiting-worker',{});renderProductionStatus({jobs:[{id:'waiting-worker',status:'done',question:{id:'q',job_id:'waiting-worker',text:'Which direction?'}}]},context)")
    assert page.evaluate("pendingQuestion.id==='q'&&jobs.has('waiting-worker')")
    page.evaluate("micOn=false;jobs.set('offline-result',{});renderProductionStatus({jobs:[{id:'offline-result',status:'done',result:{summary:'Ready'}}]},context);saveConversation()")
    assert page.evaluate("completionNotices.some(n=>n.job_id==='offline-result')")
    page.reload()
    page.evaluate("flushAudit=async()=>{};cancelTurn=async()=>{};window.__updateEditorContext({room_id:'other-room',content_id:'three'})")
    assert page.evaluate("completionNotices.some(n=>n.job_id==='offline-result')")
    browser.close()
print('PASS library navigation, content switch, reload history, reconnection, manual stop, exhausted retries, room isolation')
