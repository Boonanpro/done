# Recipe: T2 Brand Editorial

## When to use

- Corporate sites, recruiting pages, professional-service sites, founder-led businesses, and portfolio-worthy client HPs.
- The goal is trust, memorability, and proof, not only a fast lead form.
- Use this for the first two external HPs when the site should later become a case study for the agency/company HP.

## Do not use when

- The only goal is quick ad conversion or dry-test signup. Use `conversion-flat.md`.
- There are no usable facts, photos, testimonials, founder story, or proof points. Start with content discovery first.

## Core structure

1. Hero: strong statement + real/generative image or video + clear CTA.
2. ProofBar: 3-4 concrete proof points.
3. Promise section: what changes for the visitor.
4. ServiceShowcase: 3-6 services with visual hierarchy, not equal cards only.
5. CaseStudyGrid: 2-4 examples or representative scenarios.
6. ProcessTimeline: how engagement works.
7. About / Founder / Team: why this business can be trusted.
8. FAQSection: remove buying friction.
9. ConversionCta + InquiryForm / phone / booking.

## Required components

- `LpShell`
- `Section`
- `FullBleedVideoHero` or `HeroMedia`
- `ProofBar`
- `ServiceShowcase`
- `CaseStudyGrid`
- `ProcessTimeline`
- `ConversionCta`
- `FaqSection`
- `InquiryForm` when contact capture is required

## Visual direction

- Use one strong first-viewport asset. For HP quality, an actual product/place/person/work scene is better than abstract decoration.
- Use varied section structures: full-bleed hero, proof band, asymmetric service showcase, case grid, timeline, final CTA.
- Avoid long equal-card grids. Cards are allowed for repeated proof/cases, but sections should not all look like cards.
- Keep copy specific: numbers, regions, turnaround, named services, target customers, before/after, constraints.

## Media generation

- Use `media-gen` when usable photos are missing.
- Image standard: `gpt-image-2`.
- Video standard: `seedance-2.0`.
- Generate assets for actual roles: hero visual, service visual, case visual, UGC/review clip, not decorative filler.

## Acceptance checks

- First viewport says who the business is, what they do, and why trust them.
- There is at least one proof section before the first long explanation.
- There are multiple CTA locations, but they do not feel spammy.
- Mobile 390px keeps heading, CTA, and hero visual readable without overlap.
- The result can plausibly be shown as a portfolio case after replacing dummy copy/assets.
