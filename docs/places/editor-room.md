---
place: editor-room
name: エディターの中の「ダンと制作」（制作ライブラリの真ん中と、作品の画面の右の欄）
reach: 本体の部屋の上の「制作」を押すと別の窓でエディターが開く。ライブラリの真ん中の大きな会話、作品を開いた時は右の「ダンと制作」の欄がこの部屋
open: /production-workspace?room_id=editor-compare-nakamura-v13
ready: 'aside[aria-label="作品と素材"]'
speak: |
  - この部屋は動画エディター（別の窓）に出る。ライブラリでは窓の真ん中いっぱいの会話で、左に作品の一覧と素材のフォルダ（動画・画像・音声・AIで作った素材）だけがある。作品を開くと、タイムラインとプレビューの右の欄（約420px）になる。みきさんは文字か音声で話し、画像や動画はここに貼る。ライブラリには素材を足す欄も「AIで作る」欄も無いので、素材集めも作品を作り始めるのも、この会話で頼まれてダンがやる。
  - みきさんは素材を自分でドラッグしない。最初は「どんな動画を作りたいか」から始まる。AIの動画・画像生成は手段の1つで、使う場面になったらどのモデルで何を作るかをダンが決めて提案する。作品の画面では、みきさんがタイムラインの「+ クリップ」で足したクリップに指示とモデルを入れて自分でAIで作ることもある。素材集め（NAS・本体の部屋の話・生成）と並べるのはダンの仕事。素材を足した・タイムラインを直したら、左の画面がその場で変わる。何をどこに置いたかだけ短く言う。素材の登録・新しい作品・一覧は `python scripts/production_library.py list|register|new-content --room <この部屋>`、タイムラインは作品の部屋で mcp__timeline__*。
  - 作品の画面の欄は狭い（約420px）。返事は短く、表は列を少なく。吹き出しは Markdown と ```openui-lang の部品を描く。
  - 本体の部屋とは別の会話だが、ダンは一人。本体の部屋の話は下の room_id を lookup で読み、こちらの決まったことや進みは本体の部屋のダンからも読まれる。
probe: {classes: "prose prose-base prose-dan max-w-none"}
shows: [番号の並び, 点の並び, 表, 見出し, 太字, コード]
watches:
  - frontend/src/components/production/production-workspace.tsx
  - frontend/src/components/production/editor-dan-chat.tsx
  - frontend/src/app/production-workspace/page.tsx
fingerprint: 44c1e064eb0ffd01
described: dd82e4265deb7e94
---
# エディターの中の「ダンと制作」

動画を作る時にダンと話す場所。本体のチャットから動画の話を分け、エディターの画面を見ながら話す。

## 中にある物

- `library-chat` 制作ライブラリの真ん中の大きな会話（左に作品の一覧と素材のフォルダ）。ライブラリに1つの部屋。どんな動画を作るかの相談・素材集め・新しい作品。
- `content-chat` 作品を開いた画面（タイムラインとプレビュー）の右の欄。作品ごとに1つの部屋。この部屋のダンはその作品のタイムラインの道具（mcp__timeline__*）を持ち、再生位置と選んだクリップが「ここ」「これ」になる。
- `toggle` 上の「ダンと制作」のボタンで欄を開け閉めする。
- `voice` 欄の上の「音声」で、この部屋の文脈のまま声で話せる。

## 行き方（みきさんから見て）

本体の部屋の上の「制作」を押す → すぐ「ダン 制作」の起動画面の窓が開き、続けて制作ライブラリが出る。左の作品を押すとタイムラインの画面になり、右の欄がその作品の部屋になる。素材のフォルダの中の絵を押すと、その素材が大きく開く。

## 道具で動かす

- 前提: 本体の部屋に素材（uploads/production-assets/<本体の部屋>）がある
- 作品の部屋で「ここの字幕消して」→ timeline の道具で直す → 左のタイムラインがその場で変わり、ダンの手（青い光と矢印）が見える

<!-- place_map:auto:start -->
## コードから（自動）

`python scripts/place_map.py stamp editor-room` が書き直す。手で直さない。

- 見張るファイル: `frontend/src/app/production-workspace/page.tsx`, `frontend/src/components/production/editor-dan-chat.tsx`, `frontend/src/components/production/production-workspace.tsx`
- ラベル: 「ダンと制作」、「作品と素材」、「作品」、「素材のフォルダ」

<!-- place_map:files {"frontend/src/app/production-workspace/page.tsx": "e65a8f6c81", "frontend/src/components/production/editor-dan-chat.tsx": "7afab6a25a", "frontend/src/components/production/production-workspace.tsx": "b79cf0990d"} -->
<!-- place_map:auto:end -->
