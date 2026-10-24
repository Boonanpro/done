#!/bin/zsh
# Mac でダンコア(9000)を起こす。launchd の com.dan.core から呼ばれる（サンドボックス 8000 はコアが起こす）。
# ~/.dan/standby があれば控え（DAN_STANDBY=1）として起こす。本番に切り替える時はこのファイルを消して再起動する。
export PATH="$HOME/dan-venv/bin:/opt/homebrew/bin:/usr/local/bin:/usr/bin:/bin:/usr/sbin:/sbin"
export PYTHONIOENCODING=utf-8 LANG=ja_JP.UTF-8 LC_ALL=ja_JP.UTF-8
unset CLAUDECODE
# Claude の1年鍵（claude setup-token で作る）。あれば Mac のログインの写しより優先され、鍵の更新の取り合いが起きない。
if [ -f "$HOME/.dan/claude_oauth_token" ]; then export CLAUDE_CODE_OAUTH_TOKEN="$(tr -d "[:space:]" < "$HOME/.dan/claude_oauth_token")"; fi
if [ -f "$HOME/.dan/standby" ]; then export DAN_STANDBY=1; else unset DAN_STANDBY; fi
cd "$HOME/done"
log="$HOME/done/dan_core.log"
if [ -f "$log" ] && [ $(stat -f%z "$log") -gt 20971520 ]; then mv "$log" "$HOME/done/dan_core.previous.log"; fi
exec python -m uvicorn app.core.main:app --host 127.0.0.1 --port 9000 --loop app.core.event_loop:new_loop >> "$log" 2>&1
