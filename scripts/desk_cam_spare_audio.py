"""手元カメラの収録から、カメラ内蔵マイクの音（予備）を映像に合わせて取り出す。

なぜ: 中継 desk_cam_relay.py は NAS の録画に SM7dB を入れ、カメラ内蔵マイクは PC の別ファイル
（D:/dan-hw/desk-cam/camera-mic/cam_年月日_時分秒.mka）に録る。編集でカメラのマイクを使いたい時に、
その別ファイルから収録と同じ区間を、収録の音（SM7dB）と波形を突き合わせて位置を合わせて切り出す。

使い方:
    python scripts/desk_cam_spare_audio.py <収録.mp4> "<収録の開始時刻>" [-o 出力.wav]
    python scripts/desk_cam_spare_audio.py nas "<開始時刻>" "<終了時刻>" [-o 出力.wav]   # NAS から区間を取ってきて合わせる
時刻は "2026-10-04 16:20:00" か、秒（エポック）。開始時刻は ±SEARCH 秒ずれていてよい。
出力は収録と同じ長さのステレオ 48kHz の wav。合い具合（相関）と、収録の頭と末尾でのずれの差も表示する。
"""
import argparse
import subprocess
import sys
import urllib.request
import wave
from datetime import datetime
from pathlib import Path

import numpy as np

from desk_cam_relay import FFMPEG, NO_WINDOW, SPARE_DIR

NAS_CLIP = "http://192.168.40.236:5000/api/desk/start/{start}/end/{end}/clip.mp4"
RATE = 48000
COARSE = 8000  # 位置合わせはこの細かさで足りる
SEARCH = 20  # 開始時刻のずれをこの秒数まで探す


def epoch(text):
    try:
        return float(text)
    except ValueError:
        return datetime.strptime(text, "%Y-%m-%d %H:%M:%S").timestamp()


def decode(path, rate, channels, start=0.0, length=None):
    """音を int16 の配列（サンプル数 x チャンネル数）で読む。"""
    cmd = [FFMPEG, "-hide_banner", "-loglevel", "error", "-ss", f"{max(0.0, start):.3f}", "-i", str(path)]
    if length is not None:
        cmd += ["-t", f"{length:.3f}"]
    cmd += ["-vn", "-ac", str(channels), "-ar", str(rate), "-f", "s16le", "-"]
    raw = subprocess.run(cmd, capture_output=True, creationflags=NO_WINDOW).stdout
    return np.frombuffer(raw, dtype=np.int16).reshape(-1, channels)


def spare_window(start, length):
    """[start, start+length] を覆う予備の音（ステレオ 48kHz）と、その頭の時刻。途切れがあれば無音で埋める。"""
    files = sorted((datetime.strptime(f.stem, "cam_%Y%m%d_%H%M%S").timestamp(), f) for f in SPARE_DIR.glob("cam_*.mka"))
    out = np.zeros((int(length * RATE), 2), dtype=np.int16)
    found = False
    for i, (t0, f) in enumerate(files):
        t1 = files[i + 1][0] if i + 1 < len(files) else float("inf")
        if t1 <= start or t0 >= start + length:
            continue
        part = decode(f, RATE, 2, start=start - t0, length=start + length - max(start, t0))
        at = int((max(start, t0) - start) * RATE)
        part = part[: len(out) - at]
        out[at:at + len(part)] = part
        found = found or len(part) > 0
    if not found:
        sys.exit(f"この時刻の予備の音がありません（{SPARE_DIR}）")
    return out


def best_lag(clip, spare):
    """clip が spare の中のどこに当たるか（サンプル数）と、その相関（-1〜1）。"""
    a = clip.astype(np.float64) - clip.mean()
    b = spare.astype(np.float64) - spare.mean()
    n = 1 << (len(a) + len(b) - 1).bit_length()
    corr = np.fft.irfft(np.fft.rfft(b, n) * np.conj(np.fft.rfft(a, n)), n)[: len(b) - len(a) + 1]
    energy = np.concatenate(([0.0], np.cumsum(b * b)))
    norm = np.sqrt((energy[len(a):] - energy[: len(b) - len(a) + 1]) * (a * a).sum())
    score = corr / np.maximum(norm, 1e-9)
    lag = int(np.argmax(score))
    return lag, float(score[lag])


def main():
    parser = argparse.ArgumentParser(description=__doc__.splitlines()[0])
    parser.add_argument("clip", help='収録のファイル。"nas" なら NAS から取ってくる')
    parser.add_argument("start", help="収録の開始時刻")
    parser.add_argument("end", nargs="?", help='clip が "nas" の時の終了時刻')
    parser.add_argument("-o", "--out", help="出力する wav（省略時は収録の隣に _camera-mic.wav）")
    args = parser.parse_args()

    start = epoch(args.start)
    clip = Path(args.clip)
    if args.clip == "nas":
        clip = Path(args.out or f"desk_{int(start)}").with_suffix(".mp4")
        urllib.request.urlretrieve(NAS_CLIP.format(start=int(start), end=int(epoch(args.end))), clip)
        print(f"NAS の録画を保存: {clip}")
    out = Path(args.out) if args.out else clip.with_name(clip.stem + "_camera-mic.wav")

    clip_audio = decode(clip, COARSE, 1)[:, 0]
    seconds = len(clip_audio) / COARSE
    spare = spare_window(start - SEARCH, seconds + 2 * SEARCH)
    step = RATE // COARSE
    coarse = spare[: len(spare) // step * step].astype(np.int32).reshape(-1, step * 2).sum(axis=1)
    lag, score = best_lag(clip_audio, coarse)
    print(f"収録 {seconds:.1f}秒 / 開始時刻のずれ {lag / COARSE - SEARCH:+.2f}秒 / 相関 {score:.2f}")
    if seconds >= 60:  # 頭と末尾で別々に合わせ、収録の間に2つの音がどれだけずれていくかを見る
        edge = 20 * COARSE
        margin = COARSE // 2
        ends = []
        for at in (0, len(clip_audio) - edge):
            lo = max(0, lag + at - margin)
            sub_lag, sub_score = best_lag(clip_audio[at:at + edge], coarse[lo:lag + at + edge + margin])
            ends.append((lo + sub_lag - at - lag, sub_score))
        print(f"頭と末尾のずれの差 {(ends[1][0] - ends[0][0]) / COARSE * 1000:+.0f}ミリ秒"
              f"（相関 頭 {ends[0][1]:.2f} / 末尾 {ends[1][1]:.2f}）")

    first = lag * (RATE // COARSE)
    cut = spare[first:first + int(seconds * RATE)]
    with wave.open(str(out), "wb") as w:
        w.setnchannels(2)
        w.setsampwidth(2)
        w.setframerate(RATE)
        w.writeframes(cut.tobytes())
    print(f"カメラのマイクの音を保存: {out}")


if __name__ == "__main__":
    main()
