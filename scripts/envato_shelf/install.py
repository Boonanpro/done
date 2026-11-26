"""Install the owner's private catalog and its rendered previews without distributing source templates."""
import argparse
import base64
import json
import os
from pathlib import Path
import sys
from tempfile import NamedTemporaryFile

sys.path.insert(0, str(Path(__file__).resolve().parents[2]))
from app.services import envato_shelf
from app.services.owner import resolve_owner_user_id


def save(path, data):
    with NamedTemporaryFile(dir=path.parent, delete=False) as stream:
        stream.write(data.encode())
    os.replace(stream.name, path)


def install(source):
    manifest = (source/'catalog.json').read_text()
    items = json.loads(manifest)
    owner = resolve_owner_user_id()
    if not owner or not items or len({i['id'] for i in items}) != len(items):
        raise ValueError('利用者または部品一覧を確認できません')
    gallery = []
    for item in items:
        if not Path(item['source']).is_file():
            raise FileNotFoundError(item['source'])
        row = envato_shelf.describe(item)
        for key, ext, mime in [('still','jpg','jpeg'), ('motion','webp','webp')]:
            image = (source/'previews'/(item['id']+'.'+ext)).read_bytes()
            row[key] = 'data:image/'+mime+';base64,'+base64.b64encode(image).decode('ascii')
        gallery.append(row)
    shelf = envato_shelf.SHELF
    shelf.mkdir(mode=0o700, parents=True, exist_ok=True)
    save(shelf/'owner', owner)
    save(shelf/'catalog.json', manifest)
    save(shelf/'gallery.json', json.dumps(gallery, ensure_ascii=False, separators=(',',':')))
    print(f'{len(items)}個の部品を登録しました')


if __name__ == '__main__':
    parser = argparse.ArgumentParser()
    parser.add_argument('source', type=Path)
    install(parser.parse_args().source)
