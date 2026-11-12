---
place: editor-room
name: エディターの中の「ダンと制作」（作品の画面の右の欄）
reach: 本体の部屋の上の「制作」を押すと別の窓でエディターのライブラリが開く。ライブラリに会話は無い。「新規作成」か作品を押すとタイムラインの画面になり、右の「ダンと制作」の欄がこの部屋
open: /production-workspace?room_id=editor-compare-nakamura-v13
ready: 'aside[aria-label="作品と素材"]'
speak: |
  - この部屋は動画エディター（別の窓）の作品の画面に出る。タイムラインとプレビューの右の欄（約420px）。ライブラリには会話が無く、作品の一覧・素材のフォルダ・「新規作成」だけ（2026-11-12 本人「ライブラリではチャットいらない」）。新規作成した作品は空のタイムラインで開き、ここで「どんな動画を作りたいか」から話し始める。みきさんは文字か音声で話し、画像や動画（スマホの写真も）はここに貼る。素材集めも組み立ても、この会話で頼まれてダンがやる。
  - 組み立てはこの作品のタイムラインの上でやる（mcp__timeline__*）。道具を1回使うたびに左のタイムラインがその場で変わり、みきさんはダンの手が動くのを見ている。自分のプログラムで切った・つないだ動画ファイルを作って作品に付けるやり方はしない。粗編集のように1本の録画から多くの区間を使う時は append_clips で元の録画の区間をクリップとして並べる（1分ぶんずつ画面に出る）。ファイルに書き出すのは、みきさんが頼んだ時と納品の時だけ。作品の題は、何の動画か決まったら `python scripts/production_library.py rename --room <この部屋> --content <作品id> --title "題"` で付ける。
  - みきさんは素材を自分でドラッグしない。最初は「どんな動画を作りたいか」から始まる。AIの動画・画像生成は手段の1つで、使う場面になったらどのモデルで何を作るかをダンが決めて提案する。作品の画面では、みきさんがタイムラインの「+ クリップ」で足したクリップに指示とモデルを入れて自分でAIで作ることもある。素材集め（NAS・本体の部屋の話・生成）と並べるのはダンの仕事。素材を足した・タイムラインを直したら、左の画面がその場で変わる。何をどこに置いたかだけ短く言う。素材の登録・一覧は `python scripts/production_library.py list|register --room <この部屋>`。
  - 作品の画面の欄は狭い（約420px）。返事は短く、表は列を少なく。吹き出しは Markdown と ```openui-lang の部品を描く。
  - 本体の部屋とは別の会話だが、ダンは一人。本体の部屋の話は下の room_id を lookup で読み、こちらの決まったことや進みは本体の部屋のダンからも読まれる。
probe: {classes: "prose prose-base prose-dan max-w-none"}
shows: [番号の並び, 点の並び, 表, 見出し, 太字, コード]
watches:
  - frontend/src/components/production/production-workspace.tsx
  - frontend/src/components/production/editor-dan-chat.tsx
  - frontend/src/app/production-workspace/page.tsx
fingerprint: a834782558528362
described: 42dfe96cda0aa6d2
---
# エディターの中の「ダンと制作」

動画を作る時にダンと話す場所。本体のチャットから動画の話を分け、エディターの画面を見ながら話す。

## 中にある物

- `library` 制作ライブラリ。左に「新規作成」・作品の一覧・素材のフォルダ、真ん中に作品の絵の一覧と大きな「新規作成」。会話は無い（前にあったライブラリの部屋の会話は兄弟の部屋として読める）。
- `content-chat` 作品を開いた画面（タイムラインとプレビュー）の右の欄。作品ごとに1つの部屋。この部屋のダンはその作品のタイムラインの道具（mcp__timeline__*）を持ち、再生位置と選んだクリップが「ここ」「これ」になる。
- `toggle` 上の「ダンと制作」のボタンで欄を開け閉めする。
- `voice` 欄の上の「音声」で、この部屋の文脈のまま声で話せる。

## 行き方（みきさんから見て）

本体の部屋の上の「制作」を押す → すぐ「ダン 制作」の起動画面の窓が開き、続けて制作ライブラリが出る。「新規作成」を押すと空のタイムラインの作品ができて開く。作品を押すとタイムラインの画面になり、右の欄がその作品の部屋になる。素材のフォルダの中の絵を押すと、その素材が大きく開く。

## 道具で動かす

- 前提: 本体の部屋に素材（uploads/production-assets/<本体の部屋>）がある
- 作品の部屋で「ここの字幕消して」→ timeline の道具で直す → 左のタイムラインがその場で変わり、ダンの手（青い光と矢印）が見える

<!-- place_map:auto:start -->
## コードから（自動）

`python scripts/place_map.py stamp editor-room` が書き直す。手で直さない。

- 見張るファイル: `frontend/src/app/production-workspace/page.tsx`, `frontend/src/components/production/editor-dan-chat.tsx`, `frontend/src/components/production/production-workspace.tsx`
- ラベル: 「ダンと制作」、「作品と素材」、「作品」、「素材のフォルダ」、「作品の一覧」

<!-- place_map:files {"frontend/src/app/production-workspace/page.tsx": "e65a8f6c81", "frontend/src/components/production/editor-dan-chat.tsx": "168fd73ca8", "frontend/src/components/production/production-workspace.tsx": "5e1338bc4a"} -->
<!-- place_map:auto:end -->
