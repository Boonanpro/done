"""Persistent Astra conversation, with application-owned tools and no API fallback."""
import json
import asyncio
import os
import re
import threading
import uuid
import logging
import traceback
import time
from pathlib import Path
from app.services.editor_codex import CodexTurn

logger = logging.getLogger(__name__)

def pack(items):
    text=[];images=[]
    for source in items:
        item=dict(source)
        if isinstance(item.get('content'),list):
            content=[]
            for part in item['content']:
                if part.get('type')=='input_image':images.append({'type':'image','url':part['image_url']})
                else:content.append(part)
            item['content']=content
        text.append(item)
    return [{'type':'text','text':json.dumps(text,ensure_ascii=False)},*images]

class VoiceCodex:
    def __init__(self):
        self.owner = None
        self.pending = None
        self.timer = None
        self.closed = False
        self.preparation = None
        self.active = False

    async def steer(self, items):
        if self.closed or not self.owner or not self.active:
            return False
        result = await self.owner.request_concurrent('turn/steer', {
            'threadId': self.owner.thread_id, 'expectedTurnId': self.owner.turn_id,
            'input': pack(items)})
        if 'error' in result:
            logger.warning('voice_steer_rejected thread=%s code=%s', self.owner.thread_id, result['error'].get('code'))
            return False
        return True

    @staticmethod
    def config():
        config = Path(os.environ.get('CODEX_HOME',str(Path.home()/'.codex')))/'config.toml'
        names = re.findall(r'^\[mcp_servers\.([^\].]+)\]',config.read_text(encoding='utf-8'),re.M) if config.exists() else []
        return {'features.shell_tool':False,
                'features.fast_mode':True,
                'service_tier':os.environ.get('DAN_VOICE_SERVICE_TIER','fast') or None,
                'mcp_servers':{n.strip('"'):{'enabled':False} for n in names}}

    def warm(self, tools, instructions):
        if self.preparation or self.owner or self.closed:return
        async def prepare():
            if self.closed:return
            self.owner=CodexTurn()
            try:
                await self.owner.prepare(tools,instructions,'gpt-6-astra',config_overrides=self.config())
                self.idle()
            except Exception:
                self.close()
                raise
        self.preparation=asyncio.create_task(prepare())
        self.preparation.add_done_callback(lambda t: t.exception() if not t.cancelled() else None)

    def close(self):
        self.closed = True
        self.active = False
        if self.timer: self.timer.cancel()
        if self.owner: self.owner.close()

    def idle(self):
        if self.closed:return
        self.timer = threading.Timer(600, self.close)
        self.timer.daemon = True
        self.timer.start()

    async def respond(self, items, tools, instructions, on_text=None):
        measured_at=time.monotonic()
        phase='prepare'
        def mark(stage, **fields):
            logger.info('voice_turn_timing %s',json.dumps({'phase':stage,'elapsed_ms':round((time.monotonic()-measured_at)*1000),
                'thread':getattr(self.owner,'thread_id',None),**fields}))
        mark('received',input_chars=len(json.dumps(items,ensure_ascii=False)))
        if self.preparation: await self.preparation
        if self.closed: raise ValueError('音声の実行接続が終了しています。再接続してください')
        if self.timer: self.timer.cancel()
        output = []
        phases = {}
        try:
            if self.pending:
                phase='tool_result'
                call_id, request_id = self.pending
                result = next((i for i in items if i.get('type')=='function_call_output' and i.get('call_id')==call_id),None)
                if result is None: raise ValueError('実行中の道具に対応する結果が必要です')
                self.owner.send({'id':request_id,'result':{'success':True,'contentItems':[
                    {'type':'inputText','text':str(result.get('output',''))}]}})
                self.pending = None
                extra = [i for i in items if i is not result]
                if extra:
                    self.owner.serial+=1
                    self.owner.send({'id':self.owner.serial,'method':'turn/steer','params':{
                        'threadId':self.owner.thread_id,'expectedTurnId':self.owner.turn_id,'input':pack(extra)}})
            elif self.owner:
                phase='new_turn'
                if any(i.get('type')=='function_call_output' for i in items):
                    raise ValueError('終了済みの道具の結果は再実行しません')
                turn = await self.owner.rpc('turn/start',{'threadId':self.owner.thread_id,
                    'input':pack(items)})
                self.owner.turn_id = turn['turn']['id']
                self.active = True
            else:
                phase='start_agent'
                if any(i.get('type')=='function_call_output' for i in items):
                    raise ValueError('実行接続のない道具の結果は受け付けません')
                self.owner = CodexTurn()
                await self.owner.start(items,tools,instructions,'gpt-6-astra',config_overrides={
                    **self.config()})
                self.active = True
            mark('waiting_model',continuation=phase)
            while True:
                event = await self.owner.receive()
                method, params = event.get('method'),event.get('params',{})
                if method == 'item/started' and params.get('item', {}).get('type') == 'agentMessage':
                    item = params['item']
                    phases[item['id']] = item.get('phase')
                if method == 'item/agentMessage/delta' and on_text and phases.get(params.get('itemId')) == 'final_answer':
                    on_text(params.get('delta', ''))
                if method=='item/tool/call':
                    mark('tool_requested',tool=params['tool'],action=params.get('arguments',{}).get('action'))
                    call_id = 'voice-codex-'+uuid.uuid4().hex
                    self.pending = (call_id,event['id'])
                    output.append({'type':'function_call','call_id':call_id,'name':params['tool'],
                        'arguments':json.dumps(params['arguments'],ensure_ascii=False)})
                    return {'output':output,'backend':'codex_cli','model':'gpt-6-astra'}
                if method=='item/completed' and params.get('item',{}).get('type')=='agentMessage':
                    item=params['item']
                    if item.get('phase') != 'commentary':
                        output.append({'type':'message','role':'assistant','content':[{'type':'output_text','text':item['text']}]})
                elif method=='turn/completed':
                    mark('completed',status=params['turn']['status'])
                    self.active = False
                    if params['turn']['status']!='completed':
                        raise RuntimeError('Astra: '+str(params['turn'].get('error') or params['turn']['status']))
                    return {'output':output,'backend':'codex_cli','model':'gpt-6-astra'}
                elif method=='process/closed': raise RuntimeError('Astraの実行接続が終了しました')
                elif method and 'id' in event:
                    self.owner.send({'id':event['id'],'error':{'code':-32601,'message':'Use the provided Dan tools.'}})
        except Exception as exc:
            if self.closed:
                # Explicit call closure terminates the owned CLI process. Its final
                # interrupted/closed event is cancellation, not a failed live request.
                logger.info('voice_backend_cancelled')
                raise asyncio.CancelledError('Voice connection closed') from exc
            # No input text, tool output, credentials or exception messages in logs.
            logger.error('voice_backend_exception kind=%s thread=%s turn=%s pending=%s inputs=%s frames=%s',
                type(exc).__name__, getattr(self.owner,'thread_id',None), getattr(self.owner,'turn_id',None),
                self.pending, [(i.get('type'),i.get('call_id')) for i in items],
                [(f.filename,f.lineno,f.name) for f in traceback.extract_tb(exc.__traceback__)])
            self.close()
            raise
        finally:
            if not self.closed: self.idle()
