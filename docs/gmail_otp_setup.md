# Gmail OTP自動取得セットアップガイド

SmartEX予約購入の完全自動化（OTP認証含む）を実現するための設定手順。

## アーキテクチャ

```
[SmartEX] --SMS OTP--> [楽天モバイル 07083524060]
                              |
                              v
                     [SMS Forwarder (Android)]
                              |
                              v
                     [Gmail: 0aw325171@gmail.com]
                              |
                              v
                        [Dan - OTP自動抽出]
```

## 前提条件

- ✅ Android端末（楽天モバイル 07083524060）
- ✅ Gmailアカウント（0aw325171@gmail.com）
- ✅ SmartEX設定でOTP受信方法を「SMS」に変更済み

## セットアップ手順

### 1. SMS Forwarderのインストール（Android）

1. Google Playストアで「SMS Forwarder」を検索
2. アプリをインストール（開発者: Zerogic Inc.推奨）
3. 必要な権限を許可：
   - SMS読み取り権限
   - バックグラウンド実行権限

### 2. SMS転送設定

1. SMS Forwarderアプリを開く
2. 「新しいルール」を作成：
   - **フィルター**: キーワード「スマートEX」または「SafeKey」
   - **転送先**: Gmail (`0aw325171@gmail.com`)
   - **転送方法**: Gmail経由（Googleアカウントでサインイン）
3. ルールを有効化
4. テスト送信で動作確認

### 3. Gmailアプリパスワード設定

1. ブラウザで https://myaccount.google.com/apppasswords にアクセス
2. 0aw325171@gmail.com でログイン
3. アプリパスワードを作成：
   - アプリ名: "Dan SMS OTP"
4. 生成された16文字のパスワードをコピー
5. `.env`ファイルに追加：

```bash
GMAIL_APP_PASSWORD=abcd efgh ijkl mnop
```

### 4. 動作確認

#### テスト1: Gmail OTP取得スクリプト

```bash
# 自分の番号からテストSMSを送信
# 内容: 「テスト ワンタイムパスワード:123456」

# OTP取得テスト
python scripts/get_sms_otp_from_gmail.py

# 期待される出力:
# [SUCCESS] OTP detected: 123456
```

#### テスト2: EXログイン統合テスト

```bash
python scripts/test_gmail_otp_integration.py

# 期待される動作:
# 1. EXログイン画面表示
# 2. OTP発信
# 3. Gmail経由で自動OTP取得
# 4. ログイン完了
```

## 使用方法

### 完全自動化での予約購入

```bash
python scripts/buy_tokyo_osaka_jan30.py
```

**実行フロー**:
1. EXにログイン
2. （OTP必要な場合）Gmail経由で自動取得
3. 列車検索・選択
4. 座席選択
5. 購入実行
6. （3DS認証）Gmail経由でOTP自動取得
7. 購入完了

**ユーザーの操作**: なし（完全自動）

## トラブルシューティング

### OTPが取得できない

**症状**: `[TIMEOUT] OTPが見つかりませんでした`

**確認項目**:
1. SMS ForwarderがAndroidでバックグラウンド実行中か
2. Gmail転送が正常に動作しているか（Gmailを開いて確認）
3. `.env`の`GMAIL_APP_PASSWORD`が正しいか
4. SMSが実際に届いているか（Android標準メッセージアプリで確認）

**解決方法**:
```bash
# 受信トレイ確認
python scripts/check_gmail_inbox.py

# 最新10件のメールをチェック
# [SMSFW]メールが届いているか確認
```

### Gmail IMAP接続エラー

**症状**: `IMAP error: authentication failed`

**原因**:
- Gmailアプリパスワードが間違っている
- 2段階認証が無効化されている
- IMAPが無効になっている

**解決方法**:
1. https://mail.google.com/mail/u/0/#settings/fwdandpop でIMAP有効化
2. アプリパスワードを再発行
3. `.env`を更新

### SMS転送が届かない

**症状**: SMS ForwarderからGmailにメールが届かない

**確認項目**:
1. SMS Forwarderの転送ルールが有効か
2. Googleアカウント連携が切れていないか
3. 転送先アドレスが正しいか

**解決方法**:
- SMS Forwarderアプリで「テスト送信」を実行
- ログを確認してエラーメッセージを特定
- 必要に応じてGoogleアカウント再認証

## セキュリティ注意事項

1. **Gmailアプリパスワード**:
   - `.env`ファイルをGitにコミットしない
   - 定期的に再発行を推奨

2. **SMS転送**:
   - SMS Forwarderは信頼できるアプリのみ使用
   - 不要なメッセージは転送しない（フィルター設定）

3. **OTP有効期限**:
   - OTPは通常5分で失効
   - 取得後すぐに使用すること

## 実装詳細

### ファイル構成

```
app/utils/gmail_otp_helper.py
  - get_sms_otp_from_gmail()      # 同期版
  - get_sms_otp_from_gmail_async() # 非同期版

scripts/get_sms_otp_from_gmail.py
  - スタンドアロンテストスクリプト

scripts/test_gmail_otp_integration.py
  - EXログイン統合テスト

scripts/buy_tokyo_osaka_jan30.py
  - 完全自動化購入スクリプト
  - get_otp_from_gmail() コールバック関数
```

### OTP検出パターン

優先度順:
1. `ワンタイムパスワード[:：\s]*(\d{4,8})` - SmartEX専用
2. `(?:SafeKey|safekey)[:：\s]*(\d{4,8})` - SafeKey（3DS）
3. `(?:認証コード|OTP)[:：\s]*(\d{4,8})` - 一般的なパターン
4. `(?<![\d.])\b(\d{6})\b(?![\d.])` - 6桁の数字（汎用）

### フォールバック

OTP自動取得が失敗した場合、自動的に手動入力モードに切り替わります:
```python
# 2分間タイムアウト後
print("フォールバック: 手動入力")
otp_code = input("OTP (6桁): ").strip()
```

## 今後の改善案

1. **リアルタイム通知**: Gmail PubSubでPUSH通知対応
2. **複数サービス対応**: Amazon、楽天などのOTPも自動化
3. **音声OTP**: Twilio番号での音声OTP取得統合
4. **Webhook対応**: ngrok使用でWebhook受信

## 関連ドキュメント

- [Phase 9: OTP自動化](./phase9_otp_automation.md)
- [Phase 9C: 音声OTP取得](./phase9c_voice_otp.md)
- [EX予約エクスキューター](./architecture_v2_executor_flow.md)
