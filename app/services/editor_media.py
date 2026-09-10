"""Room-local media intake usable without starting a production agent."""
import json, os, shutil, subprocess, uuid
from datetime import datetime, timezone
from pathlib import Path
from app.services import timeline_draft as td


def import_media(room_id, path, name='', origin='editor'):
    src=Path(path).expanduser()
    if not src.is_file():return {'ok':False,'error':f'Media file not found: {path}'}
    suffix=src.suffix.lower()
    kind='audio' if suffix in {'.wav','.mp3','.m4a','.aac','.flac','.ogg','.opus'} else 'video' if suffix in {'.mp4','.mov','.mkv','.webm','.m4v'} else 'image' if suffix in {'.png','.jpg','.jpeg','.webp'} else ''
    if not kind:return {'ok':False,'error':'Unsupported media format: '+suffix}
    folder=td._room_dir(room_id);folder.mkdir(parents=True,exist_ok=True)
    aid=uuid.uuid4().hex[:12];dest=folder/f'agent_{aid}{suffix}'
    try:
        shutil.copy2(src,dest)
        if kind=='image':
            from PIL import Image
            with Image.open(dest) as im:
                im.load();meta={'width':im.width,'height':im.height,'duration':0,'has_audio':False,'has_video':False}
        else:
            probe=shutil.which('ffprobe') or next((str(p) for p in [Path('C:/Users/Owner/ffmpeg/bin/ffprobe.exe'),Path('C:/ffmpeg/bin/ffprobe.exe')] if p.is_file()),'ffprobe')
            result=subprocess.run([probe,'-v','error','-show_entries','format=duration:stream=index,codec_type,codec_name,width,height,sample_rate,channels,duration','-of','json',str(dest)],capture_output=True,text=True,timeout=30,creationflags=getattr(subprocess,'CREATE_NO_WINDOW',0))
            result.check_returncode();info=json.loads(result.stdout)
            streams=info.get('streams',[]);video=next((s for s in streams if s.get('codec_type')=='video'),{})
            meta={'duration':float(info.get('format',{}).get('duration') or 0),'streams':streams,
                  'has_audio':any(s.get('codec_type')=='audio' for s in streams),'has_video':bool(video),
                  **{k:video[k] for k in ('width','height') if k in video}}
            if meta['duration']<=0:raise ValueError('Media has no playable duration')
        now=datetime.now(timezone.utc).isoformat()
        row={'id':aid,'room_id':room_id,'kind':kind,'source_type':'agent_workspace','original_uri':str(src.resolve()),
             'local_path':str(dest.resolve()),'filename':name or src.name,'metadata':meta,'status':'ready',
             'created_at':now,'updated_at':now,'generated_by':origin}
        with td.ContentsLock(room_id):
            target=folder/'assets.json';rows=json.loads(target.read_text(encoding='utf-8')) if target.exists() else []
            rows.append(row);tmp=folder/f'assets.{uuid.uuid4().hex}.tmp'
            tmp.write_text(json.dumps(rows,ensure_ascii=False),encoding='utf-8');os.replace(tmp,target)
        return {'ok':True,'asset_id':aid,'kind':kind,'path':str(dest),'metadata':meta,
                'note':'Imported into the library, not placed yet. add_clip with with_audio=true includes linked original audio. Stream presence is not a quality review.'}
    except Exception as exc:
        dest.unlink(missing_ok=True)
        return {'ok':False,'error':str(exc)}
