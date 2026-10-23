"""ダンの本体がある Mac mini を、再起動の後も動く状態に戻す（この PC が控えの時、ensure_dan_stack.ps1 が呼ぶ）。

Mac は FileVault がオンなので、停電や更新で再起動すると鍵の画面で止まる。鍵を開けた後もログイン画面で
止まり、画面ログインが無いとダンの本体（launchd の com.dan.*）もダンのブラウザも動かない。
  - ssh（鍵）で入れて、画面ログインがある        -> 何もしない
  - ssh（鍵）で入れるが、画面ログインが無い      -> 画面共有でパスワードを打ってログインする
  - ssh（鍵）で入れないが 22 番が開いている      -> 起動前の ssh なので、パスワードで鍵を開ける
  - 22 番も開いていない                          -> 電源が切れているか起動中。何もしない
同じ操作は3分に1回まで（起動直後はログイン画面の準備が遅く、数回目で通ることがある）。パスワードは保管庫の mac_mini。手順の記録は ~/.dan/workspace/memory/project-mac-mini-remote-20261022.md。
"""
import asyncio
import json
import socket
import subprocess
import sys
import time
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT))
HOST = "192.168.40.172"
OWNER = "2582a188-ff24-4a4f-b989-6063034d90b2"
TOOLS = Path("D:/dan-workspace/mac_mini")          # fv_unlock.py, gui_login.sh, vncvenv (vncdotool)
STATE = ROOT / ".tmp" / "mac_keeper.json"
LOG = ROOT / "logs" / "mac_keeper.log"
CHECK_EVERY, ACT_EVERY = 120, 180
NO_WINDOW = getattr(subprocess, "CREATE_NO_WINDOW", 0)
SSH = [r"C:\Program Files\Git\usr\bin\ssh.exe", "-o", "BatchMode=yes", "-o", "ConnectTimeout=8",
       "-o", f"UserKnownHostsFile={Path.home() / '.ssh' / 'mac_mini_known_hosts'}", f"mikihonda@{HOST}"]


def log(msg):
    LOG.parent.mkdir(exist_ok=True)
    with LOG.open("a", encoding="utf-8") as f:
        f.write(time.strftime("%Y-%m-%d %H:%M:%S ") + msg + "\n")


def password():
    from dotenv import load_dotenv
    load_dotenv(ROOT / ".env")
    from app.services.credentials_service import get_credentials_service
    cred = asyncio.run(get_credentials_service().get_credential(OWNER, "mac_mini")) or {}
    return cred.get("password") or ""


def main():
    state = json.loads(STATE.read_text()) if STATE.exists() else {}
    now = time.time()
    if now - state.get("checked", 0) < CHECK_EVERY:
        return
    state["checked"] = now
    STATE.parent.mkdir(exist_ok=True)
    STATE.write_text(json.dumps(state))
    p = subprocess.run(SSH + ["who | grep -q console && echo GUI || echo NOGUI"], capture_output=True, text=True,
                       timeout=30, creationflags=NO_WINDOW)
    out = (p.stdout or "").strip()
    if p.returncode == 0 and out == "GUI":
        return
    if now - state.get("acted", 0) < ACT_EVERY:
        return
    if p.returncode == 0 and out == "NOGUI":
        action = [r"C:\Program Files\Git\bin\bash.exe", str(TOOLS / "gui_login.sh"), password(), HOST]
        what = "no screen login -> gui_login.sh"
    else:
        try:
            socket.create_connection((HOST, 22), timeout=3).close()
        except OSError:
            return   # off or still starting
        action = [sys.executable, str(TOOLS / "fv_unlock.py"), HOST, "mikihonda", password(), "60"]
        what = "key login refused but port 22 open (pre-boot) -> fv_unlock.py"
    state["acted"] = now
    STATE.write_text(json.dumps(state))
    r = subprocess.run(action, capture_output=True, text=True, timeout=300, cwd=str(TOOLS), creationflags=NO_WINDOW)
    log(f"{what}: exit {r.returncode} {(r.stdout or r.stderr or '').strip()[-200:]}")


if __name__ == "__main__":
    main()
