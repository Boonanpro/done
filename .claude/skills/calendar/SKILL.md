---
name: calendar
description: "Read availability and manage Google Calendar events for scheduling requests."
---

# calendar スキル

運用者のGoogleカレンダー(connected: shub6923)を操作する。**予定の確認・空き確認・登録は必ずこれを使う**。

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
```

## パラメータ（add）

| 引数 | 必須 | 説明 |
|---|---|---|
| `--title` | ✅ | 予定タイトル |
| `--start` / `--end` | ✅ | ISO8601(例 2026-06-20T15:00:00)。日付のみなら終日 |
| `--description` | | 詳細 |
| `--location` | | 場所(ZoomのURL等もここに) |

## 返り値

JSON。
- add 成功: `{"id":..., "title":..., "start":..., "link":...}`（link はGoogleカレンダーのURL）
- 未連携: `{"error":"カレンダー未連携。設定画面から連携してください。"}` → ユーザーに連携を依頼する

## メール連携の型（重要）

- 受信メールで日程が**確定**したら（例: 相手が「6/20 15時で」）→ `add` で登録し、返信案には「カレンダーに登録しました」と添える。
- 返信で**日時を提案**するなら → 先に `free` で空きを確認し、空いている時間だけ提案する。
- 予定の**変更/キャンセル**連絡 → まず `list` で該当予定を確認してから対応する。
