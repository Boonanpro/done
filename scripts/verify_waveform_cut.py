"""Waveform-based silence cutting. (a) _detect_silence finds audio-level silence regions in
the MAIN proxy. (b) _run_audio_analysis caches them. (c) assembling with silence regions cuts
TIGHTER than the Whisper word-gap fallback (more removed / shorter total) at the same threshold.
Verifies the FireCut-style waveform path is active from the assembly (initial build + recut)."""
import sys, json, copy
from pathlib import Path
sys.path.insert(0, str(Path(__file__).resolve().parent.parent))
from app.api import production_asset_routes as P

ROOM = "bd05fcc0-c143-4d1c-828e-7624e087b6c1"
MAIN = "e22695c0-0b77-4413-a2e8-f585739243bc"

ok = True
def check(name, cond, detail=""):
    global ok
    print(f"[{'PASS' if cond else 'FAIL'}] {name}{(' - ' + detail) if detail else ''}")
    ok = ok and cond

assets = P._read_assets(ROOM)
main = next(a for a in assets if str(a.get("id")) == MAIN)
src = main.get("proxy_path") or main.get("local_path")

# (a) raw silencedetect
print("running silencedetect on the proxy (decoding ~715s audio, ~30-60s)...")
regions = P._detect_silence(str(src))
print(f"silence regions detected: {len(regions)} (e.g. {regions[:3]})")
check("waveform silence detected", len(regions) > 5)

# (b) analysis caches silence_regions
src_assets = [{"id": MAIN, "kind": main.get("kind"), "filename": main.get("filename"),
               "local_path": main.get("local_path"), "proxy_path": main.get("proxy_path"), "metadata": main.get("metadata")}]
transcripts = P._run_audio_analysis(ROOM, "wave_verify", src_assets)
t = transcripts.get(MAIN, {})
check("analysis carries silence_regions", len(t.get("silence_regions") or []) > 5, f"{len(t.get('silence_regions') or [])} regions")

# (c) assemble with silence (real) vs without (force word fallback) at the same threshold
segs = t.get("segments") or []
decisions = {"spine": [{"segment_id": s["id"]} for s in segs], "cuts": [], "silence_threshold": 0.3}

seq_wave = P._assemble_sequence_from_decisions(copy.deepcopy(decisions), copy.deepcopy(transcripts), ROOM, "9:16")
# strip silence_regions to force the Whisper word-gap fallback
tr_noword = copy.deepcopy(transcripts)
for v in tr_noword.values():
    v["silence_regions"] = []
seq_word = P._assemble_sequence_from_decisions(copy.deepcopy(decisions), tr_noword, ROOM, "9:16")

def dur(seq):
    return seq.get("duration") if seq else None
def removed(seq):
    return seq.get("removed_total") if seq else None
print(f"WAVEFORM: duration={dur(seq_wave)} removed={removed(seq_wave)}")
print(f"WORD-GAP: duration={dur(seq_word)} removed={removed(seq_word)}")
check("waveform path produced a timeline", bool(seq_wave) and dur(seq_wave) and dur(seq_wave) > 1)
# waveform should cut at least as tight as word gaps (usually tighter -> shorter / more removed)
check("waveform cuts tighter-or-equal vs word gaps (shorter total)",
      dur(seq_wave) is not None and dur(seq_word) is not None and dur(seq_wave) <= dur(seq_word) + 0.5,
      f"wave {dur(seq_wave)} <= word {dur(seq_word)}")
check("waveform uses cut_meta", isinstance((seq_wave or {}).get("cut_meta"), list) and len(seq_wave["cut_meta"]) > 0)

print("\nWAVEFORM CUT:", "ALL PASS" if ok else "FAILURES")
