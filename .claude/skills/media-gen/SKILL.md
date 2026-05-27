---
name: media-gen
description: 画像・動画のAI生成/編集を1つにまとめたスキル。画像=GPT Image 2、動画=Kling 3.0 Pro。ヒーロー画像・日本語テキスト焼き込み・ループ/ヒーロー動画・image-to-video が必要な時に使う。（旧 image-gen / video-gen を統合）
---

# media-gen スキル

画像と動画のAI生成・編集を **1つの入口** に統合したスキル。生成物は Supabase Storage に保存され、公開 URL が返る。

- **画像**: GPT Image 2 (OpenAI) — `POST /api/v1/images/generate` ・ `/edit`
- **動画**: Kling 3.0 Pro (Kuaishou, fal.ai 経由) — `POST /api/v1/videos/generate`

> **将来 (Higgsfield 統合)**: Higgsfield MCP (`https://mcp.higgsfield.ai/mcp`) を入れると、画像+動画を1エンドポイントで Veo / Sora / Nano Banana / Seedance 等 30+ モデルに切替できる。導入時は **このスキルの裏（生成バックエンド）だけ差し替える**。入口（media-gen）と呼び出し側（build 等）は変えない。Higgsfield は従量クレジット制なので [[feedback_prefer_cli_flatrate]] とのトレードオフ判断が要る。

---

## 画像生成（GPT Image 2）

### 特徴
- **日本語テキスト描画が高精度**（仮名・漢字ともほぼ100%）→ HPヒーローに日本語コピーを焼き込む用途に最適
- reasoning搭載（描画前に構図プランニング）、複数画像でキャラ・レイアウト一貫性を保てる

### 生成 (text-to-image)
```
POST /api/v1/images/generate
{ "prompt": "構図・スタイル・ライティング・色調を具体的に",
  "size": "1024x1024" | "1792x1024" | "1024x1792" | "auto",
  "quality": "low" | "medium" | "high" | "auto",
  "project_id": "xxx" }
```
返り値: `{ "url": "....png", "kind": "generate", "size": "...", ... }`

### 編集 (image-to-image)
```
POST /api/v1/images/edit
{ "prompt": "変更内容（例: 背景をビーチに、被写体はそのまま）",
  "reference_url": "元画像のURL", "project_id": "xxx" }
```

### quality 料金目安 / size の選び方
| quality | 1024² 単価 | 用途 |
|---|---|---|
| low | 約 $0.006 | 試作・サムネ |
| medium | 約 $0.053 | 日常用途 |
| **high** | 約 **$0.211** | 本番HPヒーロー等（既定） |

| 用途 | size |
|---|---|
| ヒーロー(LP横長) | `1792x1024` |
| モバイル縦 / 9:16 | `1024x1792` |
| 正方形(SNS/アイコン) | `1024x1024` |

### Python 直接呼び出し
```python
from app.services.image_generation_service import ImageGenerationService
svc = ImageGenerationService()
result = await svc.generate(prompt=..., user_id=current_user_id, project_id=project_id,
                            size="1792x1024", quality="high")
print(result["url"])
```

### 落とし穴（画像）
- overlay（暗転・ぼかし）は独立 div を重ねず `<img>` 自体に CSS filter（`brightness`/`blur`）で適用
- prompt が弱いと平凡。構図・スタイル・ライティング・色調を必ず指定
- 生成 10〜30秒（reasoningあり）。商標ロゴ・実在人物は拒否される
- model `gpt-image-2`、認証 `OPENAI_API_KEY`、保存先 bucket `generated-images`（無ければ自動作成）

---

## 動画生成（Kling 3.0 Pro）

### 特徴
- 一貫性が強い（Subject/Element Binding で顔・服・ブランド保持）、物理整合・シネマティック品質が高い
- コスト良好（10秒+音声 約 $1.68）、最大尺15秒（10秒まで高品質保証）

### 生成 (text-to-video / image-to-video)
```
POST /api/v1/videos/generate
{ "prompt": "Cinematic wide shot, documentary style. Slow dolly in.",
  "aspect_ratio": "16:9" | "9:16" | "1:1",
  "duration": "5" | "10",
  "reference_image_url": null,   // 省略=text-to-video / URL=image-to-video
  "project_id": "xxx" }
```
返り値: `{ "url": "....mp4", "kind": "text-to-video"|"image-to-video", "model": "kling-3.0-pro", ... }`

### duration / aspect_ratio
| 用途 | duration | aspect_ratio |
|---|---|---|
| ヒーロー(LP横長) | 10 | 16:9 |
| モバイル縦・SNS | 5〜10 | 9:16 |
| 正方形 | 5 | 1:1 |

### プロンプト（英語推奨）
- カメラワーク明示: `slow dolly in` / `tracking shot` / `static wide shot` / `handheld documentary`
- ライティング・物体の動き・スタイル（`photorealistic` / `documentary` / `commercial`）
- 禁止: 過度に複雑な同時動作、5人以上の人物、高速アクション（腕・指が破綻しやすい）

### 注意
- 生成 **3〜6分**（API は完了待ちでブロック）。返り値は MP4 → `<img>` でなく `<video src autoPlay loop muted playsInline>` に
- overlay は `<video>` 自体に CSS filter（独立 div を重ねない）
- **黒帯注意**: image-to-video で元画像と `aspect_ratio` が食い違うと黒帯が焼き込まれる。元画像のアスペクト比を測ってから合わせる（または画像を作り直す）
- **スクロール動画(T3)用**: スクラブ用途は動画を **全フレーム keyframe に再エンコード**しないとシークがカクつく（FFmpeg `-g 1 -keyint_min 1`、studio の ffmpeg を利用）。詳細は `build/recipes/scroll-video.md`

### Python 直接呼び出し
```python
from app.services.video_generation_service import VideoGenerationService
svc = VideoGenerationService()
result = await svc.generate(prompt=..., user_id=current_user_id, project_id=project_id,
                            aspect_ratio="16:9", duration="10")
print(result["url"])
```

### 落とし穴（動画）
- `FAL_KEY` 必須。未設定で RuntimeError
- 5秒で試作 → 納得したら10秒で本番。人物の手アップなど繊細なカットは複数回生成 or 静止人物に
- model `kling-3.0-pro`、fal endpoints: T2V `fal-ai/kling-video/v3/pro/text-to-video` / I2V `fal-ai/kling-video/v3/pro/image-to-video`、bucket `generated-videos`

---

## いつ使うか（共通）
- HP / ダッシュボード / ツール制作でヒーロー画像・動画・装飾素材が必要なとき
- 「この画像を〜にして」「動画にして」「動かして」「アニメーションに」系の編集要望
- `build` の Phase 2（AI素材ヒーロー / 全画面モックアップ）、`studio` の素材生成、T3 スクロール動画の素材生成
