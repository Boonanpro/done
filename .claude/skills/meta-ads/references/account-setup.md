# Meta Ads アカウントセットアップ（マルチテナント）

公式 UI は変わりやすい。クリック名はその場で `browser` ツールのライブ DOM で確認すること
（このファイルは手順の地図であって、焼き込みセレクタではない）。

## 全体像

```
[運営者：1回だけ]                         [テナントごと：クライアント数だけ]
Meta Developer App 作成                    クライアントの広告アカウント/Page/IG を用意
 → Marketing API 追加                       → ユーザートークン取得（必要スコープ）
 → App ID / App Secret                      → connect で長期トークン化して保存
 → connect-app で保存                        → whoami / remote-accounts で確認
 → (他社運用なら) ビジネス認証 + App Review
```

## A. 運営者 App（1回だけ）

1. https://developers.facebook.com/ → マイアプリ → アプリを作成。タイプは「ビジネス」。
2. アプリに **Marketing API** プロダクトを追加。
3. 設定 → ベーシック で **アプリ ID** と **app secret** を取得。
4. 保存:
   ```bash
   python scripts/meta_ads_cli.py connect-app --app-id <APP_ID> --app-secret <APP_SECRET>
   ```
   または環境変数 `META_APP_ID` / `META_APP_SECRET`（設定時はそちらが最優先）。

### 標準アクセス vs Advanced（App Review）

- **運営者自身**の広告アカウント・自分が管理者の Page/IG は、**開発モード/標準アクセスのまま動く**
  （`ads_management` 等は自分の資産に対してはレビュー前から使える）。→ まずここで実働検証。
- **第三者（クライアント）の資産**を運用するには:
  - **ビジネス認証**（Meta Business で会社情報・書類）
  - **App Review**（`ads_management` / `business_management` / `instagram_business_content_publish` など、
    **権限ごとにスクリーンキャスト付きで申請**。審査 **2〜4週間**）
  - 承認後、各クライアントが OAuth でこのアプリに権限付与 → そのトークンを `connect` で保存。

## B. テナント（クライアント）接続

### 必要なもの

- クライアントの **広告アカウント ID**（Ads Manager。`act_` の後ろの数値）
- 広告クリエイティブを出す **Facebook ページ ID**
- （任意・IG配置/IG投稿する場合）**Instagram ビジネスアカウントの IG User ID**（FBページに連携済み）
- 上記に対する権限を持つ **ユーザーアクセストークン**

### スコープ（権限）

| 用途 | 必要スコープ |
|---|---|
| 広告の作成・出稿・運用 | `ads_management`, `ads_read`, `business_management` |
| Instagram オーガニック投稿 | `instagram_business_basic`, `instagram_business_content_publish`, `pages_show_list` |

> 旧名 `instagram_basic` / `instagram_content_publish` は 2025-01-27 に廃止。新名称を使う。

### トークンの取り方（2通り）

1. **短期ユーザートークン**（検証・小規模向け）: Graph API Explorer か自前 OAuth で取得 →
   ```bash
   python scripts/meta_ads_cli.py connect \
     --short-token <SHORT_TOKEN> \
     --ad-account-id <AD_ACCOUNT_ID> --page-id <PAGE_ID> --ig-user-id <IG_USER_ID>
   ```
   CLI が `fb_exchange_token` で**長期トークン（約60日）**に交換して保存する。
2. **システムユーザートークン**（本番・無期限、推奨）: Business Settings → システムユーザー →
   トークン生成（対象アプリ＋スコープ＋資産割当） →
   ```bash
   python scripts/meta_ads_cli.py connect --system-token <SYSTEM_TOKEN> --ad-account-id <ID> --page-id <ID> --ig-user-id <ID>
   ```

複数クライアントは `--account <label>`（例 `--account kittoku`）で分けて保存・切替。

### 確認

```bash
python scripts/meta_ads_cli.py whoami            # スコープ・失効日・紐づくID
python scripts/meta_ads_cli.py remote-accounts   # トークンが触れる広告アカウント一覧
python scripts/meta_ads_cli.py accounts          # ローカル保存済みの接続一覧
```

## ハマりどころ

- **ページ未指定だと広告クリエイティブが作れない**（`page_id` 必須）。connect 時に渡す。
- IG 配置や IG 投稿には IG ビジネスアカウントが FB ページに連携済みである必要がある。
- トークン失効: 長期ユーザートークンは約60日。本番はシステムユーザートークン（無期限）にする。
- 広告アカウントに**支払い方法**が未設定だと publish で課金エラー。Ads Manager の支払い設定で
  クライアント本人がカード等を登録する（カード番号をチャット/ファイルに保存しない）。
- `special_ad_categories`: 住宅・雇用・信用・社会問題/選挙系は申告必須（`campaign --special-ad-categories '["HOUSING"]'`）。
