# Recipe: Dry Test LP

Use this recipe when `dry-test-launcher` needs a landing page, signup form, monitor recruitment page, waitlist page, or ad destination.

The default goal is not "make a pretty page". The goal is to convert one qualified visitor into a measurable next action:

- leave contact details
- request monitor access
- start a free trial
- say they would pay the stated price
- book an onboarding call

## Default Structure

Build a real responsive Next.js page under `frontend/src/app/artifacts/{slug}/`.

For ad LPs and dry-test LPs, create both **mobile and desktop layouts**. Do not stretch one design across all devices and call it responsive.

Required sections:

1. First view: target audience, concrete pain, concrete promise, one primary CTA.
2. Product visual: phone mock, workflow screenshot, product screen, or generated/real image that makes the offer tangible.
3. Pain: 3-4 specific cards written in the user's language.
4. How it works: 3 steps from visitor action to result.
5. What the tool/service does: concrete outputs, not abstract AI claims.
6. Monitor offer: who it is for, what they get, price hypothesis if applicable, and limits.
7. Signup form: minimum fields needed to qualify and contact the lead.
8. After-submit next step: thank-you copy plus either a trial URL, onboarding link, LINE/DM instruction, or manual follow-up expectation.

## Visual Direction

Do not inherit the global dark app theme for a marketing LP unless the user explicitly asks for dark.

Choose the page theme from the offer, audience, reference material, and conversion goal. Override CSS variables at the page wrapper or `LpShell` root instead of relying on repository defaults:

```tsx
style={{
  "--background": "<page background>",
  "--foreground": "<main text>",
  "--card": "<surface>",
  "--card-foreground": "<surface text>",
  "--popover": "<surface>",
  "--popover-foreground": "<surface text>",
  "--muted": "<subtle surface>",
  "--muted-foreground": "<secondary text>",
  "--border": "<border>",
  "--input": "<input border/background>",
  "--primary": "<CTA/accent>",
  "--primary-foreground": "#ffffff",
  "--ring": "<CTA/accent>",
} as React.CSSProperties}
```

This is required because this repository's global `:root` theme is dark for the app shell. LPs must choose their own local theme.

## Reference-To-Implementation Workflow

When the user expects a high-quality LP and no strong design reference already exists, first create or obtain a visual reference, then implement it as a real responsive page.

Use **GPT-image-2** for the static LP mock/reference image. Do not leave the image-generation model unspecified for this workflow.

Choose the fidelity mode before coding:

### Mode A: Image-First Overlay

Use this when the current goal is a fast ad/dry-test page and visual fidelity to the mock is more important than SEO, text selection, long-term editability, or perfect responsive reflow.

- Use GPT-image-2 mocks or user-provided reference images as the visible LP art.
- Prepare separate mobile and desktop LP art. Do not reuse one tall image for both.
- Do not recreate the whole design with generic `Section` / `HeroSection` spacing.
- Overlay only the interactive parts as real HTML: CTA hit areas, form inputs, submit button, thank-you state, tracking links.
- If the mock contains form fields/buttons, prefer regenerating it with those interactive regions blank or as empty frames before overlaying HTML. Avoid covering baked-in controls unless this is only a quick temporary prototype.
- Keep the image crisp and undistorted. Use exact aspect ratio and avoid cropping important text.
- Use source art at least 2x the displayed CSS width for each layout.
- Add accessible labels for overlaid controls because the visual text is inside an image.

### Mode B: Coded Reconstruction

Use this when the page needs to become a maintainable production LP.

- Use the mock as a design spec, then rebuild sections with real HTML/CSS/React.
- Avoid generic template spacing when the mock has tighter density. Match measured rhythm, widths, card sizes, and vertical gaps.
- Recreate key visual parts as dedicated components rather than forcing everything through `HeroSection`, `Section`, and `Card`.
- Preserve real text, semantic headings, responsive behavior, and editability.
- Design mobile and desktop layouts separately, then implement responsive switching deliberately. Do not rely on automatic stacking if it changes the mock's hierarchy or density.

For first dry tests, default to **Mode A** when the user provides a strong LP image mock and asks for high visual fidelity. Move to **Mode B** after the offer has signal or when maintainability matters.

Preferred workflow:

1. Generate static mobile and desktop LP mock/reference images with **GPT-image-2**, or use the user's provided references. If only one reference exists, derive the missing breakpoint intentionally instead of stretching the same image.
2. Select Mode A or Mode B explicitly.
3. Mode A: place the image as the visible page and overlay only real interactive controls.
4. Mode B: extract its system: layout rhythm, section order, typography scale, color roles, CTA treatment, imagery style, spacing, icon style, and mobile implications.
5. Compare mobile and desktop screenshots against their references and revise until both have the same level of visual intent, density, hierarchy, and finish.

Text-only/card-only pages are not acceptable for ad traffic unless the user explicitly asks for a minimal text page. Visual assets must be relevant to the offer and audience, not generic decoration.

## Form Defaults

For first dry tests, collect:

- name
- email or LINE/Instagram contact
- company/account name or role when useful for qualification
- usage frequency or current workflow when useful for qualification
- whether they would try it now
- optional: willingness to pay the stated monthly price

Do not build recurring billing unless explicitly requested. Payment intent can be measured with copy and form fields first.

## Immediate Trial Rule

If a usable product URL already exists, do not stop at lead capture.

After signup, route or message the user toward the real trial path, for example:

- show "今すぐ1件試す" with the tool URL
- send the URL by email/LINE
- offer a short onboarding flow when credentials or setup are sensitive

This is still a dry test: the experiment validates demand, activation, support load, and payment intent before investing in full billing and multi-tenant operations.

## Quality Gate

Before finishing:

- Check desktop and mobile screenshots.
- Mobile and desktop must both be intentionally designed; one must not be a stretched or accidentally stacked version of the other.
- The page must not be dark by accident.
- Japanese text must not be mojibake.
- First CTA must be visible above the fold on mobile.
- The page must contain real/generative visual assets or a credible product mock, not only icons and cards.
- The form must have a clear destination and a clear next step after submit.
