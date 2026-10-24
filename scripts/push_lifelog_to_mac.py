"""ダンの本体が Mac にある時、この PC で書き足されるピンの録音の文字起こし（.data/lifelog）を Mac へ送る。

文字起こしの道具（DanLifelogWorker）はこの PC に残っている。Mac のダンが「今日話してたあれ」に
答えるには、Mac の ~/done/.data/lifelog に同じものが要る。ensure_dan_stack.ps1 が1分おきに呼ぶが、
送るのは10分に1回、前回から変わったファイルだけ。
"""
import subprocess
import sys
import tarfile
import time
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
LIFELOG = ROOT / ".data" / "lifelog"
STAMP = ROOT / ".tmp" / "push_lifelog_to_mac.stamp"
EVERY = 600
SSH = [r"C:\Program Files\Git\usr\bin\ssh.exe", "-o", "BatchMode=yes",
       "-o", f"UserKnownHostsFile={Path.home() / '.ssh' / 'mac_mini_known_hosts'}", "mikihonda@192.168.40.172"]


def main() -> int:
    now = time.time()
    last = float(STAMP.read_text()) if STAMP.exists() else 0.0
    if now - last < EVERY:
        return 0
    files = [p for p in LIFELOG.glob("*") if p.is_file() and p.stat().st_mtime > last - 60]
    if files:
        proc = subprocess.Popen(SSH + ["mkdir -p ~/done/.data/lifelog && tar -xf - -C ~/done/.data/lifelog"],
                                stdin=subprocess.PIPE, stdout=subprocess.DEVNULL, stderr=subprocess.DEVNULL,
                                creationflags=getattr(subprocess, "CREATE_NO_WINDOW", 0))
        with tarfile.open(fileobj=proc.stdin, mode="w|") as tar:
            for p in files:
                tar.add(str(p), arcname=p.name, recursive=False)
        proc.stdin.close()
        if proc.wait(timeout=120) != 0:
            return 1
    STAMP.parent.mkdir(exist_ok=True)
    STAMP.write_text(str(now))
    return 0


if __name__ == "__main__":
    sys.exit(main())
