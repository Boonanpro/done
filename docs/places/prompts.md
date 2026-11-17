---
place: prompts
name: ダンを動かしている指示文
open: /prompts
ready: 'img[alt="ダンの中の場所"]'
watches: [frontend/src/app/prompts/page.tsx, frontend/src/lib/prompts-api.ts, app/api/prompts_screen.py, app/services/prompt_store.py, app/prompts/catalog.json]
errors: [ログインが切れています, 失敗しました]
speak: |
  - ダンの各係が読む指示文を、みきさんが読んで直し、前の版に戻す画面です。
  - 試す時は DAN_PROMPTS_DIR を一時の場所にして、本物の指示文を書き換えません。
shows: []
---
# ダンを動かしている指示文

上に家の断面の絵があり、場所の札（みきさん・通話のダン・振り分け・判断役・調べもの係・通話の画面・作業の部屋・エディター・チャットのダン）を押すと、その場所の係が読む指示文の一覧が出ます。一覧を押すと全文・誰が読むか・いつ効くか・なぜある文か・履歴が出て、直して保存、前の版に戻すができます。

## 中にある物

- 家の断面の絵と、場所の札（数字はその場所の文の数）。
- 場所ごとの一覧。札の色: 緑＝みきさんが直した、黄＝ダンが直した、青＝元の文のまま、灰＝プログラムの中（読むだけ）。
- 全文の欄、「なぜ直したか」の欄、保存・元に戻す、この画面での履歴（押すとその版、この版に戻す）、プログラムの中にあった頃に直された日。
- スマホの幅では、一覧と全文が入れ替わり（「一覧に戻る」）。

## 行き方（みきさんから見て）

ダンの画面の /prompts。URL の ?place=<場所>&id=<文> で、その場所・その文を開いたまま共有できます。

## 道具で動かす

`place_shot.py prompts --base http://localhost:3002 --path '/prompts?place=router&id=call/router-routes' --tag now`。
直す試験は、試しのサーバーを `DAN_PROMPTS_DIR=<一時の場所> work.py try` で立てて行います。

## 落とし穴

- 文の置き場所は ~/.dan/workspace/prompts。本番で保存すると、次の通話・次の作業から本当に効きます。
