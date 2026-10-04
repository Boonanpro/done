"""手元カメラの音の表示パネル。常に手前に出る小窓で、2つのマイクが両方とも録れているかを見せる。

なぜ: カメラの画面の波形はカメラ内蔵マイクしか映さないので、SM7dB で録れているかが分からなかった（2026-10-03 に
カメラのマイクで録ってしまった）。中継 desk_cam_relay.py は SM7dB を NAS の録画へ、カメラのマイクを PC の別ファイルへ
常に録る（どちらを使うかは編集の時に選ぶ。画面での切り替えは 2026-10-04 に廃止）。このパネルは status.json を読んで
「両方録れているか」を大きく出し、SM7dB とカメラのマイクの両方の波形を並べる。

波形: 入力ごとに ffmpeg を1本立てて 8kHz の生音を読み、50ms ごとの最大値を並べる（中継と同じ入力を同時に開ける）。
実行: pythonw scripts/desk_cam_panel.py（スタートアップの「手元カメラの音」から自動起動）。右クリックで閉じる。
折りたたみ: 右上の「－」（または帯をダブルクリック）で、今の音だけを出す小さな札になる。「＋」で戻る。状態は panel.json に残す。
しまう: 右上の「×」で窓を消し、タスクバー右端（通知領域）の丸い印だけにする。印は緑 = 両方録れている、
赤 ! = どちらかが録れていない、灰色 = カメラ未接続。印を押すと窓が戻り、右クリックで終了。
"""
import atexit
import ctypes
import json
import queue
import socket
import subprocess
import threading
import time
import tkinter as tk
from collections import deque

import numpy as np
import pystray
from PIL import Image, ImageDraw, ImageFont

from desk_cam_relay import CAMERA_MATCH, FFMPEG, MOTU_DEVICE, NO_WINDOW, SETTINGS, STATUS, dshow_devices

PLACE = SETTINGS.with_name("panel.json")  # 窓の位置（開いた時の左上）と、折りたたんでいるか・しまっているか
LOCK_PORT = 47653  # 二重起動よけ
CHUNK = 400  # 8kHz で 50ms
HISTORY = 110  # 波形に並べる本数（約5.5秒）
FLOOR = -60.0  # これより小さい音は波形の底
STALE = 45  # status.json がこの秒数より古ければ中継が止まっている
SILENT = 100  # 完全な無音がこの回数（5秒）続いたら、マイクが音を返していない

BG, CARD, DIM, TEXT = "#14161a", "#1f232b", "#5b6370", "#e8eaee"
GREEN, RED, GRAY = "#22c55e", "#ef4444", "#6b7280"
SOURCES = (("motu", "SM7dB"), ("camera", "カメラのマイク"))
GOES_TO = {"motu": "NASの録画へ", "camera": "PCの別ファイルへ"}


class Meter(threading.Thread):
    """1つの入力の音量を読み続ける。levels は dBFS の並び、入力が無い間は alive=False。"""

    def __init__(self, key):
        super().__init__(daemon=True)
        self.key = key
        self.levels = deque([FLOOR] * HISTORY, maxlen=HISTORY)
        self.alive = False
        self.zeros = 0  # 完全な無音が続いている回数
        self.proc = None

    def device(self):
        audio = dshow_devices()[1]
        if self.key == "motu":
            return MOTU_DEVICE if MOTU_DEVICE in audio else None
        return next((a for a in audio if CAMERA_MATCH in a), None)

    def run(self):
        while True:
            try:
                name = self.device()
                if name:
                    self.read(name)
            except Exception:  # noqa: BLE001
                pass
            self.alive = False
            time.sleep(3)

    def read(self, name):
        self.proc = subprocess.Popen(
            [FFMPEG, "-hide_banner", "-loglevel", "error", "-f", "dshow", "-audio_buffer_size", "50",
             "-i", f"audio={name}", "-af", "pan=mono|c0=c0", "-ar", "8000", "-f", "s16le", "-"],
            stdout=subprocess.PIPE, stderr=subprocess.DEVNULL, creationflags=NO_WINDOW)
        while True:
            data = self.proc.stdout.read(CHUNK * 2)
            if len(data) < CHUNK * 2:
                break
            peak = int(np.abs(np.frombuffer(data, dtype=np.int16).astype(np.int32)).max())
            self.levels.append(max(FLOOR, 20 * np.log10(peak / 32768)) if peak else FLOOR)
            self.zeros = 0 if peak else self.zeros + 1
            self.alive = True
        self.proc.wait()

    def close(self):
        if self.proc and self.proc.poll() is None:
            self.proc.kill()


class Panel:
    def __init__(self):
        try:
            ctypes.windll.shcore.SetProcessDpiAwareness(1)
        except Exception:  # noqa: BLE001
            pass
        self.root = root = tk.Tk()
        self.s = s = root.winfo_fpixels("1i") / 96  # 画面の拡大率
        root.overrideredirect(True)
        root.attributes("-topmost", True)
        root.configure(bg=BG)
        self.full, self.small = (int(400 * s), int(178 * s)), (int(196 * s), int(30 * s))
        self.xy, self.folded, self.hidden = self.saved()

        self.bar = tk.Frame(root, bg=GRAY)
        self.bar.pack(fill="x")
        self.fold = tk.Label(self.bar, bg=GRAY, fg="#0b0d10", font=("Yu Gothic UI", 12, "bold"), cursor="hand2",
                             padx=int(8 * s))
        self.away = tk.Label(self.bar, text="×", bg=GRAY, fg="#0b0d10", font=("Yu Gothic UI", 12, "bold"), cursor="hand2",
                             padx=int(8 * s))
        self.away.pack(side="right", fill="y")
        self.fold.pack(side="right", fill="y")
        self.head = tk.Label(self.bar, bg=GRAY, fg="#0b0d10", anchor="w")
        self.head.pack(side="left", fill="both", expand=True)
        self.body = tk.Frame(root, bg=BG)
        self.sub = tk.Label(self.body, bg=BG, fg=DIM, font=("Yu Gothic UI", 9), anchor="w", padx=int(12 * s))
        self.sub.pack(fill="x")

        self.meters, self.rows = {}, {}
        for key, label in SOURCES:
            self.meters[key] = Meter(key)
            self.meters[key].start()
            row = tk.Frame(self.body, bg=CARD, highlightthickness=int(2 * s), highlightbackground=CARD)
            row.pack(fill="x", padx=int(8 * s), pady=int(3 * s))
            names = tk.Frame(row, bg=CARD)
            names.pack(side="left")
            name = tk.Label(names, text=label, bg=CARD, fg=TEXT, font=("Yu Gothic UI", 11, "bold"), width=12, anchor="w",
                            padx=int(8 * s))
            name.pack(anchor="w")
            goes = tk.Label(names, bg=CARD, fg=DIM, font=("Yu Gothic UI", 8), anchor="w", padx=int(8 * s))
            goes.pack(anchor="w")
            db = tk.Label(row, bg=CARD, fg=DIM, font=("Consolas", 10), width=7, anchor="e", padx=int(6 * s))
            db.pack(side="right")
            wave = tk.Canvas(row, bg=CARD, height=int(40 * s), highlightthickness=0)
            wave.pack(side="left", fill="x", expand=True)
            self.rows[key] = (row, name, goes, db, wave)

        for widget in (self.head, self.sub):
            widget.bind("<Button-1>", self.grab)
            widget.bind("<B1-Motion>", self.drag)
            widget.bind("<ButtonRelease-1>", lambda e: self.save_place())
        self.head.bind("<Double-Button-1>", lambda e: self.toggle())
        self.fold.bind("<Button-1>", lambda e: self.toggle())
        self.away.bind("<Button-1>", lambda e: self.show(False))
        menu = tk.Menu(root, tearoff=0)
        menu.add_command(label="タスクバーにしまう", command=lambda: self.show(False))
        menu.add_command(label="終了", command=self.quit)
        root.bind("<Button-3>", lambda e: menu.tk_popup(e.x_root, e.y_root))

        self.status, self.status_read = {}, 0.0
        self.events, self.tray_look = queue.SimpleQueue(), None
        self.tray = pystray.Icon("desk_cam_audio", self.badge(GRAY, ""), "手元カメラの音", self.tray_menu())
        self.tray.run_detached()
        atexit.register(self.cleanup)
        self.layout()
        if self.hidden:
            root.withdraw()
        self.tick()

    # --- タスクバーの印 ---
    def tray_menu(self):
        """印の操作は別のスレッドで呼ばれるので、ここでは頼まれた事を並べるだけ（tick が実行する）。"""
        ask = self.events.put
        return pystray.Menu(pystray.MenuItem("パネルを出す／しまう", lambda *_: ask(("show", None)), default=True),
                            pystray.Menu.SEPARATOR,
                            pystray.MenuItem("終了", lambda *_: ask(("quit", None))))

    @staticmethod
    def badge(color, letter):
        img = Image.new("RGBA", (64, 64), (0, 0, 0, 0))
        draw = ImageDraw.Draw(img)
        draw.ellipse((2, 2, 62, 62), fill=color)
        if letter:
            draw.text((32, 31), letter, fill="#0b0d10", anchor="mm", font=ImageFont.truetype("arialbd.ttf", 44))
        return img

    def show(self, on=None):
        self.hidden = (not self.hidden) if on is None else (not on)
        if self.hidden:
            self.root.withdraw()
        else:
            self.root.deiconify()
            self.root.attributes("-topmost", True)
            self.layout()
        self.save_place()

    def handle_events(self):
        while not self.events.empty():
            what, arg = self.events.get()
            if what == "show":
                self.show()
            elif what == "quit":
                self.quit()
                return False
        return True

    # --- 窓の位置と折りたたみ ---
    def saved(self):
        """(開いた時の左上, 折りたたんでいるか, タスクバーにしまっているか)。読めない・画面の外なら右下。"""
        root, (w, h) = self.root, self.full
        try:
            data = json.loads(PLACE.read_text(encoding="utf-8"))
            x, y = data["xy"]
            if not (0 <= x < root.winfo_screenwidth() - 50 and 0 <= y < root.winfo_screenheight() - 50):
                raise ValueError
            return (x, y), bool(data.get("collapsed")), bool(data.get("hidden"))
        except Exception:  # noqa: BLE001
            return ((root.winfo_screenwidth() - w - int(16 * self.s), root.winfo_screenheight() - h - int(64 * self.s)),
                    False, False)

    def shift(self):
        """折りたたんだ札は、開いた時の窓の右下の角に合わせる。そのずれ。"""
        return (self.full[0] - self.small[0], self.full[1] - self.small[1]) if self.folded else (0, 0)

    def layout(self):
        s, (dx, dy) = self.s, self.shift()
        w, h = self.small if self.folded else self.full
        self.bar.pack_configure(fill="both" if self.folded else "x", expand=self.folded)
        if self.folded:
            self.body.pack_forget()
            self.head.configure(font=("Yu Gothic UI", 10, "bold"), padx=int(8 * s), pady=0)
            self.fold.configure(text="＋")
        else:
            self.body.pack(fill="both", expand=True)
            self.head.configure(font=("Yu Gothic UI", 15, "bold"), padx=int(12 * s), pady=int(6 * s))
            self.fold.configure(text="－")
        self.root.geometry(f"{w}x{h}+{self.xy[0] + dx}+{self.xy[1] + dy}")

    def toggle(self):
        self.folded = not self.folded
        self.layout()
        self.save_place()

    def grab(self, e):
        self.offset = (e.x_root - self.root.winfo_x(), e.y_root - self.root.winfo_y())

    def drag(self, e):
        x, y = e.x_root - self.offset[0], e.y_root - self.offset[1]
        dx, dy = self.shift()
        self.xy = (x - dx, y - dy)
        self.root.geometry(f"+{x}+{y}")

    def save_place(self):
        try:
            PLACE.write_text(json.dumps({"xy": list(self.xy), "collapsed": self.folded, "hidden": self.hidden}),
                             encoding="utf-8")
        except Exception:  # noqa: BLE001
            pass

    # --- 表示 ---
    def read_status(self):
        if time.time() - self.status_read < 0.4:
            return
        self.status_read = time.time()
        try:
            self.status = json.loads(STATUS.read_text(encoding="utf-8"))
        except Exception:  # noqa: BLE001
            pass

    def headline(self):
        """(見出し, 色, 補足, 録れている音の集まり, 折りたたんだ時の短い見出し)"""
        st = self.status
        if not st or time.time() - st.get("updated", 0) > STALE:
            return "中継が止まっています", RED, "録画されていません（DanDeskCamRelay が動いていない）", set(), "■ 中継停止"
        if not st.get("relaying"):
            if st.get("switching"):
                return "つなぎ直し中…", GRAY, "中継を張り直しています（数秒）", set(), "つなぎ直し中…"
            return "カメラ未接続", GRAY, "録画していません。つなぐと両方のマイクで録ります", set(), "カメラ未接続"
        if st.get("sending") is False:
            return ("NASへ送れていません", RED, "映像がNASへ流れていません（自動で張り直します）", set(),
                    "■ NASへ送れていない")
        audio = st.get("audio")
        if audio == "motu":
            if not st.get("spare"):
                return ("● SM7dB だけ録音中", RED, "カメラのマイクが録れていません（自動で録り直します）", {"motu"},
                        "● カメラのマイクなし")
            if self.meters["camera"].alive and self.meters["camera"].zeros > SILENT:
                return ("● SM7dB だけ録音中", RED, "カメラのマイクが無音です（つなぎ直した直後は数十秒続きます）", {"motu"},
                        "● カメラのマイク無音")
            return "● 両方のマイクを録音中", GREEN, "どちらを使うかは編集の時に選べます", {"motu", "camera"}, "● 両方録音中"
        if audio == "camera":
            if st.get("requested") == "motu":
                return ("● カメラのマイクだけ録音中", RED, "SM7dB（MOTU）が見つかりません。つなぐと自動で戻ります", {"camera"},
                        "● SM7dBなし")
            return "● カメラのマイクだけ録音中", RED, "SM7dB を録らない設定です（relay.json）", {"camera"}, "● SM7dBなし"
        return "● 音なしで録画中", RED, "マイクが見つかりません", set(), "● 音なし"

    def tick(self):
        if not self.handle_events():
            return
        self.read_status()
        title, color, sub, active, short = self.headline()
        letter = "!" if color == RED else ""
        if self.tray_look != (color, letter, title):
            self.tray_look = (color, letter, title)
            self.tray.icon, self.tray.title = self.badge(color, letter), title.lstrip("●■ ")
        if self.hidden:  # しまっている間は印だけ更新する
            self.root.after(300, self.tick)
            return
        self.head.configure(text=short if self.folded else title, bg=color)
        for widget in (self.fold, self.away, self.bar):
            widget.configure(bg=color)
        if self.folded:  # 札の間は波形を描かない
            self.root.after(300, self.tick)
            return
        self.sub.configure(text=sub)
        nas = self.status.get("audio") if self.status.get("relaying") else None
        for key, (row, name, goes, db, wave) in self.rows.items():
            meter = self.meters[key]
            on = key in active
            row.configure(highlightbackground=GREEN if on else CARD)
            name.configure(fg=TEXT if on else DIM)
            goes.configure(text=("NASの録画へ" if key == nas else GOES_TO[key]) if on else "録れていません")
            levels = list(meter.levels)
            db.configure(text=f"{max(levels[-6:]):.0f} dB" if meter.alive else "未接続", fg=TEXT if on else DIM)
            self.draw(wave, levels if meter.alive else [], GREEN if on else DIM)
        self.root.after(100, self.tick)

    def draw(self, wave, levels, color):
        wave.delete("all")
        w, h = wave.winfo_width(), wave.winfo_height()
        mid, step = h / 2, w / HISTORY
        wave.create_line(0, mid, w, mid, fill="#2b303a")
        for i, level in enumerate(levels):
            half = max(1.0, (level - FLOOR) / -FLOOR * (mid - 2))
            x = i * step
            wave.create_line(x, mid - half, x, mid + half, fill=color, width=max(1, int(step) - 1))

    def cleanup(self):
        for meter in self.meters.values():
            meter.close()

    def quit(self):
        self.cleanup()
        self.tray.stop()
        self.root.destroy()


def main():
    lock = socket.socket()
    try:
        lock.bind(("127.0.0.1", LOCK_PORT))
    except OSError:
        return  # もう出ている
    Panel().root.mainloop()


if __name__ == "__main__":
    main()
