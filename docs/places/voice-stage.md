---
place: voice-stage
name: 通話中の画面
reach: スマホの通話画面、またはPCの通話パネル。電話を発信しない確認は scripts/check_voice_common_controls.py で通話画面の通信だけを試験用に差し替える
watches:
  - frontend/src/components/voice/voice-stage.tsx
  - frontend/src/components/artifacts/voice-controls.ts
  - frontend/src/components/artifacts/voice-controls-runtime.tsx
  - frontend/src/app/artifacts/layout.tsx
speak: |
  - 通話中は、成果物の本物の画面、番号や選択肢の大きな札、説明の図が出る。
  - 成果物の操作先を声で指定すると、画面のボタンや欄を光らせて操作する。送信などは読み上げと本人の承認を待つ。
  - 外のブラウザやスマホは操作している実画面の写真。操作ごとに更新するが、写真を指で押して操作するものではない。
fingerprint: eb576cd33cf43261
described: da83d1da81fba8da
last_review: "2026-10-30 説明は変えない: 古い画面の操作を拒否する条件を強化。説明済みの見え方は同じ"
---
# 通話中の画面

## 中にある物

- 本物の成果物。画面上の名前のあるボタン、リンク、入力欄、選択欄を共通の仕組みで操作する。
- 番号・日時・金額・短い選択肢の札。数字を大きく表示し、次にすることは1つに絞る。
- 説明の図。操作中の本物の画面を自動の図で置き換えない。
- 外の画面。ダンのブラウザ、スマホが実際に見ている画面を表示する。本人の部屋の権限で読み、公開添付にはしない。

## 行き方（みきさんから見て）

スマホ・PCからダンと通話し、「開発室を出して」などと頼む。同じ成果物の画面が開く。

## 道具で動かす

- `show_page_on_stage` → 本物の成果物。`read_screen` で今の画面の `page_id` と各操作先の `id`・`fingerprint` を読む。`operate_screen` でその3つをそのまま渡す。結果の画面を読み、保存・送信はその表示で確認する。
- `read_screen(query)` は現在描画された操作先を名前で絞る。仮想リストや別ページのデータは、そのサイトの検索欄で検索する。全体の台帳はない。
- `show_fact_on_stage` → 分かっている数字・短い選択肢の札。確認番号の発話は、漢数字を表示用の数字へ直す。
- `show_external_screen(source=browser|phone)` → 同じ操作セッションの写真。その後の browser/phone 操作でも更新する。
- 試験: `python scripts/check_voice_common_controls.py` は実際の3サイトの画面を、試験用の通話状態と結び付けて5操作ずつ行い、`.data/voice-proof/operations.json`、動画、写真へ残す。外部送信・実データ書込・電話発信は禁止した試験。数値は操作命令から結果までで、音声認識とモデル判断時間を含まない。

## 落とし穴

- 共通の操作はDOMの名前を使う。ラベルのない部品、canvasだけの操作、未描画のリスト項目、複雑なcontenteditableの編集にはそのまま使えない。新しい成果物はbuildスキルの声の操作条件に従う。
- 未分類のボタンは承認が必要。重要な操作の名前と危険度を付けると、通常の移動と確認が要る操作を区別できる。
- 別の画面・別の通話の操作先、更新されたボタン、無効な欄、上を覆われたボタンは押さない。結果が届かなければ再送せずに画面を読む。
- 2端末で通話画面を開いても、短い貸出時間で選ばれた片方の画面だけを操作する。
- 表示済みの外の画面は静止画。Googleの追加認証や端末未接続があれば、その先を操作できるとは言わない。
- 実通話の開始は本人の明示許可が必要。試験だけで「言い終わって1秒」を達成したと言わない。

<!-- place_map:auto:start -->
## コードから（自動）

`python scripts/place_map.py stamp voice-stage` が書き直す。手で直さない。

- 見張るファイル: `frontend/src/app/artifacts/layout.tsx`, `frontend/src/components/artifacts/voice-controls-runtime.tsx`, `frontend/src/components/artifacts/voice-controls.ts`, `frontend/src/components/voice/voice-stage.tsx`

<!-- place_map:files {"frontend/src/app/artifacts/layout.tsx": "6c7952f98d", "frontend/src/components/artifacts/voice-controls-runtime.tsx": "9d91ec619c", "frontend/src/components/artifacts/voice-controls.ts": "7441aa719a", "frontend/src/components/voice/voice-stage.tsx": "1afc381621"} -->
<!-- place_map:auto:end -->
