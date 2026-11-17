"""制作の素材台帳（assets.json・contents.json）に残った世代の写しの住所を、本物の住所に書き直す。

2026-11-17: 画面用の写しの住所が dan-workspace/releases/<世代>/uploads/… で書かれていて、その世代が
掃除されるとプレビューが空になった。読む時は app/paths.py shared_file が読み替えるが、台帳を直接読む
道具もあるので台帳そのものも直す。書き直す前に <名前>.bak-release-paths を残す。

    python scripts/fix_release_media_paths.py [--dry-run]
"""
from __future__ import annotations

import argparse
import json
import os
import shutil
import sys
import time
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT))
from app.paths import LIVE_ROOT, shared_file  # noqa: E402


def fix(value):
    if isinstance(value, str):
        return shared_file(value)
    if isinstance(value, list):
        return [fix(v) for v in value]
    if isinstance(value, dict):
        return {k: fix(v) for k, v in value.items()}
    return value


class _Lock:
    """timeline_draft.ContentsLock と同じ印（contents.lock）。書いている作業があれば待つ。"""

    def __init__(self, folder: Path):
        self.path = folder / "contents.lock"

    def __enter__(self):
        deadline = time.time() + 10
        while True:
            try:
                self.fd = os.open(str(self.path), os.O_CREAT | os.O_EXCL | os.O_WRONLY)
                return self
            except FileExistsError:
                if time.time() > deadline:
                    raise TimeoutError(self.path)
                time.sleep(0.1)

    def __exit__(self, *exc):
        os.close(self.fd)
        self.path.unlink(missing_ok=True)


def main() -> None:
    ap = argparse.ArgumentParser()
    ap.add_argument("--dry-run", action="store_true")
    args = ap.parse_args()
    base = LIVE_ROOT / "uploads" / "production-assets"
    total = 0
    for path in sorted(base.glob("*/assets.json")) + sorted(base.glob("*/contents.json")):
        with _Lock(path.parent):
            total += _one(path, args.dry_run)
    print("total", total)


def _one(path: Path, dry_run: bool) -> int:
    before = path.stat().st_mtime_ns
    text = path.read_text(encoding="utf-8")
    if "/releases/" not in text:
        return 0
    data = json.loads(text)
    new = fix(data)
    n = text.count("/releases/") - json.dumps(new, ensure_ascii=False).count("/releases/")
    if not n:
        return 0
    print(f"{path.parent.name[:8]}/{path.name}: {n}")
    if dry_run:
        return n
    if path.stat().st_mtime_ns != before:
        print("  changed while reading; skipped")
        return 0
    shutil.copy2(path, path.with_name(path.name + ".bak-release-paths"))
    tmp = path.with_name(path.name + ".tmp-release-paths")
    indent = 2 if text.startswith("[\n") else None
    tmp.write_text(json.dumps(new, ensure_ascii=False, indent=indent), encoding="utf-8")
    tmp.replace(path)
    return n


if __name__ == "__main__":
    main()
