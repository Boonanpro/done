# -*- coding: utf-8 -*-
"""GPU-direct preview self-test: launch native_ui, screenshot paused preview,
press Space to play, screenshot during playback, then quit. Screenshots use
PrintWindow(PW_RENDERFULLCONTENT) so the GL swapchain content is captured."""
import ctypes
import ctypes.wintypes as wt
import subprocess
import sys
import time
import os

HERE = os.path.dirname(os.path.abspath(__file__))
EXE = os.path.join(HERE, "target", "release", "native_ui.exe")
LOG = os.path.join(HERE, "selftest_gpu_present.log")

try:
    ctypes.windll.shcore.SetProcessDpiAwareness(2)  # physical pixels everywhere
except Exception:
    pass
u32 = ctypes.windll.user32
g32 = ctypes.windll.gdi32

def find_window(title_sub, timeout=30.0):
    result = []
    @ctypes.WINFUNCTYPE(wt.BOOL, wt.HWND, wt.LPARAM)
    def cb(hwnd, _):
        if not u32.IsWindowVisible(hwnd):
            return True
        buf = ctypes.create_unicode_buffer(256)
        u32.GetWindowTextW(hwnd, buf, 256)
        if title_sub in buf.value:
            result.append(hwnd)
        return True
    t0 = time.time()
    while time.time() - t0 < timeout:
        result.clear()
        u32.EnumWindows(cb, 0)
        if result:
            return result[0]
        time.sleep(0.5)
    return None

def shot(hwnd, path):
    rect = wt.RECT()
    u32.GetWindowRect(hwnd, ctypes.byref(rect))
    w, h = rect.right - rect.left, rect.bottom - rect.top
    hdc = u32.GetWindowDC(hwnd)
    mem = g32.CreateCompatibleDC(hdc)
    bmp = g32.CreateCompatibleBitmap(hdc, w, h)
    g32.SelectObject(mem, bmp)
    PW_RENDERFULLCONTENT = 2
    ok = u32.PrintWindow(hwnd, mem, PW_RENDERFULLCONTENT)
    class BMIH(ctypes.Structure):
        _fields_ = [("biSize", wt.DWORD), ("biWidth", wt.LONG), ("biHeight", wt.LONG),
                    ("biPlanes", wt.WORD), ("biBitCount", wt.WORD), ("biCompression", wt.DWORD),
                    ("biSizeImage", wt.DWORD), ("biXPelsPerMeter", wt.LONG),
                    ("biYPelsPerMeter", wt.LONG), ("biClrUsed", wt.DWORD), ("biClrImportant", wt.DWORD)]
    bmi = BMIH(ctypes.sizeof(BMIH), w, -h, 1, 32, 0, 0, 0, 0, 0, 0)
    buf = ctypes.create_string_buffer(w * h * 4)
    g32.GetDIBits(mem, bmp, 0, h, buf, ctypes.byref(bmi), 0)
    g32.DeleteObject(bmp)
    g32.DeleteDC(mem)
    u32.ReleaseDC(hwnd, hdc)
    try:
        from PIL import Image
        img = Image.frombuffer("RGBA", (w, h), buf.raw, "raw", "BGRA", 0, 1)
        img.save(path)
        print(f"SHOT {path} {w}x{h} printwindow_ok={ok}")
    except ImportError:
        with open(path + ".raw", "wb") as f:
            f.write(buf.raw)
        print(f"SHOT raw {path} {w}x{h}")

def press_space(hwnd):
    u32.SetForegroundWindow(hwnd)
    time.sleep(0.4)
    KEYEVENTF_KEYUP = 2
    u32.keybd_event(0x20, 0, 0, 0)
    time.sleep(0.06)
    u32.keybd_event(0x20, 0, KEYEVENTF_KEYUP, 0)

def click_at(hwnd, frac_x, frac_y):
    rect = wt.RECT()
    u32.GetWindowRect(hwnd, ctypes.byref(rect))
    w, h = rect.right - rect.left, rect.bottom - rect.top
    x, y = rect.left + int(w * frac_x), rect.top + int(h * frac_y)
    u32.SetForegroundWindow(hwnd)
    time.sleep(0.3)
    u32.SetCursorPos(x, y)
    time.sleep(0.2)
    pt = wt.POINT()
    u32.GetCursorPos(ctypes.byref(pt))
    print(f"click target=({x},{y}) cursor=({pt.x},{pt.y}) win=({rect.left},{rect.top},{w}x{h})")
    MOUSEEVENTF_LEFTDOWN, MOUSEEVENTF_LEFTUP = 2, 4
    u32.mouse_event(MOUSEEVENTF_LEFTDOWN, 0, 0, 0, 0)
    time.sleep(0.06)
    u32.mouse_event(MOUSEEVENTF_LEFTUP, 0, 0, 0, 0)

def main():
    log = open(LOG, "w", encoding="utf-8", errors="replace")
    proc = subprocess.Popen([EXE], stderr=log, stdout=log, cwd=HERE)
    hwnd = find_window("done Studio")
    if not hwnd:
        print("FAIL: window not found")
        proc.kill()
        return 1
    print(f"window={hwnd:#x}")
    time.sleep(4.0)
    shot(hwnd, os.path.join(HERE, "st_library.png"))
    # open the first content card ("映像→UGC 4", 341 clips — the CTA-dense doc)
    click_at(hwnd, 200 / 2264, 240 / 1709)
    time.sleep(10.0)  # editor load: first paused compose + ring pre-build
    shot(hwnd, os.path.join(HERE, "st_paused.png"))
    press_space(hwnd)
    time.sleep(4.0)
    shot(hwnd, os.path.join(HERE, "st_play1.png"))
    time.sleep(4.0)
    shot(hwnd, os.path.join(HERE, "st_play2.png"))
    time.sleep(12.0)  # keep playing into denser regions
    shot(hwnd, os.path.join(HERE, "st_play3.png"))
    press_space(hwnd)  # pause
    time.sleep(1.0)
    shot(hwnd, os.path.join(HERE, "st_paused2.png"))
    # seek to the dense zone (~01:20, many small clips + effects) and play 30s
    click_at(hwnd, 1401 / 2264, 1319 / 1709)
    time.sleep(3.0)
    shot(hwnd, os.path.join(HERE, "st_dense_seek.png"))
    press_space(hwnd)
    time.sleep(10.0)
    shot(hwnd, os.path.join(HERE, "st_dense1.png"))
    time.sleep(10.0)
    shot(hwnd, os.path.join(HERE, "st_dense2.png"))
    time.sleep(10.0)
    shot(hwnd, os.path.join(HERE, "st_dense3.png"))
    press_space(hwnd)
    time.sleep(1.0)
    proc.terminate()
    try:
        proc.wait(timeout=5)
    except subprocess.TimeoutExpired:
        proc.kill()
    log.close()
    print("DONE")
    return 0

if __name__ == "__main__":
    sys.exit(main())
