# Instagram オーガニック投稿（Content Publishing API）

広告（課金）ではなく、IG ビジネスアカウントへの**通常投稿**を API で行う。
`scripts/meta_ads_cli.py ig-post` が内部で3ステップを処理する。

## 前提

- **Instagram ビジネスアカウント**であること（クリエイターアカウントは Content Publishing 非対応）。
- IG が Facebook ページに連携済みで、connect 時に `--ig-user-id` を保存していること。
- スコープ: `instagram_business_basic` + `instagram_business_content_publish`（+ `pages_show_list`）。
  他社アカウントへの投稿は App Review 済みであること。

## 制約

- **100 投稿 / 24時間**（全種別合計）。
- **Reels は90秒以下**（超える動画は Reels として publish 不可）。
- 画像/動画は**公開到達可能な URL** で渡す（Meta 側が取得する）。ローカルファイル直は不可
  → 先に公開ストレージ（成果物公開や Supabase Storage 等）へ上げて URL 化する。

## 使い方

画像:
```bash
python scripts/meta_ads_cli.py ig-post \
  --caption "本文（ハッシュタグ含む）" \
  --image-url "https://.../image.jpg" \
  --confirm
```

Reels（動画）:
```bash
python scripts/meta_ads_cli.py ig-post \
  --caption "本文" \
  --video-url "https://.../reel.mp4" \
  --confirm
```

## 内部の3ステップ（CLI が自動処理）

1. `POST /{ig_user_id}/media` … 画像なら `image_url`、動画なら `media_type=REELS` + `video_url`、`caption`。
   → コンテナ ID（`creation_id`）を取得。
2. （動画のみ）`GET /{creation_id}?fields=status_code` を `FINISHED` までポーリング（最大~150秒）。
3. `POST /{ig_user_id}/media_publish` … `creation_id` を渡して公開。→ `ig_media_id` を返す。

## ⚠️ 公開ゲート

`--confirm` 無しでは `needs_approval: true` と投稿内容を返して**投稿しない**。
キャプション・メディアをユーザーに見せ、承認を得てから `--confirm` を付けて再実行する。

## まだ無いもの（将来）

- カルーセル（複数画像）投稿、ストーリーズ、予約投稿。
- コメント/インサイト取得。必要になったらこの CLI に subcommand を足す。
