"""Measured editing workflows on one draft; no intermediate live mutations."""
from __future__ import annotations
import copy
import difflib
import hashlib
import json
import math
import re
import subprocess
import uuid
from pathlib import Path

from app.services import timeline_commands as tc, timeline_draft as td, timeline_live as tl, timeline_scope as scope


def playback_audio_path(room_id,asset):
    # Match native media::mix_timeline_audio / Doc::asset_path exactly. Existing
    # projects can have a proxy whose clock differs from the camera original.
    proxy=td._room_dir(room_id)/(asset['id']+'_proxy.mp4')
    return proxy if proxy.is_file() else Path(asset.get('local_path') or '')


def compact_state(room_id, content_id, playhead=0, selected=(), full=False):
    content, seq = tl.live_sequence(room_id, content_id)
    if seq is None:
        return {'ok': False, 'error': '作品が見つかりません'}
    ids = {c.get('id') if isinstance(c, dict) else c for c in selected}
    clips = []
    for lane, track in enumerate(seq.get('tracks', [])):
        for c in track.get('clips', []):
            if not full and c['id'] not in ids and not (c['timeline_end'] > playhead-6 and c['timeline_start'] < playhead+6):
                continue
            clips.append({**{k:c[k] for k in ('id','text','style','asset_id','timeline_start','timeline_end','source_start','source_end','speed','volume','approved','role',
                                              'grade','position','fit','crop','opacity','muted','video_enabled','transform_keys','region','locked') if k in c},
                          'lane':lane,'kind':track.get('type')})
    return {'content_id':content_id,'title':content.get('title'),'duration':seq.get('duration'),
            'playhead':playhead,'clips':clips[:160 if full else 28], 'has_more':len(clips)>(160 if full else 28)}


def commit(draft, baseline, canceled=None):
    if canceled and canceled():raise ValueError('指示が中止されたため反映していません')
    room_id=draft['room_id']
    if td.sequence_hash(draft['sequence']) == draft['base_hash']:
        td.discard_draft(room_id,draft['draft_id'],lambda *_:None)
        return {'ok':False,'changed':False,'committed':False,'error':'変更前と同じ状態です。変更は保存されていません。'}
    td.save_draft(draft)
    result=td.commit_draft(room_id,draft['draft_id'],lambda seq,rid:[p for p in tc.validate_sequence(seq,tl._assets(rid),asset_dir=str(td._room_dir(rid))) if p not in baseline])
    if not result.get('ok'):
        td.discard_draft(room_id,draft['draft_id'],lambda *_:None)
        return {'ok':False,'error':'; '.join(result.get('problems',[]))}
    old=scope.clips(draft['base_sequence']);new=scope.clips(draft['sequence'])
    return {'ok':True,'committed':True,'draft_id':draft['draft_id'],'sequence_hash':td.sequence_hash(draft['sequence']),
            'changed':True,'changes':tl.describe_changes(draft['base_sequence'],draft['sequence']),
            'new_clip_ids':list(new.keys()-old.keys()),'changed_clip_ids':[i for i in new if new[i]!=old.get(i)]}


def resize_captions(room_id, content_id, clip_ids, factor, edit_scope, expected_hash, canceled=None):
    factor = float(factor)
    if not math.isfinite(factor) or not 0.1 <= factor <= 4 or factor == 1:
        raise ValueError('倍率は0.1〜4の、1以外の数値で指定してください')
    _, seq = tl.live_sequence(room_id, content_id)
    indexed = scope.clips(seq)
    operations = []
    if not clip_ids:
        raise ValueError('対象の字幕を指定してください')
    for cid in dict.fromkeys(clip_ids):
        c = indexed.get(cid, (None, {}))[1]
        if 'text' not in c:
            raise ValueError('対象の字幕が見つかりません')
        size = float((c.get('style') or {}).get('fontSize', 1))
        if size > 8:
            size /= 64
        new_size = round(size * factor, 6)
        if not math.isfinite(new_size) or not 0 < new_size <= 3:
            raise ValueError('字幕サイズの範囲を超えます。小さい倍率で指定してください')
        operations.append({'op':'set_clip','args':{'clip_id':cid,'style':{'fontSize':new_size}}})
    return batch_edit(room_id, content_id, operations, edit_scope, expected_hash, canceled)


def draft_for(room_id,content_id,edit_scope,expected_hash):
    d=td.create_draft(room_id,content_id,job_id='editor_workflow')
    if d['base_hash']!=expected_hash:
        td.discard_draft(room_id,d['draft_id'],lambda *_:None)
        raise ValueError('指示後に動画が変わりました。現在の画面で指示し直してください')
    if edit_scope is not None:d['edit_scope']=edit_scope
    baseline=set(tc.validate_sequence(d['sequence'],tl._assets(room_id),asset_dir=str(td._room_dir(room_id))))
    return d,baseline


def batch_edit(room_id,content_id,operations,edit_scope,expected_hash,canceled=None):
    d,baseline=draft_for(room_id,content_id,edit_scope,expected_hash)
    try:
        if not 1<=len(operations)<=20:raise ValueError('一括編集は1〜20操作で指定してください')
        from app.services.timeline_operations import resolve_results
        results=[]
        for operation in operations:
            op=operation['op'];args=resolve_results(operation.get('args',{}),results)
            if op in {'add_clip','add_caption','add_region'} and args.get('lane')=='front':
                args={**args,'lane':len(d['sequence'].get('tracks',[]))}
            if op not in tl.FAST_OPS:raise ValueError('未対応の操作: '+op)
            fn=getattr(tc,op)
            if op=='split_clip' and isinstance(args.get('at'),list):
                from app.services.timeline_operations import split_at_times
                result=split_at_times(d['sequence'],args['clip_id'],args['at'])
            else:
                result=fn(d['sequence'],**args) if op in {'remove_clip','move_clip','split_clip','set_clip','set_region','add_region','add_caption'} else fn(d['sequence'],tl._assets(room_id),**args)
            if not result.get('ok'):raise ValueError(str(result))
            results.append(result)
            d['log'].append({'tool':op,'args':args})
        return {**commit(d,baseline,canceled),'results':results}
    except Exception:
        td.discard_draft(room_id,d['draft_id'],lambda *_:None)
        raise


def measured_words(room_id,seq,start,end):
    """Source word timestamps mapped through source_start/speed onto the timeline."""
    from app.services import timeline_captions as cap
    assets=tl._assets(room_id); words=[]; evidence=[]
    for c in cap.speech_clips(seq):
        ts,te=c['timeline_start'],c['timeline_end']
        if te<=start or ts>=end:continue
        lo,hi=max(ts,start-1),min(te,end+1)
        if hi<=lo:continue
        asset=assets[c['asset_id']];src=playback_audio_path(room_id,asset)
        if not src.is_file():raise ValueError('元音声が見つかりません')
        speed=float(c.get('speed',1));ss=float(c.get('source_start',0))
        source_lo=ss+(lo-ts)*speed; source_hi=ss+(hi-ts)*speed
        key=hashlib.sha256(f'{src.resolve()}|{src.stat().st_mtime_ns}|{source_lo:.4f}|{source_hi:.4f}'.encode()).hexdigest()[:24]
        folder=td._room_dir(room_id)/'assistant'/'audio-analysis';folder.mkdir(parents=True,exist_ok=True)
        cache=folder/(key+'.json')
        if cache.exists(): raw=json.loads(cache.read_text(encoding='utf-8'))
        else:
            # Analysis scratch only. The timeline continues to reference the original media.
            wav=folder/(key+'.wav')
            subprocess.run([cap._ffmpeg(),'-nostdin','-y','-v','error','-ss',str(source_lo),'-t',str(source_hi-source_lo),'-i',str(src),
                            '-vn','-ac','1','-ar','16000',str(wav)],check=True,capture_output=True,timeout=60,
                           creationflags=getattr(subprocess,'CREATE_NO_WINDOW',0))
            raw=cap.transcribe_words(wav,model='whisper-1')
            cache.write_text(json.dumps(raw,ensure_ascii=False),encoding='utf-8')
        words.extend((lo+a/speed,lo+b/speed,w) for a,b,w in raw)
        evidence.append({'asset_id':c['asset_id'],'source_range':[source_lo,source_hi],'cache':key})
    if not words:raise ValueError('この範囲で音声を測定できませんでした。時刻は推測で変更していません')
    return sorted(words),evidence


def caption_boundaries(words,texts,start,end,fps=30):
    from app.services.timeline_captions import _norm
    target=''.join(_norm(t) for t in texts);spoken='';times=[]
    for a,b,w in words:
        n=_norm(w)
        spoken+=n;times.extend(a+(b-a)*i/max(1,len(n)) for i in range(len(n)))
    matcher=difflib.SequenceMatcher(None,target,spoken,autojunk=False)
    mapped={}
    for block in matcher.get_matching_blocks():
        for k in range(block.size):mapped[block.a+k]=times[block.b+k]
    confidence=len(mapped)/max(1,len(target))
    if confidence<.8:raise ValueError(f'台詞と音声の一致が不足しています（一致率{confidence:.0%}）。変更せず確認が必要です')
    edges=[start];pos=0
    for text in texts[:-1]:
        pos+=len(_norm(text))
        candidates=[i for i in range(pos,min(len(target),pos+3)) if i in mapped]
        if not candidates:raise ValueError('指定された字幕境界の発話を特定できませんでした')
        t=round(mapped[candidates[0]]*fps)/fps
        if t<=edges[-1]+.1 or t>=end-.1:raise ValueError('字幕境界が不自然なため変更を止めました')
        edges.append(t)
    return edges+[end],confidence


def edit_captions(room_id,content_id,clip_ids,texts,rewrite,edit_scope,expected_hash,canceled=None):
    from app.services.timeline_captions import _norm
    d,baseline=draft_for(room_id,content_id,edit_scope,expected_hash)
    try:
        indexed=scope.clips(d['sequence'])
        if edit_scope is not None and not set(clip_ids)<=set(edit_scope['clip_ids']):raise ValueError('選択範囲外の字幕は変更できません')
        clips=sorted([indexed[i][1] for i in clip_ids],key=lambda c:c['timeline_start'])
        if not clips or any(not c.get('text') or c.get('asset_id') for c in clips):raise ValueError('字幕を指定してください')
        if len({indexed[i][0] for i in clip_ids})!=1:raise ValueError('同じレーンの連続した字幕を指定してください')
        if not texts or any(not t.strip() for t in texts):raise ValueError('分割後の字幕を省略せず指定してください')
        if not rewrite and _norm(''.join(c['text'] for c in clips))!=_norm(''.join(texts)):
            raise ValueError('分割・移動の指示では台詞を省略・追加できません。元の全文を保持してください')
        start,end=clips[0]['timeline_start'],clips[-1]['timeline_end']
        lane=indexed[clip_ids[0]][0]
        if any(tid==lane and c['id'] not in clip_ids and c['timeline_start']<end and c['timeline_end']>start
               for tid,c in indexed.values()):raise ValueError('間の字幕を飛ばさず、連続した範囲を指定してください')
        if rewrite and len(clips)==len(texts)==1:
            # A wording-only change has no new boundary to align.
            edges,confidence,evidence=[start,end],None,[]
        else:
            words,evidence=measured_words(room_id,d['sequence'],start,end)
            edges,confidence=caption_boundaries(words,texts,start,end,float(d['sequence'].get('frame_rate',30)))
        track=next(t for t in d['sequence']['tracks'] if str(t.get('id'))==indexed[clip_ids[0]][0])
        replacements=[]
        for i,text in enumerate(texts):
            clip=copy.deepcopy(clips[min(i,len(clips)-1)])
            if i>=len(clips):clip['id']='caption_'+uuid.uuid4().hex[:12]
            clip.update(text=text,timeline_start=edges[i],timeline_end=edges[i+1]);replacements.append(clip)
        track['clips']=[c for c in track['clips'] if c['id'] not in clip_ids]+replacements
        track['clips'].sort(key=lambda c:c['timeline_start'])
        d['log'].append({'tool':'edit_captions','args':{'clip_ids':clip_ids,'texts':texts},'measurement':{'confidence':confidence,'boundaries':edges,'sources':evidence}})
        result=commit(d,baseline,canceled)
        result.update(captions=[{k:c[k] for k in ('id','text','timeline_start','timeline_end')} for c in replacements],
                      verification={'audio_alignment':'measured_word_timestamps' if evidence else 'unchanged_wording_only','confidence':confidence,'boundaries':edges})
        return result
    except Exception:
        td.discard_draft(room_id,d['draft_id'],lambda *_:None)
        raise


def mean_level(path,start=0,duration=15):
    from app.services.timeline_captions import _ffmpeg
    r=subprocess.run([_ffmpeg(),'-nostdin','-hide_banner','-ss',str(start),'-t',str(duration),'-i',str(path),
                      '-vn','-af','volumedetect','-f','null','-'],capture_output=True,text=True,encoding='utf-8',errors='replace',timeout=60,
                     creationflags=getattr(subprocess,'CREATE_NO_WINDOW',0))
    match=re.search(r'mean_volume:\s*([\-\d.]+) dB',r.stderr)
    if r.returncode or not match:raise ValueError('音量を測定できませんでした')
    return float(match[1])


def add_music(room_id,content_id,asset_id,edit_scope,expected_hash,canceled=None):
    """Place a source reference and measure a conservative bed below dialogue."""
    from app.services.timeline_captions import speech_clips
    d,baseline=draft_for(room_id,content_id,edit_scope,expected_hash)
    try:
        if edit_scope is not None:raise ValueError('BGMを全編へ追加する指示は、先に動画全体を対象にしてください')
        assets=tl._assets(room_id);asset=assets[asset_id]
        src=playback_audio_path(room_id,asset)
        if not src.is_file():raise ValueError('BGMの元ファイルが見つかりません')
        if any(c.get('role') in {'music','bgm'} for t in d['sequence']['tracks'] for c in t['clips']):
            raise ValueError('既にBGMがあります。重ねずに既存BGMの差し替え・音量調整を指定してください')
        length=float(asset.get('metadata',{}).get('duration',0))
        duration=float(d['sequence'].get('duration',0))
        if length<=0 or duration<=0:raise ValueError('素材または動画の長さを確認できません')
        music_db=mean_level(src,0,min(20,length))
        speech=speech_clips(d['sequence'])
        levels=[]
        for c in speech[:3]:
            db=mean_level(playback_audio_path(room_id,assets[c['asset_id']]),float(c.get('source_start',0)),min(15,c['timeline_end']-c['timeline_start']))
            levels.append(db+20*math.log10(max(.001,float(c.get('volume',1)))))
        speech_db=sum(levels)/len(levels) if levels else None
        target=(speech_db-18) if speech_db is not None else -24
        volume=round(min(1.0,10**((target-music_db)/20)),4)
        at=0;ids=[]
        while at<duration-.01:
            result=tc.add_audio(d['sequence'],assets,asset_id=asset_id,source_start=0,duration=min(length,duration-at),at=at,volume=volume,role='music')
            if not result.get('ok'):raise ValueError(str(result))
            ids.append(result['clip_id']);at=result['timeline_end']
        verification={'music_mean_db':music_db,'speech_sample_mean_db':speech_db,'volume':volume,
                      'note':'音声サンプルとの音量差を実測。曲調や全編の聴感は再生確認が必要'}
        d['log'].append({'tool':'add_music','args':{'asset_id':asset_id},'measurement':verification})
        result=commit(d,baseline,canceled);result.update(verification=verification,clip_ids=ids)
        return result
    except Exception:
        td.discard_draft(room_id,d['draft_id'],lambda *_:None)
        raise
