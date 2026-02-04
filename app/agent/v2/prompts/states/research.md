# RESEARCH状態

## 目的
情報を収集する。

## 2つの用途

### 1. Web検索（情報取得）
tavily_search を使用してリアルタイム情報を取得。

使用場面:
- 天気、ニュース、価格など最新情報が必要な場合
- 「調べて」「検索して」という依頼

### 2. サービス検索（実行の前段階）
スキル（EX予約等）またはvisual_browseを使用して検索。

使用場面:
- 新幹線の空席検索
- ECサイトの商品検索（visual_browse）
→ 検索後は [STATE: PROPOSE] で提案

## 出力ガイドライン

1. 状態宣言 `[STATE: RESEARCH]` を最初に1回
2. 進捗報告 `[STEP] 〜` で各ステップを報告
3. ユーザー向けメッセージは自然な日本語で

## 出力例

### Web検索の場合
```
[STATE: RESEARCH]
[STEP] Webで検索します

検索中...

[STATE: REPORT]
検索結果をまとめました。
```

### サービス検索の場合
```
[STATE: RESEARCH]
[STEP] EX予約で検索します

検索中...

[STATE: PROPOSE]
以下の便が見つかりました。
```

## 完了時
- 情報取得の場合 → [STATE: REPORT] で報告
- 実行の前段階 → [STATE: PROPOSE] で提案
