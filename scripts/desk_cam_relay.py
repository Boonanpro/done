"""手元カメラ中継: ZV-E10 II を USB でつなぐと、その映像をそのまま NAS の Frigate（カメラ名 desk）へ流す。

なぜ: 機器づくりの作業を、手で転送せずに NAS へ自動で溜めたい（2026-10-02）。PC には録画を溜めない。
Frigate 側は go2rtc の受け口 rtsp://192.168.40.236:8554/desk を待っていて、動きのある所だけ 60 日録画する。

動き: 10 秒ごとにカメラ（DirectShow の映像デバイス名に CAMERA_MATCH を含むもの）を探し、見つかったら ffmpeg で
NVENC(H.264、カメラのまま 1080p60) に変換して送る。カメラを外す・電源を切ると ffmpeg が終わり、また探す状態に戻る。

音: 両方のマイクを常に録り、どちらを使うかは編集の時に選ぶ（2026-10-04 本人の指示。画面での切り替えは廃止）。
    NAS の録画には MOTU M2 の入力1（SM7dB）を両耳に入れる。カメラ内蔵マイクは、中継とは別の ffmpeg で
    SPARE_DIR へ 10 分ごとのファイル（ステレオのまま）に録り続ける。予備の音を足しても中継は張り直さないので、
    NAS の録画は途切れない。SPARE_KEEP_DAYS 日より古い予備は消す。
    MOTU が見つからない時は、音なしにせずカメラ内蔵マイクを NAS へ入れる（MOTU が戻れば自動で戻る）。
    D:/dan-hw/desk-cam/relay.json の "audio" を "camera" / "none" にすると NAS の音を手で変えられる（既定は "motu"）。
    カメラのマイクで録れていたのに SM7dB で録れていると思い込んだ事故（2026-10-03）の再発防止で、
    実際に使っている音と予備が録れているかを status.json に書き出す。表示は desk_cam_panel.py。
見張り: ffmpeg が生きていても NAS へ1コマも送れていないことがある（2026-10-04 17:01、張り直した ffmpeg が
    NAS へつながらないまま38分固まり、その間「中継中」と表示していた）。送ったコマ数（-progress）が
    SEND_STALE 秒増えなければ張り直し、status.json の sending にも出す。
実行: タスク DanDeskCamRelay がログオン時に run_hidden.vbs 経由で起動（常駐）。ログは .tmp/desk_cam_relay.log。
"""
import json
import os
import re
import subprocess
import threading
import time
from collections import deque
from datetime import datetime
from pathlib import Path

FFMPEG = r"D:\dan-hw\tools\ffmpeg-7.1.exe"  # winget の 9.x はドライバー 591 だと NVENC が開けない（要 610 以上）
TARGET = "rtsp://192.168.40.236:8554/desk"
CAMERA_MATCH = "ZV-E10"
MOTU_DEVICE = "In 1-2 (MOTU M Series)"
SETTINGS = Path(r"D:\dan-hw\desk-cam\relay.json")
STATUS = SETTINGS.with_name("status.json")
MODES = ("motu", "camera", "none")
SPARE_DIR = SETTINGS.with_name("camera-mic")  # カメラ内蔵マイクの予備（cam_年月日_時分秒.mka）
SPARE_SEGMENT = 600  # 1ファイルの秒数（時計の 10 分ごとに区切る）
SPARE_KEEP_DAYS = 7
SPARE_STALE = 30  # 予備のファイルがこの秒数より更新されなければ、録れていないと見なす
SEND_STALE = 20  # 送ったコマ数がこの秒数より増えなければ、NAS へ流れていないと見なして張り直す
LOG =Path(__file__).resolve().parent.parent / ".tmp" / "desk_cam_relay.log"
NO_WINDOW = 0x08000000  # CREATE_NO_WINDOW


def log(msg):
    LOG.parent.mkdir(parents=True, exist_ok=True)
    with LOG.open("a", encoding="utf-8") as f:
        f.write(f"{datetime.now():%m/%d %H:%M:%S} {msg}\n")


def dshow_devices():
    """(映像デバイス名, 音声デバイス名) のリスト。"""
    out = subprocess.run([FFMPEG, "-hide_banner", "-list_devices", "true", "-f", "dshow", "-i", "dummy"],
                         capture_output=True, text=True, encoding="utf-8", errors="replace",
                         creationflags=NO_WINDOW).stderr
    video, audio = [], []
    for name, kind in re.findall(r'"([^"]+)" \((video|audio)\)', out):
        (video if kind == "video" else audio).append(name)
    return video, audio


def audio_mode():
    """本人が選んだ音（relay.json）。読めない時は既定の motu。"""
    try:
        mode = json.loads(SETTINGS.read_text(encoding="utf-8")).get("audio", "motu")
    except Exception:  # noqa: BLE001
        return "motu"
    return mode if mode in MODES else "motu"


def write_status(**fields):
    """今の状態を status.json へ（パネルが読む）。updated が古ければ中継自体が止まっている。"""
    fields["updated"] = time.time()
    try:
        tmp = STATUS.with_suffix(".tmp")
        tmp.write_text(json.dumps(fields, ensure_ascii=False), encoding="utf-8")
        os.replace(tmp, STATUS)
    except Exception:  # noqa: BLE001
        pass


def build_command(camera, audio_devices, requested):
    """(ffmpeg の引数, 実際に使う音)。requested が motu でも MOTU が無ければ camera に落ちる。"""
    mode = requested
    source = f"video={camera}"
    af = []
    if mode == "motu" and MOTU_DEVICE not in audio_devices:
        mode = "camera"
    if mode == "motu":
        source += f":audio={MOTU_DEVICE}"
        af = ["-af", "pan=stereo|c0=c0|c1=c0"]  # SM7dB は入力1だけなので左右両方へ
    elif mode == "camera":
        cam_mic = next((a for a in audio_devices if CAMERA_MATCH in a), None)
        if cam_mic:
            source += f":audio={cam_mic}"
        else:
            mode = "none"
    else:
        mode = "none"
    cmd = [FFMPEG, "-hide_banner", "-loglevel", "warning", "-nostats", "-progress", "pipe:1",
           "-f", "dshow", "-rtbufsize", "512M", "-pixel_format", "nv12", "-i", source,  # 形式・コマ数はカメラ任せ（ZV-E10 II は 1080p60 固定）
           "-c:v", "h264_nvenc", "-preset", "p4", "-tune", "ll", "-b:v", "10M", "-g", "60", "-pix_fmt", "yuv420p"]
    if mode == "none":
        cmd += ["-an"]
    else:
        cmd += af + ["-c:a", "aac", "-b:a", "160k", "-ar", "48000"]
    cmd += ["-f", "rtsp", "-rtsp_transport", "tcp", TARGET]
    return cmd, mode


def start_spare(audio_devices):
    """カメラ内蔵マイクを SPARE_DIR へ録り続ける ffmpeg を立てる。マイクが無ければ None。"""
    cam_mic = next((a for a in audio_devices if CAMERA_MATCH in a), None)
    if not cam_mic:
        return None
    SPARE_DIR.mkdir(parents=True, exist_ok=True)
    # mka は途中で落ちても、そこまでの音が読める（mp4 は末尾が書けないと全部読めない）
    cmd = [FFMPEG, "-hide_banner", "-loglevel", "warning", "-f", "dshow", "-i", f"audio={cam_mic}",
           "-c:a", "aac", "-b:a", "160k", "-ar", "48000",
           "-f", "segment", "-segment_time", str(SPARE_SEGMENT), "-segment_atclocktime", "1",
           "-reset_timestamps", "1", "-strftime", "1", "-segment_format", "matroska", "-fflags", "+flush_packets",
           str(SPARE_DIR / "cam_%Y%m%d_%H%M%S.mka")]
    return subprocess.Popen(cmd, stdin=subprocess.PIPE, stdout=subprocess.DEVNULL, stderr=subprocess.DEVNULL,
                            creationflags=NO_WINDOW)


def spare_recording(since):
    """予備の音が今も書かれているか（since より後に始まり、いちばん新しいファイルが更新され続けている）。"""
    try:
        newest = max(f.stat().st_mtime for f in SPARE_DIR.glob("cam_*.mka"))
    except ValueError:
        return False
    return newest >= since and time.time() - newest < SPARE_STALE


def prune_spare():
    """SPARE_KEEP_DAYS 日より古い予備を消す。"""
    limit = time.time() - SPARE_KEEP_DAYS * 86400
    for f in SPARE_DIR.glob("cam_*.mka"):
        try:
            if f.stat().st_mtime < limit:
                f.unlink()
        except OSError:
            pass


def stop(p):
    """ffmpeg を止める。q で終わらせ、3秒で終わらなければ落とす。"""
    try:
        p.stdin.write(b"q")
        p.stdin.flush()
        p.wait(timeout=3)
    except Exception:  # noqa: BLE001
        p.kill()
        p.wait()


def relay(camera, audio, requested):
    """1回分の中継。音の選び直しが要る時は True を返す（待たずに張り直す）。"""
    cmd, mode = build_command(camera, audio, requested)
    log(f"カメラ検出「{camera}」音={mode}" + ("" if mode == requested else f"（指定は {requested}）") + " → 中継開始")
    started = time.time()
    p = subprocess.Popen(cmd, stdin=subprocess.PIPE, stdout=subprocess.PIPE, stderr=subprocess.PIPE,
                         creationflags=NO_WINDOW)
    tail = deque(maxlen=3)
    reader = threading.Thread(target=lambda: tail.extend(
        line.decode("utf-8", "replace").strip() for line in p.stderr), daemon=True)
    reader.start()
    sent = {"frames": 0, "at": started}  # NAS へ送ったコマ数と、最後に増えた時刻

    def watch_progress():
        for line in p.stdout:
            if line.startswith(b"frame="):
                try:
                    frames = int(line[6:])
                except ValueError:
                    continue
                if frames > sent["frames"]:
                    sent["frames"], sent["at"] = frames, time.time()

    threading.Thread(target=watch_progress, daemon=True).start()
    status = {"relaying": True, "camera": camera, "audio": mode, "requested": requested, "since": started}
    # カメラのマイクが NAS に入っていない時だけ、予備として別に録る
    spare, spare_started, spare_ok = (start_spare(audio), started, None) if mode == "motu" else (None, 0, None)
    reason, ticks = None, 0
    while p.poll() is None:
        if mode == "motu":
            ok = spare is not None and spare.poll() is None and (
                time.time() - spare_started < SPARE_STALE or spare_recording(spare_started))
            if ok != spare_ok and (ok or spare_ok is not None or time.time() - started > SPARE_STALE):
                log("予備（カメラのマイク）" + ("録音中" if ok else "が録れていない"))
                spare_ok = ok
            status["spare"] = ok
            if not ok and ticks % 15 == 14:  # 止まっていたら立て直す（中継は触らない）
                if spare is not None:
                    stop(spare)
                spare, spare_started = start_spare(dshow_devices()[1]), time.time()
            if ticks % 3600 == 0:
                prune_spare()
        idle = time.time() - sent["at"]
        status["sending"] = idle < SEND_STALE and (sent["frames"] > 0 or None)  # None = つなぎ始め
        write_status(**status)
        time.sleep(1)
        ticks += 1
        if idle > SEND_STALE:
            reason = f"映像が NAS へ流れていない（{idle:.0f}秒・送ったコマ {sent['frames']}）"
        elif audio_mode() != requested:
            reason = f"音の指定が {audio_mode()} に変わった"
        elif mode != requested == "motu" and ticks % 15 == 0 and MOTU_DEVICE in dshow_devices()[1]:
            reason = "MOTU が戻った"
        if reason:
            stop(p)
    if spare is not None:
        stop(spare)
    reader.join(timeout=2)
    log(f"中継終了 code={p.returncode} {time.time() - started:.0f}秒 {reason or ' / '.join(tail)}")
    return bool(reason)


def main():
    log("起動")
    while True:
        try:
            video, audio = dshow_devices()
            camera = next((v for v in video if CAMERA_MATCH in v), None)
            if camera:
                requested = audio_mode()
                # マイクは映像より遅れて出てくる（5秒待ちでも間に合わず音なしで始まった 2026-10-03）。最大30秒待つ。
                for _ in range(15):
                    need_cam_mic = requested == "camera" or (requested == "motu" and MOTU_DEVICE not in audio)
                    if not need_cam_mic or any(CAMERA_MATCH in a for a in audio):
                        break
                    time.sleep(2)
                    video, audio = dshow_devices()
                switching = relay(camera, audio, requested)
                write_status(relaying=False, requested=audio_mode(), switching=switching)
                time.sleep(1 if switching else 5)
                continue
            write_status(relaying=False, requested=audio_mode())
        except Exception as e:  # noqa: BLE001
            log(f"エラー {type(e).__name__}: {e}")
        time.sleep(10)


if __name__ == "__main__":
    main()
