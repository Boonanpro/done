---
name: studio
description: >
  動画の企画・生成・編集を行うスキル。
  デモ動画、Vlog、チュートリアル等あらゆるテイストに対応する。
  ユーザーが「動画」「映像」「ムービー」「スタジオ」と言った場合や、
  プロジェクトの計画に動画制作が含まれる場合に使用する。
display_name: ダンスタジオ
updated: 2026-03-20
---

# ダンスタジオ

動画の企画・生成・編集を行うスキル。

## 動画制作ワークフロー

### 必須ルール: Bash で Playwright/FFmpeg を直接実行しない

動画の録画・エンコードには **必ず専用MCPツールを使うこと**。
Bashツールで `python record.py` や `ffmpeg` を直接実行すると、
出力データがCLIのメモリに蓄積してクラッシュする（4GBヒープ上限）。

### 使用するツール

| ツール | 用途 |
|--------|------|
| `studio_record` | HTMLをPlaywright headlessで録画 → .webm生成 |
| `studio_encode` | FFmpegで変換（WebM→MP4、解像度変更等） |
| `studio_probe` | 動画のメタ情報取得（コーデック、解像度、長さ） |
| `studio_extract_frame` | 指定時刻のフレームをPNG抽出（内容検証用） |
| `send_file` | 完成動画をチャットUIに送信 |

### 典型的なフロー

```
1. HTMLアニメーションを作成（write_file）
2. studio_record(html_path, output_dir, duration_sec)  → .webm
3. studio_encode(input_path, output_path, width=1920, height=1080)  → .mp4
4. studio_extract_frame(video_path, "5", output_path)  → 内容確認
5. send_file(file_path)  → ユーザーに送信
```

### serve_dir の使い方

HTMLに画像や動画をファイルパスで参照している場合、`file://` ではCORS制限で読み込めない。
`serve_dir` を指定すると一時HTTPサーバーが立ち上がり、全素材が正しく読み込まれる。

```
studio_record(
  html_path="D:/dan-workspace/proposals/demo.html",
  output_dir="D:/dan-workspace/proposals/output",
  duration_sec=52,
  serve_dir="D:/dan-workspace/proposals"  # このディレクトリがHTTPルートになる
)
```

### base64画像について

HTMLにbase64画像を埋め込むとファイルサイズが巨大になりブラウザがクラッシュする。
代わりに `serve_dir` を指定して通常のファイルパスで参照すること。

## 学習パターン

`~/.dan/workspace/learned/studio/learned.md` を参照。
