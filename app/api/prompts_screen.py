"""The /prompts screen: the instructions that run Dan, where each one works, its full text, its history, and saving or
putting back a version (owner, 2026-11-17). The texts live in ~/.dan/workspace/prompts (app/services/prompt_store.py)."""
import asyncio
import json

from fastapi import APIRouter, Depends, HTTPException
from pydantic import BaseModel

from app.api.chat_routes import TokenData, get_current_user
from app.services import prompt_store
from app.services.owner import resolve_owner_user_id
from app.services.skill_versions import skill_pages

from app.api.conversation_circuit import router as circuit_router
from app.api.video_flow_routes import router as video_flow_router

router = APIRouter(prefix='/prompts', tags=['prompts'])
router.include_router(circuit_router)
router.include_router(video_flow_router)


def _list(include_skills=True):
    data = prompt_store.catalog()
    items = []
    registered = {}
    for item in data['prompts']:
        if item.get('kind') == 'skill':
            registered[item['id']] = item
            continue
        try: items.append(prompt_store.summary(item['id']))
        except Exception as exc:
            items.append({**item, 'error': type(exc).__name__})
    if include_skills:
        # Opening a library should not create a history journal for every file.
        items.extend(registered.get(page['id'], page) for page in skill_pages())
    return {'places': data['places'], 'prompts': items}


def _check_skill_owner(prompt_id, current_user):
    if prompt_id.startswith('skill/') and current_user.user_id != resolve_owner_user_id():
        raise HTTPException(403, 'スキルは本人だけが開けます。')


def _item(prompt_id):
    item = prompt_store.entry(prompt_id)
    value = prompt_store.text(prompt_id)
    hist = [] if item.get('readonly') else prompt_store.history(prompt_id)
    return {**item, 'text': value, 'sha': prompt_store.sha(value), 'chars': len(value), 'history': hist}


@router.get('')
async def list_prompts(current_user: TokenData = Depends(get_current_user)):
    return await asyncio.to_thread(lambda: _list(current_user.user_id == resolve_owner_user_id()))


@router.get('/item')
async def get_prompt(id: str, current_user: TokenData = Depends(get_current_user)):
    _check_skill_owner(id, current_user)
    try: return await asyncio.to_thread(_item, id)
    except KeyError: raise HTTPException(404, 'その指示文はありません。')


def _sha(prompt_id):
    value = prompt_store.text(prompt_id)
    return {'id': prompt_id, 'sha': prompt_store.sha(value)}


@router.get('/sha')
async def prompt_sha(id: str, current_user: TokenData = Depends(get_current_user)):
    """Only the version mark: the screen asks this every few seconds while Dan works in the chat, to show Dan's change at once."""
    _check_skill_owner(id, current_user)
    try: return await asyncio.to_thread(_sha, id)
    except KeyError: raise HTTPException(404, 'その指示文はありません。')


@router.get('/working')
async def prompt_working(current_user: TokenData = Depends(get_current_user)):
    """Where Dan is working now (the lines the screen lights), or {}."""
    return await asyncio.to_thread(prompt_store.working)


class SaveBody(BaseModel):
    id: str
    text: str
    note: str = ''
    base_sha: str = ''


@router.post('/item')
async def save_prompt(body: SaveBody, current_user: TokenData = Depends(get_current_user)):
    _check_skill_owner(body.id, current_user)
    try:
        out = await asyncio.to_thread(prompt_store.save, body.id, body.text, 'owner', body.note, body.base_sha or None)
    except KeyError: raise HTTPException(404, 'その指示文はありません。')
    except ValueError as exc: raise HTTPException(422, str(exc))
    except RuntimeError as exc: raise HTTPException(409, str(exc))
    return {**out, 'item': await asyncio.to_thread(_item, body.id)}


class RevertBody(BaseModel):
    id: str
    sha: str
    base_sha: str = ''


@router.post('/revert')
async def revert_prompt(body: RevertBody, current_user: TokenData = Depends(get_current_user)):
    _check_skill_owner(body.id, current_user)
    try:
        out = await asyncio.to_thread(prompt_store.revert, body.id, body.sha, 'owner', body.base_sha or None)
    except KeyError: raise HTTPException(404, 'その版はありません。')
    except RuntimeError as exc: raise HTTPException(409, str(exc))
    except ValueError as exc: raise HTTPException(422, str(exc))
    return {**out, 'item': await asyncio.to_thread(_item, body.id)}


# ---- 指示文の画面の会話（2026-11-21 本人「指示文の見直しはお前と一緒にやった方が良いけど、ページにチャットが無いからやりにくい」）----
# 開発室のボードの話し合いと同じく、一覧に出さない部屋を1つ作り、/prompts と開発室の「指示文」の両方からその1つの部屋で話す。
# 部屋の説明（ダンが毎回読む前置き）に、この画面の発言の読み方と直し方を書く。どの文・どの行を開いているかは、
# 画面が発言ごとに <dan-context> で添える（components/prompts/prompts-chat.tsx）。
DEV_LEAD_ROOM = '7b5184bd-21a9-4b18-a6c6-da4c0ce1243f'   # ダン開発室（artifacts/dev-lead/model.ts の ROOM_ID）
CHAT_TITLE = 'ダン開発室: 指示文の見直し'
CHAT_DESCRIPTION = """この部屋は、みきさんがダンを動かしている指示文の画面（/prompts と、開発室のボードの「指示文」）を見ながら、ダンと一緒に指示文を見直すための会話です。

- みきさんの発言の頭の <dan-context> に、今開いている指示文（id・題・ファイル・誰が読むか・いつ効くか）と、選んでいる行と文、まだ保存していない書きかけがあればその違いが入っています。「ここ」「この行」「これ」はそれを指します。
- 「何のため？」「消したらどうなる？」のような質問には、その文を読むコードと効く場面を実際に確かめて答えます。答えるだけの時は文を変えません。
- 直してと頼まれた時だけ直します。直し方は1つだけです: `python /Users/mikihonda/done/scripts/prompts.py save <id> --note "<なぜ直したか。みきさんのどの言葉か>"` に新しい全文を標準入力で渡します。ファイルを直接書き換えたり、Python のコードの中に文を足したりしません。
- 直す文を決めたら、新しい文を考える前に `python /Users/mikihonda/done/scripts/prompts.py mark <id> --find "<これから直す所の今の文>"`（または `--lines 12-15`）を呼びます。みきさんの画面でその文が開き、その行が光るので、ダンがどこを直しているかが見えます。
- 保存すると、みきさんの画面の全文が数秒で新しい版に替わり、変わった行が光り、変わった所と「元に戻す」が出ます。返事には、何をどう変えたかを1〜3文で書きます（全文を貼り直さない）。
- みきさんが書きかけを保存していない時は、その書きかけを消さないよう、直す前にどちらを生かすか聞きます。
- 「読むだけ」の文（まだプログラムの中にある文）と手順書は、この部屋では書き換えません。直したいと言われたら、画面で直せる形に移す作業になると伝えて、やってよいか聞きます。
- 指示文を書き換えるのは取り返しのつく操作です（履歴から戻せます）。頼まれた直しは、聞き返さずにそのまま進めます。"""
CHAT_FILE = 'chat.json'


def _chat_path():
    return prompt_store.root() / '.chat' / CHAT_FILE


def _chat_read():
    try: return json.loads(_chat_path().read_text(encoding='utf-8'))
    except (OSError, ValueError): return {}


def _chat_write(data):
    path = _chat_path()
    path.parent.mkdir(parents=True, exist_ok=True)
    tmp = path.with_suffix('.tmp')
    tmp.write_text(json.dumps(data, ensure_ascii=False, indent=1), encoding='utf-8')
    tmp.replace(path)


_chat_lock = asyncio.Lock()


@router.get('/chat')
async def prompts_chat_room(current_user: TokenData = Depends(get_current_user)):
    """The one room for talking about the instructions with Dan. Made on first use (hidden from the room list)."""
    from app.services.project_service import ProjectService
    service = ProjectService()
    async with _chat_lock:
        saved = (await asyncio.to_thread(_chat_read)).get(current_user.user_id) or {}
        if saved.get('project_id'):
            project = await service.get_project(saved['project_id'], current_user.user_id)
            if project and project.get('room_id'):
                if (project.get('description') or '') != CHAT_DESCRIPTION:   # how Dan works in this room changed
                    await service.update_project(project['id'], current_user.user_id, description=CHAT_DESCRIPTION)
                return {'project_id': project['id'], 'room_id': project['room_id'], 'title': CHAT_TITLE}
        project = await service.create_project(user_id=current_user.user_id, title=CHAT_TITLE, description=CHAT_DESCRIPTION,
                                               origin_room_id=DEV_LEAD_ROOM, metadata={'hidden': True})
        if not project.get('room_id'):
            raise HTTPException(500, '会話の部屋を作れませんでした。')
        data = await asyncio.to_thread(_chat_read)
        data[current_user.user_id] = {'project_id': project['id'], 'room_id': project['room_id'], 'created': project.get('created_at')}
        await asyncio.to_thread(_chat_write, data)
        return {'project_id': project['id'], 'room_id': project['room_id'], 'title': CHAT_TITLE}
