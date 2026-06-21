"""Unit test for Stage 3 partial-edit merge: _clips_in_scope + _merge_revision_patch.
Asserts out-of-scope clips are preserved verbatim, edits apply, removes drop, the
out-of-scope guard ignores illegal edits, and new captions insert."""
import sys
from pathlib import Path
sys.path.insert(0, str(Path(__file__).resolve().parent.parent))
from app.api import production_asset_routes as P

seq = {
    "version": 1, "format": "9:16", "duration": 30.0,
    "tracks": [
        {"id": "video_1", "type": "video", "clips": [
            {"id": "v1", "track": "video", "timeline_start": 0, "timeline_end": 10, "source_start": 0, "source_end": 10},
            {"id": "v2", "track": "video", "timeline_start": 10, "timeline_end": 20, "source_start": 10, "source_end": 20},
            {"id": "v3", "track": "video", "timeline_start": 20, "timeline_end": 30, "source_start": 20, "source_end": 30},
        ]},
        {"id": "caption_1", "type": "caption", "clips": [
            {"id": "c1", "track": "caption", "text": "最初", "timeline_start": 0, "timeline_end": 10},
            {"id": "c2", "track": "caption", "text": "途中", "timeline_start": 10, "timeline_end": 20},
            {"id": "c3", "track": "caption", "text": "最後", "timeline_start": 20, "timeline_end": 30},
        ]},
    ],
}

# scope = a region 10-20s -> only v2, c2 in scope
regions = [{"start": 10, "end": 20, "intent": "comment"}]
allowed = P._clips_in_scope(seq, regions)
print("in-scope ids:", sorted(allowed), "(expect v2,c2)")
assert allowed == {"v2", "c2"}, allowed

# patch: recolor c2 + try to ILLEGALLY edit c1 (out of scope) + remove v2
patch = {
    "edits": [
        {"id": "c2", "text": "途中（赤）", "style": {"color": "#FF0000"}},
        {"id": "c1", "text": "改ざん（不正）"},  # out-of-scope -> must be ignored
        {"id": "v2", "remove": True},
    ],
}
merged = P._merge_revision_patch(seq, patch, allowed)
caps = {c["id"]: c for t in merged["tracks"] if t["type"] == "caption" for c in t["clips"]}
vids = {c["id"]: c for t in merged["tracks"] if t["type"] == "video" for c in t["clips"]}

# c2 edited
assert caps["c2"]["text"] == "途中（赤）" and caps["c2"]["style"]["color"] == "#FF0000", "c2 not edited"
print("OK: in-scope caption edited (text+style)")
# c1 untouched (guard) — same object content as original
assert caps["c1"]["text"] == "最初", f"out-of-scope c1 was mutated: {caps['c1']}"
print("OK: out-of-scope c1 preserved (guard blocked illegal edit)")
# c3 verbatim
assert caps["c3"]["text"] == "最後", "c3 changed"
# v2 removed, v1/v3 preserved
assert "v2" not in vids and "v1" in vids and "v3" in vids, f"video remove wrong: {list(vids)}"
print("OK: in-scope video removed, others preserved")
# v1/v3 identical to originals
assert vids["v1"]["timeline_end"] == 10 and vids["v3"]["timeline_start"] == 20
print("OK: untouched clips byte-identical")

# global instruction (no region) -> all in scope
allowed_all = P._clips_in_scope(seq, [])
assert allowed_all == {"v1", "v2", "v3", "c1", "c2", "c3"}
print("OK: no region => global scope")

# new caption insertion
patch2 = {"edits": [], "new_captions": [{"text": "追加テロップ", "timeline_start": 5, "timeline_end": 8}]}
merged2 = P._merge_revision_patch(seq, patch2, allowed_all)
cap_texts = [c["text"] for t in merged2["tracks"] if t["type"] == "caption" for c in t["clips"]]
assert "追加テロップ" in cap_texts and len(cap_texts) == 4, cap_texts
print("OK: new caption inserted")

print("\nALL REVISION-MERGE UNIT TESTS PASS")
