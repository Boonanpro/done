"""An extensible method catalog, not a list of permitted video genres."""
import json
from pathlib import Path

CATALOG = Path(__file__).resolve().parents[2] / 'docs' / 'production-methods.json'


def read(method_id=None):
    catalog = json.loads(CATALOG.read_text(encoding='utf-8'))
    if method_id:
        methods = [m for m in catalog['methods'] if m['id'] == method_id]
        if not methods:
            return {'ok':False, 'error':'未登録の制作方法です。検索・資料確認・短い実行検証を行い、新しい手段を追加できます。'}
        return {'ok':True, 'methods':methods, 'principles':catalog['principles']}
    return {'ok':True, 'principles':catalog['principles'], 'methods':[
        {k:m[k] for k in ('id','purpose','readiness')} for m in catalog['methods']]}
