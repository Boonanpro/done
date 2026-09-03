---
name: dry-test-launcher
description: Plan and prepare small-budget demand-validation campaigns for new services or offers. Use when the user says they want a dry test, demand test, ad test, landing page test, monitor recruitment, waitlist test, Instagram/TikTok/X ads test, or wants DAN/Codex to prepare ad launch materials and an approval checklist before spending money.
---

# Dry Test Launcher

Use this skill to turn a vague "test demand" request into a launch-ready dry test. Optimize for speed, clean measurement, and avoiding premature build-out.

## Operating Rules

- Test one hypothesis per campaign.
- Treat a request like "I want to run a dry test" as an end-to-end launch-prep request. Do not wait for the user to explicitly ask for LP, form, ads, targeting, UTM, account setup, or approval checklist; create/propose all of them unless the user narrows scope.
- Do not spend money, publish ads, connect payment methods, or change live ad settings without explicit human approval.
- Drive setup as far as possible: landing page, form, tracking links, ad account readiness, payment setup screen, campaign/ad draft, and final launch summary.
- Produce launch-ready materials, then stop at the approval gate.
- Prefer the smallest test that can invalidate the idea.
- Track intent first: waitlist signup, DM, consultation request, or "I would pay" response.
- Keep budgets small until there is signal. Default to 3,000-10,000 JPY total for 3-7 days unless the user specifies otherwise.
- Separate ad promise from current product reality. Do not claim features that cannot be delivered manually or with current tooling.
- If handling regulated, medical, financial, employment, housing, or sensitive targeting, pause and ask for a narrower compliant plan.
- Never ask for or store full card numbers, CVV, or other payment secrets in chat or files. Navigate to official payment screens and have the human enter sensitive details directly.

## Workflow

1. Clarify the test objective.
   - State the target customer, painful job, offer, price hypothesis, and conversion event.
   - If missing, infer a conservative first version and label assumptions.
   - Ask questions only when a missing answer blocks action. Otherwise proceed with defaults and mark them editable.

2. Define success and stop rules.
   - Set a budget cap, test duration, primary metric, and go/no-go threshold.
   - Default thresholds: 10 qualified leads, 3 strong buying-intent replies, or projected revenue exceeding infra/support cost.

3. Create the funnel.
   - Default to a landing page plus lightweight signup form when no funnel is specified.
   - Choose one destination: landing page, form, LINE/DM, or booking page.
   - Write headline, body copy, CTA, objections, FAQ, and thank-you message.
   - Include UTM naming and source labels.
   - If a landing page, signup form, or public preview URL is needed, check/invoke the `build` skill before implementation. For ad traffic, monitor recruitment, waitlists, or dry-test LPs, require the build skill's `recipes/dry-test-lp.md` in addition to normal LP rules. Return to this skill after the LP/form URL is ready.
   - If a usable product URL already exists, do not make the funnel end at contact collection. Add an immediate trial/onboarding next step after signup, while still stopping before paid launch or recurring billing unless the user explicitly approves it.

4. Create ad variants.
   - Default to Instagram first when the user mentions hairstylists, beauty, local services, visual work, or monitor recruitment and no platform is specified.
   - Produce 3-5 variants per chosen platform.
   - Vary hook, pain, proof, and CTA.
   - Include creative direction for static image/video. Do not require custom production unless the user asks.

5. Pick targeting.
   - Use job/interest/geography/behavior constraints that match the offer.
   - Avoid overly narrow targeting for the first test unless the audience is local.

6. Prepare launch checklist.
   - Confirm destination URL works on mobile.
   - Confirm form fields and notification destination.
   - Confirm UTM links.
   - Confirm budget cap and schedule.
   - Confirm final human approval before spend.

7. Prepare ad account and campaign draft when requested.
   - Check the chosen platform account, business/page/profile prerequisites, billing readiness, and permissions.
   - If an account is missing, navigate the official setup flow as far as possible.
   - If payment is missing, open the official payment setup screen and ask the human to enter sensitive payment details directly.
   - Create campaign/ad set/ad drafts when possible, but stop before publish/submit/launch or any action that starts spend.
   - Read [references/ad-account-setup.md](references/ad-account-setup.md) for platform setup notes.
   - **For Meta/Instagram, prefer the `meta-ads` skill** to create the campaign/ad set/ad drafts via the Marketing API (`scripts/meta_ads_cli.py`). It creates everything PAUSED and only goes live with `publish --confirm` after explicit human approval — the same approval gate this skill requires. Hand off the prepared hypothesis, copy, targeting, budget cap, and destination URL to it. (Google Ads / TikTok ads CLIs are not built yet — keep those on the official UI flow above.)

8. After launch, monitor and report.
   - Summarize spend, impressions, CTR, landing visits, conversion count, CPA, and qualitative replies.
   - Recommend: stop, iterate copy/targeting, or move to paid beta.

## Default Output Format

Use these sections:

- Test Hypothesis
- Audience
- Offer
- Funnel
- Ads
- Tracking
- Budget And Stop Rules
- Account And Billing Readiness
- Approval Checklist
- Next Actions

## Platform Selection

- Instagram: default first choice for visually demonstrable local/creator/beauty offers.
- TikTok: use when the offer can be shown in short video or before/after workflow.
- X: use when the audience has active professional discussion or founder-led posting can support paid tests.
- Google Search: use only when there is clear search intent and keyword CPC is acceptable.

Read [references/platforms.md](references/platforms.md) when preparing platform-specific campaign settings.

## Beauty/SALONBOARD Offer Defaults

For hairstylist SALONBOARD automation tests:

- Audience: Japanese hairstylists who post hair styles to Hot Pepper Beauty, especially solo stylists or salons with frequent style uploads.
- Pain: style posting is tedious, repetitive, and easy to postpone.
- Offer: upload hairstyle photos from a phone; AI drafts style name, comment, tags, and form fields; posting/reflect request is handled or assisted.
- First CTA: "先着10名モニター登録" or "無料で1件試す".
- Price hypothesis: monitor 500 JPY/month; later 980-2,980 JPY/month depending on automation reliability and support burden.
- Initial success signal: 10 signups or 3 users willing to connect SALONBOARD credentials for a trial.
