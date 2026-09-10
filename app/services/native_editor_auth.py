"""Persist a renewable desktop login only after an authenticated launch."""
from pathlib import Path
import os
import uuid

from app.services.auth_service import create_token_pair


def prepare_login(user):
    pair = create_token_pair(user.user_id, user.email, remember_me=True)
    folder = Path(os.environ.get('USERPROFILE') or Path.home()) / '.done'
    folder.mkdir(parents=True, exist_ok=True)
    # Refresh credentials stay on the desktop; never put them in a deep-link URL.
    for name, value in [('native_refresh_token.txt', pair.refresh_token),
                        ('native_token.txt', pair.access_token)]:
        temporary = folder / (name + '.' + uuid.uuid4().hex + '.tmp')
        temporary.write_text(value, encoding='utf-8')
        temporary.replace(folder / name)
    return pair.access_token
