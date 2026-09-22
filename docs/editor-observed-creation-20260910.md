# Observed creation and revision trial — 2026-09-10

## Scope and method

Real native editor, actual Realtime audio input and GPT-6 Astra production. The observer played Japanese Windows Haruka speech into WebRTC and through the speakers. No mocked model responses or production results. This tests synthesized speech, not the user's own microphone/accent. Conversation APIs were used; no paid image/video generation or Qwen was used.

Room `observed-trial-c6ec424c`, content `8176cd1d-274a-4d6c-aa56-f765f9d0ff07`. Raw evidence is under that room's `assistant/events` and `jobs/*/events.jsonl`. Controller: `scripts/editor_observed_trial.py`.

The test user knew the purpose but supplied no style, reference URL, prompt, or technique: make a small cafe feel like a welcoming place to decompress alone after work. Then requested a free moving sample, followed by adding a seated person relaxing their shoulders only in the middle scene, preserving the beginning/end and warm look.

## Actual results

- Reference search: 0.640 seconds. Two embedded reference videos displayed about 28 seconds after the first complete utterance reached reasoning. Search speed is good; search plus selection/presentation is still slower. Candidates were selected by title, not detailed video analysis. This does not prove reference curation quality.
- First 15-second illustrated sample: 481.85 seconds from job creation to completion. Code creation, Japanese text/font repairs, scene-overlap repairs, checks, rendering and review account for the work. This is not a fast first-sample result.
- Person revision: failed after 168.41 seconds despite the revised video having rendered. A Windows PermissionError when replacing an activity JSON escaped the telemetry path and terminated production.
- Continuation after the fix: completed in 147.52 seconds, including detecting/restoring an unintended 18-pixel vertical shift. No paid generation. Updated the same timeline clip.
- Independent frame comparison: original vs final at 1 second is pixel-identical; mean per-channel differences at 12 and 14 seconds are approximately 0.29–0.38/255. This is a sampled comparison, not a claim that every frame is identical. The worker also checked 0/2/3.5/10/12/14.5 seconds and reviewed the revised acting interval.
- Completion audio finished at 10:59:22 UTC, with `completion_spoken` recorded. Final asset `bc8f9cd39aaf`.
- After backend update and reconnect, a two-segment voice question was saved as one canonical utterance with two transcript item IDs. Dan correctly recalled the original audience and intended feeling.

Convenient viewing copy: `D:\done\exports\editor-observed-cafe-20260910.mp4`. This is a fictional cafe trial, created as HTML/SVG/GSAP by GPT-6 Astra and rendered with HyperFrames, not a generative video model and not the user's desired final commercial.

## Fixes implemented

1. Activity telemetry retries transient Windows destination locks and logs persistent I/O failures without killing production. Temporary filenames are unique and cleaned up. Both transient and persistent failures have regression tests.
2. Voice turns carry their original transcription segment IDs. On-demand conversation reads emit the canonical joined utterance once, while retaining unsubmitted/interrupted speech and genuine repeated user instructions. Original audit events remain intact. `execute_work` no longer appends a second user-only copy after attaching the speaker-labelled dialogue.
3. `prepare_motion_project()` can start with a neutral blank project. Reusing the optical-text template is optional; it no longer copies previous briefs, design instructions, comparison scripts, caches or reference audio. Existing-project forks preserve their source files.
4. `write_motion_file` accepts source as structured UTF-8 text, avoiding nested shell quoting/codepage corruption. It writes only inside a prepared working project in the current room, not an immutable approved revision.
5. Rendering honors the project's pinned check/render version instead of ignoring upgrades and always running 0.8.31. Mismatched pins fail explicitly. New scaffolds use 0.8.33; existing matching pins are preserved. The blank scaffold passed actual 0.8.33 check and render (16.06 seconds including check); this is infrastructure validation, not creative output.

18 relevant Python tests passed; JavaScript syntax and scoped diff checks passed. App sandbox restarted through its guarded endpoint after confirming no running production jobs; healthy PID 41048. Core port 9000 was not restarted. No user editor window was closed.

## Remaining limits

The observed higher-level revision worked, but first creation is still measured in minutes. This trial does not establish live-action generation quality, strong multi-source reference curation, sound design, or arbitrary-video mastery. Encoding before visual feedback still causes slow repair loops. The new source-writing/scaffold changes are structurally validated; no claim of a measured end-to-end speedup from those changes yet. A real user's creative judgement remains necessary, and this cafe sample must not substitute for their actual desired project.
