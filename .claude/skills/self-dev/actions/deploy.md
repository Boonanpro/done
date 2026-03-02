# deploy: テスト完了後のデプロイ手順

## 概要

テスト完了後、ドレインパターンで安全にデプロイする。
他のアクティブセッションが処理中でないことを確認してからgit pushする。

## 前提条件

- modify-and-test が完了していること
- テスト結果に問題がないこと

## 手順

### Step 1: テスト用サーバーの停止

port 8001のテスト用バックエンドを停止する:

```bash
netstat -ano | findstr :8001 | findstr LISTENING
taskkill //F //PID <PID>
```

### Step 2: アクティブセッションの確認

```bash
curl http://127.0.0.1:8000/api/v1/chat/dan/sessions/active-list \
  -H "Authorization: Bearer <token>"
```

レスポンス例:
```json
{"active_session_ids": ["session-abc", "session-xyz"]}
```

- 自分自身のセッション以外にアクティブなものがなければ → Step 4へ
- 他にアクティブなセッションがある → Step 3へ

### Step 3: 待機（ドレインパターン）

- 30秒間隔でポーリング（最大10分）
- 10分経っても空かない場合: ユーザーに報告して判断を仰ぐ
  - 「セッション XXX がまだアクティブです。強制的にデプロイしますか？」

### Step 4: git push

```bash
git add <変更ファイル>
git commit -m "変更内容の説明"
git push origin main
```

### Step 5: 報告

以下のように報告する:

> mainにpushしました。約30秒で自動反映されます。

**絶対に言ってはいけないこと:**
- 「完了しました」（反映はauto_deploy任せ）
- 「再起動しました」（port 8000には触らない）
- 「反映しました」（auto_deployが行う）
