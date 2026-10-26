---
place: artifact-tab
name: 成果物タブ（PC で、左にこの部屋の会話、右に成果物の画面）
reach: PC のダン本体で、成果物のある部屋を開くと右に出る。スマホのアプリには無く、成果物は押した時だけ公開版の写しをブラウザで開く
speak: |
  - PC で開いている時は、左にこの部屋の会話、右の成果物タブに成果物が1つ出る（上の切り替えで、この部屋の別の成果物にできる）。右の画面は成果物のファイルそのもので、ダンが直すと数秒で新しい版に切り替わる。スマホのアプリには成果物タブが無い。
  - 成果物の中の物を言う時は、どの成果物の話かを名前で言い、ボタンや欄は地図の「中にある物」の名前で呼ぶ。今どの成果物が出ているかは前置きの行で判断し、分からない時は決めつけない。
watches:
  - frontend/src/components/preview/preview-pane.tsx
fingerprint: 0fd2255e1824073e
described: 83a08ba47098db50
---
# 成果物タブ

ダンが作ったサイトやアプリ（成果物）を、その部屋の会話の横で動かして見る場所。みきさんはここで見て、左の会話で直してほしい所を言う。

## 中にある物

- `tab-list` 右の上の成果物の切り替え。部屋に成果物がいくつかある時に出る。
- `preview` 成果物の画面（`/preview/<slug>`）。ファイルを読む開発サーバー（3001）から出るので、保存した直後の版が出る。
- `release-badge` 公開版（スマホのアプリが開く写し）の状態。
- `chat` 左の会話。チャットと同じ吹き出し（chat の地図）。

## 行き方（みきさんから見て）

- PC: 部屋の一覧で成果物のある部屋を選ぶ → 右に成果物タブ。成果物が複数あれば上の切り替えで選ぶ。
- スマホ: アプリの部屋から成果物を押すと、使い捨ての入館証を付けて公開版の写しがブラウザで開く。

## 道具で動かす

前提:

- 成果物ごとの地図（`frontend/src/app/artifacts/<slug>/MAP.md`）があること。無ければ `python scripts/place_map.py draft <slug>`。

- **成果物の画面。** `python scripts/place_shot.py artifact:<slug> --tag before|after`。地図の `open` の画面をテスト用アカウントで開き、`shows` があればそれも測る。
- **みきさんの画面の版。** `python scripts/artifact_seen.py --slug <slug> --wait 90`。みきさんが開いている画面・裏側・公開版が今のファイルかを見る。
- **地図。** 画面を書き換えたら地図の4つの節を直して `python scripts/place_map.py stamp <slug>`。

## 落とし穴

- ダンのブラウザ（テスト用アカウント）で見えたことは、みきさんの画面の証拠にならない（2026-10-18 古い部品のせいで×ボタンが出なかった）。artifact_seen を必ず見る。
- 持ち主のアカウントだけが読む中身（開発室のボードなど）は、テスト用アカウントでは空か別の中身になる。
- 公開版の写しは、ファイルが1分静かになってから作り直され、数分かかる。

<!-- place_map:auto:start -->
## コードから（自動）

`python scripts/place_map.py stamp artifact-tab` が書き直す。手で直さない。

- 見張るファイル: `frontend/src/components/preview/preview-pane.tsx`

<!-- place_map:files {"frontend/src/components/preview/preview-pane.tsx": "b9bbcad33b"} -->
<!-- place_map:auto:end -->
