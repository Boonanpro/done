# Ad Account Setup Notes

Use this when the user wants end-to-end ad launch preparation, including account creation, billing readiness, and campaign drafts. Prefer official platform UIs. Verify current UI labels before relying on exact click names.

## Hard Rules

- Stop before publish, submit, launch, boost, or any action that can begin spend.
- Do not ask for or store full card numbers, CVV, account passwords, or 2FA codes in chat/files.
- For card/payment entry, navigate to the official payment screen and ask the human to type details directly.
- Before launch approval, summarize: platform, account, page/profile, payment readiness, campaign objective, audience, budget, schedule, ads, destination URL, UTM, and kill criteria.
- If a platform requires identity/business verification, pause and ask the human to complete that official flow.

## Meta / Instagram

Use for Instagram-first beauty and visual service tests.

Readiness checklist:
- Meta/Facebook login works.
- Business Portfolio or ad account exists, or setup flow can be started.
- Facebook Page and Instagram account are available/connected if needed.
- Ads Manager can create a campaign.
- Payment method exists, or billing setup can be opened.

Setup flow:
1. Open Meta Business Suite or Ads Manager.
2. Confirm the selected business/ad account.
3. If no ad account exists, start the official ad account creation flow.
4. Confirm Page and Instagram identity for the ad.
5. Open Billing/Payment settings if no payment method is present.
6. Ask the human to enter card/payment details directly on the official screen.
7. Build campaign/ad set/ad draft:
   - objective: leads, traffic, or messages for early dry tests
   - placement: Instagram Feed/Reels/Stories unless creative does not fit
   - daily/lifetime budget: match the approved cap
   - destination: LP/form URL with UTM
8. Stop before publish/review submission.

Official reference: Meta Help says first-time ad creation prompts adding a payment method before publishing the first ad.

## TikTok

Use when the offer can be shown as a short process demo.

Readiness checklist:
- TikTok Ads Manager login works.
- Ads Manager or Business Center account exists.
- Correct role exists for payment changes if using Business Center.
- Payment method exists, or payment setup can be opened.

Setup flow:
1. Open TikTok Ads Manager.
2. Confirm or create advertiser account.
3. For payment in Ads Manager: Tools -> Settings -> Payments -> add payment method.
4. For Business Center-managed accounts: Business Center -> Finance -> Payment management.
5. Ask the human to enter sensitive payment details directly on the official screen.
6. Build campaign/ad group/ad draft:
   - objective: traffic, lead generation, or conversions if tracking exists
   - creative: 9:16 demo video or screenshot-like phone workflow
   - URL: LP/form URL with UTM
7. Stop before Submit/Publish.

Official reference: TikTok Help states TikTok Ads Manager/Business Center require a valid payment method such as credit/debit card for advertising, and documents Ads Manager payment setup under Tools -> Settings -> Payments.

## X Ads

Use when founder-led posts, professional discussion, or direct outreach support the test.

Readiness checklist:
- X login works.
- Ads account can be accessed.
- Billing/payment readiness is visible.
- Promoted post/campaign draft can be created.

Setup flow:
1. Open X Ads.
2. Confirm ads account and billing status.
3. If payment is missing, navigate to billing/payment setup and ask the human to enter sensitive details directly.
4. Draft campaign or promoted post:
   - objective: website traffic or engagement depending on funnel
   - URL: LP/form URL with UTM
   - targeting: keywords, accounts, interests, geography when available
5. Stop before campaign launch.

## Human Approval Prompt

Use explicit wording:

> I have prepared the campaign draft and account setup as far as possible. Launching now may start ad spend. Do you approve publishing this campaign with the budget cap of {budget} JPY and schedule {schedule}?

Do not proceed from vague replies such as "looks good" unless they clearly approve launch/spend.
