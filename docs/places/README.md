# 場所の地図

ダンが話す場所と、ダンが作った成果物の画面ごとに、みきさんの画面に何が見えていて、どう開き、何が表示できないかを書いた地図。
2026-10-25 にローレン・タンさんの講演（機能の地図）と pstack の create-verification-skill / maintain-verification-skill から作った。
この日、開発室のボードの話し合いで返事の①〜⑤の番号が消えていたのに、ダンは自分の返事の見え方を一度も見ておらず、みきさんに言われるまで気づけなかった。

## 2つの使い道

- **話すダン**: 部屋ごとに、どの場所に出ているかを見分け（`app/agent/place_map.py` の `identify_place`）、その場所の前書きの `speak` を前置き `<place>` に入れる。どの端末から最後に書いたか（チャットの受け口が `.tmp/room-clients.json` に残す）と、みきさんの画面が今どの成果物を出しているか（成果物の画面が数秒ごとに知らせる `.tmp/live-views.json`）も入れ、分からない時は「分からない」と書く。確かめ方: `python scripts/place_map.py speak --room <部屋のid>`。会話の長い部屋で新しく始める時も、前置きの先頭に残る。
- **直すダン**: `python scripts/place_shot.py <場所> --tag before|after` が、前書きの `open` で画面をテスト用アカウントで開いて撮り、3つを測る。1つでも NG なら全体が NG。
  1. 着いたか: 開いた道のままか（/login・/collab に移されていないか）、`ready` の部品が見えるか
  2. 本物の画面: エラーの文（`errors` と決まった文）や Next のエラーの画面が出ていないか、白紙でないか、`probe.real` の本物の入れ物が透けたり隠れたりしていないか
  3. 見本: `shows` の物（番号の並び・表など）の見本を `probe` の入れ物に入れ、印・罫線・太さがあり、透けていないか

## 置き場所

- 共通の場所: このフォルダの `<id>.md`。今あるのは [chat](chat.md)・[artifact-tab](artifact-tab.md)・[dev-lead-room](dev-lead-room.md)・[mobile](mobile.md)。前書きの `watches` に、その場所を描くファイルを書く。
- 成果物: `frontend/src/app/artifacts/<slug>/MAP.md`。成果物と一緒に done-artifacts に残る。新しい成果物を作る時に一緒に作る: `python scripts/place_map.py draft <slug> "名前"` でコードから下書きを作り、「（ここを書く）」を埋めて `stamp`。

## 画面を直す時の順番（関所が見る）

同じ木（動いているダンか作業場所）で:

1. 最初の書き換えの前に `python scripts/place_shot.py <場所> --tag before`
2. 画面のファイルを直す（成果物の `_server`・`MAP.md`・`PRODUCT.md` 以外、または共通の場所の `watches` のファイル）
3. 変わった所の地図の説明を直して `python scripts/place_map.py stamp <場所>`。画面が変わったのに説明が1字も変わっていなければ断られる。説明を変えなくてよい直し（見た目の崩れを直しただけ等）は `--unchanged "理由"` で、理由が地図の `last_review` に残る
4. `python scripts/place_shot.py <場所> --tag after`（作業場所の画面のサーバーは `--base`）。NG なら直して撮り直す

`scripts/hook_artifact_verify_gate.py`（Stop）が、このターンの書き換えごとに、書き換えの前の before・最後の書き換えの後の after（OK）・いちばん新しい地図の状態が FRESH、の3つを見る。撮った結果は `covers` に書いた場所にも数える（dev-lead-room を撮れば開発室のボードの分にもなる）。直す前を撮っていなかった時は、後からは撮れないので1回だけ止める。動いているダンの成果物なら、あわせて本人の画面の確認（`artifact_seen.py`）も要る。確かめた結果は本人への返事に書かない。

## 1枚の形

先頭は YAML の前書き、本文はローレンさんの地図と同じ4つの節。

```
---
place: artifact:<slug>         # 共通の場所は id（chat など）
name: 画面の名前（みきさんが呼ぶ名前）
open: /preview/<slug>          # ブラウザで開く道。開けない場所は書かず、reach に行き方
ready: '[aria-label="…"]'      # 開けたと分かる、本物の画面の部品（CSS）。殻やエラーの画面には無い物を選ぶ
                               # CSS モジュールの名前は、成果物の画面のサーバー（3001）では style-module__<印>__canvas、
                               # 作業場所の webpack では style_canvas__<印>。両方に当たるよう '[class*="_canvas__"], [class$="__canvas"]' と書く
covers: [dev-lead-room]        # 同じ画面を撮る別の場所（撮った結果をそちらにも数える）
errors: ["…"]                  # この画面のエラーの文（決まった文に足す）
watches: [frontend/…/*.tsx]    # 共通の場所だけ。その場所を描くファイル
ready: '[data-x]'              # 開けたと分かる CSS の印（省略時 body）
speak: |                       # 話すダンに渡す2〜5行。みきさんに何が見えていて、何が出せないか
  - …
probe: {module: style, scope: app, bubble: md, real: '[class*="_md__"]'}   # 吹き出しの入れ物。CSS モジュールの名前か {classes: "…"}。real は本物の入れ物
shows: [番号の並び, 点の並び, 表, 見出し, 太字, コード]   # その入れ物で見えるはずの物
fingerprint: …                 # stamp が書く（画面のファイルの指紋）
described: …                   # stamp が書く（説明の指紋）
---
# 名前

1段落: みきさんがこの画面でできること。

## 中にある物          … 機能を短い id と1行で
## 行き方（みきさんから見て）  … みきさんがどこを押してここに来るか
## 道具で動かす        … 前提と、「みきさんの操作 → 道具の命令 → 見えるはずの結果」の組
## 落とし穴            … 確かめを無駄にする・誤らせる罠

<!-- place_map:auto:start -->
## コードから（自動）    … stamp がページ・ラベル・ボタンの字を書き出す。手で直さない
<!-- place_map:auto:end -->
```

書き方の決まり（pstack から）:

- みきさんから見た言葉で書く。実装の中身（関数名・ファイルの行）は「道具で動かす」の命令と「落とし穴」にだけ。
- 押す物は、ラベル・見出し・ボタンの字・道（URL）で指す。座標や並び順で指さない。
- 「見えるはずの結果」は、目で見て分かる物で書く。保存した・送ったなら、別の画面で読み直して確かめる。
- 確かめに要る状態が無くて行けない所は、通ったことにせず、何が足りなかったかを「落とし穴」に書く。

## 地図の手入れ

画面を直した時のほか、まとめて手入れする時は pstack の maintain-verification-skill の手順に従う: 地図ごとにコードを読んで地図と食い違う所を探し、全部の場所を実際に `place_shot.py` で開き、地図の直しだけを1回にまとめる。画面そのものが壊れていたら地図で隠さず、壊れていると報告する。
