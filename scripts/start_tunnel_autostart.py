"""PC 起動時にトンネルを自動で立て直すためのラッパー。

start_tunnel.py をそのまま自動起動すると、ダンコア(9000)・サンドボックス(8000) が
まだ立ち上がっていない段階でトンネルだけ先に張られてしまう。ここでは両ポートが
実際に応答するまで待ってから start_tunnel.main() を呼ぶ。

Windows のスタートアップから pythonw 経由で起動される想定（コンソール窓なし）。
ログは logs/tunnel_autostart.log に追記する。
"""
from __future__ import annotations

import os
import socket
import sys
import time
from datetime import datetime
from pathlib import Path

REPO_ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(REPO_ROOT))

LOG_DIR = REPO_ROOT / "logs"
LOG_PATH = LOG_DIR / "tunnel_autostart.log"

# 両ポートが開くまで待つ上限。Windows Update 後の初回起動は遅いので長めに取る。
WAIT_TIMEOUT_SEC = 20 * 60
POLL_INTERVAL_SEC = 5
REQUIRED_PORTS = (9000, 8000)


def log(msg: str) -> None:
    line = f"[{datetime.now():%Y-%m-%d %H:%M:%S}] {msg}"
    try:
        LOG_DIR.mkdir(exist_ok=True)
        with open(LOG_PATH, "a", encoding="utf-8") as f:
            f.write(line + "\n")
    except OSError:
        pass
    print(line, flush=True)


def port_open(port: int) -> bool:
    with socket.socket() as s:
        s.settimeout(2)
        return s.connect_ex(("127.0.0.1", port)) == 0


def wait_for_backends() -> bool:
    deadline = time.monotonic() + WAIT_TIMEOUT_SEC
    while time.monotonic() < deadline:
        missing = [p for p in REQUIRED_PORTS if not port_open(p)]
        if not missing:
            return True
        time.sleep(POLL_INTERVAL_SEC)
    log(f"タイムアウト: ポート {missing} が開かないままでした")
    return False


def main() -> int:
    log("=" * 50)
    log("トンネル自動起動を開始")

    if not wait_for_backends():
        # ポートが開かなくてもトンネル自体は張っておく。バックエンドが後から
        # 立ち上がればそのまま通るので、ここで諦めるより張ったほうが復旧が早い。
        log("バックエンド未応答のままトンネルを張ります")
    else:
        log("バックエンド(9000/8000)の応答を確認")

    os.chdir(REPO_ROOT)
    # pythonw から起動されると stdout の行き先が無く、start_tunnel 側の進行ログが
    # まるごと消える。障害時に「どこまで進んだか」が分からないので同じログへ寄せる。
    try:
        LOG_DIR.mkdir(exist_ok=True)
        sink = open(LOG_PATH, "a", encoding="utf-8", buffering=1)
        sys.stdout = sink
        sys.stderr = sink
    except OSError:
        pass

    try:
        import start_tunnel  # noqa: F401  (scripts/ 直下)
    except ImportError:
        sys.path.insert(0, str(REPO_ROOT / "scripts"))
        import start_tunnel

    try:
        start_tunnel.main()
    except SystemExit as e:
        log(f"start_tunnel が終了しました (code={e.code})")
        return int(e.code or 0)
    except Exception as e:  # noqa: BLE001
        log(f"エラー: {type(e).__name__}: {e}")
        return 1
    return 0


if __name__ == "__main__":
    sys.exit(main())
