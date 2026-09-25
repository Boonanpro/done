---
name: calendar
description: "Read availability and manage calendar events across every connected calendar account."
---

# calendar スキル

つながっているカレンダーのアカウント（Google など、複数可。`accounts` で一覧）を操作する。**予定の確認・空き確認・登録・変更・削除は必ずこれを使う**。
読むときは全アカウントの予定が、どのアカウントのどのカレンダーかと一緒に返る。書くときは `--account`（アドレスの一部で可）、無ければ既定のアカウントに入る。

## いつ使うか

- メール/チャットで**日程が確定**した（「6/20 15時で」「Zoomで」等）→ 予定を**登録**する
- 相手に**日時を提案する前**→ 自分の**空き時間を確認**してから提案する
- 「今日/今週の予定は？」と聞かれた → **一覧**する

## 使い方（Bash ツールで実行）

```bash
# 今後7日の予定一覧
python D:/done/scripts/dan_calendar.py list --days 7

# 今後5日の空き時間（9-18時）→ 日程提案の前に必ず確認
python D:/done/scripts/dan_calendar.py free --days 5

# 予定を作成（start/end は ISO8601。日本時間で解釈される）
python D:/done/scripts/dan_calendar.py add \
  --title "本田様 打ち合わせ(Zoom)" \
  --start "2026-06-20T15:00:00" --end "2026-06-20T16:00:00" \
  --description "ホームページ制作の件"

# 終日予定は日付のみ
python D:/done/scripts/dan_calendar.py add --title "出張" --start "2026-06-25" --end "2026-06-26"

# 通知（何分前、複数可）と書き込み先のアカウント
python D:/done/scripts/dan_calendar.py add --title "新大阪へ出発" --start "2026-09-24T17:20:00" --end "2026-09-24T17:25:00" --reminders 0 --account 0aw

# 予定を変える（id は list の結果の id。メモは置き換えなので、追記は今のメモ＋追記で渡す）／消す
python D:/done/scripts/dan_calendar.py update --id <id> --description "今のメモ（そのまま）／追記する文" --reminders 10
python D:/done/scripts/dan_calendar.py delete --id <id>

# つながっているアカウントと既定の書き込み先／既定を変える
python D:/done/scripts/dan_calendar.py accounts
python D:/done/scripts/dan_calendar.py default --account 0aw

# アカウントをつなぐ（本人はアドレスを言うだけ。つなぐのはダン）／別のアカウントと入れ替える
python D:/done/scripts/dan_calendar.py connect --account 0aw325171@gmail.com
python D:/done/scripts/dan_calendar.py connect --account new@example.com --replace shub
```

## アカウントをつなぐ（本人に操作を頼まない）

1. `connect --account <アドレス>` で出た `auth_url` をブラウザで開く。
2. そのアカウントを選ぶか入力し、保存済みのログイン情報でログインする（`get_credentials` で id がそのアドレスのもの。パスワードは `fill_credential`、2段階認証は `fill_totp_code`。無ければメール・SMS のコードを受け取る道具）。
3. 許可の画面で、カレンダーの権限にチェックを入れて「続行」「許可」を押す。本人がつなぐよう頼んだ時点で、この許可は本人の意思。
4. 「カレンダーを連携しました」が出たら `accounts` で並んでいるか確かめて報告する。
5. Google が確認画面（自動操作の疑い・端末の確認など）を出したら、ログインを繰り返さずに止め、その画面の内容を報告する。

## パラメータ（add）

| 引数 | 必須 | 説明 |
|---|---|---|
| `--title` | ✅ | 予定タイトル |
| `--start` / `--end` | ✅ | ISO8601(例 2026-06-20T15:00:00)。日付のみなら終日 |
| `--description` | | 詳細 |
| `--location` | | 場所(ZoomのURL等もここに) |

## 返り値

JSON。
- list: `{"events":[{... "account", "calendar", "id"}], "source":{"accounts":[...], "failed":[...]}, "reconnect":[...]}`。
  `failed` があれば、そのアカウントはログインが切れていて読めていない（他は読めている）。`reconnect` の URL を開いてそのアカウントで同意すれば直る。
- add / update 成功: `{"id":..., "account":..., "title":..., "start":..., "link":...}`
- 未連携: `{"error":"カレンダー未連携。設定画面から連携してください。"}` → 設定画面の「カレンダー」で「アカウントを追加」を頼む

## メール連携の型（重要）

- 受信メールで日程が**確定**したら（例: 相手が「6/20 15時で」）→ `add` で登録し、返信案には「カレンダーに登録しました」と添える。
- 返信で**日時を提案**するなら → 先に `free` で空きを確認し、空いている時間だけ提案する。
- 予定の**変更/キャンセル**連絡 → まず `list` で該当予定を確認してから対応する。
