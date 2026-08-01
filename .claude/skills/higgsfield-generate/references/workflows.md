# Workflow Generation

Workflows are higher-level generation flows exposed separately from the model catalog. They still create normal generation jobs, so results are fetched with `higgsfield generate get` / `higgsfield generate wait`.

## Discover workflows

```bash
higgsfield workflow list
higgsfield workflow get draw_to_video
higgsfield workflow get reframe --json
```

Use `workflow get` before creating a job when unsure about params. Do not expect workflows to appear in `higgsfield model list`.

Current public workflows:

| Workflow | Use when |
|---|---|
| `draw_to_video` | Edit a source video using an edited sketch/image frame at a timestamp. Business name may be "Draw To Edit"; CLI name is `draw_to_video`. |
| `reframe` | Reframe a source video to another aspect ratio and optional resolution. |

Do not use or mention `game_character_creator` unless the current CLI exposes it publicly and the user explicitly asks for it.

## Create jobs

### Draw To Video

Use when the user has:
- a source video
- an edited/sketched frame image
- the timestamp for that frame
- an edit instruction

```bash
higgsfield generate workflow draw_to_video \
  --video ./source.mp4 \
  --sketch ./frame.png \
  --timestamp 3.2 \
  --prompt "make the jacket red" \
  --wait
```

`--image` is an alias for `--sketch`.

### Reframe

Use when the user wants a different video aspect ratio.

```bash
higgsfield generate workflow reframe \
  --video ./source.mp4 \
  --aspect-ratio 9:16 \
  --resolution 720p \
  --wait
```

Optional:
- `--mode std|pro`; default `std`
- `--start-image <path-or-id>`
- `--image <path-or-id>` references for `--mode pro`; use 1-2 images
- `--folder-id <folder_id>`

## Cost

Workflow cost uses `generate cost workflow`, not `generate workflow cost`.

```bash
higgsfield generate cost workflow draw_to_video --duration 8.2 --resolution 720p
higgsfield generate cost workflow reframe --duration 7.1 --resolution 1080p
```

If the user asks "how much will this workflow cost?", run cost first and report credits before creating.

## Results

With `--wait`, the CLI waits for the workflow job and prints the result. Without `--wait`, it prints the job id; use normal generation job commands:

```bash
higgsfield generate get <job_id>
higgsfield generate wait <job_id>
```

Do not tell the user to use `workflow get` for a job result. `workflow get` describes the workflow schema; `generate get` fetches the created job.
