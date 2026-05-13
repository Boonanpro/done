# Cloudflare Named Tunnel

Done の公開版は Vercel からローカルの Dan Core と Sandbox に到達する必要がある。
quick tunnel は URL が変わるため、常用する場合は Cloudflare named tunnel に移行する。

## 前提

- Cloudflare 管理下のドメインを持っている
- この PC で `cloudflared` が使える
- Vercel CLI がログイン済み

## 初回だけ実行

```powershell
cloudflared tunnel login
```

ブラウザで Cloudflare にログインし、使うドメインを選択する。

## tunnel 作成、DNS設定、Vercel更新

`example.com` は Cloudflare 管理下の実ドメインに置き換える。

```powershell
python scripts\setup_cloudflare_named_tunnel.py `
  --core-host done-core.example.com `
  --sandbox-host done-sandbox.example.com `
  --run
```

このスクリプトは以下を行う。

- `done-prod` named tunnel を作成または再利用
- `done-core.example.com` を `127.0.0.1:9000` にルーティング
- `done-sandbox.example.com` を `127.0.0.1:8000` にルーティング
- Vercel production の `CORE_BACKEND_URL` と `BACKEND_URL` を更新
- 古い `NEXT_PUBLIC_API_URL` を削除
- production deploy を実行

## 次回以降の起動

```powershell
cloudflared tunnel --config $env:USERPROFILE\.cloudflared\done-prod.yml run
```

Windows 起動時に常駐させる場合は、上記コマンドをタスクスケジューラに登録する。
