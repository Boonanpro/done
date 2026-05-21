"""Register Windows Startup entries for Dan auxiliary processes.

- pythonw 系（auto_deploy / observer_scheduler）はターミナル無しで起動する .bat を生成
- shell 系（DanFrontend）はリポジトリ内の .bat を call する薄いラッパーを生成

DanCore.lnk と DanFrontend は Windows Update 等で PC が再起動した後に
ダン本体(9000)・サンドボックス(8000)・フロントエンド(3000) を自動復活させるための要。
"""
import os

PYTHONW = r"C:\Program Files\Python310\pythonw.exe"
WORK_DIR = r"D:\done"

startup_dir = os.path.join(
    os.environ["APPDATA"],
    "Microsoft", "Windows", "Start Menu", "Programs", "Startup",
)

# pythonw で起動する Python スクリプト系
PYTHONW_TASKS = [
    {
        "name": "DanAutoDeploy",
        "script": "scripts\\auto_deploy.py",
        "args": "--bg",
    },
    {
        "name": "DanObserverScheduler",
        "script": "scripts\\observer_scheduler.py",
        "args": "",
    },
]

# リポジトリ内の .bat を呼ぶだけの薄いラッパー系
SHELL_TASKS = [
    {
        "name": "DanFrontend",
        "target_bat": r"D:\done\scripts\start_frontend.bat",
    },
]

for task in PYTHONW_TASKS:
    bat_path = os.path.join(startup_dir, f"{task['name']}.bat")
    script_path = os.path.join(WORK_DIR, task["script"])
    args = f' {task["args"]}' if task["args"] else ""
    cmd = f'@echo off\ncd /d "{WORK_DIR}"\nstart "" "{PYTHONW}" "{script_path}"{args}\n'

    with open(bat_path, "w") as f:
        f.write(cmd)
    print(f"Updated: {bat_path}")

for task in SHELL_TASKS:
    bat_path = os.path.join(startup_dir, f"{task['name']}.bat")
    cmd = f'@echo off\ncall "{task["target_bat"]}"\n'

    with open(bat_path, "w") as f:
        f.write(cmd)
    print(f"Updated: {bat_path}")

print("\nDone.")
