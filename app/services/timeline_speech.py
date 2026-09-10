"""Narration synthesis for the timeline tools.

`synthesize(text, out_path, voice="owner")` produces a wav in the caller's own
(cloned) voice entry point is retired: Qwen3-TTS is disabled at user request.
Existing narration assets remain usable; no alternate provider is selected automatically.

Voice profiles live in uploads/voice/<name>/{profile.json, ref.wav}; "owner" is the
user's cloned voice (17s reference). A profile is machine-local (uploads is not in git).
"""

from __future__ import annotations

import json
import os
import re
import sys
import time
from pathlib import Path
from typing import Any


ROOT = Path(__file__).resolve().parents[2]
VENV_PY = ROOT / "venv_tts" / "Scripts" / "python.exe"
SCRIPT = ROOT / "scripts" / "tts_clone.py"
VOICE_ROOT = ROOT / "uploads" / "voice"

# readings the model gets wrong; applied to the SPOKEN text only
_DEFAULT_READINGS = {
    "架装型式": "かそうかたしき", "架装": "かそう", "型式": "かたしき", "製造番号": "せいぞうばんごう",
    "車体番号": "しゃたいばんごう", "車台番号": "しゃだいばんごう", "年式": "ねんしき",
    "車検証": "しゃけんしょう", "銘板": "めいばん", "初度登録年月": "しょどとうろくねんげつ",
    "5点": "五点", "５点": "五点", "1回目": "一回目", "１回目": "一回目",
}


def list_voices() -> list[str]:
    if not VOICE_ROOT.exists():
        return []
    return sorted(p.name for p in VOICE_ROOT.iterdir() if (p / "profile.json").exists())


def spoken_form(text: str, readings: dict[str, str] | None = None) -> str:
    """Apply kana readings (longest key first) so the synthesizer says the right thing."""
    table = dict(_DEFAULT_READINGS)
    if readings:
        table.update({str(k): str(v) for k, v in readings.items()})
    out = text
    for k in sorted(table, key=len, reverse=True):
        out = out.replace(k, table[k])
    return out


def wav_duration(path: str | Path) -> float:
    try:
        import wave

        with wave.open(str(path), "rb") as w:
            return w.getnframes() / float(w.getframerate() or 1)
    except Exception:
        return 0.0


def synthesize_many(lines: dict[str, str], out_dir: str | Path, voice: str = "owner",
                    readings: dict[str, str] | None = None, timeout: float = 1800.0) -> dict[str, Any]:
    """Synthesize several lines with one model load. Returns {ok, files:{name:{path,duration,spoken}}, ...}."""
    from app.services.qwen_policy import MESSAGE
    return {'ok': False, 'error': MESSAGE, 'backend': 'disabled'}



def synthesize(text: str, out_path: str | Path, voice: str = "owner",
               readings: dict[str, str] | None = None) -> dict[str, Any]:
    out_path = Path(out_path)
    name = re.sub(r"[^A-Za-z0-9_-]", "_", out_path.stem) or "line"
    res = synthesize_many({name: text}, out_path.parent, voice=voice, readings=readings)
    if not res.get("ok"):
        return res
    got = (res.get("files") or {}).get(name)
    if not got:
        return {"ok": False, "error": "no output produced"}
    src = Path(got["path"])
    if src.resolve() != out_path.resolve():
        os.replace(src, out_path)
    return {"ok": True, "path": str(out_path), "duration": got["duration"], "spoken": got["spoken"],
            "seconds": res.get("seconds"), "gpu_wait": res.get("gpu_wait"),
            "backend":res.get('backend','cache' if res.get('cached') else 'local'),
            "pod_id":res.get('pod_id'), "transfer_included_seconds":res.get('transfer_included_seconds')}


if __name__ == "__main__":  # manual check: python -m app.services.timeline_speech "テキスト" out.wav
    sys.path.insert(0, str(ROOT))
    print(json.dumps(synthesize(sys.argv[1], sys.argv[2]), ensure_ascii=False))
