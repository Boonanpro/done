---
name: line-official-account-setup
description: Create and fully configure a LINE Official Account (LINE公式アカウント) for a project — open the account, pass SMS verification, set the greeting (あいさつ) message with a link, and build a rich menu (リッチメニュー). Use when the user wants a LINE official account, a LINE receptacle/funnel for a project, a friend-add link, an auto-reply on friend-add, a rich menu, or "プロジェクトごとにLINEを作る". Covers the non-obvious trick that the rich-menu image must be set via the Messaging API, not the browser uploader.
---

# LINE Official Account Setup

End-to-end playbook for standing up a LINE Official Account (公式アカウント) as a project receptacle: open it, verify, set the friend-add greeting message, and publish a rich menu. Built from the スタイルアップ build (2026-06-01).

## Operating Rules

- Account name and owner name are set by the user. Confirm the アカウント名 before creating.
- The account lives under a **LINE Business ID** (email-based login), NOT the user's personal LINE login. Record which email/Business ID owns it (e.g. memory + credentials).
- SMS verification (電話番号認証) is required to create an account under an existing Business ID. Ask the user for the phone number; do not invent one. Save it to personal info once given.
- Reuse the existing logged-in browser session. Start at the destination (manager.line.biz), not a login page. Log in only if redirected to an unauthenticated page.
- ⚠️ **ログイン方式は必ず「ビジネスアカウントでログイン」（メール＋パスワード, `account.line.biz`）を選ぶ。** 「LINEアカウントでログイン」（個人LINE, `access.line.me/oauth2/...`）は**絶対に選ばない** — そちらは別アカウント種別で、歪んだ文字の画像認証＋reCAPTCHA Enterprise の bot 検知地獄に突っ込み、ログインできずループする。URLが `access.line.me` に飛んだら入口を間違えている。
- ⚠️ **ログイン認証情報は `get_credentials(service="line")` で取得する。** 同じメール（例 `shub6923@gmail.com`）が `google_shub` / `gmail_shub6923` など別サービスにも保存されており**パスワードが異なる**。メールアドレスで推測して別記録を引くと違うパスワードを使ってログイン失敗する（実際に発生済み）。
- 画像認証(CAPTCHA)が出たら自分の目で読まず `browser(action="solve_captcha")` を使う。ただし上記の正しいビジネスアカウント経路なら通常CAPTCHAは出ない。
- Do not hand browser/auth steps to the user unless genuinely impossible (e.g. reading an OTP only the user's device/inbox has).
- Red-zone (account creation, enabling developer features, sending money) → proceed only with user approval. Enabling Messaging API is a real, free, reversible account feature — get a quick OK before enabling.

## Key URLs

- Manager home for an account: `https://manager.line.biz/account/<basicId>/` (e.g. `@541xhrev`)
- Create account flow: from アカウントリスト → 「LINE公式アカウントを作成」 → `https://entry.line.biz/form/entry/unverified`
- Greeting message: left nav トークルーム管理 → あいさつメッセージ (`/account/<id>/autoresponse/welcome`)
- Rich menu: トークルーム管理 → リッチメニュー (`/account/<id>/richmenu`)
- Messaging API settings: 設定 → Messaging API (`/account/<id>/setting/messaging-api`)
- Business ID settings (name/email/password/LINE-link): avatar menu (top-right name) → ビジネスID設定 → `https://account.line.biz/profile`
- Friend-add link to give out: `https://line.me/R/ti/p/<basicId>` (e.g. `https://line.me/R/ti/p/@541xhrev`)

## Workflow

### 1. Open the account
1. `manager.line.biz` → アカウントリスト → 「LINE公式アカウントを作成」.
2. Fill: アカウント名 (user-chosen), メールアドレス (the Business ID email), 所在国=日本, 業種 (大/小 — select via JS if the MCP `select` action times out; see Pitfalls), 運用目的 (check at least one), 主な使い方 (radio), ビジネスマネージャーの組織=作成.
3. 確認 → 完了. A reCAPTCHA is solved automatically. Agree to the two 情報利用 consent screens. Skip 認証リクエスト ("あとで認証を行う") — an unverified account is fine for a dry test.

### 2. SMS verification (電話番号認証)
1. On 「SMS認証を行う」, enter the user's phone number, send once.
2. Auto-fill the code with `browser(action="wait_for_otp_from_app", ref=<code field>, press_enter=false, timeout_seconds=30)` — the Android APK forwards the OTP without exposing it. Then click 確認する.
3. If the page reset and the code field is gone, the code is dead — re-send once and wait again. If no OTP arrives, keep the page open and ask the user for the code; never close the browser or spam re-send (Akamai/CAPTCHA risk).

### 3. Greeting message (あいさつメッセージ)
1. Open あいさつメッセージ. Close the テンプレート modal.
2. Click into the editor (a custom `<rich-textarea>`). Clear the default text: focus it, `document.execCommand('selectAll'); document.execCommand('delete')`.
3. Insert the message with `document.execCommand('insertText', false, msg)` (newlines OK). Put the tool URL on its own line so LINE auto-links it.
4. 変更を保存 → 保存. Verify the toast 「保存しました」.

### 4. Rich menu (リッチメニュー) — IMPORTANT: image goes via Messaging API
The manager's rich-menu image uploader (`#image-creator-upload`) opens a native file chooser the browser tool cannot fill, and the in-app image editor can't place text precisely via automation. **Build the image locally, then push it via the Messaging API.**

1. **Design the image** (exact template size, e.g. 小=2500×843 single-area). Use PIL with a Japanese font (`C:/Windows/Fonts/YuGothB.ttc`, `meiryo.ttc`). Save PNG. Verify by downscaling and Reading the preview.
2. **Enable Messaging API**: 設定 → Messaging API → 利用する → register developer info (name + email) → create/select a プロバイダー → agree. Grab **Channel ID** and **Channel secret** from the page. Save them via `save_credentials` (service e.g. `line_messaging_api_<slug>`), never in plaintext memory.
3. **Issue a channel access token** (no console needed):
   ```bash
   curl -s -X POST https://api.line.me/v2/oauth/accessToken \
     -H "Content-Type: application/x-www-form-urlencoded" \
     --data-urlencode "grant_type=client_credentials" \
     --data-urlencode "client_id=<ChannelID>" \
     --data-urlencode "client_secret=<ChannelSecret>"
   ```
4. **Create rich menu** (POST `https://api.line.me/v2/bot/richmenu`, JSON): `size {width,height}`, `selected:true`, `name`, `chatBarText`, `areas:[{bounds, action:{type:"uri", uri:<tool URL>}}]`. → returns `richMenuId`.
5. **Upload the image**: POST `https://api-data.line.me/v2/bot/richmenu/<id>/content` with `Content-Type: image/png`, `--data-binary @image.png`. Expect HTTP 200 `{}`.
6. **Set as default for all users**: POST `https://api.line.me/v2/bot/user/all/richmenu/<id>`. Expect 200.
7. **Verify**: GET `/v2/bot/user/all/richmenu` (default id), GET `/v2/bot/richmenu/<id>` (detail), GET the image content (200, image/png, size matches).

Note: rich menus set via Messaging API do NOT appear in the manager's rich-menu list — that's expected; they still show to users.

### 5. Friend-add link & access
- Give out `https://line.me/R/ti/p/<basicId>` as the funnel receptacle link. Verify it opens (shows QR / "友だち追加").
- The dashboard is reachable only via the owning Business ID (email login), not the user's personal LINE login. To let the user in on their own device, either (a) reset the password via `account.line.biz/profile` (reset link goes to the Business ID email — only the user can read it), or (b) link their personal LINE account (LINEアカウント 未連携 → 連携), after which their LINE login shows the account. Changing the password from the profile requires the *current* password, which is unknown if it was system-generated — use reset instead.

## Pitfalls

- MCP `browser(action="select")` on this site often times out. Set `<select>` values via `evaluate`: find the select, set `.value` via the native setter, dispatch `input`+`change`. Pick options by visible text.
- The site reloads/blanks intermittently (about:blank). Re-open the target URL and continue; the session persists.
- Cookie copying to a side profile fails (Chrome App-Bound Encryption) — do NOT try to run a second Playwright on a copied profile to upload files; use the Messaging API instead.
- Channel access token from `client_credentials` is valid ~30 days; re-issue from the saved Channel ID + secret when needed.

## Future automation (same token)
The Messaging API token also enables step messages, reminders, and broadcast pushes (e.g. pre-payment reminders) — the foundation for the dry-test funnel automation.
