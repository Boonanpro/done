"""手元カメラ（Frigate の desk）の「人が映っている時間」だけを残す（期限なし）。

2026-11-18 本人「一旦180日より長く残したい」（Vlog の素材）。書き出しは自動では消さない。
NAS の空きが RESERVE を割る前に書き出しを止める（下の2）。期限を付け直す時は KEEP_DAYS に日数を入れる。

なぜこの作り:
  Frigate 0.17 が録画を消すかどうかは「見返し用の区間（ReviewSegment）」だけで決まる。
  在席判定（Windows の desk_cam_presence.py）が付ける手動の印（label=present）は
  見返し用の区間にならないことを 2026-11-18 に実測で確かめた（10/4〜11/18 で重なり0）。
  そこで、印の区間を Frigate の「書き出し」（-c copy、画質はそのまま）で別の動画として残し、
  録画そのものは continuous の日数（最終的に3日）で消えるようにする。

1回の実行でやること（launchd で1時間ごと）:
  1. 印の区間を集めて、近い区間（5分以内）はつなぐ。終わりが記録されていない印
     （Frigate の再起動で後からまとめて閉じられた印）は、次の印の始まりか4時間で切る。
  2. まだ書き出していない区間を古い順に書き出す。NAS の空きが RESERVE を割りそうなら止める。
     書き出しが済んだら、動画の長さが録画の長さとほぼ同じかを ffprobe で確かめる。
  3. KEEP_DAYS に日数がある時だけ、書き出しの名前が「desk zaiseki」で始まりがそれより前の物を消す。
  4. --manage-retention の時だけ: まだ書き出していない一番古い区間より前の録画が消えてよい
     日数まで continuous の日数を下げる（最小3日）。本人が机にいない時（開いた印が無く、
     最後の印の終わりから10分以上）だけ、2時間に1回まで。下げたら Frigate を再起動し、
     戻ったことと日数を確かめる。
"""
from __future__ import annotations

import argparse
import datetime as dt
import json
import math
import os
import subprocess
import sys
import time
import urllib.error
import urllib.parse
import urllib.request
from collections import Counter
from pathlib import Path

FRIGATE = os.environ.get("FRIGATE_URL", "http://127.0.0.1:15000").rstrip("/")
CAMERA = "desk"
LABEL = "present"
NAME_PREFIX = "desk zaiseki"
MERGE_GAP = 600          # 秒。これ以内に次の印が始まれば1つの区間にする
PRE, POST = 15, 10       # 区間の前後に足す秒（desk の alerts の pre/post と同じ）
SETTLE = 600             # 区間が終わってからこの秒数たってから書き出す
UNKNOWN_END_CAP = 4 * 3600
KEEP_DAYS: float | None = None   # None＝消さない（本人 11/18）
MIN_CONTINUOUS_DAYS = 3
RESERVE_MIB = 25 * 1024  # 書き出した後も NAS にこれだけは空けておく
OWNER_AWAY_SEC = 600
RESTART_COOLDOWN = 2 * 3600
RUN_BUDGET = 50 * 60
EXPORT_TIMEOUT = 40 * 60

STATE_DIR = Path(os.environ.get(
    "DESK_KEEP_STATE", str(Path.home() / ".dan/workspace/data/desk-presence-keep")))
STATE_FILE = STATE_DIR / "state.json"
LOG_FILE = STATE_DIR / "log.jsonl"


# ---------------------------------------------------------------- 小道具
def log(event: str, **kw) -> None:
    rec = {"t": dt.datetime.now().isoformat(timespec="seconds"), "event": event, **kw}
    print(json.dumps(rec, ensure_ascii=False), flush=True)
    STATE_DIR.mkdir(parents=True, exist_ok=True)
    with LOG_FILE.open("a", encoding="utf-8") as f:
        f.write(json.dumps(rec, ensure_ascii=False) + "\n")


def api(method: str, path: str, body: dict | None = None, timeout: float = 60):
    data = json.dumps(body).encode() if body is not None else None
    req = urllib.request.Request(FRIGATE + path, data=data, method=method)
    if data is not None:
        req.add_header("Content-Type", "application/json")
    try:
        with urllib.request.urlopen(req, timeout=timeout) as r:
            raw = r.read()
    except urllib.error.HTTPError as e:
        raw = e.read()
        try:
            return e.code, json.loads(raw)
        except Exception:
            return e.code, raw.decode(errors="replace")
    try:
        return 200, json.loads(raw)
    except Exception:
        return 200, raw.decode(errors="replace")


def get(path: str, timeout: float = 60):
    code, body = api("GET", path, timeout=timeout)
    if code != 200:
        raise RuntimeError(f"GET {path} -> {code} {str(body)[:200]}")
    return body


def load_state() -> dict:
    try:
        return json.loads(STATE_FILE.read_text())
    except Exception:
        return {"failed": {}, "last_restart": 0, "verified": []}


def save_state(st: dict) -> None:
    STATE_DIR.mkdir(parents=True, exist_ok=True)
    tmp = STATE_FILE.with_suffix(".tmp")
    tmp.write_text(json.dumps(st, ensure_ascii=False, indent=1))
    tmp.replace(STATE_FILE)


def fmt(ts: float) -> str:
    return dt.datetime.fromtimestamp(ts).strftime("%m-%d %H%M")


# ---------------------------------------------------------------- 区間
def fetch_events(after: float) -> list[dict]:
    q = urllib.parse.urlencode({"camera": CAMERA, "label": LABEL, "limit": 20000, "after": int(after)})
    return get(f"/api/events?{q}", timeout=120)


def presence_intervals(events: list[dict], now: float) -> tuple[list[list[float]], bool, float]:
    """(つないだ区間, 今開いている印があるか, 最後に印が終わった時刻)"""
    ends = Counter(round(e["end_time"]) for e in events if e.get("end_time"))
    forced = {t for t, c in ends.items() if c >= 3}  # 再起動でまとめて閉じられた終わり
    evs = sorted(events, key=lambda e: e["start_time"])
    starts = [e["start_time"] for e in evs]
    raw: list[tuple[float, float]] = []
    open_now = False
    last_end = 0.0
    for i, e in enumerate(evs):
        s, en = e["start_time"], e.get("end_time")
        nxt = next((x for x in starts[i + 1:] if x > s), None)
        if en is None:
            # 今の印か、閉じ損ねた印
            if now - s < UNKNOWN_END_CAP and (nxt is None):
                open_now = True
                continue
            en = min(nxt or s + UNKNOWN_END_CAP, s + UNKNOWN_END_CAP)
        elif round(en) in forced or en - s > UNKNOWN_END_CAP:
            en = min(en, nxt or en, s + UNKNOWN_END_CAP)
        last_end = max(last_end, en)
        raw.append((s - PRE, en + POST))
    merged: list[list[float]] = []
    for s, en in sorted(raw):
        if merged and s <= merged[-1][1] + MERGE_GAP:
            merged[-1][1] = max(merged[-1][1], en)
        else:
            merged.append([s, en])
    return merged, open_now, last_end


def export_ranges(exports: list[dict]) -> list[tuple[float, float, dict]]:
    out = []
    for x in exports:
        if x.get("camera") != CAMERA:
            continue
        stem = Path(x.get("video_path", "")).stem  # desk_20261004_083845-20261004_101225_xxx
        try:
            _, a, b = stem.split("_", 2)
            a = a + "_" + b.split("-")[0]
            b2 = b.split("-")[1]
            s = dt.datetime.strptime(a, "%Y%m%d_%H%M%S").replace(tzinfo=dt.timezone.utc).timestamp()
            e = dt.datetime.strptime(b2[:15], "%Y%m%d_%H%M%S").replace(tzinfo=dt.timezone.utc).timestamp()
        except Exception:
            continue
        out.append((s, e, x))
    return out


def covered(s: float, e: float, ranges) -> float:
    tot = 0.0
    for a, b, _ in ranges:
        lo, hi = max(s, a), min(e, b)
        if hi > lo:
            tot += hi - lo
    return min(tot, e - s) / max(e - s, 1)


def recorded_seconds(s: float, e: float) -> float:
    q = urllib.parse.urlencode({"after": int(s), "before": int(math.ceil(e))})
    segs = get(f"/api/{CAMERA}/recordings?{q}", timeout=120)
    tot = 0.0
    for g in segs:
        lo, hi = max(s, g["start_time"]), min(e, g["end_time"])
        if hi > lo:
            tot += hi - lo
    return tot


def storage_free_mib() -> float:
    st = get("/api/stats")
    return float(st["service"]["storage"]["/media/frigate/recordings"]["free"])


def bandwidth_mib_per_h() -> float:
    st = get("/api/recordings/storage")
    return float(st.get(CAMERA, {}).get("bandwidth") or 3600)


def ffprobe_duration(url: str) -> float:
    try:
        out = subprocess.run(
            ["ffprobe", "-v", "error", "-show_entries", "format=duration", "-of", "csv=p=0", url],
            capture_output=True, text=True, timeout=120)
        return float(out.stdout.strip() or 0)
    except Exception:
        return 0.0


# ---------------------------------------------------------------- 書き出し
def export_one(s: float, e: float, rec_sec: float) -> tuple[bool, str]:
    name = f"{NAME_PREFIX} {fmt(s)}-{dt.datetime.fromtimestamp(e).strftime('%H%M')}"
    code, body = api("POST", f"/api/export/{CAMERA}/start/{int(s)}/end/{int(math.ceil(e))}",
                     {"playback": "realtime", "source": "recordings", "name": name})
    if code != 200 or not isinstance(body, dict) or not body.get("success"):
        return False, f"start failed {code} {str(body)[:200]}"
    exp_id = body["export_id"]
    t0 = time.time()
    info = None
    while time.time() - t0 < EXPORT_TIMEOUT:
        time.sleep(5)
        c, info = api("GET", f"/api/exports/{exp_id}")
        if c == 200 and isinstance(info, dict) and not info.get("in_progress"):
            break
    else:
        return False, f"timeout {exp_id}"
    vp = (info or {}).get("video_path", "")
    dur = ffprobe_duration(f"{FRIGATE}/exports/{Path(vp).name}")
    # 録画にある秒数の9割以上が動画に入っていれば良しとする
    if dur <= 0 or dur < rec_sec * 0.9 - 5:
        api("DELETE", f"/api/export/{exp_id}")
        return False, f"short export {exp_id} dur={dur:.0f} rec={rec_sec:.0f} (deleted)"
    return True, exp_id


def reconcile_exports(st: dict, exports: list[dict]) -> None:
    """途中で止まった実行が残した、まだ確かめていない書き出しを確かめる。足りなければ消す。"""
    verified = set(st.setdefault("verified", []))
    for s, e, x in export_ranges(exports):
        if x["id"] in verified or x.get("in_progress"):
            continue
        if not (x.get("name") or "").startswith(NAME_PREFIX):
            continue
        dur = ffprobe_duration(f"{FRIGATE}/exports/{Path(x.get('video_path', '')).name}")
        rec = recorded_seconds(s, e)
        if dur > 0 and (rec < 5 or dur >= rec * 0.9 - 5):
            verified.add(x["id"])
            log("verified_existing", id=x["id"], name=x.get("name"), dur=round(dur))
        else:
            api("DELETE", f"/api/export/{x['id']}")
            log("deleted_broken_export", id=x["id"], name=x.get("name"), dur=round(dur), rec=round(rec))
    st["verified"] = sorted(verified)
    save_state(st)


def trusted_ranges(st: dict, exports: list[dict], include_running: bool):
    verified = set(st.get("verified", []))
    return [(s, e, x) for s, e, x in export_ranges(exports)
            if x["id"] in verified or (include_running and x.get("in_progress"))
            or (not x.get("in_progress") and not (x.get("name") or "").startswith(NAME_PREFIX))]


def delete_old_exports(exports: list[dict], now: float, dry: bool) -> int:
    n = 0
    if not KEEP_DAYS:
        return 0
    for s, e, x in export_ranges(exports):
        if not (x.get("name") or "").startswith(NAME_PREFIX):
            continue
        if now - s > KEEP_DAYS * 86400:
            if dry:
                log("would_delete_export", id=x["id"], name=x.get("name"))
            else:
                code, body = api("DELETE", f"/api/export/{x['id']}")
                log("delete_export", id=x["id"], name=x.get("name"), code=code)
            n += 1
    return n


# ---------------------------------------------------------------- 録画の日数
def current_continuous_days() -> float:
    cfg = get("/api/config")
    return float(cfg["cameras"][CAMERA]["record"]["continuous"]["days"])


def set_continuous_days(days: int) -> bool:
    backup = STATE_DIR / "frigate_record_before.json"
    if not backup.exists():
        cfg = get("/api/config")
        backup.write_text(json.dumps({c: v["record"] for c, v in cfg["cameras"].items()}, indent=1))
    q = urllib.parse.urlencode({f"cameras.{CAMERA}.record.continuous.days": days})
    code, body = api("PUT", f"/api/config/set?{q}", {"requires_restart": 1})
    if code != 200:
        log("config_set_failed", code=code, body=str(body)[:300])
        return False
    api("POST", "/api/restart", {})
    t0 = time.time()
    time.sleep(20)
    while time.time() - t0 < 300:
        try:
            if abs(current_continuous_days() - days) < 0.01:
                return True
        except Exception:
            pass
        time.sleep(5)
    return False


# ---------------------------------------------------------------- 本体
def run(args) -> int:
    now = time.time()
    t_start = now
    st = load_state()
    rec_days = sorted(d["day"] for d in get(f"/api/{CAMERA}/recordings/summary", timeout=120))
    oldest_rec = dt.datetime.strptime(rec_days[0], "%Y-%m-%d").timestamp() if rec_days else now
    events = fetch_events(oldest_rec - 86400)
    intervals, open_now, last_end = presence_intervals(events, now)
    exports = get("/api/exports")
    if not args.plan:
        reconcile_exports(st, exports)
        exports = get("/api/exports")
    ranges = trusted_ranges(st, exports, include_running=True) if not args.plan else export_ranges(exports)

    todo = []
    for s, e in intervals:
        if e > now - SETTLE:
            continue
        if e < oldest_rec:
            continue
        if covered(s, e, ranges) >= 0.95:
            continue
        key = f"{int(s)}-{int(e)}"
        if st["failed"].get(key, {}).get("n", 0) >= 3:
            continue
        todo.append((s, e))
    log("plan", intervals=len(intervals), todo=len(todo), todo_hours=round(sum(e - s for s, e in todo) / 3600, 1),
        open_now=open_now, oldest_recording_day=rec_days[0] if rec_days else None)

    if args.plan:
        for s, e in todo[:50]:
            print(fmt(s), "-", fmt(e), round((e - s) / 60), "min")
        return 0

    bw = bandwidth_mib_per_h()
    done = 0
    for s, e in todo:
        if time.time() - t_start > RUN_BUDGET or (args.max and done >= args.max):
            break
        need = (e - s) / 3600 * bw
        free = storage_free_mib()
        if free - need < RESERVE_MIB:
            log("stop_low_space", free_gib=round(free / 1024, 1), need_gib=round(need / 1024, 1))
            break
        rec = recorded_seconds(s, e)
        key = f"{int(s)}-{int(e)}"
        if rec < 5:
            st["failed"][key] = {"n": 3, "why": "no recordings"}
            save_state(st)
            log("skip_no_recordings", start=fmt(s), end=fmt(e))
            continue
        ok, msg = export_one(s, e, rec)
        if ok:
            done += 1
            st.setdefault("verified", []).append(msg)
            save_state(st)
            log("exported", start=fmt(s), end=fmt(e), detail=msg)
        else:
            f = st["failed"].setdefault(key, {"n": 0})
            f["n"] += 1
            f["why"] = msg
            save_state(st)
            log("export_failed", start=fmt(s), end=fmt(e), detail=msg)

    exports = get("/api/exports")
    delete_old_exports(exports, now, dry=False)

    if args.manage_retention:
        manage_retention(st, now)
    save_state(st)
    return 0


def manage_retention(st: dict, now: float) -> None:
    rec_days = sorted(d["day"] for d in get(f"/api/{CAMERA}/recordings/summary", timeout=120))
    oldest_rec = dt.datetime.strptime(rec_days[0], "%Y-%m-%d").timestamp() if rec_days else now
    events = fetch_events(oldest_rec - 86400)
    intervals, open_now, last_end = presence_intervals(events, now)
    ranges = trusted_ranges(st, get("/api/exports"), include_running=False)
    pending = [s for s, e in intervals
               if e >= oldest_rec and covered(s, e, ranges) < 0.95
               and st["failed"].get(f"{int(s)}-{int(e)}", {}).get("n", 0) < 3]
    oldest_pending = min(pending) if pending else now
    # 一番古い未書き出しの区間より前だけが消える日数（1日の余裕を足す）
    target = max(MIN_CONTINUOUS_DAYS, math.ceil((now - oldest_pending) / 86400) + 1)
    cur = current_continuous_days()
    log("retention_check", current_days=cur, target_days=target, pending=len(pending),
        open_now=open_now, minutes_since_present=round((now - last_end) / 60) if last_end else None)
    if target >= cur:
        return
    if open_now or now - last_end < OWNER_AWAY_SEC:
        log("retention_wait_owner_present")
        return
    if now - st.get("last_restart", 0) < RESTART_COOLDOWN:
        log("retention_wait_cooldown")
        return
    c, x = api("GET", "/api/exports")
    if any(e.get("in_progress") for e in (x if isinstance(x, list) else [])):
        log("retention_wait_export_running")
        return
    ok = set_continuous_days(int(target))
    st["last_restart"] = time.time()
    log("retention_set", from_days=cur, to_days=target, ok=ok)


def main() -> int:
    ap = argparse.ArgumentParser(description=__doc__)
    ap.add_argument("--plan", action="store_true", help="書き出す予定の区間だけを表示する")
    ap.add_argument("--max", type=int, default=0, help="この数だけ書き出して止める")
    ap.add_argument("--manage-retention", action="store_true",
                    help="書き出しが追いついた分だけ continuous の日数を下げる（再起動あり）")
    args = ap.parse_args()
    try:
        return run(args)
    except Exception as e:  # launchd の記録に残す
        log("error", error=repr(e)[:500])
        return 1


if __name__ == "__main__":
    sys.exit(main())
