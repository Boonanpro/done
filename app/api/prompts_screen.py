"""The /prompts screen: the instructions that run Dan, where each one works, its full text, its history, and saving or
putting back a version (owner, 2026-11-17). The texts live in ~/.dan/workspace/prompts (app/services/prompt_store.py)."""
import asyncio

from fastapi import APIRouter, Depends, HTTPException
from pydantic import BaseModel

from app.api.chat_routes import TokenData, get_current_user
from app.services import prompt_store

router = APIRouter(prefix='/prompts', tags=['prompts'])
SKILLS = prompt_store.REPO / '.claude' / 'skills'


def _skills():
    """The skills, read only here: they are files of Dan's code (a change goes through a worktree)."""
    out = []
    for path in sorted(SKILLS.glob('*/SKILL.md')):
        try: head = path.read_text(encoding='utf-8')[:1500]
        except OSError: continue
        desc = ''
        for line in head.splitlines():
            if line.startswith('description:'):
                desc = line.split(':', 1)[1].strip().strip('"')
                break
        out.append({'id': f'skill/{path.parent.name}', 'title': f'手順書「{path.parent.name}」', 'place': 'chat', 'readonly': True,
                    'reader': 'チャットのダン・作業の部屋のダン（その作業に要る時だけ読む）', 'when': '作業がこの手順書に当たる時',
                    'source': f'.claude/skills/{path.parent.name}/SKILL.md', 'why': desc, 'kind': 'skill'})
    return out


def _skill_text(prompt_id):
    name = prompt_id.split('/', 1)[1]
    path = (SKILLS / name / 'SKILL.md').resolve()
    if path.parent.parent != SKILLS.resolve() or not path.exists():
        raise KeyError(prompt_id)
    return path.read_text(encoding='utf-8')


def _list():
    data = prompt_store.catalog()
    items = []
    for item in data['prompts']:
        try: items.append(prompt_store.summary(item['id']))
        except Exception as exc:
            items.append({**item, 'error': type(exc).__name__})
    items.extend(_skills())
    return {'places': data['places'], 'prompts': items}


def _item(prompt_id):
    if prompt_id.startswith('skill/'):
        skill = next((s for s in _skills() if s['id'] == prompt_id), None)
        if skill is None: raise KeyError(prompt_id)
        value = _skill_text(prompt_id)
        return {**skill, 'text': value, 'sha': prompt_store.sha(value), 'chars': len(value), 'history': []}
    item = prompt_store.entry(prompt_id)
    value = prompt_store.text(prompt_id)
    hist = [] if item.get('readonly') else prompt_store.history(prompt_id)
    return {**item, 'text': value, 'sha': prompt_store.sha(value), 'chars': len(value), 'history': hist}


@router.get('')
async def list_prompts(current_user: TokenData = Depends(get_current_user)):
    return await asyncio.to_thread(_list)


@router.get('/item')
async def get_prompt(id: str, current_user: TokenData = Depends(get_current_user)):
    try: return await asyncio.to_thread(_item, id)
    except KeyError: raise HTTPException(404, 'その指示文はありません。')


class SaveBody(BaseModel):
    id: str
    text: str
    note: str = ''
    base_sha: str = ''


@router.post('/item')
async def save_prompt(body: SaveBody, current_user: TokenData = Depends(get_current_user)):
    try:
        out = await asyncio.to_thread(prompt_store.save, body.id, body.text, 'owner', body.note, body.base_sha or None)
    except KeyError: raise HTTPException(404, 'その指示文はありません。')
    except ValueError as exc: raise HTTPException(422, str(exc))
    except RuntimeError as exc: raise HTTPException(409, str(exc))
    return {**out, 'item': await asyncio.to_thread(_item, body.id)}


class RevertBody(BaseModel):
    id: str
    sha: str


@router.post('/revert')
async def revert_prompt(body: RevertBody, current_user: TokenData = Depends(get_current_user)):
    try:
        out = await asyncio.to_thread(prompt_store.revert, body.id, body.sha, 'owner')
    except KeyError: raise HTTPException(404, 'その版はありません。')
    except ValueError as exc: raise HTTPException(422, str(exc))
    return {**out, 'item': await asyncio.to_thread(_item, body.id)}
