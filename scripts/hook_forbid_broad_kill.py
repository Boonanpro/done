# -*- coding: utf-8 -*-
"""PreToolUse(Bash) hook: ダン自身のインフラを巻き込むプロセスkillを遮断する。

2026-06-11 実例: ダンが自分の残骸スクリプト（python）を掃除するつもりで
taskkill を実行し、ダンコア(9000)・サンドボックス(8000)も python.exe のため
巻き込んで死亡 → 実行中ターンの回答が未保存のまま消失した。

ブロックする操作:
  1. イメージ名一括kill: taskkill /IM python.exe, pkill python, killall python,
     Stop-Process -Name python など（node も同様: フロント/CLI を巻き込む）
  2. PID指定kill でも、その PID がダンコア/サンドボックス/フロントエンドの
     リスナー（port 9000/8000/3000）の場合

代替手段（ブロックメッセージで案内）: 自分が起動したスクリプトは PID を控えて
`taskkill //F //PID <pid>` で個別に殺す。

exit 0 = 許可 / exit 2 = ブロック（stderr がモデルへのフィードバックになる）。
判定不能な異常時は fail-open（許可）でダンの作業を止めない。
"""
import json
import re
import sys


PROTECTED_PORTS = {9000, 8000, 3000}

# イメージ名一括kill（python/node/uvicorn を巻き込むもの）
BROAD_KILL_PATTERNS = [
    r"taskkill[^&|;\n]*?/+\s*im\s+\S*(python|node|uvicorn)",
    r"\bpkill\b[^&|;\n]*(python|node|uvicorn)",
    r"\bkillall\b[^&|;\n]*(python|node|uvicorn)",
    r"stop-process\b[^|;\n]*-name\b[^|;\n]*(python|node|uvicorn)",
    r"\bwmic\b[^&|;\n]*process[^&|;\n]*(python|node|uvicorn)[^&|;\n]*\b(delete|terminate)\b",
]

BLOCK_MESSAGE = (
    "[BLOCKED] このコマンドはダン自身のインフラ（ダンコア9000/サンドボックス8000/"
    "フロント3000 はいずれも python/node プロセス）を巻き込んで殺す恐れがあるため"
    "遮断しました（2026-06-11 に taskkill でコア巻き込み死の実例あり）。\n"
    "代わりに: 自分が起動したプロセスだけを PID 指定で個別に終了してください。"
    "例: スクリプト起動時に echo $! 等で PID を控え `taskkill //F //PID <pid>`。"
    "PID が分からない場合は `wmic process where \"commandline like '%スクリプト名%'\" get processid` "
    "で自分のスクリプトの PID だけを特定してから kill すること。"
)


def _protected_pids() -> set:
    """ポート 9000/8000/3000 を LISTEN しているプロセスとその親の PID。"""
    pids = set()
    try:
        import psutil
        for conn in psutil.net_connections(kind="tcp"):
            try:
                if conn.laddr and conn.laddr.port in PROTECTED_PORTS and conn.status == "LISTEN" and conn.pid:
                    pids.add(conn.pid)
                    parent = psutil.Process(conn.pid).ppid()
                    if parent:
                        pids.add(parent)
            except Exception:
                continue
    except Exception:
        pass
    return pids


def main() -> int:
    try:
        payload = json.loads(sys.stdin.read() or "{}")
    except Exception:
        return 0
    if payload.get("tool_name") != "Bash":
        return 0
    command = (payload.get("tool_input") or {}).get("command") or ""
    lowered = command.lower()

    if not any(k in lowered for k in ("taskkill", "pkill", "killall", "stop-process", "wmic")):
        return 0

    for pattern in BROAD_KILL_PATTERNS:
        if re.search(pattern, lowered):
            print(BLOCK_MESSAGE, file=sys.stderr)
            return 2

    # PID 指定 kill: 保護対象（コア/サンドボックス/フロント）の PID なら遮断
    pid_matches = re.findall(r"/+\s*pid\s+(\d+)", lowered) + re.findall(
        r"stop-process\b[^|;\n]*-id\s+(\d+)", lowered
    )
    if pid_matches:
        protected = _protected_pids()
        hit = [p for p in pid_matches if int(p) in protected]
        if hit:
            print(
                f"[BLOCKED] PID {', '.join(hit)} はダンコア/サンドボックス/フロントエンド"
                "本体です。これを殺すとダン自身が死にます（チャットも中断されます）。"
                "本当にサンドボックスの再起動が必要なら "
                "`curl -X POST http://127.0.0.1:9000/api/v1/sandbox/restart` を使うこと。",
                file=sys.stderr,
            )
            return 2
    return 0


if __name__ == "__main__":
    sys.exit(main())
