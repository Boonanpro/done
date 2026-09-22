"""チャット統合音声モード（V1）のバックエンド。

  POST /api/v1/voicelog/session      — チャット用 gpt-realtime セッションの ephemeral トークン発行
  POST /api/v1/voicelog/{room_id}    — 音声会話の文字起こしを部屋の履歴に保存

音声そのものはブラウザ ↔ OpenAI の WebRTC 直結。ここはトークン発行と
「会話をチャットログに残す」だけを担う。文字起こしを chat_messages に保存する
ことで、ダン（CLI）が後のターンで音声会話を文脈として読める＝部屋が共有記憶になる。

サンドボックス側に置く理由: 反映が sandbox restart だけで済む（コアは不変の原則）。
next.config の rewrites では /api/v1/voicelog/* は既定でサンドボックス(8000)に届く。
"""
from __future__ import annotations

import logging
from typing import Optional, Literal
from datetime import datetime

import httpx
from fastapi import APIRouter, HTTPException, Request
from pydantic import BaseModel, Field

from app.config import settings
from app.services.auth_service import TokenData, decode_access_token
from app.api.atom_relay_routes import router as atom_relay_router
from app.services.chat_service import ChatService

logger = logging.getLogger(__name__)

router = APIRouter(prefix="/voicelog", tags=["voice-mode"])
router.include_router(atom_relay_router)

CLIENT_SECRETS_ENDPOINT = "https://api.openai.com/v1/realtime/client_secrets"
REALTIME_MODEL = "gpt-realtime-2.1"
ACCESS_TOKEN_COOKIE = "done_access_token"


def _get_user(request: Request) -> TokenData:
    token = request.cookies.get(ACCESS_TOKEN_COOKIE)
    if not token:
        auth = request.headers.get("Authorization", "")
        if auth.startswith("Bearer "):
            token = auth[7:]
    td = decode_access_token(token) if token else None
    if not td:
        raise HTTPException(status_code=401, detail="Not authenticated")
    return td


class OverviewRequest(BaseModel):
    wait: bool = False


@router.get('/command-center/device')
async def command_center_device(request: Request):
    import asyncio
    import json
    from pathlib import Path
    user = _get_user(request)
    try:
        destination = json.loads((Path(__file__).resolve().parents[2] / '.tmp/atom-voice-room.json').read_text(encoding='utf-8'))
        if not await ChatService().get_room(destination['room_id'], user.user_id):
            raise HTTPException(status_code=403, detail='No access to this device')
        async with httpx.AsyncClient(timeout=2) as client:
            device, voice = await asyncio.gather(client.get('http://127.0.0.1:48801/status'), client.get('http://127.0.0.1:48802/status'))
            device.raise_for_status()
            voice.raise_for_status()
            d, v = device.json(), voice.json()
        return {'connected': bool(d.get('device_connected')), 'state': v.get('state'),
            'requested': bool(d.get('requested')), 'room_id': destination['room_id']}
    except HTTPException:
        raise
    except Exception:
        return {'connected': False, 'state': 'unavailable'}


@router.get('/command-center/overview')
async def command_center_overview(request: Request):
    from app.services.command_center_overview import recent_conversations
    return await recent_conversations(_get_user(request).user_id)


@router.post('/command-center/overview')
async def refresh_command_center_overview(request: Request, body: OverviewRequest):
    return await command_center_overview(request)


def _chat_instructions(chat_title: Optional[str]) -> str:
    context = f'会話の場所は「{chat_title}」。' if chat_title else ''
    return 'あなたはダン。ユーザーと日本語で話す仕事仲間。' + context


_CHAT_TOOLS = [
    {
        'type':'function', 'name':'control_dan_task',
        'description':'進行中の同じ作業に追加指示(update)、一時停止(pause)、再開(resume)、停止(cancel)、提示済み確定内容への本人の承認(confirm)を届ける。追加条件や質問は新しい委譲にせずupdateする。対象IDと確認IDはcheck_dan_statusのlive_jobsから得る。confirmは本人がその具体内容を承認した時だけ。',
        'parameters':{'type':'object','properties':{
            'job_id':{'type':'string'}, 'operation':{'type':'string','enum':['update','pause','resume','cancel','confirm']},
            'task':{'type':'string','description':'追加指示・質問の原文。'},
            'confirmation_id':{'type':'string'}}, 'required':['job_id','operation']},
    },
    {
        "type": "function",
        "name": "delegate_to_dan",
        "description": (
              "書き込み可能な独立したDan実行環境で、この部屋の仕事を進める。この窓口のローカルファイル権限とは独立している。ブラウザ操作、ログイン状態の確認、"
            "買い物・予約、ファイル操作、実装・分析に使う。ユーザーが許可した範囲で実行する。"
            "ブラウザで確認するだけの依頼にも使える。画面共有は不要。"
              "受付後、この呼び出しで完了まで待つ必要はない。進捗・完了結果はアプリから自動で音声とこの部屋へ届く。"
              "check_dan_statusは本人が状況を尋ねた時に使える。"
        ),
        "parameters": {
            "type": "object",
            "properties": {
                "task": {
                    "type": "string",
                    "description": "作業指示。ユーザーの依頼を具体的かつ自己完結した形で書く（要約で意図を歪めない）。",
                }
            },
            "required": ["task"],
        },
    },
    {
        "type": "function",
        "name": "check_dan_status",
        "description": "この部屋の作業と、Doneから別室へ依頼した作業の状態・プロセスモニターを確認する。",
        "parameters": {"type": "object", "properties": {}, "required": []},
    },
    {
        "type": "function",
        "name": "timeline_state",
        "description": (
            "動画エディタの『今』を読む: 開いているコンテンツ、再生位置、選択中クリップ、再生位置にあるクリップ、"
            "タイムライン全体の構造（レーン/クリップ/時刻/種類、clip_id付き）。動画の編集の話になったら最初に必ず読む。"
            "『ここ』『この字幕』『いま映ってる枠』は再生位置と選択で解決する。"
        ),
        "parameters": {"type": "object", "properties": {
            "outline": {"type": "boolean", "description": "true=全体構造も返す（既定）。false=状態だけ（速い）"}}, "required": []},
    },
    {
        "type": "function",
        "name": "timeline_edit",
        "description": (
            "動画エディタのタイムラインに小さな編集を1つ即時反映する（数秒で画面が変わる）。"
            "op と args を渡す。op: move_clip{clip_id,new_start} / trim_clip{clip_id,edge:left|right,new_time} / "
            "remove_clip{clip_id} / split_clip{clip_id,at} / set_clip{clip_id,text?,style?}(字幕の文言) / "
            "set_clip_props{clip_id,props:{position|fit|crop|opacity|volume|muted|speed|transform_keys|asset_id|source_start|grade}} / "
            "gradeは{ev,contrast,sat,temp,tint}の全置換。明るさはev(露出段数、0=無補正)、contrast/satは倍率(1=無補正)、temp/tintは0=無補正。既存の他の補正を保つなら現在値も含める。 / "
            "add_region{timeline_start,timeline_end,x,y,width,height,style:gaussian|mosaic|frame|marker|spotlight,color?,strength?,keys?}"
            "（ぼかし/黄色枠。座標は画面比0-1、左上原点） / set_region{clip_id,x?,y?,width?,height?,style?,color?,strength?,keys?,clear_keys?} / "
            "add_caption{text,timeline_start,timeline_end} / add_clip{asset_id,timeline_start,duration,source_start?,position?,speed?} / "
            "add_audio{asset_id,duration,at,source_start?,volume?,role?}。"
            "複数の編集は1つずつ順に呼ぶ。素材の生成・複雑な構成変更は delegate_to_dan。"
        ),
        "parameters": {"type": "object", "properties": {
            "op": {"type": "string"},
            "args": {"type": "object", "description": "opの引数"},
            "content_id": {"type": "string", "description": "省略時はエディタで開いているコンテンツ"}},
            "required": ["op", "args"]},
    },
    {
        "type": "function",
        "name": "timeline_frame",
        "description": "動画の指定秒の合成後の画面（字幕・ぼかし・枠・重ね全部込み）を画像で見る。編集の前後確認に使う。約10秒。",
        "parameters": {"type": "object", "properties": {
            "t": {"type": "number", "description": "タイムライン秒。省略時は再生位置"},
            "content_id": {"type": "string"}}, "required": []},
    },
    {
        "type": "function",
        "name": "web_search",
        "description": (
            "webを検索して結果（タイトル・要旨・URL）を受け取り、自分で読んで答える。"
            "最新情報・ニュース・事実確認などの軽い調べ物はこれで自己完結する（数秒）。"
            "複数ステップの深い調査や作業を伴うものだけ delegate_to_dan を使う。"
        ),
        "parameters": {
            "type": "object",
            "properties": {
                "query": {"type": "string", "description": "検索クエリ（日本語可）"},
            },
            "required": ["query"],
        },
    },
    {
        "type": "function",
        "name": "read_room_history",
        "description": (
            "このチャットルームの過去の会話履歴を読む。部屋で何が話されてきたか・"
            "直前の文脈が必要なとき、推測せずこれで自分で確認する。"
        ),
        "parameters": {
            "type": "object",
            "properties": {
                "limit": {"type": "integer", "description": "読む件数（既定30、最大50）"},
            },
            "required": [],
        },
    },
    {
        "type": "function",
        "name": "look_at_screen",
        "description": (
            "ユーザーの画面（共有されたタブ/ウィンドウ）をスクリーンショットで見る。"
            "「これ見て」の共有を受けるときに使う。初回はユーザーに共有許可ダイアログが出る。"
        ),
        "parameters": {"type": "object", "properties": {}, "required": []},
    },
    # ---- 成果物編集（対象=成果物タブで開いている成果物。開いていなければエラーが返る） ----
    {
        "type": "function",
        "name": "get_artifact_state",
        "description": "開いている成果物の編集可能な要素一覧（id・テキスト・スタイル）を取得する。編集の前に対象を確認する。",
        "parameters": {"type": "object", "properties": {}, "required": []},
    },
    {
        "type": "function",
        "name": "set_text",
        "description": "成果物の要素のテキストを書き換える（draftとして保存され、公開は別操作）。",
        "parameters": {
            "type": "object",
            "properties": {
                "id": {"type": "string", "description": "対象要素の id（get_artifact_state で確認）"},
                "text": {"type": "string", "description": "新しいテキスト"},
            },
            "required": ["id", "text"],
        },
    },
    {
        "type": "function",
        "name": "set_style",
        "description": "成果物の要素のスタイルを変更する。styles は CSSプロパティ→値（例: {\"font-size\": \"32px\", \"color\": \"#c0392b\"}）。",
        "parameters": {
            "type": "object",
            "properties": {
                "id": {"type": "string"},
                "styles": {"type": "object", "additionalProperties": {"type": "string"}},
            },
            "required": ["id", "styles"],
        },
    },
    {
        "type": "function",
        "name": "list_source_files",
        "description": "開いている成果物のソースファイル一覧を取得する。",
        "parameters": {"type": "object", "properties": {}, "required": []},
    },
    {
        "type": "function",
        "name": "read_source",
        "description": "成果物のソースファイル（page.tsx 等）を読む。構造の把握や編集の前に使う。",
        "parameters": {
            "type": "object",
            "properties": {"file": {"type": "string", "description": "例: page.tsx"}},
            "required": ["file"],
        },
    },
    {
        "type": "function",
        "name": "edit_source",
        "description": "ソースを部分編集する（完全一致の置換・1箇所）。構造変更・レイアウト変更を自分で行う。1〜2秒でプレビューに反映される。",
        "parameters": {
            "type": "object",
            "properties": {
                "file": {"type": "string"},
                "old_string": {"type": "string", "description": "ファイル内で一意になるよう前後を含める"},
                "new_string": {"type": "string"},
            },
            "required": ["file", "old_string", "new_string"],
        },
    },
    {
        "type": "function",
        "name": "write_source",
        "description": "ソースファイルを丸ごと書き換える/新規作成する。大規模な作り直し用。部分変更は edit_source を使う。",
        "parameters": {
            "type": "object",
            "properties": {"file": {"type": "string"}, "content": {"type": "string"}},
            "required": ["file", "content"],
        },
    },
    {
        "type": "function",
        "name": "generate_image",
        "description": (
            "GPT Image 2 で画像を生成する（20〜60秒）。返ってきた url を set_style の background-image や "
            "edit_source で <img> の src に自分で適用する。prompt は内容の説明文（会話の貼り付け禁止・"
            "画風や形容を勝手に足さない。デザイン判断はユーザーがする）。"
        ),
        "parameters": {
            "type": "object",
            "properties": {
                "prompt": {"type": "string"},
                "size": {"type": "string", "description": "WxH（両辺16の倍数）。省略時 1520x800"},
            },
            "required": ["prompt"],
        },
    },
    {
        "type": "function",
        "name": "look_at_page",
        "description": (
            "開いている成果物の全体を、文字が読める高解像度タイル数枚（上から順・draft反映済み）で見る（あなたの目）。"
            "編集を数回したら必ずこれで自分の目で確認してから報告する。"
        ),
        "parameters": {"type": "object", "properties": {}, "required": []},
    },
    {
        "type": "function",
        "name": "look_at_section",
        "description": "指定要素だけを原寸で見る。小さい文字の可読性や細部の確認に使う。",
        "parameters": {
            "type": "object",
            "properties": {"id": {"type": "string"}},
            "required": ["id"],
        },
    },
    {
        "type": "function",
        "name": "check_contrast",
        "description": "補助lint（任意）: 全テキスト要素のコントラスト比（WCAG）を機械計算し、読めない要素を列挙する。数値の裏取りが欲しいときに使う。",
        "parameters": {"type": "object", "properties": {}, "required": []},
    },
    {
        "type": "function",
        "name": "read_skill",
        "description": (
            "制作の作法が定義されたスキル文書を読む。name省略で一覧、指定で本文。"
            "まとまった制作・編集（LP作成、デザイン変更など）を自分でやる前に、該当スキルがあれば読んで作法に従う。"
        ),
        "parameters": {
            "type": "object",
            "properties": {"name": {"type": "string", "description": "例: build"}},
            "required": [],
        },
    },
]


class VoiceSessionRequest(BaseModel):
    chat_title: Optional[str] = None
    room_id: Optional[str] = None
    command_center_tools: bool = False
    effort: str = Field(default="high", pattern="^(minimal|low|medium|high|xhigh)$")


class LiveSessionRequest(BaseModel):
    server_delegation: bool = False   # the app will not answer delegations itself; the server's sideband does
    sdp: str = Field(default='', max_length=65536)
    room_id: str
    device: bool = False
    provider: Literal['openai', 'gemini'] = 'openai'
    thinking: Literal['low', 'medium', 'high'] = 'low'
    timezone: str = Field(default='Asia/Tokyo', max_length=128)


@router.post('/live/session')
async def create_live_session(request: Request, body: LiveSessionRequest):
    from app.services.project_service import ProjectService
    from app.services.command_center import INSTRUCTIONS, TOOL
    from app.services.voice_live import MODEL, session_config, STANDBY_TOOL, register, warm, bind_session, close
    from uuid import uuid4
    user = _get_user(request)
    chat = ChatService()
    if not await chat.get_room(body.room_id, user.user_id):
        raise HTTPException(403, '部屋へのアクセス権がありません')
    if body.provider == 'openai' and not body.sdp:
        raise HTTPException(422, 'SDP is required for Live 1')
    if body.provider == 'openai' and not settings.OPENAI_API_KEY:
        raise HTTPException(503, 'OPENAI_API_KEY が未設定です')
    if body.provider == 'gemini' and not settings.GOOGLE_GEMINI_API_KEY:
        raise HTTPException(503, 'Gemini APIの接続設定がありません')
    project = await ProjectService().get_project_by_room_id(body.room_id)
    instructions = _chat_instructions(project.get('title') if project else None)
    tools = list(_CHAT_TOOLS)
    if body.device:
        # An unattended Atom controller cannot request desktop screen sharing.
        # Browser work belongs to the normal Dan executor, not this capture tool.
        tools = [tool for tool in tools if tool['name'] != 'look_at_screen']
    if project and (project.get('metadata') or {}).get('role') == 'command_center':
        instructions += '\n' + INSTRUCTIONS
        tools.append({'type': 'function', 'name': TOOL['name'],
            'description': TOOL['description'], 'parameters': TOOL['input_schema']})
    if body.device:
        tools.append(STANDBY_TOOL)
    from app.services.voice_history import room_history
    # Load once, with the same room membership check as ordinary chat history.
    # A failed read must not silently turn an existing room into an empty call.
    messages = await chat.get_messages(body.room_id, user.user_id, limit=96)
    history = room_history(messages)
    pending_id = 'pending-' + uuid4().hex
    register(pending_id, user.user_id, instructions, tools, room_history(messages, budget=60000), room_id=body.room_id)
    warm(pending_id)
    bound = False
    try:
        if body.provider == 'gemini':
            from app.services.voice_gemini import provision
            try:
                connection = await provision(settings.GOOGLE_GEMINI_API_KEY, history, body.thinking)
            except Exception as exc:
                logger.warning('Gemini provisioning failed kind=%s', type(exc).__name__)
                raise HTTPException(502, 'Geminiの音声接続を準備できませんでした') from None
            session_id = 'gemini-' + uuid4().hex
            bind_session(pending_id, session_id)
            bound = True
            return {'session': {'id': session_id}, **connection}
        async with httpx.AsyncClient(timeout=40) as client:
            response = await client.post('https://api.openai.com/v1/live/sessions',
                headers={'Authorization': 'Bearer ' + settings.OPENAI_API_KEY},
                json={'session': session_config(instructions, tools, history, timezone=body.timezone),
                    'transport': {'type': 'webrtc', 'sdp': body.sdp}})
        data = response.json()
        if response.status_code not in (200, 201) or not data.get('session', {}).get('id') or not data.get('transport', {}).get('sdp'):
            logger.error('Live session rejected: status=%s request_id=%s', response.status_code, response.headers.get('x-request-id'))
            raise HTTPException(502, 'Live 1への接続に失敗しました')
        bind_session(pending_id, data['session']['id'])
        bound = True
        # The server answers this call's delegations itself only when the app says it will not (older apps: observe only).
        from app.services import voice_sideband
        owned = voice_sideband.attach(data['session']['id'], user.user_id, body.room_id, settings.OPENAI_API_KEY,
                                      own=bool(getattr(body, 'server_delegation', False)))
        return {'session': {'id': data['session']['id']}, 'transport': data['transport'], 'model': MODEL, 'server_delegation': owned}
    except (httpx.HTTPError, ValueError) as exc:
        raise HTTPException(502, 'Live 1への接続に失敗しました') from exc
    finally:
        if not bound:
            close(pending_id, user.user_id)


class LiveBackendRequest(BaseModel):
    session_id: str
    input: list[dict] = Field(min_length=1, max_length=200)


@router.post('/live/backend')
async def live_backend(request: Request, body: LiveBackendRequest):
    from app.services.voice_live import respond
    user = _get_user(request)
    try:
        return await respond(body.session_id, user.user_id, body.input)
    except ValueError as exc:
        logger.warning('Live backend conflict session=%s input_types=%s', body.session_id,
                       [(i.get('type'), i.get('call_id')) for i in body.input])
        raise HTTPException(409, str(exc)) from exc
    except RuntimeError:
        logger.exception('Live backend failed')
        raise HTTPException(502, 'Astraの実行接続でエラーが発生しました。APIへの切り替えはしていません。')


@router.post('/live/backend/steer')
async def steer_live_backend(request: Request, body: LiveBackendRequest):
    from app.services.voice_live import steer
    user = _get_user(request)
    try:
        return {'accepted': await steer(body.session_id, user.user_id, body.input)}
    except ValueError:
        return {'accepted': False}
    except RuntimeError as exc:
        raise HTTPException(502, str(exc)) from exc


@router.post('/live/backend/stream')
async def stream_live_backend(request: Request, body: LiveBackendRequest):
    import json
    from fastapi.responses import StreamingResponse
    from app.services.voice_live import stream_response, get_session
    user = _get_user(request)
    state = get_session(body.session_id, user.user_id)
    if not state or state['user_id'] != user.user_id:
        raise HTTPException(409, '音声の接続が更新されています。再接続してください')
    async def events():
        async for event in stream_response(body.session_id, user.user_id, body.input):
            yield 'data: ' + json.dumps(event, ensure_ascii=False) + '\n\n'
    return StreamingResponse(events(), media_type='text/event-stream', headers={'Cache-Control':'no-cache','X-Accel-Buffering':'no'})

class LiveCloseRequest(BaseModel):
    session_id: str

class CallControlUtterance(BaseModel):
    role: Literal['user', 'assistant']
    text: str = Field(min_length=1, max_length=2000)


class LiveCallControlRequest(BaseModel):
    session_id: str
    dialogue: list[CallControlUtterance] = Field(min_length=1, max_length=8)


@router.post('/live/call-control')
async def live_call_control(request: Request, body: LiveCallControlRequest):
    from app.services.voice_live import get_session
    from app.services.voice_call_control import review, CallControl
    user = _get_user(request)
    state = get_session(body.session_id, user.user_id)
    if not state or state['user_id'] != user.user_id:
        raise HTTPException(409, '音声の接続が更新されています。再接続してください')
    # Separate from the worker lock: ending a call must not queue behind a job.
    if state.get('call_control_pending'):
        return {'action': 'review', 'reason': 'pending'}
    state['call_control_pending'] = True
    try:
        if not state.get('call_control'):
            state['call_control'] = CallControl(user.user_id)
        return await review(user.user_id, [item.model_dump() for item in body.dialogue], state['call_control'])
    finally:
        state['call_control_pending'] = False


@router.post('/live/backend/close')
async def close_live_backend(request: Request, body: LiveCloseRequest):
    from app.services.voice_live import close
    user=_get_user(request)
    try: close(body.session_id,user.user_id)
    except ValueError as exc: raise HTTPException(409,str(exc)) from exc
    return {'closed':True}


async def _room_memory_digest(room_id: str, user_id: str) -> str:
    """接続時に注入する「この部屋のこれまで」の要約。

    一言目から部屋の文脈を持っているための起動時記憶。過去の教訓:
    生の対話をそのまま注入するとモデルが今の会話と混同する（2026-08-23 実証）ため、
    記憶であることを明示し、発話ラベル付き・短縮・上限つきのダイジェスト形式にする。
    """
    try:
        svc = ChatService()
        # 解像度が命: 110字/件では長文回答が見出しで切れ、決定事項が記憶に入らない
        # （2026-08-26 実証: 免許再発行の文脈が切れ落ちて聞き返し事故）。
        # ダンの回答は結論から書く流儀なので、400字あれば各回答の要点が入る。
        messages = await svc.get_messages(room_id, user_id, limit=25)
        if not messages:
            return ""
        lines = []
        for m in messages:
            content = (m.get("content") or "").strip()
            if content.startswith("🎙"):
                content = content[1:].strip()
            who = "みきさん" if m.get("sender_type") in ("human", "user") else "あなた"
            lines.append(f"- {who}: {content[:400]}")
        digest = "\n".join(lines)[-7000:]
        return (
            "\n\n【この部屋のこれまで（あなた自身の記憶の要約。過去の記録であり、いま話しかけられている言葉ではない）】\n"
            f"{digest}\n"
            "この続きとして会話する。新しい発話にだけ応答する。"
        )
    except Exception:
        return ""


@router.post("/session")
async def create_chat_voice_session(request: Request, body: VoiceSessionRequest):
    user = _get_user(request)
    if not settings.OPENAI_API_KEY:
        raise HTTPException(status_code=503, detail="OPENAI_API_KEY が未設定です")

    instructions = _chat_instructions(body.chat_title)
    tools = list(_CHAT_TOOLS)
    if body.room_id:
        from app.services.project_service import ProjectService
        from app.services.command_center import INSTRUCTIONS, TOOL
        if not await ChatService().get_room(body.room_id, user.user_id):
            raise HTTPException(status_code=403, detail="部屋へのアクセス権がありません")
        project = await ProjectService().get_project_by_room_id(body.room_id)
        if body.command_center_tools and project and (project.get("metadata") or {}).get("role") == "command_center":
            instructions += "\n\n" + INSTRUCTIONS
            tools.append({"type": "function", "name": TOOL["name"],
                "description": TOOL["description"], "parameters": TOOL["input_schema"]})
        instructions += await _room_memory_digest(body.room_id, user.user_id)

    session = {
        "type": "realtime",
        "model": REALTIME_MODEL,
        "instructions": instructions,
        "audio": {
            "input": {
                "transcription": {"model": "gpt-realtime-whisper", "language": "ja"},
                "noise_reduction": {"type": "near_field"},
                "turn_detection": {"type": "semantic_vad", "eagerness": "low"},
            },
            "output": {"voice": "cedar"},
        },
        "tools": tools,
        "reasoning": {"effort": body.effort},
    }
    async with httpx.AsyncClient(timeout=30.0) as client:
        resp = await client.post(
            CLIENT_SECRETS_ENDPOINT,
            headers={"Authorization": f"Bearer {settings.OPENAI_API_KEY}", "Content-Type": "application/json"},
            json={"session": session},
        )
    if resp.status_code != 200:
        detail = resp.text[:500]
        logger.error("voicelog session mint failed: HTTP %s %s", resp.status_code, detail)
        raise HTTPException(status_code=502, detail=f"セッション発行に失敗 (HTTP {resp.status_code}): {detail}")
    data = resp.json()
    return {"value": data.get("value", ""), "model": REALTIME_MODEL, "expires_at": data.get("expires_at")}


class CommandCenterRequest(BaseModel):
    room_id: str
    args: dict


@router.post("/command-center")
async def command_center(request: Request, body: CommandCenterRequest):
    from app.services.command_center import execute
    user = _get_user(request)
    try:
        return await execute(body.args, body.room_id, user.user_id)
    except ValueError as exc:
        raise HTTPException(status_code=400, detail=str(exc)) from exc


# ------------------------------------------------------- artifact editing
#
# V2: 成果物編集ツール群（scratch実験で実証済みの一式の本番移植）。
# チャットのプレビューiframeはクロスオリジン(postMessage方式)のため、
# 編集・撮影・検査はすべてサーバー側で実行し、フロントは編集後に
# プレビューの contentVersion を bump して再読込で見せる。

import asyncio
import base64
import re as _re
import subprocess
from pathlib import Path as _Path

_REPO_ROOT = _Path(__file__).resolve().parents[2]
_ARTIFACTS_ROOT = _REPO_ROOT / "frontend" / "src" / "app" / "artifacts"
_SKILLS_ROOT = _REPO_ROOT / ".claude" / "skills"
_ALLOWED_EXT = {".tsx", ".ts", ".css", ".md", ".json", ".txt"}
_CAPTURE_SCRIPT = _REPO_ROOT / "scripts" / "voice_page_capture.py"
_GEN_DIR = _REPO_ROOT / "frontend" / "public" / "artifacts" / "voice-gen"


def _raw_token(request: Request) -> str:
    token = request.cookies.get(ACCESS_TOKEN_COOKIE)
    if not token:
        auth = request.headers.get("Authorization", "")
        if auth.startswith("Bearer "):
            token = auth[7:]
    return token or ""


def _artifact_root(slug: str) -> _Path:
    if not _re.match(r"^[a-z0-9][a-z0-9-]*$", slug or ""):
        raise HTTPException(status_code=400, detail="slug が不正です")
    return _ARTIFACTS_ROOT / slug


def _resolve_file(root: _Path, file: str) -> _Path:
    if not file or ".." in file or file.startswith(("/", "\\")):
        raise HTTPException(status_code=400, detail="file パスが不正です")
    if _Path(file).suffix.lower() not in _ALLOWED_EXT:
        raise HTTPException(status_code=400, detail="この拡張子は扱えません")
    full = (root / file).resolve()
    if not str(full).startswith(str(root.resolve())):
        raise HTTPException(status_code=400, detail="成果物ディレクトリ外は扱えません")
    return full


class SourceRequest(BaseModel):
    action: str = Field(pattern="^(list|read|edit|write)$")
    slug: str
    file: Optional[str] = None
    old_string: Optional[str] = None
    new_string: Optional[str] = None
    content: Optional[str] = None


@router.post("/source")
async def voice_source(request: Request, body: SourceRequest):
    _get_user(request)
    root = _artifact_root(body.slug)

    if body.action == "list":
        files = []
        if root.exists():
            for p in sorted(root.rglob("*")):
                if p.is_file():
                    files.append({"file": str(p.relative_to(root)).replace("\\", "/"), "bytes": p.stat().st_size})
        return {"files": files[:100]}

    full = _resolve_file(root, body.file or "")
    if body.action == "read":
        try:
            content = full.read_text(encoding="utf-8")
        except FileNotFoundError:
            raise HTTPException(status_code=404, detail="ファイルがありません")
        return {"file": body.file, "bytes": len(content), "content": content[:40_000], "truncated": len(content) > 40_000}

    if body.action == "edit":
        old = body.old_string or ""
        if not old:
            raise HTTPException(status_code=400, detail="old_string が空です")
        try:
            content = full.read_text(encoding="utf-8")
        except FileNotFoundError:
            raise HTTPException(status_code=404, detail="ファイルがありません")
        count = content.count(old)
        if count == 0:
            raise HTTPException(status_code=409, detail="old_string が見つかりません（完全一致が必要）")
        if count > 1:
            raise HTTPException(status_code=409, detail=f"old_string が{count}箇所にマッチします。前後を含めて一意にしてください")
        full.write_text(content.replace(old, body.new_string or "", 1), encoding="utf-8")
        return {"ok": True, "file": body.file, "note": "1〜2秒でプレビューに反映されます"}

    # write
    content = body.content or ""
    if not content:
        raise HTTPException(status_code=400, detail="content が空です")
    if len(content) > 400_000:
        raise HTTPException(status_code=413, detail="content が大きすぎます")
    full.parent.mkdir(parents=True, exist_ok=True)
    full.write_text(content, encoding="utf-8")
    return {"ok": True, "file": body.file, "bytes": len(content)}


def _kebab(styles: dict) -> dict:
    return { _re.sub(r"[A-Z]", lambda m: "-" + m.group(0).lower(), k): v for k, v in (styles or {}).items() }


class EditRequest(BaseModel):
    slug: str
    element_id: str = Field(min_length=1, max_length=120)
    text: Optional[str] = None
    styles: Optional[dict] = None


@router.post("/edit")
async def voice_edit(request: Request, body: EditRequest):
    """set_text / set_style（draft=inspector_overrides レーン。Inspector手編集と同じ保存先）。"""
    user = _get_user(request)
    from app.services.inspector_overrides_service import InspectorOverridesService

    svc = InspectorOverridesService()
    key = f"@{body.element_id}"
    styles = _kebab(body.styles) if body.styles else None
    attrs = None
    if body.text is not None:
        # 既存 model_v2 を保全して text だけ差し替える（過去のスタイル編集を壊さない）
        try:
            row = (
                svc.supabase.table("inspector_overrides").select("attrs")
                .eq("artifact_slug", body.slug).eq("element_key", key).limit(1).execute()
            )
            model = {"v": 2, "text": None, "blockStyle": {}, "spans": [], "attrs": {}}
            if row.data and isinstance(row.data[0].get("attrs"), dict):
                import json as _json

                raw = row.data[0]["attrs"].get("model_v2")
                if isinstance(raw, str):
                    model = {**model, **_json.loads(raw)}
        except Exception:
            model = {"v": 2, "text": None, "blockStyle": {}, "spans": [], "attrs": {}}
        model["text"] = body.text
        import json as _json

        attrs = {"model_v2": _json.dumps(model, ensure_ascii=False)}
    result = await svc.upsert(
        artifact_slug=body.slug, element_key=key, styles=styles, attrs=attrs,
        user_id=user.user_id, project_id=None, replace_attrs=False,
    )
    return {"ok": True, "element_key": key, "id": str(result.get("id", ""))}


class TimelineToolRequest(BaseModel):
    room_id: str
    action: str  # state | edit | frame
    content_id: Optional[str] = None
    op: Optional[str] = None
    args: Optional[dict] = None
    t: Optional[float] = None
    outline: bool = True


@router.post("/timeline")
async def voice_timeline(request: Request, body: TimelineToolRequest):
    """Voice agent's hands and eyes on the video editor (fast lane, no agent job)."""
    _get_user(request)
    from app.services import timeline_live as tl
    import asyncio

    room_id = body.room_id.strip()
    if not room_id:
        raise HTTPException(status_code=400, detail="room_id が空です")
    cid = (body.content_id or "").strip()
    if not cid:
        st = tl.editor_state(room_id)
        cid = str(st.get("content_id") or "") if st else ""
    if body.action == "state":
        return await asyncio.to_thread(tl.editor_context, room_id, cid or None, body.outline)
    if not cid:
        return {"ok": False, "error": "エディタが開いていない。content_id を指定するか、制作ルームで動画エディタを開いてもらう"}
    if body.action == "edit":
        if not body.op:
            raise HTTPException(status_code=400, detail="op が必要")
        return await asyncio.to_thread(tl.apply_edit, room_id, cid, body.op, body.args or {})
    if body.action == "frame":
        t = body.t
        if t is None:
            st = tl.editor_state(room_id)
            t = float((st or {}).get("playhead") or 0.0)
        return await asyncio.to_thread(tl.render_frame_b64, room_id, cid, float(t))
    raise HTTPException(status_code=400, detail=f"unknown action {body.action}")


class CaptureRequest(BaseModel):
    slug: str
    mode: str = Field(pattern="^(tiles|section|state|contrast)$")
    element_id: Optional[str] = None


@router.post("/capture")
async def voice_capture(request: Request, body: CaptureRequest):
    _get_user(request)
    token = _raw_token(request)
    _artifact_root(body.slug)  # slug validation
    args = ["python", str(_CAPTURE_SCRIPT), "--slug", body.slug, "--mode", body.mode]
    if token:
        args += ["--token", token]
    if body.element_id:
        if not _re.match(r"^[a-zA-Z0-9_-]+$", body.element_id):
            raise HTTPException(status_code=400, detail="element_id が不正です")
        args += ["--element-id", body.element_id]

    def _run():
        return subprocess.run(args, capture_output=True, text=True, timeout=60, encoding="utf-8", errors="replace")

    proc = await asyncio.to_thread(_run)
    if proc.returncode != 0:
        raise HTTPException(status_code=502, detail=f"capture失敗: {(proc.stderr or '')[:300]}")
    try:
        data = __import__("json").loads(proc.stdout.strip().splitlines()[-1])
    except Exception:
        raise HTTPException(status_code=502, detail=f"capture出力の解析に失敗: {proc.stdout[:200]}")

    def _b64(path: str) -> str:
        return "data:image/jpeg;base64," + base64.b64encode(_Path(path).read_bytes()).decode()

    if "tiles" in data:
        return {"tiles": [_b64(t) for t in data["tiles"]], "count": len(data["tiles"])}
    if "image" in data:
        return {"image": _b64(data["image"])}
    return data  # state / contrast はそのまま


class GenerateImageRequest(BaseModel):
    prompt: str = Field(min_length=1, max_length=2000)
    size: Optional[str] = None


@router.post("/generate-image")
async def voice_generate_image(request: Request, body: GenerateImageRequest):
    _get_user(request)
    if not settings.OPENAI_API_KEY:
        raise HTTPException(status_code=503, detail="OPENAI_API_KEY が未設定です")
    size = body.size or "1520x800"
    m = _re.match(r"^(\d+)x(\d+)$", size)
    if not m or int(m.group(1)) % 16 or int(m.group(2)) % 16:
        size = "1520x800"
    async with httpx.AsyncClient(timeout=180.0) as client:
        resp = await client.post(
            "https://api.openai.com/v1/images/generations",
            headers={"Authorization": f"Bearer {settings.OPENAI_API_KEY}"},
            json={"model": "gpt-image-2", "prompt": body.prompt, "size": size, "quality": "low"},
        )
    if resp.status_code != 200:
        raise HTTPException(status_code=502, detail=f"画像生成に失敗 (HTTP {resp.status_code})")
    b64 = (resp.json().get("data") or [{}])[0].get("b64_json")
    if not b64:
        raise HTTPException(status_code=502, detail="画像データが空でした")
    _GEN_DIR.mkdir(parents=True, exist_ok=True)
    name = f"gen-{int(__import__('time').time() * 1000)}.png"
    (_GEN_DIR / name).write_bytes(base64.b64decode(b64))
    return {"url": f"/artifacts/voice-gen/{name}", "size": size}


class SkillRequest(BaseModel):
    name: Optional[str] = None


@router.post("/skill")
async def voice_read_skill(request: Request, body: SkillRequest):
    """スキルの一覧/本文をエージェントに読ませる（あてずっぽう作業の防止）。"""
    _get_user(request)
    if not body.name:
        skills = []
        for d in sorted(_SKILLS_ROOT.iterdir()):
            md = d / "SKILL.md"
            if md.exists():
                head = md.read_text(encoding="utf-8", errors="replace")[:400]
                skills.append({"name": d.name, "summary": head.replace("\n", " ")[:180]})
        return {"skills": skills}
    if not _re.match(r"^[a-z0-9_-]+$", body.name):
        raise HTTPException(status_code=400, detail="スキル名が不正です")
    md = _SKILLS_ROOT / body.name / "SKILL.md"
    if not md.exists():
        raise HTTPException(status_code=404, detail=f"スキル {body.name} がありません")
    content = md.read_text(encoding="utf-8", errors="replace")
    return {"name": body.name, "content": content[:18_000], "truncated": len(content) > 18_000}


# ---------------------------------------------------------------- mobile support

@router.post("/config")
async def voice_config(request: Request):
    """モバイル用の接続設定。委譲WS(コア)はVercelプロキシを通らないため、
    コアのトンネルURLを直接返してアプリから wss 直結させる。"""
    _get_user(request)
    delegate_ws = ""
    try:
        core_url = (_REPO_ROOT / ".tunnel_core_url").read_text(encoding="utf-8").strip()
        if core_url.startswith("https://"):
            delegate_ws = "wss://" + core_url[len("https://"):].rstrip("/") + "/ws/realtime-delegate"
    except Exception:
        pass
    return {"delegate_ws": delegate_ws}


class RoomArtifactRequest(BaseModel):
    room_id: str


@router.post("/room-artifact")
async def voice_room_artifact(request: Request, body: RoomArtifactRequest):
    """部屋に紐づく最新の成果物slugを返す（モバイルにはプレビュー面が無いため、
    編集ツールの対象slugをサーバー側で解決する）。"""
    _get_user(request)
    from app.services.inspector_overrides_service import InspectorOverridesService

    sb = InspectorOverridesService().supabase
    rows = (
        sb.table("chat_artifact").select("slug,label,updated_at")
        .eq("room_id", body.room_id).order("updated_at", desc=True).limit(1).execute()
    )
    if not rows.data:
        return {"slug": None}
    return {"slug": rows.data[0]["slug"], "label": rows.data[0].get("label")}


# ---------------------------------------------------------------- search

class SearchRequest(BaseModel):
    query: str = Field(min_length=1, max_length=400)


@router.post("/search")
async def voice_web_search(request: Request, body: SearchRequest):
    """Return query-relevant source passages, preserving evidence for the intake."""
    _get_user(request)
    import os

    key = os.environ.get("TAVILY_API_KEY", "") or getattr(settings, "TAVILY_API_KEY", "")
    if not key:
        from pathlib import Path

        env_path = Path(__file__).resolve().parents[2] / ".env"
        try:
            key = next(
                (l.split("=", 1)[1].strip() for l in env_path.read_text(encoding="utf-8").splitlines()
                 if l.startswith("TAVILY_API_KEY=")),
                "",
            )
        except Exception:
            key = ""
    if not key:
        raise HTTPException(status_code=503, detail="検索APIキーが未設定です")

    async with httpx.AsyncClient(timeout=20.0) as client:
        resp = await client.post(
            "https://api.tavily.com/search",
            json={"api_key": key, "query": body.query, "max_results": 4, "include_answer": False,
                  "search_depth": "advanced", "chunks_per_source": 2},
        )
    if resp.status_code != 200:
        raise HTTPException(status_code=502, detail=f"検索に失敗 (HTTP {resp.status_code})")
    data = resp.json()
    results = [
        {
            "title": r.get("title", "")[:120],
            "snippet": (r.get("content") or "")[:1100],
            "url": r.get("url", ""),
        }
        for r in (data.get("results") or [])[:4]
    ]
    return {"query": body.query, "results": results}


# ------------------------------------------------------------- transcript

class TranscriptRequest(BaseModel):
    role: str = Field(pattern="^(user|assistant)$")
    content: str = Field(min_length=1, max_length=8000)
    created_at: Optional[datetime] = None


@router.post("/{room_id}")
async def add_voice_transcript(room_id: str, request: Request, body: TranscriptRequest):
    """音声会話の1発話を部屋の履歴に保存する（🎙マーク付き）。

    sender_type は human/ai を使い分けるので、チャットUIでは通常の
    ユーザー/ダンの吹き出しとして時系列に並ぶ。ダン（CLI）は後のターンで
    この履歴を読めるため、音声↔テキストの記憶が部屋単位で繋がる。
    """
    user = _get_user(request)
    sender_type = "human" if body.role == "user" else "ai"
    content = f"🎙 {body.content.strip()}"
    svc = ChatService()
    try:
        message = await svc.send_message(room_id, user.user_id, content, sender_type=sender_type,
            created_at=body.created_at.isoformat() if body.created_at else None)
    except ValueError as e:
        raise HTTPException(status_code=403, detail=str(e))
    return {"ok": True, "id": message.get("id")}
