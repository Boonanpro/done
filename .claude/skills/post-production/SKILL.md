---
name: post-production
description: Video finishing skill for editing, reframing, aspect-ratio conversion, subtitles, audio, color grading, LUT creation/application, compression, exports, and quality checks. Use when the user asks to edit footage, make vertical/horizontal versions, create social variants, color grade, apply/make LUTs, resize/crop/blur-fill/extend videos, or finish generated/captured clips.
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

For UGC / operation-demo edits, follow the detailed rules in `edit_policy.md` (same directory): cut ONLY restatements (keep filler, never clip sentence ends, keep a 0.3-0.5s breath), compress only inter-sentence silence, show the full operation flow from app launch, captions as outline+shadow (no black box) and none during PiP/screen sections. The production tab (dan_edit) injects this policy automatically; in chat, read it before editing this kind of footage.

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

| Target type | Preferred method |
|---|---|
| Stable app input fields | UI-state detection + fixed/relative rectangle masks |
| Scrolling app screens | Detect screen state, then apply state-specific masks over known fields |
| Moving faces or people | Face/person detection + tracker + manual QA |
| Moving phone/object | Detector/segmentation + tracker + manual QA |
| High-risk private data | NLE/manual pass in DaVinci Resolve, Premiere, After Effects, or Fusion |

OpenCV tracking is acceptable as an automation layer, but it is not enough by itself for high-risk privacy redaction. If a mask drifts, disappears, or hits the wrong area, the output is not complete.

### Input-Field Blur Workflow

For app recordings where only input fields should be hidden:

1. Extract representative frames for each UI state.
2. Detect the phone/app viewport when needed.
3. Define rectangle masks for only the sensitive fields in that UI state.
4. Apply masks by frame range or by UI-state detection.
5. Keep surrounding UI readable unless it contains sensitive data.
6. Generate a review contact sheet showing blurred frames from the start, middle, and end of each masked segment.
7. Run OCR or visual inspection on the final export for the sensitive regions and any likely leaks.

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
