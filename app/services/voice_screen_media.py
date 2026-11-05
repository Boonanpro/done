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


def local_file(url):
    """The file on this machine behind one of the stage's image addresses, or None."""
    url = str(url or '')
    if URL.match(url):
        room, name = url.split('/')[-3], url.split('/')[-1]
        path = ROOT / (room + '.screens') / name
        return path if path.is_file() else None
    if url.startswith('/api/v1/files/'):
        from app.api.file_routes import UPLOAD_DIR
        path = (UPLOAD_DIR / url.rsplit('/', 1)[-1]).resolve()
        return path if path.is_relative_to(UPLOAD_DIR.resolve()) and path.is_file() else None
    return None


def blank(url):
    """Is the picture one flat colour (a white page still loading, a black phone screen)? In the 2026-11-05 0:59 call
    five of the eight screens shown were such pictures. A stream, a remote address or an unreadable file is not judged."""
    path = local_file(url)
    if path is None or path.suffix == '.mjpeg':
        return False
    try:
        from PIL import Image, ImageStat
        with Image.open(path) as image:
            small = image.convert('L').resize((64, 64))
        return ImageStat.Stat(small).stddev[0] < 3.0
    except Exception:
        return False
