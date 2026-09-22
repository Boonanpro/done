---
name: post-production
description: "Finish existing footage: reframe, captions, audio, grade, redaction or export."
---

# Post Production

Finish videos after capture or generation. Prefer deterministic tools for exact changes and AI generation only when missing visual content must be invented.

## Editing Policy

Treat editing as preserving the user's intended message, not simply shortening the footage.

When cutting talking-head, camera, or demo footage:

1. Transcribe or outline the full source before aggressive cutting.
2. Remove false starts, repeated takes, long dead air, obvious mistakes, and setup noise.
3. Keep every complete claim, explanation, offer, CTA, and important operation step unless the user explicitly asks for a tighter rewrite.
4. If several takes say the same thing, keep the best complete take instead of cutting the idea entirely.
5. Before final export, make a coverage check: list the required points from the source/brief and confirm each one appears in the edited timeline.

Do not report an edit as final if the cut removed necessary context. Report it as a rough cut and ask for review when message coverage is uncertain.

For UGC / operation-demo edits, `edit_policy.md` describes preserving meaning and checking cuts. Pacing, caption design, framing and coverage follow the current brief. In the Dan editor, use timeline tools and editor_help for saving and proportionate verification; this skill does not require a separate finishing or export stage for every edit.

## Privacy Blur And Redaction

Privacy blur is a protection task, not just a visual effect. Do not mark it complete until the target list, mask behavior, and review evidence are clear.

### Target List First

Before blurring, identify exactly what should be hidden:

- Text input fields
- Names, IDs, email addresses, phone numbers, LINE/account handles
- Notifications, customer data, private admin data
- Faces or bodies when identity should be protected
- Payment, address, or credential information

Avoid broad full-screen blur unless the user asks for it. For app demos, prefer field-level masks so the UI, buttons, labels, and operation flow remain readable.

### Choose The Mask Method

**FORBIDDEN: a fixed rectangle over a time range for anything that can move.** On a scrolling page or moving camera, the target slides out from under the rectangle and leaks. The historical failure mode: widen the rectangle "to be safe", which then destroys surrounding content the user wanted visible. Masks must be anchored to the target, not to screen coordinates.

| Target type | Preferred method |
|---|---|
| On-screen text/cards with fixed appearance (app UI, screen recordings, names, IDs) | Template matching per frame + relative-offset mask (workflow below). This is the proven high-precision one-shot method. |
| Moving faces, people, objects in real footage (appearance changes with scale/rotation/light) | SAM 3.1 tracked mask: `scripts/blur_mask_bake.py` (see below) + manual QA |
| High-risk private data | NLE/manual pass in DaVinci Resolve, Premiere, After Effects, or Fusion |

For real-footage targets, run the SAM 3.1 baker in its dedicated env:

```text
D:/done/venv_sam3/Scripts/python.exe scripts/blur_mask_bake.py IN.mp4 --out mask.mp4 --prompt "person" --start 130 --duration 12
```

It tracks well (people, icons) but one-shot mask quality is NOT guaranteed final quality — plan a manual finishing pass in the production tab's content editor. A user-drawn box without a text concept needs the tracker-specific single-object mode.

### Template-Matched Blur Workflow (ぼかし・モザイク追従)

For screen recordings where specific on-screen text must be hidden while everything else stays visible (proven one-shot 2026-08-19; reference implementation `D:\dan-workspace\demo_build3\build.py`, templates in `D:\dan-workspace\blur_audit\`):

1. **Agree the target list with the user before touching the video.** Do not guess what counts as sensitive; a wrong guess wastes a full review round.
2. **Cut template images**: crop the exact target (e.g. a name) from a representative frame, save as grayscale PNG. One template per distinct appearance of the target.
3. **Match every frame**: decode frames one by one and run `cv2.matchTemplate(gray, tpl, cv2.TM_CCOEFF_NORMED)`, accept at score >= ~0.55. If the same text also appears elsewhere in frame (thumbnails, camera roll), restrict the search to a y-band so the wrong instance is never grabbed.
4. **Mask by relative offset** `(dx, dy, w, h)` from the matched top-left. The mask then follows scrolling automatically and stays tight.
5. **Resolve missed tracking**: a missed match is an unresolved interval. Inspect that interval and correct the target's tracking or keyframes. Do not silently reuse a stale position or replace the result with full-frame blur. Until corrected and checked, keep that interval out of a final external delivery and report the remaining issue.
6. **Report the tracking rate** (`tracked=hits/total` per segment). A low rate means failure: re-cut the template or adjust the search band before delivering.

Core pattern:

```python
res = cv2.matchTemplate(gray[band0:band1, :], tpl, cv2.TM_CCOEFF_NORMED)
_, mx, _, loc = cv2.minMaxLoc(res)
if mx >= 0.55:
    pos = (loc[0], loc[1] + band0); hits += 1
else:
    pos = None                      # unresolved: inspect/correct this interval
if pos is not None:
    mask(frame, pos[0] + dx, pos[1] + dy, w, h)
else:
    unresolved_frames.append(frame_index)  # not approved for final delivery
```

Destruction must be two-stage: pixelate first (downscale ~1/14 with INTER_AREA, upscale with INTER_NEAREST), then GaussianBlur on top. A plain Gaussian blur of known-font text can be partially reversed; for maximum irreversibility use an opaque fill.

Tracking rate alone does not establish correct masking. Review corrected intervals and their boundaries before final delivery.

After masking, always:

1. Generate a review contact sheet showing blurred frames from the start, middle, and end of each masked segment.
2. Run OCR or visual inspection on the final export for the sensitive regions and any likely leaks.

### Review Status

Use these statuses for redaction work:

- `draft`: masks applied, not reviewed.
- `needs_review`: tracking may drift, a field appears near an edge, or confidence is low.
- `failed`: wrong area blurred, blur disappears, or sensitive data remains visible.
- `approved`: reviewed frames show the intended targets are hidden and no obvious leak remains.

Never say "done" for privacy blur unless the status is `approved`. If Gemini or another vision model is used, treat it as advisory only; provide review frames or coordinates so a human can verify.

## Reframe And Aspect Ratios

Choose the method by content:

| Task | Best method |
|---|---|
| Vertical -> horizontal with important subject centered | Crop/scale if enough margin exists; otherwise AI outpaint/generate side plates + composite |
| Horizontal -> vertical social | Smart crop around face/product/UI; add punch-in cuts |
| UI demo variants | Re-render from source capture when possible; avoid cropping unreadable UI |
| Talking head | Face-centered crop with safe headroom; optional blurred background fill |
| Product/film shot | Prefer generative outpaint or regenerate from keyframe at target aspect |

FFmpeg patterns:

```powershell
# Fit inside 16:9 with blurred fill
ffmpeg -i input.mp4 -filter_complex "[0:v]scale=1920:1080:force_original_aspect_ratio=increase,crop=1920:1080,boxblur=20:1[bg];[0:v]scale=1920:1080:force_original_aspect_ratio=decrease[fg];[bg][fg]overlay=(W-w)/2:(H-h)/2" -c:a copy output-16x9.mp4

# Center crop to 9:16
ffmpeg -i input.mp4 -vf "scale=1080:1920:force_original_aspect_ratio=increase,crop=1080:1920" -c:a copy output-9x16.mp4

# Pad to square
ffmpeg -i input.mp4 -vf "scale=1080:1080:force_original_aspect_ratio=decrease,pad=1080:1080:(ow-iw)/2:(oh-ih)/2" -c:a copy output-1x1.mp4
```

Use `C:\Users\Owner\ffmpeg\bin\ffmpeg.exe` if `ffmpeg` is not on PATH.

## Color And LUT

For grading:

1. Extract representative frames.
2. Decide target look: clean SaaS, beauty/salon, cinematic teal-orange, anime pastel, high-key UGC, night neon, documentary neutral.
3. Apply primary correction first: exposure, contrast, white balance, saturation.
4. Apply creative look second: curves, hue shifts, film grain, halation, vignette.
5. Export a LUT only after the grade works on multiple frames.

Useful FFmpeg filters:

```powershell
# Apply LUT
ffmpeg -i input.mp4 -vf "lut3d=file=look.cube" -c:a copy graded.mp4

# Simple grade without LUT
ffmpeg -i input.mp4 -vf "eq=contrast=1.08:brightness=0.02:saturation=1.12,curves=preset=medium_contrast" -c:a copy graded.mp4

# Extract frames for review
ffmpeg -i input.mp4 -vf fps=1 frames/frame_%03d.png
```

## Captions, Audio, Exports

- Burned captions: use large readable Japanese text for social; keep safe margins for app UI.
- SRT captions: create when platform captions are preferred.
- BGM/SE: use licensed/royalty-free real audio. Do not synthesize placeholder beeps for final output.
- Export social variants as separate files named by aspect: `name-9x16.mp4`, `name-16x9.mp4`, `name-1x1.mp4`.

## Quality Check

Before delivery:

- Check no important UI/logo/text is cropped.
- Check required source points survived the cut.
- Check all privacy blur targets are listed, masked, and reviewed.
- Check field-level blur hides only the sensitive input fields when requested.
- Check the output is not marked final if privacy redaction is still `draft`, `needs_review`, or `failed`.
- Check subtitles fit mobile.
- Check audio length matches video.
- Check color is consistent between generated and real footage.
- Check first 2 seconds communicate the hook.
- For aspect variants, inspect frame 0, middle, and final frame.
