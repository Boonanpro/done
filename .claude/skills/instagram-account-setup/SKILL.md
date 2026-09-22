---
name: instagram-account-setup
description: "Create and configure an Instagram account when account setup is requested."
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
- If using phone: `wait_for_otp_from_app` (default sms). SMS can take minutes to arrive; the tool waits up to the code's validity (default 300s) — do not ask the user for the code before that. If the code died, resend once.

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

### 4. Profile icon — design it properly, then fill `<input type=file>` IN-BROWSER (no OS dialog)
⚠️ Do NOT ship a quick PIL text box — it looks cheap and got rejected ("くそダサい"). Make a real designed icon.
- **Get the brand color from the actual product, don't guess.** Open the tool/artifact and sample it: `getComputedStyle(el).backgroundImage` on the header to read the exact gradient (StyleUp = `linear-gradient(#E8607F → #C8587A)`, rose pink). Using an invented purple was a real mistake.
- **Generate the icon with media-gen / AI image** (OpenAI GPT Image). Prompt a premium rounded-square app icon: brand-color gradient bg + a clean white emblem (e.g. hair scissors + sparkle), flat vector, no text, reads well in a circle. Direct call works: `POST https://api.openai.com/v1/images/generations` with `OPENAI_API_KEY` + `IMAGE_GENERATION_MODEL` from `.env`, `size 1024x1024`, `quality high`, take `data[0].b64_json`. Review a downscaled preview before uploading.

Upload (the 写真を変更 button opens an OS chooser the MCP browser can't drive, but the page has hidden `input[type=file]`):
1. Compress for transport: resize ~256px, JPEG → base64.
2. ⚠️ **A single `evaluate` expression truncates around ~4200 chars.** For anything bigger, **chunk the base64**: first `evaluate` sets `window.__b64="<chunk>"`, then append more with `window.__b64+="<chunk>"`, each returning `window.__b64.length` so you VERIFY the running total. To avoid hand-assembly errors, compute exact substrings with Bash (`b[4200:]`) rather than eyeballing chunk boundaries.
3. Build + inject (handle BOTH file inputs; IG has 2):
   ```js
   const bin=atob(window.__b64);const a=new Uint8Array(bin.length);
   for(let i=0;i<bin.length;i++)a[i]=bin.charCodeAt(i);
   const f=new File([a],'icon.jpg',{type:'image/jpeg'});
   const dt=new DataTransfer();dt.items.add(f);
   [...document.querySelectorAll('input[type=file]')].forEach(inp=>{
     inp.files=dt.files;inp.dispatchEvent(new Event('change',{bubbles:true}));});
   return inp.files[0].size; // must equal the real file size
   ```
4. IG web applies the avatar immediately on file selection (no separate save; the left-nav avatar updates). No cropper on web. Reload the profile to confirm.

### 5. Convert to professional (business) account
- 設定 → アカウントの種類とツール → 「プロアカウントに切り替える」 → choose **ビジネス** (for a tool/service/brand) → 次へ → カテゴリ select (e.g. 商品・サービス) → 完了 → 「次へ」 confirm → on 連絡先情報の確認, click **「連絡先情報を使用しない」** (don't publish personal contact) → 完了.
- Result: insights/analytics + ads eligibility unlocked.

## Pitfalls
- The MCP `select`/`click` by `@eN` ref sometimes times out on instagram.com; set `<select>`/`<input>` values via `evaluate` (native setter + dispatch input/change), and click options by ref after the dropdown opens.
- Pages briefly blank/reload (about:blank); re-open the target URL and continue — the session persists.
- TikTok is much more aggressive than IG on automated signup; expect CAPTCHA (`browser(action="solve_captcha")`) and possible phone verification.

## After setup
Hand the user: profile URL `instagram.com/<handle>`, username, login email, password. The website-link in bio still needs to be added from their phone app. Then proceed to content (studio/media-gen) and posting.
