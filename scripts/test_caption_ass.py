"""Unit test for caption ASS styling + line-wrapping (Stage 1C).
Verifies: unstyled captions stay identical to before, long captions wrap with \\N,
styled captions get inline override (color/size/position)."""
import sys, tempfile
from pathlib import Path
sys.path.insert(0, str(Path(__file__).resolve().parent.parent))
from app.api import production_asset_routes as P

W, H = 720, 1280
NL = chr(92) + "N"  # the literal ASS line-break token \N

def dialogue(path):
    return [l for l in path.read_text(encoding="utf-8").splitlines() if l.startswith("Dialogue")][0]

# 1) unstyled short caption -> no override braces, no wrap
p1 = Path(tempfile.gettempdir()) / "cap_plain.ass"
P._write_caption_ass(p1, [{"text": "短いテロップ", "timeline_start": 1.0, "timeline_end": 3.0}], W, H)
d1 = dialogue(p1)
print("[plain]", d1)
assert "{" not in d1, "unstyled must have no override braces"
assert d1.endswith("短いテロップ"), "unstyled text changed"
assert NL not in d1, "short caption should not wrap"
print("  OK: unstyled identical, no wrap")

# 2) very long Japanese caption -> wraps with \N
longtext = "サロンボードへのスタイル投稿は毎回スタイル名やコメントやハッシュタグを考えるのが本当に大変で時間がかかります"
p2 = Path(tempfile.gettempdir()) / "cap_long.ass"
P._write_caption_ass(p2, [{"text": longtext, "timeline_start": 1.0, "timeline_end": 5.0}], W, H)
d2 = dialogue(p2)
nbreaks = d2.count(NL)
print(f"[long] breaks={nbreaks}:", d2[:130])
assert nbreaks >= 1, "long caption not wrapped"
# each visual line should be within budget (rough: count CJK chars per line)
print("  OK: long caption wrapped")

# 3) styled caption (red, 1.5x, top) -> inline override present
p3 = Path(tempfile.gettempdir()) / "cap_styled.ass"
P._write_caption_ass(p3, [{"text": "赤いテロップ", "timeline_start": 1.0, "timeline_end": 3.0,
                           "style": {"color": "#FF0000", "fontSize": 1.5, "position": "top"}}], W, H)
d3 = dialogue(p3)
print("[styled]", d3)
assert d3.startswith("Dialogue: 0,") and "{" in d3, "styled must have override braces"
body = d3.split(",", 9)[9]  # text is the 10th field
assert body.startswith("{"), f"override must prefix the text: {body}"
assert (chr(92) + "c") in body, "color override missing"
assert (chr(92) + "an8") in body, "top position override missing"
assert (chr(92) + "fs") in body, "fontsize override missing"
# verify red maps to ASS &H000000FF (BGR of FF0000)
assert "&H000000FF" in body, f"red color wrong: {body}"
print("  OK: style override (color/size/top) correct, red->&H000000FF")

# 4) color helper sanity
assert P._hex_to_ass_color("#FF0000") == "&H000000FF"
assert P._hex_to_ass_color("#FFFFFF") == "&H00FFFFFF"
assert P._hex_to_ass_color("#00FF00") == "&H0000FF00"
print("  OK: _hex_to_ass_color BGR reversal")

print("\nALL CAPTION ASS UNIT TESTS PASS")
