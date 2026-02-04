#!/usr/bin/env python3
"""Test hook - always blocks uvicorn commands"""
import sys
import json
import datetime

# Log to file
with open("D:/done/logs/hook_test.log", "a") as f:
    f.write(f"[{datetime.datetime.now()}] Hook started\n")

stdin_data = sys.stdin.read()
with open("D:/done/logs/hook_test.log", "a") as f:
    f.write(f"[{datetime.datetime.now()}] stdin: {stdin_data[:100]}\n")

data = json.loads(stdin_data)
command = data.get("tool_input", {}).get("command", "")

if "uvicorn" in command.lower():
    print("HOOK TEST: Blocking uvicorn command", file=sys.stderr)
    sys.exit(2)  # Block

sys.exit(0)
