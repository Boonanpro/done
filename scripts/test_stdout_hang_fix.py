"""Reproduces the production hang and validates the REAL fix mechanism.

Scenario: a CLI process exits but a surviving grandchild inherits and holds the
stdout write-end, so readline() never sees EOF (blocks forever). On Windows you
cannot cancel that blocked synchronous read from another thread (closing the fd
does NOT interrupt a pending ReadFile). So the fix decouples reading into a daemon
thread feeding a queue; the main loop consumes with a timeout and, once the process
has exited and no new lines arrive within a grace window, stops waiting (the daemon
reader is abandoned — harmless, dies with the process).
"""
import subprocess, sys, threading, time, queue, tempfile, textwrap

PARENT = textwrap.dedent("""
    import subprocess, sys
    print('{"type":"system"}', flush=True)
    print('{"type":"assistant"}', flush=True)
    print('{"type":"result"}', flush=True)
    # grandchild inherits fd 1 (pipe write end) and holds it open past our exit
    subprocess.Popen([sys.executable, "-c", "import time; time.sleep(60)"], close_fds=False)
    sys.exit(0)
""")

def run() -> tuple[float, int]:
    f = tempfile.NamedTemporaryFile("w", suffix=".py", delete=False)
    f.write(PARENT); f.close()
    proc = subprocess.Popen(
        [sys.executable, f.name],
        stdout=subprocess.PIPE, stderr=subprocess.PIPE,
        encoding="utf-8", errors="replace",
    )
    STDOUT_EOF_GRACE = 3
    line_queue: "queue.Queue" = queue.Queue()

    def _reader():
        try:
            while True:
                ln = proc.stdout.readline()
                if not ln:
                    break
                line_queue.put(ln)
        except (ValueError, OSError):
            pass
        finally:
            line_queue.put(None)  # EOF sentinel

    threading.Thread(target=_reader, daemon=True).start()

    start = time.time()
    exited_at = [None]
    lines = []
    while True:
        try:
            line = line_queue.get(timeout=0.5)
        except queue.Empty:
            if proc.poll() is not None:  # process exited
                if exited_at[0] is None:
                    exited_at[0] = time.time()
                elif time.time() - exited_at[0] > STDOUT_EOF_GRACE:
                    # exited + no new lines for grace -> stop (grandchild holds pipe)
                    break
            continue
        if line is None:
            break  # EOF sentinel — clean end
        lines.append(line.strip())
    return time.time() - start, len(lines)

print("=== reader-thread + queue + post-exit grace ===")
elapsed, n = run()
print(f"  read {n} lines, main loop returned in {elapsed:.1f}s")
assert n == 3, f"FAIL: expected 3 lines, got {n}"
assert elapsed < 10, f"FAIL: took {elapsed:.1f}s (should be ~grace, not 60s hang)"
print(f"  PASS: all 3 lines read, completed in {elapsed:.1f}s despite grandchild holding the pipe")
print("DONE")
