# Recipe: T1 コンバージョン・フラット（既定技法）

## いつ使う
- 集客・問い合わせ・予約獲得が目的の地域ビジネスHP（吉川特装・五条・バードSTC 等）、情報サイト、SaaS のマーケ LP
- 表示速度・SEO・モバイルが最優先のとき = **迷ったらこれ**

## スタック
- shadcn/ui + Tailwind（既存 templates）
- framer-motion（微細モーションのみ）
- 追加 npm 不要（すべて導入済み）

## 作り方の核
- `LpShell` + `Section` + `HeroMedia` + `ProofBar` + `ServiceShowcase` + `ProcessTimeline` + `ConversionCta` + `InquiryForm` + `LocationMap` を組む
- CTAの数・面積・固定表示は `DESIGN.md` の `cta_intensity` に従う。CV導線は必要だが、表示量は案件ごとの情報密度とブランド体験に合わせる
- セクションごとに構造を変える（均等グリッドの連続禁止）、余白でリズム
- ヒーローは `HeroMedia`（media-gen の AI 画像 or 実写真）

## 標準構成
1. Hero: 何のサイトかを3秒で伝える。本文量とCTA量は `visual_density` / `cta_intensity` に合わせる
2. ProofBar: 実績・対応範囲・年数・件数などの信頼材料
3. ServiceShowcase: 主要サービスを強弱付きで見せる
4. ProcessTimeline: 問い合わせ後の流れ
5. FAQSection: よくある不安を先に潰す
6. ConversionCta: 最終CTA
7. InquiryForm / phone / booking

## モーション（framer-motion）
- `whileInView` で控えめなフェード / スライドイン、hover で微妙な浮き
- スクロールジャック禁止。`prefers-reduced-motion` 尊重
- 動きの量は `motion_intensity` に従う。参考サイト由来の動きを採用する場合は `Interaction Evidence` に目的と実装候補を残す

## 性能ガードレール
- LCP 軽量、重い JS ライブラリを足さない、画像は最適サイズ、モバイルファースト

## 自己評価の追加チェック
- モバイルで CTA が常に届くか / LCP が速いか / 「AI感」脱却チェック全項目
