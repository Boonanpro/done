---
name: video-direction
description: Video planning and direction skill. Use for scripting, storyboards, shot lists, creative direction, UGC hooks, product/service ads, operation demos, tutorials, film-like shorts, anime-style clips, avatar scenes, reference-driven motion plans, and deciding what should be real capture, AI-generated, or composited.
---

# Video Direction

Plan the video before generating or editing. Keep output concrete enough that `media-gen`, `studio`, and `post-production` can execute it.

## Choose The Format

| Format | Best for | Default structure |
|---|---|---|
| UGC ad | Social proof, pain/solution, founder/product pitch | Hook -> pain -> demo/proof -> benefit -> CTA |
| Operation demo | SaaS/app/workflow explanation | What changes -> access -> one task completed -> result -> CTA |
| Story ad | Instagram/TikTok story | Problem frame -> visual proof -> offer -> swipe/click CTA |
| Product showcase | Object/brand-led visual | Hero shot -> use case -> details -> proof -> CTA |
| Film short | Mood, brand world, cinematic concept | Inciting image -> movement -> reveal -> emotional beat |
| Anime short | Character/story/world-building | Character goal -> action -> transformation -> end card |
| Tutorial | Teach a repeatable process | Outcome -> steps -> check result -> next action |

## Decide Capture vs Generate vs Composite

- **Real capture**: UI operation, app screens, website flows, form entry, exact text, before/after proof.
- **AI generation**: presenter, avatar, cinematic scenes, anime shots, B-roll, environments, product lifestyle, hand/phone atmosphere.
- **Composite**: exact logo/app icon, real screen in phone/laptop mockup, subtitles, product labels, CTA, legal text.

For app demos, never ask a video model to invent the UI. Generate the person/environment, then composite the real screen recording or screenshot.

## Shot Plan Template

```markdown
# Video Plan: <title>
- Goal:
- Audience:
- Platform/aspect:
- Duration:
- Core promise:
- Required exact assets:
- Generation style:
- Capture/composite notes:

## Shots
1. <seconds> - <role: hook/demo/proof/CTA>
   Visual:
   Source: real-capture | Higgsfield | composite | stock
   Motion:
   Text/VO:
   Exact assets:
   Post notes:
```

## Direction Rules

- Start with a visible outcome or emotional hook in the first 2 seconds.
- Show one complete task for demos instead of listing features.
- Keep generated clips short and purposeful; 4-8 seconds is usually easier to control.
- Use reference images/video whenever identity, product, motion, or style continuity matters.
- For cinematic/anime work, specify lens/camera, lighting, motion, material, and emotional beat.
- For UGC, write natural speech first, then visual plan. Avoid corporate copy in a UGC mouth.

## Handoff

After planning:

- Send generation shots to `media-gen`.
- Send exact brand/product requirements to `brand-asset-kit`.
- Send real capture scenes to `studio`.
- Send reframing, grading, LUT, subtitles, audio, and export work to `post-production`.
