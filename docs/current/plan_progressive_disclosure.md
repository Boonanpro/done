# 実装計画: 正しい Progressive Disclosure の実装

## ゴール

1. **ダン（VisualAgent含む）が存在するスキルを使えるようになる**
2. **正しい Progressive Disclosure が実装される**

---

## 現在の状態

### 既に実装済み

| 項目 | 状態 |
|------|------|
| execute_tool() のハードコードされたハンドラ削除 | ✅ 実装済み |
| 全スキル呼び出しを VisualAgent に委譲 | ✅ 実装済み |
| run_script アクション | ✅ 実装済み |
| _build_skill_manual() ヘルパー | ✅ 実装済み |

### 残っている問題

| 問題 | 詳細 |
|------|------|
| 各アクションがツール化されている | `rakuten_login`, `rakuten_search` 等が個別のツールとして生成される |
| Progressive Disclosure が間違っている | 選択段階で actions/*.md の1行目まで見せている |
| ダンがスキル一覧を認識できない | システムプロンプトにスキル一覧がない |

---

## 正しい Progressive Disclosure（Anthropic公式）

| レベル | タイミング | 何を見せるか |
|--------|-----------|-------------|
| 1 | セッション開始時 | スキル一覧（description のみ、約100トークン） |
| 2 | スキル使用を判断した時 | SKILL.md 本文（check_skill で取得） |
| 3 | アクション実行時 | actions/*.md（VisualAgent に渡す） |

---

## 修正後の設計

### ツール構成

**残すツール:**
- `visual_browse` - スキルを実行（手順書を渡す）
- `check_skill` - SKILL.md を読む
- `save_credentials` - 認証情報保存
- `tavily_search` - Web検索
- `respond_to_user` - ユーザーへの回答

**廃止:**
- 各アクションのツール（`rakuten_login`, `rakuten_search` 等）

### 実行フロー

```
1. ユーザー「楽天にログインして」

2. ダンがシステムプロンプトのスキル一覧を見る
   → "rakuten: 楽天市場で商品を検索・購入するスキル"

3. ダンが check_skill("rakuten") を呼ぶ（任意）
   → SKILL.md 本文を取得

4. ダンが visual_browse を呼ぶ
   {
     "task": "楽天にログインする",
     "site": "rakuten.co.jp",
     "skill_name": "rakuten"
   }

5. _execute_visual_browse() で:
   - skill_name から Skill を取得
   - SKILL.md + 関連 actions/*.md を結合
   - VisualAgent に渡して実行

6. VisualAgent が手順書に従って操作
```

---

## 変更内容

### 1. tools.py: get_all_skill_tools() を変更

スキルからツールを生成する処理を削除し、コアツールのみを返す。

```python
def get_all_skill_tools() -> List[Dict[str, Any]]:
    """コアツールのみを返す（スキルはツール化しない）"""
    return [
        VISUAL_BROWSE_TOOL,
        TAVILY_SEARCH_TOOL,
        SAVE_CREDENTIALS_TOOL,
        CHECK_SKILL_TOOL,
    ]
```

### 2. tools.py: VISUAL_BROWSE_TOOL に skill_name パラメータ追加

```python
"skill_name": {
    "type": "string",
    "description": "使用するスキル名（例: 'rakuten'）。指定すると手順書が自動で読み込まれる"
}
```

### 3. tools.py: _execute_visual_browse() で skill_name から手順書を構築

```python
skill_name = params.get("skill_name")
if skill_name:
    skill = SkillRegistry.get(skill_name)
    if skill:
        skill_manual = _build_skill_manual(skill, action=None)  # 全体を渡す
        if not site and skill.domain:
            site = skill.domain
```

### 4. runner.py: システムプロンプトにスキル一覧を追加

```python
def _build_skill_list_section(self) -> str:
    """スキル一覧（description のみ）"""
    skills = SkillRegistry.list_all()
    lines = ["\n## 利用可能なスキル"]
    for skill in skills:
        lines.append(f"- `{skill.name}`: {skill.description}")
    lines.append("\n※ スキルを使う場合は visual_browse の skill_name に指定")
    return "\n".join(lines)
```

---

## 変更ファイル一覧

| ファイル | 変更内容 |
|---------|---------|
| `app/agent/v2/tools.py` | get_all_skill_tools() を簡略化 |
| `app/agent/v2/tools.py` | VISUAL_BROWSE_TOOL に skill_name 追加 |
| `app/agent/v2/tools.py` | _execute_visual_browse() で skill_name 処理 |
| `app/agent/v2/runner.py` | _build_skill_list_section() 追加 |

---

## 実装手順

1. tools.py: get_all_skill_tools() からスキルツール生成を削除
2. tools.py: VISUAL_BROWSE_TOOL に skill_name パラメータ追加
3. tools.py: _execute_visual_browse() で skill_name から手順書を構築
4. runner.py: _build_skill_list_section() を追加してシステムプロンプトに注入
5. バックエンド再起動

---

## 検証ポイント

- [ ] システムプロンプトにスキル一覧（description のみ）が含まれる
- [ ] check_skill で SKILL.md 本文が取得できる
- [ ] visual_browse に skill_name を指定すると手順書が構築される
- [ ] ダンが「楽天にログインして」でスキルを認識して実行できる
