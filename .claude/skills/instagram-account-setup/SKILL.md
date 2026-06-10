---
name: instagram-account-setup
description: Create and fully build out an Instagram account for a project — open the account, pass email/SMS verification, set username, bio, profile icon, and convert to a professional (business) account. Use when the user wants a new Instagram account for a brand/project, an IG presence, or "プロジェクトのインスタを作って". Covers the non-obvious tricks: in-browser file-input injection for the icon (no OS dialog), email-OTP signup, and username availability checking via the Accounts Center.
---

# Instagram Account Setup

End-to-end playbook for standing up a brand Instagram account and building the profile. Built from the スタイルアップ (@styleup_jp) build (2026-06-10).

## Operating Rules

- **NEVER fabricate personal data.** Birthday, real name, etc. must come from the user (saved personal info) — if unknown, ASK first. Do not invent a placeholder DOB to get past a required field. (Burned once: a made-up 1995/6/15 birthday.)
- Account name, username, and bio wording are the user's brand choices. Confirm username and bio direction before committing; don't change identity unilaterally.
- Reuse the existing logged-in browser session; start at the destination page. Only one clean signup attempt — IG/Meta bot-detection punishes repeated rapid signups.
- Do NOT publish the user's personal phone/address as public business contact info unless they ask. Use 「連絡先情報を使用しない」 in the pro-account flow.
- Save the login to credentials (`save_credentials`, service e.g. `instagram_<slug>`). Username may change; email login stays valid.

## Verification method (decide first)

- **Prefer EMAIL signup** over phone. Email OTP is readable via `browser(action="wait_for_otp_from_app", source="email", email_address="<inbox>")` **if that inbox has an app password set** (if not, the tool returns one-time setup guidance to relay). Phone SMS via the Android APK forwarding sometimes fails to forward — email is more reliable.
- If using phone: `wait_for_otp_from_app` (default sms). If it doesn't arrive in ~60s, ask the user for the code; the SMS challenge screen resets if you wait too long (code dies → resend once).

## Workflow

### 1. Create the account
1. Open `https://www.instagram.com/accounts/emailsignup/`.
2. Fill: 連絡先 (email — use the project email), パスワード (generate strong; save later), 名前 (display name), ユーザーネーム.
3. **Birthday**: open the 年/月/日 comboboxes one by one (click the combobox `div[role=combobox]`, then click the option `div[role=option]`). Use the **user's real DOB** from saved personal info.
4. **Username field is a `<input type=search role=combobox>`.** Set it via JS (native setter + `input` event), then **click the field once** to trigger the async availability check. Green check = available; the 送信 button enables. If it shows 「○○というユーザーネームは使用できません」 it's taken — try another.
5. Click 送信 → reCAPTCHA may auto-pass → email/SMS verification screen.
6. Enter the OTP (see above) → 次へ. Dismiss the 「お知らせをオンにする」 popup with 後で.

### 2. Username availability / change (after creation)
- Quick availability probe: visit `instagram.com/<handle>`. 「ページが見つかりません」 = free; a real profile = taken; 「このページはご利用いただけません」 = ambiguous (could be a disabled account holding it) — confirm in the change form.
- Change username: `accountscenter.instagram.com/profiles/` → click the profile → ユーザーネーム → set value via JS (native setter + input) → **click the field to validate** → green check → 完了. (The web "プロフィールを編集" page has NO username field; it's in Accounts Center.)

### 3. Bio (自己紹介)
- `instagram.com/accounts/edit/` → 自己紹介 textarea → type → 送信する. Max 150 chars.
- ⚠️ The **website link is mobile-app-only on web** ("リンクはモバイルデバイスからのみ編集できます"). Hand the link to the user to add via their phone, or set it via the app later.

### 4. Profile icon — fill `<input type=file>` IN-BROWSER (no OS dialog)
The 写真を変更 button opens an OS file chooser the MCP browser can't drive, but the page has hidden `input[type=file]` (accept image/jpeg,image/png). Inject in-page:
1. Build the icon with PIL (logo on solid brand square). **Keep base64 SMALL: ~300px, palette-quantized (`convert("P", colors=4)`) → ~2KB file → ~2.6KB base64.** A base64 string over ~4.5KB gets **truncated mid-`evaluate`-expression → SyntaxError**. Verify by Reading the `.b64` file fully.
2. Inject:
   ```js
   const bin=atob(b64);const a=new Uint8Array(bin.length);
   for(let i=0;i<bin.length;i++)a[i]=bin.charCodeAt(i);
   const f=new File([a],'icon.png',{type:'image/png'});
   const dt=new DataTransfer();dt.items.add(f);
   const inp=document.querySelector('input[type=file]');inp.files=dt.files;
   inp.dispatchEvent(new Event('change',{bubbles:true}));
   return inp.files[0].size; // must equal the real PNG size
   ```
3. IG web applies the avatar immediately on file selection (no separate save; the left-nav avatar updates). No cropper on web.

### 5. Convert to professional (business) account
- 設定 → アカウントの種類とツール → 「プロアカウントに切り替える」 → choose **ビジネス** (for a tool/service/brand) → 次へ → カテゴリ select (e.g. 商品・サービス) → 完了 → 「次へ」 confirm → on 連絡先情報の確認, click **「連絡先情報を使用しない」** (don't publish personal contact) → 完了.
- Result: insights/analytics + ads eligibility unlocked.

## Pitfalls
- The MCP `select`/`click` by `@eN` ref sometimes times out on instagram.com; set `<select>`/`<input>` values via `evaluate` (native setter + dispatch input/change), and click options by ref after the dropdown opens.
- Pages briefly blank/reload (about:blank); re-open the target URL and continue — the session persists.
- TikTok is much more aggressive than IG on automated signup; expect CAPTCHA (`browser(action="solve_captcha")`) and possible phone verification.

## After setup
Hand the user: profile URL `instagram.com/<handle>`, username, login email, password. The website-link in bio still needs to be added from their phone app. Then proceed to content (studio/media-gen) and posting.
