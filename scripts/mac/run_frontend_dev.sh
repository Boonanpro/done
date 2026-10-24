#!/bin/zsh
# 成果物プレビュー用の開発サーバー(3001)。Windows の start_preview_dev.bat と同じ設定。launchd の com.dan.preview から呼ばれる。
export PATH="/opt/homebrew/bin:/usr/bin:/bin:/usr/sbin:/sbin"
export NEXT_DIST_DIR=.next-preview NEXT_ASSET_PREFIX=/_live
cd "$HOME/done/frontend"
exec npm run dev -- --hostname 0.0.0.0 --port 3001 >> "$HOME/done/frontend-dev-3001.log" 2>&1
