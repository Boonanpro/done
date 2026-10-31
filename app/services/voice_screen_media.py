"""Private screen observations. Unlike shareable attachments, these require room access."""
import re
import uuid
from pathlib import Path
from app.services.voice_calls import ROOT, _name

URL = re.compile(r'^/api/v1/voicelog/stage/[A-Za-z0-9_-]{1,100}/image/[a-f0-9]{32}\.(png|jpg|webp|mjpeg)$')

def directory(room): return ROOT / (_name(room)+'.screens')

def store(room, data, mime):
    suffix={'image/png':'png','image/jpeg':'jpg','image/webp':'webp'}.get(mime)
    if not suffix or not room or len(data)>12_000_000: return ''
    folder=directory(room);folder.mkdir(parents=True,exist_ok=True)
    name=uuid.uuid4().hex+'.'+suffix
    (folder/name).write_bytes(data)
    return '/api/v1/voicelog/stage/'+_name(room)+'/image/'+name
