---
place: chat
name: ダンのチャット（PC のダン本体とスマホのアプリ）
open: /chat
ready: 'textarea'
reach: PC は dan.paina.info の部屋の一覧から部屋を選ぶ。スマホはダンのアプリ（mobile の地図）
speak: |
  - この部屋は、PC のダン本体（左に部屋の一覧、真ん中に会話）とスマホのアプリの両方に出る。どちらで読んでいるかは前置きの「端末」の行で判断し、分からない時は両方で読める形で書く。
  - PC の吹き出しは Markdown（番号・点の並び、表、見出し、太字、コード、画像）と ```openui-lang の部品を描く。スマホのアプリは表と見出しとコードと部品を描くが、番号と点の並びは「1.」「-」の文字のまま出る。
  - 作業中は、progress で書いた数行と道具の行がたたまれて出る。返事の本文に作業の経過を書かない。
probe: {classes: "prose prose-base prose-dan max-w-none"}
shows: [番号の並び, 点の並び, 表, 見出し, 太字, コード]
watches:
  - frontend/src/components/layout/project-chat-panel.tsx
  - frontend/src/components/chat/chat-shapes.tsx
  - frontend/src/lib/chat-shapes/*.ts
  - frontend/src/app/globals.css
fingerprint: f6a33d5e07869a15
described: 66ccf8065a51442d
last_review: "2026-10-26 説明は変えない: globals.css の追加は通話の画面係（[data-stage-scene]）だけで、チャットの吹き出しの見え方は変わらない"
---
# ダンのチャット

ふだんの部屋。みきさんがダンに頼み事をし、ダンが返事と作業の様子を返す。部屋に成果物があれば、右に成果物タブが出る（artifact-tab の地図）。

## 中にある物

- `room-list` 左の部屋の一覧。司令塔（Done）を開いた時は前の部屋の選択表示を消す。作業中の部屋には印が出る。開発室の枝の部屋のような隠れた部屋は出ない。
- `chat-bubble` 会話。ダンの返事は Markdown と部品（表・選択ボタン・数字・流れの図など）、添付の印（[添付画像: …] [添付動画: …] [添付ファイル: …]）を描く。
- `live-rows` 作業中に、ダンが progress で書いた数行と、道具の説明の行が出る。GPTも作業の対象・目的と確認した結果を伝える。説明がない操作でも、ファイル確認・編集・テスト・ビルドなど実際の操作を表示する。終わるとたたまれる。
- `summon-banner` ダンが本人を今すぐ呼んでいる間（振込の承認・認証コードなど。summon の道具）、どのページでも画面の上に琥珀色の帯で理由が出て、3秒ごとに音が鳴る。押すとその部屋が開き、呼び出しが止まる。
- `model-switcher` 選択したモデルで実行する。利用上限時はClaudeとGPTの間で作業記録を引き継いで切り替え、切替中の表示を出す。両方が上限の場合は停止理由を表示する。
- `chat-input` 下の欄。送ると、作業中でも追い連絡として届く。
- `artifact-tab` 部屋に成果物があれば右に出る（artifact-tab の地図）。

## 行き方（みきさんから見て）

- PC: dan.paina.info を開き、左の部屋の一覧で部屋を選ぶ。道は `/chat/<project の id>`。
- スマホ: ダンのアプリを開き、部屋の一覧で選ぶ。

## 道具で動かす

前提:

- チャット画面は持ち主のアカウントだけが開ける（`frontend/src/lib/api-client.ts` の `OWNER_USER_ID`）。テスト用アカウントでは /collab に移される。

- **吹き出しの見え方。** 下の手順で開いた画面のサーバーを渡して `python scripts/place_shot.py chat --tag after --base http://127.0.0.1:3002`。着いたか・本物の画面・吹き出しと同じクラス（prose）の見本の3つを測る。差し替えずに開くと /collab に移されて「着いたか」が NG になる。
- **本物の会話の画面。** 記憶の project-chat-ui-test-with-test-account の手順（作業場所の 3002 で `OWNER_USER_ID` だけテスト用に差し替える）で開き、テスト用アカウントの部屋で確かめる。差し替えはコミットしない。

## 落とし穴

- 本番の画面（3000）は作った時点の写し。作業場所のファイルを直しても映らない。
- `prose` の見た目は Tailwind の typography が決める。`globals.css` の `prose-dan` を変えると、全部の部屋の吹き出しが変わる。
- 部品の描き方を変えた時は、スマホのアプリの写し（mobile/chat-shapes*）も同じに保つ（tests/chat_shapes_plain.test.mjs）。

<!-- place_map:auto:start -->
## コードから（自動）

`python scripts/place_map.py stamp chat` が書き直す。手で直さない。

- 見張るファイル: `frontend/src/app/globals.css`, `frontend/src/components/chat/chat-shapes.tsx`, `frontend/src/components/layout/project-chat-panel.tsx`, `frontend/src/lib/chat-shapes/answer-sends.ts`, `frontend/src/lib/chat-shapes/answers.ts`, `frontend/src/lib/chat-shapes/chart-geometry.ts`, `frontend/src/lib/chat-shapes/job-report.ts`, `frontend/src/lib/chat-shapes/live-line.ts`, `frontend/src/lib/chat-shapes/no-openui-devtools.ts`, `frontend/src/lib/chat-shapes/plain.ts`, `frontend/src/lib/chat-shapes/schema.ts`, `frontend/src/lib/chat-shapes/split.ts`, `frontend/src/lib/chat-shapes/use-answer-send.ts`
- ラベル: 「部品を準備中」、「このコメントを外す」、「タイムライン参照を外す」

<!-- place_map:files {"frontend/src/app/globals.css": "18079a7ca6", "frontend/src/components/chat/chat-shapes.tsx": "dbfb90dc36", "frontend/src/components/layout/project-chat-panel.tsx": "d85e4e440d", "frontend/src/lib/chat-shapes/answer-sends.ts": "4ca1a9be51", "frontend/src/lib/chat-shapes/answers.ts": "be1dd2effa", "frontend/src/lib/chat-shapes/chart-geometry.ts": "87ea9350f3", "frontend/src/lib/chat-shapes/job-report.ts": "9a154596f2", "frontend/src/lib/chat-shapes/live-line.ts": "a2cb48aa00", "frontend/src/lib/chat-shapes/no-openui-devtools.ts": "33b9df7e21", "frontend/src/lib/chat-shapes/plain.ts": "c93fc29f64", "frontend/src/lib/chat-shapes/schema.ts": "d5afefe4b8", "frontend/src/lib/chat-shapes/split.ts": "c2502ef5b0", "frontend/src/lib/chat-shapes/use-answer-send.ts": "ac6f99f5f5"} -->
<!-- place_map:auto:end -->
