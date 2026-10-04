"""Durable, revisioned story/scene decisions shared by conversation and production."""
from copy import deepcopy
import json
import time
from app.services import timeline_draft as td


def empty():
    return {'revision': 0, 'story': '', 'story_status': 'unknown', 'scenes': [], 'decisions': []}


def read(room, content_id):
    content = td._find_content(td._read_contents_raw(room), content_id)
    if content is None:
        raise ValueError('作品が見つかりません')
    return deepcopy(content.get('film_plan') or empty())


def update(room, content_id, base_revision, changes, evidence):
    if not isinstance(evidence, str) or not evidence.strip() or len(evidence) > 2000:
        raise ValueError('今回の変更理由またはユーザーの発言が必要です')
    if not isinstance(changes, list) or not 1 <= len(changes) <= 30:
        raise ValueError('変更は1〜30件です')
    if any(not isinstance(c,dict) for c in changes):
        raise ValueError('変更はオブジェクトで指定してください')
    with td.ContentsLock(room):
        contents = td._read_contents_raw(room)
        content = td._find_content(contents, content_id)
        if content is None:
            raise ValueError('作品が見つかりません')
        plan = deepcopy(content.get('film_plan') or empty())
        if base_revision != plan['revision']:
            raise ValueError('制作案が更新されています。現在の案を読んで変更してください')
        known = {i['id'] for p in content.get('proposal_history', []) + [content.get('presentation', {})]
                 for i in p.get('items', [])}
        for change in changes:
            op = change.get('op')
            if op == 'story':
                value = change.get('text')
                if not isinstance(value, str) or not value.strip() or len(value) > 6000:
                    raise ValueError('物語案は1〜6000文字です')
                if value != plan['story']:
                    plan['story_status'] = 'proposed'
                plan['story'] = value
            elif op == 'story_status':
                if not plan['story'] or change.get('status') not in ('proposed', 'agreed'):
                    raise ValueError('物語案と有効な合意状態が必要です')
                plan['story_status'] = change['status']
            elif op == 'scene':
                ident = change.get('id')
                if not isinstance(ident, str) or not ident or len(ident) > 100:
                    raise ValueError('場面IDが必要です')
                scene = next((s for s in plan['scenes'] if s['id'] == ident), None)
                if scene is None:
                    scene = {'id': ident, 'title': '', 'action': '', 'dialogue': '', 'camera': '',
                             'sound': '', 'duration': 10, 'visual_ids': [], 'status': 'proposed'}
                    plan['scenes'].append(scene)
                previous = deepcopy(scene)
                for key in ('title', 'action', 'dialogue', 'camera', 'sound'):
                    if key in change:
                        if not isinstance(change[key], str) or len(change[key]) > 4000:
                            raise ValueError('場面の記述が不正です')
                        scene[key] = change[key]
                if 'duration' in change:
                    value = change['duration']
                    if isinstance(value, bool) or not isinstance(value, (float, int)) or not 0 < value <= 600:
                        raise ValueError('場面の長さは0秒より長く600秒以下です')
                    scene['duration'] = value
                if 'visual_ids' in change:
                    ids = change['visual_ids']
                    if not isinstance(ids, list) or len(ids) > 20 or any(not isinstance(i,str) or i not in known for i in ids):
                        raise ValueError('この作品で提示した実物のIDを指定してください')
                    scene['visual_ids'] = list(dict.fromkeys(ids))
                if scene != previous:
                    scene['status'] = 'proposed'
                if 'status' in change:
                    if change['status'] not in ('proposed', 'agreed'):
                        raise ValueError('場面の合意状態が不正です')
                    scene['status'] = change['status']
            elif op == 'remove_scene':
                if not any(s['id'] == change.get('id') for s in plan['scenes']):
                    raise ValueError('削除する場面が見つかりません')
                plan['scenes'] = [s for s in plan['scenes'] if s['id'] != change['id']]
            elif op == 'order':
                ids = change.get('ids')
                if not isinstance(ids, list) or any(not isinstance(i,str) for i in ids) or len(ids) != len(plan['scenes']) or set(ids) != {s['id'] for s in plan['scenes']}:
                    raise ValueError('全場面を重複なく並べてください')
                by_id = {s['id']: s for s in plan['scenes']}
                plan['scenes'] = [by_id[i] for i in ids]
            else:
                raise ValueError('未対応の制作案変更です')
        if len(plan['scenes']) > 1000:
            raise ValueError('場面数が多すぎます')
        plan['revision'] += 1
        plan['decisions'] = (plan['decisions'] + [{'revision': plan['revision'], 'at': time.time(),
                                                'evidence': evidence, 'changes': deepcopy(changes)}])[-100:]
        content['film_plan'] = plan
        td._write_contents_raw(room, contents)
    return deepcopy(plan)


def production_context(room, content_id):
    plan = read(room, content_id)
    return json.dumps({k: v for k, v in plan.items() if k != 'decisions'}, ensure_ascii=False)


def place_scene(room,content_id,scene_id,item_id,start=None):
    """Publish an editable scene into a normal video lane using timeline CAS."""
    import math
    from app.services import timeline_commands as tc
    content=td._find_content(td._read_contents_raw(room),content_id)
    if content is None:raise ValueError('作品が見つかりません')
    scene=next((s for s in content.get('film_plan',{}).get('scenes',[]) if s['id']==scene_id),None)
    if not scene:raise ValueError('制作案に場面を保存してください')
    item=next((i for p in reversed(content.get('proposal_history',[])) for i in p.get('items',[]) if i['id']==item_id),None)
    if not item or item.get('kind')!='scene':raise ValueError('編集可能なsceneの見本を指定してください')
    draft=td.create_draft(room,content_id)
    seq=draft['sequence'];tracks=seq.setdefault('tracks',[])
    found=next(((tr,c) for tr in tracks for c in tr.get('clips',[]) if c.get('film_scene_id')==scene_id),None)
    if found:
        track,clip=found
        if track.get('locked') or clip.get('approved'):raise ValueError('この場面はロックされています')
        if start is not None:raise ValueError('既存場面の配置は保持します。移動は通常の編集操作を使ってください')
    else:
        if start is None:start=max((c.get('timeline_end',0) for tr in tracks for c in tr.get('clips',[])),default=0)
        if isinstance(start,bool) or not isinstance(start,(int,float)) or not math.isfinite(start) or start<0:raise ValueError('開始位置が不正です')
        track=next((tr for tr in tracks if tr.get('id')=='film-scenes'),None)
        if track and track.get('locked'):raise ValueError('配置先のレーンはロックされています')
        if track is None:
            track={'id':'film-scenes','type':'video','clips':[]};tracks.append(track)
        import uuid
        clip={'id':'scene-'+uuid.uuid4().hex[:12],'film_scene_id':scene_id,'timeline_start':start,
              'timeline_end':start+scene['duration']}
        track['clips'].append(clip)
    clip.update(scene=deepcopy(item['scene']),presentation_item_id=item_id,label=scene['title'] or scene_id)
    seq['duration']=max((c.get('timeline_end',0) for tr in tracks for c in tr.get('clips',[])),default=0)
    assets_path=td._room_dir(room)/'assets.json'
    assets={a['id']:a for a in json.loads(assets_path.read_text(encoding='utf-8'))} if assets_path.exists() else {}
    baseline=set(tc.validate_sequence(draft['base_sequence'],assets))
    td.save_draft(draft)
    result=td.commit_draft(room,draft['draft_id'],lambda s,r:[p for p in tc.validate_sequence(s,assets) if p not in baseline])
    return {**result,'clip_id':clip['id'],'draft_id':draft['draft_id'],'editable':True}


def link_visual_revision(room,content_id,old_id,new_id):
    """Only scenes still referring to the original follow its explicit revision."""
    with td.ContentsLock(room):
        contents=td._read_contents_raw(room)
        content=td._find_content(contents,content_id)
        if content is None:raise ValueError('作品が見つかりません')
        plan=content.get('film_plan')
        if not plan:return empty()
        touched=[]
        for scene in plan['scenes']:
            if old_id in scene.get('visual_ids',[]):
                scene['visual_ids']=[new_id if i==old_id else i for i in scene['visual_ids']]
                scene['status']='proposed';touched.append(scene['id'])
        if touched:
            plan['revision']+=1
            plan['decisions']=(plan['decisions']+[{'revision':plan['revision'],'at':time.time(),
                'evidence':'指定された見本の部分修正','visual_revision':{'from':old_id,'to':new_id,'scenes':touched}}])[-100:]
            td._write_contents_raw(room,contents)
        return deepcopy(plan)


INSTRUCTIONS = '''映画・物語の制作相談:
シート完成は脚本や演出の完成ではありません。get_consultation_stateのfilm_planを読み、既存の物語案と場面を引き継ぎます。展開がまだ不明なら「考えている展開はありますか？ 未定なら提案します」程度に聞きます。既に展開を話していたら聞き直しません。
update_film_planで短い物語案と場面別の演出を保存します。ユーザーの事実と自分の提案を区別し、提案はproposed、会話で了承された時だけagreed。台本を8項目のシートに詰め込まず、この制作案に記録します。場面のIDを保ち、変更された場面だけ更新します。
人物や舞台の見た目が判断に必要なら完成イメージ画像を提案・制作し、実際に表示されたIDを該当場面のvisual_idsへ記録します。構成や構図はshow_consultation_visualで実物を見せ、動きの試作は編集可能なsceneで示せます。revise_consultation_visualで指定した部分だけ直します。提案の保存と実物の表示は別なので、保存だけで見せたと報告しません。
revise_consultation_visualは該当場面のvisual_idsも更新して最新film_planを返します。見本IDの付け替えだけのためにupdate_film_planを重ねる必要はありません。場面の意味や台詞も変わった場合だけ追加で記録します。
タイムラインで見たい、下書きに配置したいという依頼には、場面に対応するsceneをplace_film_sceneで通常の映像レーンに配置します。初回は指定位置または既存クリップの後ろ、以後は同じ場面IDのクリップをその位置・尺のまま更新します。タイムラインへ配置済みの場面を修正したら、新しい見本IDでplace_film_sceneも呼び、タイムラインへ反映できた結果を確認します。
場面のactionは具体的な行動・反応・間、cameraは構図と動き、dialogueは台詞、soundは音です。必要に応じて埋め、空欄を無関係な定型表現で埋めません。主人公の見た目、色、演技、間を動画モデル任せにしません。
制作依頼には対象場面IDと今回の目的を指定し、採用した物語・実物・未定事項を引き継ぎます。過去の停止済みジョブは制作案ではありません。再開という言葉だけで古い長編生成を復活させず、最新の相談に基づく範囲で進めます。操作できるコンテの依頼を、再生しかできないMP4で代用しません。現状の道具で作れない部分はそのまま説明し、できたとは報告しません。
'''


def tools():
    return [{'type':'function','name':'place_film_scene','strict':False,
             'description':'表示した編集可能な3D/sceneを通常タイムラインへ配置する。既存の同じ場面は位置・長さを保って更新。他のクリップは変更しない。',
             'parameters':{'type':'object','properties':{'scene_id':{'type':'string'},'item_id':{'type':'string'},'start':{'type':'number','minimum':0}},'required':['scene_id','item_id'],'additionalProperties':False}},
            {'type': 'function', 'name': 'update_film_plan', 'strict': False,
             'description': 'この作品の物語・場面別演出を差分保存。生成や承認は自動ではない。変更後の全体を返す。',
             'parameters': {'type': 'object', 'properties': {
                 'base_revision': {'type': 'integer'}, 'evidence': {'type': 'string'},
                 'changes': {'type': 'array', 'minItems': 1, 'maxItems': 30, 'items': {
                     'type': 'object', 'properties': {
                         'op': {'type': 'string', 'enum': ['story', 'story_status', 'scene', 'remove_scene', 'order']},
                         **{k: {'type': 'string'} for k in ('id', 'text', 'title', 'action', 'camera', 'dialogue', 'sound')},
                         'status': {'type': 'string', 'enum': ['proposed', 'agreed']},
                         'duration': {'type': 'number'},
                         'visual_ids': {'type': 'array', 'items': {'type': 'string'}},
                         'ids': {'type': 'array', 'items': {'type': 'string'}}},
                     'required': ['op'], 'additionalProperties': False}}},
                 'required': ['base_revision', 'evidence', 'changes'], 'additionalProperties': False}}]
