# 編集可能な成果物の通常制作への接続

2026-09-07。ユーザーが確認した床暖房LPの再構成を、通常の成果物用コンポーネントと
公開データの契約へ接続した。比較画面のlocalStorageエディターは使っていない。

## 変更

- buildの新規LPレシピに `scripts/editable_artifact.py` の開始・検査・完了手順を追加。
  Image 2の見本を使う場合も、直接コードで制作する場合も同じ編集契約を利用する。
- `init` はserver page、EditableProvider、releaseデータ、制作body、確認用manifestを用意。
  既存slugへの上書きを拒否する。
- `audit` は390/560/1280pxで必須コピー、編集ID、画像読込、横溢れと接続を確認し、画像を保存。
  見た目の合否はモデルが画像を見て判断する。透明文字や画像内の文字の完全検出器ではない。
- `finish` は検査後のソース・参照画像・ローカル依存変更を検出し、レビュー内容を記録。
  チャット環境では `--register` で既存core登録・配信経路へ渡す。
  この検証ではチャット登録や外部配信を実行していない。
- 床暖房の通常成果物は `/preview/floor-lp-native`。元画像比較は `/preview/floor-lp-compare`。
  対象は元LPの先頭2セクション。登録ボタンの業務処理は検証範囲外。

このCLIは画像を自動分解する変換モデルではない。DANが見本を読み、本文・CTA・表を
実要素として実装し、品質を比較する制作ループを支援する。写真は画像として差し替え可能。
写真そのものの画素や複雑なイラストの内部は、この編集機構で編集する対象ではない。

## 検証

`python scripts/test_editable_lp.py --floor --output scratch/floor-lp-native-editor`

実際のPreviewPaneとinspectorを使い、見出し・行間・画像URL・セクション余白を変更。
ブラウザー保存領域を持たない別contextで取得データから復元し、通常の「保存」ボタンが
下書き保存後にreleaseを要求することを確認。保存APIのテスト実装がローカルreleaseへ
反映し、JavaScriptを無効にした実際のNext.jsページで文字・画像・余白を確認した。
長い見出しでも次のセクションに重ならない。テスト後はreleaseを元に戻す。

保存APIはメモリー内の代替実装で、本番の認証・DB・配信は未検証。
テストで実ユーザーのチャットへ成果物を追加したとは扱わない。
通常チャットで別の依頼を最初から生成し、品質が安定して再現するかは今後の実運用確認が必要。

`python -m pytest tests/test_editable_artifact.py -q`：3件合格。
既存release保護、不正slug拒否、未合格検査・レビュー欠落・依存更新後の完了拒否を確認。

`python scripts/editable_artifact.py audit --slug floor-lp-native`：全3幅合格。
スマホ画像と編集後画像を目視確認。元画像との差は比較検証と同じで、アイコンは代替品。
結果は `scratch/editable-artifacts/floor-lp-native/` と
`scratch/floor-lp-native-editor/` に保存。
