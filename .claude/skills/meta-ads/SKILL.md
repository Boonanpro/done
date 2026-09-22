---
name: meta-ads
description: "Operate Meta ad campaigns or Instagram publishing when those external actions are requested."
allowed-tools: Bash
---

# Meta Ads (Instagram / Facebook)

実際に Meta 広告を出稿・運用し、Instagram にオーガニック投稿するスキル。公式 CLI は無いため
`scripts/meta_ads_cli.py`（Marketing API / Graph API の薄いラッパー、`requests` のみ依存）を使う。

## アーキテクチャ（マルチテナント / SaaS）

- **運営者の Meta Developer App は1つ**。各テナント（クライアント）は自分の広告アカウントを
  OAuth で接続し、自分のトークンを持つ。`(user_id, account_label)` で識別。
- 接続情報は `meta_ad_accounts` テーブルに暗号化保存（`app/services/meta_ads_service.py`）。
- `user_id` は既定で `$DAN_USER_ID`（無ければ owner）。複数アカウントは `--account <label>` で切替。

## ⚠️ 課金・公開ゲート（厳守）

- `publish`（キャンペーン/広告セット/広告の**有効化＝課金開始**）と `ig-post`（**公開投稿**）は
  **`--confirm` 必須**。付けずに実行すると承認待ちプロンプト（`needs_approval: true`）を返して何もしない。
- ユーザーに予算上限・期間・ターゲットを提示し、**明示承認を得てから** `--confirm` を付けて再実行する。
  「いい感じ」等の曖昧な返事で出稿しない。
- 作成系（`campaign`/`adset`/`ad`）は**常に PAUSED** で作られる。ここまでは課金されない。

## セットアップ（初回のみ）

詳細は [references/account-setup.md](references/account-setup.md)。要点:

1. **運営者 App（1回）**: Meta for Developers でアプリ作成 → Marketing API 追加 → App ID/Secret を
   `python scripts/meta_ads_cli.py connect-app --app-id <ID> --app-secret <SECRET>`
   （または env `META_APP_ID`/`META_APP_SECRET`）。
2. **テナント接続**: クライアントの広告アカウント・FBページ・IGビジネスアカウントを用意し、短期
   ユーザートークン（`ads_management,ads_read,business_management`、IG投稿には
   `instagram_business_content_publish` も）を取得 →
   `python scripts/meta_ads_cli.py connect --short-token <TOKEN> --ad-account-id <ID> --page-id <ID> --ig-user-id <ID>`
   （長期トークンに自動交換して保存。システムユーザートークンは `--system-token` でそのまま保存）。
3. **確認**: `whoami`（スコープ・失効）、`remote-accounts`（触れる広告アカウント一覧）。

> 自分（運営者）の広告アカウントは開発モード/標準アクセスで**審査前から動く**。
> 他社アカウントの運用には**ビジネス認証＋App Review（2〜4週間/権限ごと）**が必要。

## 出稿ワークフロー

1. **クリエイティブ準備**: 画像/動画は `creative-studio` / `media-gen` / `higgsfield-generate` で作る
   （このスキルは出稿のみ。生成はしない）。LP/フォームが要るなら `dry-test-launcher` → `build`。
2. **キャンペーン**: `campaign --name "..." --objective OUTCOME_TRAFFIC`（PAUSED で作成、`campaign_id` を得る）。
3. **広告セット**: `adset --campaign-id <ID> --name "..." --daily-budget 1000 --countries JP --optimization-goal LINK_CLICKS`
   （予算はアカウント通貨の単位。JPY なら円。詳細は [references/campaign-fields.md](references/campaign-fields.md)）。
4. **広告**: `ad --adset-id <ID> --name "..." --link <URL> --message "本文" --headline "見出し" --image <path> --cta LEARN_MORE`。
5. **承認 → 出稿**: 予算・期間を提示して承認を得る → `publish --campaign-id <ID> --confirm`。
6. **運用**: `insights --campaign-id <ID> --date-preset last_7d` で spend/CTR/CPA を取得 →
   改善 or `pause --campaign-id <ID>`（キルスイッチ）。

## Instagram オーガニック投稿

`ig-post --caption "本文" --image-url <公開URL> --confirm`（動画は `--video-url`、Reels として投稿）。
3ステップ（コンテナ作成→処理待ち→公開）は CLI 内部で処理。詳細は
[references/instagram-publishing.md](references/instagram-publishing.md)。要ビジネスアカウント・100投稿/24h・Reels≤90s。

## UX ルール

- 生 ID や JSON ダンプをチャットに垂れ流さない。要点（作成した campaign/adset/ad、予算、状態、成果）を簡潔に。
- 出力は全コマンド JSON（`ok`/`error`）。`needs_approval: true` が返ったら、それは「承認待ち」であり失敗ではない。
- エラー時は CLI が `detail`（Meta API の error payload）を返す。権限不足なら不足スコープ/審査要否を案内する。
- 平易な言葉で。専門用語（objective 名等）は必要時のみ、まず日本語で説明する。

## 関連スキル

- `dry-test-launcher` — 出稿前の仮説・LP・コピー・ターゲット設計（承認ゲートで止まる）。ドラフトをここに渡す。
- `creative-studio` / `media-gen` / `higgsfield-generate` — 広告クリエイティブ生成。
- `brand-asset-kit` — ブランド/商品アセットの準備。
- （未実装）Google Ads / TikTok Ads は同じ構造で横展開予定。
