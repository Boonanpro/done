---
place: mobile
name: スマホのダンのアプリ（Galaxy）
reach: Mac mini に USB でつないだ開発用の Galaxy S24 を phone の道具で開く（ブラウザでは開けない）
speak: |
  - スマホのアプリは PC と同じ部屋と会話を読むが、描き方が違う。表・見出し・コード・太字と ```openui-lang の部品は描くが、番号と点の並びは「1.」「-」の文字のまま出る。
  - 画像・動画は [添付画像: …] などの印から出る。PC の成果物タブは無く、成果物は公開版の写しをブラウザで開く。
---
# スマホのダンのアプリ

みきさんが外でダンと話す画面。部屋の一覧、会話、通話、成果物を開くボタンがある。

## 中にある物

- `rooms` 部屋の一覧。
- `chat` 会話。本文は `mobile/chat-markdown.tsx` が段落・見出し・表・コードに分けて描き、文中の太字・コード・斜体は `renderInlineMarkdown`（mobile/App.tsx）が描く。部品は `mobile/chat-shapes.tsx`、描けない部品は読める文章にする。
- `live-rows` 作業中の数行（mobile/chatTimeline.ts）。
- `voice` 通話。
- `open-artifact` 成果物を、使い捨ての入館証を付けて公開版の写しで開く（/enter）。

## 行き方（みきさんから見て）

- ホーム画面のダンのアプリを開く → 部屋を選ぶ。

## 道具で動かす

前提:

- 開発用の Galaxy S24 が Mac mini に USB でつながり、ロックが外れている（記憶の project-galaxy-s24-dev-phone-20261024）。本人のスマホは使わない。

- **会話の見え方。** `phone` の道具で `open`（アプリの package）→ 部屋を選ぶ → `read` で部品の一覧、見た目は `screenshot`。
- **ブラウザの道具では開けない。** `place_shot.py mobile` は UNREACHABLE を返す。

## 落とし穴

- アプリの画面を直したら、アプリを作り直して入れ直すまで変わらない（版が上がる。記憶の reference-mac-android-build）。
- PC で直した描き方（chat-shapes）は、アプリの写し（mobile/chat-shapes*）にも写す。
