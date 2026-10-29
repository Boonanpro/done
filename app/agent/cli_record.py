# -*- coding: utf-8 -*-
"""担当（Claude Code / Codex の子プロセス）が自分の側に残す記録の置き場所。

2026-10-29 X顧問の部屋で担当が 14:41 に固まった時、担当は自分の詳しい記録を書かない設定で動いて
いて、本体は担当が JSON 以外の形で出した言葉（stderr・JSON でない stdout 行）を読み飛ばしていた。
凍る直前に担当が何を見たか（通信のやり直し・見切り・誤り）を知る手がかりがどこにも残っていなかった。

ここで決めるのは 3 つ:

* ``debug_file_path(room_id)``: Claude Code に ``--debug-file`` で渡す記録ファイル。担当を起こすたびに
  1 本（起こした時刻が名前）。``API error (attempt 1/11)`` のような通信の誤りとやり直しがここに残る。
* ``stray_line(room_id, backend, line)``: 担当が JSON 以外の形で出した言葉を、捨てずに日付ごとの
  ファイルへ残す（Claude・Codex・並行作業の担当で同じ場所）。
* ``prune()``: 古い記録を消す（既定 7 日。部屋ごとの上限も設ける）。担当を起こすたびに呼ぶが、
  実際に歩くのは 1 時間に 1 回。

置き場所は ``<PROJECT_ROOT>/.data/cli_records/<部屋の先頭8桁>/``。``.data/`` は git が追わない。
cli_runner を import しない（streaming_session・codex_runner からも使うので、循環を作らない）。
"""
from __future__ import annotations

import os
import threading
import time
from datetime import datetime
from pathlib import Path
from typing import Optional

PROJECT_ROOT = Path(__file__).resolve().parent.parent.parent  # app/agent/ → app/ → リポジトリの根

_KEEP_DAYS = float(os.environ.get("DAN_CLI_RECORD_KEEP_DAYS", "7"))
_ROOM_CAP_BYTES = int(os.environ.get("DAN_CLI_RECORD_ROOM_CAP_BYTES", str(200 * 1024 * 1024)))
_PRUNE_EVERY_SECONDS = 3600.0
_STRAY_LINE_MAX_CHARS = 2000

_lock = threading.Lock()
_last_prune_at = 0.0


def records_root() -> Path:
    root = os.environ.get("DAN_CLI_RECORDS_DIR")
    return Path(root) if root else PROJECT_ROOT / ".data" / "cli_records"


def room_dir(room_id: str) -> Path:
    key = (room_id or "unknown")[:8] or "unknown"
    return records_root() / key


def debug_file_path(room_id: str, backend: str = "claude", now: Optional[datetime] = None) -> str:
    """担当を起こす時に渡す、その担当だけの詳しい記録ファイル。呼ぶたびに新しい名前になる
    （同じ秒に 2 回起こしても別の名前）。"""
    d = room_dir(room_id)
    d.mkdir(parents=True, exist_ok=True)
    stamp = (now or datetime.now()).strftime("%Y%m%d-%H%M%S")
    base = d / f"{backend}_{stamp}.log"
    n = 1
    path = base
    while path.exists():
        n += 1
        path = d / f"{backend}_{stamp}-{n}.log"
    try:
        path.touch()  # 名前を取った印（同じ秒の次の担当と重ならない。担当が何も書かなくても起動の跡が残る）
    except OSError:
        pass
    return str(path)


def stray_line(room_id: str, backend: str, line: str, *, source: str = "stdout") -> None:
    """担当が JSON 以外の形で出した 1 行を、日付ごとのファイルへ残す。失敗しても呼び手を止めない。"""
    text = (line or "").rstrip("\r\n")
    if not text.strip():
        return
    if len(text) > _STRAY_LINE_MAX_CHARS:
        text = text[:_STRAY_LINE_MAX_CHARS] + "…"
    try:
        d = room_dir(room_id)
        d.mkdir(parents=True, exist_ok=True)
        now = datetime.now()
        path = d / f"stray_{now.strftime('%Y-%m-%d')}.log"
        with open(path, "a", encoding="utf-8") as f:
            f.write(f"[{now.strftime('%H:%M:%S.%f')[:-3]}] [{backend}:{source}] {text}\n")
    except Exception:
        pass


def latest_debug_file(room_id: str) -> Optional[Path]:
    """その部屋で最後に起こした担当の詳しい記録（調べる時の入口）。"""
    d = room_dir(room_id)
    if not d.is_dir():
        return None
    files = sorted((p for p in d.glob("*_*.log") if not p.name.startswith("stray_")), key=lambda p: p.stat().st_mtime)
    return files[-1] if files else None


def prune(*, force: bool = False, now: Optional[float] = None) -> int:
    """古い記録を消す。既定 7 日より古い物と、部屋ごとの上限を超えた分（古い順）。
    消した数を返す。1 時間に 1 回しか歩かない（force で毎回）。"""
    global _last_prune_at
    t = now if now is not None else time.time()
    with _lock:
        if not force and t - _last_prune_at < _PRUNE_EVERY_SECONDS:
            return 0
        _last_prune_at = t
    root = records_root()
    if not root.is_dir():
        return 0
    removed = 0
    cutoff = t - _KEEP_DAYS * 86400
    for d in root.iterdir():
        if not d.is_dir():
            continue
        entries = []
        for p in d.iterdir():
            if not p.is_file():
                continue
            try:
                st = p.stat()
            except OSError:
                continue
            if st.st_mtime < cutoff:
                try:
                    p.unlink()
                    removed += 1
                except OSError:
                    pass
                continue
            entries.append((st.st_mtime, st.st_size, p))
        total = sum(size for _, size, _ in entries)
        for _, size, p in sorted(entries):
            if total <= _ROOM_CAP_BYTES:
                break
            try:
                p.unlink()
                removed += 1
                total -= size
            except OSError:
                pass
        try:
            if not any(d.iterdir()):
                d.rmdir()
        except OSError:
            pass
    return removed
