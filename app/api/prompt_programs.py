"""Read the implementation shown on the owner's diagram and keep exact test inputs."""
import asyncio
import hashlib
import json
import os
import subprocess
import tempfile
from pathlib import Path

from fastapi import APIRouter, Depends, HTTPException
from pydantic import BaseModel, Field

from app.api.conversation_circuit import owner
from app.services import prompt_store

ROOT = Path(__file__).resolve().parents[2]
CATALOG = ROOT / 'frontend/src/components/prompts/program-sources.json'


router = APIRouter(prefix='/program', dependencies=[Depends(owner)])


def source(path: str):
    paths = json.loads(CATALOG.read_text(encoding='utf-8'))
    if not any(path in files for files in paths.values()):
        raise HTTPException(404, 'この構成図に登録されていないファイルです。')
    file = (ROOT / path).resolve()
    if not file.is_relative_to(ROOT) or not file.is_file():
        raise HTTPException(404, 'この版にはファイルがありません。')
    text = file.read_text(encoding='utf-8')
    return {'path': path, 'text': text, 'sha': hashlib.sha256(text.encode()).hexdigest()}


@router.get('')
async def get_source(path: str):
    return await asyncio.to_thread(source, path)


def last_change(path: str):
    source(path)
    # Only the path already accepted by the diagram catalog reaches git.
    try:
        result = subprocess.run(
            ['git', '-C', str(ROOT), 'log', '-1', '--no-ext-diff', '--no-textconv',
             '--format=%h %as %s', '--patch', '--', path],
            capture_output=True, text=True, timeout=6, check=True,
        ).stdout
    except (OSError, subprocess.SubprocessError):
        raise HTTPException(503, '変更履歴を開けませんでした。')
    return {'diff': result[:120000], 'truncated': len(result) > 120000}


@router.get('/change')
async def get_last_change(path: str):
    return await asyncio.to_thread(last_change, path)


class TrialDraft(BaseModel):
    path: str
    base_sha: str = Field(pattern='^[0-9a-f]{64}$')
    text: str = Field(max_length=1_000_000)
    scenario: str = Field(min_length=1, max_length=4000)


def save_draft(body: TrialDraft):
    original = source(body.path)
    if original['sha'] != body.base_sha:
        raise HTTPException(409, '編集中に元の実装が変わりました。書きかけを控えてから開き直してください。')
    folder = prompt_store.root() / '.program-trials'
    folder.mkdir(parents=True, exist_ok=True, mode=0o700)
    data = json.dumps(body.model_dump(), ensure_ascii=False).encode()
    digest = hashlib.sha256(data).hexdigest()
    target = folder / (digest + '.json')
    with tempfile.NamedTemporaryFile(dir=folder, delete=False) as tmp:
        try:
            tmp.write(data)
            tmp.flush()
            os.replace(tmp.name, target)
        finally:
            Path(tmp.name).unlink(missing_ok=True)
    return {'draft': str(target)}


@router.post('/draft')
async def keep_draft(body: TrialDraft):
    return await asyncio.to_thread(save_draft, body)
