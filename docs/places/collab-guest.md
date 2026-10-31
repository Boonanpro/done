---
place: collab-guest
name: 招かれた人のチャット
open: /collab
ready: 'textarea[placeholder="メッセージを入力..."]'
watches: [frontend/src/app/collab/join/**/page.tsx, frontend/src/components/collab/*.tsx, frontend/src/hooks/usePushNotification.ts, frontend/src/hooks/useCollabOutbox.ts, frontend/src/lib/collab-*.ts, frontend/worker/index.js]
errors: [このリンクは使えません, この招待リンクは期限切れです]
speak: |
  - 招待された人が使うチャットです。相手への連絡は送信許可のある窓口だけで行います。
  - 試験には試験専用の窓口と参加者を使います。
shows: []
fingerprint: 206f5f43c68df83d
described: b1164a0a9ee558de
---
# 招かれた人のチャット

招待リンクから名前を入れて参加し、文章・画像・動画・書類を送ったり、引用して返信したりする画面です。

## 中にある物

- 名前を入れて参加する入口と、参加者専用の戻り先。
- 日付ごとの会話、既読、引用返信、絵文字の反応、添付ファイル。
- 書きかけの文章・引用・添付の保持。送信待ちは端末に残り、再接続後に重複せず届きます。
- 通知を押すと会話へ戻ります。リンクはページの見出し付きで表示します。
- 通知の初回設定中は「通知を準備しています…」と表示し、完了するまで重ねて押せません。
- 読み込み済みでない引用元も、過去を読み足して開きます。別の参加者は名前付きで左、自分の発言は右に表示します。

## 行き方（みきさんから見て）

試験用の窓口を作り、招待リンクから試験参加者の名前を入れます。以後は参加後の本人専用リンクから開きます。

## 道具で動かす

`place_shot.py collab-guest --no-login --path /collab/join/<試験参加者の本人専用トークン> --base http://localhost:3002 --tag before|after`。
招待トークンは地図やソースに書きません。実機は phone で招待リンクを Chrome に入力し、同じ操作の前後を撮ります。

## 落とし穴

- 地図の既定の入口では本人専用の画面になりません。必ず試験参加者の道を --path に渡します。
- スマホ幅のブラウザ試験だけでは、実機のキーボード・通知音・ホーム画面追加を確かめたことになりません。
- 日をまたいだ再入室は実際に日をまたいで確かめます。
- 本物の相手を招いたり試験メッセージを送ったりしません。

<!-- place_map:auto:start -->
## コードから（自動）

`python scripts/place_map.py stamp collab-guest` が書き直す。手で直さない。

- 見張るファイル: `frontend/src/app/collab/join/[token]/page.tsx`, `frontend/src/components/collab/link-preview.tsx`, `frontend/src/components/collab/pending-attachments.tsx`, `frontend/src/components/collab/reaction-bar.tsx`, `frontend/src/hooks/useCollabOutbox.ts`, `frontend/src/hooks/usePushNotification.ts`, `frontend/src/lib/collab-draft.ts`, `frontend/src/lib/collab-identity.ts`, `frontend/src/lib/collab-scroll.ts`, `frontend/worker/index.js`
- ラベル: 「送信待ちのメッセージ」、「引用返信をやめる」、「写真・動画・ファイルを添付」、「引用元のメッセージを開く」、「引用して返信」、「添付を外す」、「リアクションを追加」
- 見出し: 「通知を受け取るには」

<!-- place_map:files {"frontend/src/app/collab/join/[token]/page.tsx": "75ac025cd2", "frontend/src/components/collab/link-preview.tsx": "f229db56d5", "frontend/src/components/collab/pending-attachments.tsx": "cae79861e8", "frontend/src/components/collab/reaction-bar.tsx": "6f0b04f37b", "frontend/src/hooks/useCollabOutbox.ts": "ad174d6a0c", "frontend/src/hooks/usePushNotification.ts": "3b36d00206", "frontend/src/lib/collab-draft.ts": "3ca5c67deb", "frontend/src/lib/collab-identity.ts": "85d0078a7e", "frontend/src/lib/collab-scroll.ts": "e9631b5d10", "frontend/worker/index.js": "decdf56e94"} -->
<!-- place_map:auto:end -->
