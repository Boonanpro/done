#!/bin/zsh
# ダッシュボード(3000)。frontend_prod.py build が記録した最新のビルドで next start する。launchd の com.dan.frontend から呼ばれる。
# 新しいビルドに入れ替える時: python scripts/frontend_prod.py build してから launchctl kickstart -k gui/$(id -u)/com.dan.frontend
export PATH="/opt/homebrew/bin:/usr/bin:/bin:/usr/sbin:/sbin"
cd "$HOME/done/frontend"
dist=$(/usr/bin/python3 -c "import json;print(json.load(open('$HOME/done/.tmp/frontend_prod.json'))['latest_build'])")
export NEXT_DIST_DIR="$dist" NEXT_TELEMETRY_DISABLED=1 NODE_ENV=production \
  DAN_LIVE_PREVIEW_ORIGIN=http://127.0.0.1:3001 NEXT_PUBLIC_DASHBOARD_BUILD="$dist"
exec node node_modules/next/dist/bin/next start -p 3000 -H :: >> "$HOME/done/frontend-prod-3000.log" 2>&1
