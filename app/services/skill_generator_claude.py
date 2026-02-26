"""
Skill Generator using Claude Code CLI

Claude Code CLIを使って高品質なスキルを自動生成する。
従来のテンプレート変換（skill_generator.py）を置き換える。
"""

import asyncio
import logging
import re
import uuid
from pathlib import Path
from typing import Dict, Any, Optional, List
from dataclasses import dataclass
import json
import yaml

from app.services import learning_service

logger = logging.getLogger(__name__)

# スキル保存先ディレクトリ
SKILLS_DIR = Path(__file__).parent.parent.parent / ".claude" / "skills"

# Claude Code CLI設定
ALLOWED_TOOLS = "Read,Write,Edit,Bash(mkdir*)"
TIMEOUT_ANALYZE = 60  # 分析は60秒
TIMEOUT_GENERATE = 300  # 生成は5分


@dataclass
class SkillProposal:
    """スキル提案"""
    skill_name: str
    description: str
    site: str
    actions: list[str]
    parameters: list[Dict[str, str]]
    raw_analysis: str
    analysis: Optional[Dict[str, Any]] = None
    steps: Optional[list[str]] = None
    # 重複検出結果（レガシー互換用）
    should_create: bool = True  # 生成すべきか
    existing_skill: Optional[str] = None  # 既存スキル名
    skip_reason: Optional[str] = None  # スキップ理由
    # Phase 1: LLM判断結果
    decision: str = "create"  # create / extend / skip
    decision_reason: str = ""
    target_skill: Optional[str] = None  # extend時の対象スキル
    new_actions: Optional[list[str]] = None  # extend時の追加アクション
    granularity_ok: bool = True
    granularity_issue: Optional[str] = None


@dataclass
class SkillGenerationResult:
    """スキル生成結果"""
    success: bool
    skill_name: str
    skill_path: Optional[str] = None
    files_created: list[str] = None
    error: Optional[str] = None
    output: Optional[str] = None


def _get_existing_skills_summary() -> str:
    """
    既存スキルの簡潔なサマリを生成（LLMプロンプト用）

    Returns:
        既存スキル一覧のMarkdown文字列
    """
    try:
        from app.agent.v2.tools import SkillRegistry
    except ImportError:
        return "## 既存スキル一覧\n（スキルなし）"

    lines = ["## 既存スキル一覧"]
    for skill in SkillRegistry.list_all():
        domain = skill.domain or "不明"
        # list_available_actions() メソッドでアクション一覧を取得
        actions_list = skill.list_available_actions()
        actions = ", ".join(actions_list) if actions_list else "execute"
        lines.append(f"- {skill.name} ({domain}): {actions}")

    if len(lines) == 1:
        lines.append("（スキルなし）")

    return "\n".join(lines)


def _filter_successful_path(yaml_log_path: str) -> str:
    """
    YAMLログから試行錯誤を除去し、成功パスのみを抽出

    除去対象:
    - result.success=falseのステップ
    - 同じ座標への連続クリック
    - llm_reasoningに「警告」「別のアプローチ」を含むステップ
    - action=error のステップ

    Returns:
        フィルタ済みYAMLの一時ファイルパス
    """
    log_path = Path(yaml_log_path)
    if not log_path.exists():
        return yaml_log_path

    try:
        raw = log_path.read_text(encoding="utf-8")
        data = yaml.safe_load(raw)
    except Exception:
        return yaml_log_path

    if not isinstance(data, dict) or "steps" not in data:
        return yaml_log_path

    steps = data.get("steps", [])
    if not isinstance(steps, list):
        return yaml_log_path

    filtered_steps = []
    last_click_xy = None
    last_action = None

    trial_keywords = ("警告", "別のアプローチ")

    for step in steps:
        if not isinstance(step, dict):
            continue

        action = step.get("action", "")
        result = step.get("result", {}) or {}

        # action=error を除外
        if action == "error":
            continue

        # 失敗ステップを除外
        if result.get("success") is False:
            continue

        # 試行錯誤っぽい理由を除外
        llm_reasoning = step.get("llm_reasoning")
        if llm_reasoning and any(keyword in llm_reasoning for keyword in trial_keywords):
            continue

        # 同じ座標への連続クリックを除外
        if action == "click":
            params = step.get("params", {}) or {}
            x = params.get("x", result.get("x"))
            y = params.get("y", result.get("y"))
            if x is not None and y is not None:
                current_xy = (x, y)
                if last_action == "click" and last_click_xy == current_xy:
                    continue
                last_click_xy = current_xy
            else:
                last_click_xy = None
        else:
            last_click_xy = None

        last_action = action
        filtered_steps.append(step)

    if not filtered_steps:
        return yaml_log_path

    data["steps"] = filtered_steps

    # イベントがあれば、残ったステップに関連するものだけ残す
    if isinstance(data.get("events"), list):
        kept_indices = {s.get("index") for s in filtered_steps if isinstance(s, dict)}
        filtered_events = []
        for event in data.get("events", []):
            if not isinstance(event, dict):
                continue
            step_index = event.get("step_index")
            if step_index is None or step_index in kept_indices:
                filtered_events.append(event)
        data["events"] = filtered_events

    # 元ファイルと同じディレクトリに一時ファイルを作成
    output_dir = log_path.parent
    output_dir.mkdir(parents=True, exist_ok=True)
    temp_path = output_dir / f"{log_path.stem}_filtered_{uuid.uuid4().hex[:6]}.yaml"

    try:
        with open(temp_path, "w", encoding="utf-8") as f:
            yaml.dump(
                data,
                f,
                allow_unicode=True,
                default_flow_style=False,
                sort_keys=False,
            )
        return str(temp_path)
    except Exception:
        return yaml_log_path


def _analyze_step_for_hybrid(step: dict) -> str:
    """
    各ステップがセレクタベースかVisualベースか判定

    Returns:
        "selector" - セレクタで再現可能
        "visual" - スクショ確認が必要
        "unknown" - 要調査
    """
    if not isinstance(step, dict):
        return "unknown"

    decision_type = step.get("decision_type")
    if decision_type in {"selector", "visual"}:
        return decision_type

    result = step.get("result", {}) or {}
    selectors = result.get("selectors", []) or []
    high_reliability = any(s.get("reliability") == "high" for s in selectors if isinstance(s, dict))

    if high_reliability:
        return "selector"
    llm_reasoning = step.get("llm_reasoning") or ""
    if "画面を見て" in llm_reasoning:
        return "visual"
    return "unknown"


def _format_events_as_session_log(events: list) -> str:
    """
    learning_eventsをセッションログテキストに変換

    スキル分析/生成のプロンプトに埋め込む用。
    """
    if not events:
        return "（イベントなし）"

    lines = []
    for i, event in enumerate(events, 1):
        action = event.get("action_name", "unknown")
        params = event.get("action_params") or {}
        success = event.get("technical_success", False)
        context = event.get("context") or {}

        lines.append(f"ステップ {i}: {action}")

        # パラメータ
        param_parts = []
        for k, v in params.items():
            if v is not None and v != "":
                param_parts.append(f"{k}={v}")
        if param_parts:
            lines.append(f"  パラメータ: {', '.join(param_parts)}")

        lines.append(f"  結果: {'成功' if success else '失敗'}")

        page_url = context.get("page_url", "")
        page_title = context.get("page_title", "")
        element_tag = context.get("element_tag", "")
        element_text = context.get("element_text", "")

        if page_url:
            lines.append(f"  URL: {page_url}")
        if page_title:
            lines.append(f"  タイトル: {page_title}")
        if element_tag:
            el_info = f"[{element_tag}]"
            if element_text:
                el_info += f" {element_text}"
            lines.append(f"  要素: {el_info}")

        lines.append("")

    return "\n".join(lines)


def _filter_successful_events(events: list) -> list:
    """成功したイベントのみを抽出し、連続重複を除去"""
    filtered = []
    last_action = None
    last_ref = None

    for event in events:
        if not event.get("technical_success", False):
            continue

        action = event.get("action_name", "")
        params = event.get("action_params") or {}
        ref = params.get("ref", "")

        # 同じアクション+refの連続を除去
        if action == last_action and ref == last_ref and ref:
            continue

        last_action = action
        last_ref = ref
        filtered.append(event)

    return filtered


def _extract_site_from_events(events: list) -> Optional[str]:
    """イベントリストからサイトドメインを抽出"""
    for event in events:
        site = event.get("site")
        if site:
            return site
    return None


def _run_claude_cli_sync(prompt: str, timeout: int, debug_log: Path, project_root: Path) -> tuple[bool, str, str]:
    """
    Claude Code CLIを同期的に実行（スレッドプール用）
    """
    import os
    import subprocess
    import uuid

    try:
        # 一時ファイルにプロンプトを書き込み
        temp_dir = project_root / "temp"
        temp_dir.mkdir(exist_ok=True)

        prompt_file = temp_dir / f"prompt_{uuid.uuid4().hex[:8]}.txt"
        output_file = temp_dir / f"output_{uuid.uuid4().hex[:8]}.txt"

        with open(debug_log, "a", encoding="utf-8") as f:
            f.write(f"[_run_claude_cli_sync] prompt_file={prompt_file}\n")
            f.write(f"[_run_claude_cli_sync] output_file={output_file}\n")

        # プロンプトをUTF-8で書き込み
        prompt_file.write_text(prompt, encoding="utf-8")

        # UTF-8を強制する環境変数
        env = os.environ.copy()
        env["PYTHONIOENCODING"] = "utf-8"
        env["PYTHONUTF8"] = "1"

        # PowerShellでUTF-8を強制してCLIを実行
        ps_cmd = f'''
            $OutputEncoding = [System.Text.Encoding]::UTF8
            [Console]::OutputEncoding = [System.Text.Encoding]::UTF8
            Get-Content -Path "{prompt_file}" -Encoding UTF8 | claude --print --allowedTools "{ALLOWED_TOOLS}" | Out-File -FilePath "{output_file}" -Encoding UTF8
        '''

        with open(debug_log, "a", encoding="utf-8") as f:
            f.write(f"[_run_claude_cli_sync] Executing subprocess.run...\n")

        result = subprocess.run(
            ["powershell", "-NoProfile", "-Command", ps_cmd],
            cwd=str(project_root),
            env=env,
            capture_output=True,
            timeout=timeout,
        )

        with open(debug_log, "a", encoding="utf-8") as f:
            f.write(f"[_run_claude_cli_sync] returncode={result.returncode}\n")
            f.write(f"[_run_claude_cli_sync] stdout={result.stdout.decode('utf-8', errors='replace')[:200]}\n")
            f.write(f"[_run_claude_cli_sync] stderr={result.stderr.decode('utf-8', errors='replace')[:200]}\n")
            f.write(f"[_run_claude_cli_sync] output_file.exists()={output_file.exists()}\n")

        # PowerShellのエラー出力をログ
        if result.stderr:
            logger.warning(f"PowerShell stderr: {result.stderr.decode('utf-8', errors='replace')}")

        # 出力をUTF-8で読み込み（BOMを除去）
        if output_file.exists():
            stdout_str = output_file.read_text(encoding="utf-8-sig", errors="replace")
            with open(debug_log, "a", encoding="utf-8") as f:
                f.write(f"[_run_claude_cli_sync] Read output file, length={len(stdout_str)}\n")
        else:
            stdout_str = ""
            with open(debug_log, "a", encoding="utf-8") as f:
                f.write(f"[_run_claude_cli_sync] Output file does not exist!\n")

        # クリーンアップ
        try:
            prompt_file.unlink()
            output_file.unlink()
        except Exception:
            pass

        if result.returncode != 0:
            logger.error(f"Claude CLI failed with return code {result.returncode}")
            return False, stdout_str, f"Exit code: {result.returncode}"

        return True, stdout_str, ""

    except subprocess.TimeoutExpired:
        logger.error(f"Claude CLI timeout after {timeout}s")
        with open(debug_log, "a", encoding="utf-8") as f:
            f.write(f"[_run_claude_cli_sync] TIMEOUT after {timeout}s\n")
        return False, "", f"Timeout after {timeout} seconds"

    except Exception as e:
        import traceback
        error_details = f"{type(e).__name__}: {e}\n{traceback.format_exc()}"
        logger.error(f"Claude CLI error: {error_details}")
        with open(debug_log, "a", encoding="utf-8") as f:
            f.write(f"[_run_claude_cli_sync] EXCEPTION: {error_details}\n")
        return False, "", str(e)


async def _run_claude_cli(prompt: str, timeout: int = 60) -> tuple[bool, str, str]:
    """
    Claude Code CLIを実行

    Windows + uvicorn環境でのasyncioサブプロセス問題を回避するため、
    スレッドプールで同期的にsubprocess.runを実行する。

    Args:
        prompt: プロンプト
        timeout: タイムアウト秒数

    Returns:
        (success, stdout, stderr)
    """
    import concurrent.futures

    project_root = Path(__file__).parent.parent.parent
    debug_log = Path("D:/done/skill_analyze_debug.log")

    with open(debug_log, "a", encoding="utf-8") as f:
        f.write(f"[_run_claude_cli] Starting with ThreadPoolExecutor...\n")

    loop = asyncio.get_event_loop()
    with concurrent.futures.ThreadPoolExecutor() as executor:
        result = await loop.run_in_executor(
            executor,
            _run_claude_cli_sync,
            prompt,
            timeout,
            debug_log,
            project_root,
        )

    return result


def _escape_for_shell(text: str) -> str:
    """シェル用にエスケープ"""
    # シングルクォートでラップし、内部のシングルクォートをエスケープ
    escaped = text.replace("'", "'\"'\"'")
    return f"'{escaped}'"


def _parse_proposals(stdout: str) -> list[dict]:
    """
    複数スキル提案をパースする

    ---PROPOSAL N--- セパレータで分割し、各ブロックをパース。
    セパレータがない場合は単一提案として処理。

    Args:
        stdout: CLIの出力文字列

    Returns:
        パースされた提案のリスト（各提案はdictで、フィールドを含む）
    """
    proposals = []

    # 複数提案の形式かチェック
    if "---PROPOSAL 1---" in stdout:
        # ---PROPOSAL N--- で分割
        import re
        pattern = r'---PROPOSAL\s+\d+---'
        parts = re.split(pattern, stdout)

        # 最初の部分は空またはプリアンブル
        for part in parts[1:]:  # 最初の空部分をスキップ
            # ---END PROPOSALS--- 以降を除去
            if "---END PROPOSALS---" in part:
                part = part.split("---END PROPOSALS---")[0]

            part = part.strip()
            if not part:
                continue

            proposal_data = _parse_single_proposal(part)
            if proposal_data:
                proposals.append(proposal_data)
    else:
        # 単一提案として処理
        proposal_data = _parse_single_proposal(stdout)
        if proposal_data:
            proposals.append(proposal_data)

    # 最大3件に制限
    return proposals[:3]


def _parse_single_proposal(text: str) -> Optional[dict]:
    """
    単一の提案ブロックをパースする

    Args:
        text: 単一提案のテキスト

    Returns:
        パースされた提案（dict）またはNone
    """
    decision_fields = _parse_decision_fields(text)
    decision = decision_fields["decision"]

    result = {
        "decision": decision,
        "reason": decision_fields["reason"],
        "target_skill": decision_fields["target_skill"],
        "new_actions": decision_fields["new_actions"],
        "granularity_ok": decision_fields["granularity_ok"],
        "granularity_issue": decision_fields["granularity_issue"],
    }

    # create または extend の場合はスキル情報もパース
    if decision in ("create", "extend"):
        result["skill_name"] = _extract_field(text, "SKILL_NAME")
        result["description"] = _extract_field(text, "DESCRIPTION")
        result["site"] = _extract_field(text, "SITE")
        result["actions_str"] = _extract_field(text, "ACTIONS")
        result["params_str"] = _extract_field(text, "PARAMETERS")
        result["steps_str"] = _extract_field(text, "STEPS")
        result["analysis_str"] = _extract_field(text, "ANALYSIS")

    return result


async def analyze_session_for_skill(
    yaml_log_path: Optional[str] = None,
    instruction: Optional[str] = None,
    events: Optional[list] = None,
) -> list[SkillProposal]:
    """
    セッションログを分析してスキル提案を生成

    ユーザーに「このスキルを作りますか？」と表示するための情報を取得。
    1つのセッションから複数のスキル提案を返す可能性がある。

    Args:
        yaml_log_path: YAMLログファイルのパス（レガシー）
        instruction: 追加の指示（任意）
        events: learning_eventsのリスト（新方式）

    Returns:
        SkillProposalのリスト（0件の場合もあり）
    """
    from pathlib import Path
    debug_log = Path("D:/done/skill_analyze_debug.log")

    # ログセクションを入力タイプに応じて構築
    if events:
        logger.info(f"Analyzing session from {len(events)} learning events")
        with open(debug_log, "a", encoding="utf-8") as f:
            f.write(f"[CLAUDE_CLI] Starting analysis from {len(events)} events\n")

        filtered_events = _filter_successful_events(events)
        session_log_text = _format_events_as_session_log(filtered_events)
        site = _extract_site_from_events(events)

        log_section = f"""## セッションログ（browser_* ツール操作記録）
サイト: {site or '不明'}
操作数: {len(filtered_events)}件（成功のみ、フィルタ後）

{session_log_text}"""
    elif yaml_log_path:
        logger.info(f"Analyzing session for skill: {yaml_log_path}")
        with open(debug_log, "a", encoding="utf-8") as f:
            f.write(f"[CLAUDE_CLI] Starting analysis for: {yaml_log_path}\n")

        filtered_yaml_path = _filter_successful_path(yaml_log_path)
        with open(debug_log, "a", encoding="utf-8") as f:
            f.write(f"[CLAUDE_CLI] Filtered YAML path: {filtered_yaml_path}\n")

        hybrid_summary = ""
        try:
            filtered_data = yaml.safe_load(Path(filtered_yaml_path).read_text(encoding="utf-8"))
            steps = filtered_data.get("steps", []) if isinstance(filtered_data, dict) else []
            counts = {"selector": 0, "visual": 0, "unknown": 0}
            visual_steps = []
            for step in steps:
                mode = _analyze_step_for_hybrid(step)
                counts[mode] = counts.get(mode, 0) + 1
                if mode == "visual":
                    idx = step.get("index")
                    if idx is not None:
                        visual_steps.append(str(idx))
            hybrid_summary = (
                f"Hybrid判定: selector={counts['selector']}, visual={counts['visual']}, unknown={counts['unknown']}"
            )
            if visual_steps:
                hybrid_summary += f"\nVisual推定ステップ: {', '.join(visual_steps[:10])}"
        except Exception:
            hybrid_summary = ""

        log_section = f"ログファイル: {filtered_yaml_path}\n{hybrid_summary}"
    else:
        logger.warning("analyze_session_for_skill called with no input")
        return []

    instruction_block = ""
    if instruction:
        instruction_block = (
            f"\n追加指示: {instruction}\n"
            "- 追加指示がログ内容と矛盾する場合は、矛盾点をnotesに明記する\n"
            "- 追加指示がある場合は手順やパラメータに必ず反映する\n"
        )

    # Phase 1: 既存スキルサマリを取得
    existing_skills_summary = _get_existing_skills_summary()

    prompt = f"""
以下のセッションログを分析し、スキル化の判断を行ってください。

{existing_skills_summary}

## 判断基準
1. 既存スキルで完全に対応可能 → skip
2. 既存スキルにアクション追加で対応可能 → extend
3. 新規スキルが必要 → create
4. 粒度が細かすぎる → skip with reason

## 粒度ガイドライン
- 単体では使われないアクション（ログインのみ等）は独立スキルにしない
- ユースケース単位（購入、予約、検索+購入等）でまとめる
- SKILL.md は 5,000 words 以下
{instruction_block}

重要:
- 試行錯誤（失敗した操作、やり直し）は除外する
- 成功した最短ルートのみをスキル化する
- 同じ操作の繰り返しは1回にまとめる
- 何が成功要因だったかを必ず分析し、再現条件を明示する
- 実行手順はSTEPSに「動詞で始まる短文」を5〜12件、順序通りにまとめる
- **ACTIONSにはセッションログに実際に記録された操作のみを含める。推測や一般的な機能を追加しない**
  - 例: ログイン→カート確認のログなら ACTIONS: login, view-cart のみ。searchは含めない

{log_section}

## 出力形式（複数スキル対応）

セッションログに複数の独立したタスク（例: ログイン→検索→購入）が含まれる場合、
各タスクを別々のスキルとして提案できる。ただし：
- 最大3件まで
- 粒度ガイドラインに従う
- 論理的に一体のフロー（検索→購入など）は1つにまとめることも可

### 単一スキルの場合
DECISION: create / extend / skip
REASON: 判断理由（1-2文）
TARGET_SKILL: (extend時のみ) 対象スキル名
NEW_ACTIONS: (extend時のみ) 追加アクション名（カンマ区切り）
GRANULARITY_OK: true / false
GRANULARITY_ISSUE: (falseの場合) 問題点

(DECISION=create または extend の場合のみ以下も出力)
SKILL_NAME: <スキル名 - 重要: サイト名のみ（例: amazon, rakuten, yahoo）。アクション名（search, login, cart等）は含めない。1サイト=1スキルの原則>
DESCRIPTION: <スキルの説明（日本語、1行）>
SITE: <対象サイトのドメイン>
ACTIONS: <セッションログに記録されたアクションのみ（カンマ区切り）。推測で追加しない>
PARAMETERS: <主要なパラメータ（JSON形式）>
STEPS: <実行手順（JSON配列・1行）>
ANALYSIS: <成功要因と再現条件のJSON（1行）>

### 複数スキルの場合（セパレータを使用）
---PROPOSAL 1---
DECISION: create
REASON: ...
SKILL_NAME: ...
（各フィールド）

---PROPOSAL 2---
DECISION: create
REASON: ...
SKILL_NAME: ...
（各フィールド）

---END PROPOSALS---

ANALYSIS JSONの例（1行、改行禁止）:
{{"success_factors":["検索欄を正しく特定できた","検索結果のスポンサーを避けた"],"visual_required_steps":[5,7],"selector_ok_steps":[1,2,3],"notes":"検索結果の選択は視覚判断が必要"}}

例（create の場合）:
DECISION: create
REASON: 新規サイトで既存スキルがない
GRANULARITY_OK: true
SKILL_NAME: yahoo
DESCRIPTION: Yahoo! Japanで検索や各種サービスを利用する
SITE: yahoo.co.jp
ACTIONS: search
PARAMETERS: [{{"name": "keyword", "type": "string", "required": true, "description": "検索キーワード"}}]
STEPS: ["検索欄を選択する","キーワードを入力する","検索ボタンを押す","結果一覧を表示する"]
ANALYSIS: {{"success_factors":["検索欄をセレクタで特定できた"],"visual_required_steps":[],"selector_ok_steps":[1,2],"notes":""}}

例（create - ログイン+カート確認のみのログの場合）:
DECISION: create
REASON: Amazonでログインとカート確認を実行（ログ記録: login, view_cart のみ）
GRANULARITY_OK: true
SKILL_NAME: amazon
DESCRIPTION: Amazonでログインしてカートを確認する
SITE: amazon.co.jp
ACTIONS: login, view_cart
PARAMETERS: [{{"name": "email", "type": "string", "required": true, "description": "メールアドレス"}}, {{"name": "password", "type": "string", "required": true, "description": "パスワード"}}]
STEPS: ["amazon.co.jpにアクセスする","ログインボタンをクリックする","メールアドレスを入力する","パスワードを入力する","ログインを完了する","カートアイコンをクリックする","カート内容を確認する"]
ANALYSIS: {{"success_factors":["ログインフォームを正しく特定できた"],"visual_required_steps":[],"selector_ok_steps":[1,2,3],"notes":"searchはログに記録されていないため含めない"}}

例（skip の場合）:
DECISION: skip
REASON: 既存スキル 'amazon' の search アクションで対応可能
GRANULARITY_OK: true

例（複数スキルの場合 - 1つのセッションで異なるサイトを操作した場合）:
---PROPOSAL 1---
DECISION: create
REASON: メルカリでの出品操作（ログ記録: login, list_item）
GRANULARITY_OK: true
SKILL_NAME: mercari
DESCRIPTION: メルカリで商品を出品する
SITE: mercari.com
ACTIONS: login, list_item
PARAMETERS: [{{"name": "email", "type": "string", "required": true, "description": "メールアドレス"}}]
STEPS: ["ログインする","出品ボタンをクリックする","商品情報を入力する","出品を完了する"]
ANALYSIS: {{"success_factors":["出品フォームを正しく特定できた"],"visual_required_steps":[],"selector_ok_steps":[1,2],"notes":""}}

---PROPOSAL 2---
DECISION: create
REASON: 楽天での検索操作（ログ記録: search）
GRANULARITY_OK: true
SKILL_NAME: rakuten
DESCRIPTION: 楽天市場で商品を検索する
SITE: rakuten.co.jp
ACTIONS: search
PARAMETERS: [{{"name": "keyword", "type": "string", "required": true, "description": "検索キーワード"}}]
STEPS: ["検索欄にキーワードを入力する","検索ボタンを押す","結果を確認する"]
ANALYSIS: {{"success_factors":["検索フローを正しく実行できた"],"visual_required_steps":[],"selector_ok_steps":[1,2],"notes":""}}

---END PROPOSALS---
"""

    with open(debug_log, "a", encoding="utf-8") as f:
        f.write(f"[CLAUDE_CLI] Calling _run_claude_cli...\n")

    success, stdout, stderr = await _run_claude_cli(prompt, timeout=TIMEOUT_ANALYZE)

    with open(debug_log, "a", encoding="utf-8") as f:
        f.write(f"[CLAUDE_CLI] success={success}\n")
        f.write(f"[CLAUDE_CLI] stdout length={len(stdout)}\n")
        f.write(f"[CLAUDE_CLI] stdout (first 500 chars)={stdout[:500]}\n")
        f.write(f"[CLAUDE_CLI] stderr={stderr}\n")

    if not success:
        logger.error(f"Analysis failed: {stderr}")
        with open(debug_log, "a", encoding="utf-8") as f:
            f.write(f"[CLAUDE_CLI] Returning empty list due to success=False\n")
        return []

    # 出力をパース（複数提案対応）
    try:
        proposals_data = _parse_proposals(stdout)

        with open(debug_log, "a", encoding="utf-8") as f:
            f.write(f"[CLAUDE_CLI] Parsed {len(proposals_data)} proposals\n")

        results: list[SkillProposal] = []

        for idx, data in enumerate(proposals_data):
            decision = data["decision"]
            decision_reason = data["reason"]
            target_skill = data.get("target_skill")
            new_actions = data.get("new_actions")
            granularity_ok = data.get("granularity_ok", True)
            granularity_issue = data.get("granularity_issue")

            with open(debug_log, "a", encoding="utf-8") as f:
                f.write(f"[CLAUDE_CLI] Proposal {idx+1}: decision={decision}, reason={decision_reason}\n")

            # skip の場合は最小限の情報で返す
            if decision == "skip":
                skip_reason = decision_reason
                if not granularity_ok and granularity_issue:
                    skip_reason = f"{decision_reason}（粒度問題: {granularity_issue}）"

                results.append(SkillProposal(
                    skill_name="",
                    description="",
                    site="",
                    actions=[],
                    parameters=[],
                    raw_analysis=stdout,
                    should_create=False,
                    existing_skill=target_skill,
                    skip_reason=skip_reason,
                    decision=decision,
                    decision_reason=decision_reason,
                    target_skill=target_skill,
                    new_actions=new_actions,
                    granularity_ok=granularity_ok,
                    granularity_issue=granularity_issue,
                ))
                continue

            # create または extend の場合はスキル情報をパース
            skill_name = data.get("skill_name")
            description = data.get("description")
            site = data.get("site")
            actions_str = data.get("actions_str")
            params_str = data.get("params_str")
            steps_str = data.get("steps_str")
            analysis_str = data.get("analysis_str")

            with open(debug_log, "a", encoding="utf-8") as f:
                f.write(f"[CLAUDE_CLI] Proposal {idx+1}: skill_name={skill_name}, description={description}\n")

            # extend の場合、スキル情報は任意（既存スキルに追加するため）
            if decision == "extend" and not skill_name:
                skill_name = target_skill or ""

            if not skill_name or not description:
                logger.warning(f"Proposal {idx+1}: missing skill_name or description, skipping")
                with open(debug_log, "a", encoding="utf-8") as f:
                    f.write(f"[CLAUDE_CLI] Proposal {idx+1}: skipped due to missing skill_name or description\n")
                continue

            actions = [a.strip() for a in actions_str.split(",")] if actions_str else ["execute"]

            # パラメータをパース
            parameters = []
            if params_str:
                try:
                    import json
                    parameters = json.loads(params_str)
                except json.JSONDecodeError:
                    logger.warning(f"Proposal {idx+1}: failed to parse parameters JSON: {params_str}")

            analysis = None
            if analysis_str:
                try:
                    import json
                    analysis = json.loads(analysis_str)
                except json.JSONDecodeError:
                    logger.warning(f"Proposal {idx+1}: failed to parse analysis JSON: {analysis_str}")

            steps = None
            if steps_str:
                try:
                    import json
                    steps = json.loads(steps_str)
                except json.JSONDecodeError:
                    logger.warning(f"Proposal {idx+1}: failed to parse steps JSON: {steps_str}")

            # should_create を decision から決定
            should_create = (decision == "create")

            results.append(SkillProposal(
                skill_name=skill_name,
                description=description,
                site=site or "",
                actions=actions,
                parameters=parameters,
                raw_analysis=stdout,
                analysis=analysis,
                steps=steps,
                should_create=should_create,
                existing_skill=target_skill if decision == "extend" else None,
                skip_reason=None,
                decision=decision,
                decision_reason=decision_reason,
                target_skill=target_skill,
                new_actions=new_actions,
                granularity_ok=granularity_ok,
                granularity_issue=granularity_issue,
            ))

        return results

    except Exception as e:
        logger.error(f"Failed to parse analysis: {e}")
        return []


def _extract_field(text: str, field_name: str) -> Optional[str]:
    """テキストからフィールドを抽出"""
    pattern = rf"{field_name}:\s*(.+?)(?:\n|$)"
    match = re.search(pattern, text)
    if match:
        return match.group(1).strip()
    return None


def _parse_decision_fields(stdout: str) -> dict:
    """
    DECISION関連フィールドをパース（Phase 1: LLM判断結果）

    Returns:
        {
            "decision": "create" / "extend" / "skip",
            "reason": 判断理由,
            "target_skill": extend時の対象スキル名,
            "new_actions": extend時の追加アクション（カンマ区切り→リスト）,
            "granularity_ok": true / false,
            "granularity_issue": 粒度問題の説明,
        }
    """
    decision = _extract_field(stdout, "DECISION") or "create"
    reason = _extract_field(stdout, "REASON") or ""
    target_skill = _extract_field(stdout, "TARGET_SKILL")
    new_actions_str = _extract_field(stdout, "NEW_ACTIONS")
    granularity_ok_str = _extract_field(stdout, "GRANULARITY_OK") or "true"
    granularity_issue = _extract_field(stdout, "GRANULARITY_ISSUE")

    # new_actions をリストに変換
    new_actions = None
    if new_actions_str:
        new_actions = [a.strip() for a in new_actions_str.split(",") if a.strip()]

    # granularity_ok を bool に変換
    granularity_ok = granularity_ok_str.lower() in ("true", "yes", "1")

    return {
        "decision": decision.lower(),
        "reason": reason,
        "target_skill": target_skill,
        "new_actions": new_actions,
        "granularity_ok": granularity_ok,
        "granularity_issue": granularity_issue,
    }

def _infer_parent_skill(skill_name: str, content: str) -> Optional[str]:
    """Infer parent skill group from name/content (best-effort)."""
    name_lower = (skill_name or "").lower()
    content_lower = (content or "").lower()
    if "amazon" in name_lower or "amazon" in content_lower:
        return "amazon"
    if "rakuten" in name_lower or "rakuten" in content_lower:
        return "rakuten"
    if "willer" in name_lower or "willer" in content_lower:
        return "willer"
    return None


def _extract_domain_from_yaml(yaml_log_path: str) -> Optional[str]:
    """Extract a domain from YAML log steps (best-effort)."""
    try:
        data = yaml.safe_load(Path(yaml_log_path).read_text(encoding="utf-8"))
    except Exception:
        return None
    if not isinstance(data, dict):
        return None
    steps = data.get("steps", [])
    if not isinstance(steps, list):
        return None
    for step in steps:
        if not isinstance(step, dict):
            continue
        # direct fields
        for key in ("page_url", "url"):
            url = step.get(key)
            if isinstance(url, str) and url.startswith("http"):
                return url.split("//", 1)[-1].split("/")[0].lower()
        # nested result
        result = step.get("result")
        if isinstance(result, dict):
            for key in ("page_url", "url"):
                url = result.get(key)
                if isinstance(url, str) and url.startswith("http"):
                    return url.split("//", 1)[-1].split("/")[0].lower()
        # nested params
        params = step.get("params")
        if isinstance(params, dict):
            url = params.get("url")
            if isinstance(url, str) and url.startswith("http"):
                return url.split("//", 1)[-1].split("/")[0].lower()
    return None


def _ensure_skill_md_structure(skill_dir: Path, yaml_log_path: str, skill_name: str) -> None:
    """Normalize SKILL.md title/metadata/actions (best-effort)."""
    skill_md_path = skill_dir / "SKILL.md"
    if not skill_md_path.exists():
        return

    try:
        content = skill_md_path.read_text(encoding="utf-8")
    except Exception:
        return

    changed = False
    lines = content.splitlines()
    if lines:
        if lines[0].startswith("# "):
            title = lines[0][2:].strip()
            normalized = re.sub(r"\s*\([^)]*\)\s*$", "", title)
            normalized = re.sub(r"\bSkill\b", "", normalized, flags=re.IGNORECASE)
            normalized = re.sub(r"\bv\d+\b", "", normalized, flags=re.IGNORECASE)
            normalized = re.sub(r"\s{2,}", " ", normalized).strip()
            if normalized and normalized != title:
                lines[0] = f"# {normalized}"
                changed = True

    # metadata detection
    has_domain = re.search(r"^\s*(domain|site)\s*:\s*", content, re.MULTILINE | re.IGNORECASE)
    has_parent = re.search(r"^\s*(parent_skill|parent)\s*:\s*", content, re.MULTILINE | re.IGNORECASE)
    insert_meta = []

    if not has_domain:
        domain = _extract_domain_from_yaml(yaml_log_path)
        if domain:
            insert_meta.append(f"domain: {domain}")
            changed = True

    if not has_parent:
        parent = _infer_parent_skill(skill_name, content)
        if parent:
            insert_meta.append(f"parent_skill: {parent}")
            changed = True

    if insert_meta:
        insert_at = 1 if lines else 0
        lines = lines[:insert_at] + insert_meta + [""] + lines[insert_at:]

    # actions table detection
    # Check for both formats:
    # - Japanese: ## アクション一覧
    # - English: ## Actions
    # - Table with backticks: | `login` |
    # - Table without backticks: | login |
    has_action_section = re.search(r"##\s*(アクション一覧|Actions)", content) is not None
    has_action_table = re.search(r"\|\s*`?\w+(-\w+)*`?\s*\|.*\|.*\|", content) is not None
    if not has_action_section and not has_action_table:
        actions_dir = skill_dir / "actions"
        actions = []
        if actions_dir.exists():
            actions = [p.stem for p in actions_dir.glob("*.md")]
        if not actions:
            actions = ["execute"]
        table = ["", "## Actions", "| Action | Description | Doc |", "|---|---|---|"]
        for action in actions:
            table.append(f"| `{action}` |  | actions/{action}.md |")
        lines.extend(table)
        changed = True

    if changed:
        skill_md_path.write_text("\n".join(lines), encoding="utf-8")



async def generate_skill(
    yaml_log_path: Optional[str] = None,
    skill_name: str = "",
    description: Optional[str] = None,
    analysis: Optional[Dict[str, Any]] = None,
    steps: Optional[list[str]] = None,
    instruction: Optional[str] = None,
    session_log_text: Optional[str] = None,
) -> SkillGenerationResult:
    """
    スキルを生成

    Claude Code CLIを使って高品質なスキルを生成。

    Args:
        yaml_log_path: YAMLログファイルのパス（レガシー）
        skill_name: スキル名
        description: スキルの説明（省略時はログから推測）
        analysis: 成功要因や再現条件の分析
        steps: 実行手順（短文の配列）
        instruction: 追加の修正指示（任意）
        session_log_text: セッションログテキスト（events方式、yaml_log_pathの代替）

    Returns:
        SkillGenerationResult
    """
    logger.info(f"Generating skill: {skill_name}")

    skill_dir = SKILLS_DIR / skill_name

    # 既存スキルのチェック
    if skill_dir.exists():
        # バージョン番号を付ける
        i = 2
        while (SKILLS_DIR / f"{skill_name}_{i}").exists():
            i += 1
        skill_name = f"{skill_name}_{i}"
        skill_dir = SKILLS_DIR / skill_name
        logger.info(f"Skill already exists, using: {skill_name}")

    # ログセクション構築
    if session_log_text:
        log_input_section = f"- セッションログ: 下記に埋め込み"
        log_embed_section = f"\n## セッションログ\n{session_log_text}\n"
    elif yaml_log_path:
        filtered_yaml_path = _filter_successful_path(yaml_log_path)
        log_input_section = f"- ログファイル: {filtered_yaml_path}"
        log_embed_section = ""
    else:
        return SkillGenerationResult(
            success=False,
            skill_name=skill_name,
            error="No log source provided (yaml_log_path or session_log_text required)",
        )

    # 学習済みルールを取得（スキル生成の参考情報として）
    learned_rules_text = ""
    try:
        site_domain = None
        if yaml_log_path:
            try:
                with open(yaml_log_path, "r", encoding="utf-8") as f:
                    yaml_content = yaml.safe_load(f)
                    if yaml_content and isinstance(yaml_content, dict):
                        site_domain = yaml_content.get("site")
            except Exception:
                pass

        rules = await learning_service.get_rules_for_skill(
            site=site_domain,
            skill_name=skill_name,
            min_confidence=0.5,
        )
        if rules:
            learned_rules_text = learning_service.format_rules_for_prompt(rules)
            logger.info(f"Found {len(rules)} learned rules for skill generation")
    except Exception as e:
        logger.debug(f"Failed to fetch learned rules: {e}")

    analysis_json = ""
    steps_json = ""
    instruction_text = instruction or ""
    if analysis:
        try:
            analysis_json = json.dumps(analysis, ensure_ascii=False)
        except Exception:
            analysis_json = str(analysis)
    if steps:
        try:
            steps_json = json.dumps(steps, ensure_ascii=False)
        except Exception:
            steps_json = str(steps)

    # 学習ルールセクション
    learned_rules_section = ""
    if learned_rules_text:
        learned_rules_section = f"""
## 学習済みルール（過去のデータから検出されたパターン）
以下は過去の操作データから学習したルールです。SKILL.md の Requires 列や
アクションの前提条件を記載する際に参考にしてください：

{learned_rules_text}
"""

    prompt = f"""
以下のタスクを実行してください：

## 入力
{log_input_section}
- スキル名: {skill_name}
- 保存先: {skill_dir}
- 説明: {description or "（未指定）"}

## 分析/手順
- 分析: {analysis_json or "（なし）"}
- 手順: {steps_json or "（なし）"}
- 追加指示: {instruction_text or "（なし）"}
{learned_rules_section}
## 生成するファイル

### 1. {skill_dir}/SKILL.md
スキルの手順書。

【絶対ルール - 省略禁止】SKILL.md は必ず以下の形式で始めること：
---
name: スキル名
description: スキルの説明
domain: 対象ドメイン
---

例（正しい形式）:
---
name: amazon
description: Amazonで商品を検索・購入するスキル
domain: amazon.co.jp
---

# Amazon スキル
...

※ファイルの1行目は必ず「---」で始まる。これがないと無効。

**本文に含める内容:**
- スキルの概要と目的
- 対象サイト/サービス（domain: を記載）
- 認証要件（必要な場合）
- アクション一覧（Actionsテーブル形式、下記参照）
- パラメータ一覧（テーブル形式）
- 実行フロー（視覚ベースの説明）

**Actionsテーブルの形式（必須）:**
| Action | Requires | Doc |
|--------|----------|-----|
| login | - | actions/login.md |
| view-cart | login | actions/view-cart.md |

**Requires列のルール:**
- 認証依存（login）のみ記載する
- ページ遷移の前提は含めない（アクションファイルに記載）
- 判断基準: ログインしないとユーザーにとって意味のある結果が得られないか
  - login必要: カート操作、お気に入り、購入履歴、アカウント設定など
  - login不要: 検索、商品閲覧など

### 2. {skill_dir}/actions/{{action}}.md（各アクションごと）
アクションの詳細手順を記載:
- 操作の目的
- **前提条件（重要）**: このアクションを実行する前に必要な状態を明記
  - 認証要件: 「ログイン済みであること」→ [login](login.md) アクションへのリンク
  - ページ状態: 「カートページを表示していること」→ 推奨の遷移方法を記載
  ※認証要件（login必要かどうか）はSKILL.mdのActionsテーブルのRequires列にも反映する
  ※ページ状態はアクションファイルにのみ記載（Actionsテーブルには含めない）
- 画面の見つけ方（テキスト、ボタンの文字、画像の特徴など視覚的な説明）
- 操作手順（ステップバイステップ、番号付きリスト）
- 成功条件（何が表示されたら成功か）
- 失敗時の対処
- 注意点

## 重要な制約
- executor.py は生成しない
- selectors.py は生成しない
- 手順書はブラウザ操作AI（browserツールのaction=open/click/type等を使用）が読んで実行する前提で書く
- CSSセレクタではなく、視覚的な特徴で要素を説明する
- 「○○ボタンをクリック」ではなく「画面右上の青い『ログイン』ボタンをクリック」のように具体的に

## 品質基準
- 人間が読んでも手順が分かる
- 画面を見たことがない人でも操作できる詳細さ
- エッジケースや注意点を記載
{log_embed_section}"""

    success, stdout, stderr = await _run_claude_cli(prompt, timeout=TIMEOUT_GENERATE)

    if not success:
        return SkillGenerationResult(
            success=False,
            skill_name=skill_name,
            error=stderr or "Unknown error",
            output=stdout,
        )

    # SKILL.md の存在を確認（必須）
    if not (skill_dir / "SKILL.md").exists():
        return SkillGenerationResult(
            success=False,
            skill_name=skill_name,
            error="SKILL.md was not created",
            output=stdout,
        )

    # 生成されたファイルを列挙
    files_created = ["SKILL.md"]
    actions_dir = skill_dir / "actions"
    if actions_dir.exists():
        for action_file in actions_dir.glob("*.md"):
            files_created.append(f"actions/{action_file.name}")

    logger.info(f"Skill generated: {skill_dir}, files: {files_created}")

    # Normalize SKILL.md structure (title/metadata/actions)
    try:
        _ensure_skill_md_structure(skill_dir, yaml_log_path, skill_name)
    except Exception as e:
        logger.warning(f"Failed to normalize SKILL.md: {e}")

    # Note: _rebuild_skill_md() は新規作成時には実行しない
    # Claude CLI が生成した SKILL.md をそのまま使用する
    # 拡張時（extend_skill）のみ _rebuild_skill_md() を実行して
    # 新しいアクションの依存関係を反映する

    # Refresh skill caches so the new skill is immediately usable.
    try:
        from app.agent.v2.tools import SkillRegistry
        from app.services.skill_loader import get_skill_loader

        SkillRegistry.reload()
        get_skill_loader().load_all(force=True)
    except Exception as e:
        logger.warning(f"Failed to refresh skill cache: {e}")

    return SkillGenerationResult(
        success=True,
        skill_name=skill_name,
        skill_path=str(skill_dir),
        files_created=files_created,
        output=stdout,
    )


async def _regenerate_skill_md(skill_dir: Path, skill_name: str) -> None:
    """
    SKILL.md を Claude CLI で再生成する

    全ての action.md を読み込み、それらを反映した新しい SKILL.md を生成。
    description、本文、実行フロー、Actionsテーブルを全て更新。
    """
    skill_md_path = skill_dir / "SKILL.md"
    actions_dir = skill_dir / "actions"

    # 既存の SKILL.md から domain を抽出（保持するため）
    existing_content = skill_md_path.read_text(encoding="utf-8") if skill_md_path.exists() else ""
    domain_match = re.search(r'domain:\s*(\S+)', existing_content)
    domain = domain_match.group(1) if domain_match else ""

    # 全アクションファイルを読み込み
    action_contents = {}
    all_actions = []
    if actions_dir.exists():
        for action_file in sorted(actions_dir.glob("*.md")):
            action_name = action_file.stem
            all_actions.append(action_name)
            content = action_file.read_text(encoding="utf-8")
            # 最初の500文字だけ（プロンプトサイズ制限）
            action_contents[action_name] = content[:500]

    if not all_actions:
        return

    actions_summary = "\n".join([
        f"### {name}\n{content}...\n"
        for name, content in action_contents.items()
    ])

    prompt = f"""
以下のスキルの SKILL.md を再生成してください。

## スキル情報
- スキル名: {skill_name}
- ドメイン: {domain}
- 保存先: {skill_md_path}

## 全アクション一覧（actions/*.md の内容抜粋）
{actions_summary}

## 生成ルール

【絶対ルール】SKILL.md は必ず以下の YAML frontmatter で始めること：
---
name: {skill_name}
description: （全アクションの機能を要約した1行の説明）
domain: {domain}
---

## 本文に含める内容
1. スキルの概要（全アクションを反映した説明）
2. 対象サイト/サービス
3. 認証要件（必要な場合）
4. パラメータ一覧（テーブル形式）
5. 実行フロー（依存関係を含む）
6. Actionsテーブル（全アクション）

## Actionsテーブルの形式
| Action | Description | Requires | Doc |
|--------|-------------|----------|-----|
| login | ログインする | - | actions/login.md |
| search | 商品を検索する | - | actions/search.md |
| add-to-cart | カートに追加する | login | actions/add-to-cart.md |

**Requires列のルール:**
- 認証依存（login）のみ記載
- 各 action.md の「前提条件」→「認証要件」セクションを確認して判断

## 重要
- 全アクションの機能を description に反映すること
- 実行フローは依存関係順に並べること
- 視覚的な説明を含めること（VisualAgent向け）
"""

    success, stdout, stderr = await _run_claude_cli(prompt, timeout=TIMEOUT_GENERATE)

    if not success:
        raise Exception(f"Claude CLI failed: {stderr}")

    # SKILL.md が更新されたか確認
    if not skill_md_path.exists():
        raise Exception("SKILL.md was not created")

    logger.info(f"Regenerated SKILL.md for {skill_name}")


async def extend_skill(
    yaml_log_path: Optional[str] = None,
    target_skill: str = "",
    new_actions: list[str] = None,
    description: Optional[str] = None,
    analysis: Optional[Dict[str, Any]] = None,
    steps: Optional[list[str]] = None,
    instruction: Optional[str] = None,
    session_log_text: Optional[str] = None,
) -> SkillGenerationResult:
    """
    既存スキルにアクションを追加

    Args:
        yaml_log_path: YAMLログファイルのパス（レガシー）
        target_skill: 追加先の既存スキル名
        new_actions: 追加するアクション名のリスト
        description: アクションの説明
        analysis: 成功要因や再現条件の分析
        steps: 実行手順
        instruction: 追加の修正指示
        session_log_text: セッションログテキスト（events方式）

    Returns:
        SkillGenerationResult
    """
    if new_actions is None:
        new_actions = []
    logger.info(f"Extending skill: {target_skill} with actions: {new_actions}")

    # 1. 既存スキルディレクトリを特定
    skill_dir = SKILLS_DIR / target_skill
    if not skill_dir.exists():
        return SkillGenerationResult(
            success=False,
            skill_name=target_skill,
            error=f"Skill '{target_skill}' not found at {skill_dir}",
        )

    # SKILL.md の存在確認
    skill_md_path = skill_dir / "SKILL.md"
    if not skill_md_path.exists():
        return SkillGenerationResult(
            success=False,
            skill_name=target_skill,
            error=f"SKILL.md not found in {skill_dir}",
        )

    # 既存の SKILL.md を読み込み
    try:
        existing_skill_md = skill_md_path.read_text(encoding="utf-8")
    except Exception as e:
        return SkillGenerationResult(
            success=False,
            skill_name=target_skill,
            error=f"Failed to read SKILL.md: {e}",
        )

    # ログセクション構築
    if session_log_text:
        log_input_line = "- セッションログ: 下記に埋め込み"
        log_embed_section = f"\n## セッションログ\n{session_log_text}\n"
    elif yaml_log_path:
        filtered_yaml_path = _filter_successful_path(yaml_log_path)
        log_input_line = f"- ログファイル: {filtered_yaml_path}"
        log_embed_section = ""
    else:
        return SkillGenerationResult(
            success=False,
            skill_name=target_skill,
            error="No log source provided",
        )

    # 学習済みルールを取得
    learned_rules_text = ""
    try:
        site_domain = None
        try:
            from app.agent.v2.tools import SkillRegistry
            skill = SkillRegistry.get(target_skill)
            if skill:
                site_domain = skill.domain
        except Exception:
            pass

        rules = await learning_service.get_rules_for_skill(
            site=site_domain,
            skill_name=target_skill,
            actions=new_actions,
            min_confidence=0.5,
        )
        if rules:
            learned_rules_text = learning_service.format_rules_for_prompt(rules)
            logger.info(f"Found {len(rules)} learned rules for skill extension")
    except Exception as e:
        logger.debug(f"Failed to fetch learned rules: {e}")

    analysis_json = ""
    steps_json = ""
    instruction_text = instruction or ""
    if analysis:
        try:
            analysis_json = json.dumps(analysis, ensure_ascii=False)
        except Exception:
            analysis_json = str(analysis)
    if steps:
        try:
            steps_json = json.dumps(steps, ensure_ascii=False)
        except Exception:
            steps_json = str(steps)

    # 学習ルールセクション
    learned_rules_section = ""
    if learned_rules_text:
        learned_rules_section = f"""
## 学習済みルール（過去のデータから検出されたパターン）
{learned_rules_text}
"""

    actions_dir = skill_dir / "actions"
    actions_list = ", ".join(new_actions) if new_actions else "execute"

    # 2. Claude CLI で新しいアクションの手順書のみを生成
    prompt = f"""
以下のタスクを実行してください：

## 入力
{log_input_line}
- 既存スキル: {target_skill}
- 既存SKILL.md: {skill_md_path}
- 追加アクション: {actions_list}
- actionsディレクトリ: {actions_dir}

## 既存 SKILL.md の内容（参照用、編集不要）
```
{existing_skill_md[:2000]}
```

## 分析/手順
- 説明: {description or "（未指定）"}
- 分析: {analysis_json or "（なし）"}
- 手順: {steps_json or "（なし）"}
- 追加指示: {instruction_text or "（なし）"}
{learned_rules_section}
## 生成するファイル

### {actions_dir}/{{action}}.md（追加アクションごと）
アクションの詳細手順を記載:
- 操作の目的
- **前提条件（重要）**: このアクションを実行する前に必要な状態を明記
  - 認証要件: 「ログイン済みであること」→ [login](login.md) アクションへのリンク
  - ページ状態: 「カートページを表示していること」→ 推奨の遷移方法を記載
  ※認証要件（login必要かどうか）は拡張後にSKILL.mdのActionsテーブルのRequires列に反映される
  ※ページ状態はアクションファイルにのみ記載（Actionsテーブルには含めない）
- 画面の見つけ方（テキスト、ボタンの文字、画像の特徴など視覚的な説明）
- 操作手順（ステップバイステップ、番号付きリスト）
- 成功条件（何が表示されたら成功か）
- 失敗時の対処
- 注意点

## 重要な制約
- SKILL.md は絶対に編集・上書きしない（既存のまま）
- actions/ ディレクトリに新しいアクションファイルのみ追加する
- executor.py は生成しない
- selectors.py は生成しない
- 手順書はブラウザ操作AI（browserツールのaction=open/click/type等を使用）が読んで実行する前提で書く
- CSSセレクタではなく、視覚的な特徴で要素を説明する

## 品質基準
- 人間が読んでも手順が分かる
- 画面を見たことがない人でも操作できる詳細さ
- エッジケースや注意点を記載
{log_embed_section}"""

    success, stdout, stderr = await _run_claude_cli(prompt, timeout=TIMEOUT_GENERATE)

    if not success:
        return SkillGenerationResult(
            success=False,
            skill_name=target_skill,
            error=stderr or "Unknown error",
            output=stdout,
        )

    # 生成されたファイルを列挙
    files_created = []
    if actions_dir.exists():
        for action in new_actions:
            action_file = actions_dir / f"{action}.md"
            if action_file.exists():
                files_created.append(f"actions/{action}.md")

    if not files_created:
        return SkillGenerationResult(
            success=False,
            skill_name=target_skill,
            error="No action files were created",
            output=stdout,
        )

    logger.info(f"Skill extended: {skill_dir}, files: {files_created}")

    # 3. SKILL.md を Claude CLI で再生成（全アクションを反映）
    try:
        await _regenerate_skill_md(skill_dir, target_skill)
        files_created.append("SKILL.md (regenerated)")
    except Exception as e:
        logger.warning(f"Failed to regenerate SKILL.md: {e}")
        # フォールバック: テンプレート的な更新
        try:
            _rebuild_skill_md(skill_dir)
        except Exception as e2:
            logger.warning(f"Failed to rebuild SKILL.md: {e2}")

    # 4. キャッシュ更新
    try:
        from app.agent.v2.tools import SkillRegistry
        from app.services.skill_loader import get_skill_loader

        SkillRegistry.reload()
        get_skill_loader().load_all(force=True)
    except Exception as e:
        logger.warning(f"Failed to refresh skill cache: {e}")

    return SkillGenerationResult(
        success=True,
        skill_name=target_skill,
        skill_path=str(skill_dir),
        files_created=files_created,
        output=stdout,
    )


def _rebuild_skill_md(skill_dir: Path) -> None:
    """
    SKILL.md を再構築する

    actionsディレクトリの全アクションを読み取り、
    実行フロー、依存関係、アクション一覧を最新状態に更新する。
    """
    skill_md_path = skill_dir / "SKILL.md"
    actions_dir = skill_dir / "actions"

    if not skill_md_path.exists():
        return

    content = skill_md_path.read_text(encoding="utf-8")

    # YAML frontmatterを抽出・保持
    frontmatter = ""
    frontmatter_match = re.match(r'^---\n(.*?)\n---\n', content, re.DOTALL)
    if frontmatter_match:
        frontmatter = frontmatter_match.group(0)
        content = content[len(frontmatter):]
    else:
        # frontmatterがない場合は生成
        skill_name = skill_dir.name
        frontmatter = f"---\nname: {skill_name}\ndescription: {skill_name} スキル\ndomain: \n---\n"

    # 全アクションを列挙
    all_actions = []
    action_deps = {}  # action -> required actions

    if actions_dir.exists():
        for action_file in sorted(actions_dir.glob("*.md")):
            action_name = action_file.stem
            all_actions.append(action_name)

            # 前提条件から認証依存のみを抽出
            # ページ遷移の前提（search等）はRequiresに含めない
            action_content = action_file.read_text(encoding="utf-8")
            deps = []
            if action_name != "login":
                # 「**認証要件**」セクションがあればloginを追加
                if re.search(r'\*\*認証要件\*\*', action_content):
                    deps.append("login")
            action_deps[action_name] = deps

    if not all_actions:
        return

    # 実行フローを生成（トポロジカルソート）
    # 依存されているアクションを先に配置
    flow_order = []
    remaining = set(all_actions)

    # まず依存なしのアクションを追加
    while remaining:
        added = False
        for action in list(remaining):
            deps = action_deps.get(action, [])
            # 全ての依存がflow_orderに含まれているか確認
            if all(d in flow_order or d not in all_actions for d in deps):
                flow_order.append(action)
                remaining.remove(action)
                added = True
        if not added:
            # 循環依存の場合、残りを追加
            flow_order.extend(sorted(remaining))
            break

    flow_lines = ["```", "実行可能なフロー:"]
    for i, action in enumerate(flow_order, 1):
        deps = action_deps.get(action, [])
        dep_note = f" (要: {', '.join(deps)})" if deps else ""
        flow_lines.append(f"{i}. {action}{dep_note}")
    flow_lines.append("```")
    flow_text = "\n".join(flow_lines)

    # 実行フローセクションを更新
    flow_pattern = r'## 実行フロー\s*\n```[\s\S]*?```'
    if re.search(flow_pattern, content):
        content = re.sub(flow_pattern, f"## 実行フロー\n{flow_text}", content)
    else:
        # 実行フローセクションがない場合は追加
        # アクション一覧の前に挿入
        actions_section = re.search(r'## (アクション一覧|Actions)', content)
        if actions_section:
            insert_pos = actions_section.start()
            content = content[:insert_pos] + f"## 実行フロー\n{flow_text}\n\n" + content[insert_pos:]

    # アクションテーブルを完全に再構築（実行フロー順）
    table_lines = [
        "## Actions",
        "| Action | Description | Requires | Doc |",
        "|--------|-------------|----------|-----|",
    ]
    for action in flow_order:  # all_actions ではなく flow_order を使用
        deps = action_deps.get(action, [])
        requires = ", ".join(deps) if deps else "-"
        table_lines.append(f"| `{action}` | | {requires} | actions/{action}.md |")
    new_table = "\n".join(table_lines)

    # 既存の「アクション一覧」セクションを削除（日本語テーブル対応）
    old_actions_pattern = r'## アクション一覧\s*\n\|[\s\S]*?(?=\n##|\n\n[^|]|\Z)'
    content = re.sub(old_actions_pattern, '', content)

    # 既存の Actions セクションを置換
    actions_pattern = r'## Actions\s*\n\|[\s\S]*?(?=\n##|\n\n[^|]|\Z)'
    if re.search(actions_pattern, content):
        content = re.sub(actions_pattern, new_table + "\n", content)
    else:
        content = content.rstrip() + "\n\n" + new_table + "\n"

    # frontmatterを先頭に追加して書き出し
    skill_md_path.write_text(frontmatter + content, encoding="utf-8")
    logger.info(f"Rebuilt SKILL.md with {len(all_actions)} actions")


def _update_skill_md_actions(skill_md_path: Path, new_actions: list[str]) -> None:
    """
    SKILL.md のアクションテーブルに新しいアクションを追加

    既存のテーブルがあれば行を追加、なければテーブルを作成
    """
    content = skill_md_path.read_text(encoding="utf-8")

    # アクションテーブルを探す
    # パターン: | Action | Description | Doc | のようなヘッダー
    table_pattern = r'(\|\s*Action\s*\|.*?\n\|[-\s|]+\n)((?:\|.*?\n)*)'
    match = re.search(table_pattern, content, re.IGNORECASE)

    if match:
        # 既存テーブルに行を追加
        header = match.group(1)
        existing_rows = match.group(2)

        # 既存のアクション名を取得
        existing_actions = set()
        for row in existing_rows.strip().split('\n'):
            action_match = re.search(r'\|\s*`(\w+)`\s*\|', row)
            if action_match:
                existing_actions.add(action_match.group(1))

        # 新しいアクションの行を追加
        new_rows = []
        for action in new_actions:
            if action not in existing_actions:
                new_rows.append(f"| `{action}` |  | actions/{action}.md |")

        if new_rows:
            updated_table = header + existing_rows.rstrip('\n') + '\n' + '\n'.join(new_rows) + '\n'
            content = content[:match.start()] + updated_table + content[match.end():]

    else:
        # テーブルがない場合は末尾に追加
        table_lines = [
            "",
            "## Actions",
            "| Action | Description | Doc |",
            "|---|---|---|",
        ]
        for action in new_actions:
            table_lines.append(f"| `{action}` |  | actions/{action}.md |")
        content += '\n'.join(table_lines)

    skill_md_path.write_text(content, encoding="utf-8")


async def generate_skill_from_session(
    yaml_log_path: Optional[str] = None,
    events: Optional[list] = None,
) -> SkillGenerationResult:
    """
    セッションからスキルを生成（分析→生成を一括実行）

    複数提案がある場合、最初のcreate/extend提案のみを生成する。

    Args:
        yaml_log_path: YAMLログファイルのパス（レガシー）
        events: learning_eventsのリスト（新方式）

    Returns:
        SkillGenerationResult
    """
    # 1. 分析
    proposals = await analyze_session_for_skill(yaml_log_path=yaml_log_path, events=events)

    if not proposals:
        return SkillGenerationResult(
            success=False,
            skill_name="unknown",
            error="Failed to analyze session",
        )

    # 最初のcreate/extend提案を使用
    proposal = None
    for p in proposals:
        if p.decision in ("create", "extend") and p.skill_name:
            proposal = p
            break

    if not proposal:
        return SkillGenerationResult(
            success=False,
            skill_name="unknown",
            error="No valid proposal found (all skipped)",
        )

    # 2. 生成
    return await generate_skill(
        yaml_log_path=yaml_log_path,
        skill_name=proposal.skill_name,
        description=proposal.description,
        analysis=proposal.analysis,
        steps=proposal.steps,
    )
