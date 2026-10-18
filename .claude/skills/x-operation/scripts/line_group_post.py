"""Post a fixed message to a LINE group from the LINE desktop app, one checked step at a time.

LINE usually sits on another Windows virtual desktop (DWM cloaked), so the desktop tool's
window list does not show it and UI Automation exposes no text. This script moves the
window to the current virtual desktop, works through its two Edit boxes (search at the
top, message box at the bottom), and saves a PrintWindow capture after every step so the
caller can read the screen before going on.

  python line_group_post.py open --query 記事タイトルアドバイス   # search and open the first talk -> shot
  python line_group_post.py paste --file message.txt               # paste into the message box -> shot
  python line_group_post.py send                                   # press Enter once -> shot
  python line_group_post.py clear                                  # empty the message box -> shot
  python line_group_post.py restore                                # move LINE back to its desktop

Text always goes through the clipboard: typing goes through the IME and turns katakana
into hiragana, and Enter in the message box sends the message. Read every shot before
the next step (the talk name at the top must be the group name; the box must hold exactly
the message). Captures go to D:/dan-workspace/x_skill/line_post/<step>.png.
"""
import argparse, ctypes, json, sys, time
from pathlib import Path

import win32clipboard, win32gui, win32process, win32ui
from PIL import Image
from pywinauto import Application, mouse
import pywinauto.keyboard as kb
from pyvda import AppView, VirtualDesktop, get_virtual_desktops

OUT = Path('D:/dan-workspace/x_skill/line_post')
STATE = OUT / 'state.json'


def line_window():
    import psutil
    pids = {p.pid for p in psutil.process_iter() if p.name().lower() == 'line.exe'}
    found = []

    def cb(h, _):
        _, pid = win32process.GetWindowThreadProcessId(h)
        if pid in pids and win32gui.GetClassName(h) == 'Qt663QWindowIcon' and win32gui.IsWindowVisible(h):
            l, t, r, b = win32gui.GetWindowRect(h)
            found.append(((r - l) * (b - t), h))
    win32gui.EnumWindows(cb, None)
    if not found:
        sys.exit('LINE の窓が見つかりません（LINE が起動していない）')
    return max(found)[1]


def shot(h, name):
    OUT.mkdir(parents=True, exist_ok=True)
    l, t, r, b = win32gui.GetWindowRect(h)
    w, hh = r - l, b - t
    hdc = win32gui.GetWindowDC(h)
    mfc = win32ui.CreateDCFromHandle(hdc)
    sdc = mfc.CreateCompatibleDC()
    bmp = win32ui.CreateBitmap()
    bmp.CreateCompatibleBitmap(mfc, w, hh)
    sdc.SelectObject(bmp)
    ctypes.windll.user32.PrintWindow(h, sdc.GetSafeHdc(), 2)
    info = bmp.GetInfo()
    im = Image.frombuffer('RGB', (info['bmWidth'], info['bmHeight']), bmp.GetBitmapBits(True), 'raw', 'BGRX', 0, 1)
    win32gui.DeleteObject(bmp.GetHandle()); sdc.DeleteDC(); mfc.DeleteDC(); win32gui.ReleaseDC(h, hdc)
    path = OUT / f'{name}.png'
    im.resize((w // 3, hh // 3)).save(path)
    print(json.dumps({'shot': str(path)}, ensure_ascii=False))


def clip(text):
    win32clipboard.OpenClipboard()
    win32clipboard.EmptyClipboard()
    win32clipboard.SetClipboardText(text, win32clipboard.CF_UNICODETEXT)
    win32clipboard.CloseClipboard()


def edits(h):
    w = Application(backend='uia').connect(handle=h).window(handle=h)
    w.set_focus()
    time.sleep(0.3)
    boxes = sorted(w.descendants(control_type='Edit'), key=lambda e: e.rectangle().top)
    if len(boxes) < 2:
        sys.exit('検索欄と入力欄が見つかりません')
    return boxes[0], boxes[-1]


def main():
    sys.stdout.reconfigure(encoding='utf-8')
    ap = argparse.ArgumentParser()
    ap.add_argument('step', choices=['open', 'paste', 'send', 'clear', 'restore'])
    ap.add_argument('--query')
    ap.add_argument('--file')
    a = ap.parse_args()
    h = line_window()
    if a.step == 'restore':
        st = json.loads(STATE.read_text(encoding='utf-8')) if STATE.exists() else {}
        n = st.get('desktop')
        if n:
            AppView(h).move([d for d in get_virtual_desktops() if d.number == n][0])
        print(json.dumps({'restored_to': n}))
        return
    if a.step == 'open':
        if not a.query:
            sys.exit('--query が要ります')
        OUT.mkdir(parents=True, exist_ok=True)
        view = AppView(h)
        STATE.write_text(json.dumps({'desktop': view.desktop.number}), encoding='utf-8')
        if view.desktop.number != VirtualDesktop.current().number:
            view.move(VirtualDesktop.current())
            time.sleep(0.5)
    search, box = edits(h)
    if a.step == 'open':
        search.click_input(); time.sleep(0.2)
        kb.send_keys('^a{BACKSPACE}'); time.sleep(0.2)
        clip(a.query); kb.send_keys('^v'); time.sleep(1.5)
        r = search.rectangle()
        # the first talk in the results sits about 1.8 search-box heights below the box
        mouse.click(coords=((r.left + r.right) // 2, int(r.bottom + r.height() * 1.8)))
        time.sleep(1.0)
    elif a.step == 'paste':
        text = Path(a.file).read_text(encoding='utf-8').strip('\n')
        box.click_input(); time.sleep(0.2)
        kb.send_keys('^a{BACKSPACE}'); time.sleep(0.2)
        clip(text); kb.send_keys('^v'); time.sleep(1.0)
    elif a.step == 'send':
        box.click_input(); time.sleep(0.2)
        kb.send_keys('{ENTER}'); time.sleep(1.5)
    elif a.step == 'clear':
        box.click_input(); time.sleep(0.2)
        kb.send_keys('^a{BACKSPACE}'); time.sleep(0.5)
    shot(h, a.step)


if __name__ == '__main__':
    main()
