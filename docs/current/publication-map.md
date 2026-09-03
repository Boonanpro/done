# 公開の地図 — 第1章

この文書は「いま、どのサイトがどこから公開されているか」を読むための地図です。
公開の動作を変えるものではありません。

## まず三つの言葉

### Git

Git はサイトの**設計図の履歴帳**です。ファイルを保存し、いつ誰が何を変更したかを記録します。
GitHub はその履歴帳をネット上に置く場所です。Git/GitHub 自体は、サイトをお客さまへ表示しません。

### Vercel

Vercel は設計図からサイトを組み立て、インターネットへ配る**建設会社兼配達所**です。
Vercel が組み立てた一回分を「デプロイ」と呼びます。URL を開いた人が見るのは、Git ではなく Vercel のデプロイです。

### DNS

DNS はドメイン名の**住所録**です。
`paina.info` を開こうとしたとき、DNS が「この名前はどのサーバーへ行くか」を案内します。
住所録が古いと、Vercel に正しいサイトがあっても、訪問者はそこへ到達できません。

## 現在の公開の登場人物

| 役割 | 現在のもの | 意味 |
| --- | --- | --- |
| ダン本体のコード | `D:\done` / GitHub `Boonanpro/done` | ダン画面、公開機能、吉川特装を含むフロントエンドの設計図 |
| 成果物用コード | `D:\done-artifacts` / GitHub `Boonanpro/done-artifacts` | 成果物の一部を届けるための別の設計図 |
| ダン本体のVercel | `frontend` プロジェクト | ダン画面と、同居する成果物を配る場所 |
| 成果物用Vercel | `done-artifacts` プロジェクト | `*-done.vercel.app` 系の成果物を配る場所 |
| ドメイン管理 | Cloudflare Registrar / Name.com | ドメインの購入とDNS設定を担当する会社 |

## URL の役割

| URLの種類 | 例 | 誰のためか | 本番か |
| --- | --- | --- | --- |
| ダンの管理画面 | `frontend-mikis-projects-86652663.vercel.app` | 運営者 | いいえ |
| 編集プレビュー | `/preview/<slug>` | 制作者 | いいえ |
| 成果物URL | `denki-knowledge-done.vercel.app` | 確認・納品用 | 独自ドメイン前の公開URL |
| 独自ドメイン | `paina.info` / `kikkawatokuso.com` | 一般の訪問者 | はい |

## いま確認できた状態

### 電管ナレッジ

`https://denki-knowledge-done.vercel.app/` は公開されており、HTTP 200 で応答しています。
「公開しない設定」ではありません。これは独自ドメインを付ける前の成果物公開URLです。

### paina.info

Vercel は `paina.info` を `done-artifacts` プロジェクトに結び付けています。しかしDNSはVercelが求める `76.76.21.21` ではなく、別の `18.204.152.241` を指しています。
そのため、Vercelに建物があっても、DNSの住所録が別の場所を案内している状態です。

### 吉川特装

現在は `kittoku.vercel.app` が仮の公開先です。ドメイン購入・DNS・Vercel接続が完了した後に、`kikkawatokuso.com` が本番URLになります。

## GitHub が止まると何が止まるか

現在の自動処理は、GitHub の `main` を定期的に確認し、変更があればPCへ取り込みます。成果物の公開でもGitHubへのpushを使い、Vercelの自動ビルドを起動します。

したがってGitHubが止まると、**新しい版をGitHub経由で公開する道**が止まります。すでにVercelへ完成しているサイトが直ちに消えるわけではありません。

第4章以降では、この依存を「Gitは設計図の正本、Vercelの不変デプロイが本番」という形に整理します。

## 次章で決めること

第2章では、編集プレビュー・納品確認URL・本番URLを、どの画面で誰に見せるかを固定します。
