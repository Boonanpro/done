"""Small real Jev selection check; does not create videos or voice sessions."""
import asyncio
import json
from pathlib import Path
from app.services.editor_consultation_sheet import update
from app.services.editor_production_handoff import select

async def main():
    rows = []
    for kind, subject, expected in [
        ('実写風の2分映画', '27歳の主人公が自宅の作業場で空飛ぶ車を開発する', 'story'),
        ('アニメ解説', '小学生に火山が噴火する仕組みを説明する', 'explanation'),
        ('モーショングラフィックスのローンチ動画', '新しい動画編集サービスの魅力を伝える', 'launch'),
    ]:
        values = dict(video_type=kind, subject=subject, platform='YouTube', purpose='視聴者に楽しんでもらう',
                      audience='一般視聴者', duration='2分', materials='AIで制作', references='参考の方向に合意済み')
        sheet = update(None, [dict(field=k, status='confirmed', value=v) for k,v in values.items()], True)
        result = (await select(sheet, None, '2582a188-ff24-4a4f-b989-6063034d90b2'))['production_handoff']
        rows.append(dict(case=kind, expected=expected, status=result['status'], workflow=result.get('workflow'),
                         elapsed_ms=result['elapsed_ms'], passed=result.get('workflow') == expected))
    path=Path('scratch/editor-production-handoff/result.json')
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(json.dumps(rows, ensure_ascii=False, indent=2), encoding='utf-8')
    print(json.dumps(rows, ensure_ascii=False))
    assert all(row['passed'] for row in rows)

if __name__ == '__main__':
    asyncio.run(main())
