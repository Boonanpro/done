---
name: studio
description: "Capture real screens, record browser demos or edit an existing Remotion project."
---

# studio

Use this skill for real screen capture or existing Remotion work. In the Dan editor, the timeline and editor_help define the editing and saving contract. A reference to a studio tool does not require restarting creative intake, creating a separate composition, or exporting an otherwise complete timeline edit.

## Role In The New System

| Skill | Responsibility |
|---|---|
| `creative-studio` | Top-level creative routing |
| `video-direction` | Plan, script, storyboard, shot list |
| `brand-asset-kit` | Exact assets and fidelity constraints |
| `media-gen` | Higgsfield/OpenAI generation |
| `studio` | Real capture and timeline assembly |
| `post-production` | Reframe, subtitles, audio, color, LUT, final export |

## Use Studio For

- App/SaaS/site operation demos
- Screen recordings and click/type/scroll flows
- Remotion timeline assembly
- Cursor overlays, zooms, text cards, BGM/SE placement
- Final file handoff through Dan chat tools

## Existing Tools

| Tool | Use |
|---|---|
| `studio_record` | Record HTML/browser content with Playwright -> WebM |
| `studio_encode` | Convert WebM/MP4, resize, re-encode |
| `studio_probe` | Inspect video metadata |
| `studio_extract_frame` | Extract PNG frame at timecode |
| `send_file` | Send finished media to chat UI |

Do not run large Playwright/FFmpeg jobs directly in foreground if Dan tool wrappers exist; raw output can flood the CLI context.

## ⚠️ 制作ルーム（制作タブ）のタイムライン書き出しは必ず export ジョブを使う ⚠️

制作ルームのタイムライン（contents.json の timeline）を動画に書き出す依頼を受けたら、
**自分で ffmpeg を組んではいけない**。必ずバックエンドの書き出しジョブを使う：

```
POST /api/v1/production-assets/jobs
{"room_id": <room>, "content_id": <content>,
 "instruction": {"mode": "export", "timeline": <そのcontentのtimeline>}}
```

- この経路はプレビューと同一のネイティブ合成器で描く（テロップ・ぼかし・モザイク・
  追従・音声ミックスすべてプレビュー一致が保証される）。約30fpsで書き出せる
  （5分の動画≒5〜7分）。完了は同エンドポイントのジョブ一覧をポーリング、
  結果の result.output_path / result.user_output_path が完成ファイル。
- 部分書き出しは instruction に "export_range": [開始秒, 終了秒] を足す。
- 保存先指定は "output_copy_path": "<フルパス>.mp4" を足す。
- **ffmpeg で filtergraph を自作してタイムラインを再現するのは禁止**（見た目が
  プレビューと一致せず、過去に5分の動画へ3時間かけて不一致動画を作った）。
  ffmpeg 直接使用は素材の変換・切り出しなど「タイムライン再現以外」に限る。

## Screen Capture Rules

- Select real UI elements with selectors, not hand-guessed coordinates.
- Use `bounding_box()` for cursor and zoom targets.
- Record full-resolution source footage; do zoom/crop in edit.
- Show cursor only for meaningful actions.
- Avoid instant scroll jumps; use smooth scroll and keep the next action group visible.
- Record click/type timing for SE placement when possible.

## Demo Story Rules

For operation demos, follow `actions/video_guidelines.md`:

1. Hook within 5 seconds.
2. Show where the product/tool is accessed.
3. Complete one real task end to end.
4. Insert concise text cards only when they clarify the story.
5. End with product name/logo/CTA.

## Quality Check

Before delivery:

- Operation and screen transitions must be causally clear.
- UI text must remain readable.
- BGM/SE must not outlast the video.
- Required scenes from the plan must be present.
- If input fields, customer data, account data, or private notifications must be hidden, send the timeline to `post-production` privacy blur/redaction before final delivery.
- Do not treat privacy blur as complete from tracking alone; require review frames or an approved redaction status from `post-production`.
- If the video was generated or heavily edited, ask `post-production` to inspect key frames and variants.

## Proposal Videos

Only when the user explicitly says "提案動画作って", read `actions/proposal_video.md`.
