"""Fast unit test of _assemble_sequence_from_decisions (no LLM): feed synthetic
DECISIONS + transcript referencing the real StyleUp assets and assert the assembled
timeline has correct tracks/clips/timing/PiP/caption-suppression/blur mapping."""
import sys, json
from pathlib import Path
sys.path.insert(0, str(Path(__file__).resolve().parent.parent))

from app.api import production_asset_routes as P

ROOM = "bd05fcc0-c143-4d1c-828e-7624e087b6c1"
MAIN = "e22695c0-0b77-4413-a2e8-f585739243bc"   # talking head
SCREEN = "535e2cc4-e200-40c3-b8f1-ade7c5cd3833" # screen recording

transcripts = {
    MAIN: {"asset_id": MAIN, "asset_index": 1, "duration": 90.0, "segments": [
        {"id": "a1_s01", "asset_id": MAIN, "start": 0.0, "end": 5.0, "text": "サロンボードへの投稿、めんどくないですか？"},
        {"id": "a1_s02", "asset_id": MAIN, "start": 5.5, "end": 12.0, "text": "スタイル名やタグを毎回考えるの大変ですよね"},
        {"id": "a1_s03", "asset_id": MAIN, "start": 12.5, "end": 20.0, "text": "このツールで解決できます。実際の画面で見せます"},
    ], "dead_air": [], "restatements": []},
    SCREEN: {"asset_id": SCREEN, "asset_index": 2, "duration": 140.0, "segments": [], "dead_air": [], "restatements": []},
}

decisions = {
    "spine": [
        {"segment_id": "a1_s01", "caption": None},
        {"segment_id": "a1_s02", "caption": "スタイル名・タグを毎回考えるの大変"},
        {"segment_id": "a1_s03", "caption": None},
    ],
    "screen_overlays": [
        {"screen_asset_id": SCREEN, "screen_source_start": 10.0, "screen_source_end": 30.0,
         "from_segment": "a1_s02", "to_segment": "a1_s03", "main_as_pip": True},
    ],
    "blur": [
        {"asset_id": SCREEN, "region": {"x": 0.1, "y": 0.2, "width": 0.8, "height": 0.1},
         "source_start": 15.0, "source_end": 22.0, "style": "soft"},
    ],
    "pacing_gap": 0.3,
}

seq = P._assemble_sequence_from_decisions(decisions, transcripts, ROOM, "9:16")
assert seq, "no sequence produced"
tracks = {t["type"]: t["clips"] for t in seq["tracks"]}
print("duration:", seq["duration"])
for t in seq["tracks"]:
    print(f"  {t['type']}: {len(t['clips'])} clips")

# Assertions
video, overlay, caption, audio, effect = (tracks["video"], tracks["overlay"], tracks["caption"], tracks["audio"], tracks["effect"])

# a1_s01 not covered -> fullscreen main on video; a1_s02/a1_s03 covered -> PiP on overlay
main_fs = [c for c in video if c.get("role") == "main"]
assert len(main_fs) == 1 and main_fs[0]["composition"] == "fullscreen", f"expected 1 fullscreen main, got {len(main_fs)}"
screen_bg = [c for c in video if c.get("role") == "screen"]
assert len(screen_bg) == 1 and screen_bg[0]["composition"] == "background", "expected 1 screen background clip"
assert len(overlay) == 2 and all(c["composition"] == "pip" and c.get("position") for c in overlay), "expected 2 PiP overlay clips with position"

# captions only for the non-covered segment (a1_s01)
assert len(caption) == 1, f"expected 1 caption (covered segments suppressed), got {len(caption)}"
assert "めんどく" in caption[0]["text"], "caption text mismatch"

# audio: 3 continuous dialogue clips from MAIN
assert len(audio) == 3 and all(c["asset_id"] == MAIN and c["role"] == "dialogue" for c in audio), "audio should be 3 main dialogue clips"

# timeline monotonic + gap
starts = [c["timeline_start"] for c in audio]
assert starts == sorted(starts), "audio not monotonic"

# blur mapped into the overlay span (not 0..total)
assert len(effect) == 1, "expected 1 blur effect"
e = effect[0]
span_start = screen_bg[0]["timeline_start"]; span_end = screen_bg[0]["timeline_end"]
assert span_start <= e["timeline_start"] < e["timeline_end"] <= span_end + 0.01, \
    f"blur not mapped into overlay span: blur={e['timeline_start']}-{e['timeline_end']} span={span_start}-{span_end}"
print(f"  blur mapped to {e['timeline_start']:.2f}-{e['timeline_end']:.2f} within screen span {span_start:.2f}-{span_end:.2f}")

# screen background spans exactly a1_s02..a1_s03
assert abs(screen_bg[0]["timeline_start"] - overlay[0]["timeline_start"]) < 0.01, "screen bg start != first PiP start"

print("\nPASS: assembler produces correct timeline (PiP swap, caption suppression, continuous main audio, blur mapping)")
