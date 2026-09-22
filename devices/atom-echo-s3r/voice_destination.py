"""One local destination shared by the controller and audio bridge."""
import json
from pathlib import Path
from uuid import UUID

CONFIG = Path(__file__).resolve().parents[2] / '.tmp/atom-voice-room.json'
destination = json.loads(CONFIG.read_text(encoding='utf-8')) if CONFIG.exists() else {
    'room_id': '14d138aa-9499-4f51-b752-d088d12b5c59', 'title': '音声デバイステスト',
}
ROOM = str(UUID(destination['room_id']))
TITLE = destination['title']
