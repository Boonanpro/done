# -*- coding: utf-8 -*-
"""D:/done/.env を暗号化してPC外へ退避する（「合鍵の束に南京錠をかけたコピー」）。

.env は git 管理外で、このPCにしか無い。中には credentials 金庫を開ける鍵
(ENCRYPTION_KEY) も入っているため、失うとクラウドに残った保存パスワード全部が
読めなくなる。そこで gpg の共通鍵暗号 (AES256) で固めたコピーを

  1. ~/.dan/workspace/secrets/done.env.gpg   (dan-workspace リポジトリ → GitLab へ push)
  2. <OneDrive>/DanBackup/done.env.gpg        (クラウド同期)
  3. 週次バックアップの出力ディレクトリ         (dan_backup.py から呼ばれた時)

に置く。復号の暗証番号は ~/.dan/env_backup_passphrase にあり、同じものを本人が
スマホに控える。暗証番号はこのファイル以外（git・ログ・チャット）に書かない。

使い方:
  python scripts/backup_env_encrypted.py            # 暗号化して 1・2 に配置、復号検証
  python scripts/backup_env_encrypted.py --show     # 暗証番号を表示（本人に渡す時だけ）
復元:
  gpg -d done.env.gpg > D:/done/.env   （暗証番号を聞かれる）
"""
from __future__ import annotations

import argparse
import hashlib
import os
import secrets
import shutil
import subprocess
import sys
from pathlib import Path

HOME = Path.home()
ENV_FILE = Path(__file__).resolve().parents[1] / ".env"
PASSPHRASE_FILE = HOME / ".dan" / "env_backup_passphrase"
WORKSPACE_OUT = HOME / ".dan" / "workspace" / "secrets" / "done.env.gpg"
ONEDRIVE = Path(os.environ.get("OneDrive") or (HOME / "OneDrive"))
ONEDRIVE_OUT = ONEDRIVE / "DanBackup" / "done.env.gpg"
NO_WINDOW = getattr(subprocess, "CREATE_NO_WINDOW", 0)


def _gpg() -> str:
    for c in (
        shutil.which("gpg"),
        r"C:\Program Files\Git\usr\bin\gpg.exe",
        r"C:\Program Files (x86)\Git\usr\bin\gpg.exe",
    ):
        if c and Path(c).exists():
            return c
    raise RuntimeError("gpg が見つかりません（Git for Windows に同梱）")


def _passphrase() -> str:
    if PASSPHRASE_FILE.exists():
        return PASSPHRASE_FILE.read_text(encoding="utf-8").strip()
    # 4語×5文字（紛らわしい文字 0/o/1/l を除く）。スマホに打ち込める長さで約100bit。
    alphabet = "abcdefghijkmnpqrstuvwxyz23456789"
    words = ["".join(secrets.choice(alphabet) for _ in range(5)) for _ in range(4)]
    pw = "-".join(words)
    PASSPHRASE_FILE.parent.mkdir(parents=True, exist_ok=True)
    PASSPHRASE_FILE.write_text(pw + "\n", encoding="utf-8")
    return pw


def _run(args: list[str], data: bytes | None = None) -> bytes:
    p = subprocess.run(args, input=data, capture_output=True, creationflags=NO_WINDOW)
    if p.returncode != 0:
        raise RuntimeError(p.stderr.decode("utf-8", "replace")[:400])
    return p.stdout


def encrypt_env(extra_out_dir: Path | None = None) -> list[Path]:
    """暗号化して配置し、復号して元と一致することを確かめる。配置先一覧を返す。"""
    if not ENV_FILE.exists():
        raise FileNotFoundError(ENV_FILE)
    gpg = _gpg()
    pw = _passphrase()
    plain = ENV_FILE.read_bytes()
    cipher = _run(
        [gpg, "--batch", "--yes", "--symmetric", "--cipher-algo", "AES256",
         "--pinentry-mode", "loopback", "--passphrase", pw, "--output", "-"],
        plain,
    )
    back = _run([gpg, "--batch", "--quiet", "--pinentry-mode", "loopback", "--passphrase", pw, "--decrypt"], cipher)
    if hashlib.sha256(back).digest() != hashlib.sha256(plain).digest():
        raise RuntimeError("復号結果が元の .env と一致しません")

    outs = [WORKSPACE_OUT, ONEDRIVE_OUT]
    if extra_out_dir:
        outs.append(Path(extra_out_dir) / "done.env.gpg")
    written: list[Path] = []
    for out in outs:
        if out is ONEDRIVE_OUT and not ONEDRIVE.exists():
            continue
        out.parent.mkdir(parents=True, exist_ok=True)
        out.write_bytes(cipher)
        written.append(out)
    return written


def main() -> int:
    ap = argparse.ArgumentParser()
    ap.add_argument("--show", action="store_true", help="暗証番号を表示する")
    a = ap.parse_args()
    if a.show:
        print(_passphrase())
        return 0
    for p in encrypt_env():
        print(f"wrote {p} ({p.stat().st_size} bytes)")
    print("verified: decrypt(gpg) == .env")
    return 0


if __name__ == "__main__":
    sys.exit(main())
