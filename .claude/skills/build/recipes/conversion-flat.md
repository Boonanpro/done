# Recipe: T1 コンバージョン・フラット（既定技法）

## いつ使う
- 集客・問い合わせ・予約獲得が目的の地域ビジネスHP（吉川特装・五条・バードSTC 等）、情報サイト、SaaS のマーケ LP
- 表示速度・SEO・モバイルが最優先のとき = **迷ったらこれ**

## スタック
- shadcn/ui + Tailwind（既存 templates）
- framer-motion（微細モーションのみ）
- 追加 npm 不要（すべて導入済み）

## 作り方の核
- `LpShell` + `Section` + `HeroMedia` + `FeatureGrid` + `InquiryForm` + `LocationMap` を組む
- 全セクションに CTA（問い合わせ / 電話）。モバイルで即タップ可能に
- セクションごとに構造を変える（均等グリッドの連続禁止）、余白でリズム
- ヒーローは `HeroMedia`（media-gen の AI 画像 or 実写真）

## モーション（framer-motion）
- `whileInView` で控えめなフェード / スライドイン、hover で微妙な浮き
- スクロールジャック禁止。`prefers-reduced-motion` 尊重

## 性能ガードレール
- LCP 軽量、重い JS ライブラリを足さない、画像は最適サイズ、モバイルファースト

## 自己評価の追加チェック
- モバイルで CTA が常に届くか / LCP が速いか / 「AI感」脱却チェック全項目
