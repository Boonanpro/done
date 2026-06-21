"""Exhaustive isolation test: prove that for EVERY kind of revision edit, ONLY the
intended field of the intended clip changes — everything else (other clips AND other
fields of the same clip) is preserved byte-identical."""
import sys, json, copy
from pathlib import Path
sys.path.insert(0, str(Path(__file__).resolve().parent.parent))
from app.api import production_asset_routes as P

def base_seq():
    return {
        "version": 1, "format": "9:16", "duration": 30.0,
        "tracks": [
            {"id": "video_1", "type": "video", "clips": [
                {"id": "v1", "track": "video", "timeline_start": 0, "timeline_end": 10, "source_start": 0, "source_end": 10, "link_id": "L1"},
                {"id": "v2", "track": "video", "timeline_start": 10, "timeline_end": 20, "source_start": 10, "source_end": 20, "link_id": "L2"},
            ]},
            {"id": "caption_1", "type": "caption", "clips": [
                {"id": "c1", "track": "caption", "text": "一つ目", "timeline_start": 0, "timeline_end": 10,
                 "style": {"color": "#FF0000", "fontSize": 1.6, "bold": True}},
                {"id": "c2", "track": "caption", "text": "二つ目", "timeline_start": 10, "timeline_end": 20,
                 "style": {"color": "#00FF00"}},
                {"id": "c3", "track": "caption", "text": "三つ目", "timeline_start": 20, "timeline_end": 30},
            ]},
            {"id": "audio_1", "type": "audio", "clips": [
                {"id": "a1", "track": "audio", "timeline_start": 0, "timeline_end": 10, "source_start": 0, "source_end": 10, "link_id": "L1"},
            ]},
        ],
    }

def all_clips(seq):
    return {c["id"]: c for t in seq["tracks"] for c in t.get("clips", [])}

def diff(before, after):
    """Return {clip_id: {field: (old,new)}} for everything that changed."""
    out = {}
    ba, aa = all_clips(before), all_clips(after)
    for cid in set(ba) | set(aa):
        b, a = ba.get(cid), aa.get(cid)
        if b is None:
            out[cid] = {"__added__": a}; continue
        if a is None:
            out[cid] = {"__removed__": True}; continue
        fd = {}
        for k in set(b) | set(a):
            if json.dumps(b.get(k), sort_keys=True, ensure_ascii=False) != json.dumps(a.get(k), sort_keys=True, ensure_ascii=False):
                fd[k] = (b.get(k), a.get(k))
        if fd:
            out[cid] = fd
    return out

PASS = True
def check(name, seq, patch, allowed, expect_changed):
    """expect_changed: {clip_id: set(fields)} that ARE allowed to change. Anything else fails."""
    global PASS
    before = copy.deepcopy(seq)
    after = P._merge_revision_patch(seq, patch, allowed)
    d = diff(before, after)
    # remove sequence-level duration (recomputed) — compare clip-level only
    illegal = {}
    for cid, fields in d.items():
        allowed_fields = expect_changed.get(cid)
        if allowed_fields is None:
            illegal[cid] = fields  # this clip should not have changed at all
            continue
        extra = {k: v for k, v in fields.items() if k not in allowed_fields and k not in ("__added__", "__removed__")}
        if extra:
            illegal[cid] = extra
    ok = not illegal
    PASS = PASS and ok
    print(f"[{'PASS' if ok else 'FAIL'}] {name}")
    if not ok:
        print("    leaked changes:", json.dumps(illegal, ensure_ascii=False)[:300])

# 1. style: change only position of c1 -> color/fontSize/bold preserved
check("style position only -> color/size kept", base_seq(),
      {"edits": [{"id": "c1", "style": {"position": "center"}}]}, {"c1"},
      {"c1": {"style"}})  # style field changes but we verify content below
# deeper: ensure c1 still has color red
s = all_clips(P._merge_revision_patch(base_seq(), {"edits":[{"id":"c1","style":{"position":"center"}}]}, {"c1"}))["c1"]["style"]
assert s.get("color") == "#FF0000" and s.get("fontSize") == 1.6 and s.get("position") == "center", s
print("    -> c1.style =", s)

# 2. text only: change c2 text -> its style untouched, others untouched
check("text only -> style + others untouched", base_seq(),
      {"edits": [{"id": "c2", "text": "二つ目（修正）"}]}, {"c2"},
      {"c2": {"text"}})

# 3. timing only: trim v1 end -> source/link/others untouched
check("timeline_end only -> other fields untouched", base_seq(),
      {"edits": [{"id": "v1", "timeline_end": 8}]}, {"v1"},
      {"v1": {"timeline_end"}})

# 4. remove c3 -> only c3 gone, others identical
check("remove c3 -> others identical", base_seq(),
      {"edits": [{"id": "c3", "remove": True}]}, {"c3"},
      {"c3": {"__removed__"}})

# 5. out-of-scope guard: try to edit c2 but it's NOT allowed -> nothing changes
check("out-of-scope edit ignored", base_seq(),
      {"edits": [{"id": "c2", "text": "改ざん"}]}, {"c1"},
      {})  # nothing should change

# 6. illegal id: edit non-existent clip -> nothing changes
check("unknown id ignored", base_seq(),
      {"edits": [{"id": "ZZZ", "text": "x"}]}, {"ZZZ"},
      {})

# 7. new caption: add one -> only an addition, no existing clip touched
res = P._merge_revision_patch(base_seq(), {"new_captions": [{"text": "追加", "timeline_start": 5, "timeline_end": 7}]}, set(all_clips(base_seq())))
d = diff(base_seq(), res)
added = [k for k, v in d.items() if "__added__" in v]
touched = [k for k, v in d.items() if "__added__" not in v]
ok7 = len(added) == 1 and not touched
PASS = PASS and ok7
print(f"[{'PASS' if ok7 else 'FAIL'}] new caption -> only an addition, nothing else touched")

print("\n" + ("ALL ISOLATION TESTS PASS — only the intended field of the intended clip changes" if PASS else "SOME TESTS FAILED"))
sys.exit(0 if PASS else 1)
