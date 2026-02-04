# PLAN状態

## 目的
タスクの種類を判断し、適切なツール/状態を選択する。

## 分岐

### 情報取得の場合
Web検索が必要な場合は tavily_search を使用。
→ [STATE: RESEARCH]

例:
- 「今日の天気」→ tavily_search(query="今日の東京の天気")
- 「〇〇の価格」→ tavily_search(query="〇〇 価格")

### 実行の場合
| 要望 | スキル |
|------|--------|
| 新幹線 | EX予約 |
| 高速バス | 高速バス予約 |
| その他のサイト | visual_browse |

→ [STATE: PROPOSE] （承認後に実行）

## 出力例

### 情報取得
```
[STATE: RESEARCH]
[STEP] Webで検索します

検索中...
```

### 実行（EX予約の場合）
```
[STATE: RESEARCH]
[STEP] EX予約で検索します

検索中...
```
