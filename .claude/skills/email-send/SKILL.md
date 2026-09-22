---
name: email-send
description: "Send authorized email and record it for reply matching. Form replies use the notification workflow."
---

# email-send スキル

ユーザーの指示で外部へメールを送る。**必ずこのスキル経由で送ること**（直接 SMTP やブラウザで送らない）。
理由: このスキルは送信を `external_message_routes` に記録するので、相手の返信を
`email_poller` が自動照合し、通知タブに「返信案」として戻せる。素の送信だと返信に気づけない。

## ⚠️ まず compose_message ツール（既定の経路）

外部宛メールの文面は **`compose_message(action="propose", channel="email", to, subject, body, to_name, intent)`** で送信案カードとして出す。
チャット本文に文面を書いて「これで良ければ送ります」と聞くのは禁止。

- カードはユーザーがその場で本文を直して送信ボタンを押せる（ダンを起こさずに送信される）。
- ユーザーに「送って」と言われたら `compose_message(action="send", proposal_id=...)`。本文は渡さない（DBの現在本文＝ユーザーの編集版が送られる）。
- 送信台帳への記録（返信照合）は send の中で自動で行われる。
- **受信メールへの返信**は `reply_to_message_id`（Message-ID）と `reply_to_subject` を渡す。件名不要・同じスレッドに繋がる（In-Reply-To/References 自動）。
- 編集・送信・破棄の結果は次ターンの冒頭で自動的に知らされる。

下記の `dan_send_email.py` は **カードを経由できない自動化スクリプト内（見張りの定期業務など、ユーザー不在で承認不要と明記された場合）だけ** 使う。

## いつ使うか

- ユーザーが「〜にメールして」「〜に連絡して」「見積もりを送って」等と指示したとき
- 取引先・クライアント・問い合わせ相手・ベンダーへのメール

## 使い方（Bash ツールで実行）

本文は改行や記号で壊れやすいので、**一旦ファイルに書いてから `--body-file` で渡す**のが安全:

```bash
cat > /tmp/mail_body.txt <<'BODY'
山田様

お世話になっております。Done の田中です。
ご依頼の見積書を添付いたします。
ご確認のほどよろしくお願いいたします。
BODY

python D:/done/scripts/dan_send_email.py \
  --to "yamada@example.com" \
  --subject "お見積書の送付" \
  --from-name "株式会社パイナ" \
  --body-file /tmp/mail_body.txt
```

短い本文なら `--body "..."` でも可。

## パラメータ

| 引数 | 必須 | 説明 |
|---|---|---|
| `--to` | ✅ | 宛先メールアドレス |
| `--subject` | ✅ | 件名 |
| `--body` / `--body-file` | ✅(どちらか) | 本文（長文はファイル推奨） |
| `--from-name` | | 差出人表示名（既定: Done）。会社名を名乗るなら指定 |
| `--room` | | 紐づけルームID。既定で環境変数 `$DAN_ROOM_ID`（＝今のチャット）を使うので通常は省略 |

## 返り値

JSON。`{"sent": true, "routing_key": "REF-XXXX", "message_id": "...", "route_id": "..."}` なら成功。
`{"sent": false, "error": "..."}` なら失敗（理由を読んでユーザーに伝える）。

## 送信後: 返信期限の見張りを登録する（必須手順）

送信が成功したら（`"sent": true`）、**必ず** watch で「返信が来ない場合」の見張りを登録する:

```
watch(action="create", at="<返信を待つ期限。目安3営業日後、急ぎなら翌日>",
      note="REF-XXXX（<相手> 宛「<件名>」）の返信が来たか台帳を確認。来ていなければ催促文案を作ってユーザーに提案する。返信済みならこの確認は不要と一言で終える。")
```

- 期限は用件の緊急度で自分で判断する（見積もり→3営業日、日程調整→翌日、等）
- ユーザーが「返事は急がない」「催促不要」と言った場合は登録しない
- ⚠️ **watch(mail_from=相手) は登録しないこと**。返信が来たことの検知は台帳+email_poller が自動で行い、この部屋のダンを起こす。mail見張りを足すと二重検知になる。watchの役割は「来ない場合」だけ。

## 仕組み（覚えておくこと）

- 本文末尾に `[Ref: REF-XXXX]` が自動付与され、X-Dan-Ref ヘッダと Message-ID も付く（返信照合用）。消さない。
- 送信は GMAIL_APP_PASSWORD の SMTP 経由。
- 相手が返信すると数分以内に通知タブへ「メール返信案」が出る（承認で返信送信）。
