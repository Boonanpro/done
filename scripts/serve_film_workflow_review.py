"""Read-only review of saved film-workflow evidence. No live-server restart."""
import json
import mimetypes
from pathlib import Path
from http.server import BaseHTTPRequestHandler, ThreadingHTTPServer
from urllib.request import urlopen

ROOT = Path(__file__).resolve().parents[1]
OUT = ROOT / 'scratch' / 'film-plan-dialogue'


class Handler(BaseHTTPRequestHandler):
    def do_GET(self):
        path = self.path.split('?', 1)[0]
        if path == '/':
            file = OUT / 'review.html'
        elif path == '/scene.js':
            file = ROOT / 'app/static/editor-scene.js'
        elif path == '/data.json':
            owner = json.loads((OUT / 'result.json').read_text(encoding='utf-8'))['owner']
            contents = json.loads((ROOT / 'uploads/production-assets' / owner['room_id'] / 'contents.json').read_text(encoding='utf-8'))
            content = next(c for c in contents if c['id'] == owner['content_id'])
            items = {i['id']: i for p in content.get('proposal_history', []) for i in p.get('items', [])}
            self.respond(json.dumps({'plan': content['film_plan'], 'items': items}, ensure_ascii=False).encode(), 'application/json')
            return
        elif path.startswith('/api/v1/editor-assistant/scene-vendor/'):
            name = path.rsplit('/', 1)[-1]
            if name not in ('three.module.min.js', 'three.core.min.js', 'gsap.min.js'):
                self.send_error(404); return
            try:
                with urlopen('http://127.0.0.1:8000' + path, timeout=15) as r:
                    self.respond(r.read(), 'application/javascript')
            except Exception:
                self.send_error(503, 'Scene dependency unavailable')
            return
        else:
            self.send_error(404); return
        self.respond(file.read_bytes(), mimetypes.guess_type(file.name)[0] or 'application/octet-stream')

    def respond(self, data, mime):
        self.send_response(200)
        self.send_header('Content-Type', mime + '; charset=utf-8')
        self.send_header('Content-Length', str(len(data)))
        self.send_header('Cache-Control', 'no-store')
        self.send_header('Access-Control-Allow-Origin', '*')
        self.end_headers(); self.wfile.write(data)


if __name__ == '__main__':
    ThreadingHTTPServer(('127.0.0.1', 8766), Handler).serve_forever()
