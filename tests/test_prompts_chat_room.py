"""指示文の画面の会話の部屋（/prompts/chat）: 初めて開いた時に1つ作り、あとは同じ部屋を返す。消えていたら作り直す。"""
import asyncio
import types

from app.api import prompts_screen
from app.services import prompt_store


class FakeService:
    made = []
    alive = set()

    async def get_project(self, project_id, user_id):
        return {'id': project_id, 'room_id': f'room-{project_id}'} if project_id in self.alive else None

    async def create_project(self, user_id, title, description=None, origin_room_id=None, metadata=None):
        pid = f'p{len(self.made) + 1}'
        self.made.append({'title': title, 'description': description, 'origin': origin_room_id, 'metadata': metadata})
        self.alive.add(pid)
        return {'id': pid, 'room_id': f'room-{pid}'}


def test_chat_room_made_once_and_remade_when_gone(tmp_path, monkeypatch):
    monkeypatch.setattr(prompt_store, 'root', lambda: tmp_path)
    import app.services.project_service as ps
    FakeService.made, FakeService.alive = [], set()
    monkeypatch.setattr(ps, 'ProjectService', FakeService)
    user = types.SimpleNamespace(user_id='u1')

    first = asyncio.run(prompts_screen.prompts_chat_room(current_user=user))
    again = asyncio.run(prompts_screen.prompts_chat_room(current_user=user))
    assert first['room_id'] == again['room_id'] == 'room-p1'
    assert len(FakeService.made) == 1
    made = FakeService.made[0]
    assert made['metadata'] == {'hidden': True}
    assert made['origin'] == prompts_screen.DEV_LEAD_ROOM
    assert 'scripts/prompts.py save' in made['description']

    FakeService.alive.clear()   # 部屋が消された
    third = asyncio.run(prompts_screen.prompts_chat_room(current_user=user))
    assert third['room_id'] == 'room-p2'


def test_sha_matches_item(monkeypatch):
    pid = prompt_store.catalog()['prompts'][0]['id']
    assert prompts_screen._sha(pid)['sha'] == prompts_screen._item(pid)['sha']
