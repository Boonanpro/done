---
name: amazon
description: >
  Amazonでの商品検索、カート操作、注文履歴確認を自動化する。
  ユーザーがAmazon、買い物、商品検索、カート追加、注文履歴、
  あとで買う、商品購入に言及した場合に使用する。
domain: amazon.co.jp
language: 日本語
updated: 2026-02-07
---

# Amazon スキル

Amazonでの商品検索、カート操作、注文履歴確認などのショッピング操作を自動化するスキル。

## 対象サイト

- **URL**: https://www.amazon.co.jp
- **言語**: 日本語

## 認証要件

ほとんどのアクションはログインが必要。未ログインでも検索は可能だが、カートに追加した商品はログイン後に保持されないことがある。

- **login不要**: search
- **login推奨**: add-to-cart（未ログインだとカート内容が保持されない場合あり）
- **login必須**: view-cart, save-for-later, view-order-history

認証情報は save_credentials ツールで保存・取得する。

## パラメータ一覧

| パラメータ | 型 | 必須 | 説明 | 使用アクション |
|-----------|-----|------|------|---------------|
| query | string | search時必須 | 検索キーワード | search |
| product_name | string | add-to-cart時推奨 | 追加する商品名 | add-to-cart |

## 実行フロー

### 基本フロー（検索→購入）

```
login → search → add-to-cart → view-cart
```

### カート確認のみ

```
login → view-cart
```

## ブラウザ操作の注意

- 操作には `browser_open`, `browser_click`, `browser_type`, `browser_scroll`, `browser_back` 等のツールを使用する
- 各ツール実行後にスクリーンショットと要素一覧（@e1, @e2...）が返される
- 要素をクリック/入力する際はref番号（例: @e3）で指定する
- 要素一覧からボタンやリンクのテキストを確認し、正しい要素を選択する

## ログイン状態の判定

- **未ログイン**: ナビゲーションバーに「こんにちは、ログイン」と表示
- **ログイン済み**: 「○○さん」とアカウント名が表示

## 注意事項

- ログイン後のページでは `browser_back` が予期せぬ動作を起こす可能性がある。明示的にURLを開く（`browser_open`）方が安全
- 検索結果には「カートに入れる」ボタンが多数存在する。商品名と画像で正しい商品を確認してから操作する

## Actions

| Action | Description | Requires | Doc |
|--------|-------------|----------|-----|
| login | Amazonにログインする | - | actions/login.md |
| search | キーワードで商品を検索する | - | actions/search.md |
| add-to-cart | 商品をカートに追加する | login推奨 | actions/add-to-cart.md |
| view-cart | カートの中身を確認する | login | actions/view-cart.md |
| save-for-later | カート内商品を「あとで買う」に移動する | login | actions/save-for-later.md |
| view-order-history | 注文履歴を確認する | login | actions/view-order-history.md |
