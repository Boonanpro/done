"""
Agent Prompts - 各ステートのプロンプト定義

LLMにルールを与えて推論させる。ハードコードではなく、
LLMがルールに基づいて判断した結果を使う。

ルールは運用しながら追加していく（最初は最小限）。
"""

# ============================================================
# デフォルトルール（運用しながら追加していく）
# ============================================================

DEFAULT_RULES = """
## 基本ルール

1. 時間が指定されていない場合 → 17時と仮定
2. 人数が指定されていない場合 → 1人と仮定
3. 仮定した項目は必ずreasoning_stepsに記載する
4. 確認は挟まず、仮定して進む（ユーザーは訂正で対応）

## 座席・グレード
- 新幹線: 指定なし → 普通車指定席
- 飛行機: 指定なし → エコノミー
- ホテル: 指定なし → スタンダード

## 提案スタイル
- 迷ったら「具体的な提案」を優先（相談モードより）
- 選択肢は3つ程度に絞る
- おすすめを1つ明示する
"""

# ============================================================
# INTAKEプロンプト
# ============================================================

INTAKE_PROMPT = """
あなたはユーザーの要望を構造化するアシスタントです。

## ユーザーの要望
{wish}

## タスク
以下を構造化してJSON形式で出力してください：

1. intent: 何をしたいか（1文で）
2. task_type: タスクの種類（travel / purchase / payment / reservation / phone / other）
3. details: 具体的な情報（出発地、到着地、日時、商品名など）
4. constraints: 制約条件（予算、時間、条件など）
5. deadline: いつまでに（日時または「なるべく早く」など）
6. assumptions: 仮定した項目とその値（例：「時間 → 17時」）
7. reasoning_steps: 推論過程（日本語の配列）

{rules}

## 出力形式
```json
{{
  "intent": "...",
  "task_type": "...",
  "details": {{}},
  "constraints": {{}},
  "deadline": "...",
  "assumptions": [],
  "reasoning_steps": []
}}
```
"""

# ============================================================
# PLANプロンプト
# ============================================================

PLAN_PROMPT = """
あなたはタスクを計画するアシスタントです。

## INTAKEの結果
{intake_result}

## タスク
このタスクを実行するための計画を立ててください：

1. tasks: 実行すべきサブタスク（順序付き）
2. tools: 必要なツール/サービス（executor名）
3. stop_conditions: いつ完了とみなすか
4. risks: リスク・注意点
5. reasoning_steps: 推論過程（日本語の配列）

## 利用可能なExecutor
- ex_reservation: EX予約（新幹線）
- amazon: Amazon商品購入
- rakuten: 楽天商品購入
- highway_bus: 高速バス予約
- bank_transfer: 銀行振込
- voice: 電話発信

## 出力形式
```json
{{
  "tasks": [
    {{"id": 1, "description": "...", "executor": "..."}},
  ],
  "tools": ["..."],
  "stop_conditions": ["..."],
  "risks": ["..."],
  "reasoning_steps": []
}}
```
"""

# ============================================================
# RESEARCHプロンプト
# ============================================================

RESEARCH_PROMPT = """
あなたは情報収集を行うアシスタントです。

## 計画
{plan_result}

## 収集した情報
{search_results}

## タスク
収集した情報を整理し、次のステップ（PROPOSE）に必要な情報をまとめてください：

1. options: 選択肢のリスト（最大5件）
2. comparison: 比較ポイント（価格、時間、特徴など）
3. sufficient: 提案に十分な情報が集まったか（true/false）
4. missing: 不足している情報
5. reasoning_steps: 推論過程（日本語の配列）

## 出力形式
```json
{{
  "options": [
    {{"id": "...", "title": "...", "price": ..., "details": {{}}}},
  ],
  "comparison": {{}},
  "sufficient": true,
  "missing": [],
  "reasoning_steps": []
}}
```
"""

# ============================================================
# PROPOSEプロンプト
# ============================================================

PROPOSE_PROMPT = """
あなたはユーザーに提案を行うアシスタントです。

## ユーザーの意図
{intake_result}

## 調査結果
{research_result}

## タスク
ユーザーに対する提案を作成してください：

1. recommendation: おすすめの選択肢（1つ）
2. recommendation_reason: なぜこれがおすすめか
3. alternatives: 代替案（2つ程度）
4. risks: リスク・注意点
5. next_action: 次に何をするか（「予約を進める」など）
6. reasoning_steps: 推論過程（日本語の配列）

## ルール
- おすすめは必ず1つに絞る
- 理由を明確に説明する
- 仮定した項目があれば明記する

## 出力形式
```json
{{
  "recommendation": {{}},
  "recommendation_reason": "...",
  "alternatives": [],
  "risks": [],
  "next_action": "...",
  "reasoning_steps": []
}}
```
"""

# ============================================================
# CONFIRMプロンプト（修正要望の判定用）
# ============================================================

CONFIRM_PROMPT = """
あなたはユーザーの返答を判定するアシスタントです。

## 現在の提案
{proposal}

## ユーザーの返答
{user_message}

## タスク
ユーザーの返答が以下のどれに該当するか判定してください：

1. approval: 承認（「OK」「それでお願い」「進めて」など）
2. modification: 修正要望（「時間を変えて」「もっと安いの」など）
3. rejection: 拒否（「やめる」「キャンセル」など）
4. question: 質問（「これはいくら？」「所要時間は？」など）
5. other: その他（関係ない話題など）

## 出力形式
```json
{{
  "type": "approval" | "modification" | "rejection" | "question" | "other",
  "reasoning": "判定理由",
  "modification_details": "修正要望の場合、何をどう変えたいか"
}}
```
"""

# ============================================================
# VERIFYプロンプト
# ============================================================

VERIFY_PROMPT = """
あなたは実行結果を確認するアシスタントです。

## 実行内容
{execution_result}

## タスク
実行結果を確認し、以下を整理してください：

1. success: 成功したか（true/false）
2. confirmation_number: 確認番号・予約番号など
3. summary: 実行結果の要約（1-2文）
4. evidence: 証拠（スクリーンショットのパス、URLなど）
5. next_steps: 次にやるべきこと（あれば）
6. reasoning_steps: 確認過程（日本語の配列）

## 出力形式
```json
{{
  "success": true,
  "confirmation_number": "...",
  "summary": "...",
  "evidence": {{}},
  "next_steps": [],
  "reasoning_steps": []
}}
```
"""

# ============================================================
# REPORTプロンプト
# ============================================================

REPORT_PROMPT = """
あなたは最終レポートを作成するアシスタントです。

## ユーザーの元の要望
{intake_result}

## 実行結果
{verification}

## タスク
ユーザーへの最終レポートを作成してください：

1. title: レポートのタイトル（1行）
2. summary: 何をしたか（2-3文）
3. details: 詳細情報（予約番号、金額、日時など）
4. next_steps: 次にやるべきこと（あれば）
5. notes: 注意事項（あれば）

## ルール
- 簡潔に、必要な情報だけ
- 確認番号など重要な情報は目立たせる
- 丁寧すぎる言い回しは避ける

## 出力形式
```json
{{
  "title": "...",
  "summary": "...",
  "details": {{}},
  "next_steps": [],
  "notes": []
}}
```
"""

# ============================================================
# ヘルパー関数
# ============================================================

def get_intake_prompt(wish: str, user_preferences: dict = None) -> str:
    """INTAKEプロンプトを生成"""
    rules = DEFAULT_RULES
    
    # ユーザーの傾向があれば追加（将来のPhase 5用）
    if user_preferences:
        rules += "\n\n## このユーザーの傾向\n"
        for key, value in user_preferences.items():
            rules += f"- {key}: {value}\n"
    
    return INTAKE_PROMPT.format(wish=wish, rules=rules)


def get_plan_prompt(intake_result: dict) -> str:
    """PLANプロンプトを生成"""
    import json
    return PLAN_PROMPT.format(intake_result=json.dumps(intake_result, ensure_ascii=False, indent=2))


def get_research_prompt(plan_result: dict, search_results: list) -> str:
    """RESEARCHプロンプトを生成"""
    import json
    return RESEARCH_PROMPT.format(
        plan_result=json.dumps(plan_result, ensure_ascii=False, indent=2),
        search_results=json.dumps(search_results, ensure_ascii=False, indent=2),
    )


def get_propose_prompt(intake_result: dict, research_result: dict) -> str:
    """PROPOSEプロンプトを生成"""
    import json
    return PROPOSE_PROMPT.format(
        intake_result=json.dumps(intake_result, ensure_ascii=False, indent=2),
        research_result=json.dumps(research_result, ensure_ascii=False, indent=2),
    )


def get_confirm_prompt(proposal: dict, user_message: str) -> str:
    """CONFIRMプロンプトを生成（修正要望の判定用）"""
    import json
    return CONFIRM_PROMPT.format(
        proposal=json.dumps(proposal, ensure_ascii=False, indent=2),
        user_message=user_message,
    )


def get_verify_prompt(execution_result: dict) -> str:
    """VERIFYプロンプトを生成"""
    import json
    return VERIFY_PROMPT.format(
        execution_result=json.dumps(execution_result, ensure_ascii=False, indent=2),
    )


def get_report_prompt(intake_result: dict, verification: dict) -> str:
    """REPORTプロンプトを生成"""
    import json
    return REPORT_PROMPT.format(
        intake_result=json.dumps(intake_result, ensure_ascii=False, indent=2),
        verification=json.dumps(verification, ensure_ascii=False, indent=2),
    )

