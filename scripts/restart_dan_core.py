"""Stop dan core + sandbox (listeners on 9000/8000 and their start_dan_core/uvicorn
process tree), wait for the ports to free. Launching a fresh core is done
separately so it can run in the background.
"""
import sys
import time
import psutil

PORTS = {8000, 9000}


def listeners():
    found = {}
    for c in psutil.net_connections(kind="inet"):
        if c.status == psutil.CONN_LISTEN and c.laddr and c.laddr.port in PORTS and c.pid:
            found.setdefault(c.pid, set()).add(c.laddr.port)
    return found


def main():
    me = psutil.Process().pid
    l = listeners()
    print("listeners before:", {pid: sorted(ports) for pid, ports in l.items()})

    targets = set()
    for pid in l:
        try:
            p = psutil.Process(pid)
            targets.add(pid)
            for par in p.parents():
                try:
                    cl = " ".join(par.cmdline())
                except Exception:
                    cl = ""
                if "start_dan_core" in cl or "uvicorn" in cl:
                    targets.add(par.pid)
        except Exception as e:
            print("inspect err", pid, e)

    procs = []
    for pid in targets:
        if pid == me:
            continue
        try:
            pr = psutil.Process(pid)
            for ch in pr.children(recursive=True):
                if ch.pid != me:
                    procs.append(ch)
            procs.append(pr)
        except Exception:
            pass
    # dedup
    seen, uniq = set(), []
    for pr in procs:
        if pr.pid not in seen:
            seen.add(pr.pid)
            uniq.append(pr)
    print("terminating PIDs:", sorted(p.pid for p in uniq))
    for pr in uniq:
        try:
            pr.terminate()
        except Exception:
            pass
    gone, alive = psutil.wait_procs(uniq, timeout=8)
    for pr in alive:
        try:
            pr.kill()
        except Exception:
            pass
    time.sleep(2)
    after = listeners()
    print("listeners after:", {pid: sorted(ports) for pid, ports in after.items()})
    if after:
        print("WARNING: ports still occupied")
        sys.exit(1)
    print("OK: 9000 and 8000 are free")


if __name__ == "__main__":
    main()
