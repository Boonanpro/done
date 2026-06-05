# HP Reference

HPは、店舗/企業/ブランド/採用/実績掲載など、対象全体への理解と信頼を作るサイト。
広告LPの平均型を流用しない。CTAは重要だが、ブランド体験と情報探索を壊さない範囲で設計する。

## 必須フロー

1. 目的分類: 集客 / 採用 / ブランド / 実績掲載 / 信頼形成 / 店舗案内。
2. レンダリング方針を決める:
   - `dom-first`: SEO、編集性、情報量を重視。
   - `comp-guided-dom`: 高品質ビジュアルコンプを参照しHTMLで再構成。
   - `image-slice-hybrid`: 見せ場の画像スライス + active DOM overlay。
   - `media-rich-hybrid`: 実写/生成動画、レイヤー、パララックス、スクロール演出を組み合わせる。
3. 表現パラメータを `DESIGN.md` に書く:
   - `visual_density`: sparse / balanced / dense
   - `cta_intensity`: quiet / standard / aggressive
   - `motion_intensity`: none / subtle / expressive / scroll-driven
   - `content_priority`: imagery / copy / proof / utility / interaction
   - `authenticity_policy`: real-assets-only / generated-atmosphere / generated-placeholder
4. 2-3案のビジュアル方向性を出し、1案を選ぶ。
5. 参考サイトを確認し、`Reference Evidence` と `Interaction Evidence` を残す。
6. 実装後、設計パラメータと実装が一致しているか確認する。

## Reference Evidence

ユーザー提供URLを最優先する。ない場合は業種に合う実在サイト、1GUU、Godly等から最低3件を見る。
丸写しせず、次を抽出する。

- ファーストビューの情報量
- 写真/動画のトリミング
- タイポグラフィ
- 余白とセクションリズム
- CTAの出し方
- スクロールやホバーの動き

参考サイトに動きがある場合は `Interaction Evidence` に、見た動き、目的、採用/不採用、実装候補を書く。

## HPの構成判断

標準構成は固定しない。目的に合わせて組む。

- 店舗HP: hero / about / menu or service / space or gallery / access / reservation/contact
- 企業HP: hero / proof / services / cases / process / company / contact
- 採用HP: hero / mission / people / work / culture / requirements / entry
- 実績掲載HP: hero / positioning / cases / capabilities / process / contact

`FeatureGrid` や均等カード列だけを連続させない。
セクションごとに主役と見せ方を変える。

## CTA

CTAの数や強さは `cta_intensity` に従う。

- `quiet`: ナビ、固定タブ、小さな最終CTAなど。画面の余白を優先。
- `standard`: heroまたはナビに主CTA、途中と最後に自然な導線。
- `aggressive`: 広告流入や緊急性が高い場合。固定CTAや複数箇所を許可。

「集客目的」だけで aggressive にしない。

## Motion

動きは `motion_intensity` に従う。

- `none`: 静的。速度/読みやすさ優先。
- `subtle`: hover、軽いreveal、ナビ状態変化。
- `expressive`: 画像リビール、背景変化、レイヤーパララックス。
- `scroll-driven`: ScrollVideo、GSAP/Lenis、章立てスクロール。性能予算とreduced-motion fallback必須。

使える標準部品:

- `FadeIn` / `Stagger`: 軽いreveal。subtle向け。
- `ImageReveal`: 写真がマスクで開く。料理、物件、人物、作品の見せ場向け。
- `ParallaxMedia`: 写真/動画が少し遅れて動く。フルブリード写真や2カラムの媒体向け。
- `TextReveal`: 見出しを行単位で出す。ファーストビューや強い章見出し向け。
- `StickyStory`: 片側の媒体を固定し、章テキスト・進捗レール・active章ハイライト・章ごとのmediaフェードで読ませる。採用/ブランド/こだわり説明向け。
- `SectionThemeShift`: セクション進入で背景色やトーンを変える。明暗の切り替えや没入感向け。

判断ルール:

- `subtle`: `FadeIn` / `Stagger` 中心でよい。
- `expressive`: `FadeIn` だけで終わらせず、`ImageReveal` / `ParallaxMedia` / `TextReveal` / `SectionThemeShift` から最低1つ使う。
- `scroll-driven`: `ScrollVideo` または `StickyStory` を主役にし、reduced-motion fallbackを用意する。`StickyStory` は各章にmediaを渡せるなら渡し、章が進んだことを視覚的に分かるようにする。

参考サイトの動きを採用すると書いた場合、Interaction Evidenceの「目的」と上記部品を対応させる。

## 素材

実在店舗/人物/商品では、AI生成素材が期待値を偽らないか確認する。

- `real-assets-only`: 実写・実物のみ。
- `generated-atmosphere`: 和紙、光、背景、抽象質感など非欺瞞素材のみ生成。
- `generated-placeholder`: 後で差し替える前提の仮素材。サイト上でも誤認を避ける。

## 完了条件

- `DESIGN.md` に目的、レンダリング方針、表現パラメータ、Reference Evidence、Interaction Evidenceがある。
- ファーストビューの情報量が `visual_density` と合っている。
- CTA露出が `cta_intensity` と合っている。
- 動きが `motion_intensity` と合っている。
- PC/mobileスクリーンショットで文字、CTA、画像/動画が崩れていない。
