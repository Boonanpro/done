# -*- coding: utf-8 -*-
"""native_ui のビルド→デプロイを1コマンド化する。

「ビルドはしたがデプロイ先に置き忘れて、修正報告と実機が食い違う」事故の根治策。
ランチャー (done_app_launcher.bat) は C:\\Users\\Owner\\.done\\bin\\native_ui_editor.exe
だけを起動するので、ここへのコピーまでやって初めて修正は「反映」される。

usage: python deploy_native.py [--no-build] [--no-relaunch]

やること:
  1. cargo build --release（このチェックアウトから）
  2. 起動中なら更新を保留する（利用中の画面は閉じない）
  3. .done\\bin\\native_ui_editor.exe をバックアップして新ビルドをコピー
  4. 起動していた場合は再起動
  5. ビルドタグ（タイトルバーに出るものと同じ）を表示 → 報告にそのまま書く
"""
import argparse
import os
import re
import shutil
import subprocess
import sys
import time

HERE = os.path.dirname(os.path.abspath(__file__))
EXE_SRC = os.path.join(HERE, "target", "release", "native_ui.exe")
DEPLOY = r"C:\Users\Owner\.done\bin\native_ui_editor.exe"


def build_tag() -> str:
    def git(*args):
        r = subprocess.run(["git", *args], cwd=HERE, capture_output=True, text=True)
        return r.stdout.strip() if r.returncode == 0 else ""
    h = git("rev-parse", "--short", "HEAD") or "nogit"
    dirty = "+" if git("status", "--porcelain", "--untracked-files=no", "--", ".") else ""
    return f"{h}{dirty}"


def running_pids() -> list[str]:
    r = subprocess.run(["tasklist", "/FI", "IMAGENAME eq native_ui_editor.exe", "/FO", "CSV"],
                       capture_output=True, text=True)
    return re.findall(r'"native_ui_editor.exe","(\d+)"', r.stdout or "")


def main() -> int:
    ap = argparse.ArgumentParser()
    ap.add_argument("--no-build", action="store_true", help="ビルド済みのexeをそのまま配る")
    ap.add_argument("--no-relaunch", action="store_true", help="終了させても再起動しない")
    ap.add_argument("--room", default="", help="再起動時にこの部屋を開く (done://production?room_id=...)")
    ap.add_argument('--stage-if-running',action='store_true')
    ap.add_argument('--install-pending',action='store_true')
    a = ap.parse_args()
    pending=DEPLOY+'.pending.exe'
    if a.install_pending:
        deadline=time.monotonic()+86400
        while os.path.exists(pending) and time.monotonic()<deadline:
            if not running_pids():
                try:
                    if os.path.exists(DEPLOY):shutil.copy2(DEPLOY,DEPLOY+'.bak')
                    shutil.copy2(pending,DEPLOY)
                    shutil.copy2(pending,os.path.join(os.path.dirname(DEPLOY),'native_ui_headless.exe'))
                    os.unlink(pending)
                    return 0
                except OSError:pass
            time.sleep(2)
        return 0

    if not a.no_build:
        print("== cargo build --release ==")
        r = subprocess.run(["cargo", "build", "--release"], cwd=HERE)
        if r.returncode != 0:
            print("BUILD FAILED — デプロイ中止")
            return 1
    if not os.path.exists(EXE_SRC):
        print(f"exe が無い: {EXE_SRC}")
        return 1

    was_running = running_pids()
    if was_running:
        if a.stage_if_running:
            shutil.copy2(EXE_SRC,pending)
            subprocess.Popen([sys.executable,__file__,'--install-pending'],stdin=subprocess.DEVNULL,stdout=subprocess.DEVNULL,stderr=subprocess.DEVNULL,
                             creationflags=getattr(subprocess,'CREATE_NO_WINDOW',0))
            print('更新ファイルを準備しました。エディターを閉じた後に自動で反映します。起動中の画面は変更しません。')
            return 0
        print(f"更新を保留しました。エディターを終了してから再実行してください (pid {', '.join(was_running)})")
        return 2

    os.makedirs(os.path.dirname(DEPLOY), exist_ok=True)
    if os.path.exists(DEPLOY):
        shutil.copy2(DEPLOY, DEPLOY + ".bak")
    shutil.copy2(EXE_SRC, DEPLOY)
    # headless copy = the exe the backend uses for render_frame / validate / dumps.
    # It is never held open by the editor, so it can be refreshed at any time and the
    # agent's eyes always match the user's preview build.
    headless = os.path.join(os.path.dirname(DEPLOY), "native_ui_headless.exe")
    try:
        shutil.copy2(EXE_SRC, headless)
        print(f"== headless copy -> {headless} ==")
    except OSError as exc:
        print(f"!! headless copy skipped ({exc}); a dump/validate job may be running — rerun later")
    tag = build_tag()
    print(f"== DEPLOYED {tag} -> {DEPLOY} ==")

    if was_running and not a.no_relaunch:
        args = [DEPLOY]
        if a.room:
            args.append(f"done://production?room_id={a.room}")
        subprocess.Popen(args, cwd=os.path.dirname(DEPLOY),
                         creationflags=subprocess.DETACHED_PROCESS | subprocess.CREATE_NEW_PROCESS_GROUP)
        print("== 再起動しました ==" + (f"（部屋 {a.room}）" if a.room else ""))
    print(f"タイトルバーが [ {tag} ... ] になっていれば反映済み")
    return 0


if __name__ == "__main__":
    sys.exit(main())
