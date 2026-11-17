---
place: prompts
name: ダンを動かしている指示文
open: /prompts
ready: 'textarea, button:has(img[src^="/prompts/arch/"])'
watches: [frontend/src/app/prompts/page.tsx, frontend/src/components/prompts/prompts-screen.tsx, frontend/src/components/prompts/architecture.ts, frontend/src/lib/prompts-api.ts, app/api/prompts_screen.py, app/services/prompt_store.py, app/prompts/catalog.json]
errors: [ログインが切れています, 失敗しました]
speak: |
  - ダンの各係が読む指示文を、みきさんが読んで直し、前の版に戻す画面です。
  - 試す時は DAN_PROMPTS_DIR を一時の場所にして、本物の指示文を書き換えません。
shows: []
---
# ダンを動かしている指示文

上に、みきさんの頼みが流れる順の構成図（上から下：みきさん→画面のサーバー→入口→会話の本体／道具と通話のサーバー→チャットのダン・通話のダン・エディター→振り分け→調べもの係・画面係・判断役→作業の部屋）。箱には何の場所かの小さな絵、中で動くモデル、読む指示文の数。箱を押すとその箱が読む指示文の一覧、押すと全文がそのまま出て、その場で書き直して保存できる。誰が読むか・いつ効くか・なぜある文か・元の場所・履歴は全文の下にたたんである。
開発室のボード（artifact:dev-lead）の上の切り替え「部屋／地図／指示文」の「指示文」でも同じ画面が出る（2026-11-17 本人「開発室の中に1要素として」）。

## 中にある物

- 構成図（components/prompts/architecture.ts。箱と矢印はコードで確かめた呼び出し順で、根拠のファイルは同じファイルの頭に書いてある。仕組みを変えたらここも直す）。スマホの幅では図が横に広く、押した箱の所まで横に送る。
- 場所ごとの一覧。札の色: 緑＝みきさんが直した、黄＝ダンが直した、青＝元の文のまま、灰＝プログラムの中（読むだけ）。
- 全文の欄（「この文は、ここでそのまま書き直せます」。欄は中身の高さまで伸びる）、下に貼り付いた保存の帯（書き直すと「なぜ直したか」・直す前に戻す・保存が出る）、たたんだ「この文について」と「履歴」（押すとその版、この版に戻す・プログラムの中にあった頃に直された日）。
- スマホの幅では、一覧と全文が入れ替わり（「一覧に戻る」）。

## 行き方（みきさんから見て）

ダンの画面の /prompts。URL の ?place=<場所>&id=<文> で、その場所・その文を開いたまま共有できます。

## 道具で動かす

`place_shot.py prompts --base http://localhost:3002 --path '/prompts?place=router&id=call/router-routes' --tag now`。
直す試験は、試しのサーバーを `DAN_PROMPTS_DIR=<一時の場所> work.py try` で立てて行います。

## 落とし穴

- ダンの画面は html と body のスクロールを止めている。この画面は自分の枠（h-dvh・overflow-y-auto）でスクロールする。外すと全文の欄まで下りられなくなる（11/17 の「見るだけで編集できない」の原因）。
- 開発室の中では、開発室の初期化（余白を0にする等）を .promptsPane で外している。

- 文の置き場所は ~/.dan/workspace/prompts。本番で保存すると、次の通話・次の作業から本当に効きます。
