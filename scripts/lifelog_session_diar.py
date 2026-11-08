"""Speakers of one whole conversation with pyannote speaker-diarization-community-1 (2026-11-09).

Run by app/services/lifelog_sessions.py in its own Python (DAN_PYANNOTE_PYTHON, default ~/pya-venv/bin/python): the
pyannote 4 / torch stack does not load in dan-venv on this Mac (its scipy fails on macOS 27). Reads a 16 kHz mono wav,
writes [[start, end, speaker], ...] (exclusive: one speaker at a time, the form words can be given to) as JSON.
Local and free; the model comes from Hugging Face once (gated: the token in ~/.cache/huggingface/token).

Setting the Python up (once):
  /opt/homebrew/bin/python3.13 -m venv ~/pya-venv && ~/pya-venv/bin/pip install pyannote.audio soundfile

usage: lifelog_session_diar.py <in.wav> <out.json>
"""
import json
import sys
import wave

import numpy as np
import torch
from pyannote.audio import Pipeline

MODEL = "pyannote/speaker-diarization-community-1"


def main(src: str, dst: str) -> None:
    with wave.open(src, "rb") as w:
        rate = w.getframerate()
        y = np.frombuffer(w.readframes(w.getnframes()), dtype=np.int16).astype(np.float32) / 32768
    pipe = Pipeline.from_pretrained(MODEL)
    if torch.backends.mps.is_available():
        pipe.to(torch.device("mps"))
    out = pipe({"waveform": torch.from_numpy(y)[None], "sample_rate": rate})
    ann = getattr(out, "exclusive_speaker_diarization", None) or getattr(out, "speaker_diarization", out)
    segs = [[round(t.start, 3), round(t.end, 3), str(s)] for t, _, s in ann.itertracks(yield_label=True)]
    with open(dst, "w") as f:
        json.dump(segs, f)


if __name__ == "__main__":
    main(sys.argv[1], sys.argv[2])
