---
name: image-gen
description: Nano Banana (Gemini 2.5 Flash Image) 経由の画像生成/編集。ヒーロー画像・イラスト・装飾素材が必要な時に使う。
---

# image-gen スキル

Nano Banana（Gemini 2.5 Flash Image）で画像を生成・編集する。生成物は Supabase Storage に保存され、公開 URL が返る。

## いつ使うか

- ダッシュボード/HP/ツール制作でヒーロー画像やイラストが必要
- 既存画像を別物に置き換える時（「この画像を〜に変えて」）
- 編集要望（`<dan-context>kind: element-comment`）で `<img>` 要素が対象、かつユーザー文面が「画像を〜にして」系

## API

いずれもオーナーのアクセストークン必須（プロジェクトを開いている = 認証済み）。

### 生成（ゼロから、text-to-image）

```
POST /api/v1/images/generate
{
  "prompt": "詳細な画像プロンプト（英語推奨、構図・スタイル・ライティング・色調を具体的に）",
  "project_id": "xxx"   // 省略可、履歴紐づけ用
}
```

返り値:
```json
{
  "id": "...",
  "url": "https://....supabase.co/storage/.../generate/xxx.png",
  "prompt": "...",
  "kind": "generate",
  ...
}
```

### 編集（既存画像を元に変更、image-to-image）

```
POST /api/v1/images/edit
{
  "prompt": "変更内容を具体的に（例: 背景をビーチにして、被写体はそのまま）",
  "reference_url": "https://元画像のURL",
  "project_id": "xxx"
}
```

## 典型フロー：ダッシュボードのヒーロー画像を差し替え

1. ユーザー要望を画像プロンプトに翻訳（英語、詳細に）
2. `POST /images/generate` または `/images/edit` を叩く
3. 返ってきた `url` を対象ファイル（例: `frontend/src/app/demo/xxx/page.tsx`）の `<img src>` に埋め込み
4. Next.js `<Image>` を使う場合、`next.config.ts` の `images.remotePatterns` に Supabase ドメインが入っているか確認（無ければ追加）
5. HMR でプレビュー自動反映

## Pythonからの直接呼び出し（バックエンド内）

```python
from app.services.image_generation_service import ImageGenerationService

svc = ImageGenerationService()
result = await svc.generate(
    prompt="Minimal SaaS hero: abstract blue geometric, soft gradient, 16:9",
    user_id=current_user_id,
    project_id=project_id,  # optional
)
print(result["url"])  # 使う URL
```

## 落とし穴

- prompt が弱いと平凡になる。構図・スタイル・ライティング・色調を必ず指定
- 生成は 5〜15 秒。UI 側はローディング必須
- 商標ロゴ・実在人物は拒否される
- モデル ID は **`gemini-2.5-flash-image`** （`-preview` を付けると 404）
- 保存先バケット `generated-images` が無ければサービスが自動作成する（public）
