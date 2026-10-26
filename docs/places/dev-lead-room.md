---
place: dev-lead-room
name: 開発室のボードの話し合い（枝・付箋ごとの部屋）
open: /preview/dev-lead
ready: '[class*="_canvas__"]'
covers: [artifact:dev-lead]
speak: |
  - PC では、ダン本体の「ダン開発室」の部屋の右の成果物タブにボード（枝と付箋の地図）が出て、その左側の一覧でこの話し合いを選んで読む。スマホではボードの公開版の写しを開いて読む。同じボードの上に、ほかの枝の話し合いと付箋の状態も見えている。
  - 返事の吹き出しは Markdown（番号・点の並び、表、太字、コード）と ```openui-lang の部品、[添付画像: …] などの印を描く。見出しは本文と同じ大きさの太字にしかならない。
  - 付箋はボードに出ている札の言葉（例「場所の地図と自分で確かめる」）で呼ぶ。全体の部屋（「ダン開発室」）は別の会話で、ここに書いたことはそちらには出ない。
probe: {module: style, scope: app, bubble: md, real: '[class*="_md__"]'}
shows: [番号の並び, 点の並び, 表, 見出し, 太字, コード]
watches:
  - frontend/src/app/artifacts/dev-lead/page-body.tsx
  - frontend/src/app/artifacts/dev-lead/style.module.css
  - frontend/src/app/artifacts/dev-lead/model.ts
fingerprint: a455832e844e0868
described: b51f0ab40acda937
---
# 開発室のボードの話し合い

ボードの枝や付箋ごとに1つずつある部屋。みきさんは付箋の中身を読みながら、その付箋の担当のダンと話し、GO・見送り・本番に入れるをボタンかチャットで返す。

## 中にある物

- `talk-list` ボードの左の「話し合い」の一覧。いちばん上が全体の部屋、その下に枝と付箋ごとの部屋。最後の発言の主（あなたの番・ダンの番）と作業中の印。
- `talk-bubble` 選んだ部屋の会話。ダンの返事は Markdown・部品・添付の印を描く。作業中は、ダンが progress で書いた数行が出る。
- `talk-input` 下の欄。`/model` だけ使える。それ以外の `/` で始まる文はそのまま届く。
- `note-actions` 付箋の GO・見送り・意見・本番に入れる・やめる。押すとこの部屋にみきさんの発言として「GO: …」などが届く。

## 行き方（みきさんから見て）

- PC: ダン本体（dan.paina.info）の部屋の一覧で「ダン開発室」→ 右の成果物タブにボード → 左の「話し合い」で枝か付箋を選ぶ。幅 1300 以上では最初から開いている。
- ボードの枝や付箋を押して横に出る詳細の「この枝の話し合い」「この提案の話し合い」からも入れる。
- 道: `/preview/dev-lead`（成果物タブの中身そのもの）。

## 道具で動かす

前提:

- 成果物の開発サーバー（3001）か、作業場所で立てた画面のサーバーが動いている。
- ボードの中身は持ち主のアカウントだけが読める保存先から来るので、テスト用アカウントで開くとボードと話し合いは空。吹き出しの見た目は、見本を同じ入れ物に入れて測る。

- **吹き出しの見え方。** `python scripts/place_shot.py dev-lead-room --tag after`。見本の吹き出しに番号（1. 2. 3.）、点、枠のある表、太字の見出し、背景の付いたコードが出て、終わりの行が `result=OK`。
- **前と後。** 直す前に `--tag before`、直した後に `--tag after`。`.data/place_shots/dev-lead-room/compare.png` に前と後が並ぶ。
- **本人の画面。** 成果物のファイルを直した後は `python scripts/artifact_seen.py --slug dev-lead --wait 90` で、みきさんの開いている画面が今の版かを見る。

## 落とし穴

- 画面全体に `.app :where(ul,ol){list-style:none}` があり、吹き出しの `.md` の中で並びの印を戻さないと、番号と点が消えて余白だけ残る（2026-10-25 に起きた）。
- 話し合いの部屋はダンの部屋の一覧に出ない隠れた部屋（projects.metadata.hidden）。元の部屋（origin_room_id）がダン開発室。
- スマホのアプリは成果物の公開版の写しでボードを開くので、写しの作り直し（数分）が終わるまで古い見た目のまま。

<!-- place_map:auto:start -->
## コードから（自動）

`python scripts/place_map.py stamp dev-lead-room` が書き直す。手で直さない。

- 見張るファイル: `frontend/src/app/artifacts/dev-lead/model.ts`, `frontend/src/app/artifacts/dev-lead/page-body.tsx`, `frontend/src/app/artifacts/dev-lead/style.module.css`
- ラベル: 「この話に書く」、「止める（Esc）」、「送る」、「処理の流れ」、「送っています」、「見本あり」、「枝の言葉」、「この枝を消す」、「足す枝の言葉」、「何もない所に置く箱の言葉」、「大きな枝を足す」、「モデル」、「ダンの性能目標とプロジェクトの目標を開く」、「性能目標とプロジェクトの目標を直す」、「目標を畳む」、「言葉を直す」、「小さくする」、「大きくする」、「パネルの幅を変える」、「閉じる」
- ボタンの字: 「保存」、「並びを元に戻す」
- 見出し: 「ダンに入ったもの」、「何が、どこから変わったか」

<!-- place_map:files {"frontend/src/app/artifacts/dev-lead/model.ts": "4510b48416", "frontend/src/app/artifacts/dev-lead/page-body.tsx": "74f3fa381f", "frontend/src/app/artifacts/dev-lead/style.module.css": "34252829fd"} -->
<!-- place_map:auto:end -->
