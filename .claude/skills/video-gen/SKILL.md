---
name: video-gen
description: Veo 3.1 Fast 経由の動画生成/image-to-video。ヒーロー動画・ループ動画・アニメーションが必要な時に使う。
---

# video-gen スキル

Veo 3.1 Fast (Google) で動画を生成・既存画像から動画化する。生成物は Supabase Storage に保存され、公開 URL が返る。

## いつ使うか

- ダッシュボード/HP/LP でヒーロー動画やループ動画が必要
- ユーザーから「この画像を動画にして」「動きをつけて」系の要望
- 編集要望（`<dan-context>`）で `<img>` が対象、かつ文面が動画化を示唆（「動かして」「動画に」「アニメーションに」）

## API

### 生成（text-to-video または image-to-video）

```
POST /api/v1/videos/generate
{
  "prompt": "波が静かに打ち寄せる、黄金のサンセット、ゆっくり映画的に",
  "aspect_ratio": "16:9",              // "16:9" | "9:16" | "1:1"
  "reference_image_url": null,          // 省略 or null = text-to-video
                                       // URL を入れると image-to-video
  "project_id": "xxx"                   // 履歴紐づけ、省略可
}
```

返り値:
```json
{
  "id": "...",
  "url": "https://....supabase.co/storage/.../text-to-video/xxx.mp4",
  "kind": "text-to-video" | "image-to-video",
  "prompt": "...",
  "aspect_ratio": "16:9",
  ...
}
```

## 注意

- **生成は 30秒〜2分かかる**。API コールは完了待ちでブロックする（非同期ポーリング内部実装）
- 返ってきた URL は **MP4 動画**。`<img>` に入れると動かない。対象ファイルのタグを書き換える：

  ```tsx
  // before
  <img src="/hero.jpg" alt="..." />

  // after
  <video src="https://.../hero.mp4" autoPlay loop muted playsInline className="..." />
  ```

- `autoPlay loop muted playsInline` は LP で必須（ブラウザ自動再生の制約）
- `<Image>` コンポーネントは不可。`<video>` を使う
- **overlay（暗転・ぼかし・グラデーション）は独立した div を作らず、`<video>` 自体に CSS で適用する**
  - ❌ `<div className="absolute inset-0 bg-black/40">` を video の上に重ねる
  - ✅ `<video className="... brightness-75">` or `style={{ filter: 'brightness(0.75) blur(2px)' }}`
  - 理由: overlay div があるとクリック時に overlay が選択されて、Inspector で video を掴めなくなる。filter なら video 自体のプロパティとして編集できる

## 典型フロー：既存画像を動画化

1. 対象 `<img>` の src を取得（`<dan-context>` の `html` から `src="..."` を抽出）
2. `POST /videos/generate` に `reference_image_url` として渡す
3. 完了後に返った URL を使って、ファイルの `<img>` を `<video>` に書き換える
4. HMR で自動反映

## Python から直接呼び出し

```python
from app.services.video_generation_service import VideoGenerationService

svc = VideoGenerationService()
result = await svc.generate(
    prompt="Subtle cinematic parallax on the product screenshot",
    user_id=current_user_id,
    project_id=project_id,
    aspect_ratio="16:9",
    reference_image_url="https://元画像のURL",  # image-to-video
)
print(result["url"])
```

## ⚠️ 重要: アスペクト比の事前確認（黒帯を作らない）

image-to-video で生成する時、**元画像と `aspect_ratio` が食い違うと動画に黒帯が焼き込まれる**。以下を必ず事前チェック:

1. **元画像のアスペクト比を測る**
   - ファイルがローカルにあれば `PIL.Image.open(path).size`
   - URL の場合は HTTP 経由で取得してから PIL で開く
   - HTML 上の `<img>` なら `naturalWidth / naturalHeight`

2. **想定用途から target aspect を決める**
   | 用途 | aspect_ratio |
   |---|---|
   | LP / ヒーロー / 一般ウェブ | `16:9` |
   | モバイル縦 / ストーリー | `9:16` |
   | アイコン / アバター / SNS 正方形 | `1:1` |

3. **不一致なら選ぶ**:
   - **(a)** 元画像を target aspect で作り直す（image-gen `size: "1536x1024"` で 16:9 相当、「1024x1536」で 9:16 相当、「1024x1024」で 1:1）→ その後 video-gen
   - **(b)** target aspect を元画像に合わせる（元画像が 1:1 なら `aspect_ratio: "1:1"`）

4. **両方の選択肢に迷ったら用途優先**。「ヒーロー動画」と言われたら 16:9 固定で、元画像が 1:1 なら (a) で作り直す

ユーザーからわざわざ黒帯指摘をされる前に、自前でアスペクト揃えて生成する。

## その他の落とし穴

- prompt は詳細に。「何が動くのか」「速度」「カメラワーク」「時間」を具体的に
- 実在人物・著名人・商標は拒否される
- モデル ID: **`veo-3.1-fast-generate-preview`**（preview だが fast 版で速い、コスパ良好）
- バケット `generated-videos` が無ければサービスが自動作成（public）
- ファイルサイズ大（数 MB）。LP 埋め込み時は `preload="metadata"` で初期ロードを軽くするのも手
