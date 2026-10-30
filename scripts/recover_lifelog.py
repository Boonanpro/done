"""Copy misplaced Mac lifelog audio to permanent storage. Never remove originals."""
import hashlib
import shutil
import sys
from pathlib import Path
sys.path.insert(0, str(Path(__file__).resolve().parents[1]))
from app.services import lifelog


def recover(roots, target):
    copied = 0
    for root in roots:
        for source in root.glob('*dan-lifelog*'):
            for audio in source.glob('20??-??-??/*.ogg'):
                dest = target / audio.parent.name / audio.name
                dest.parent.mkdir(parents=True, exist_ok=True)
                if dest.exists():
                    if hashlib.sha256(dest.read_bytes()).digest() != hashlib.sha256(audio.read_bytes()).digest():
                        raise RuntimeError(f'conflicting audio: {audio}')
                    continue
                temp = dest.with_suffix('.recovering')
                shutil.copy2(audio, temp)
                temp.replace(dest)
                copied += 1
    return copied


if __name__ == '__main__':
    home = Path.home()
    roots = [home / 'done', *list((home / 'dan-workspace' / 'releases').glob('*'))]
    print('copied:', recover(roots, lifelog.AUDIO_ROOT))
    old = home / 'done' / '.data' / 'lifelog'
    lifelog.INDEX_ROOT.mkdir(parents=True, exist_ok=True)
    for p in old.glob('*.jsonl'):
        dest = lifelog.INDEX_ROOT / p.name
        if not dest.exists():
            shutil.copy2(p, dest)
