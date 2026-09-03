# -*- coding: utf-8 -*-
"""実使用の体感時間ログ(.tmp/perf_events.jsonl)を集計する。

使い方: python scripts/perf_report.py [--last N] [--since 2026-09-03T12:00]
出力: surface × event ごとの件数 / 中央値 / p90 / 最大、直近の生イベント。
"""
from __future__ import annotations

import argparse
import json
import statistics
import sys
from pathlib import Path

PATH = Path(__file__).resolve().parents[1] / ".tmp" / "perf_events.jsonl"


def main() -> int:
    ap = argparse.ArgumentParser()
    ap.add_argument("--last", type=int, default=15, help="直近N件の生イベントを表示")
    ap.add_argument("--since", default="", help="この時刻(ISO)以降だけ集計")
    a = ap.parse_args()
    if not PATH.exists():
        print("no events yet:", PATH)
        return 0
    rows = [json.loads(l) for l in PATH.read_text(encoding="utf-8").splitlines() if l.strip()]
    if a.since:
        rows = [r for r in rows if (r.get("received_at") or "") >= a.since]
    groups: dict[tuple[str, str], list[float]] = {}
    for r in rows:
        groups.setdefault((r.get("surface", "?"), r.get("event", "?")), []).append(float(r.get("ms", 0)))
    print(f"{'surface':8} {'event':20} {'n':>4} {'median':>8} {'p90':>8} {'max':>8}")
    for (surface, event), xs in sorted(groups.items()):
        xs.sort()
        p90 = xs[min(len(xs) - 1, int(len(xs) * 0.9))]
        print(f"{surface:8} {event:20} {len(xs):4d} {statistics.median(xs):8.0f} {p90:8.0f} {xs[-1]:8.0f}")
    print("\n-- 直近 --")
    for r in rows[-a.last:]:
        extra = r.get("extra") or {}
        srv = extra.get("server")
        srv_s = f" server={srv.get('total')}ms" if isinstance(srv, dict) else ""
        print(f"{(r.get('received_at') or '')[11:19]} {r.get('surface','?'):6} {r.get('event','?'):18} {float(r.get('ms',0)):6.0f}ms{srv_s} {json.dumps({k: v for k, v in extra.items() if k != 'server'}, ensure_ascii=False)}")
    return 0


if __name__ == "__main__":
    sys.exit(main())
