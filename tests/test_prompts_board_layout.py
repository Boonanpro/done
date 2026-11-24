"""構成図のボードの並べ方（/prompts/board-layout）: 本人が動かした箱・枠・線の点だけを保存し、読み返せる。"""
import asyncio
import types

import pytest
from fastapi import HTTPException

from app.api import prompts_screen
from app.services import prompt_store


def test_board_layout_saved_and_read(tmp_path, monkeypatch):
    monkeypatch.setattr(prompt_store, 'root', lambda: tmp_path)
    monkeypatch.setattr(prompts_screen, 'resolve_owner_user_id', lambda: 'owner')
    me = types.SimpleNamespace(user_id='owner')
    assert asyncio.run(prompts_screen.board_layout(current_user=me)) == {'nodes': {}, 'frames': {}, 'edges': {}}
    body = prompts_screen.BoardBody(nodes={'pc': {'x': 10, 'y': 20.04, 'w': 150, 'h': 128}, 'bad': {'x': 1}},
                                    frames={'work': {'x': 0, 'y': 0, 'w': 300, 'h': 900}},
                                    edges={'chat/reply': [[1, 2], [3.33, 4]], 'broken': 'x'})
    asyncio.run(prompts_screen.save_board_layout(body, current_user=me))
    got = asyncio.run(prompts_screen.board_layout(current_user=me))
    assert got['nodes'] == {'pc': {'x': 10.0, 'y': 20.0, 'w': 150.0, 'h': 128.0}}
    assert got['frames']['work']['h'] == 900.0
    assert got['edges'] == {'chat/reply': [[1.0, 2.0], [3.3, 4.0]]}


def test_board_layout_only_owner_saves(tmp_path, monkeypatch):
    monkeypatch.setattr(prompt_store, 'root', lambda: tmp_path)
    monkeypatch.setattr(prompts_screen, 'resolve_owner_user_id', lambda: 'owner')
    with pytest.raises(HTTPException):
        asyncio.run(prompts_screen.save_board_layout(prompts_screen.BoardBody(), current_user=types.SimpleNamespace(user_id='x')))
