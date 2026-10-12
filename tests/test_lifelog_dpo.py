"""The lifelog's .dpo container and its Ogg Opus wrapper (app/services/lifelog.py): what the phone writes — from the
pin or from its own microphone (DanPhoneLifelog) — must parse back frame for frame, and the Ogg the PC keeps must be
well-formed (page magic, CRC, granule positions at 48 kHz, 16 kHz OpusHead)."""
import struct

import pytest

from app.services import lifelog


def dpo(frames: list[bytes], start_ms: int = 1_760_000_000_000, frame_ms: int = 10) -> bytes:
    body = bytearray(b"DPO1" + struct.pack("<QH", start_ms, frame_ms))
    for f in frames:
        body += struct.pack("<H", len(f)) + f
    return bytes(body)


def test_parse_dpo_round_trip():
    frames = [bytes([0x78, i & 255]) * (3 + i % 7) for i in range(250)]   # 2.5 s of 10 ms frames, varied sizes
    start_ms, frame_ms, parsed = lifelog.parse_dpo(dpo(frames))
    assert (start_ms, frame_ms) == (1_760_000_000_000, 10)
    assert parsed == frames


def test_parse_dpo_rejects_other_files():
    with pytest.raises(ValueError):
        lifelog.parse_dpo(b"RIFF" + b"\0" * 40)


def test_parse_dpo_stops_at_truncated_tail():
    frames = [b"\x78\x01\x02"] * 10
    data = dpo(frames) + struct.pack("<H", 50) + b"\x78\x01"   # a length that runs past the end
    assert lifelog.parse_dpo(data)[2] == frames


def _pages(ogg: bytes):
    at = 0
    while at < len(ogg):
        assert ogg[at:at + 4] == b"OggS"
        nseg = ogg[at + 26]
        lacing = ogg[at + 27:at + 27 + nseg]
        body = sum(lacing)
        page = ogg[at:at + 27 + nseg + body]
        granule = struct.unpack_from("<q", page, 6)[0]
        crc = struct.unpack_from("<I", page, 22)[0]
        bare = bytearray(page); struct.pack_into("<I", bare, 22, 0)
        yield granule, crc, lifelog._crc_fast(bytes(bare)), page[27 + nseg:]
        at += len(page)


def test_ogg_opus_pages_are_well_formed():
    frames = [bytes([0x78]) + bytes([i & 255]) * 20 for i in range(120)]   # 1.2 s
    ogg = lifelog.ogg_opus(frames, 10)
    pages = list(_pages(ogg))
    assert pages[0][3].startswith(b"OpusHead") and pages[1][3].startswith(b"OpusTags")
    assert struct.unpack_from("<I", pages[0][3], 12)[0] == 16000           # input sample rate the phone encodes at
    assert all(crc == want for _, crc, want, _ in pages)
    audio = pages[2:]
    assert [g for g, *_ in audio] == [480 * 50, 480 * 100, 480 * 120]      # granule counted at 48 kHz, 10 ms = 480
    assert b"".join(p for *_, p in audio) == b"".join(frames)
    assert lifelog._crc_fast(b"abc") == lifelog._crc(b"abc")


def test_store_segment_keeps_ogg_in_day_folder(tmp_path, monkeypatch):
    monkeypatch.setattr(lifelog, "AUDIO_ROOT", tmp_path / "audio")
    frames = [b"\x78\x11\x22\x33"] * 100
    out = lifelog.store_segment("1f53bb2a-test-user", dpo(frames, start_ms=1_760_000_000_000))
    assert out["seconds"] == 1.0
    kept = tmp_path / "audio" / out["audio"].split("\\")[-2] / out["audio"].split("\\")[-1]
    assert kept.exists() and kept.suffix == ".ogg" and kept.name.endswith("_1f53bb2a.ogg")
    with pytest.raises(ValueError):
        lifelog.store_segment("u", dpo([]))
