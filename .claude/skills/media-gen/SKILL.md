---
name: media-gen
description: AI media generation routing skill centered on Higgsfield CLI. Use for generating or editing images/videos, UGC ads, product demos, cinematic or anime shots, image-to-video, reference-driven generation, product placement, motion-controlled clips, avatars, brand kits, app/service ad creatives, and model selection across Higgsfield, OpenAI image generation, and existing local endpoints.
---

# media-gen

Use this as Dan's AI media generation router. It chooses the generation engine and hands exact finishing work to `post-production`.

## Default Engine

Prefer Higgsfield CLI for new image/video generation:

- Generic images/design/text: `higgsfield-generate` with GPT Image 2
- Serious video/image-to-video: `higgsfield-generate` with Seedance 2.0 by default
- Ads/UGC/product demos: `higgsfield-generate` Marketing Studio
- Product photos: `higgsfield-product-photoshoot`
- Consistent person/avatar: `higgsfield-soul-id` then `higgsfield-generate`
- Marketplace listing cards: `higgsfield-marketplace-cards`

Use existing Dan API endpoints only when they are a better fit or already wired into the current product surface:

- `POST /api/v1/images/generate`
- `POST /api/v1/images/edit`
- `POST /api/v1/videos/generate`

## CLI Rules

Before generation:

```powershell
higgsfield account status
higgsfield workspace status
```

If unauthenticated, ask the user to complete `higgsfield auth login`.

Always inspect model params when uncertain:

```powershell
higgsfield model list --json
higgsfield model get <model_id> --json
```

Use `--wait` so the command returns the final result URL:

```powershell
higgsfield generate create seedance_2_0 --prompt "..." --aspect_ratio 9:16 --duration 8 --wait
```

## Generation Decision Table

| Need | Route |
|---|---|
| UGC ad from URL/product | `higgsfield-generate` Marketing Studio |
| Branded app/service ad | `brand-asset-kit` -> Marketing Studio -> `post-production` exact logo/UI composite |
| Cinematic film-like clip | `higgsfield-generate` Seedance/Cinema/Veo route; check model catalog |
| Anime-style clip | `higgsfield-generate`; use anime/stylized references and short clips |
| Animate a still | Image-to-video with `--start-image` |
| Control first and last frame | Use `--start-image` and `--end-image` if model supports it |
| Specific person consistency | `higgsfield-soul-id` first |
| Product photo set | `higgsfield-product-photoshoot` |
| Exact UI/app icon/logo | Generate environment only; composite exact assets later |

## Marketing Studio Quick Flow

For product/service ads:

1. Use `brand-asset-kit` to collect URL, logo, screenshots, product refs, and CTA.
2. Fetch/create product or webproduct via Higgsfield.
3. Pick preset/custom avatar only if the concept needs a presenter.
4. Generate 1-3 short variants first; do not spend credits on long versions before direction is approved.
5. Send output to `post-production` for exact overlays, captions, audio, grading, and aspect variants.

Useful references live in `higgsfield-generate/references/`:

- `model-catalog.md`
- `marketing-products.md`
- `marketing-brand-kits.md`
- `marketing-avatars.md`
- `marketing-modes.md`
- `media-inputs.md`
- `prompt-engineering.md`

## Fidelity Rule

For brands, apps, and SaaS demos:

- Real screen recording/screenshot is source of truth.
- Video model output is supporting footage.
- Exact logo/icon/UI text should be composited in `post-production`.

Do not promise a generative model will faithfully reproduce UI text or logos unless a final compositing step is planned.
