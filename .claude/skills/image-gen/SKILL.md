---
name: image-gen
description: GPT Image 2 (OpenAI) 経由の画像生成/編集。ヒーロー画像・イラスト・日本語テキスト焼き込み・装飾素材が必要な時に使う。
---

# image-gen スキル

GPT Image 2 (OpenAI、2026-04 公開) で画像を生成・編集する。生成物は Supabase Storage に保存され、公開 URL が返る。

## 特徴

- **日本語テキスト描画が高精度** (仮名・漢字ともほぼ 100% 正確) → HP ヒーロー画像に日本語コピーを焼き込む用途に最適
- reasoning 搭載: 描画前に構図プランニングを行う
- 複数画像でキャラ・レイアウト一貫性を保てる

## いつ使うか

- ダッシュボード/HP/ツール制作でヒーロー画像やイラストが必要
- 日本語テキスト入りのデザイン画像 (バナー、提案書、LP)
- 既存画像を別物に置き換える時 (「この画像を〜に変えて」)
- 編集要望 (`<dan-context>kind: element-comment`) で `<img>` 要素が対象、かつユーザー文面が「画像を〜にして」系

## API

### 生成 (text-to-image)

```
POST /api/v1/images/generate
{
  "prompt": "詳細な画像プロンプト (構図・スタイル・ライティング・色調を具体的に)",
  "size": "1024x1024" | "1792x1024" | "1024x1792" | "auto",
  "quality": "low" | "medium" | "high" | "auto",
  "project_id": "xxx"
}
```

返り値:
```json
{
  "id": "...",
  "url": "https://....supabase.co/storage/.../generate/xxx.png",
  "prompt": "...",
  "kind": "generate",
  "size": "1024x1024",
  ...
}
```

### 編集 (image-to-image)

```
POST /api/v1/images/edit
{
  "prompt": "変更内容 (例: 背景をビーチにして、被写体はそのまま)",
  "reference_url": "https://元画像のURL",
  "project_id": "xxx"
}
```

## quality と料金の目安

| quality | 1024x1024 単価 | 用途 |
|---|---|---|
| low | 約 $0.006 | 試作・サムネ |
| medium | 約 $0.053 | 日常用途 |
| **high** | 約 **$0.211** | 本番 HP ヒーロー等 (デフォルト) |

## size の選び方

| 用途 | size |
|---|---|
| ヒーロー (LP 横長) | `1792x1024` |
| モバイル縦 / スマホ 9:16 | `1024x1792` |
| 正方形 (SNS、アイコン) | `1024x1024` |

## 典型フロー: HP ヒーロー画像を生成

1. ユーザー要望を画像プロンプトに翻訳。日本語テキスト入れるなら prompt にそのまま日本語で書く
2. `POST /images/generate` with `size: "1792x1024"`, `quality: "high"`
3. 返ってきた `url` を対象ファイル (例: `frontend/src/app/demo/yoshikawa-hp/page.tsx`) の `<img src>` に埋め込み
4. HMR で即プレビュー反映

## Python 直接呼び出し

```python
from app.services.image_generation_service import ImageGenerationService

svc = ImageGenerationService()
result = await svc.generate(
    prompt="プロ向けサービスのヒーロー画像。日本語コピー『特装の現場を、もっと賢く』を中央に配置。白背景ミニマル。",
    user_id=current_user_id,
    project_id=project_id,
    size="1792x1024",
    quality="high",
)
print(result["url"])
```

## 落とし穴

- **overlay (暗転・ぼかし) は独立 div を作らず、`<img>` 自体に CSS filter で適用**
  - ❌ `<div className="absolute inset-0 bg-black/40">` を重ねる
  - ✅ `<img style={{ filter: 'brightness(0.75) blur(2px)' }}>` or Tailwind `brightness-75 blur-sm`
- prompt 弱いと平凡。構図・スタイル・ライティング・色調を必ず指定
- 生成は 10〜30 秒 (reasoning ありのため少し長め)。UI 側はローディング必須
- 商標ロゴ・実在人物は拒否される
- モデル ID: **`gpt-image-2`**
- 認証: `OPENAI_API_KEY` (サーバ側で .env から自動取得)
- 保存先バケット `generated-images` が無ければサービスが自動作成 (public)
