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

## 前回の会話の状態
{previous_state}

## 直近の会話履歴
{conversation_history}

## ユーザーの最新メッセージ
{wish}

## タスク
ユーザーの要望を分析し、構造化してください。

{rules}

## 出力形式（必ずこの形式で出力）

まず、現在行っている作業を1行ずつ [STEP] で出力してください：
[STEP] 新大阪から品川への新幹線を確認
[STEP] 日付は1月20日、19時台の便を検索
[STEP] 1人分、普通車指定席の通路側
（簡潔なアクション表示のみ、分析や説明は不要）

次に、[RESULT] と [/RESULT] の間にJSONを出力してください：
[RESULT]
{{
  "intent": "何をしたいか（1文で）",
  "task_type": "travel / purchase / payment / reservation / phone / follow_up / credentials_providing / other のいずれか",
  "requires_search": true または false,
  "search_query": "検索が必要な場合の検索クエリ（日本語）",
  "details": {{
    "departure": "出発地（駅名、空港名など）",
    "arrival": "到着地（駅名、空港名など）",
    "date": "日付（YYYY-MM-DD または「明日」など）",
    "time": "時刻（HH:MM または「18時」など）",
    "product": "商品名（購入の場合）",
    "quantity": "数量（購入の場合）"
  }},
  "credentials": {{
    "member_id": "会員ID（認証情報提供の場合）",
    "password": "パスワード（認証情報提供の場合）"
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
- requires_search: 最新情報やリアルタイム情報が必要な場合はtrue（例：今日のニュース、天気、株価など）
- search_query: requires_searchがtrueの場合、適切な検索クエリを設定

**task_typeの判定基準**:
- credentials_providing: **最優先判定** - 前回のresearch_resultに"credentials_required": trueがあり、かつユーザーが会員ID・パスワードのような認証情報を提供している場合
  - 例: 「5719671594」と「Bold1315」のような文字列が含まれる
  - credentialsフィールドにmember_idとpasswordを設定すること
- follow_up: 前回「情報不足」で終わり、ユーザーが追加情報（出発地、時刻など）を提供している場合
- other: 雑談、質問、感謝など、タスク実行を伴わない会話
- travel/purchase等: 新しいタスクリクエスト

**重要**: research_resultに"credentials_required": trueがある場合、ユーザーのメッセージに数字や英数字が含まれていれば、それは認証情報の提供と判断してcredentials_providingにすること。
"""

# ============================================================
# PLANプロンプト
# ============================================================

PLAN_PROMPT = """
あなたはタスクを計画するアシスタントです。

## INTAKEの結果
{intake_result}
{execution_history_section}

## 利用可能なツール
- web_search: 一般的なWeb検索（Tavily + Jina AI Reader）
- ex_reservation: EX予約（新幹線）- ログインが必要
- amazon: Amazon商品購入
- rakuten: 楽天商品購入
- highway_bus: 高速バス予約
- bank_transfer: 銀行振込
- voice: 電話発信

## タスク
このタスクを実行するための計画を立ててください。

## 出力形式（必ずこの形式で出力）

まず、現在の作業を1行ずつ [STEP] で出力してください：
[STEP] EX予約で検索
[STEP] ログイン情報が必要
（簡潔なアクション表示のみ）

次に、[RESULT] と [/RESULT] の間にJSONを出力してください：
[RESULT]
{{
  "tasks": [
    {{"id": 1, "description": "...", "executor": "..."}}
  ],
  "tools": ["..."],
  "stop_conditions": ["..."],
  "risks": ["..."]
}}
[/RESULT]

## ナレーションルール（重要）
- **前のステートで確認したことは繰り返さない**
- **現在の作業のみ**記載
- 例: 「EX予約で検索」
- 悪い例: 「ユーザーは新大阪から博多に...」「出発地は...到着地は...」

## 重要なルール
- 具体的な情報（列車名、料金など）は推測しない
- 過去に失敗したツールは避け、代替手段を検討する
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
収集した情報を整理し、提案に必要な情報をまとめてください。

## 出力形式（必ずこの形式で出力）

まず、現在の作業を1行ずつ [STEP] で出力してください：
[STEP] 5件の候補を取得
[STEP] 19時台の便を確認
（簡潔な進捗のみ）

次に、[RESULT] と [/RESULT] の間にJSONを出力してください：
[RESULT]
{{
  "options": [
    {{
      "id": "option_1",
      "title": "のぞみ45号 12:00発",
      "price": 15820,
      "time": "12:00発 → 14:30着",
      "details": {{"seat": "普通車指定席", "duration": "2時間30分"}}
    }}
  ],
  "comparison": {{"price_range": "15000-20000円", "time_range": "2-3時間"}},
  "sufficient": true,
  "missing": []
}}
[/RESULT]

## ナレーションルール（重要）
- **前のステートで確認したことは繰り返さない**
- **新しい発見のみ**記載
- 例: 「3件の候補を取得」
- 悪い例: 「新大阪から博多への新幹線を検索した結果...」

## 重要なルール
- options内のtitle, price, timeは検索結果から正確に引用する
- 推測で値を埋めない（不明なら "不明" とする）
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
ユーザーに対する提案を作成してください。

## 出力形式（必ずこの形式で出力）

まず、現在の作業を1行ずつ [STEP] で出力してください：
[STEP] のぞみ326号が希望に最も近い
[STEP] 通路側の座席を確認
（簡潔な判断のみ）

次に、[RESULT] と [/RESULT] の間にJSONを出力してください：
[RESULT]
{{
  "recommendation": {{
    "title": "のぞみ45号 12:00発 → 14:30着",
    "price": 15820,
    "time": "12:00発",
    "details": "普通車指定席、所要時間2時間30分"
  }},
  "recommendation_reason": "希望の12時発に完全一致",
  "alternatives": [
    {{
      "title": "のぞみ47号 12:30発 → 15:00着",
      "price": 15820,
      "reason": "12時台の代替"
    }}
  ],
  "risks": ["グリーン車の空席状況は要確認"],
  "next_action": "予約を進める"
}}
[/RESULT]

## ナレーションルール（重要）
- **前のステートで確認したことは繰り返さない**
- **新しい判断のみ**記載
- 例: 「19:00発が希望に最も近い」
- 悪い例: 「ユーザーは19時台を希望しており...」

## 重要なルール
- recommendation内のtitle, price, timeは**調査結果から正確に引用**する
- 調査結果にない値は推測しない
- title, price, detailsは必須フィールド
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
実行結果を確認し、成功/失敗と重要な情報を抽出してください。

## 出力形式（必ずこの形式で出力）

まず、確認結果を1行ずつ [STEP] で出力してください：
[STEP] 成功/失敗の判定
[STEP] 重要な情報（予約番号など）
（簡潔に、必要なだけ）

次に、[RESULT] と [/RESULT] の間にJSONを出力してください：
[RESULT]
{{
  "success": true,
  "confirmation_number": "ABC123456",
  "summary": "新幹線を予約しました",
  "evidence": {{"screenshot": "path/to/screenshot.png"}},
  "next_steps": []
}}
[/RESULT]

## ナレーションルール（重要）
- **結果のみ**記載: 成功/失敗、予約番号
- 例: 「→ 予約完了、番号: ABC123456」
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
ユーザーへの最終レポートを作成してください。

## 出力形式（必ずこの形式で出力）

まず、レポート作成過程を1行ずつ [STEP] で出力してください：
[STEP] 完了内容の確認
（簡潔に、1-2行で）

次に、[RESULT] と [/RESULT] の間にJSONを出力してください：
[RESULT]
{{
  "title": "新幹線予約完了",
  "summary": "のぞみ45号を予約しました。",
  "details": {{
    "confirmation_number": "ABC123456",
    "train": "のぞみ45号",
    "date": "2026-01-09",
    "price": 15820
  }},
  "next_steps": [],
  "notes": []
}}
[/RESULT]

## ルール
- 簡潔に、必要な情報だけ
- 確認番号など重要な情報は目立たせる
"""

# ============================================================
# ヘルパー関数
# ============================================================

def get_intake_prompt(wish: str, user_preferences: dict = None, conversation_history: list = None, previous_state: dict = None) -> str:
    """INTAKEプロンプトを生成

    Args:
        wish: ユーザーの最新メッセージ
        user_preferences: ユーザーの傾向（将来のPhase 5用）
        conversation_history: 直近の会話履歴（DBから取得したリスト）
        previous_state: 前回の状態情報（intake_result, current_state等）
    """
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

    # 前回の状態をフォーマット
    if previous_state:
        prev_intake = previous_state.get("intake_result", {})
        prev_current_state = previous_state.get("current_state", "")
        prev_research = previous_state.get("research_result", {})

        previous_state_str = f"- 前回の状態: {prev_current_state}\n"
        if prev_intake.get("intent"):
            previous_state_str += f"- 前回の意図: {prev_intake.get('intent')}\n"
        if prev_intake.get("details"):
            previous_state_str += f"- 前回の詳細: {prev_intake.get('details')}\n"

        # 認証情報が必要だった場合
        if prev_research.get("credentials_required"):
            executor_name = prev_research.get("executor_name", "不明なサービス")
            previous_state_str += f"- **前回の要求**: {executor_name}の認証情報が必要\n"
            previous_state_str += f"- **状態**: 認証情報待ち\n"

        # 情報不足だった場合
        if prev_research.get("missing"):
            missing_items = ", ".join(prev_research.get("missing", []))
            previous_state_str += f"- 不足していた情報: {missing_items}\n"

        # 判定の指示
        if prev_research.get("credentials_required"):
            previous_state_str += "\n**重要**: ユーザーが認証情報（ID・パスワード）を提供している場合、task_type='credentials_providing'を設定してください。"
        else:
            previous_state_str += "\n**重要**: 前回の情報不足を解消するための追加情報が提供された場合、task_type='follow_up'を設定してください。"
    else:
        previous_state_str = "（新しい会話 - 前回の状態なし）"

    # 会話履歴をフォーマット
    if conversation_history:
        history_lines = []
        # 古い順に並べる（reversedで時系列順に）
        for msg in reversed(conversation_history):
            sender = "ユーザー" if msg.get("sender_type") == "human" else "ダン"
            content = msg.get("content", "")
            if content:
                # 長いメッセージは省略
                if len(content) > 200:
                    content = content[:200] + "..."
                history_lines.append(f"{sender}: {content}")
        conversation_history_str = "\n".join(history_lines)
    else:
        conversation_history_str = "（会話履歴なし - 新しい会話の開始）"

    return INTAKE_PROMPT.format(
        wish=wish,
        rules=rules,
        current_datetime=current_datetime,
        previous_state=previous_state_str,
        conversation_history=conversation_history_str
    )


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

    # search_resultsを要約（プロンプトが長すぎる問題を防ぐ）
    summarized_results = []
    for result in search_results:
        if isinstance(result, dict):
            # 各結果から必要な情報のみ抽出
            summarized = {}

            # Web検索結果の場合
            if "results" in result:
                summarized["type"] = "web_search"
                summarized["count"] = len(result.get("results", []))
                # 最初の3件のみ保持（タイトル、URL、要約のみ）
                summarized["results"] = [
                    {
                        "title": r.get("title", ""),
                        "url": r.get("url", ""),
                        "snippet": r.get("content", "")[:300],  # 最初の300文字のみ
                    }
                    for r in result.get("results", [])[:3]
                ]

            # Executor検索結果の場合
            elif "options" in result:
                summarized["type"] = "executor_search"
                summarized["service"] = result.get("service_name", "unknown")
                summarized["count"] = len(result.get("options", []))
                # 最初の5件のみ保持
                summarized["options"] = result.get("options", [])[:5]

            # エラーの場合
            elif "error" in result:
                summarized["type"] = "error"
                summarized["error"] = result.get("error")
                summarized["message"] = result.get("message", "")

            summarized_results.append(summarized)

    return RESEARCH_PROMPT.format(
        plan_result=json.dumps(plan_result, ensure_ascii=False, indent=2),
        search_results=json.dumps(summarized_results, ensure_ascii=False, indent=2),
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

