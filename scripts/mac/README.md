# ダンを Mac で動かす

2026-10-23 にダンの本体を Mac mini へ移した時の起動の仕組み。

- `run_core.sh` — ダンコア(9000)。コアがサンドボックス(8000)を起こす。`~/.dan/standby` があれば控え(DAN_STANDBY=1)。
- `run_frontend_dev.sh` — 成果物プレビュー(3001)。
- ダッシュボード(3000) は `python scripts/frontend_prod.py build` → `start`（Windows と同じ）。
- launchd: `~/Library/LaunchAgents/com.dan.*.plist`（画面ログイン中に動く。ダンのブラウザは画面ありの Chrome なので、画面ログインが要る）。
- 再起動の後: Windows から `fv_unlock.py` で鍵を開け、`gui_login.sh` で画面にログインすると、launchd がここを起こす。
- `com.dan.ae-sweep`（5分おき）: `python -m app.services.envato_shelf`。呼び出し元が終わった After Effects の書き出しと、使われていない作業フォルダ（2時間以上動きなし）を片付ける。画面で開く After Effects は対象外。記録は `~/.dan/workspace/data/ae-sweep/launchd.log`（片付けた時だけ1行）。
