---
name: build
description: >
  Next.js + shadcn/ui + Tailwind で見せて使える成果物を実装するスキル。
  ダッシュボード、社内/公開ツール、HP、LP、問い合わせフォーム付きページなどを作る時に使う。
---

# build スキル

このファイルは **ルーター**。制作物タイプを分類し、必要な参照ファイルだけを読む。
HP制作でLPの型を読ませない。LP制作でHPのブランド表現を読ませない。

## 1. 最初に分類する

ユーザーの依頼を次のどれかに分類し、該当する primary reference を読む。

| タイプ | 例 | 必ず読む |
|---|---|---|
| HP | 店舗サイト、企業サイト、採用サイト、ブランドサイト、実績掲載サイト | `references/hp.md` |
| LP | 広告LP、モニター募集、待機リスト、商品/サービス単体訴求、需要検証 | `references/lp.md` |
| Tool | 予約、診断、生成、投稿支援、業務フローなど操作が主役 | `references/tool.md` |
| Dashboard | KPI、一覧、チャート、管理画面、業務モニタリング | `references/dashboard.md` |

分類に迷う場合:

- 複数ページやブランド/店舗全体の信頼形成が主目的なら **HP**。
- 1つの行動に一直線で誘導する広告・募集・検証なら **LP**。
- ユーザーが画面で作業するなら **Tool**。
- データを見て判断するなら **Dashboard**。

重なる案件では primary を1つ決め、必要な add-on だけ読む。
例: 店舗HPに予約機能を入れるなら `references/hp.md` + Toolの予約ブロック。LPの型は読まない。

## 2. 共通実装ルール

- 通常の成果物は `frontend/src/app/artifacts/{slug}/` に作る。
- 既存の `frontend/src/components/templates/` を先に確認し、使えるものは使う。
- 足りない構造は成果物内で毎回手書きせず、再利用価値があるなら `frontend/src/components/templates/` に足してから使う。
- 編集対象の見出し、本文、CTA、主要画像/動画には一意の `data-edit-id` を付ける。
- 画像/動画素材が必要な場合は `media-gen` を使う。標準は画像=GPT Image 2、動画=Seedance 2.0。
- ユーザー提供素材は優先して使う。実在店舗/人物/商品をAI素材で置き換える場合は、その扱いを設計メモに残す。
- Playwright等でPC 1440pxとモバイル390pxを確認し、ファーストビュー、CTA、文字詰まり、画像/動画の見え方を直してから出す。
- 既存のユーザー変更を巻き戻さない。

## 3. 共通テンプレート

成果物を書く前に `frontend/src/components/templates/` を確認する。

| コンポーネント | 用途 |
|---|---|
| `<PageShell>` | 管理画面/ツールの外枠 |
| `<LpShell>` | LP全体の外枠 |
| `<Section>` | セクションの縦リズムとmax-width |
| `<HeroSection>` | 汎用ヒーロー |
| `<HeroMedia>` | 静止画/通常動画背景のヒーロー |
| `<FullBleedVideoHero>` | 全画面動画ファーストビュー |
| `<ScrollVideo>` | スクロール量に合わせて動画と章テキストを進める |
| `<ImageSlicePage>` | 画像スライス + active DOM overlay |
| `<ProofBar>` | 信頼材料の横断バンド |
| `<ServiceShowcase>` | 主要サービスを強弱付きで見せる |
| `<CaseStudyGrid>` | 実績/事例 |
| `<ProcessTimeline>` | 導入/問い合わせ後の流れ |
| `<ConversionCta>` | 最終CTA |
| `<FaqSection>` | FAQ |
| `<InquiryForm>` | 問い合わせフォーム |
| `<LocationMap>` | Google Maps iframe |

## 4. 検証

`criteria.md` を参照し、分類したタイプに合う基準で自己評価する。
HP/LPでは `DESIGN.md` または同等の設計メモを成果物フォルダに置き、後続改善で参照できるようにする。

提案書HTMLはユーザーが明示した時だけ `actions/proposal_html.md` を読む。
