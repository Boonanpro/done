#!/bin/zsh
# dan.paina.info の入口（Cloudflare の固定トンネル）。launchd の com.dan.tunnel から呼ばれる。
# 控えの間（~/.dan/standby がある）は起こさない。本番と控えの両方で動くと Cloudflare が2台に振り分ける。
# 同じトンネルの voice.paina.info は 127.0.0.1:48763 を向いている。そこは Windows から張る
# 中継（scripts/voice_relay_to_mac.ps1、ssh -R）が Windows の音声入力サーバーへつなぐ。
if [ -f "$HOME/.dan/standby" ]; then sleep 60; exit 0; fi
exec /opt/homebrew/bin/cloudflared tunnel --no-autoupdate --protocol http2 --metrics 127.0.0.1:20246 \
  run --token-file "$HOME/.cloudflared/dan-paina.token" >> "$HOME/done/logs/named-tunnel-mac.log" 2>&1
