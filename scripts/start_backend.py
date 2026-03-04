#!/usr/bin/env python3
"""
Backend startup script - THE ONLY WAY to start the backend.

This script:
1. Finds and kills ALL uvicorn processes using wmic (reliable)
2. Waits for port 8000 to be free
3. Starts uvicorn with subprocess.Popen
4. Verifies startup with health check

Usage:
    python scripts/start_backend.py
"""

import re
import subprocess
import sys
import time
import socket
import urllib.request
import urllib.error


def get_uvicorn_processes() -> list[tuple[int, str]]:
    """
    Get all Python processes related to uvicorn using wmic.

    This includes:
    - uvicorn main process (contains "uvicorn" in command)
    - Child processes spawned by uvicorn (contains "parent_pid=" in command)
    """
    try:
        result = subprocess.run(
            ["wmic", "process", "where", "name='python.exe'", "get", "processid,commandline"],
            capture_output=True,
            text=True,
            timeout=10,
        )

        processes = []
        uvicorn_pids = set()

        # First pass: find uvicorn main processes
        for line in result.stdout.split("\n"):
            line = line.strip()
            if not line or "CommandLine" in line:
                continue
            if "uvicorn" in line.lower():
                parts = line.split()
                if parts:
                    try:
                        pid = int(parts[-1])
                        cmdline = " ".join(parts[:-1])[:60]
                        processes.append((pid, cmdline))
                        uvicorn_pids.add(pid)
                    except ValueError:
                        pass

        # Second pass: find child processes (multiprocessing spawn)
        for line in result.stdout.split("\n"):
            line = line.strip()
            if not line or "CommandLine" in line:
                continue
            # Check for multiprocessing spawn children
            if "multiprocessing" in line.lower() and "spawn" in line.lower():
                # Extract parent_pid from command line
                match = re.search(r'parent_pid=(\d+)', line)
                if match:
                    parent_pid = int(match.group(1))
                    # If parent is a uvicorn process (or was killed), include this child
                    parts = line.split()
                    if parts:
                        try:
                            pid = int(parts[-1])
                            if pid not in uvicorn_pids:  # Don't add duplicates
                                cmdline = f"[child of PID {parent_pid}]"
                                processes.append((pid, cmdline))
                        except ValueError:
                            pass

        return processes
    except Exception as e:
        print(f"[start] Error getting processes: {e}")
        return []


def kill_process(pid: int) -> bool:
    """Kill a process by PID using taskkill."""
    try:
        result = subprocess.run(
            ["taskkill", "/F", "/PID", str(pid)],
            capture_output=True,
            text=True,
            timeout=10,
        )
        return result.returncode == 0
    except Exception as e:
        print(f"[start] Error killing PID {pid}: {e}")
        return False


def is_port_free(port: int = 8000) -> bool:
    """Check if port is free."""
    with socket.socket(socket.AF_INET, socket.SOCK_STREAM) as s:
        return s.connect_ex(('127.0.0.1', port)) != 0


def check_health(timeout: int = 5) -> bool:
    """Check if backend is healthy."""
    try:
        req = urllib.request.Request(
            "http://127.0.0.1:8000/health",
            headers={"User-Agent": "start_backend.py"}
        )
        with urllib.request.urlopen(req, timeout=timeout) as resp:
            return resp.status == 200
    except Exception:
        return False


def _get_own_process_tree() -> set[int]:
    """
    Get PIDs of the entire Claude Code session: ancestors AND all descendants
    of the claude.exe root process.

    Previous bug: only ancestors were protected, so sibling/child processes
    of claude.exe (workers, language servers, etc.) got killed, crashing
    the Claude Code session.

    Fix: find claude.exe in ancestor chain, then protect ALL its descendants.
    """
    import os
    pids = set()

    try:
        # Step 1: Get ALL processes in one wmic call (efficient)
        proc_parent = {}  # pid -> parent_pid
        proc_name = {}    # pid -> process name (lowercase)
        result = subprocess.run(
            ["wmic", "process", "get", "processid,parentprocessid,name", "/format:csv"],
            capture_output=True, text=True, timeout=10,
        )
        for line in result.stdout.split("\n"):
            line = line.strip()
            if not line or line.startswith("Node"):
                continue
            # CSV format: Node,Name,ParentProcessId,ProcessId
            parts = line.split(",")
            if len(parts) >= 4:
                try:
                    name = parts[1].strip().lower()
                    parent_pid = int(parts[2].strip())
                    pid_val = int(parts[3].strip())
                    proc_parent[pid_val] = parent_pid
                    proc_name[pid_val] = name
                except (ValueError, IndexError):
                    pass

        if not proc_parent:
            print("[start] Warning: wmic CSV returned no processes, falling back to ancestor-only")
            return _get_ancestors_only()

        # Step 2: Trace ancestors from current PID
        claude_root = None
        pid = os.getpid()
        for _ in range(30):
            pids.add(pid)
            # Check if this ancestor is claude.exe
            if proc_name.get(pid) == "claude.exe":
                claude_root = pid
            parent = proc_parent.get(pid)
            if parent is None or parent == 0 or parent in pids:
                break
            pid = parent

        # Step 2b: If no claude.exe found, check if any ancestor node.exe is Claude Code
        if claude_root is None:
            for ancestor_pid in list(pids):
                if proc_name.get(ancestor_pid) == "node.exe":
                    try:
                        cmd_result = subprocess.run(
                            ["wmic", "process", "where", f"processid={ancestor_pid}",
                             "get", "commandline"],
                            capture_output=True, text=True, timeout=5,
                        )
                        if "claude" in cmd_result.stdout.lower():
                            claude_root = ancestor_pid
                            break
                    except Exception:
                        pass

        # Step 3: If we found claude.exe/node-claude, protect ALL its descendants
        if claude_root is not None:
            queue = [claude_root]
            visited = {claude_root}
            while queue:
                p = queue.pop()
                pids.add(p)
                for child_pid, parent_pid in proc_parent.items():
                    if parent_pid == p and child_pid not in visited:
                        visited.add(child_pid)
                        queue.append(child_pid)
            print(f"  [INFO] Protecting Claude Code session (root PID {claude_root}, {len(pids)} processes)")
        else:
            print(f"  [INFO] No claude.exe ancestor found, protecting {len(pids)} ancestor processes only")

    except Exception as e:
        print(f"[start] Warning: could not get process tree: {e}")
        return _get_ancestors_only()

    return pids


def _get_ancestors_only() -> set[int]:
    """Fallback: trace only ancestor PIDs (old behavior)."""
    import os
    pids = set()
    try:
        pid = os.getpid()
        for _ in range(30):
            pids.add(pid)
            result = subprocess.run(
                ["wmic", "process", "where", f"processid={pid}", "get", "parentprocessid"],
                capture_output=True, text=True, timeout=5,
            )
            parent_pid = None
            for line in result.stdout.split("\n"):
                line = line.strip()
                if line and not line.startswith("ParentProcessId"):
                    try:
                        parent_pid = int(line)
                    except ValueError:
                        pass
            if parent_pid is None or parent_pid == 0 or parent_pid in pids:
                break
            pid = parent_pid
    except Exception as e:
        print(f"[start] Warning: ancestor trace failed: {e}")
    return pids


def _get_interactive_claude_pids() -> set[int]:
    """
    Find claude.exe/node claude processes launched from interactive shells
    (powershell, pwsh, cmd, bash, mintty, WindowsTerminal).
    These are the user's Claude Code sessions — must NOT be killed.
    """
    interactive_pids = set()
    try:
        # Build parent->name map
        result = subprocess.run(
            ["wmic", "process", "get", "processid,parentprocessid,name", "/format:csv"],
            capture_output=True, text=True, timeout=10,
        )
        proc_parent = {}
        proc_name = {}
        for line in result.stdout.split("\n"):
            line = line.strip()
            if not line or line.startswith("Node"):
                continue
            parts = line.split(",")
            if len(parts) >= 4:
                try:
                    name = parts[1].strip().lower()
                    parent_pid = int(parts[2].strip())
                    pid_val = int(parts[3].strip())
                    proc_parent[pid_val] = parent_pid
                    proc_name[pid_val] = name
                except (ValueError, IndexError):
                    pass

        SHELL_NAMES = {"powershell.exe", "pwsh.exe", "cmd.exe", "bash.exe",
                       "mintty.exe", "windowsterminal.exe", "conhost.exe"}

        # Find claude.exe whose parent (or grandparent) is a shell
        for pid_val, name in proc_name.items():
            if name != "claude.exe":
                continue
            # Walk up to 5 ancestors looking for a shell
            check_pid = pid_val
            for _ in range(5):
                parent = proc_parent.get(check_pid)
                if parent is None or parent == 0:
                    break
                parent_name = proc_name.get(parent, "")
                if parent_name in SHELL_NAMES:
                    interactive_pids.add(pid_val)
                    # Also protect entire subtree of this interactive session
                    queue = [pid_val]
                    while queue:
                        p = queue.pop()
                        interactive_pids.add(p)
                        for child, par in proc_parent.items():
                            if par == p and child not in interactive_pids:
                                interactive_pids.add(child)
                                queue.append(child)
                    break
                check_pid = parent

    except Exception as e:
        print(f"[start] Warning: could not detect interactive sessions: {e}")
    return interactive_pids


def get_sdk_processes() -> list[tuple[int, str]]:
    """
    Get SDK/CLI-related processes (claude.exe, node claude, and mcp_server.py)
    spawned by project execution (Dan's backend).

    IMPORTANT: Excludes:
    - The current process tree (ancestors) so we don't kill ourselves
    - Interactive Claude Code sessions launched from shells (PowerShell, cmd, etc.)
    """
    own_pids = _get_own_process_tree()
    interactive_pids = _get_interactive_claude_pids()
    protected_pids = own_pids | interactive_pids
    processes = []
    try:
        # claude.exe (SDK agent processes - native binary)
        result = subprocess.run(
            ["wmic", "process", "where", "name='claude.exe'", "get", "processid,commandline"],
            capture_output=True, text=True, timeout=10,
        )
        for line in result.stdout.split("\n"):
            line = line.strip()
            if not line or "CommandLine" in line:
                continue
            parts = line.split()
            if parts:
                try:
                    pid = int(parts[-1])
                    if pid in own_pids:
                        print(f"  [SKIP] claude.exe PID {pid} (own process tree)")
                    elif pid in interactive_pids:
                        print(f"  [SKIP] claude.exe PID {pid} (interactive session)")
                    else:
                        processes.append((pid, "claude.exe"))
                except ValueError:
                    pass

        # Node.js-based claude CLI processes
        # These run as node.exe with "claude" in the command line
        # Exclude: ancestor processes, and frontend dev servers (next, react-scripts, etc.)
        result = subprocess.run(
            ["wmic", "process", "where", "name='node.exe'", "get", "processid,commandline"],
            capture_output=True, text=True, timeout=10,
        )
        for line in result.stdout.split("\n"):
            line = line.strip()
            if not line or "CommandLine" in line:
                continue
            line_lower = line.lower()
            # Skip frontend dev servers (next dev, react-scripts, etc.)
            if any(kw in line_lower for kw in ["next", "react-scripts", "webpack", "vite", "turbopack"]):
                continue
            if "claude" in line_lower:
                parts = line.split()
                if parts:
                    try:
                        pid = int(parts[-1])
                        if pid in own_pids:
                            print(f"  [SKIP] node claude PID {pid} (own process tree)")
                        elif pid in interactive_pids:
                            print(f"  [SKIP] node claude PID {pid} (interactive session)")
                        else:
                            processes.append((pid, "node claude"))
                    except ValueError:
                        pass

        # mcp_server.py (MCP server processes spawned by SDK/CLI)
        result = subprocess.run(
            ["wmic", "process", "where", "name='python.exe'", "get", "processid,commandline"],
            capture_output=True, text=True, timeout=10,
        )
        for line in result.stdout.split("\n"):
            line = line.strip()
            if not line or "CommandLine" in line:
                continue
            if "mcp_server.py" in line:
                parts = line.split()
                if parts:
                    try:
                        pid = int(parts[-1])
                        if pid in own_pids:
                            print(f"  [SKIP] mcp_server.py PID {pid} (own process tree)")
                        elif pid in interactive_pids:
                            print(f"  [SKIP] mcp_server.py PID {pid} (interactive session)")
                        else:
                            processes.append((pid, "mcp_server.py"))
                    except ValueError:
                        pass
    except Exception as e:
        print(f"[start] Error getting SDK processes: {e}")
    return processes


def cleanup() -> bool:
    """Kill all uvicorn processes, SDK processes, and wait for port to be free."""
    print("[start] Step 1: Finding uvicorn processes with wmic...")

    processes = get_uvicorn_processes()

    if not processes:
        print("[start] No uvicorn processes found.")
    else:
        print(f"[start] Found {len(processes)} uvicorn process(es):")
        for pid, cmdline in processes:
            print(f"  PID {pid}: {cmdline}...")

        print("[start] Step 2: Killing all uvicorn processes...")
        for pid, _ in processes:
            if kill_process(pid):
                print(f"  [OK] Killed PID {pid}")
            else:
                print(f"  [FAIL] Could not kill PID {pid}")

    # Kill leftover SDK/CLI processes (claude.exe, node claude, mcp_server.py)
    print("[start] Step 2b: Cleaning up SDK/CLI processes...")
    sdk_procs = get_sdk_processes()
    if not sdk_procs:
        print("[start] No SDK processes found.")
    else:
        print(f"[start] Found {len(sdk_procs)} SDK process(es):")
        for pid, name in sdk_procs:
            print(f"  PID {pid}: {name}")
        for pid, name in sdk_procs:
            if kill_process(pid):
                print(f"  [OK] Killed {name} PID {pid}")
            else:
                print(f"  [FAIL] Could not kill {name} PID {pid}")

    # Wait for port to be free
    print("[start] Step 3: Waiting for port 8000 to be free...")
    for i in range(15):
        if is_port_free(8000):
            print("[start] Port 8000 is free.")
            return True
        print(f"  Waiting... ({i+1}/15)")
        time.sleep(1)

    print("[start] ERROR: Port 8000 is still in use after 15 seconds!")
    return False


def start_uvicorn() -> subprocess.Popen:
    """Start uvicorn server with subprocess.Popen."""
    print("[start] Step 4: Starting uvicorn...")

    cmd = [sys.executable, "-m", "uvicorn", "main:app",
           "--host", "0.0.0.0", "--port", "8000"]

    # CLAUDECODE を除外した環境変数を渡す
    # （Claude Code セッション内から起動しても SDK が動くようにする）
    import os
    clean_env = {k: v for k, v in os.environ.items() if k != "CLAUDECODE"}

    log_file = open("D:/done/backend.log", "w", encoding="utf-8")
    process = subprocess.Popen(
        cmd,
        cwd="D:/done",
        stdout=log_file,
        stderr=log_file,
        env=clean_env,
    )

    print(f"[start] uvicorn started with PID {process.pid}")
    return process


def verify_startup(max_attempts: int = 10) -> bool:
    """Verify backend started successfully."""
    print("[start] Step 5: Verifying startup...")

    for i in range(max_attempts):
        if check_health():
            print("[start] Health check passed!")
            return True
        print(f"  Waiting for backend... ({i+1}/{max_attempts})")
        time.sleep(1)

    print("[start] ERROR: Backend did not respond to health check!")
    return False


def main():
    print("=" * 60)
    print("Backend Startup Script (wmic-based, reliable)")
    print("=" * 60)

    # Step 1-3: Cleanup
    if not cleanup():
        print("[start] Cleanup failed. Aborting.")
        sys.exit(1)

    # Step 4: Start
    process = start_uvicorn()

    # Step 5: Verify
    if verify_startup():
        print("=" * 60)
        print(f"[start] SUCCESS! Backend running on http://127.0.0.1:8000")
        print(f"[start] Process PID: {process.pid}")
        print("=" * 60)
        sys.exit(0)
    else:
        print("[start] Startup verification failed. Killing process...")
        process.terminate()
        sys.exit(1)


if __name__ == "__main__":
    main()
