---
name: popout
description: "Create the specific frame-break cutout effect from talking-head footage."
argument-hint: "<input-video> [--intensity dramatic|mid|subtle] [--no-shadow] [--bg <image>] [--start S --duration D]"
allowed-tools: Bash
---

# popout — frame-break / pop-out renderer

Turns a talking-head clip into a vertical short where the subject pops out over the
top edge of a rounded card. Real footage stays untouched; only compositing is applied.
**No API credits** — matting is local (Robust Video Matting on the GPU).

## How it works (so you can explain / tune it)

1. **Human matting** per frame via RVM (`torch.hub` `PeterL1n/RobustVideoMatting`), CUDA.
2. **Composite**: source video clipped to a rounded "card"; the matted person is then
   drawn **on top**, clipped to **(inside the card OR above the card's top edge)**.
   Because the full person is always front-most there, the card border/seam never
   crosses the body (this was the key fix — fading the cutout at the top edge leaves a
   seam/halo on the face; don't do that).
3. Card **drop shadow** + optional **contact shadow** from the popped head sell depth.

## Run it

```bash
python scripts/popout_render.py <INPUT.mp4> --out <OUT.mp4> [options]
```

Options:

| Flag | Meaning | Default |
|---|---|---|
| `--intensity subtle\|mid\|dramatic` | how much of the body pops over the top (subtle=頭の先 / mid=頭+肩少し / dramatic=顔・肩ごと) | `dramatic` |
| `--card-top <y>` | manual override of the card top edge (finer control than presets) | preset |
| `--no-shadow` | turn off the contact shadow (flatter look) | shadow on |
| `--bg none\|<image>` | `none` = generated dark gradient studio; or a path to a background image (e.g. a Higgsfield/`soul_location` environment) shown inside the card + blurred outside | `none` |
| `--start <s> --duration <s>` | trim a segment from the source | full clip |
| `--aspect <W:H>` | output aspect (canvas long side 1920) | `9:16` |
| `--fps <n>` | output fps | `30` |

Output is H.264 1080x1920 with the source audio muxed back in.

Examples:

```bash
# Default dramatic pop-out, full clip
python scripts/popout_render.py in.mp4 --out out.mp4

# Subtle, no contact shadow, just a 6s segment
python scripts/popout_render.py in.mp4 --out out.mp4 --intensity subtle --no-shadow --start 138 --duration 6

# Pop out over a generated environment image (e.g. from higgsfield soul_location)
python scripts/popout_render.py in.mp4 --out out.mp4 --bg neon_studio.png
```

## UX rules

1. Pick `dramatic` by default; offer `mid`/`subtle` if the user wants less. The amount
   is a single continuous knob (`--card-top`), so you can fine-tune to taste.
2. After rendering, attach/point to the output file and state the intensity + whether
   the shadow is on (per the "成果物を必ず添付" / "アクセス方法明記" feedback rules).
3. Source should be a vertical-ish talking head with the head in the upper-center. 4K
   input is fine (it is scaled+cropped to 1080x1920).
4. Requires a clip with the person clearly separable; busy/cluttered subjects matte worse.

## Where this fits (両パターン router)

- **① this skill** — real footage pop-out (local, free). ✅
- **② environment/lighting change keeping the real person** — video-to-video edit
  (fal `kling-video/o1/video-to-video/edit`, or Gemini Omni when its API ships). See
  `media-gen`. Needs fal credits; use only when a real deliverable is requested.
- **③ photo + audio → talking video** — fal OmniHuman / Kling AI Avatar.
- **④ full-AI generation** — `higgsfield-generate`.

To layer effects: do the **② v2v environment change first**, then run this pop-out
skill on the restyled clip.
