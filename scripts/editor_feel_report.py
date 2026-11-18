"""エディターの体感（本人の端末で測った editor-feel）をまとめて見る。

python scripts/editor_feel_report.py [--since 2026-11-18] [--ua Windows]
飛んでから絵が出るまで・再生が流れ出すまで・操作の反応の速さと、0.2秒以上止めた処理の名前を並べる。
"""
import argparse
import collections
import json
from pathlib import Path

PATH = Path(__file__).resolve().parents[1] / ".tmp" / "perf_events.jsonl"


def main() -> None:
    ap = argparse.ArgumentParser()
    ap.add_argument("--since", default="")
    ap.add_argument("--ua", default="")
    a = ap.parse_args()
    rows = []
    with open(PATH, encoding="utf-8") as f:
        for line in f:
            if '"editor-feel"' not in line:
                continue
            r = json.loads(line)
            if r.get("at", "") < a.since or a.ua not in (r.get("ua") or ""):
                continue
            rows.append(r)
    seek, start, inp = [], [], []
    culprits = collections.Counter()
    culprit_ms = collections.Counter()
    for r in rows:
        x = r.get("extra") or {}
        print(r["at"][:19], (r.get("ua") or "")[13:30], "seek", x.get("seek"), "start", x.get("start"),
              "input", x.get("input"), "stalls", x.get("stalls"), "frozen", x.get("frozen_ms"))
        for lf in x.get("loaf") or []:
            for s in lf.get("scripts") or [{"what": "(画面の描き直し)", "ms": lf.get("ms")}]:
                culprits[s["what"]] += 1
                culprit_ms[s["what"]] += s["ms"]
    print("\n0.2秒以上止めた処理（回数・合計ms）")
    for k, v in culprit_ms.most_common(15):
        print(f"{culprits[k]:4d} {v:7d}  {k}")
    if rows:
        print("\n端末:", {k: rows[-1]["extra"].get(k) for k in ("cores", "mem_gb", "gpu", "dpr", "screen")})


if __name__ == "__main__":
    main()
