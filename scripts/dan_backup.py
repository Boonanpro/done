# -*- coding: utf-8 -*-
"""ダンの記録のオフマシン・バックアップ (GitHub push 不能期間の保険)。

何を守るか (このPCにしか存在しないもの):
  - D:/done, D:/done-artifacts, ~/.dan/workspace の git 全履歴 (未pushのcommit含む) → git bundle
  - ~/.claude/projects/**/*.jsonl + ~/.claude/history.jsonl (ターミナルCLIのセッションログ) → zip
  - ~/.claude/projects/D--done/memory (開発CLIのメモリ) → zip に含む

出力:
  D:/dan-archive/backup/<YYYY-MM-DD>/   (ローカル、直近 KEEP 世代を保持)
  <OneDrive>/DanBackup/<YYYY-MM-DD>/    (クラウド同期フォルダへミラー = 別マシン保険、直近1世代 (約3GB))

実行: python scripts/dan_backup.py   (週次タスク DanWeeklyBackup が run_hidden.vbs 経由で起動)
"""
from __future__ import annotations

import os
import shutil
import subprocess
import sys
import zipfile
from datetime import datetime
from pathlib import Path

HOME = Path.home()
ARCHIVE_ROOT = Path(os.environ.get("DAN_ARCHIVE_ROOT") or "D:/dan-archive") / "backup"
ONEDRIVE = Path(os.environ.get("OneDrive") or (HOME / "OneDrive"))
KEEP = 4

REPOS = {
    "done": Path("D:/done"),
    "done-artifacts": Path("D:/done-artifacts"),
    "dan-workspace": HOME / ".dan" / "workspace",
}
CLI_DIRS = [HOME / ".claude" / "projects"]
CLI_FILES = [HOME / ".claude" / "history.jsonl"]

NO_WINDOW = getattr(subprocess, "CREATE_NO_WINDOW", 0)

# タスクスケジューラ/コンソールが cp932 でも落ちないように
for _stream in (sys.stdout, sys.stderr):
    try:
        _stream.reconfigure(encoding="utf-8", errors="replace")
    except Exception:
        pass


def log(msg: str) -> None:
    print(f"[dan_backup] {datetime.now():%H:%M:%S} {msg}", flush=True)


def bundle_repo(name: str, repo: Path, out_dir: Path) -> Path | None:
    if not (repo / ".git").exists():
        log(f"skip {name}: not a git repo ({repo})")
        return None
    out = out_dir / f"{name}.bundle"
    r = subprocess.run(["git", "-C", str(repo), "bundle", "create", str(out), "--all"],
                       capture_output=True, text=True, encoding="utf-8", errors="replace", creationflags=NO_WINDOW)
    if r.returncode != 0:
        log(f"bundle FAILED {name}: {r.stderr.strip()[:300]}")
        return None
    # 未push / 未commit の規模もメモしておく (復元時の目安)
    status = subprocess.run(["git", "-C", str(repo), "status", "--porcelain"], capture_output=True, text=True, encoding="utf-8", errors="replace", creationflags=NO_WINDOW).stdout
    head = subprocess.run(["git", "-C", str(repo), "log", "-1", "--format=%h %ad %s", "--date=short"], capture_output=True, text=True, encoding="utf-8", errors="replace", creationflags=NO_WINDOW).stdout.strip()
    (out_dir / f"{name}.txt").write_text(f"HEAD: {head}\nuncommitted files: {len(status.splitlines())}\n", encoding="utf-8")
    log(f"bundled {name}: {out.stat().st_size/1e6:.1f} MB ({head})")
    return out


def zip_cli_logs(out_dir: Path) -> Path:
    out = out_dir / "claude-cli-logs.zip"
    n = 0
    with zipfile.ZipFile(out, "w", zipfile.ZIP_DEFLATED) as z:
        for d in CLI_DIRS:
            if not d.exists():
                continue
            for p in d.rglob("*"):
                if p.is_file() and p.suffix in (".jsonl", ".md", ".json"):
                    z.write(p, str(p.relative_to(HOME)))
                    n += 1
        for f in CLI_FILES:
            if f.exists():
                z.write(f, str(f.relative_to(HOME)))
                n += 1
    log(f"zipped CLI logs: {n} files, {out.stat().st_size/1e6:.1f} MB")
    return out


def mirror(src: Path) -> None:
    """OneDrive 同期フォルダへ日付ディレクトリごとコピー (rename は OneDrive がロックするので使わない)。"""
    if not ONEDRIVE.exists():
        log(f"OneDrive not found ({ONEDRIVE}); skip mirror")
        return
    root = ONEDRIVE / "DanBackup"
    root.mkdir(parents=True, exist_ok=True)
    dst = root / src.name
    if dst.exists():
        shutil.rmtree(dst, ignore_errors=True)
    shutil.copytree(src, dst)
    for old in sorted(p for p in root.iterdir() if p.is_dir())[:-1]:
        shutil.rmtree(old, ignore_errors=True)
    for junk in root.glob("latest*"):
        shutil.rmtree(junk, ignore_errors=True)
    log(f"mirrored to {dst}")


def prune() -> None:
    dirs = sorted(p for p in ARCHIVE_ROOT.iterdir() if p.is_dir())
    for old in dirs[:-KEEP]:
        shutil.rmtree(old, ignore_errors=True)
        log(f"pruned {old.name}")


def main() -> int:
    stamp = datetime.now().strftime("%Y-%m-%d")
    out_dir = ARCHIVE_ROOT / stamp
    out_dir.mkdir(parents=True, exist_ok=True)
    log(f"start -> {out_dir}")
    ok = True
    for name, repo in REPOS.items():
        if bundle_repo(name, repo, out_dir) is None and name == "done":
            ok = False
    zip_cli_logs(out_dir)
    # 物語データ (週次日記/章/UIスクショ)。GitLab にも push しているが OneDrive 側の保険にも含める
    story = ARCHIVE_ROOT.parent / "story"
    if story.exists():
        outz = out_dir / "story.zip"
        with zipfile.ZipFile(outz, "w", zipfile.ZIP_DEFLATED) as z:
            for f in story.rglob("*"):
                if f.is_file():
                    z.write(f, str(f.relative_to(story.parent)))
        log(f"zipped story: {outz.stat().st_size/1e6:.1f} MB")
    # .env（合鍵の束）は git 管理外なので、gpg で暗号化したコピーを同梱する。
    # 暗証番号は ~/.dan/env_backup_passphrase（本人のスマホにも控えあり）。
    try:
        sys.path.insert(0, str(Path(__file__).resolve().parent))
        from backup_env_encrypted import encrypt_env
        for p in encrypt_env(out_dir):
            log(f"encrypted .env -> {p}")
    except Exception as e:  # noqa: BLE001
        log(f"WARN: .env encryption skipped: {e}")
        ok = False
    (out_dir / "README.txt").write_text(
        "restore: git clone <name>.bundle <dir>   /   unzip claude-cli-logs.zip into %USERPROFILE%\n"
        f"created: {datetime.now().isoformat()}\n", encoding="utf-8")
    mirror(out_dir)
    prune()
    log("done" if ok else "done WITH ERRORS")
    return 0 if ok else 1


if __name__ == "__main__":
    sys.exit(main())
