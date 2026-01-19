#!/usr/bin/env python3
"""Debug hook - log all inputs to a file."""
import sys
import json
from datetime import datetime

LOG_FILE = "D:/done/hook_debug.log"

def main():
    try:
        stdin_data = sys.stdin.read()

        with open(LOG_FILE, "a", encoding="utf-8") as f:
            f.write(f"\n--- {datetime.now().isoformat()} ---\n")
            f.write(f"stdin: {stdin_data[:500]}\n")

            if stdin_data.strip():
                try:
                    data = json.loads(stdin_data)
                    command = data.get("tool_input", {}).get("command", "")
                    f.write(f"command: {command}\n")
                except:
                    f.write("JSON parse failed\n")
    except Exception as e:
        with open(LOG_FILE, "a", encoding="utf-8") as f:
            f.write(f"Error: {e}\n")

    return 0

if __name__ == "__main__":
    sys.exit(main())
