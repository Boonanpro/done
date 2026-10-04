"""Project-owned finished-look images, with explicit models and edit ancestry."""
import base64
import hashlib
import json
import mimetypes
import time
from contextlib import ExitStack
from pathlib import Path
import httpx
from app.services import timeline_draft as td

MODELS={'gpt-image-2','gpt-image-2.5-flare','gpt-image-2.5-sunburst'}

def generate(room, content_id, prompt, title='完成イメージ', reference_asset_ids=None, model=None, aspect='16:9', revises=None):
    from app.config import settings
    from app.services.editor_media import import_media
    from app.services.editor_presentation import present
    content=td._find_content(td._read_contents_raw(room),content_id)
    if not content:raise ValueError('Content not found')
    ids=list(dict.fromkeys(reference_asset_ids or []))
    if not prompt.strip() or len(prompt)>12000 or len(ids)>4:raise ValueError('Invalid image request')
    assets_path=td._room_dir(room)/'assets.json'
    assets={a['id']:a for a in json.loads(assets_path.read_text(encoding='utf8'))} if assets_path.exists() else {}
    if revises:
        previous=next((r for r in content.get('look_frames',[]) if r['item_id']==revises),None)
        if not previous:raise ValueError('Original look frame not found in this project')
        ids=list(dict.fromkeys([previous['asset_id'],*ids]))
    if len(ids)>4:raise ValueError('At most four reference images')
    sources=[]
    for aid in ids:
        a=assets.get(aid,{})
        p=Path(a.get('local_path',''))
        if a.get('kind')!='image' or not p.is_file():raise ValueError('Reference image not found: '+aid)
        if p.stat().st_size>20*1024*1024:raise ValueError('Reference image exceeds 20 MB')
        sources.append(p)
    model=model or ('gpt-image-2.5-sunburst' if revises else 'gpt-image-2.5-flare')
    if model not in MODELS:raise ValueError('Use a supported GPT Image model')
    sizes={'16:9':'1536x864','9:16':'864x1536','1:1':'1024x1024'}
    if aspect not in sizes:raise ValueError('Unsupported aspect ratio')
    spec={'prompt':prompt,'model':model,'size':sizes[aspect],'quality':'high','reference_asset_ids':ids,
          'reference_sha256':[hashlib.sha256(p.read_bytes()).hexdigest() for p in sources],'revises':revises}
    key=hashlib.sha256(json.dumps(spec,sort_keys=True).encode()).hexdigest()[:24]
    target=td._room_dir(room)/'look-frames'/content_id/key
    target.mkdir(parents=True,exist_ok=True)
    receipt=target/'receipt.json';output=target/'image.png'
    if receipt.exists():
        saved=json.loads(receipt.read_text(encoding='utf8'))
        if saved.get('state')!='completed' or not output.exists():
            raise ValueError('Previous generation has no confirmed result; inspect receipt before retrying')
    else:
        if not settings.OPENAI_API_KEY:raise ValueError('OpenAI API is not configured')
        saved={'state':'requesting','request':spec}
        with receipt.open('x',encoding='utf8') as f:json.dump(saved,f,ensure_ascii=False)
        start=time.monotonic()
        try:
            fields={k:spec[k] for k in ('prompt','model','size','quality')}
            with httpx.Client(timeout=600) as client, ExitStack() as stack:
                headers={'Authorization':'Bearer '+settings.OPENAI_API_KEY}
                if sources:
                    files=[('image[]',(p.name,stack.enter_context(p.open('rb')),mimetypes.guess_type(p.name)[0] or 'image/png')) for p in sources]
                    response=client.post('https://api.openai.com/v1/images/edits',headers=headers,data=fields,files=files)
                else:
                    response=client.post('https://api.openai.com/v1/images/generations',headers=headers,json=fields)
            saved['http_status']=response.status_code
            response.raise_for_status();body=response.json()
            raw=base64.b64decode(body['data'][0]['b64_json'],validate=True)
            from PIL import Image
            from io import BytesIO
            with Image.open(BytesIO(raw)) as im:im.verify()
            output.write_bytes(raw)
            saved.update(state='completed',returned_model=body.get('model'),usage=body.get('usage',{}),elapsed_seconds=round(time.monotonic()-start,2))
        except Exception:
            saved['state']='uncertain'
            raise
        finally:
            receipt.write_text(json.dumps(saved,ensure_ascii=False,indent=2),encoding='utf8')
    completed=next((r for r in content.get('look_frames',[]) if r.get('receipt')==str(receipt)),None)
    if completed:
        previous_presentation=next((p for p in content.get('proposal_history',[])+[content.get('presentation',{})]
            if any(i.get('id')==completed['item_id'] for i in p.get('items',[]))),None)
        if previous_presentation:
            return {'ok':True,'asset_id':completed['asset_id'],'path':str(output),'model':model,
                    'elapsed_seconds':saved['elapsed_seconds'],'presentation':previous_presentation,'reused':True}
    # Reuse the registered asset on retries without another generation or copy.
    existing=next((a for a in assets.values() if a.get('original_uri')==str(output.resolve())),None)
    if existing:aid=existing['id']
    else:
        registered=import_media(room,str(output),title,origin='gpt-image-look-frame')
        if not registered['ok']:raise ValueError(registered['error'])
        aid=registered['asset_id']
    item={'kind':'image','title':title,'asset_id':aid}
    if revises:item['revises']=revises
    shown=present(room,content_id,[item],comparison_key='look-frame:'+key)
    item_id=shown['presentation']['items'][0]['id']
    row={'item_id':item_id,'asset_id':aid,'revises':revises,'requested_model':model,'returned_model':saved.get('returned_model'),
         'prompt':prompt,'reference_asset_ids':ids,'receipt':str(receipt),'path':str(output),'created_at':time.time()}
    with td.ContentsLock(room):
        contents=td._read_contents_raw(room);current=td._find_content(contents,content_id)
        if not current:raise ValueError('Content deleted during generation')
        rows=current.setdefault('look_frames',[])
        if not any(r['item_id']==item_id for r in rows):rows.append(row)
        td._write_contents_raw(room,contents)
    return {'ok':True,'asset_id':aid,'path':str(output),'model':model,'elapsed_seconds':saved['elapsed_seconds'],
            'presentation':shown['presentation'],'note':'Saved to the visual conversation, not the timeline. Await the user response before treating this look as adopted.'}
