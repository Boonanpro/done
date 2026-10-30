"""Lifelog: the Dan pin hears the owner's day; the speech parts are kept and written down (2026-10-09).

The phone cuts the pin's microphone stream into speech segments and uploads each as a .dpo file: b"DPO1", the segment's
start (unix ms, u64 LE), the frame length (ms, u16 LE), then the pin's Opus frames as [u16 LE length][frame]. Nothing is
re-encoded: the pin's own 16 kHz Opus frames are wrapped into an Ogg Opus file and kept on the NAS for 180 days.
A worker on this PC (scripts/lifelog_worker.py, GPU Whisper) writes each file down; the text goes into one local JSONL
per day, which Dan searches ("今日話してたあれ") and reads back for the last minutes ("今の聞いてた？").
"""
from __future__ import annotations

import json
import os
import struct
import zlib
import tempfile
from datetime import datetime, timedelta, timezone
from pathlib import Path
from zoneinfo import ZoneInfo

JST = ZoneInfo("Asia/Tokyo")
# State must survive release/worktree changes. Windows keeps its NAS archive.
STATE_ROOT = Path.home() / ".dan" / "lifelog"
AUDIO_ROOT = Path(os.environ.get("DAN_LIFELOG_AUDIO") or (r"\\192.168.40.236\personal_folder\dan-lifelog" if os.name == "nt" else STATE_ROOT / "audio"))
INDEX_ROOT = Path(os.environ.get("DAN_LIFELOG_INDEX") or STATE_ROOT / "index")
KEEP_DAYS = 180


# ---------------------------------------------------------------- .dpo -> Ogg Opus

def parse_dpo(data: bytes) -> tuple[int, int, list[bytes]]:
    if data[:4] != b"DPO1" or len(data) < 14:
        raise ValueError("not a DPO1 segment")
    start_ms, frame_ms = struct.unpack_from("<QH", data, 4)
    frames, at = [], 14
    while at + 2 <= len(data):
        (n,) = struct.unpack_from("<H", data, at)
        at += 2
        if n == 0 or at + n > len(data):
            break
        frames.append(data[at:at + n])
        at += n
    return start_ms, frame_ms, frames


def _crc(page: bytes) -> int:
    # Ogg's CRC-32: polynomial 0x04C11DB7, not reflected, initial 0
    crc = 0
    for b in page:
        crc ^= b << 24
        for _ in range(8):
            crc = ((crc << 1) ^ 0x04C11DB7) & 0xFFFFFFFF if crc & 0x80000000 else (crc << 1) & 0xFFFFFFFF
    return crc


_CRC_TABLE = None


def _crc_fast(page: bytes) -> int:
    global _CRC_TABLE
    if _CRC_TABLE is None:
        t = []
        for i in range(256):
            r = i << 24
            for _ in range(8):
                r = ((r << 1) ^ 0x04C11DB7) & 0xFFFFFFFF if r & 0x80000000 else (r << 1) & 0xFFFFFFFF
            t.append(r)
        _CRC_TABLE = t
    crc = 0
    for b in page:
        crc = ((crc << 8) & 0xFFFFFFFF) ^ _CRC_TABLE[((crc >> 24) ^ b) & 0xFF]
    return crc


def _page(packets: list[bytes], granule: int, serial: int, seq: int, flags: int) -> bytes:
    lacing = bytearray()
    for p in packets:
        n = len(p)
        lacing += bytes([255] * (n // 255)) + bytes([n % 255])
    header = b"OggS" + struct.pack("<BBqIIIB", 0, flags, granule, serial, seq, 0, len(lacing)) + bytes(lacing)
    page = bytearray(header + b"".join(packets))
    struct.pack_into("<I", page, 22, _crc_fast(bytes(page)))
    return bytes(page)


def ogg_opus(frames: list[bytes], frame_ms: int, rate: int = 16000) -> bytes:
    serial = zlib.crc32(b"".join(frames[:4])) & 0xFFFFFFFF
    head = b"OpusHead" + struct.pack("<BBHIhB", 1, 1, 0, rate, 0, 0)
    tags = b"OpusTags" + struct.pack("<I", 3) + b"dan" + struct.pack("<I", 0)
    out = [_page([head], 0, serial, 0, 0x02), _page([tags], 0, serial, 1, 0)]
    step = 48 * frame_ms                      # granule is always counted at 48 kHz
    granule, seq = 0, 2
    for i in range(0, len(frames), 50):
        chunk = frames[i:i + 50]
        granule += step * len(chunk)
        last = i + 50 >= len(frames)
        out.append(_page(chunk, granule, serial, seq, 0x04 if last else 0))
        seq += 1
    return b"".join(out)


# ---------------------------------------------------------------- storage

def store_segment(user_id: str, data: bytes) -> dict:
    start_ms, frame_ms, frames = parse_dpo(data)
    if not frames:
        raise ValueError("empty segment")
    start = datetime.fromtimestamp(start_ms / 1000, JST)
    seconds = len(frames) * frame_ms / 1000
    day = AUDIO_ROOT / start.strftime("%Y-%m-%d")
    day.mkdir(parents=True, exist_ok=True)
    path = day / f"{start:%H%M%S}_{start_ms % 1000:03d}_{user_id[:8]}.ogg"
    if not path.exists():
        # The worker must never see a partially written Ogg.
        with tempfile.NamedTemporaryFile(dir=day, suffix=".pending", delete=False) as f:
            temp = Path(f.name)
            f.write(ogg_opus(frames, frame_ms))
            f.flush()
            os.fsync(f.fileno())
        temp.replace(path)
    return {"audio": str(path), "start": start.isoformat(), "seconds": round(seconds, 2)}


def index_file(day: str) -> Path:
    return INDEX_ROOT / f"{day}.jsonl"


def add_transcript(entry: dict) -> None:
    INDEX_ROOT.mkdir(parents=True, exist_ok=True)
    day = entry["start"][:10]
    with index_file(day).open("a", encoding="utf-8") as f:
        f.write(json.dumps(entry, ensure_ascii=False) + "\n")


def read_day(day: str) -> list[dict]:
    p = index_file(day)
    if not p.exists():
        return []
    rows = []
    for line in p.read_text(encoding="utf-8").splitlines():
        try:
            rows.append(json.loads(line))
        except ValueError:
            continue
    rows.sort(key=lambda r: r.get("start", ""))
    return rows


def recent(minutes: float = 10, now: datetime | None = None) -> list[dict]:
    now = now or datetime.now(JST)
    since = (now - timedelta(minutes=minutes)).isoformat()
    days = {now.strftime("%Y-%m-%d"), (now - timedelta(minutes=minutes)).strftime("%Y-%m-%d")}
    return [r for d in sorted(days) for r in read_day(d) if r.get("start", "") >= since and r.get("text")]


def search(query: str, days: int = 7, limit: int = 30, date: str | None = None) -> list[dict]:
    """Rows whose text has every word of the query (spaces split words), newest first."""
    words = [w for w in (query or "").replace("　", " ").split() if w]
    today = datetime.now(JST)
    span = [date] if date else [(today - timedelta(days=i)).strftime("%Y-%m-%d") for i in range(days)]
    hits = []
    for d in span:
        for r in reversed(read_day(d)):
            text = r.get("text", "")
            if all(w in text for w in words):
                hits.append(r)
                if len(hits) >= limit:
                    return hits
    return hits


def as_text(rows: list[dict]) -> str:
    return "\n".join(f"[{r['start'][11:19]}] {r['text']}" for r in rows if r.get("text"))
