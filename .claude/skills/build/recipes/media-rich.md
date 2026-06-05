# Recipe: T3 Media Rich HP

## When to use

- The site needs a premium visual hook: video hero, UGC video, product motion, scroll video, or 3D.
- The business has a product, place, person, or transformation that benefits from being seen in motion.
- Use as an add-on to `conversion-flat.md` or `brand-editorial.md`; do not replace information architecture with motion.

## Technique menu

- `FullBleedVideoHero`: high-impact first viewport.
- `ScrollVideo`: chaptered scroll-controlled video.
- `HeroMedia`: image/video background when full custom hero is unnecessary.
- 3D recipe: use `3d-immersive.md` only for products/objects where interaction adds real understanding.
- UGC video: use `media-gen` with Seedance 2.0 for testimonial/review/social proof blocks.

## Media workflow

1. Decide the job of the media: trust, explanation, product desire, social proof, recruiting atmosphere.
2. Write a 3-shot plan, not only one vague prompt.
3. Generate still references with `gpt-image-2` when needed.
4. Generate video with `seedance-2.0`.
5. Export both desktop and mobile-safe variants if framing matters.
6. Create poster images and use fallback content for reduced motion.
7. Verify with browser screenshots before shipping.

## Prompt shape

Use specific subject, environment, motion, camera, lighting, and constraints.

```text
Commercial documentary video for a Japanese local service company.
Subject: [specific service/person/product].
Environment: [actual place or plausible scene].
Camera: slow dolly in, stable, no fast cuts.
Lighting: natural daylight, premium but realistic.
Motion: gentle continuous action suitable for website hero.
Avoid: text, logos, distorted hands, rapid cuts, surreal elements.
Aspect ratio: 16:9.
Duration: 10 seconds.
```

## Guardrails

- Do not use heavy media just because it is available.
- Do not hide critical text in video pixels. Text belongs in DOM.
- For UGC claims, do not invent real customer names or fake endorsements. Use scenario-based copy unless the user provides real testimonials.
- If media generation fails or looks artificial, ship a strong static hero instead of forcing bad motion.

## Acceptance checks

- The media makes the business easier to understand or trust.
- The first frame works as a poster.
- The section still works with reduced motion.
- Mobile does not crop the subject awkwardly.
- LCP is protected: large video is not the only way to understand the page.
