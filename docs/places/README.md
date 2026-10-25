# 場所の地図

ダンが話す場所と、ダンが作った成果物の画面ごとに、みきさんの画面に何が見えていて、どう開き、何が表示できないかを書いた地図。
2026-10-25 にローレン・タンさんの講演（機能の地図）と pstack の create-verification-skill / maintain-verification-skill から作った。
この日、開発室のボードの話し合いで返事の①〜⑤の番号が消えていたのに、ダンは自分の返事の見え方を一度も見ておらず、みきさんに言われるまで気づけなかった。

## 2つの使い道

- **話すダン**: 部屋ごとに、どの場所に出ているかを見分け（`app/agent/place_map.py` の `identify_place`）、その場所の前書きの `speak` を前置き `<place>` に入れる。成果物タブなら、右の成果物の地図の `speak` も入れる。確かめ方: `python scripts/place_map.py speak --room <部屋のid>`。
- **直すダン**: `python scripts/place_shot.py <場所> --tag before|after` が、前書きの `open` で画面をテスト用アカウントで開いて撮り、`shows` に書いた物（番号の並び・表など）の見本を `probe` の入れ物に入れて、本当に見えるかを測る。見えなければ NG。

## 置き場所

- 共通の場所: このフォルダの `<id>.md`。今あるのは [chat](chat.md)・[artifact-tab](artifact-tab.md)・[dev-lead-room](dev-lead-room.md)・[mobile](mobile.md)。
- 成果物: `frontend/src/app/artifacts/<slug>/MAP.md`。成果物と一緒に done-artifacts に残る。
  - 新しい成果物を作る時に一緒に作る: `python scripts/place_map.py draft <slug> "名前"` でコードから下書きを作り、「（ここを書く）」を埋めて `stamp`。
  - 前書きの `fingerprint` は画面のファイル（`_server` と MAP.md を除く .tsx/.ts/.css など）から作った指紋。画面を書き換えると合わなくなる。
  - 成果物の画面を書き換えたターンは、終わる前に地図を直して `python scripts/place_map.py stamp <slug>`（FRESH になる）と `place_shot.py artifact:<slug>` を走らせる。走らせずに終えようとすると `scripts/hook_artifact_verify_gate.py` が止める。地図の無い成果物は、その時に下書きから作る。

## 1枚の形

先頭は YAML の前書き、本文はローレンさんの地図と同じ4つの節。

```
---
place: artifact:<slug>         # 共通の場所は id（chat など）
name: 画面の名前（みきさんが呼ぶ名前）
open: /preview/<slug>          # ブラウザで開く道。開けない場所は書かず、reach に行き方
ready: '[data-x]'              # 開けたと分かる CSS の印（省略時 body）
speak: |                       # 話すダンに渡す2〜5行。みきさんに何が見えていて、何が出せないか
  - …
probe: {module: style, scope: app, bubble: md}   # 返事の吹き出しの入れ物。CSS モジュールの名前か {classes: "…"}
shows: [番号の並び, 点の並び, 表, 見出し, 太字, コード]   # その入れ物で見えるはずの物
fingerprint: …                 # 成果物だけ。stamp が書く
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
