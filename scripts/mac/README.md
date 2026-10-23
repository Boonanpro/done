# ダンを Mac で動かす

2026-10-23 にダンの本体を Mac mini へ移した時の起動の仕組み。

- `run_core.sh` — ダンコア(9000)。コアがサンドボックス(8000)を起こす。`~/.dan/standby` があれば控え(DAN_STANDBY=1)。
- `run_frontend_dev.sh` — 成果物プレビュー(3001)。
- ダッシュボード(3000) は `python scripts/frontend_prod.py build` → `start`（Windows と同じ）。
- launchd: `~/Library/LaunchAgents/com.dan.*.plist`（画面ログイン中に動く。ダンのブラウザは画面ありの Chrome なので、画面ログインが要る）。
- 再起動の後: Windows から `fv_unlock.py` で鍵を開け、`gui_login.sh` で画面にログインすると、launchd がここを起こす。
