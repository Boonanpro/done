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

## 現在の情報
- 現在時刻: {current_datetime}
- タイムゾーン: 日本時間 (JST/UTC+9)

## ユーザーの要望
{wish}

## タスク
ユーザーの要望を分析し、構造化してください。

{rules}

## 出力形式（必ずこの形式で出力）

まず、思考過程を1行ずつ [STEP] で出力してください：
[STEP] 思考ステップ1
[STEP] 思考ステップ2
[STEP] 思考ステップ3
（必要なだけ続ける）

次に、[RESULT] と [/RESULT] の間にJSONを出力してください：
[RESULT]
{{
  "intent": "何をしたいか（1文で）",
  "task_type": "travel / purchase / payment / reservation / phone / other のいずれか",
  "details": {{
    "departure": "出発地（駅名、空港名など）",
    "arrival": "到着地（駅名、空港名など）",
    "date": "日付（YYYY-MM-DD または「明日」など）",
    "time": "時刻（HH:MM または「18時」など）",
    "product": "商品名（購入の場合）",
    "quantity": "数量（購入の場合）"
  }},
  "constraints": {{}},
  "deadline": "いつまでに",
  "assumptions": ["仮定した項目とその値"]
}}
[/RESULT]

**重要**: 
- [STEP] は1行に1つの思考
- [RESULT] の中はJSONのみ（reasoning_stepsは不要）
- detailsには上記のフィールドを必ず使用すること
"""

# ============================================================
# PLANプロンプト
# ============================================================

PLAN_PROMPT = """
あなたはタスクを計画するアシスタントです。

## INTAKEの結果
{intake_result}
{execution_history_section}
## タスク
このタスクを実行するための計画を立ててください：

1. tasks: 実行すべきサブタスク（順序付き）
2. tools: 必要なツール/サービス（executor名）
3. stop_conditions: いつ完了とみなすか
4. risks: リスク・注意点
5. reasoning_steps: 推論過程（日本語の配列）

## reasoning_stepsの書き方（重要）
自問自答形式で、なぜそのツールを選んだかの根拠を書いてください：

良い例：
- 「新幹線で行きたい」→ EX予約が最適。在来線や飛行機は対象外。
- 新大阪→博多はのぞみで約2時間半。EX予約なら空席確認と予約が一括でできる。
- 高速バスという選択肢もあるが、時間優先なら新幹線の方が良いだろう。

悪い例：
- ex_reservationで検索する ← なぜ？が書かれていない

## 利用可能なツール
- web_search: 一般的なWeb検索（Tavily + Jina AI Reader）
- ex_reservation: EX予約（新幹線）- ログインが必要
- amazon: Amazon商品購入
- rakuten: 楽天商品購入
- highway_bus: 高速バス予約
- bank_transfer: 銀行振込
- voice: 電話発信

## 重要なルール
- **具体的な情報（列車名、料金、商品名など）は推測しない**
- 具体的な情報はExecutorの検索結果から取得する
- 計画段階では「新幹線を検索する」のように抽象的に記述する
- **過去に失敗したツールは避け、代替手段を検討する**

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
    from datetime import datetime
    import pytz
    
    # 現在時刻（日本時間）
    jst = pytz.timezone('Asia/Tokyo')
    now = datetime.now(jst)
    current_datetime = now.strftime("%Y年%m月%d日 %H:%M:%S（%A）")
    
    rules = DEFAULT_RULES
    
    # ユーザーの傾向があれば追加（将来のPhase 5用）
    if user_preferences:
        rules += "\n\n## このユーザーの傾向\n"
        for key, value in user_preferences.items():
            rules += f"- {key}: {value}\n"
    
    return INTAKE_PROMPT.format(wish=wish, rules=rules, current_datetime=current_datetime)


def get_plan_prompt(intake_result: dict, execution_history: list = None) -> str:
    """
    PLANプロンプトを生成
    
    Args:
        intake_result: ユーザーの要望
        execution_history: 過去の実行履歴（失敗情報含む）
    """
    import json
    
    # 実行履歴があれば追加
    execution_history_section = ""
    if execution_history:
        failures = [r for r in execution_history if not r.get("success")]
        if failures:
            execution_history_section = "\n## 過去の実行履歴（注意が必要）\n"
            for f in failures:
                execution_history_section += f"- ❌ {f['tool']}の{f['action']}に失敗: {f.get('error', '不明なエラー')}\n"
            execution_history_section += "\n"
    
    return PLAN_PROMPT.format(
        intake_result=json.dumps(intake_result, ensure_ascii=False, indent=2),
        execution_history_section=execution_history_section,
    )


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

