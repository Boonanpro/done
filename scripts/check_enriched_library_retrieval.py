"""Real Jev retrieval against the complete corpus; no voice or editor job."""
import asyncio
import json
import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT))
from app.services import reference_url_index as index
from scripts.enrich_production_library import OUT, save

CASES = [
    ('object_stop_motion', '食材ではない日用品を食材に見立てるストップモーション。物が別の物に変わる面白さと、調理の音の気持ちよさを参考にしたい。'),
    ('hardware_cgi', 'スマートフォンの内部構造を精密な3Dで見せつつ、実写の日常シーンにつなげる高品質な製品広告を参考にしたい。'),
    ('lighting_scene', '逆光やリムライトで人物を浮き立たせ、動きの速いスポーツをスローモーションと交互に見せる演出の参考区間が欲しい。'),
]


async def main():
    results = []
    for name, query in CASES:
        result = await index.search('2582a188-ff24-4a4f-b989-6063034d90b2', query,
                                    scope='technique' if name == 'lighting_scene' else 'work',
                                    limit=2, routing='genres', verify_matches=True, timeout=12)
        results.append({'case': name, 'query': query, **result})
        save(OUT / 'retrieval-check.json', results)
        print(json.dumps({'case': name, 'available': result.get('available'), 'ms': result.get('elapsed_ms'),
                          'selected': [{'id': r['id'], 'title': r.get('title')} for r in result.get('results', [])]},
                         ensure_ascii=False), flush=True)


if __name__ == '__main__': asyncio.run(main())
