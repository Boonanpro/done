# 「〇〇さんから連絡来てる？」をメールと LINE でも（2026-11-13）

本人（11/13 0:32）「APIで早く正確になるものは積極的に取り入れて良い」「正確なまま早くする」。Chatwork は API で読めるようにした（PR900）が、メールと LINE は通話からチャットのダンに回り、ブラウザやスマホで開いていた（分単位）。

## 何をどこから読むか（全部読むだけ。送信・既読にしない）

| 相手の場所 | 読む所 | かかる時間 |
|---|---|---|
| メール（gmail=shub6923・gmail2=0aw325171・icloud） | IMAP。3つを並べて、直近7日の見出し→人からのメールだけ本文（引用・HTMLの飾りを除く、先頭60KBまで）→送信済みで本人が後で返したか。名前があれば120日前まで（Gmail は from: 検索、一文字の名前は直近500通の差出人を読む） | 3.5〜5.5秒（つながりを20分使い回す） |
| 公式LINE（イツキ main・VIP・ふくろうP） | Cloudflare D1 itsuki-line の events（Webhook が全部残している） | 0.3秒 |
| 公式LINE（ポルノアンチ） | ~/.dan/workspace/data/pornanti-feedback.sqlite3 の line_events | すぐ |
| 個人の LINE | 開発用 Galaxy S24（本人の LINE のサブ端末）の通知を `adb shell dumpsys notification --noredact` で（トーク名・送り主・本文・時刻） | 0.6秒 |

個人の LINE には公式の読み取り API が無い。通知は未読の分しか残らない（読むと消える）ので、記録係 `python -m app.services.line_notices`（launchd com.dan.line-notices、30秒ごと、`scripts/install_line_notices.py`）が通知を ~/.dan/line-notices/<YYYY-MM>.jsonl に1件1回残す。分からないもの: 記録係が動く前の既読の分、写真・スタンプの中身、本人の返信。その時だけ LINE を開く（通話では「30秒ほどかかる」と先に言う）。

人とお知らせの見分け（`contact_read.automated`）: no-reply 等のアドレス、List-Unsubscribe/List-Id、Precedence bulk、Auto-Submitted、**Return-Path が差出人と違う（SES・SendGrid・bounce.*）、Feedback-ID がある**。11/13 の受信箱で、税理士・DisplayModule は人、Amazon・X・Tesla・楽天・Chatwork 通知はお知らせになった。Qoo10・PayPal は残る。

## 使い方

- 通話: 行き先 contact で、頼みの言葉の「〇〇さん」（`voice_router.named_person`）を名前にして、Chatwork・メール・LINE を並べて先に読み、1回で答える。道具 read_chatwork・read_mail・read_line も通話と調べもの係にある（who は相手の名前だけ。複数語なら全部一致）。
- チャット: lookup(source=contacts, query=名前) で3つまとめて、source=line で LINE だけ。

## 結果（本物の受信箱と記録、tests/voice_backends/contact_*.json、gpt-6-luna、2回ずつ）

| 頼み | 前（11/13 本番） | 後 |
|---|---|---|
| 金さんからメール来てる？（11/5「10月試算表」） | 「確認します」で裏の作業へ・答え無し 11.3秒 | 2/2 正しい 12〜13秒 |
| ディスプレイモジュールから返事来てた？ | — | 2/2 12秒 |
| 日本ゴアから何か連絡来てる？（調整に使っていない） | 「Chatworkには無い。メールも確認しますか？」11.5秒 | 2/2 12.5〜17秒 |
| 上野さんからLINE来てる？（個人LINE） | 「LINEはまだ確認していません」7.3秒 | 2/2 8〜11.5秒 |
| イツキの公式LINEに高橋さんから何か来てた？ | 答え無し 20.1秒 | 名前の取り出しを直した後 1/1 8.8秒（直す前は「公式LINEに高橋」を名前にして2回とも見落とし） |
| 浅香さんから連絡来てる？（調整に使っていない） | — | 2/2 7.5〜9秒 |
| 中村さん（Chatwork）3件 | — | 6/6、ただし1回だけ声の係の返事が49.7秒（モデル側の遅れ） |

Chatwork の中村さんの答えは 11/13 12:00 時点の中身に合わせ直した（7:43「5年間/3回分のみ台本調整を」）。
