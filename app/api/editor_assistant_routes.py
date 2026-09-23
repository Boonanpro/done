"""Conversation inside the native editor. No timeline writes outside guarded drafts."""
from __future__ import annotations

import asyncio
import json
import re
import time
import uuid
from datetime import datetime, timezone
from typing import Literal
from pathlib import Path

import httpx
from fastapi import APIRouter, HTTPException, Request
from fastapi.responses import HTMLResponse, Response, StreamingResponse
from pydantic import BaseModel, Field

from app.api.voicelog_routes import _get_user as _cookie_user, _EDITOR_TOOLS, CLIENT_SECRETS_ENDPOINT, REALTIME_MODEL
from app.config import settings
from app.services import timeline_draft as td, timeline_live as tl, timeline_scope as scope
from app.services import editor_workflows as workflows
from app.services import editor_project as project

router = APIRouter(prefix='/editor-assistant', tags=['editor-assistant'])
PAGE = Path(__file__).parents[1] / 'static' / 'editor-assistant.html'


@router.get('/reference-library/media/{ident}')
def reference_library_media(ident: str):
    # Only the explicitly curated public reference corpus is served here.
    from app.services.editor_reference_library import media_path
    from fastapi.responses import FileResponse
    try:
        path = media_path(ident)
    except ValueError:
        raise HTTPException(404, 'Reference not found')
    return FileResponse(path,headers={'Cache-Control':'public, max-age=86400'})


def _get_user(request):
    # Native authentication must not be shadowed by an unrelated localhost cookie.
    auth = request.headers.get('Authorization', '')
    if auth.startswith('Bearer '):
        from app.services.auth_service import decode_access_token
        user = decode_access_token(auth[7:])
        if not user:
            raise HTTPException(401, 'Not authenticated')
        return user
    return _cookie_user(request)


@router.post('/auth')
def auth_status(request: Request):
    _get_user(request)
    return {'ok': True}


class FastPresentationRequest(BaseModel):
    consultation_memo: dict | None = None
    dialogue: list[dict] = Field(default_factory=list, max_length=40)
    items: list[dict] = Field(default_factory=list, max_length=60)
    focus: str | None = None
    pending_reference: dict | None = None
    execution_state: dict | None = None


@router.post('/presentation-action')
async def fast_presentation_action(request: Request, body: FastPresentationRequest):
    user = _get_user(request)
    from app.services.editor_jev import presentation_action
    # Decisions only: this endpoint cannot mutate a timeline or execute code.
    items = [{'id': str(i.get('id', ''))[:100], 'title': str(i.get('title', ''))[:160],
              'kind': str(i.get('kind', ''))[:30], 'group': str(i.get('group', ''))[:100]}
             for i in body.items if i.get('id') and i.get('id') != 'none']
    dialogue = [{'role': r['role'], 'text': str(r.get('text', ''))[:3000]}
                for r in body.dialogue if r.get('role') in ('user', 'assistant')]
    return await presentation_action(user.user_id, dialogue, items, body.focus)


@router.post('/reference-library/decision')
async def reference_library_decision(request: Request, body: FastPresentationRequest):
    from app.services.editor_reference_library import suggest
    user = _get_user(request)
    dialogue=[{'role':r['role'],'text':str(r.get('text',''))[:3000]} for r in body.dialogue if r.get('role') in ('user','assistant')]
    text=next((r['text'] for r in reversed(dialogue) if r['role']=='user'),'')
    if not text.strip():
        return {'handled':False}
    items=[{k:str(i.get(k,''))[:500] for k in ('id','title','kind','source_url','url')} for i in body.items]
    return await suggest(user.user_id,None,None,text[:2000],dialogue,selection_only=True,presentations=items)


@router.post('/visual-decision')
async def visual_decision(request: Request, body: FastPresentationRequest):
    from app.services.editor_visual_decision import decide
    user=_get_user(request)
    dialogue=[{'role':r['role'],'text':str(r.get('text',''))[:3000]} for r in body.dialogue if r.get('role') in ('user','assistant')]
    items=[{**{k:str(i.get(k,''))[:500] for k in ('id','title','kind','library_id','presentation_id','reference_identity')},
            'position':i.get('position') if isinstance(i.get('position'),int) else None,
            'is_latest':i.get('is_latest') is True} for i in body.items if i.get('id')]
    return await decide(user.user_id,dialogue,items,body.focus,include_url_index=True,pending_reference=body.pending_reference,execution_state=body.execution_state,consultation_memo=body.consultation_memo)


class ConsultationUpdateRequest(BaseModel):
    previous: dict | None = None
    changes: list[dict] = Field(default_factory=list,max_length=8)
    reference_agreed: bool | None = None


@router.post('/consultation/update')
def update_consultation(request: Request, body: ConsultationUpdateRequest):
    _get_user(request)
    from app.services.editor_consultation_sheet import update
    try:return update(body.previous,body.changes,body.reference_agreed)
    except ValueError as exc:raise HTTPException(422,str(exc))


class LiveReferenceSearchRequest(BaseModel):
    query: str = Field(min_length=1,max_length=4000)
    scope: str = 'work'
    dialogue: list[dict] = Field(default_factory=list,max_length=40)
    items: list[dict] = Field(default_factory=list,max_length=60)


@router.post('/live/reference-search')
async def live_reference_search(request: Request, body: LiveReferenceSearchRequest):
    user=_get_user(request)
    if body.scope=='work':
        from app.services.reference_url_index import search
        result=await search(user.user_id,body.query,dialogue=body.dialogue,displayed=body.items,
                            embedded=True,routing='genres',verify_matches=True,limit=3)
        return {'available':result['available'],'ids':[r['id'] for r in result['results']],
                'elapsed_ms':result['elapsed_ms'],'failure':result.get('failure')}
    if body.scope=='component':
        from app.services.editor_reference_library import suggest
        result=await suggest(user.user_id,None,None,body.query[:2000],body.dialogue,selection_only=True,presentations=body.items,allow_astra_fallback=False)
        return {'available':result.get('ranking_available',False),'ids':result.get('selected_library_ids',[]),
                'elapsed_ms':result.get('ranking_ms')}
    raise HTTPException(422,'Invalid reference scope')


class RefreshLogin(BaseModel):
    refresh_token: str = Field(min_length=1, max_length=8192)


class LibraryPresentationRequest(BaseModel):
    room_id: str = Field(pattern=r'^[A-Za-z0-9_-]{1,100}$')
    content_id: str = Field(min_length=1, max_length=100)
    ids: list[str] = Field(min_length=1, max_length=3)
    comparison_key: str = Field(min_length=1, max_length=160)


@router.post('/reference-library/present')
async def present_library_selection(request: Request, body: LibraryPresentationRequest):
    _get_user(request)
    from app.services.editor_reference_library import show
    # Reference comparison does not need an editing turn, timeline snapshot,
    # clip selection or a production-agent context. show validates the catalog
    # IDs and persists a content-scoped presentation without editing clips.
    try:
        return await asyncio.to_thread(show,body.room_id,body.content_id,body.ids,body.comparison_key)
    except ValueError as exc:
        raise HTTPException(400,str(exc))


@router.post('/refresh')
def refresh_login(body: RefreshLogin):
    # Auth routes live on the core server; the desktop connects to the sandbox.
    # Validate the same refresh credential here, never an expired access token.
    from app.services.auth_service import refresh_tokens
    pair = refresh_tokens(body.refresh_token)
    if not pair:
        raise HTTPException(401, 'ログインを更新できません。ダン本体からエディターを開き直してください。')
    return {'access_token': pair.access_token, 'refresh_token': pair.refresh_token}


def room_path(room_id):
    if not re.fullmatch(r'[A-Za-z0-9_-]{1,100}', room_id):
        raise HTTPException(400, '部屋の指定が不正です')
    return td._room_dir(room_id)


class Context(BaseModel):
    room_id: str
    content_id: str
    playhead: float = 0
    selected: list[dict] = Field(default_factory=list)
    unsaved: bool = False
    scope_mode: Literal['selected', 'whole'] = 'selected'
    pointer: dict = Field(default_factory=dict)
    visible_targets: list[dict] = Field(default_factory=list)
    target_turn: str | None = None
    previous_turn: str | None = None
    utterance: str = ''
    transcript_item_ids: list[str] = Field(default_factory=list, max_length=200)
    input_mode: Literal['text', 'voice'] = 'text'
    region_selection: dict | None = None
    reference_focus: str | None = None
    observed_views: list[dict] = Field(default_factory=list, max_length=3000)
    viewed_context: dict = Field(default_factory=dict)
    live_dialogue: list[dict] = Field(default_factory=list, max_length=200)
    consultation_memo: dict | None = None
    reference_library: dict | None = None


class ToolRequest(BaseModel):
    room_id: str
    turn_id: str
    name: str
    args: dict = Field(default_factory=dict)


def read_turn(room_id, turn_id, user_id):
    if not re.fullmatch(r'[a-f0-9]{32}', turn_id):
        raise HTTPException(400, '会話の指定が不正です')
    path = room_path(room_id) / 'assistant' / f'{turn_id}.json'
    try:
        turn = json.loads(path.read_text(encoding='utf-8'))
    except FileNotFoundError:
        raise HTTPException(404, '指示の対象を取得し直してください')
    if turn['user_id'] != user_id:
        raise HTTPException(403, 'この会話にはアクセスできません')
    if time.time() - turn['created_at'] > 3600:
        raise HTTPException(409, '指示が古くなりました。もう一度伝えてください')
    if path.with_suffix('.canceled').exists():
        turn['canceled']=True
    return path, turn


def save_json(path, value):
    path.parent.mkdir(parents=True, exist_ok=True)
    tmp = path.with_suffix('.tmp')
    tmp.write_text(json.dumps(value, ensure_ascii=False), encoding='utf-8')
    tmp.replace(path)


@router.get('/page', response_class=HTMLResponse)
def page():
    return HTMLResponse(PAGE.read_text(encoding='utf-8'), headers={
        'Cache-Control': 'no-store',
        'Content-Security-Policy': "default-src 'self'; script-src 'self' 'unsafe-inline' 'wasm-unsafe-eval'; style-src 'self' 'unsafe-inline'; connect-src 'self' https: data:; img-src 'self' data: blob: https:; media-src 'self' blob: https:; worker-src 'self' blob:; frame-src 'self' https://www.youtube-nocookie.com https://player.vimeo.com; frame-ancestors 'none'",
    })


@router.get('/script')
def script():
    import hashlib
    version=hashlib.sha256(b''.join(PAGE.with_name(name).read_bytes() for name in ('editor-assistant.js','editor-live.js','editor-proposals.js','editor-scene.js'))).hexdigest()[:16]
    return Response('window.__danEditorBuild='+json.dumps(version)+';\n'+PAGE.with_suffix('.js').read_text(encoding='utf-8'), media_type='application/javascript',
                    headers={'Cache-Control': 'no-store'})


@router.get('/model-viewer.js')
def model_viewer_script():
    return Response((PAGE.parent/'vendor/model-viewer.min.js').read_bytes(),media_type='application/javascript')


@router.get('/vimeo-player.js')
def vimeo_player_script():
    return Response((PAGE.parent/'vendor/vimeo-player.min.js').read_bytes(),media_type='application/javascript')


@router.get('/scene-vendor/{name}')
def scene_vendor(name: str):
    if name == 'gsap.min.js':
        return Response((PAGE.parent/'vendor/gsap-3.14.2.min.js').read_bytes(),media_type='application/javascript',headers={'Access-Control-Allow-Origin':'*','Cache-Control':'public, max-age=86400'})
    if name not in {'three.module.min.js','three.core.min.js'}:
        raise HTTPException(404)
    return Response((PAGE.parent/'vendor/three-r180'/name).read_bytes(),media_type='application/javascript',headers={'Access-Control-Allow-Origin':'*','Cache-Control':'public, max-age=86400'})


@router.post('/begin')
def begin(request: Request, body: Context):
    user = _get_user(request)
    folder = room_path(body.room_id)
    _, seq = tl.live_sequence(body.room_id, body.content_id)
    if seq is None:
        raise HTTPException(404, '動画を開いてください')
    if body.unsaved:
        raise HTTPException(409, '手編集を保存中です。少し待ってから伝えてください')
    selected = body.selected
    # An empty project has nothing to select or accidentally overwrite. Requiring
    # clip selection here prevented creation and pushed the conversation into a
    # read-only preparation job. Existing projects retain their edit boundaries.
    edit_scope = scope.make_scope(seq, selected) if body.scope_mode == 'selected' and scope.clips(seq) else None
    turn_id = uuid.uuid4().hex
    turn = {'user_id': user.user_id, 'created_at': time.time(), 'context': body.model_dump(),
            'scope': edit_scope, 'sequence_hash': td.sequence_hash(seq), 'edits': []}
    save_json(folder / 'assistant' / f'{turn_id}.json', turn)
    context = workflows.compact_state(body.room_id, body.content_id, body.playhead, selected)
    context.update(room_id=body.room_id, playhead=body.playhead, selected=selected, scope_mode=body.scope_mode,
                   pointer=body.pointer, visible_targets=body.visible_targets,
                    input_mode=body.input_mode, region_selection=body.region_selection, edit_scope=edit_scope,
                    observed_views=body.observed_views, viewed_context=body.viewed_context,live_dialogue=body.live_dialogue,consultation_memo=body.consultation_memo,
                   )
    if body.target_turn:
        _, previous = read_turn(body.room_id, body.target_turn, user.user_id)
        if previous['context']['content_id'] == body.content_id:
            context['proposed_target'] = previous.get('proposal')
    history = []
    prior = body.previous_turn
    seen = {turn_id}
    for _ in range(6):
        if not prior or prior in seen:
            break
        seen.add(prior)
        try:
            _, previous = read_turn(body.room_id, prior, user.user_id)
        except HTTPException:
            break
        pc = previous['context']
        if pc['content_id'] != body.content_id:
            break
        history.append({'utterance': pc.get('utterance', ''), 'playhead': pc.get('playhead'),
                        'selected': pc.get('selected'), 'results': previous.get('results', []),
                        'canceled': previous.get('canceled', False)})
        prior = pc.get('previous_turn')
    context['recent_conversation'] = list(reversed(history))
    for past in history:
        commits = [r for r in past['results'] if r.get('result', {}).get('committed')]
        if commits:
            context['last_actual_edit'] = {'request':past['utterance'],
                'changes':[c for r in commits for c in r['result'].get('changes', [])],
                'note':'前の編集の話ならこちらが対象。現在の画面の選択とは別です。新しい対象への依頼なら現在の画面を使います。'}
            break
    with td.ContentsLock(body.room_id):
        content = td._find_content(td._read_contents_raw(body.room_id), body.content_id)
        context['creative_brief'] = (content or {}).get('creative_brief', {})
        context['presentation'] = (content or {}).get('presentation')
        context['chosen_proposal'] = (content or {}).get('chosen_proposal')
        context['reference_focus'] = body.reference_focus
        if body.reference_library:
            context['reference_library'] = body.reference_library
        context['focused_presentation_item'] = next((i for p in reversed((content or {}).get('proposal_history',[])) for i in p.get('items',[]) if i.get('id')==body.reference_focus),None)
    live = project.current_status(body.room_id,body.content_id)
    context['production'] = {'observed_at':time.time(),'active_count':live['active_count'],
        'active_jobs':[{k:j.get(k) for k in ('id','status','request','question','events')} for j in live['active_jobs']],
        'latest_finished_job':live['latest_finished_job']}
    turn['context'].update(context)
    save_json(folder / 'assistant' / f'{turn_id}.json', turn)
    return {'turn_id': turn_id, 'context': context, 'can_edit': edit_scope is None or bool(edit_scope['clip_ids'])}


@router.get('/proposal-script')
def proposal_script():
    source=PAGE.with_name('editor-scene.js').read_text(encoding='utf-8-sig')+'\n'+PAGE.with_name('editor-proposals.js').read_text(encoding='utf-8-sig')
    return Response(source,media_type='application/javascript',headers={'Cache-Control':'no-store'})


@router.get('/proposal-style')
def proposal_style():
    return Response(PAGE.with_name('editor-proposals.css').read_text(encoding='utf-8-sig'),media_type='text/css',headers={'Cache-Control':'no-store'})


class PresentationHistoryRequest(BaseModel):
    room_id: str
    content_id: str
    before: float | None = None
    limit: int = 12


@router.post('/presentations')
def presentation_history(request: Request, body: PresentationHistoryRequest):
    _get_user(request)
    room_path(body.room_id)
    from app.services.editor_presentation import history
    return history(body.room_id,body.content_id,body.before,body.limit)


class ProjectStatusRequest(BaseModel):
    room_id: str
    content_id: str


@router.post('/project-status')
def project_status(request: Request, body: ProjectStatusRequest):
    _get_user(request)
    room_path(body.room_id)
    return project.status(body.room_id,body.content_id)


class NewContent(BaseModel):
    room_id: str


@router.post('/conversation-projects')
def conversation_projects(request: Request, body: NewContent):
    _get_user(request)
    room_path(body.room_id)
    return {'content_ids': [c['id'] for c in td._read_contents_raw(body.room_id) if c.get('id')]}


class ReferenceInput(BaseModel):
    room_id: str
    content_id: str
    source: str
    present_upload: bool = False


@router.post('/reference')
async def add_reference(request: Request, body: ReferenceInput):
    _get_user(request)
    room_path(body.room_id)
    from app.services import editor_references
    try:
        result = await asyncio.to_thread(editor_references.resolve, body.room_id, body.content_id, body.source)
        if body.present_upload:
            if result['item'].get('asset_id') != body.source:
                raise ValueError('アップロードした素材を指定してください')
            from app.services.editor_presentation import present
            item = {**result['item'], 'note': ''}
            shown = await asyncio.to_thread(present, body.room_id, body.content_id, [item], author='user')
            result['presentation'] = shown['presentation']
        return result
    except (ValueError, httpx.HTTPError) as exc:
        raise HTTPException(400, str(exc))


class ProposalChoice(BaseModel):
    room_id: str
    content_id: str
    item_id: str
    feedback: str = ''


@router.post('/choose')
def choose_proposal(request:Request,body:ProposalChoice):
    _get_user(request)
    room_path(body.room_id)
    from app.services.editor_presentation import choose
    try:return choose(body.room_id,body.content_id,body.item_id,body.feedback)
    except ValueError as e:raise HTTPException(400,str(e))


class AnswerQuestion(BaseModel):
    # Answers do not depend on a mouse position or transient editor selection.
    room_id: str
    content_id: str
    job_id: str
    question_id: str
    text: str = Field(min_length=1,max_length=16000)


@router.post('/answer')
def answer_question(request: Request, body: AnswerQuestion):
    _get_user(request)
    room_path(body.room_id)
    from app.services import editor_questions
    jobs=project.read_json(td._room_dir(body.room_id)/'jobs.json',[])
    job=next((j for j in jobs if j['id']==body.job_id and j.get('content_id')==body.content_id),None)
    if not job:raise HTTPException(404,'回答先が見つかりません')
    try:editor_questions.answer(body.room_id,body.job_id,body.question_id,body.text)
    except ValueError as exc:raise HTTPException(409,str(exc))
    return {'ok':True,'delivery':'running' if job.get('status')=='running' else 'saved',
            'note':'回答を保存しました。担当が終了済みの場合は、残る回答と合わせて次の制作指示へ引き継げます。'}


@router.post('/new')
def new_content(request: Request, body: NewContent):
    _get_user(request)
    folder = room_path(body.room_id)
    if not folder.exists():
        raise HTTPException(404, '制作ルームを開いてください')
    content_id = str(uuid.uuid4())
    now = datetime.now(timezone.utc).isoformat()
    content = {'id': content_id, 'title': '新しい作品', 'room_id': body.room_id,
               'created_at': now, 'updated_at': now,
               'status': 'draft', 'format': '16:9', 'asset_ids': [],
               'timeline': {'format': '16:9', 'sequence': {'duration': 0, 'format': '16:9',
                   'frame_rate': 30, 'tracks': []}}, 'creative_brief': {}}
    with td.ContentsLock(body.room_id):
        contents = td._read_contents_raw(body.room_id)
        contents.insert(0, content)
        td._write_contents_raw(body.room_id, contents)
    return {'ok': True, 'content_id': content_id}


class Approval(Context):
    approved: bool


@router.post('/approval')
def approval(request: Request, body: Approval):
    _get_user(request)
    room_path(body.room_id)
    if body.unsaved:
        raise HTTPException(409, '手編集の保存を待ってください')
    with td.ContentsLock(body.room_id):
        contents = td._read_contents_raw(body.room_id)
        content = td._find_content(contents, body.content_id)
        if content is None:
            raise HTTPException(404, '作品が見つかりません')
        seq = td._content_sequence(content)
        selected = scope.make_scope(seq, body.selected)['clip_ids']
        for cid, (_, clip) in scope.clips(seq).items():
            if cid in selected:
                if body.approved:
                    clip['approved'] = True
                else:
                    clip.pop('approved', None)
        td._write_contents_raw(body.room_id, contents)
    return {'ok': True, 'count': len(selected)}


from app.services.editor_conversation import INSTRUCTIONS as EDITOR_INSTRUCTIONS


def function(name, description, properties, required):
    return {'type': 'function', 'name': name, 'description': description,
            'parameters': {'type': 'object', 'properties': properties, 'required': required}}


from app.services.editor_presentation import ITEM_SCHEMA, DESCRIPTION as PRESENT_DESCRIPTION, REVISE_PROPERTIES, REVISE_DESCRIPTION
from app.services import editor_references
from app.services.editor_direction_library import PLAN_SCHEMA as DIRECTION_PLAN_SCHEMA

EDITOR_TOOLS = list(_EDITOR_TOOLS) + [
    function('read_reference_component','保存済みの動く部品の編集用ソース・調整項目・出典を読む。初回はidのみで一覧、file指定で元コードを取得する。',{'id':{'type':'string'},'file':{'type':'string'}},['id']),
    function('find_direction_patterns','目的・感情・理解に役立つ編集可能な演出部品をJevで推薦する。固定の制作方針や完成品質の保証ではない。',{'request':{'type':'string'}},['request']),
    function('preview_direction_plan','演出部品を会話に合う順序・文言・間で組み、編集可能な動く実物を即時提示する。元タイムラインは変更しない。修正はrevise_presentationの/scene/params/beatsへ。',{'plan':DIRECTION_PLAN_SCHEMA},['plan']),
    function('suggest_reference_examples','確認済みの参考知識庫から会話に合う実物を選び即時提示する。原文も渡される。確信不足なら候補と記述を返すので判断を引き継ぐ。Web検索・生成なし。',{'request':{'type':'string','description':'今比較したいこと。本人の採用・却下条件を変えない。'}},['request']),
    function('present_reference_examples','参考知識庫のIDを1〜3点選んで保存済みの実物を即時表示する。候補がなければ実行せず不足を伝える。',{'ids':{'type':'array','items':{'type':'string'},'minItems':1,'maxItems':3}},['ids']),
    function('import_media','ユーザー指定または取得済みのローカル動画・音声・画像をライブラリに取り込む。asset_idと実測した尺・音声トラック・画像寸法を返す。配置はbatch_editで行う。新規生成や制作担当の起動は不要。',{'path':{'type':'string'},'name':{'type':'string'}},['path']),
    function('editor_help','エディターの表示・保存・操作・提案の仕組みを確認する。自分のUIについて推測する前に読む。',{'topic':{'type':'string','enum':['workflow','proposals','operations']}},[]),
    function('search_references','参考動画を検索して候補情報を返す。まだ画面表示しない。目的に合うものを選びpresent_referencesで提示する。作品例と制作手順解説を区別。最大3検索を並行。',{ 'queries':{'type':'array','items':{'type':'string'},'minItems':1,'maxItems':3}},['queries']),
    function('search_web_references','X・YouTube・作者サイト等を横断して参考作品や制作資料を出典付きで検索。実物はresolve_referenceで取得する。',{'queries':{'type':'array','items':{'type':'string'},'minItems':1,'maxItems':3}},['queries']),
    function('resolve_reference',editor_references.DESCRIPTION,editor_references.SCHEMA,['source']),
    function('read_references','この作品に保存した参考素材を読む。',{'reference_id':{'type':'string'}},[]),
    function('present_references',PRESENT_DESCRIPTION,{'items':{'type':'array','items':ITEM_SCHEMA}},['items']),
    function('revise_presentation',REVISE_DESCRIPTION,REVISE_PROPERTIES,['item_id','changes']),
    function('read_presentations','提示済みの実物を履歴から読む。過去の画像・文字・動画・3D・改訂元をID付きで取得。beforeでさらに遡る。',{'before':{'type':'number'},'limit':{'type':'integer'}},[]),
    function('choose_reference','ユーザーが選んだ提案と好みを保存。次の制作担当へ実物を引き継ぐ。',{'item_id':{'type':'string'},'feedback':{'type':'string'}},['item_id']),
    function('read_editor_context','発言時の再生位置・マウス・選択範囲・作品の方針・以前の編集を読む。画面に関係する依頼で必要なときに使う。',{},[]),
    function('answer_question','制作担当の質問に対するユーザーの回答・条件変更を同じ仕事へ返す。質問への問い返し、雑談、会話への苦情は回答として送らない。',
             {'question_id':{'type':'string'},'text':{'type':'string'}},['question_id','text']),
    function('wait_for_user','返答を必要としない独り言、考え中の発話、雑音には音声を出さず待つ。マイクも制作も止めない。',{},[]),
    function('set_voice_notifications','完了報告も含めて通知しないと明示された時だけpaused=true。余計な説明を止める・黙って待つ依頼はwait_for_user。必要な報告の再開はfalse。',{'paused':{'type':'boolean'}},['paused']),
    function('project_status','進行中・完了した制作、実行モデル、直近の処理記録、残っている依頼を実データで調べる。',{},[]),
    function('stop_production','現在の作品の制作を停止する。job_id省略時はこの作品の進行中の仕事全部。会話だけ黙る場合はwait_for_user。',{'job_id':{'type':'string'}},[]),
    function('edit_history','この作品の実際の編集履歴と変更前後を必要なときに読む。続きはnext_offsetを指定。',{'offset':{'type':'integer','minimum':0}},[]),
    function('export_video','現在のタイムラインを動画として書き出す。制作や修正とは別の処理。依頼されたときに使い、完了はproject_statusで確認。',{},[]),
    function('inspect_range','指定区間の構成・素材・保存済み発話を読む。動きのキー全件が必要なときだけinclude_keyframes=true。',{'start':{'type':'number'},'end':{'type':'number'},'include_keyframes':{'type':'boolean'}},['start','end']),
    function('measure_speech','エディターが実際に再生する音声を指定区間で測定する。字幕の時刻や旧解析が信用できない時に使う。未計測なら時間がかかる。',{'start':{'type':'number'},'end':{'type':'number'}},['start','end']),
    function('asset_image','既存の静止画素材を実際に見る。テイストや配置の検討の参考にする。',{'asset_id':{'type':'string'}},['asset_id']),
    function('update_work','依頼と残作業を作品に記録する。会話の割り込み後も継続する。完了は実行結果を確認してから。',
             {'work_id':{'type':'string'},'title':{'type':'string'},'state':{'type':'string','enum':['pending','running','needs_review','done','blocked','canceled']},'note':{'type':'string'},'job_id':{'type':'string'}},['work_id','title','state']),
    function('resize_captions', '字幕の現在の大きさに倍率を掛ける。少し大きくは1.25、さらに大きくは現在値から増やす。時間・文言は保持。',
             {'clip_ids':{'type':'array','items':{'type':'string'}},'factor':{'type':'number','minimum':0.1,'maximum':4}}, ['clip_ids','factor']),
    function('timeline_state','現在付近の編集要素を確認。別の時刻はt、全体構成が必要なときだけfull=true。',
             {'t':{'type':'number'},'full':{'type':'boolean'},'include_keyframes':{'type':'boolean','description':'動きのキー全件を読む場合だけtrue。省略時は件数と両端の値。'}},[]),
    function('add_music','選んだ既存の音楽素材を全編に配置。声と曲の音量を実測して調整する。',
             {'asset_id':{'type':'string'}},['asset_id']),
    function('set_project_scope', '動画全体への明示的な制作・BGM追加指示を対象にする。承認済みは保護する。',
             {'instruction': {'type':'string'}}, ['instruction']),
    function('list_assets', 'この制作ルームのライブラリ素材を一覧する。タイムラインに未配置の動画・画像・音声も含む。素材の有無や候補を確認する。中身は名前だけで判断せず担当に調査を依頼できる。',
             {'kind':{'type':'string','enum':['audio','music','video','image']},'query':{'type':'string','description':'素材名の部分一致。曲調や用途では絞り込まず一覧を確認する。'}}, []),
    function('edit_captions', '字幕の分割・再区切り・音声同期を一度に行う。元の音声を測定し、指定外と台詞を保持。',
             {'clip_ids':{'type':'array','items':{'type':'string'}},'texts':{'type':'array','items':{'type':'string'}},
              'rewrite':{'type':'boolean'}}, ['clip_ids','texts']),
    function('batch_edit', '複数の映像・音声・効果の操作を一つの変更として反映。途中で失敗したら全て未反映。',
             {'operations':{'type':'array','items':{'type':'object','properties':{'op':{'type':'string'},'args':{'type':'object'}},'required':['op','args']}}}, ['operations']),
    function('resolve_target', '音声指示で対象が明確な場合に編集範囲を結ぶ。確認質問は不要。テキストでは使用不可。',
             {'clip_ids': {'type': 'array', 'items': {'type': 'string'}}}, ['clip_ids']),
    function('propose_target', '修正対象を映像上に囲んで確認する。動画は変更しない。',
             {'clip_ids': {'type': 'array', 'items': {'type': 'string'}},
              'rect': {'type': 'array', 'items': {'type': 'number'}, 'minItems': 4, 'maxItems': 4},
              'start': {'type': 'number'}, 'end': {'type': 'number'},
              'label': {'type': 'string'}}, ['clip_ids', 'rect', 'start', 'end', 'label']),
    function('confirm_target', '前の発話で示した範囲にユーザーが同意した場合だけ、その範囲で編集を可能にする。', {}, []),
    function('editor_view', 'エディターの再生位置を動かして一時停止する。動画を変更しない。',
             {'t': {'type': 'number'}}, ['t']),
    function('save_brief', 'ユーザーと合意した作品の意図・テイスト・参考・制約を保存。未合意の案はproposalsへ。',
             {'intent': {'type': 'string'}, 'taste': {'type': 'string'}, 'references': {'type': 'string'},
              'constraints': {'type': 'string'}, 'proposals': {'type': 'string'}}, []),
    function('delegate_edit', 'Astraへ検索・ブラウザー/PC操作・外部サービスの接続準備・素材調達・生成・動画編集を依頼する。task_kind=prepareなら選択範囲なしで調査や接続準備を実行できる。',
             {'instruction': {'type': 'string'},'task_kind':{'type':'string','enum':['edit','prepare'],'description':'prepareは調査・サービス操作・接続準備。タイムラインは変更しない。省略時はedit。'},'clip_ids':{'type':'array','items':{'type':'string'}},'resume_job_id':{'type':'string','description':'未完了の仕事を保存済み下書きから再開する場合のjob_id。project_statusで確認。'}}, ['instruction']),
]


@router.get('/live/page')
async def live_page():
    html=PAGE.read_text(encoding='utf-8')
    return HTMLResponse(html,headers={'Cache-Control':'no-store'})


@router.get('/live-script')
async def live_script():
    return Response((PAGE.parent/'editor-live.js').read_text(encoding='utf-8'),media_type='application/javascript',headers={'Cache-Control':'no-store'})


class LiveSessionRequest(BaseModel):
    sdp: str = Field(min_length=1, max_length=65536)
    history: list[dict] = Field(default_factory=list, max_length=200)
    client_build: str | None = Field(default=None,max_length=64)


@router.post('/live/session')
async def live_session(request: Request, body: LiveSessionRequest):
    user=_get_user(request)
    if not settings.OPENAI_API_KEY:
        raise HTTPException(503, '音声サービスの接続設定がありません')
    from app.services.editor_live import session_config
    import hashlib
    config=session_config(body.history, EDITOR_TOOLS)
    try:
        async with httpx.AsyncClient(timeout=40) as client:
            response = await client.post('https://api.openai.com/v1/live/sessions',
                headers={'Authorization': f'Bearer {settings.OPENAI_API_KEY}'},
                json={'session': config, 'transport': {'type':'webrtc','sdp':body.sdp}})
    except httpx.RequestError as exc:
        raise HTTPException(502, 'LIVE 1への接続が完了しませんでした。マイクを押して接続し直してください。') from exc
    from app.services.editor_live import parse_session_response
    data=parse_session_response(response)
    return {'session':{'id':data['session']['id']},'transport':data['transport'],'model':'gpt-live-1',
            'runtime':{'client_build':body.client_build,'instructions_hash':hashlib.sha256(config['instructions'].encode()).hexdigest()[:16],
                       'history_hash':hashlib.sha256(json.dumps(config['input'],ensure_ascii=False).encode()).hexdigest()[:16],'history_rows':len(body.history)}}


@router.post('/session')
async def session(request: Request):
    _get_user(request)
    if not settings.OPENAI_API_KEY:
        raise HTTPException(503, '音声サービスの接続設定がありません')
    spec = {'type': 'realtime', 'model': REALTIME_MODEL, 'instructions': 'あなたはダンの音声出力です。読み上げを依頼された文章をそのまま日本語で話します。自分で制作判断やツール操作をせず、内容を追加しません。',
            'max_output_tokens': 4096,
            'truncation': {'type':'retention_ratio','retention_ratio':.7,'token_limits':{'post_instructions':6000}},
            'audio': {'input': {'transcription': {'model': 'gpt-realtime-whisper', 'language': 'ja'},
                                'noise_reduction': {'type': 'near_field'},
                                'turn_detection': {'type': 'semantic_vad', 'eagerness': 'medium', 'create_response': False}},
                      'output': {'voice': 'cedar'}},
            'tools': [], 'reasoning': {'effort': 'high'}}
    async with httpx.AsyncClient(timeout=30) as client:
        response = await client.post(CLIENT_SECRETS_ENDPOINT,
            headers={'Authorization': f'Bearer {settings.OPENAI_API_KEY}'}, json={'session': spec})
    if response.status_code != 200:
        raise HTTPException(502, f'会話に接続できませんでした ({response.status_code})')
    return {'value': response.json().get('value'), 'model': REALTIME_MODEL, 'conversation_model':'gpt-6-astra'}


class ReasonRequest(BaseModel):
    room_id: str
    turn_id: str
    outputs: list[dict] = Field(default_factory=list, max_length=40)
    runtime: dict = Field(default_factory=dict)


class NoticeRequest(BaseModel):
    room_id: str
    content_id: str
    job_id: str
    kind: str = 'completion'
    question_id: str | None = None


@router.post('/notice')
async def notice(request: Request, body: NoticeRequest):
    _get_user(request)
    from app.services import editor_reasoning
    status=await asyncio.to_thread(project.status,body.room_id,body.content_id)
    job=next((j for j in status.get('jobs',[]) if j['id']==body.job_id),None)
    if job is None:raise HTTPException(404,'作業結果が見つかりません')
    dialogue=await asyncio.to_thread(project.dialogue,body.room_id,body.content_id,40)
    text=''
    async for event in editor_reasoning.stream_response([
        *[{'role':m['role'],'content':m['text']} for m in dialogue['messages'] if m.get('role') in {'user','assistant'} and m.get('text')],
        {'role':'user','content':'アプリからの作業通知です。ユーザーの新しい依頼ではありません。直前までの会話の合意と優先順位を守り、今回の変化だけを自然な日本語で一、二文で知らせてください。完了通知では保存結果と残る問題を伝え、古い質問を読み直しません。質問通知でも、後の会話で撤回・延期された質問は繰り返さず現在の作業を伝えます。ツールは使いません。保存と品質の合格を区別してください。\n'+json.dumps({'kind':body.kind,'job':job},ensure_ascii=False)}],[]):
        if event['type']=='text':text+=event['delta']
    return {'text':text,'model':editor_reasoning.MODEL}


@router.post('/reason')
async def reason(request: Request, body: ReasonRequest):
    user=_get_user(request)
    path, saved=read_turn(body.room_id,body.turn_id,user.user_id)
    if saved.get('canceled'):raise HTTPException(409,'この発話は中止されています')
    from app.services import editor_reasoning
    async def events():
        async with _turn_lock(body.room_id,body.turn_id):
            try:
                _, current=read_turn(body.room_id,body.turn_id,user.user_id)
                if current.get('canceled'):return
                state=current.get('reasoning')
                if state is None:
                    if body.outputs:raise ValueError('対応する操作がありません')
                    rows=await asyncio.to_thread(project.dialogue,body.room_id,current['context']['content_id'],60)
                    state={'voice_model':body.runtime.get('voice_model'),'inputs':editor_reasoning.initial_input({**current['context'],'conversation_state':body.runtime},rows['messages']),'pending':[]}
                else:
                    expected={c['call_id'] for c in state.get('pending',[])}
                    supplied=[o.get('call_id') for o in body.outputs]
                    if len(supplied)!=len(set(supplied)) or set(supplied)!=expected:
                        raise ValueError('操作の結果が揃っていません。会話を続けてください。')
                    if not expected:raise ValueError('この応答は完了しています')
                    for o in body.outputs:
                        result=dict(o.get('result',{}))
                        image=result.pop('image',None)
                        state['inputs'].append({'type':'function_call_output','call_id':o['call_id'],
                            'output':json.dumps(result,ensure_ascii=False)})
                        if image:
                            state['inputs'].append({'role':'user','content':[
                                {'type':'input_text','text':'直前の確認ツールが返した実際の画像です。新しい依頼ではありません。'},
                                {'type':'input_image','image_url':image}]})
                async for event in editor_reasoning.stream_response(state['inputs'],editor_reasoning.tools_for_conversation(EDITOR_TOOLS)+([{'type':'web_search'}] if body.runtime.get('voice_model')=='gpt-live-1' else []),live=body.runtime.get('voice_model')=='gpt-live-1',run_key=(body.room_id,body.turn_id)):
                    if await request.is_disconnected():return
                    if path.with_suffix('.canceled').exists():return
                    if event['type']=='completed':
                        state['inputs']+=event['output']
                        reply=''.join(c.get('text','') for o in event['output'] if o.get('type')=='message' for c in o.get('content',[]) if c.get('type')=='output_text')
                        if reply:
                            state['reply_text']=state.get('reply_text','')+reply
                            state['reply_at']=time.time()
                        state['pending']=[o for o in event['output'] if o['type']=='function_call']
                        _,latest=read_turn(body.room_id,body.turn_id,user.user_id)
                        latest['reasoning']=state
                        save_json(path,latest)
                        for call in state['pending']:
                            yield json.dumps({'type':'tool','name':call['name'],'call_id':call['call_id'],
                                'arguments':call['arguments']},ensure_ascii=False)+'\n'
                        yield json.dumps({'type':'done','usage':event['usage'],'has_tools':bool(state['pending']),
                                          'backend':event.get('backend'),'billing':event.get('billing'),'thread_id':event.get('thread_id')})+'\n'
                    else:yield json.dumps(event,ensure_ascii=False)+'\n'
            except Exception as exc:
                yield json.dumps({'type':'error','message':str(exc)},ensure_ascii=False)+'\n'
    return StreamingResponse(events(),media_type='application/x-ndjson',headers={'Cache-Control':'no-store','X-Accel-Buffering':'no'})


@router.post('/tool')
async def tool(request: Request, body: ToolRequest):
    async with _turn_lock(body.room_id, body.turn_id):
        try:
            result = await _tool(request, body)
        except ValueError as exc:
            # Invalid tool arguments are actionable feedback, not an HTML 500
            # that falsely suggests the voice connection needs reopening.
            result = {'ok':False,'error':str(exc)}
        if body.name not in {'timeline_frame','timeline_state','list_assets','read_skill','asset_image','inspect_range','project_status','edit_history','measure_speech'}:
            user = _get_user(request)
            path, turn = read_turn(body.room_id, body.turn_id, user.user_id)
            turn.setdefault('results', []).append({'tool':body.name,'args':body.args,'result':result})
            turn['results'] = turn['results'][-12:]
            save_json(path, turn)
        return result


async def _tool(request: Request, body: ToolRequest):
    user = _get_user(request)
    path, turn = read_turn(body.room_id, body.turn_id, user.user_id)
    ctx, args = turn['context'], body.args
    if body.name == 'set_edit_target':
        target_id=args['content_id']
        _, sequence=tl.live_sequence(body.room_id,target_id)
        updated=workflows.compact_state(body.room_id,target_id,0,[])
        updated.update(room_id=body.room_id,content_id=target_id,playhead=0,selected=[],input_mode=ctx.get('input_mode','voice'),scope_mode='selected',pointer={},visible_targets=[])
        turn['context']=updated
        turn['scope']=scope.make_scope(sequence,[]) if scope.clips(sequence) else None
        turn['sequence_hash']=td.sequence_hash(sequence)
        save_json(path,turn)
        return {'ok':True,'context':updated}
    if body.name=='read_presentations':
        from app.services.editor_presentation import history
        return history(body.room_id,ctx['content_id'],args.get('before'),args.get('limit',12))
    if body.name=='read_conversation':
        return await asyncio.to_thread(project.dialogue,body.room_id,ctx['content_id'],args.get('limit',30),args.get('before'))
    original_dialogue_attached = body.name == 'execute_work'
    if original_dialogue_attached:
        # The conversation authority does not classify the job as preparation.
        # Original speech and references remain available to the execution agent.
        args=dict(args)
        args.pop('task_kind',None)
        rows=await asyncio.to_thread(project.dialogue,body.room_id,ctx['content_id'],60)
        if ctx.get('live_dialogue'):rows={'messages':ctx['live_dialogue']}
        updates=path.with_suffix('.updates.jsonl')
        if updates.exists():
            latest={}
            for line in updates.read_text(encoding='utf-8').splitlines():
                try:
                    update=json.loads(line);latest[update['item_id']]=update
                except (ValueError,KeyError):continue
            rows={'messages':[*rows['messages'],*[{'role':'user','text':u['text'],'observed_views':u.get('observed_views',[])} for u in latest.values()]]}
        # Keep every utterance verbatim, but don't duplicate hundreds of old
        # screen snapshots into every job. The source turn retains those views.
        transcript=[{k:r[k] for k in ('role','text') if k in r} for r in rows['messages']]
        args['instruction']='依頼を達成するまで、必要な調査・接続確認・制作・検品・表示を同じ仕事で続けてください。許可された範囲の確認が済んだら、そのまま実行します。本人の新しい条件を優先し、補足を本人の制約と取り違えないでください。\n作業上の補足: '+str(args.get('instruction',''))+'\n話者付き会話原文:\n'+json.dumps(transcript,ensure_ascii=False)+'\n画面観測を含む元記録（必要時のみ読む）: '+str(path)
        body=ToolRequest(room_id=body.room_id,turn_id=body.turn_id,name='delegate_edit',args=args)
    preparing = body.name == 'delegate_edit' and args.get('task_kind') == 'prepare'
    presentation_only = body.name == 'delegate_edit' and args.get('destination') == 'presentation'
    independent = preparing or presentation_only
    cid = ctx['content_id']
    if body.name=='read_reference_component':
        from app.services.editor_component_library import read
        return await asyncio.to_thread(read,args.get('id'),args.get('file'))
    if body.name in {'find_direction_patterns','preview_direction_plan'}:
        from app.services import editor_direction_library as directions
        if turn.get('canceled') or (body.room_id,body.turn_id) in _canceled_turns:
            return {'ok':False,'canceled':True}
        if body.name=='preview_direction_plan':
            return await asyncio.to_thread(directions.preview,body.room_id,cid,args.get('plan'))
        rows=ctx.get('live_dialogue')
        if rows is None:
            rows=(await asyncio.to_thread(project.dialogue,body.room_id,cid,30))['messages']
        return await directions.search(user.user_id,args.get('request',''),[{k:r[k] for k in ('role','text') if k in r} for r in rows])
    if body.name in {'suggest_reference_examples','present_reference_examples'}:
        from app.services import editor_reference_library as library
        def current():
            return not json.loads(path.read_text(encoding='utf-8')).get('canceled') and (body.room_id,body.turn_id) not in _canceled_turns
        if not current():
            return {'ok':False,'canceled':True}
        if body.name=='present_reference_examples':
            return await asyncio.to_thread(library.show,body.room_id,cid,args.get('ids'),args.get('comparison_key'))
        rows=ctx.get('live_dialogue')
        if rows is None:
            rows=(await asyncio.to_thread(project.dialogue,body.room_id,cid,30))['messages']
        dialogue=[{k:r[k] for k in ('role','text') if k in r} for r in rows]
        saved=td._find_content(td._read_contents_raw(body.room_id),cid)
        items=(saved or {}).get('presentation',{}).get('items',[])
        # Both voice and the production agent search the same full reference
        # index. The legacy component-only scorer cannot satisfy whole works.
        from app.services.editor_visual_decision import decide
        decision=await decide(user.user_id,dialogue,items,include_url_index=True)
        if not current():return {'ok':False,'canceled':True}
        ids=decision.get('selected_library_ids',[])
        if decision.get('action')=='compare' and ids:
            shown=await asyncio.to_thread(library.show,body.room_id,cid,ids)
            return {**shown,'presented':True,'selected_library_ids':ids,'selection_backend':'jev','elapsed_ms':decision.get('elapsed_ms')}
        return {'ok':True,'presented':False,'needs_judgment':True,'decision':decision,
                'note':'No reference was displayed. Preserve the requested scope: a whole-video request must not be replaced with a component.'}
    if body.name=='search_web_references':
        from app.services.editor_reference_search import search_web
        result = await search_web(args.get('queries'))
        from app.services.editor_jev import rank_candidates
        result['ranking'] = await rank_candidates(user.user_id, args.get('queries'), result.get('candidates', []))
        return result
    if body.name in {'resolve_reference','read_references'}:
        if turn.get('canceled') or (body.room_id,body.turn_id) in _canceled_turns:
            return {'ok':False,'canceled':True}
        if body.name == 'resolve_reference':
            return await asyncio.to_thread(editor_references.resolve,body.room_id,cid,args['source'])
        return editor_references.read(body.room_id,cid,args.get('reference_id'))
    if body.name=='editor_help':
        from app.services.editor_help import read
        return read(args.get('topic','workflow'))
    if body.name=='search_references':
        from app.services.editor_reference_search import search
        def current():
            return not json.loads(path.read_text(encoding='utf-8')).get('canceled') and (body.room_id,body.turn_id) not in _canceled_turns
        result = await search(body.room_id,cid,args.get('queries'),current)
        from app.services.editor_jev import rank_candidates
        result['ranking'] = await rank_candidates(user.user_id, args.get('queries'), result.get('candidates', []))
        return result
    if body.name=='choose_reference':
        from app.services.editor_presentation import choose
        return choose(body.room_id,cid,args['item_id'],args.get('feedback',''))
    if body.name=='revise_presentation':
        from app.services.editor_presentation import revise
        return revise(body.room_id,cid,args['item_id'],args['changes'])
    if body.name=='present_references':
        from app.services.editor_presentation import resolve_and_present
        return await resolve_and_present(body.room_id,cid,args.get('items'),
            lambda: not json.loads(path.read_text(encoding='utf-8')).get('canceled')
                and (body.room_id,body.turn_id) not in _canceled_turns)
    if body.name in {'project_status','inspect_range','asset_image','update_work','edit_history','measure_speech'}:
        if body.name == 'update_work' and (turn.get('canceled') or (body.room_id,body.turn_id) in _canceled_turns):
            return {'ok':False,'error':'この発話は中止されています'}
        try:
            if body.name == 'project_status':return await asyncio.to_thread(project.current_status,body.room_id,cid)
            if body.name == 'edit_history':return await asyncio.to_thread(project.history,body.room_id,cid,args.get('offset',0))
            if body.name == 'inspect_range':return await asyncio.to_thread(project.inspect_range,body.room_id,cid,args['start'],args['end'],bool(args.get('include_keyframes',False)))
            if body.name == 'measure_speech':
                project.inspect_range(body.room_id,cid,args['start'],args['end'])
                _,seq=tl.live_sequence(body.room_id,cid)
                words,evidence=await asyncio.to_thread(workflows.measured_words,body.room_id,seq,float(args['start']),float(args['end']))
                return {'ok':True,'words':words,'evidence':evidence}
            if body.name == 'asset_image':return await asyncio.to_thread(project.asset_image,body.room_id,args['asset_id'])
            return project.update_work(body.room_id,cid,args['work_id'],args['title'],args['state'],args.get('note',''),args.get('job_id'))
        except (ValueError,KeyError) as exc:
            return {'ok':False,'error':str(exc)}
    if turn.get('canceled') or (body.room_id,body.turn_id) in _canceled_turns:
        return {'ok': False, 'error': 'ユーザーが割り込みました。この指示の操作は中止されています'}
    if body.name == 'import_media':
        from app.services.editor_media import import_media
        return await asyncio.to_thread(import_media,body.room_id,args['path'],args.get('name',''))
    if body.name == 'stop_production':
        return await asyncio.to_thread(project.stop_production, body.room_id, cid, args.get('job_id'))
    if body.name == 'set_project_scope':
        if ctx.get('input_mode')=='text' and ctx.get('scope_mode')!='whole':
            return {'ok':False,'error':'テキストでは「作品全体を制作」を選んでください'}
        turn['scope']=None
        turn['project_instruction']=str(args.get('instruction',''))
        save_json(path,turn)
        return {'ok':True,'scope':'whole_project','approved_protected':True}
    if body.name == 'list_assets':
        kind=args.get('kind','');query=str(args.get('query','')).lower()
        if kind in {'music','bgm','sound'}:kind='audio'
        items=[]
        for asset in tl._assets(body.room_id).values():
            if kind and asset.get('type',asset.get('kind'))!=kind:continue
            name=asset.get('name') or asset.get('filename','')
            if not Path(asset.get('local_path') or '').is_file():continue
            items.append({'id':asset['id'],'name':name,'kind':asset.get('type',asset.get('kind')),'duration':asset.get('metadata',{}).get('duration'),
                          'likely_speech':bool(re.search(r'narration|nar_|speech|tts|voice|ナレーション',name,re.I))})
        items.sort(key=lambda a:a['likely_speech'])
        matching=[a for a in items if query in a['name'].lower()] if query else items
        fallback=bool(query and not matching)
        if fallback:matching=items
        return {'assets':matching[:60],'has_more':len(matching)>60,
                'note':'素材名に一致しなかったため、利用可能な候補を表示しています。未試聴の曲調は断定しないでください。' if fallback else '曲調は名前だけで断定せず、必要なら試聴・確認してください。'}
    if body.name == 'resolve_target':
        if ctx.get('input_mode') != 'voice':
            return {'ok': False, 'error': 'テキスト指示ではユーザーの明示的な選択範囲を使ってください'}
        _, seq = tl.live_sequence(body.room_id, cid)
        if td.sequence_hash(seq) != turn['sequence_hash']:
            return {'ok': False, 'error': '動画が変わりました。現在の画面で指示し直してください'}
        ids = args.get('clip_ids', [])
        if not ids or any(i not in scope.clips(seq) for i in ids):
            return {'ok': False, 'error': '対象が見つかりません'}
        turn['scope'] = scope.make_scope(seq, ids)
        turn['target_bound'] = True
        ctx['selected'] = [{'id': i} for i in turn['scope']['clip_ids']]
        save_json(path, turn)
        return {'ok': True, 'edit_scope': turn['scope']}
    if body.name == 'editor_view':
        _, seq = tl.live_sequence(body.room_id, cid)
        t = max(0, min(float(args.get('t', 0)), float(seq.get('duration', 0))))
        return {'ok': True, 'editor_action': {'kind': 'seek', 't': t, 'content_id': cid}}
    if body.name == 'propose_target':
        _, seq = tl.live_sequence(body.room_id, cid)
        if td.sequence_hash(seq) != turn['sequence_hash']:
            return {'ok': False, 'error': '画面が変わりました。現在の画面で確認し直してください'}
        ids = args.get('clip_ids', [])
        indexed = scope.clips(seq)
        if not ids or any(i not in indexed for i in ids):
            return {'ok': False, 'error': '対象の要素が見つかりません。timeline_stateで確認してください'}
        rect = args.get('rect', [])
        if len(rect) != 4 or any(not isinstance(n, (int, float)) for n in rect):
            raise HTTPException(400, '範囲の座標が不正です')
        x, y, w, h = rect
        if not (0 <= x < 1 and 0 <= y < 1 and 0 < w <= 1-x+1e-6 and 0 < h <= 1-y+1e-6):
            raise HTTPException(400, '範囲は映像の内側で指定してください')
        start, end = float(args.get('start', 0)), float(args.get('end', 0))
        if not (0 <= start < end <= float(seq.get('duration', 0)) + .001):
            raise HTTPException(400, '時間範囲が不正です')
        if any(indexed[i][1]['timeline_start'] >= end or indexed[i][1]['timeline_end'] <= start for i in ids):
            raise HTTPException(400, '対象と時間範囲が一致していません')
        proposal = {'kind': 'focus', 'content_id': cid, 'clip_ids': ids, 'rect': rect,
                    'start': start, 'end': end, 't': min(max(ctx['playhead'], start), end-.001),
                    'label': str(args.get('label', 'この辺り？'))[:160], 'turn_id': body.turn_id}
        turn['proposal'] = proposal
        save_json(path, turn)
        return {'ok': True, 'editor_action': proposal, 'note': '画面に範囲を表示しました。ユーザーの返答を待ってください'}
    if body.name == 'confirm_target':
        prior = ctx.get('target_turn')
        if not prior or prior == body.turn_id:
            return {'ok': False, 'error': '先に対象を画面に示し、次の発話で確認してください'}
        _, previous = read_turn(body.room_id, prior, user.user_id)
        _, seq = tl.live_sequence(body.room_id, cid)
        proposal = previous.get('proposal')
        if not proposal or proposal['content_id'] != cid or previous['sequence_hash'] != td.sequence_hash(seq):
            return {'ok': False, 'error': '確認中に動画が変わりました。対象を示し直してください'}
        turn['scope'] = scope.make_scope(seq, proposal['clip_ids'])
        turn['scope']['spans'] = [[proposal['start'], proposal['end']]]
        ctx['selected'] = [{'id': i} for i in turn['scope']['clip_ids']]
        turn['proposal'] = proposal
        turn['confirmed'] = True
        turn['target_bound'] = True
        save_json(path, turn)
        return {'ok': True, 'edit_scope': turn['scope'], 'target': proposal}
    if body.name == 'timeline_state':
        result = workflows.compact_state(body.room_id,cid,float(args.get('t',ctx['playhead'])),ctx['selected'],bool(args.get('full',False)),bool(args.get('include_keyframes',False)))
        result.update(playhead=ctx['playhead'], selected=ctx['selected'], edit_scope=turn['scope'])
        return result
    if body.name == 'timeline_frame':
        return await asyncio.to_thread(tl.render_frame_b64, body.room_id, args.get('content_id') or cid, float(args.get('t', turn.get('verify_at', ctx['playhead']))))
    if body.name == 'export_video':
        from fastapi import BackgroundTasks
        from app.api.production_asset_routes import CreateJobRequest, create_job
        content,seq=tl.live_sequence(body.room_id,cid)
        if not seq or not seq.get('tracks'):
            return {'ok':False,'error':'書き出す映像がまだありません'}
        if td.sequence_hash(seq)!=turn['sequence_hash']:
            return {'ok':False,'error':'動画が変更されました。現在の状態から書き出しを依頼してください'}
        bg=BackgroundTasks()
        job=await create_job(CreateJobRequest(room_id=body.room_id,content_id=cid,instruction={'mode':'export','timeline':content['timeline']}),bg,user)
        task=asyncio.create_task(bg());_jobs.add(task);task.add_done_callback(_jobs.discard)
        project.update_work(body.room_id,cid,'job:'+job['id'],'動画を書き出す','running',job_id=job['id'])
        return {'ok':True,'job_id':job['id'],'note':'書き出しを受け付けました。まだ完了していません。'}
    if body.name == 'save_brief':
        from app.services.editor_intent import save_brief
        return save_brief(body.room_id,cid,args)
    if body.name == 'read_skill':
        from app.agent.v2.tools import SkillRegistry
        name = args.get('name')
        if name:
            text=SkillRegistry.get_prompt(name)
            if text:return {'text':text[:22000]}
            # Codex also advertises user-installed skills. Resolve the same
            # named skill here rather than returning a successful empty read.
            parts = name.replace('\\', '/').split('/') if isinstance(name,str) else []
            if parts and parts[0].replace('-','').replace('_','').isalnum() and all(p not in ('', '.', '..') for p in parts):
                for root in (Path.home()/'.agents/skills',Path.home()/'.codex/skills'):
                    package=(root/parts[0]).resolve()
                    candidate=(package.joinpath(*parts[1:]) if len(parts)>1 else package/'SKILL.md').resolve()
                    if candidate.is_relative_to(package) and candidate.suffix.lower()=='.md' and candidate.is_file():
                        return {'text':candidate.read_text(encoding='utf-8-sig')[:22000],'source':str(candidate)}
            return {'ok':False,'error':'指定されたスキルはこの環境にありません','name':name}
        return {'skills': [{'name': s.name, 'description': s.description} for s in SkillRegistry.list_all()]}
    if body.name not in {'timeline_edit', 'delegate_edit','edit_captions','batch_edit','add_music','resize_captions','transform_visuals'}:
        raise HTTPException(400, '未対応の操作です')
    if body.name == 'delegate_edit' and not original_dialogue_attached:
        original=[h.get('utterance','') for h in ctx.get('recent_conversation',[])]
        original.append(ctx.get('utterance',''))
        original=[s for s in original if s]
        args['instruction']=str(args.get('instruction',''))+'\nユーザーの発言（要約で固有名詞・指定条件を落とさない。後の訂正を優先）:\n'+'\n'.join(original)[-16000:]
    if body.name == 'delegate_edit':
        from app.services.timeline_agent import content_busy
        from app.services import editor_job_updates
        active=content_busy(cid)
        if active:
            if presentation_only:
                running=next((j for j in project.read_json(td._room_dir(body.room_id)/'jobs.json',[]) if j.get('id')==active),{})
                if not running.get('instruction',{}).get('presentation_only'):
                    return {'ok':False,'error':'タイムライン制作が進行中です。別の見本はpresent_referencesで直接提示するか、制作の終了後に開始できます。'}
            ids=args.get('clip_ids',[]) if ctx.get('input_mode')=='voice' else [c.get('id') for c in ctx.get('selected',[])]
            _,current=tl.live_sequence(body.room_id,cid)
            if any(i not in scope.clips(current) for i in ids):
                return {'ok':False,'error':'追加指示の対象を現在のタイムラインで確認してください'}
            update=editor_job_updates.submit(body.room_id,active,str(args.get('instruction','')),ids)
            return {'ok':True,'job_id':active,'update_id':update['id'],'state':'instruction_pending',
                    'note':'実行中の制作へ追加指示を保存しました。まだ制作側の受領・反映は確認できていません。別ジョブは開始していません。'}
    # Voice tools already carry the model's explicit referent. Bind it atomically
    # instead of relying on a separate resolve call that can be omitted. Text
    # continues to obey the user's selected scope. Approval/CAS still apply.
    if not independent and ctx.get('input_mode') == 'voice' and turn['scope'] is not None and not turn.get('target_bound'):
        ids = []
        if body.name in {'resize_captions','edit_captions','delegate_edit','transform_visuals'}:
            ids = args.get('clip_ids', [])
        elif body.name == 'timeline_edit':
            clip_id = (args.get('args') or {}).get('clip_id')
            if clip_id:
                ids = [clip_id]
        elif body.name == 'batch_edit':
            ids = [o.get('args', {}).get('clip_id') for o in args.get('operations', [])]
            ids = [i for i in ids if isinstance(i,str) and i]
        if ids:
            _, seq = tl.live_sequence(body.room_id, cid)
            if td.sequence_hash(seq) != turn['sequence_hash']:
                return {'ok':False,'error':'指示後に動画が変わりました。現在の内容を確認してください。'}
            if any(i not in scope.clips(seq) for i in ids):
                return {'ok':False,'error':'対象が見つかりません。timeline_stateで確認してください。'}
            turn['scope'] = scope.make_scope(seq, ids)
            turn['target_bound'] = True
            ctx['selected'] = [{'id':i} for i in ids]
    if ctx.get('input_mode')=='voice' and turn['scope'] is not None and body.name in {'batch_edit','timeline_edit'}:
        from app.services.timeline_operations import addition_spans
        operations=args.get('operations',[]) if body.name=='batch_edit' else [args]
        spans=addition_spans(operations)
        if spans:
            turn['scope']['spans']+=spans
            turn['target_bound']=True
    if not independent and turn['scope'] is not None and not turn['scope']['clip_ids'] and not turn['scope'].get('spans'):
        return {'ok': False, 'error': '音声では明確な対象をresolve_targetで結んでください。曖昧なときだけpropose_targetで確認。テキストでは範囲を選択してください'}
    if body.name == 'delegate_edit':
        from fastapi import BackgroundTasks
        from app.api.production_asset_routes import CreateJobRequest, create_job
        _, seq = tl.live_sequence(body.room_id, cid)
        if not independent and td.sequence_hash(seq) != turn['sequence_hash']:
            return {'ok': False, 'error': '指示後に動画が変わりました。もう一度指示してください'}
        bg = BackgroundTasks()
        instruction = str(args.get('instruction', ''))
        resume_draft=None
        if args.get('resume_job_id'):
            prior=next((j for j in project.read_json(td._room_dir(body.room_id)/'jobs.json',[]) if j['id']==args['resume_job_id'] and j.get('content_id')==cid),None)
            if not prior or prior.get('status') not in {'failed','canceled'}:
                return {'ok':False,'error':'再開対象の未完了作業が見つかりません'}
            from app.services.production_worker import saved_draft
            resume_draft=saved_draft(body.room_id,prior)
            if not resume_draft:return {'ok':False,'error':'この古い作業には再開可能な下書きの記録がありません。生成済み素材を使って残りの編集を依頼できます。'}
            instruction=prior.get('instruction',{}).get('revision_text','')+'\n保存済みの途中成果から再開。最新の追加指示:\n'+instruction
        if ctx.get('region_selection'):
            instruction += '\nユーザーが画面で選択した範囲: ' + json.dumps(ctx['region_selection'], ensure_ascii=False)
        if turn.get('proposal'):
            instruction += '\n合意した修正対象: ' + json.dumps(turn['proposal'], ensure_ascii=False)
        job = await create_job(CreateJobRequest(room_id=body.room_id, content_id=cid, instruction={
            'mode': 'dan_revise', 'revision_text': instruction,
            'selected_clips': ctx['selected'] if not independent and turn['scope'] is not None else [], 'content_id': cid,
            'editor_guarded': True, 'editor_expected_hash': None if independent else turn['sequence_hash'],
            'preparation_only':preparing,
            'presentation_only':presentation_only,
            'resume_draft_id':resume_draft,
        }), bg, user)
        # Keep a task reference until the existing production worker records completion.
        task = asyncio.create_task(bg())
        _jobs.add(task)
        task.add_done_callback(_jobs.discard)
        project.update_work(body.room_id,cid,'job:'+job['id'],instruction[:160],'running',job_id=job['id'])
        return {'ok': True, 'job_id': job['id'], 'note': '編集を受け付けました。結果はパネルに表示されます'}
    try:
        canceled=lambda:(body.room_id,body.turn_id) in _canceled_turns
        if body.name=='transform_visuals':
            result=await asyncio.to_thread(workflows.transform_visuals,body.room_id,cid,args.get('clip_ids',[]),args.get('factor'),args.get('anchor',{}),turn['scope'],turn['sequence_hash'],canceled)
        elif body.name=='resize_captions':
            result=await asyncio.to_thread(workflows.resize_captions,body.room_id,cid,args.get('clip_ids',[]),args.get('factor'),turn['scope'],turn['sequence_hash'],canceled)
        elif body.name=='add_music':
            result=await asyncio.to_thread(workflows.add_music,body.room_id,cid,args.get('asset_id',''),turn['scope'],turn['sequence_hash'],canceled)
        elif body.name=='edit_captions':
            result=await asyncio.to_thread(workflows.edit_captions,body.room_id,cid,args.get('clip_ids',[]),args.get('texts',[]),
                                          bool(args.get('rewrite',False)),turn['scope'],turn['sequence_hash'],canceled)
        elif body.name=='batch_edit':
            result=await asyncio.to_thread(workflows.batch_edit,body.room_id,cid,args.get('operations',[]),turn['scope'],turn['sequence_hash'],canceled)
        else:
            result = await asyncio.to_thread(tl.apply_edit, body.room_id, cid, str(args.get('op', '')),
                                            args.get('args') or {}, turn['scope'], turn['sequence_hash'])
    except (ValueError,KeyError,RuntimeError) as exc:
        return {'ok':False,'error':str(exc)}
    if result.get('committed'):
        turn['sequence_hash'] = result['sequence_hash']
        turn['edits'].append(result['draft_id'])
        spans = [(c.get('start'),c.get('end')) for c in result.get('changes', []) if not c.get('removed')]
        spans = [(a,b) for a,b in spans if a is not None and b is not None and b>a]
        if spans:
            points = [ctx['playhead'] if a<=ctx['playhead']<b else (a+b)/2 for a,b in spans]
            turn['verify_times'] = list(dict.fromkeys(turn.get('verify_times', []) + points))
            turn['verify_at'] = turn['verify_times'][0]
            result['verify_at'] = turn['verify_at']
            result['verify_times'] = turn['verify_times']
        # Newly split clips remain editable in the same utterance.
        if turn['scope'] is not None:
            turn['scope']['clip_ids'] += result.get('new_clip_ids', [])
    save_json(path, turn)
    return result


class EventBatch(BaseModel):
    room_id: str
    session_id: str = Field(pattern=r'^[a-f0-9-]{1,64}$')
    events: list[dict] = Field(max_length=100)


@router.post('/events')
async def events(request:Request,body:EventBatch):
    user=_get_user(request)
    valid_content_ids={c.get('id') for c in td._read_contents_raw(body.room_id)}
    folder=room_path(body.room_id)/'assistant'/'events';folder.mkdir(parents=True,exist_ok=True)
    path=folder/f'{user.user_id}_{body.session_id}.jsonl'
    with path.open('a',encoding='utf-8') as f:
        for event in body.events:
            # A closing browser may flush after deletion. Do not recreate the
            # removed work's transcript from that delayed batch.
            if event.get('content_id') and event['content_id'] not in valid_content_ids:
                continue
            if event.get('type') == 'user_transcript' and event.get('turn_id'):
                try:
                    async with _turn_lock(body.room_id, event['turn_id']):
                        turn_path, saved = read_turn(body.room_id, event['turn_id'], user.user_id)
                        saved['context']['utterance'] = str(event.get('text', ''))[:8000]
                        save_json(turn_path, saved)
                except HTTPException:
                    pass
            row=json.dumps(event,ensure_ascii=False)
            # Conversation is source data, not disposable diagnostic telemetry.
            # Screen history can exceed the old limit during a single sentence.
            if event.get('type') in {'user_transcript','assistant_transcript'} or len(row)<=16000:
                f.write(row+'\n')
    return {'ok':True}


_jobs: set[asyncio.Task] = set()

# Serialize cancellation and writes for each utterance. A canceled turn cannot
# commit a later tool call; an already committed change remains available to Undo.
_turn_locks: dict[tuple[str, str], asyncio.Lock] = {}
_canceled_turns: set[tuple[str,str]] = set()


def _turn_lock(room_id, turn_id):
    key = (room_id, turn_id)
    if len(_turn_locks) > 4096:
        for old in list(_turn_locks):
            if not _turn_locks[old].locked() and old != key:
                del _turn_locks[old]
                if len(_turn_locks) <= 2048:
                    break
    return _turn_locks.setdefault(key, asyncio.Lock())


@router.post('/cancel')
async def cancel(request: Request, body: ToolRequest):
    user = _get_user(request)
    path, turn = read_turn(body.room_id,body.turn_id,user.user_id)
    _canceled_turns.add((body.room_id,body.turn_id))
    path.with_suffix('.canceled').touch()
    from app.services.editor_codex import cancel_pending,cancel_active
    cancel_active((body.room_id,body.turn_id))
    cancel_pending((turn.get('reasoning') or {}).get('pending', []))
    # Cancellation intent is durable immediately. Do not hold a new spoken turn
    # behind an old search/render that still owns its turn lock.
    if _turn_lock(body.room_id, body.turn_id).locked():
        return {'ok':True,'committed_count':len(turn['edits']),'operation_finishing':True}
    async with _turn_lock(body.room_id, body.turn_id):
        path, turn = read_turn(body.room_id, body.turn_id, user.user_id)
        turn['canceled'] = True
        save_json(path, turn)
        return {'ok': True, 'committed_count': len(turn['edits'])}


@router.post('/steer')
async def steer(request: Request, body: ToolRequest):
    user=_get_user(request)
    path,turn=read_turn(body.room_id,body.turn_id,user.user_id)
    if turn.get('canceled'):return {'ok':False,'reason':'canceled'}
    from app.services.editor_codex import steer_active
    text=str(body.args.get('text',''))
    if not text:return {'ok':False,'reason':'empty'}
    # Bypass the tool-turn lock: an update must reach a running model while its
    # response stream owns that lock. This does not grant any new permissions.
    update={'item_id':str(body.args.get('item_id') or uuid.uuid4().hex),'text':text,'observed_views':body.args.get('observed_views',[])}
    delivered=steer_active((body.room_id,body.turn_id),
        '実行中に届いたユーザーの最新の発言原文です。同じitem_idは続きです。途中の発言の場合もあります。訂正・取消なら進め方と回答を更新し、既に実行済みの変更は区別してください。\n'+json.dumps(update,ensure_ascii=False))
    if delivered:
        with path.with_suffix('.updates.jsonl').open('a',encoding='utf-8') as f:
            f.write(json.dumps(update,ensure_ascii=False)+'\n')
    return {'ok':delivered,'state':'forwarded' if delivered else 'not_running'}
