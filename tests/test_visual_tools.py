"""Pictures Dan shows in the chat (2026-11-16): a browser screenshot with red rings and arrows, a drawn scene, and the
result of page_clip / draw_picture reaching Dan (they came back as 「完了」 only)."""
import io

from PIL import Image

from app.agent.v2.tools import format_tool_result, get_all_skill_tools, parse_tool_name
from app.services import browser_mark


def _png(w, h):
    buf = io.BytesIO()
    Image.new('RGB', (w, h), (255, 255, 255)).save(buf, 'PNG')
    return buf.getvalue()


def test_rings_follow_the_picture_scale_not_an_assumed_pixel_ratio():
    # a 2x screenshot of a 400-wide page: the ring around a box at x=100..200 lands at 200..400 in the picture
    out = Image.open(io.BytesIO(browser_mark.draw_marks(_png(800, 600), 400, [{'x': 100, 'y': 100, 'w': 100, 'h': 40}], ['ここ'])))
    assert out.size == (800, 600)
    px = out.load()
    red = lambda p: p[0] > 200 and p[1] < 80 and p[2] < 80
    left_edge = [x for x in range(150, 260) if red(px[x, 240])]
    assert left_edge and 180 <= left_edge[0] <= 200          # 100*2 - 7*2 padding
    assert not red(px[300, 240])                              # inside the ring stays as it was


def test_a_missing_target_draws_nothing():
    out = Image.open(io.BytesIO(browser_mark.draw_marks(_png(400, 300), 400, [None], [''])))
    assert all(p == (255, 255, 255) for p in out.getdata())


def test_tools_are_offered_and_routed():
    tools = {t['name']: t for t in get_all_skill_tools()}
    assert 'draw_picture' in tools and parse_tool_name('draw_picture') == ('_draw_picture', 'create')
    browser = tools['browser']['input_schema']['properties']
    assert 'mark' in browser['action']['enum'] and 'marks' in browser


def test_value_results_reach_dan():
    text = format_tool_result({'success': True, 'url': 'https://example.com', 'crop': '/api/v1/files/clip-a.png'}, '_page_clip', 'read').text
    assert '/api/v1/files/clip-a.png' in text
    f = format_tool_result({'success': True, 'url': '/api/v1/files/draw-a.png', 'screenshot_base64': 'aGk='}, '_draw_picture', 'create')
    assert '/api/v1/files/draw-a.png' in f.text and 'aGk=' not in f.text and len(f.images) == 1
