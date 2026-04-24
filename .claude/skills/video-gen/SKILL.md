---
name: video-gen
description: Kling 3.0 Pro (Kuaishou) 経由の動画生成/image-to-video。ヒーロー動画・ループ動画・アニメーションが必要な時に使う。
---

# video-gen スキル

Kling 3.0 Pro (Kuaishou、fal.ai 経由) で動画を生成・既存画像から動画化する。生成物は Supabase Storage に保存され、公開 URL が返る。

## 特徴

- **一貫性が強い** (Subject/Element Binding で顔・服・ブランドを保持)
- **物理整合・シネマティック**品質が高い
- **コスト良好** (10 秒 + 音声で約 $1.68、旧 Veo 3.1 Fast の 42%)
- **最大尺 15 秒**、10 秒まで高品質保証

## いつ使うか

- ダッシュボード/HP/LP でヒーロー動画やループ動画が必要
- ユーザーから「この画像を動画にして」「動きをつけて」系の要望
- 編集要望 (`<dan-context>`) で `<img>` が対象、かつ文面が動画化を示唆 (「動かして」「動画に」「アニメーションに」)

## API

### 生成 (text-to-video または image-to-video)

```
POST /api/v1/videos/generate
{
  "prompt": "Cinematic wide shot, documentary style. Slow dolly in.",
  "aspect_ratio": "16:9",             // "16:9" | "9:16" | "1:1"
  "duration": "5",                     // "5" or "10" (秒)
  "reference_image_url": null,         // 省略 = text-to-video / URL = image-to-video
  "project_id": "xxx"
}
```

返り値:
```json
{
  "id": "...",
  "url": "https://....supabase.co/storage/.../text-to-video/xxx.mp4",
  "kind": "text-to-video" | "image-to-video",
  "aspect_ratio": "16:9",
  "model": "kling-3.0-pro",
  ...
}
```

## duration / aspect_ratio の選び方

| 用途 | duration | aspect_ratio |
|---|---|---|
| ヒーロー動画 (LP 横長) | 10 | 16:9 |
| モバイル縦・SNS ショート | 5〜10 | 9:16 |
| 正方形 (SNS、アイコン) | 5 | 1:1 |
| ループ背景 (単純な動き) | 5 | 16:9 |

## プロンプトのコツ (Kling 系)

英語プロンプト推奨。日本語も通るが英語の方が精度高い。

- **カメラワーク明示**: "slow dolly in", "tracking shot left to right", "static wide shot", "handheld documentary style"
- **ライティング**: "cinematic golden hour", "soft overhead lighting", "industrial fluorescent lighting"
- **物体の動き**: "the welder's arm moves steadily across the beam", "camera follows the truck as it drives through the garage"
- **スタイル**: "photorealistic", "documentary", "commercial shot"
- **禁止表現**: 過度に複雑な同時動作、5 人以上の人物、高速アクション (腕・指が破綻しやすい)

## 注意

- **生成は 3〜6 分**かかる。API コールは完了待ちでブロックする (非同期ポーリング内部実装)
- 返ってきた URL は **MP4 動画**。`<img>` に入れると動かない。対象ファイルのタグを書き換える:

  ```tsx
  // before
  <img src="/hero.jpg" alt="..." />

  // after
  <video
    src="https://.../hero.mp4"
    autoPlay loop muted playsInline
    className="..."
  />
  ```

- `autoPlay loop muted playsInline` は LP で必須 (ブラウザ自動再生の制約)
- **overlay (暗転・ぼかし・グラデーション) は独立した div を作らず、`<video>` 自体に CSS で適用する**
  - ❌ `<div className="absolute inset-0 bg-black/40">` を video の上に重ねる
  - ✅ `<video className="... brightness-75">` or `style={{ filter: 'brightness(0.75) blur(2px)' }}`
  - 理由: overlay div があるとクリック時に overlay が選択されて、Inspector で video を掴めなくなる

## ⚠️ 重要: アスペクト比の事前確認 (黒帯を作らない)

image-to-video で生成する時、**元画像と `aspect_ratio` が食い違うと動画に黒帯が焼き込まれる**。以下を必ず事前チェック:

1. **元画像のアスペクト比を測る**
   - ファイルがローカルにあれば `PIL.Image.open(path).size`
   - URL の場合は HTTP 経由で取得してから PIL で開く
   - HTML 上の `<img>` なら `naturalWidth / naturalHeight`

2. **想定用途から target aspect を決める** (上の表参照)

3. **不一致なら選ぶ**:
   - (a) 元画像を target aspect で作り直す (image-gen `size: "1792x1024"` で 16:9、`"1024x1792"` で 9:16)
   - (b) target aspect を元画像に合わせる (元画像が 1:1 なら `aspect_ratio: "1:1"`)

4. **両方の選択肢に迷ったら用途優先**。「ヒーロー動画」と言われたら 16:9 固定で、元画像が 1:1 なら (a) で作り直す

## Python 直接呼び出し

```python
from app.services.video_generation_service import VideoGenerationService

svc = VideoGenerationService()
result = await svc.generate(
    prompt="Cinematic wide shot, documentary style. A Japanese mechanic in navy work uniform walks across a specialty-vehicle garage floor at golden hour. Slow dolly in.",
    user_id=current_user_id,
    project_id=project_id,
    aspect_ratio="16:9",
    duration="10",
)
print(result["url"])
```

## 落とし穴

- **FAL_KEY 必須**: `.env` に `FAL_KEY=fal_...` を設定。未設定だと RuntimeError
- **10 秒の prompt 複雑度**: 10 秒で複雑なシーン切替を指示すると破綻しやすい。**5 秒で試作 → 納得したら 10 秒**で本番
- **人物動作の注意**: 腕・指の融合が散発的に起こる。人物の手アップなど繊細なカットは複数回生成して当たりを取る or 静止人物にする
- **商標・実在人物**: 拒否される or 品質落ちる
- **モデル ID (DB 記録)**: `kling-3.0-pro`
- **fal エンドポイント**:
  - T2V: `fal-ai/kling-video/v3/pro/text-to-video`
  - I2V: `fal-ai/kling-video/v3/pro/image-to-video`
- バケット `generated-videos` が無ければサービスが自動作成 (public)
- ファイルサイズ大 (数 MB)。LP 埋め込み時は `preload="metadata"` で初期ロードを軽くするのも手
