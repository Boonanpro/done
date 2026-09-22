"""Editable direction primitives, not a fixed genre-to-template workflow."""
import json
import math
from pathlib import Path

ROOT = Path(__file__).resolve().parents[2]
CATALOG = ROOT / 'docs/direction-patterns.json'
PROGRAM = ROOT / 'app/static/direction-patterns.js'


def catalog():
    return json.loads(CATALOG.read_text(encoding='utf-8'))


async def search(user, request, dialogue):
    from app.services.editor_jev import judge
    rows = catalog()
    result = await judge(user, {'request': request, 'conversation': dialogue[-30:], 'patterns': rows}, {
        r['id']: {'type': 'score', 'instructions':
            f"演出 {r['id']}：{r['effect']} 注意：{r['avoid']}。会話の目的にこの演出が役立つか。題材の単語一致ではなく、見た人の理解や感情への効果で判断。禁止条件と矛盾すれば0。",
            'criteria': ['矛盾する', '関連が弱い', '組み合わせの一部として有効', '目的に強く合う']}
        for r in rows}, timeout=3.5)
    answers = result.get('answers', {})
    ranked = []
    for row in rows:
        score = answers.get(row['id'], {}).get('score')
        if isinstance(score, (int, float)) and math.isfinite(score) and 0 <= score <= 3:
            ranked.append({**row, 'score': score})
    ranked.sort(key=lambda r: -r['score'])
    return {'patterns': ranked or rows, 'ranking_available': result.get('available', False),
            'elapsed_ms': result['elapsed_ms'],
            'medium': '2D文字・図形の編集可能なモーショングラフィック。実写・人物生成・音声は含まない。',
            'note': '点数は演出の推薦であり完成品質の保証ではない。順序・内容・組み合わせは会話原文から決める。適さない場合は自由制作も可能。'}


def validate(plan):
    if not isinstance(plan, dict):
        raise ValueError('plan must be an object')
    beats = plan.get('beats')
    if not isinstance(beats, list) or not 1 <= len(beats) <= 12:
        raise ValueError('beats must contain 1..12 scenes')
    known = {r['id'] for r in catalog()}
    out = {'title': str(plan.get('title', '演出見本'))[:80], 'beats': []}
    for key, default in [('background', '#10191f'), ('foreground', '#f5f0df'), ('accent', '#b7e5ce')]:
        value = plan.get(key, default)
        import re
        if not isinstance(value, str) or not re.fullmatch(r'#[0-9a-fA-F]{6}', value):
            raise ValueError('Colors must be six-digit hex values')
        out[key] = value
    for beat in beats:
        if not isinstance(beat, dict) or beat.get('pattern') not in known:
            raise ValueError('Unknown direction pattern')
        duration = beat.get('duration', 4)
        pace = beat.get('pace', 1)
        for value, lo, hi in [(duration, 2, 12), (pace, .5, 2)]:
            if isinstance(value, bool) or not isinstance(value, (int, float)) or not math.isfinite(value) or not lo <= value <= hi:
                raise ValueError('Duration or pace outside allowed range')
        headline, detail = beat.get('headline', ''), beat.get('detail', '')
        if not isinstance(headline, str) or not 1 <= len(headline) <= 48 or not isinstance(detail, str) or len(detail) > 80:
            raise ValueError('Keep headline 1..48 and detail at most 80 characters')
        labels = beat.get('labels', [])
        if not isinstance(labels, list) or len(labels) > 5 or any(not isinstance(x, str) or not 1 <= len(x) <= 18 for x in labels):
            raise ValueError('labels must contain at most five short strings')
        required = {'compare': 2, 'gather': 2, 'path': 2, 'rhythm': 2}.get(beat['pattern'], 0)
        if len(labels) < required or (beat['pattern'] == 'compare' and len(labels) != 2):
            raise ValueError('Pattern requires meaningful labels')
        layout = beat.get('layout', 'center')
        if layout not in ('center', 'left'):
            raise ValueError('Unknown layout')
        out['beats'].append({'pattern': beat['pattern'], 'duration': duration, 'pace': pace,
                             'headline': headline, 'detail': detail, 'labels': labels, 'layout': layout})
    if sum(b['duration'] for b in out['beats']) > 120:
        raise ValueError('Preview exceeds 120 seconds')
    return out


def proposal(plan):
    params = validate(plan)
    return {'title': params['title'], 'kind': 'scene', 'scene': {
        'code': PROGRAM.read_text(encoding='utf-8'), 'duration': sum(b['duration'] for b in params['beats']),
        'width': 1280, 'height': 720, 'params': params,
        'description': '編集可能な演出の組み合わせ。完成映像の素材生成や音声は含まない。'}}


def preview(room, content, plan):
    from app.services.editor_presentation import present
    return present(room, content, [proposal(plan)])


PLAN_SCHEMA = {'type': 'object', 'description': '演出部品を任意の順序で組む。目的を固定のテンプレへ分類せず、会話に合わせて順序・間・文言を決める。数字や事実は原文にあるものだけ使う。',
    'properties': {'title': {'type': 'string'},
        **{k: {'type': 'string', 'description': '#RRGGBB'} for k in ('background', 'foreground', 'accent')},
        'beats': {'type': 'array', 'minItems': 1, 'maxItems': 12, 'items': {'type': 'object', 'properties': {
            'pattern': {'type': 'string', 'enum': ['reveal', 'compare', 'gather', 'path', 'focus', 'rhythm']},
            'duration': {'type': 'number', 'minimum': 2, 'maximum': 12},
            'headline': {'type': 'string', 'maxLength': 48}, 'detail': {'type': 'string', 'maxLength': 80},
            'labels': {'type': 'array', 'description': 'compareは必ず2項目。gather/path/rhythmは必ず2〜5項目。reveal/focusでは不要。', 'items': {'type': 'string', 'minLength': 1, 'maxLength': 18}, 'maxItems': 5},
            'pace': {'type': 'number', 'minimum': .5, 'maximum': 2},
            'layout': {'type': 'string', 'enum': ['center', 'left']}}, 'required': ['pattern', 'duration', 'headline']}}}, 'required': ['title', 'beats']}
