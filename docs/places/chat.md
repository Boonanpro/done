---
place: chat
name: ダンのチャット（PC のダン本体とスマホのアプリ）
open: /chat
reach: PC は dan.paina.info の部屋の一覧から部屋を選ぶ。スマホはダンのアプリ（mobile の地図）
speak: |
  - みきさんはこの部屋を、PC のダン本体の画面（左に部屋の一覧、真ん中に会話）か、スマホのアプリで読んでいる。どちらで読んでいるかは分からないので、両方で読める形で書く。
  - PC の吹き出しは Markdown（番号・点の並び、表、見出し、太字、コード、画像）と ```openui-lang の部品を描く。スマホのアプリは表と見出しとコードを描くが、並びは「1.」「-」の文字のまま出る。
  - 作業中は、progress で書いた数行と道具の行がたたまれて出る。返事の本文に作業の経過を書かない。
probe: {classes: "prose prose-base prose-dan max-w-none"}
shows: [番号の並び, 点の並び, 表, 見出し, 太字, コード]
---
# ダンのチャット

ふだんの部屋。みきさんがダンに頼み事をし、ダンが返事と作業の様子を返す。部屋に成果物があれば、右に成果物タブが出る（artifact-tab の地図）。

## 中にある物

- `room-list` 左の部屋の一覧。作業中の部屋には印が出る。開発室の枝の部屋のような隠れた部屋は出ない。
- `chat-bubble` 会話。ダンの返事は Markdown と部品（表・選択ボタン・数字・流れの図など）、添付の印（[添付画像: …] [添付動画: …] [添付ファイル: …]）を描く。
- `live-rows` 作業中に、ダンが progress で書いた数行と、道具の説明の行が出る。終わるとたたまれる。
- `chat-input` 下の欄。送ると、作業中でも追い連絡として届く。
- `artifact-tab` 部屋に成果物があれば右に出る（artifact-tab の地図）。

## 行き方（みきさんから見て）

- PC: dan.paina.info を開き、左の部屋の一覧で部屋を選ぶ。道は `/chat/<project の id>`。
- スマホ: ダンのアプリを開き、部屋の一覧で選ぶ。

## 道具で動かす

前提:

- チャット画面は持ち主のアカウントだけが開ける（`frontend/src/lib/api-client.ts` の `OWNER_USER_ID`）。テスト用アカウントでは /collab に移される。

- **吹き出しの見え方。** `python scripts/place_shot.py chat --tag after --base http://127.0.0.1:3002`。画面全体は /collab に移っても、吹き出しと同じクラス（prose）の見本を入れて、番号・点・表・見出し・太字・コードが見えるかを測れる。
- **本物の会話の画面。** 記憶の project-chat-ui-test-with-test-account の手順（作業場所の 3002 で `OWNER_USER_ID` だけテスト用に差し替える）で開き、テスト用アカウントの部屋で確かめる。差し替えはコミットしない。

## 落とし穴

- 本番の画面（3000）は作った時点の写し。作業場所のファイルを直しても映らない。
- `prose` の見た目は Tailwind の typography が決める。`globals.css` の `prose-dan` を変えると、全部の部屋の吹き出しが変わる。
- 部品の描き方を変えた時は、スマホのアプリの写し（mobile/chat-shapes*）も同じに保つ（tests/chat_shapes_plain.test.mjs）。
