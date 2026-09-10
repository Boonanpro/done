# -*- coding: utf-8 -*-
"""Voice-clone text-to-speech (Qwen3-TTS, local GPU) — runs inside venv_tts.

usage (from the normal interpreter, via app.services.timeline_speech):
  D:/done/venv_tts/Scripts/python.exe scripts/tts_clone.py --profile uploads/voice/owner \
      --text "..." --out out.wav [--text-file lines.json --out-dir dir]

--text-file: JSON {"name": "text", ...} → one wav per entry in --out-dir (model loads once).
Readings: write kana for words the model misreads (車検証→しゃけんしょう). The spoken
text is what is synthesized; keep the DISPLAY text (for captions) separately.
Prints one JSON line per output: {"name","path","duration"} and finally CLONE_DONE.
"""
import argparse
import json
import os
import sys
import time

sys.stdout.reconfigure(encoding="utf-8")


def main() -> int:
    print('Qwen3-TTS is disabled at the user\'s request.', file=sys.stderr)
    return 1


if __name__ == "__main__":
    sys.exit(main())
