# -*- coding: utf-8 -*-
"""native_ui のビルド→デプロイを1コマンド化する。

「ビルドはしたがデプロイ先に置き忘れて、修正報告と実機が食い違う」事故の根治策。
ランチャー (done_app_launcher.bat) は C:\\Users\\Owner\\.done\\bin\\native_ui.exe
だけを起動するので、ここへのコピーまでやって初めて修正は「反映」される。

usage: python deploy_native.py [--no-build] [--no-relaunch]

やること:
  1. cargo build --release（このチェックアウトから）
  2. 起動中の native_ui.exe があれば終了（自動保存はアプリ終了時に走る）
  3. .done\\bin\\native_ui.exe をバックアップして新ビルドをコピー
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
DEPLOY = r"C:\Users\Owner\.done\bin\native_ui.exe"


def build_tag() -> str:
    def git(*args):
        r = subprocess.run(["git", *args], cwd=HERE, capture_output=True, text=True)
        return r.stdout.strip() if r.returncode == 0 else ""
    h = git("rev-parse", "--short", "HEAD") or "nogit"
    dirty = "+" if git("status", "--porcelain", "--untracked-files=no", "--", ".") else ""
    return f"{h}{dirty}"


def running_pids() -> list[str]:
    r = subprocess.run(["tasklist", "/FI", "IMAGENAME eq native_ui.exe", "/FO", "CSV"],
                       capture_output=True, text=True)
    return re.findall(r'"native_ui.exe","(\d+)"', r.stdout or "")


def main() -> int:
    ap = argparse.ArgumentParser()
    ap.add_argument("--no-build", action="store_true", help="ビルド済みのexeをそのまま配る")
    ap.add_argument("--no-relaunch", action="store_true", help="終了させても再起動しない")
    a = ap.parse_args()

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
        print(f"== 起動中の native_ui を終了 (pid {', '.join(was_running)}) ==")
        subprocess.run(["taskkill", "/F", "/IM", "native_ui.exe"], capture_output=True)
        time.sleep(1.0)

    os.makedirs(os.path.dirname(DEPLOY), exist_ok=True)
    if os.path.exists(DEPLOY):
        shutil.copy2(DEPLOY, DEPLOY + ".bak")
    shutil.copy2(EXE_SRC, DEPLOY)
    tag = build_tag()
    print(f"== DEPLOYED {tag} -> {DEPLOY} ==")

    if was_running and not a.no_relaunch:
        subprocess.Popen([DEPLOY], cwd=os.path.dirname(DEPLOY),
                         creationflags=subprocess.DETACHED_PROCESS | subprocess.CREATE_NEW_PROCESS_GROUP)
        print("== 再起動しました ==")
    print(f"タイトルバーが [ {tag} ... ] になっていれば反映済み")
    return 0


if __name__ == "__main__":
    sys.exit(main())
