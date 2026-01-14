# AI秘書システム アーキテクチャ v2

## 現状の問題点

### 1. 会話の文脈が途切れる
- 各状態で新しいLLM呼び出し
- 全てを1つの`user`メッセージとして渡している
- LLMは「自分が何を言ったか」を認識できない

### 2. ファイル構造の問題
- `state_machine.py`が1219行で肥大化
- 責務が混在（状態遷移、LLM呼び出し、ツール実行）
- プロンプトが1ファイルに集約（570行）

### 3. 状態遷移のハードコード
- コードで状態遷移を制御しすぎ
- LLMの判断力を活かせていない

---

## 新アーキテクチャの設計思想

### 原則1: 会話の継続性
ChatGPTと同様に、1つの会話セッション内で状態が進む。
LLMは自分の発言を覚えている。

### 原則2: Progressive Disclosure
必要な情報だけを必要な時に渡す。
状態ごとの指示は、その状態に入った時だけ読み込む。

### 原則3: LLMに判断を委ねる
状態遷移の判断はLLM自身が行う。
コードは宣言を解析して追従する。

---

## ファイル構造

```
app/agent/
├── v2/                          # 新アーキテクチャ
│   ├── __init__.py
│   ├── states.py                # 状態Enum（既存を流用）
│   ├── session.py               # 会話セッション管理
│   ├── runner.py                # メインループ（状態遷移のオーケストレーション）
│   ├── tools.py                 # ツール定義（Executorへの橋渡し）
│   │
│   ├── prompts/
│   │   ├── system.md            # システムプロンプト（ダンの人格）
│   │   └── states/              # 状態ごとの指示
│   │       ├── intake.md
│   │       ├── plan.md
│   │       ├── research.md
│   │       ├── propose.md
│   │       ├── confirm.md
│   │       ├── execute.md
│   │       ├── verify.md
│   │       └── report.md
│   │
│   └── skills/                  # スキル定義（将来のAgent Skills対応）
│       ├── ex_reservation/
│       │   └── SKILL.md
│       ├── amazon/
│       │   └── SKILL.md
│       └── web_search/
│           └── SKILL.md
```

---

## 会話セッション管理 (session.py)

```python
from dataclasses import dataclass, field
from typing import List, Dict, Any, Optional
from enum import Enum

class State(str, Enum):
    INTAKE = "intake"
    PLAN = "plan"
    RESEARCH = "research"
    PROPOSE = "propose"
    CONFIRM = "confirm"
    EXECUTE = "execute"
    VERIFY = "verify"
    REPORT = "report"
    CHAT = "chat"  # 雑談モード

@dataclass
class Session:
    """会話セッション - Messages配列を中心に管理"""

    session_id: str
    user_id: str

    # 会話履歴（これが全て）
    messages: List[Dict[str, str]] = field(default_factory=list)

    # 現在の状態
    current_state: State = State.INTAKE

    # 状態ごとのコンテキスト（必要に応じて保持）
    context: Dict[str, Any] = field(default_factory=dict)

    def add_user_message(self, content: str):
        """ユーザーメッセージを追加"""
        self.messages.append({"role": "user", "content": content})

    def add_assistant_message(self, content: str):
        """アシスタントメッセージを追加"""
        self.messages.append({"role": "assistant", "content": content})

    def add_system_instruction(self, content: str):
        """状態遷移時のシステム指示を追加"""
        # systemロールではなく、assistantの内部思考として追加
        self.messages.append({
            "role": "assistant",
            "content": f"[内部指示] {content}"
        })

    def get_messages_for_llm(self) -> List[Dict[str, str]]:
        """LLMに渡すメッセージ配列を取得"""
        return self.messages.copy()
```

---

## システムプロンプト (prompts/system.md)

```markdown
あなたは「ダン」という名前のAI秘書です。

## あなたの役割
ユーザーの要望を理解し、必要なタスクを実行します。
- 新幹線の予約（EX予約）
- 商品の購入（Amazon、楽天）
- 支払い・振込
- 情報検索
- 日常会話

## 状態遷移
タスクを実行する際は、以下の状態を順番に進みます：

1. **INTAKE**: 要望を理解する
2. **PLAN**: 実行計画を立てる
3. **RESEARCH**: 情報を収集する
4. **PROPOSE**: 提案する
5. **CONFIRM**: ユーザーの承認を得る
6. **EXECUTE**: 実行する
7. **VERIFY**: 結果を確認する
8. **REPORT**: 報告する

## 出力形式
状態を遷移する時は、必ず以下の形式で宣言してください：

[STATE: 状態名]
（思考や行動の内容）

例：
[STATE: PLAN]
EX予約で新幹線を検索します。認証情報が必要です。

## ツール
以下のツールが使えます：
- `search_ex`: EX予約で新幹線を検索
- `book_ex`: EX予約で新幹線を予約
- `search_web`: Web検索
- （他のツールは状態指示で追加）

## 重要なルール
1. ユーザーの発言を正しく理解する（文脈を読む）
2. 必要な情報が不足している場合は確認する
3. 不可逆な操作（予約、購入）は必ず確認を取る
4. 認証情報を受け取ったら、すぐに次のステップに進む
```

---

## 状態指示ファイル例 (prompts/states/intake.md)

```markdown
# INTAKE状態

## 目的
ユーザーの要望を理解し、構造化する。

## やること
1. ユーザーの発言から意図を抽出
2. 必要な情報（出発地、到着地、日時など）を特定
3. 不足している情報があれば確認
4. 十分な情報が揃ったらPLANに進む

## 出力例

### 情報が十分な場合
[STATE: PLAN]
新大阪から博多への新幹線を1月20日19時頃で検索します。

### 情報が不足している場合
出発地はどちらですか？

### 雑談の場合
[STATE: CHAT]
こんにちは！何かお手伝いできることはありますか？
```

---

## メインループ (runner.py)

```python
class AgentRunner:
    """状態機械を駆動するメインループ"""

    def __init__(self, session: Session):
        self.session = session
        self.llm_client = get_llm_client()
        self.state_instructions = {}  # 遅延読み込み

    async def process_message(self, user_message: str) -> str:
        """ユーザーメッセージを処理"""

        # 1. ユーザーメッセージを追加
        self.session.add_user_message(user_message)

        # 2. 現在の状態の指示を読み込み（まだなら）
        if self.session.current_state not in self.state_instructions:
            self._load_state_instruction(self.session.current_state)

        # 3. LLMを呼び出し（Messages配列で）
        response = await self._call_llm()

        # 4. レスポンスから状態遷移を検出
        new_state = self._detect_state_transition(response)
        if new_state and new_state != self.session.current_state:
            self.session.current_state = new_state
            # 新しい状態の指示を読み込み
            self._load_state_instruction(new_state)

        # 5. アシスタントメッセージを追加
        self.session.add_assistant_message(response)

        # 6. ツール呼び出しがあれば実行
        tool_results = await self._execute_tools(response)
        if tool_results:
            # ツール結果を追加して再度LLM呼び出し
            self.session.add_assistant_message(f"[ツール結果] {tool_results}")
            response = await self._call_llm()
            self.session.add_assistant_message(response)

        # 7. ユーザー向けの応答を抽出して返す
        return self._extract_user_response(response)

    async def _call_llm(self) -> str:
        """LLMを呼び出す（Messages配列方式）"""
        system_prompt = self._get_system_prompt()
        messages = self.session.get_messages_for_llm()

        response = await self.llm_client.messages.create(
            model="claude-sonnet-4-20250514",
            max_tokens=2000,
            system=system_prompt,
            messages=messages,
        )
        return response.content[0].text

    def _detect_state_transition(self, response: str) -> Optional[State]:
        """レスポンスから状態遷移を検出"""
        import re
        match = re.search(r'\[STATE:\s*(\w+)\]', response)
        if match:
            state_name = match.group(1).lower()
            try:
                return State(state_name)
            except ValueError:
                pass
        return None

    def _load_state_instruction(self, state: State):
        """状態指示を読み込み（Progressive Disclosure）"""
        path = f"app/agent/v2/prompts/states/{state.value}.md"
        try:
            with open(path, 'r', encoding='utf-8') as f:
                instruction = f.read()
            self.state_instructions[state] = instruction
            # セッションに内部指示として追加
            self.session.add_system_instruction(
                f"現在の状態: {state.value}\n{instruction}"
            )
        except FileNotFoundError:
            pass
```

---

## 会話フローの例

### ユーザー: 「新幹線を予約したい」

```
messages = [
    {"role": "system", "content": "(システムプロンプト)"},
    {"role": "user", "content": "新幹線を予約したい"},
    {"role": "assistant", "content": "[STATE: INTAKE]\n出発地と到着地、日時を教えてください。"},
]
```

### ユーザー: 「新大阪から博多、明日の19時」

```
messages = [
    ...,
    {"role": "user", "content": "新大阪から博多、明日の19時"},
    {"role": "assistant", "content": "[STATE: PLAN]\nEX予約で検索します。認証情報が必要です。\n\n会員IDとパスワードを教えてください。"},
]
```

### ユーザー: 「123456 と password」

```
messages = [
    ...,
    {"role": "user", "content": "123456 と password"},
    {"role": "assistant", "content": "[STATE: RESEARCH]\n認証情報を受け取りました。EX予約で検索中...\n\n[ツール呼び出し: search_ex]"},
]
```

**LLMは自分が「認証情報を教えてください」と言ったことを覚えている。**
だから「123456 と password」が認証情報だと自然に理解できる。

---

## 移行計画

### Phase 1: 基盤
1. `app/agent/v2/` ディレクトリ作成
2. `session.py` 実装
3. `runner.py` 基本実装

### Phase 2: プロンプト
1. `system.md` 作成
2. 各状態の指示ファイル作成

### Phase 3: ツール連携
1. 既存Executorへの橋渡し
2. ツール呼び出しの実装

### Phase 4: 統合
1. APIルートの更新
2. テスト
3. 既存コードの段階的廃止

---

## 将来の設計方針

### 1. 実演によるスキル作成
Claude for Desktopの「ワークフローを教える」機能で作成した成果物をインポートするフロー。
- ユーザーが実際に操作してスキルを教える
- 成果物をSKILL.mdとしてインポート

### 2. agent-browserの検討
Vercelの [agent-browser](https://github.com/vercel/agent-browser) を使い、コンテキストを節約しながらブラウザ操作を行う構成。
- 現在のPlaywright直接操作からの移行を検討
- LLMのコンテキスト消費を削減

### 3. スキルの自己拡張（Self-Healing）
**最重要**: ダン自身のコードやSKILL.mdを書き換えるスキルを持たせる。
- 最初は最小限のSKILL.md（種）だけ用意
- 実行しながらダン自身にマニュアル（SKILL.md）を完成させていく
- エラーや新しいパターンを学習してスキルを自己改善

### ツール呼び出し方式
**B方式（キーワード検出）** を採用。
- LLMが `[TOOL: skill-name action]` と宣言
- コードが検出してExecutorを呼び出し
- Self-Healingとの親和性が高い（SKILL.mdの変更だけで挙動を変えられる）

---

## まとめ

| 項目 | 現行 | 新アーキテクチャ |
|-----|-----|----------------|
| 会話管理 | 各状態で新規プロンプト | Messages配列を継続 |
| 状態遷移 | コードでハードコード | LLMが宣言、コードが追従 |
| プロンプト | 1ファイル570行 | 状態ごとに分離 |
| 責務分離 | 混在 | session / runner / tools |
| LLMの文脈 | 途切れる | 継続する |
