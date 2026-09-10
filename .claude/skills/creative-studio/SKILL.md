---
name: creative-studio
description: Creative production router for Dan. Use when the user asks for videos, ads, UGC, product/service promos, app demos, film-like shorts, anime-style clips, AI avatar content, story/reel/TikTok/Instagram creatives, aspect-ratio variants, or broad requests like "こういう動画作って" that require choosing between direction, generation, editing, color, LUT, and delivery workflows.
---

# Creative Studio

Dan's top-level creative production entrypoint. Use this skill to translate a loose user request into the right production route, then call the specialist skills.

For an existing Dan editor project, preserve its agreed direction and edit it with timeline tools. Use editor_help for the editor contract. The routes below describe available capabilities, not required stages or a fixed provider choice. Select only what the request needs; use other methods when better suited. Previously supplied goals, references and assets remain available without repeating intake.

## Routing

Classify the request first:

| User intent | Primary skill | Notes |
|---|---|---|
| "この商品/サービスの広告作って" | `video-direction` + `brand-asset-kit` + `media-gen` | Use Higgsfield Marketing Studio for UGC/ad variants. |
| "操作デモ/紹介動画を作って" | `video-direction` + `studio` + `post-production` | Real screen recording is the source of truth for UI. |
| "映画っぽい/アニメっぽい映像" | `video-direction` + `media-gen` + `post-production` | Use cinematic/anime direction, references, and grading. |
| "AIアバター/人物を一貫させたい" | `brand-asset-kit` + `higgsfield-soul-id` + `media-gen` | Build or reuse identity references. |
| "解説動画/ドキュメンタリー調/ナレーション音声から動画" | `explainer-video` | Narration-driven explainer. Build in the production room (editor), not in chat. |
| "縦を横に/横を縦にしたい" | `post-production` | Reframe, extend, crop, blur-fill, or regenerate missing sides. |
| "色味を整えて/LUT作って" | `post-production` | Grade, generate LUT, export variants. |
| "ロゴ/アイコン/商品を正確に出したい" | `brand-asset-kit` + `post-production` | Prefer exact overlay/compositing over generative approximation. |

## Capabilities To Select As Needed

1. **Intake**: identify goal, audience, platform, duration, aspect ratios, available assets, and whether exact UI/logo fidelity matters.
2. **Asset kit**: use `brand-asset-kit` to collect product URL, app icon, logo, screenshots, demo recording, brand colors, fonts, reference people, and forbidden changes.
3. **Direction**: use `video-direction` to choose format: demo, UGC, story ad, product showcase, film, anime, tutorial, trailer, or variant pack.
4. **Generation**: use `media-gen` for Higgsfield-driven images/videos, avatars, product placement, motion control, or cinematic/anime shots.
5. **Capture/edit**: use `studio` for real screen capture and timeline assembly.
6. **Post**: use `post-production` for aspect-ratio variants, subtitles, audio, color, LUTs, export, and quality checks.

## Production Principle

Use generated video for what it is good at: people, mood, cinematic motion, animation, product/world building, and ad variation.

Use deterministic editing/compositing for what must be exact: app icons, logos, UI text, screenshots, real operation flows, subtitles, CTA, and final brand marks.

## Minimal Questions

Ask only what blocks the next action. Common first question:

```text
使う素材はありますか？（URL、ロゴ/アイコン、画面録画、商品画像、参考動画）
```

If the user already gave enough, proceed with sensible defaults:

- Short-form social: `9:16`, 15-30s
- Web/YouTube: `16:9`, 30-90s
- Ad variant pack: `9:16`, `1:1`, `16:9`
- Demo fidelity: real capture first, AI ambience second
