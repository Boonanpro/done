# 編集可能なLP・ページ成果物

完成条件は見た目の品質と編集可能性の両立。方式の維持を品質の代わりにしない。

## 制作

- ユーザーの目的、実素材、既存の採用デザインを出発点にする。
- コードによる制作、Image 2の見本から再構成、生成素材との併用から選ぶ。
  画像見本を作ることや画像からの変換そのものを必須工程にしない。
- 文章・見出し・価格・CTAはネイティブな文字と要素にする。画像のalt、透明な
  テキスト、画像内の文字と重複したテキストは編集可能性の代わりにならない。
- 写真・複雑なイラスト・テクスチャは画像素材のままでよい。文字を素材へ
  焼き込まない。既存画像からの分離が必要なら元の画像を残して品質を比較する。
- レイアウトは内容に追従させる。改行・文量変更で隣のセクションを覆わないように
  通常フローやgrid/flexを使う。座標固定で見本をなぞるだけで完成としない。
- 一律のカード配列やテンプレートへ押し込めず、写真・余白・文字の大小・構成の
  リズムで案件の意図を表す。既存コンポーネントは適合する場合に利用する。

## ダンの編集・保存との接続

新規成果物の開始時は次を実行する（既存slugには実行しない）。

```bash
python scripts/editable_artifact.py init --slug <slug> --title "成果物のタイトル"
```

`frontend/src/app/artifacts/<slug>/page-body.tsx` に実際のデザインを実装する。
`page.tsx` と `release.gen.json` の接続は初期化済み。画像の再構成はモデルが
見本を見て実装・比較・調整する作業であり、このCLIが画像を自動変換するわけではない。
`editable-artifact.json` の `requiredText` に見出し・本文・CTA・表の全文を、
`references` に比較元のローカルファイルパス（リポジトリ相対）を記録する。
比較元がない新規デザインでは `references` は空配列でよい。

`@/components/dan/editable` を使う。IDはslug・ページ・意味に基づき一意にし、
チャット修正でも維持する。リストは並び順ではなく項目の安定したキーを使う。

- 本文: `<EditableText as="h1" editId="shop-top-title">…</EditableText>`
- 画像: `<EditableElement as="img" editId="shop-top-photo" src="…" alt="…" />`
- 余白や背景を編集する単位:
  `<EditableElement as="section" editId="shop-top-hero">…</EditableElement>`
- リンクの文字とURLを同じ単位で扱うなら `EditableText as="a"`。
  アイコン等を内包する複合要素は、親にEditableElement、文字にEditableTextを使う。
- `data-edit-id`を付けるだけでは公開リビジョンのSSR反映はできない。
  画像・構造もEditableElementで公開のスタイル/属性を読む。
- server pageから `release.gen.json` → `toEditableOverrides` → `EditableProvider`
  を渡す既存契約を使う。公開済み編集とチャット変更の競合はbuild共通ルールに従う。

## 確認

実装後、稼働中のフロントエンドのoriginを指定して確認する。

```bash
python scripts/editable_artifact.py audit --slug <slug> --origin http://localhost:3001
```

390/560/1280pxの画像と検査結果が `scratch/editable-artifacts/<slug>/` に出る。
必須コピー欠落、編集ID不足・重複、画像読込失敗、横溢れ、公開データ接続を検査する。
構造検査の合格は見た目の品質保証ではない。画像内の残存文字、隠れた文字、
写真の不自然な切れ方は必ずスクリーンショットで確認する。

1. デスクトップとスマートフォンでスクリーンショットを見て、文字の読みやすさ、
   写真の切れ方、情報の順序と密度を確認。比較元があれば同じ幅で並べる。
2. 手動編集ONで見出しをクリックし、長い文章・改行へ変更する。
3. 文字サイズ・行間、画像差し替え、セクションの余白を変更する。
4. 再読み込みして保存を確認。公開リビジョンが初回HTMLに文字・画像・スタイルを
   反映することも確認する。外部公開は実行環境の承認ルールに従う。
5. 画像品質の比較・手動編集・保存・公開の検証を分けて報告する。保存APIを
   モックしたテストを、本番DBや公開URLまで成功した証拠と扱わない。

確認と修正が済んだら次で完了を記録する。変更後はauditを再実行する。

```bash
python scripts/editable_artifact.py finish --slug <slug> --review-notes "見本との差分・編集確認の結果"
```

DANのチャット実行環境（`DAN_ROOM_ID`/`DAN_SESSION_ID` と `DAN_PROJECT_ID`）では
`--register` を付け、既存の成果物登録・配信経路に渡す。登録は配信を開始し得るため、
ユーザーの制作依頼と実行環境の権限範囲に従う。識別子を捏造しない。
CLI実行はファイル書込みフックで拾えない場合もあるので登録結果を確認する。
既存成果物ではreleaseと安定IDを維持し、初期化で保存済み編集を消さない。

同じ内容の画像LPとの比較例: `frontend/src/components/artifacts/floor-lp-reconstruction.tsx`。
`/preview/floor-lp-compare` で元画像と並べ、文字変更・写真非表示で実要素を確認できる。
検証: `python scripts/test_floor_lp_comparison.py`。
写真は元画像の写真領域だけをCSSで表示し、周囲の文字・表・CTAを再構成している。
この作業はモデルが画像を見て実装・調整した例であり、汎用の自動変換器ではない。
別デザインを新しく作っただけの例を、画像方式との品質比較に使わない。
採用例を通常の成果物編集パネルで検証するコマンド:
`python scripts/test_editable_lp.py --floor --output scratch/floor-lp-native-editor`。
対象は `/preview/floor-lp-native`。保存APIはテスト用、SSRは実際のNext.jsページを使用する。
一つの例で全案件の品質や画像方式への優位性が証明されたとは扱わない。
