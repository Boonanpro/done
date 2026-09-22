---
name: brand-asset-kit
description: "Collect exact brand assets and identity references for a production that needs brand fidelity."
---

# Brand Asset Kit

Prepare the assets and constraints that keep generated and edited content faithful.

## Collect

For each project, gather what exists:

- Product/service URL
- App icon, logo, favicon, wordmark
- UI screenshots and screen recordings
- Product photos or package images
- Brand colors and fonts
- Target audience and offer
- Reference videos or ads
- Person/avatar photos, if a consistent presenter is needed
- Required CTA and landing URL

## Classify Fidelity

| Asset | Fidelity rule |
|---|---|
| App icon/logo/wordmark | Must be exact. Use compositing/overlay for final frames. |
| UI screen/text | Must be exact. Use real capture or screenshot. |
| Product package/label | Prefer exact image/product placement; inspect final frame. |
| Presenter identity | Use `higgsfield-soul-id` or approved avatar references. |
| Mood/background/B-roll | Can be generated creatively. |

## Higgsfield Setup

Use `higgsfield-generate` references when needed:

- Website/product import: `references/marketing-products.md`
- Brand kit from URL: `references/marketing-brand-kits.md`
- Avatar selection/creation: `references/marketing-avatars.md`
- Ad reference video: `references/marketing-ad-references.md`
- Soul/person identity: use `higgsfield-soul-id`

For app/SaaS work, create a web product or brand kit from the URL, but still keep separate exact screenshots for compositing.

## Output Brief

Produce a concise asset brief before generation:

```markdown
# Asset Kit: <project>
- Product URL:
- Exact assets:
- Reference assets:
- Brand colors/fonts:
- Presenter/avatar:
- UI/demo sources:
- Must not change:
- CTA:
- Export platforms:
```

## Rule

If accuracy matters, do not rely on a video model to draw brand assets from memory. Generate the surrounding shot, then composite the exact asset in `post-production`.
