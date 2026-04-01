"""Register auto_deploy.py and observer_scheduler.py in Windows Startup folder.
Uses pythonw.exe to avoid terminal windows flashing."""
import os

PYTHONW = r"C:\Program Files\Python310\pythonw.exe"
WORK_DIR = r"D:\done"

startup_dir = os.path.join(
    os.environ["APPDATA"],
    "Microsoft", "Windows", "Start Menu", "Programs", "Startup",
)

TASKS = [
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

for task in TASKS:
    bat_path = os.path.join(startup_dir, f"{task['name']}.bat")
    script_path = os.path.join(WORK_DIR, task["script"])
    args = f' {task["args"]}' if task["args"] else ""
    cmd = f'@echo off\ncd /d "{WORK_DIR}"\nstart "" "{PYTHONW}" "{script_path}"{args}\n'

    with open(bat_path, "w") as f:
        f.write(cmd)
    print(f"Updated: {bat_path}")

print("\nDone. Using pythonw.exe (no terminal windows).")
