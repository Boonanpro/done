# -*- coding: utf-8 -*-
"""ダッシュボード(Next.js)を本番ビルドで動かす（port 3000）。

2サーバー構成:
  - 3000: 本番ビルド `next start`（ダッシュボード。描画2〜3倍、タブ移動10倍速）
  - 3001: 開発サーバー `next dev`（成果物プレビュー。HMR が要る。start_preview_dev.bat）

使い方:
  python scripts/frontend_prod.py build     # .next-prod-<n> へビルド（稼働中の3000は止めない）
  python scripts/frontend_prod.py start     # 最新ビルドで 3000 を起動（既存があれば入れ替え）
  python scripts/frontend_prod.py restart   # build + start
  python scripts/frontend_prod.py status

ビルドは出力先を毎回新しいディレクトリ(.next-prod-<unix秒>)にする。稼働中の
`next start` が読んでいる .next-prod-* を書き換えると chunk 欠落で壊れるため。
起動後に古い出力を2世代残して削除する。プロセスはウィンドウ無しで detached 起動
（run_hidden 規律）。PID は .tmp/frontend_prod.pid。
"""
from __future__ import annotations

import json
import os
import shutil
import socket
import subprocess
import sys
import time
import urllib.request
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
FRONTEND = ROOT / "frontend"
TMP = ROOT / ".tmp"
PID_FILE = TMP / "frontend_prod.pid"
STATE_FILE = TMP / "frontend_prod.json"
PORT = int(os.environ.get("DAN_FRONTEND_PORT", "3000"))
NPM = r"C:\Program Files\nodejs\npm.cmd"
NODE = r"C:\Program Files\nodejs\node.exe"
NO_WINDOW = getattr(subprocess, "CREATE_NO_WINDOW", 0)
KEEP_BUILDS = 2

if sys.stdout.encoding and sys.stdout.encoding.lower() != "utf-8":
    sys.stdout.reconfigure(encoding="utf-8", errors="replace")


def log(msg: str) -> None:
    print(f"[frontend-prod] {msg}", flush=True)


def _state() -> dict:
    try:
        return json.loads(STATE_FILE.read_text(encoding="utf-8"))
    except Exception:
        return {}


def _save_state(d: dict) -> None:
    TMP.mkdir(exist_ok=True)
    STATE_FILE.write_text(json.dumps(d, ensure_ascii=False, indent=1), encoding="utf-8")


def _port_open(port: int) -> bool:
    with socket.socket() as s:
        s.settimeout(0.5)
        return s.connect_ex(("127.0.0.1", port)) == 0


def _health(port: int) -> bool:
    try:
        req = urllib.request.Request(f"http://127.0.0.1:{port}/login", headers={"User-Agent": "frontend_prod"})
        with urllib.request.urlopen(req, timeout=5) as r:
            return r.status < 500
    except Exception:
        return False


def build() -> Path:
    dist = f".next-prod-{int(time.time())}"
    # Each build owns its generated route types and incremental cache. Never
    # append historical .next directories to the shared development tsconfig.
    config_name = f"tsconfig{dist}.json"
    config = json.loads((FRONTEND / 'tsconfig.json').read_text(encoding='utf-8'))
    config['include'] = ['next-env.d.ts', 'src/**/*.ts', 'src/**/*.tsx', '*.ts', '*.mts',
                         f'{dist}/types/**/*.ts', f'{dist}/dev/types/**/*.ts']
    config['exclude'] = ['node_modules']
    config['compilerOptions']['tsBuildInfoFile'] = f'{dist}/tsconfig.tsbuildinfo'
    (FRONTEND / config_name).write_text(json.dumps(config, indent=2) + '\n', encoding='utf-8')
    env = dict(os.environ, NEXT_DIST_DIR=dist, NEXT_TSCONFIG=config_name, NEXT_TELEMETRY_DISABLED="1")
    log(f"build -> {dist}")
    t0 = time.time()
    logf = open(TMP / "next_build.log", "w", encoding="utf-8")
    p = subprocess.run([NPM, "run", "build"], cwd=str(FRONTEND), env=env, stdout=logf, stderr=subprocess.STDOUT, creationflags=NO_WINDOW)
    logf.close()
    if p.returncode != 0:
        tail = (TMP / "next_build.log").read_text(encoding="utf-8", errors="replace")[-1500:]
        raise SystemExit(f"build failed (exit {p.returncode}):\n{tail}")
    log(f"build ok in {time.time() - t0:.0f}s")
    st = _state()
    st["latest_build"] = dist
    _save_state(st)
    return FRONTEND / dist


def _kill_pid(pid: int) -> None:
    subprocess.run(["taskkill", "/F", "/T", "/PID", str(pid)], capture_output=True, creationflags=NO_WINDOW)


def _kill_port(port: int) -> None:
    out = subprocess.run(["netstat", "-ano"], capture_output=True, text=True, creationflags=NO_WINDOW).stdout
    for line in out.splitlines():
        if f":{port} " in line and "LISTENING" in line:
            pid = line.split()[-1]
            if pid.isdigit() and int(pid) != os.getpid():
                _kill_pid(int(pid))


def start() -> None:
    st = _state()
    dist = st.get("latest_build")
    if not dist or not (FRONTEND / dist / "BUILD_ID").exists():
        raise SystemExit("no build yet: run `python scripts/frontend_prod.py build` first")
    old_pid = st.get("pid")
    # 先に新プロセスを別ポートで上げてから入れ替える手もあるが、同一ポートで
    # 待ち受ける必要があるので「止めて→上げる」（実測 数秒の空白）。
    if old_pid:
        _kill_pid(int(old_pid))
    _kill_port(PORT)
    for _ in range(20):
        if not _port_open(PORT):
            break
        time.sleep(0.25)
    env = dict(os.environ, NEXT_DIST_DIR=dist, NEXT_TELEMETRY_DISABLED="1", NODE_ENV="production")
    TMP.mkdir(exist_ok=True)
    out = open(ROOT / "frontend-prod-3000.log", "a", encoding="utf-8")
    flags = NO_WINDOW | getattr(subprocess, "DETACHED_PROCESS", 0) | getattr(subprocess, "CREATE_NEW_PROCESS_GROUP", 0)
    next_bin = FRONTEND / "node_modules" / "next" / "dist" / "bin" / "next"
    p = subprocess.Popen(
        [NODE, str(next_bin), "start", "-p", str(PORT), "-H", "::"],
        cwd=str(FRONTEND), env=env, stdout=out, stderr=subprocess.STDOUT,
        stdin=subprocess.DEVNULL, creationflags=flags, close_fds=True,
    )
    st["pid"] = p.pid
    st["dist"] = dist
    st["started_at"] = time.time()
    _save_state(st)
    PID_FILE.write_text(str(p.pid), encoding="utf-8")
    for i in range(60):
        if _health(PORT):
            log(f"started pid={p.pid} dist={dist} port={PORT} ({i * 0.5:.1f}s)")
            _prune_builds(keep=dist)
            return
        time.sleep(0.5)
    raise SystemExit("frontend did not become healthy within 30s; see frontend-prod-3000.log")


def _prune_builds(keep: str) -> None:
    builds = sorted([d for d in FRONTEND.glob(".next-prod-*") if d.is_dir()], key=lambda d: d.name)
    for d in builds[:-KEEP_BUILDS]:
        if d.name == keep:
            continue
        if d.resolve().parent != FRONTEND.resolve():
            raise RuntimeError('Refusing to prune a build outside the frontend directory')
        shutil.rmtree(d, ignore_errors=True)
        log(f"pruned {d.name}")


def status() -> None:
    st = _state()
    print(json.dumps({**st, "port_open": _port_open(PORT), "healthy": _health(PORT)}, ensure_ascii=False, indent=1))


def main() -> int:
    cmd = sys.argv[1] if len(sys.argv) > 1 else "status"
    if cmd == "build":
        build()
    elif cmd == "start":
        start()
    elif cmd == "restart":
        build()
        start()
    elif cmd == "status":
        status()
    else:
        raise SystemExit(__doc__)
    return 0


if __name__ == "__main__":
    sys.exit(main())
