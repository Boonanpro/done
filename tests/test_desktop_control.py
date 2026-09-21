"""desktop tool against a window this test creates itself.

Never the owner's apps: launching Notepad on Windows 11 restores the owner's open tabs, and an earlier version of
this test overwrote the unsaved buffer of one of them and force-closed Notepad. The fixture below owns its process
and ends only that process id.
"""
import asyncio
import subprocess
import sys
import textwrap
import time

import pytest

pywinauto = pytest.importorskip('pywinauto')
from app.services import desktop_control as dc

TITLE = 'DanDesktopToolTest-7f3a'
APP = textwrap.dedent(f'''
    import tkinter as tk
    root = tk.Tk(); root.title("{TITLE}"); root.geometry("420x200+60+60")
    box = tk.Entry(root, width=40); box.pack(pady=8)
    filled = tk.Entry(root, width=40); filled.insert(0, "owner text already here"); filled.pack(pady=8)
    status = tk.Label(root, text="idle"); status.pack()
    tk.Button(root, text="Apply", command=lambda: status.config(text="applied:"+box.get())).pack()
    tk.Button(root, text="Send", command=lambda: status.config(text="SENT")).pack()
    root.mainloop()
''')


@pytest.fixture
def window():
    proc = subprocess.Popen([sys.executable, '-c', APP])
    try:
        deadline = time.time()+20
        while time.time() < deadline and not any(TITLE in t for t, _ in dc._windows()):
            time.sleep(.3)
        if not any(TITLE in t for t, _ in dc._windows()):
            pytest.skip('test window did not appear')
        yield TITLE
    finally:
        proc.kill()          # this process only; never by image name


def run(params):
    return asyncio.run(dc.run(params))


def test_observe_and_guards_on_an_isolated_window(window):
    assert TITLE in run({'action': 'windows'})['output']
    seen = run({'action': 'observe', 'window': window})
    assert seen['success']
    # Tk exposes little to UI Automation; whatever is listed must be addressable, and the fallback must work.
    shot = run({'action': 'screenshot', 'window': window})
    assert shot['content'][0]['type'] == 'image' and '実寸' in shot['content'][1]['text']
    assert run({'action': 'click', 'window': window, 'x': 10, 'y': 10})['success'] is False      # blind coordinates need approval
    assert run({'action': 'click', 'window': window, 'label': '存在しないボタン名'})['success'] is False
    assert run({'action': 'observe', 'window': 'このタイトルのウィンドウは無い'})['success'] is False
    assert run({'action': 'click', 'ref': '@d999999'})['success'] is False


class FakeValue:
    def __init__(self, text): self.CurrentValue = text; self.set_to = None
    def SetValue(self, text): self.set_to = text


def fake(kind, name, value=None):
    class Info: control_type = kind
    Info.name = name
    class Element:
        element_info = Info()
        pressed = False
        iface_value = value
        def is_enabled(self): return True
        def invoke(self): Element.pressed = True
    return Element()


def test_type_never_replaces_existing_content_silently():
    value = FakeValue('本人が書きかけの下書き')
    dc._refs['@dedit'] = fake('Document', 'テキスト エディター', value)
    refused = run({'action': 'type', 'ref': '@dedit', 'text': 'x'})
    assert refused['success'] is False and value.set_to is None and '置き換わります' in refused['error']
    assert run({'action': 'type', 'ref': '@dedit', 'text': 'x', 'replace': True})['success'] and value.set_to == 'x'
    empty = FakeValue('')
    dc._refs['@dempty'] = fake('Edit', '検索', empty)
    assert run({'action': 'type', 'ref': '@dempty', 'text': 'hello'})['success'] and empty.set_to == 'hello'
    # Enter after typing could send a message in a chat app: refused without the owner's approval.
    assert run({'action': 'type', 'ref': '@dempty', 'text': 'y', 'replace': True, 'press_enter': True})['success'] is False


def test_sensitive_labels_need_confirmation():
    element = fake('Button', '送信')
    dc._refs['@dsend'] = element
    blocked = run({'action': 'click', 'ref': '@dsend'})
    assert blocked['success'] is False and not type(element).pressed and 'confirmed' in blocked['error']
    assert run({'action': 'click', 'ref': '@dsend', 'confirmed': True})['success'] and type(element).pressed
