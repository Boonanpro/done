# 株式会社パイナ コーポレートサイト DESIGN.md

## 目的分類
信頼形成 + ブランド + 実績掲載 + リード獲得（問い合わせ / Done ウェイティングリスト）。
メイン事業 = AIエージェント「Done（ダン）」の開発と将来提供。
参考: https://thinkingmachines.ai/（AI研究ラボのマニフェスト型サイト）。

## クリエイティブディレクション（ビジネスゴールから逆算）
1. ビジネスゴール: パイナが「思想を持ってAIエージェントを作っている会社」だと伝え、Doneへの期待値とDX支援/制作の受注を生む。
2. 訪問者の行動: ①Doneのウェイティングリスト登録 ②事業（制作/DX支援）の問い合わせ。
3. 確信させたいこと: 明確な思想・アプローチがある / 実際に作って提供した実績がある（吉川特装・五条・スタイルアップ・電管ナレッジ）。
4. 必要なコンテンツ: 思想を語る長文マニフェスト、開発アプローチの言語化、事業の整理、実績4件、問い合わせ導線。
5. デザイン方針: 主役は「言葉（コピー）」。写真は持たないので、余白・タイポグラフィ・細い罫線で知性と落ち着きを作る。

## レンダリング方針
`dom-first`。SEOと編集性、長文可読性を優先。画像はロゴワードマークのみ。

## 表現パラメータ
- visual_density: sparse
- cta_intensity: quiet（ナビ右端に主CTA、各ページ末に静かな最終CTA）
- motion_intensity: subtle（FadeIn / 行リビールのみ。スクロール演出はしない）
- content_priority: copy
- authenticity_policy: generated-atmosphere（生成物はロゴワードマークのみ。実績の社名・事実は実在情報）

## type_system
- 表示見出し（hero/マニフェスト）: JP=Noto Serif JP 500/600、EN=Fraunces 400/500（optical serif）。literary で思索的なトーン。
- セクション見出し: 同上 serif、サイズを落とす。
- 本文: Noto Sans JP 400、行間広め（leading-loose）、JPに大きな字間をかけない。
- ラベル/キッカー/ナビ/EN: Space Grotesk、uppercase、tracking 広め。
- ロゴ: 生成ワードマーク "PAINA"（/paina/logo.png）。

## color_system（4層・warm ink monochrome + quiet gold）
- Neutral 背景: warm near-white（#FAFAF7 相当）
- Primary 文字: warm near-black（#1A1712 相当）
- Accent: muted gold/amber（#B08D3F 相当）— 罫線の差し色、キッカー、ウェイティングリスト等、面積はごく僅か
- Border: light warm gray
ダークではなくライト基調。色面積に頼らず余白と罫線で品を作る。

## 構成（企業HP型）
- ホーム `/artifacts/paina`: hero(社名+一文) / 思想マニフェスト(長文) / 開発アプローチ(原則3-4) / 事業サマリ / 実績ティーザー / 最終CTA
- 事業内容 `/artifacts/paina/business`: Done(coming soon + ウェイティングリスト) / HP制作 / DX支援、各に実績。実績=吉川特装・五条(制作)、スタイルアップ・電管ナレッジ(DX支援)
- 問い合わせ `/artifacts/paina/contact`: InquiryForm（scope=paina-contact）→ /api/v1/inquiries → メール shub6923@gmail.com

## バックエンド
- 問い合わせ/ウェイティングリスト: 既存 `/api/v1/inquiries`（scope で分岐）。
- メール通知を新規追加: `app/services/inquiry_notify.py`（Gmail SMTP, 宛先 shub6923@gmail.com）。inquiry_service.create から発火。
- waitlist scope=`paina-waitlist`、contact scope=`paina-contact`。

## Reference Evidence（thinkingmachines.ai）
- ファーストビュー情報量: 極小。社名と一文の宣言のみ、巨大な余白。
- タイポ: 英文セリフ + grotesk。見出し大きすぎず、本文が主役の読み物。
- セクション: 斜体の小見出しラベル → 段落。罫線で仕切らずホワイトスペースで分離。
- CTA: 非常に静か。末尾に「Join us」程度。
- 採用方針: 写真ゼロでも成立する「言葉とレイアウトの品」。これをJP企業HPに翻訳する。

## Interaction Evidence
- 動きはほぼ無し。読み物として静的。→ motion=subtle、入場 FadeIn のみ採用。スクロール固定演出は不採用（思索的トーンを壊さない）。
