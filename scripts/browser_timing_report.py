"""Summarize local timings without displaying page or user data."""
import argparse
import json
import os
import statistics
from collections import defaultdict
from pathlib import Path


def main():
    parser = argparse.ArgumentParser()
    parser.add_argument("path", nargs="?", default=os.environ.get("DAN_BROWSER_TIMING_LOG") or str(Path.home() / ".dan/logs/browser-timing.jsonl"))
    args = parser.parse_args()
    groups = defaultdict(list)
    requests = []
    path = Path(args.path)
    if not path.exists():
        print("No browser timings recorded yet.")
        return
    for line in path.read_text(encoding="utf-8").splitlines():
        try:
            row = json.loads(line)
            groups[(row["phase"], row["operation"], row["status"])].append(float(row["elapsed_ms"]))
            if row["phase"] == "agent_request": requests.append(row)
        except (ValueError, KeyError, TypeError):
            continue
    if requests:
        print(f"Agent browser requests: {len(requests)}; median wall time {statistics.median(r['elapsed_ms'] for r in requests)/1000:.2f}s; browser calls {sum(r.get('browser_calls',0) for r in requests)}; error events {sum(r.get('error_events',0) for r in requests)}")
        print("A returned result is not independent evidence of task completion.")
    else:
        print("No production agent-request samples yet. Tool timings alone do not establish user-perceived speed.")
    print("phase / operation / status | count | median ms | p95 ms | total ms")
    for key, values in sorted(groups.items()):
        ordered = sorted(values)
        p95 = ordered[min(len(ordered) - 1, int((len(ordered) - 1) * .95))]
        print(f"{' / '.join(key)} | {len(values)} | {statistics.median(values):.2f} | {p95:.2f} | {sum(values):.2f}")
    print("Phases overlap: do not add totals. Agent-request wall time includes model waits; model inference alone is not separately measured.")


if __name__ == "__main__":
    main()
