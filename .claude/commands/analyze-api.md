# analyze-api

FastAPIのルートファイルを解析し、APIエンドポイント一覧を抽出・整理するコマンド。

## 使い方

```
/analyze-api [ディレクトリパス]
```

- ディレクトリパス（オプション）: 解析対象のディレクトリ。省略時は `app/api/`

## 出力形式

各ルートファイルごとに以下の情報を抽出：
- ルーターのprefix
- エンドポイント一覧（HTTPメソッド、パス、説明）

## 実行手順

1. 指定されたディレクトリ（デフォルト: `app/api/`）内の `*_routes.py` ファイルを検索
2. 各ファイルを読み込み、以下のパターンを抽出：
   - `router = APIRouter(prefix="...")` からプレフィックスを取得
   - `@router.get`, `@router.post`, `@router.patch`, `@router.put`, `@router.delete`, `@router.websocket` デコレータからエンドポイントを取得
   - 関数のdocstringから説明を取得
3. 結果をMarkdownテーブル形式で出力

## 出力例

```markdown
## chat_routes.py
- Prefix: `/chat`

| Method | Path | Description |
|--------|------|-------------|
| POST | /register | ユーザー登録 |
| POST | /login | ログイン |
| GET | /me | ユーザー情報取得 |
| WS | /ws/chat | WebSocketチャット |
```

## 解析対象パターン

```python
# ルーター定義
router = APIRouter(prefix="/chat", tags=["chat"])

# エンドポイント定義
@router.get("/path")
@router.post("/path", response_model=Model)
@router.patch("/path/{id}")
@router.put("/path/{id}")
@router.delete("/path/{id}")
@router.websocket("/ws/path")
```

## 注意事項

- FastAPI形式のルートファイルのみ対応
- デコレータは `@router.` で始まるものを対象
- 複雑なデコレータ（複数行にまたがるもの等）は一部取得できない場合あり
