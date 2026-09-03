"""スマホ用ヒーロー動画: 2・3シーン目だけフレーム単位で正確に横シフトする。

時間(-ss/-to)で切ると29.97fpsでは境目が1〜2フレームずれ、切替の瞬間に
「ずれた位置の絵」が一瞬出てちらつく。ここではフレーム番号で厳密に判定する。

シーン切替(実測): scene2=frame166, scene3=frame280, scene4=frame387
 - scene2 (166-279): 顔(x1360)を中央(960)へ = 左に400シフト
 - scene3 (280-386): 人物(x780)を中央やや左(870)へ = 右に90シフト
 - それ以外: 無変更
シフトで空く側は黒。スマホは中央帯しか映さないので黒は見えない。

使い方: python scripts/kittoku_mobile_reframe.py <part1.mp4> <out.mp4>
"""
from __future__ import annotations
import subprocess
import sys
import numpy as np

FFMPEG = "C:/Users/Owner/ffmpeg/bin/ffmpeg.exe"
FFPROBE = "C:/Users/Owner/ffmpeg/bin/ffprobe.exe"

S2_START, S2_END = 166, 279   # scene2 (inclusive)
S3_START, S3_END = 280, 386   # scene3 (inclusive)
SHIFT_S2 = 400                # 左へ
SHIFT_S3 = -90                # 右へ(負=右)


def shift(frame: np.ndarray, dx: int) -> np.ndarray:
    """dx>0で内容を左へ、dx<0で右へ。空いた側は黒。"""
    h, w, _ = frame.shape
    out = np.zeros_like(frame)
    if dx >= 0:                      # 左シフト: input[dx:] -> output[:w-dx]
        out[:, : w - dx] = frame[:, dx:]
    else:                            # 右シフト
        d = -dx
        out[:, d:] = frame[:, : w - d]
    return out


def main():
    src, dst = sys.argv[1], sys.argv[2]
    w, h = 1920, 1080
    fps = subprocess.run(
        [FFPROBE, "-v", "error", "-select_streams", "v:0",
         "-show_entries", "stream=r_frame_rate", "-of",
         "default=noprint_wrappers=1:nokey=1", src],
        capture_output=True, text=True).stdout.strip()

    dec = subprocess.Popen(
        [FFMPEG, "-v", "error", "-i", src, "-f", "rawvideo", "-pix_fmt", "rgb24", "-"],
        stdout=subprocess.PIPE)
    enc = subprocess.Popen(
        [FFMPEG, "-v", "error", "-y", "-f", "rawvideo", "-pix_fmt", "rgb24",
         "-s", f"{w}x{h}", "-r", fps, "-i", "-",
         "-c:v", "libx264", "-crf", "17", "-preset", "slow",
         "-pix_fmt", "yuv420p", "-movflags", "+faststart", "-an", dst],
        stdin=subprocess.PIPE)

    fb = w * h * 3
    n = 0
    while True:
        buf = dec.stdout.read(fb)
        if len(buf) < fb:
            break
        frame = np.frombuffer(buf, np.uint8).reshape(h, w, 3)
        if S2_START <= n <= S2_END:
            frame = shift(frame, SHIFT_S2)
        elif S3_START <= n <= S3_END:
            frame = shift(frame, SHIFT_S3)
        enc.stdin.write(np.ascontiguousarray(frame).tobytes())
        n += 1
    enc.stdin.close()
    dec.wait(); enc.wait()
    print(f"処理フレーム数: {n}  出力: {dst}")


if __name__ == "__main__":
    main()
