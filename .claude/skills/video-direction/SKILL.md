---
name: video-direction
description: "Develop a video script, storyboard or visual direction when creative planning is needed."
---

# Video Direction

Use this for new direction or meaningful changes to a project's direction. Preserve an existing agreed plan during ordinary edits. Keep decisions concrete enough to execute with the editor or specialist tools needed for this project.

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

This is an optional working aid. Include fields that help this project; an empty field is not a reason to invent a user requirement or ask another question. Label creative proposals and assumptions separately from the user's requirements.

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

- Choose an opening that serves the intended viewing experience. An immediate outcome or emotional hook is useful for some short promotions, not mandatory for every film or explanation.
- Show one complete task for demos instead of listing features.
- Keep generated clips short and purposeful; 4-8 seconds is usually easier to control.
- Use reference images/video whenever identity, product, motion, or style continuity matters.
- For cinematic/anime work, specify lens/camera, lighting, motion, material, and emotional beat.
- For UGC, write natural speech first, then visual plan. Avoid corporate copy in a UGC mouth.

## Handoff

When these capabilities are needed (not a mandatory chain):

- Send generation shots to `media-gen`.
- Send exact brand/product requirements to `brand-asset-kit`.
- Send real capture scenes to `studio`.
- Send reframing, grading, LUT, subtitles, audio, and export work to `post-production`.
