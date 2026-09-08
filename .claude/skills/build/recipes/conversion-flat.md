# Recipe: T1 コンバージョン・フラット

## いつ使う
- 集客・問い合わせ・予約獲得が目的の地域ビジネス HP（吉川特装・五条・バード STC 等）、
  情報サイト、SaaS のマーケ LP
- 表示速度・SEO・モバイルが最優先のとき。迷ったらこれが無難

## スタック
- Tailwind + 既存 templates（shadcn/ui は使ってもよい、義務ではない）
- framer-motion（微細モーション）
- 追加 npm 不要

## 作り方の核
- `LpShell` + `Section` + `HeroMedia` + `FeatureGrid` / `ServiceShowcase` / `CaseStudyGrid` /
  `ProcessTimeline` / `ProofBar` / `FaqSection` + `ConversionCta` + `InquiryForm` + `LocationMap`
  から合うものを選んで組む。合わなければ書く
- 全セクションから CTA（問い合わせ / 電話 / 予約）に到達できる。モバイルで即タップ
- セクションごとに構成を変えると読み進めやすい（均一なカード行列だけだと単調になりやすい）
- ヒーローは `HeroMedia`（実写真が最優先。無ければ生成画像）

## モーション（framer-motion）
- `whileInView` で控えめなフェード / スライドイン、hover で応答感
- スクロールジャックしない。`prefers-reduced-motion` を尊重

## 性能
- LCP を軽く。重い JS ライブラリを足さない。画像は最適サイズ。モバイルファースト

## 確認の追加項目
- モバイルで CTA が常に届くか / LCP が速いか
