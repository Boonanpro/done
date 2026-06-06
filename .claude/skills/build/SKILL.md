---
name: build
description: >
  Next.js + shadcn/ui + Tailwind で見せて使える成果物を実装するスキル。
  ダッシュボード、社内/公開ツール、HP、LP、問い合わせフォーム付きページなどを作る時に使う。
---

# build スキル

このファイルは**振り分け役**。依頼が何を作るものか（HP / LP / Tool / Dashboard）を見分けて、対応する詳しい手順書（`references/*.md`）だけを読む。作り方そのものは各 `references` に書いてある。
HP制作でLPの型を読ませない。LP制作でHPのブランド表現を読ませない。

## 1. 最初に分類する

ユーザーの依頼を次のどれかに分類し、該当する primary reference を読む。

| タイプ | 例 | 必ず読む |
|---|---|---|
| HP | 店舗サイト、企業サイト、採用サイト、ブランドサイト、実績掲載サイト | `references/hp.md` |
| LP | 広告LP、モニター募集、待機リスト、商品/サービス単体訴求、需要検証 | `references/lp.md` |
| Tool | 予約、診断、生成、投稿支援、業務フローなど操作が主役 | `references/tool.md` |
| Dashboard | KPI、一覧、チャート、管理画面、業務モニタリング | `references/dashboard.md` |

**どのタイプか迷う時**（1つに絞る）:

- 複数ページやブランド/店舗全体の信頼形成が主目的 → **HP**
- 1つの行動に一直線で誘導する広告・募集・検証 → **LP**
- ユーザーが画面で作業する → **Tool**
- データを見て判断する → **Dashboard**

**複数のタイプが混ざる時**: 主役(primary)を1つ決め、必要な add-on だけ読む。
例: 店舗HP（HP）に予約機能（Tool）を入れる → `references/hp.md` + Toolの予約ブロックだけ読む。

## 2. 共通実装ルール

- 通常の成果物は `frontend/src/app/artifacts/{slug}/` に作る。
- `frontend/src/components/templates/` を先に確認して使う。無ければ、再利用価値があるものだけ templates に足してから使う。
- 編集対象の見出し、本文、CTA、主要画像/動画には一意の `data-edit-id` を付ける。
- 画像/動画素材が必要なら `media-gen`（標準: 画像=GPT Image 2、動画=Seedance 2.0）。
- ユーザー提供素材を優先。実在の店舗/人物/商品をAI素材で置き換える時は、その扱いを設計メモに残す。
- `browser` ツールでPC 1440pxとモバイル390pxを確認し、ファーストビュー・CTA・文字詰まり・画像/動画の見え方を直してから出す。
- 既存のユーザー変更を巻き戻さない。

## 3. 共通テンプレート

成果物を書く前に **`frontend/src/components/templates/index.ts` を読んで使える部品を確認する**（ここが唯一の正。部品はここで増減する）。

主な部品（全部ではない。完全版は index.ts を見る）:

- 外枠: `PageShell`（管理画面/ツール）, `LpShell`（LP/HP全体）, `Section`（縦リズムとmax-width）
- ヒーロー: `HeroMedia`（静止画/動画背景）, `FullBleedVideoHero`（全画面動画）, `ScrollVideo`（スクロール連動動画）, `HeroSection`（汎用）
- 信頼/実績: `ProofBar`, `CaseStudyGrid`
- サービス/導線: `ServiceShowcase`, `ProcessTimeline`, `ConversionCta`, `FaqSection`, `InquiryForm`, `LocationMap`
- 画像スライス: `ImageSlicePage`
- ダッシュボード: `KpiCard`, `FeatureGrid`

タイポ・装飾の細かい部品（`HeroCopy`, `RoundelBadge`, `BrushStroke` 等）は `references/hp.md` を参照。

## 4. 検証

`criteria.md` を参照し、分類したタイプに合う基準で自己評価する。
生成→評価→改善のループ手順は `actions/create.md` を参照する。
HP/LPでは `DESIGN.md` または同等の設計メモを成果物フォルダに置き、後続改善で参照できるようにする。

提案書HTMLはユーザーが明示した時だけ `actions/proposal_html.md` を読む。
