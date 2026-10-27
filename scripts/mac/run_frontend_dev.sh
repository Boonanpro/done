#!/bin/zsh
# 成果物プレビュー用の開発サーバー(3001)。Windows の start_preview_dev.bat と同じ設定。launchd の com.dan.preview から呼ばれる。
# 成果物の受け口が起こす Python（表紙の保存・編集アシスタントなど）。PATH に python が無く、×が保存できなかった（2026-10-27）
export PATH="$HOME/dan-venv/bin:/opt/homebrew/bin:/usr/bin:/bin:/usr/sbin:/sbin"
export DAN_PYTHON="$HOME/dan-venv/bin/python"
export NEXT_DIST_DIR=.next-preview NEXT_ASSET_PREFIX=/_live
cd "$HOME/done/frontend"
exec npm run dev -- --hostname 0.0.0.0 --port 3001 >> "$HOME/done/frontend-dev-3001.log" 2>&1
