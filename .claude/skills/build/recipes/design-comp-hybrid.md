# Design Comp Hybrid

Use this recipe when a HP/LP needs a stronger first-pass visual direction than a normal DOM-first build can reliably produce.

This is not a shortcut for every site. It is a rendering strategy for visually-led marketing pages where GPT Image output, generated mockups, photos, or video can carry the art direction better than rebuilding every detail as HTML.

## When to choose it

- The user asks for a professional, polished, portfolio-worthy HP/LP.
- The site is for a restaurant, salon, clinic, event, product, creator, venue, local business, or brand where mood and first impression matter.
- A generated visual comp is clearly stronger than a plain DOM layout.
- The desired page includes rich photography, editorial composition, device mockups, texture, collage, or complex visual detail.
- The page is mostly marketing content with a small number of active CTAs/forms.

Avoid it as the main strategy when the page is documentation-heavy, SEO article-heavy, must be edited frequently by CMS, or has many dynamic states. In those cases, use the comp as a visual reference and rebuild the content in DOM.

## Required decision

Before coding, choose one rendering mode and write it in `DESIGN.md`.

1. `dom-first`: all content is real HTML/CSS. Best for SEO, editability, accessibility, and maintainability.
2. `comp-guided-dom`: create or inspect a high-quality visual comp, then rebuild it as HTML. Good balance, but pixel-level fidelity is lower.
3. `image-slice-hybrid`: use generated section images for highly visual areas and overlay only active DOM elements such as CTAs, forms, nav, booking widgets, and maps. Highest visual fidelity.
4. `media-rich-hybrid`: combine generated image slices/layers with Seedance video, scroll video, parallax, or animated DOM overlays.

If the visual bar is high and the project is a LP or small HP, prefer `comp-guided-dom` or `image-slice-hybrid` over plain `dom-first`.

## Workflow

1. Create 2-3 short visual direction options in `DESIGN.md`. Name them by style and outcome, not vague adjectives.
   - Example: `Quiet Editorial Izakaya`, `Warm Reservation-first Local`, `Premium Night Bar`.
2. Pick one direction and explain why it fits the user's goal.
3. Generate or use visual comps with `media-gen` using GPT Image 2 for images.
4. Decide which sections are image-backed and which remain DOM.
5. Keep critical information in DOM or duplicate it for accessibility/SEO.
   - H1, shop/service name, location, opening hours, primary CTA, menu/service summary, contact/reservation details.
6. For image-slice pages, create separate desktop and mobile slices.
7. Overlay active elements with percentage-based rectangles so scaling does not break placement.
8. Verify desktop and mobile screenshots. If overlays drift or text becomes unreadable, adjust before finishing.

## Recommended split

- Hero: image/video-backed, with DOM nav and CTA overlays.
- Brand mood/photo collage: image-backed or layered assets.
- Menu/service details: DOM-first, unless visual fidelity is more important than SEO.
- Proof, access, FAQ, contact/reservation: DOM-first.
- Final CTA: DOM-first or overlay on an image-backed band.

## Motion

Static image slices can support motion around the image, not inside it.

Use DOM/CSS/Framer motion for:

- reveal on scroll
- sticky nav state
- CTA hover/press states
- parallax movement of separate layers
- counters, accordions, tabs, menus, and form states

Use generated video or frame sequences for:

- moving food/product/person scenes
- UGC-style clips
- scroll-scrubbed video
- animated hero backgrounds
- camera moves inside an image-like scene

For scroll-driven sites, use `media-rich-hybrid` with `<ScrollVideo>` or layered assets. Do not claim a baked static image itself is animated.

## Quality bar

The output should not look like a sequence of equal cards. At least the first two viewports must have a clear art direction:

- distinctive composition
- intentional typography scale
- concrete photo or generated visual system
- visible CTA
- one memorable brand detail
- reference evidence reflected in layout, crop, motion, or interaction
