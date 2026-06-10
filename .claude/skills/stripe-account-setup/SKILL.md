---
name: stripe-account-setup
description: Create a brand-new, dedicated Stripe account for a business/project via the browser, end-to-end (signup, business onboarding, dashboard). Use when the user wants a separate Stripe account per business ("1事業=1アカウント"), a new payment account for a project, or to stop a new brand's checkout from showing a previous business's name. Covers the non-obvious bits: Stripe's random-password requirement, the Arkose image CAPTCHA that must be handed to a human, and choosing self-managed payments to avoid the +3.5% Managed Payments fee.
---

# Stripe Account Setup (new account per business)

Stand up a fresh, independent Stripe account so one brand's checkout page, card-statement descriptor, products and payouts are fully separated from other businesses. Built from the StyleUp account build (acct_1TgobiELXOqbGhZX, 2026-06-11).

## Why a new account (not a new product in an existing one)
The **business name + logo shown on the hosted Checkout page comes from account-level settings** — there is only one per account. So multiple brands cannot cleanly share one account (a leftover name like "yakyu" then shows on every checkout). One business = one Stripe account. Stripe allows many accounts; each is independent.

## Operating rules
- Register with the **brand's own email** (e.g. the project's Gmail) so the account is self-contained and email OTP is readable. Don't require the operator's existing-account password.
- **NEVER fabricate personal data.** Use the real account-representative name from saved personal info.
- Generate a **strong RANDOM password** — Stripe rejects anything with dictionary words, the brand name, or dates ("パスワードの強度が不足しています / 弱すぎる"). Use ~16+ mixed random chars, no real words. Save it with `save_credentials` (service e.g. `stripe_<brand>`, login_url `https://dashboard.stripe.com/login`).
- The browser runs on the user's own PC, so the user can see and take over for CAPTCHAs.

## Workflow

### 1. Open registration
- `open_target https://dashboard.stripe.com/` → it redirects to login. Click **「Stripe アカウントを作成」** (register link) to reach `dashboard.stripe.com/register`. (Do NOT try to log into an existing account — we want a new one.)

### 2. Fill the signup form
- メール = brand email, 氏名 = real representative name, 国 = 日本.
- パスワード = strong random string. If it shows 「弱すぎる」, the button stays disabled — replace with a more random one (clear via native-setter evaluate, retype).
- Click 「アカウントを作成」.

### 3. ⚠️ Arkose CAPTCHA — HAND OFF TO THE HUMAN
- An **Arkose FunCaptcha** appears (image-select like "表示されているコンテナに収まるものをすべてクリック", or drag-puzzle "左側の図形を、はまる場所にドラッグしてください"). It lives in a **cross-origin iframe** — the puzzle images are NOT exposed as `@eN` refs, so they can't be clicked reliably by automation. `browser(action="solve_captcha")` does NOT work on Arkose ("captchaは検出されませんでした").
- **Do not gamble** (wrong attempts can block the not-yet-created account). Keep the browser open, tell the user the exact on-screen instruction, and ask them to solve it on their PC and say "いけた". Then continue.
- If it times out and the submit button hangs on a spinner, reload `dashboard.stripe.com/register`, re-fill, and resubmit so a fresh puzzle appears for the user to solve live.

### 4. Business onboarding (multi-step wizard)
1. ビジネス名 = brand (e.g. "StyleUp"), 企業の所在地 = 日本 → 続ける. (This name becomes the public business name.)
2. ウェブサイト + ビジネス内容 → 続行 (helps Stripe pre-config; fill honestly).
3. 「グローバル販売は誰が担当すべきですか？」 → choose **「自分で管理」(self-handle)**, NOT the recommended Managed Payments — Managed Payments adds **+3.5% per transaction**. For a domestic small subscription you don't need Stripe to handle global tax/VAT. → 続行.
4. Suggested products (継続課金 / Invoicing / 税金回収) → keep 継続課金 (subscriptions) and 続行.
5. 設定方法 → 「ダッシュボードで設定」 → 続行 → 「サンドボックスに移動」.

### 5. You're in the dashboard
- The account opens in **sandbox/test** mode. Home page shows **test API keys**: `pk_test_...` and `sk_test_...` (also under 開発者 / API キー). Account id is `acct_...`.
- Save the login immediately (`save_credentials`).

## After creation — what still needs doing
- **Email verification** (設定を完了する → メールアドレスを確認する): a verify link is emailed to the brand inbox.
- **Activation for LIVE payments** (事業を確認する): requires business details + **a bank account for payouts** + identity. Bank/identity is sensitive — get it from the user; don't invent it. Until activated, only `sk_test_`/`pk_test_` work (no real charges).
- **Wire into DAN**: DAN's existing Stripe integration (`app/tools/publish_site/stripe_payments.py`) uses ONE operator key (`service="stripe"`, `OPERATOR_USER_ID`). For per-business accounts, store each account's key under its own credential (e.g. `stripe_<brand>`) and select by project, rather than reusing the single operator key.

## Pitfalls
- Weak password → silent disabled button. Always use random chars.
- Arkose CAPTCHA is the only true human-only step — everything else (email OTP, phone) you can do. Don't burn attempts on it.
- Test vs live: a freshly created account is test-only until activated; don't promise real charges before activation + bank setup.
