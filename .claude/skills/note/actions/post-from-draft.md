# システムの下書きからnoteへ投稿

## 概要
done投稿システムに保存された下書き（清書済み）をnoteに投稿する。

## 前提
- noteにログイン済み
- メール認証完了済み
- 下書きIDが指定されていること

## 手順

### 1. 清書済みコンテンツを取得
- API `GET /api/v1/notes/polish/{draft_id}` で清書データを取得
- 清書がない場合は、元の下書き `GET /api/v1/notes/drafts/{draft_id}` を使用

### 2. noteエディタを開く
- `browser_open` で `https://editor.note.com/new` を開く
- エディタが表示されることを確認

### 3. 記事を入力
- タイトル欄に清書後のタイトルを入力
- 本文欄に `full_text` の内容を入力
  - Markdownの見出し（##）はエディタの見出し機能で変換
  - **太字** はエディタの太字機能で変換
  - 段落ごとにEnterで入力

### 4. タグを設定
- 清書データの `tags` をハッシュタグとして設定

### 5. 有料/無料設定
- ユーザーの指定に従う
- 有料の場合: 価格をユーザーに確認（**Red判定**）
- 無料の場合: そのまま進む

### 6. 公開
- 内容を確認して「公開」または「下書き保存」
- 公開後のURLを取得

### 7. 記録
- API `POST /api/v1/notes/posts` で投稿記録を保存
  ```json
  {
    "draft_id": "xxx",
    "note_url": "https://note.com/mickey_writer/n/xxxxx",
    "published": true
  }
  ```
- ユーザーに完了報告
