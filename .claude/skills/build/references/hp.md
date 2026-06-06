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
   - `type_system`: headline / body / label のフォント候補、太さ、行間、字間。日本語と英字でtrackingを分ける
4. 2-3案のビジュアル方向性を出し、1案を選ぶ。
5. `Visual Direction Lock` を行う。Reference-board mode / Brand-guideline image mode / Skip のどれかを選び、理由を `DESIGN.md` に書く。
6. 参考サイトを確認し、`Reference Evidence` と `Interaction Evidence` を残す。
7. 実装後、設計パラメータと実装が一致しているか確認する。

## Visual Direction Lock

新規HP、プロ品質の一発出し、ブランド/店舗/採用/実績掲載のように見た目の世界観が重要な案件では、実装前に視覚方向を固定する。

次のどれかを選ぶ:

### Reference-board mode

実在サイト、1GUU、Godly、ユーザー提供素材、既存写真から方向性を固める。
`DESIGN.md` に以下を整理する。

- `type_system`: headline / body / label の候補、太さ、行間、字間
- `color_system`: neutral / primary / accent / border
- `photo_tone`: 明るさ、色温度、構図、トリミング
- `cta_style`: 塗り、罫線、余白、固定表示の有無
- `editorial_accents`: roundel、罫線、スタンプ、キャプション、情報帯など
- `motion_direction`: none / subtle / expressive / scroll-driven と採用理由

### Brand-guideline image mode

GPT Image 2でブランドガイドライン画像を作り、そこから方向性を固める。
向く案件: 店舗、宿、美容、採用、ブランドサイト、実績掲載、ポートフォリオ化したいHP。

画像に含めたい要素:

- ロゴ/仮ロゴの扱い
- color palette
- typography samples
- photography tone
- CTA/button examples
- editorial accents such as roundel, rule, seal, caption, info strip
- layout principle
- wrong usage if useful

作った画像はそのまま実装仕様として信じない。`DESIGN.md` へ `type_system`、色、CTA形状、アクセント部品、写真トーンとして抽出し、実在フォント/CSS変数/React componentに置き換える。

### Skip

既存HPの軽微修正、情報優先の小ページ、時間優先の修正ではスキップしてよい。
スキップする場合も `DESIGN.md` に理由を書く。

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

## Typography and Editorial Accents

フォントを1つに固定しない。案件ごとに `type_system` を決め、文字の役割ごとに組む。
毎回 `text-5xl font-bold tracking-wide` のような直接指定に逃げず、標準部品を使う。

文字組み標準部品:

- `HeroCopy`: 横組みの強いヒーロー見出し。
- `VerticalHeroCopy`: 縦書きヒーロー見出し。和食、宿、工芸、作家性のある案件向け。
- `SectionKicker`: 小さな章ラベル。英字/短いラベル向け。
- `SectionTitle`: セクション見出し。
- `LeadCopy`: 導入文。余白と行間を大きく取る。
- `BodyCopy`: 本文。読みやすさ優先。
- `MetaLabel`: メタ情報、日付、カテゴリ、短い補助ラベル。
- `EditorialButton`: 色面積に頼らず、罫線・余白・文字で上品に見せるCTA。

編集的アクセント:

- `RoundelBadge`: 円形コールアウト/roundel。距離、実績、限定性など、主見出しではない強調に使う。
- `SealMark`: 角印/小さなスタンプ風の印。
- `RuleDivider`: 細い罫線区切り。章の切り替えや余白の整理に使う。
- `PhotoCaption`: 写真キャプション。
- `InfoStrip`: 営業時間、所在地、料金、実績などの横断情報。
- `EditorialFrame`: 写真や情報を細い罫線で囲む。

判断ルール:

- 日本語本文に大きなletter-spacingをかけない。英字ラベルの広いtrackingを日本語へ流用しない。
- 高級感は太字や大ボタンではなく、余白、行間、細い罫線、写真、低い色面積で作る。
- Brand-guideline image mode を使った場合は、そこから `type_system`、色、CTA形状、アクセント部品を抽出してDESIGN.mdに書く。
- 画像内のフォント名やカラーコードはそのまま信じず、実在フォントとCSS変数に置き換える。

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
