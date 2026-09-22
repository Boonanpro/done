"""Provision an owner's command-center project and the local Atom destination.

Run from the Dan repository: python devices/atom-echo-s3r/setup_command_center.py --user-id UUID
Uses the existing local Dan database configuration. Never copies credentials.
Restart the audio bridge and headless controller after changing the destination.
"""
import argparse
import asyncio
import json
from pathlib import Path
import sys
from uuid import UUID

ROOT = Path(__file__).resolve().parents[2]
sys.path.insert(0, str(ROOT))
from app.services.command_center import INSTRUCTIONS
from app.services.project_service import ProjectService


async def provision(user_id: str):
    service = ProjectService()
    rows = await service.list_projects(user_id)
    hubs = [p for p in rows if (p.get('metadata') or {}).get('role') == 'command_center']
    if len(hubs) > 1:
        raise RuntimeError('Multiple command centers exist; resolve before pairing')
    project = hubs[0] if hubs else await service.create_project(
        user_id, 'ダンの司令塔', description=INSTRUCTIONS, metadata={'role': 'command_center'})
    await service.update_project(project['id'], user_id, pinned=True, icon='🧭')
    destination = {k: project[k] for k in ('room_id', 'title')}
    destination['project_id'] = project['id']
    config = ROOT / '.tmp/atom-voice-room.json'
    config.parent.mkdir(parents=True, exist_ok=True)
    temporary = config.with_suffix('.new')
    temporary.write_text(json.dumps(destination, ensure_ascii=False), encoding='utf-8')
    temporary.replace(config)
    print('https://dan.paina.info/chat/' + project['id'])


if __name__ == '__main__':
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument('--user-id', type=UUID, required=True)
    asyncio.run(provision(str(parser.parse_args().user_id)))
