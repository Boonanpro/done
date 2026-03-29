"""
Tools - スキルとExecutorの橋渡し（Native Tool Use方式）

Anthropic Tool Use APIを使用して構造化された出力を実現。
LLMのテキスト出力がそのままユーザーへの返答になる。
"""

import re
import asyncio
import logging
from pathlib import Path
from typing import Dict, Any, List, Optional, Tuple
from dataclasses import dataclass, field

logger = logging.getLogger(__name__)

# バックグラウンドタスクの参照を保持（GC防止）
# ============================================
# スキル定義（動的読み込み方式）
# ============================================
#
# 以前はここにハードコードされたSKILL_ACTIONS, CORE_SKILLS, CORE_SKILL_PREFIXES があったが、
# 全てのスキルをSKILL.mdとactions/*.mdから動的に読み取る設計に統一した。
# これにより：
# - 新しいスキル追加時にコード変更が不要
# - スキル定義の一元管理（SKILL.md + actions/*.md）
# - メンテナンス性の向上
#
# 互換性のため空の定義を残す（参照エラー防止）
SKILL_ACTIONS: Dict[str, Dict[str, Any]] = {}
CORE_SKILLS: set = set()
CORE_SKILL_PREFIXES: List[str] = []


def _log_core_skill_mismatch(skill: "Skill", actions: Dict[str, Dict[str, Any]]) -> None:
    """Log mismatches between SKILL.md parameters and core hardcoded actions (no behavior change)."""
    if not skill.raw_content:
        return

    # Action list mismatch (if actions directory exists)
    available_actions = skill.list_available_actions()
    if available_actions:
        core_actions = set(actions.keys())
        skill_actions = set(available_actions)
        if core_actions != skill_actions:
            logger.debug(
                "Core skill action mismatch for %s: core=%s skill=%s",
                skill.name,
                sorted(core_actions),
                sorted(skill_actions),
            )

    # Only compare when a single param table exists (typically for search)
    params_from_skill, required_from_skill = skill.get_parameters()
    if not params_from_skill:
        return

    core_action = actions.get("search")
    if not core_action:
        return

    core_params = core_action.get("parameters", {})
    core_required = set(core_action.get("required", []))

    skill_param_keys = set(params_from_skill.keys())
    core_param_keys = set(core_params.keys())

    extra_in_core = core_param_keys - skill_param_keys
    extra_in_skill = skill_param_keys - core_param_keys
    missing_required = set(required_from_skill) - core_required

    if extra_in_core or extra_in_skill or missing_required:
        logger.debug(
            "Core skill parameter mismatch for %s: extra_in_core=%s extra_in_skill=%s missing_required=%s",
            skill.name,
            sorted(extra_in_core),
            sorted(extra_in_skill),
            sorted(missing_required),
        )




# ============================================
# Skill doc parsing (no behavior changes; used for verification)
# ============================================

def _parse_param_table_from_text(text: str) -> Tuple[Dict[str, Dict[str, str]], List[str]]:
    """Parse a markdown parameter table into properties/required."""
    properties: Dict[str, Dict[str, str]] = {}
    required: List[str] = []

    lines = [line.strip() for line in text.splitlines()]
    in_table = False

    for line in lines:
        if line.startswith("|"):
            in_table = True
            if "----" in line:
                continue
            cells = [c.strip() for c in line.strip().strip("|").split("|")]
            if len(cells) < 4:
                continue

            param_name = cells[0].strip("`").strip()
            required_cell = cells[1].strip().lower()
            # 4カラム: param, required, type, description
            # 5カラム以上: 末尾に空セルがある場合
            if len(cells) >= 4:
                type_cell = cells[2].strip().lower()
                description = cells[3].strip()
            else:
                # 3カラム以下: type推測、descriptionは3番目
                type_cell = "string"
                description = cells[2].strip() if len(cells) > 2 else ""

            if param_name.lower() in {"parameter", "param", "name", "パラメータ"}:
                continue

            type_map = {
                "string": "string",
                "str": "string",
                "number": "number",
                "int": "integer",
                "integer": "integer",
                "float": "number",
                "bool": "boolean",
                "boolean": "boolean",
            }
            param_type = type_map.get(type_cell, "string")

            properties[param_name] = {
                "type": param_type,
                "description": description,
            }

            if required_cell in {"yes", "y", "required", "必須", "true"}:
                required.append(param_name)
        elif in_table:
            # Stop after the first table block to avoid parsing other tables.
            break

    return properties, required


def _load_action_doc_params(skill: "Skill", action: str) -> Tuple[Dict[str, Dict[str, str]], List[str], bool]:
    """Load parameters from actions/{action}.md if present."""
    if not skill.skill_dir:
        return {}, [], False

    action_file = skill.skill_dir / "actions" / f"{action}.md"
    if not action_file.exists():
        return {}, [], False

    try:
        content = action_file.read_text(encoding="utf-8")
    except Exception:
        return {}, [], False

    props, req = _parse_param_table_from_text(content)
    if not props and not req:
        return {}, [], False

    return props, req, True


def _core_action_params_match(
    core_action: Dict[str, Any],
    doc_properties: Dict[str, Dict[str, str]],
    doc_required: List[str],
) -> bool:
    """Strict equality check for params/required."""
    core_params = core_action.get("parameters", {})
    core_required = set(core_action.get("required", []))

    if set(core_params.keys()) != set(doc_properties.keys()):
        return False
    if set(doc_required) != core_required:
        return False

    return True


def _load_skill_md_params(skill: "Skill") -> Tuple[Dict[str, Dict[str, str]], List[str], bool]:
    """Load parameters from SKILL.md if present."""
    if not skill.raw_content:
        return {}, [], False

    props, req = skill.get_parameters()
    if not props and not req:
        return {}, [], False

    return props, req, True


# ============================================
# Native Tool Use: スキル→Tool変換
# ============================================

def convert_skill_to_tools(skill: "Skill") -> List[Dict[str, Any]]:
    """
    スキルをAnthropic Tool形式に変換

    各スキルのアクションを個別のツールとして定義。
    ツール名は `{skill_name}_{action}` 形式。

    Args:
        skill: Skillオブジェクト

    Returns:
        Anthropic Tool形式の辞書のリスト
    """
    tools = []

    # スキルごとのアクション定義
    skill_actions = SKILL_ACTIONS

    # スキルのアクション定義を取得
    actions = skill_actions.get(skill.name, {})

    if skill.name in CORE_SKILLS:
        _log_core_skill_mismatch(skill, actions)
        doc_params_ok = True
        doc_params_by_action: Dict[str, Tuple[Dict[str, Dict[str, str]], List[str]]] = {}

        for action_name, action_def in actions.items():
            doc_props, doc_required, parsed = _load_action_doc_params(skill, action_name)
            if not parsed:
                doc_params_ok = False
                break
            if not _core_action_params_match(action_def, doc_props, doc_required):
                doc_params_ok = False
                break
            doc_params_by_action[action_name] = (doc_props, doc_required)

        if doc_params_ok and doc_params_by_action:
            # Use doc-derived params (identical to core by strict check) without changing behavior.
            actions = {
                action_name: {
                    **action_def,
                    "parameters": doc_params_by_action[action_name][0],
                    "required": doc_params_by_action[action_name][1],
                }
                for action_name, action_def in actions.items()
            }
        else:
            # Fallback: try SKILL.md param table (typically for search) if it matches core exactly.
            skill_props, skill_required, parsed = _load_skill_md_params(skill)
            if parsed and "search" in actions:
                search_action = actions.get("search", {})
                if _core_action_params_match(search_action, skill_props, skill_required):
                    actions = {
                        **actions,
                        "search": {
                            **search_action,
                            "parameters": skill_props,
                            "required": skill_required,
                        },
                    }

    # 定義済みスキルの場合
    for action_name, action_def in actions.items():
        # パラメータスキーマを構築
        properties = {}
        required = action_def.get("required", [])

        for param_name, param_def in action_def.get("parameters", {}).items():
            properties[param_name] = {
                "type": param_def.get("type", "string"),
                "description": param_def.get("description", ""),
            }

        tool = {
            "name": f"{skill.name.replace('-', '_')}_{action_name}",
            "description": f"[{skill.display_name}] {action_def['description']}",
            "input_schema": {
                "type": "object",
                "properties": properties,
                "required": required,
            },
        }
        tools.append(tool)

    # スキルのアクション定義がない場合（SKILL.md + actions/*.mdから動的に読み取る）
    # 以前は "generated" タイプのみだったが、全スキルで動的読み取りを使用
    if not actions:
        # actions/*.md から利用可能なアクションを取得
        available_actions = skill.list_available_actions()
        if not available_actions:
            available_actions = ["execute"]  # デフォルトはexecute

        for action_name in available_actions:
            # actions/{action_name}.mdからパラメータを読み取る（優先）
            properties, required, parsed = _load_action_doc_params(skill, action_name)

            # actions/*.mdにパラメータがなければSKILL.mdから（フォールバック）
            if not parsed or not properties:
                properties, required = skill.get_parameters()

            # Progressive Disclosure: 詳細なdescription
            # フォーマット: [スキル説明（150文字まで）] アクション説明
            action_summary = skill.get_action_summary(action_name)
            skill_desc = skill.description[:150] if skill.description else skill.display_name
            full_description = f"[{skill_desc}] {action_summary}"

            tool = {
                "name": f"{skill.name.replace('-', '_')}_{action_name}",
                "description": full_description,
                "input_schema": {
                    "type": "object",
                    "properties": properties,
                    "required": required,
                },
            }
            tools.append(tool)

    return tools


def get_all_skill_tools() -> List[Dict[str, Any]]:
    """
    コアツールのみを返す

    スキルはツール化しない（Progressive Disclosure に基づく設計）。
    スキル一覧はシステムプロンプトに description のみで表示される。
    スキルを使う場合は check_skill で手順書を確認し、browser ツールで直接操作。

    Returns:
        コアツールのリスト
    """
    return [
        BROWSER_TOOL,
        READ_URL_TOOL,
        CREATE_PROPOSAL_TOOL,
        SAVE_CREDENTIALS_TOOL,
        GET_CREDENTIALS_TOOL,
        CHECK_SKILL_TOOL,
        READ_FILE_TOOL,
        WRITE_FILE_TOOL,
        EDIT_FILE_TOOL,
        BASH_TOOL,
        STUDIO_RECORD_TOOL,
        STUDIO_ENCODE_TOOL,
        STUDIO_PROBE_TOOL,
        STUDIO_EXTRACT_FRAME_TOOL,
        STUDIO_EVALUATE_TOOL,
    ]



# ============================================
# ブラウザ操作ツール（Dan直接操作）
# ============================================

BROWSER_TOOL = {
    "name": "browser",
    "description": "ブラウザを操作する。操作後にスクリーンショットと要素一覧を返す。evaluate: JSを実行して結果を返す。content: ページのHTML全体を取得する。keyboard_press: キーを押す（Escape, Tab等）。hover: 要素にマウスを乗せる。reload: ページを再読み込み。",
    "input_schema": {
        "type": "object",
        "properties": {
            "action": {
                "type": "string",
                "enum": ["open", "screenshot", "click", "type", "scroll", "back", "select", "evaluate", "content", "keyboard_press", "hover", "reload", "save_image"],
                "description": "実行するアクション",
            },
            "url": {"type": "string", "description": "開くURL（action=open）"},
            "ref": {"type": "string", "description": "操作対象の要素ref（例: @e1）"},
            "text": {"type": "string", "description": "入力テキスト（action=type）"},
            "press_enter": {"type": "boolean", "description": "入力後にEnterを押すか（action=type, デフォルト: false）"},
            "direction": {"type": "string", "enum": ["down", "up"], "description": "スクロール方向（action=scroll）"},
            "x": {"type": "integer", "description": "X座標（action=click, refが使えない場合）"},
            "y": {"type": "integer", "description": "Y座標（action=click, refが使えない場合）"},
            "value": {"type": "string", "description": "選択する値（action=select）"},
            "expression": {"type": "string", "description": "実行するJavaScriptコード（action=evaluate）"},
            "key": {"type": "string", "description": "押すキー（action=keyboard_press, 例: Escape, Tab, Enter, ArrowDown）"},
            "path": {"type": "string", "description": "保存先ファイルパス（action=save_image）"},
        },
        "required": ["action"]
    }
}

# ============================================
# URL読み込みツール（Jina Reader）
# ============================================

READ_URL_TOOL = {
    "name": "read_url",
    "description": """URLのページ内容を取得する。
検索結果のURLを実際に読んで詳細を確認したい時に使用。
Markdown形式でページ全文を返す。""",
    "input_schema": {
        "type": "object",
        "properties": {
            "url": {"type": "string", "description": "読み込むURL"}
        },
        "required": ["url"]
    }
}

# ============================================
# 認証情報: サービス名正規化
# ============================================

def _normalize_service_name(service: str) -> str:
    """
    サービス名を正規化して表記揺れを吸収する。

    例:
        "Amazon" → "amazon"
        "amazon.co.jp" → "amazon"
        "Amazon.co.jp" → "amazon"
        "rakuten" → "rakuten"
        "www.mercari.com" → "mercari"
    """
    s = service.strip().lower()
    # ドメイン形式の場合、ベース名を抽出
    if "." in s:
        # www.を除去
        if s.startswith("www."):
            s = s[4:]
        # 最初のドットより前をサービス名とする
        s = s.split(".")[0]
    # スペースやハイフンをアンダースコアに
    s = s.replace(" ", "_").replace("-", "_")
    return s

# ============================================
# 認証情報保存ツール
# ============================================

SAVE_CREDENTIALS_TOOL = {
    "name": "save_credentials",
    "description": """ユーザーから教えてもらった認証情報をDBに保存する。
ユーザーが「これ○○のログイン情報だから覚えといて」と言った時に使用。
保存した認証情報は次回以降のツール実行時に自動で使用される。

使用例:
- 「楽天のログイン覚えといて、ID: xxx, パスワード: yyy」→ 新規登録
- 「楽天のパスワード変わったから更新して。新しいのは zzz」→ password のみ指定（部分更新）
- 「楽天のID変えたから更新して」→ login_id のみ指定（部分更新）
- 「楽天のログインはAmazonと同じだよ」→ copy_from: "amazon" を使用""",
    "input_schema": {
        "type": "object",
        "properties": {
            "service": {
                "type": "string",
                "description": "保存先のサービス名（例: amazon, ex_reservation, rakuten, smartex）"
            },
            "login_id": {
                "type": "string",
                "description": "ログインID/メールアドレス/会員ID。新規登録時は必須。既存サービスの部分更新時は省略可（既存値を保持）"
            },
            "password": {
                "type": "string",
                "description": "パスワード。新規登録時は必須。既存サービスの部分更新時は省略可（既存値を保持）"
            },
            "copy_from": {
                "type": "string",
                "description": "コピー元のサービス名。「○○と同じ」という指示の場合に使用（例: amazon）"
            },
        },
        "required": ["service"],
    },
}

GET_CREDENTIALS_TOOL = {
    "name": "get_credentials",
    "description": """サービスの認証情報をDBから取得する。
ログインが必要なサイトを操作する前に、認証情報が保存済みか確認する時に使用。

返される内容:
- 保存済みの場合: ログインID と パスワード
- 未保存の場合: 認証情報が見つからない旨のメッセージ（ユーザーに聞くこと）""",
    "input_schema": {
        "type": "object",
        "properties": {
            "service": {
                "type": "string",
                "description": "サービス名（例: amazon, rakuten, mercari）"
            }
        },
        "required": ["service"],
    },
}

# ============================================
# スキル確認ツール（手順書取得）
# ============================================

CHECK_SKILL_TOOL = {
    "name": "check_skill",
    "description": """スキルの詳細（手順書）を取得する。
実行タスクで使えるスキルがあるか確認する時に使用。

使用タイミング:
- ユーザーが「○○を予約/購入/キャンセルして」と言った時
- 利用可能なツール一覧に関連しそうなスキルがある時
- ブラウザ操作の前に手順書を確認したい時

返される内容:
- SKILL.mdの本文（スキルの概要、使用方法）
- actions/*.md の内容（各アクションの詳細手順）""",
    "input_schema": {
        "type": "object",
        "properties": {
            "skill_name": {
                "type": "string",
                "description": "確認するスキル名（例: ex-reservation, amazon, rakuten）"
            }
        },
        "required": ["skill_name"]
    }
}

WORKSPACE_DIR = Path.home() / ".dan" / "workspace"

# ============================================
# コード実行ツール
# ============================================

EXEC_CODE_TOOL = {
    "name": "exec_code",
    "description": """Pythonコードを実行する。
API呼び出し、データ処理、計算、ファイル操作など、既存ツールでは対応できない操作に使用。
作業ディレクトリ: ~/.dan/sandbox/
タイムアウト: 30秒
pip install済みのライブラリが使用可能。""",
    "input_schema": {
        "type": "object",
        "properties": {
            "code": {
                "type": "string",
                "description": "実行するPythonコード"
            },
            "description": {
                "type": "string",
                "description": "コードの目的（ログ用）"
            }
        },
        "required": ["code"]
    }
}

# ============================================
# ファイル操作・コマンド実行ツール
# ============================================

READ_FILE_TOOL = {
    "name": "read_file",
    "description": "ファイルの内容を読み込む。",
    "input_schema": {
        "type": "object",
        "properties": {
            "path": {"type": "string", "description": "ファイルパス"}
        },
        "required": ["path"]
    }
}

WRITE_FILE_TOOL = {
    "name": "write_file",
    "description": "ファイルに内容を書き込む（上書きまたは新規作成）。",
    "input_schema": {
        "type": "object",
        "properties": {
            "path": {"type": "string", "description": "ファイルパス"},
            "content": {"type": "string", "description": "書き込む内容"}
        },
        "required": ["path", "content"]
    }
}

EDIT_FILE_TOOL = {
    "name": "edit_file",
    "description": "ファイル内の文字列を置換して編集する。",
    "input_schema": {
        "type": "object",
        "properties": {
            "path": {"type": "string", "description": "ファイルパス"},
            "old_string": {"type": "string", "description": "置換前の文字列"},
            "new_string": {"type": "string", "description": "置換後の文字列"}
        },
        "required": ["path", "old_string", "new_string"]
    }
}

BASH_TOOL = {
    "name": "bash",
    "description": "シェルコマンドを実行する。git操作、npm、pip install等に使用。\n\n重要: bash で find/grep/cat/head/tail を実行してはいけない。代わりに専用ツールを使うこと:\n- ファイル検索: glob ツール（find や ls ではなく）\n- 内容検索: grep ツール（bash の grep/rg ではなく）\n- ファイル読み取り: read_file ツール（cat/head/tail ではなく）",
    "input_schema": {
        "type": "object",
        "properties": {
            "command": {"type": "string", "description": "実行するコマンド"}
        },
        "required": ["command"]
    }
}

# ============================================
# プロジェクト管理ツール
# ============================================

CREATE_PROPOSAL_TOOL = {
    "name": "create_proposal",
    "description": "ユーザーに承認を求める提案を作成する。新しい作業を始める前や、重要な方針変更を行う時に使用。UIに承認/却下ボタンが自動表示される。軽微な質問・調査・修正には使わない。",
    "input_schema": {
        "type": "object",
        "properties": {
            "title": {
                "type": "string",
                "description": "提案のタイトル（例: HP制作計画）"
            },
            "steps": {
                "type": "array",
                "items": {"type": "string"},
                "description": "実行ステップのリスト。各ステップは「何を」「どうやって」を含む（例: ['v0.devでプロ品質コンポーネント生成', 'Claude Codeでコード調整・統合']）"
            },
        },
        "required": ["title", "steps"]
    }
}

# ============================================
# コード探索ツール
# ============================================

GLOB_TOOL = {
    "name": "glob",
    "description": "ファイルをパターンで検索する。例: '**/*.tsx', 'src/**/*.py', '*.md'。ファイル名や拡張子でファイルを探す時に使う。",
    "input_schema": {
        "type": "object",
        "properties": {
            "pattern": {"type": "string", "description": "globパターン（例: **/*.tsx, src/**/*.py）"},
            "path": {"type": "string", "description": "検索開始ディレクトリ（省略時: D:/done）"}
        },
        "required": ["pattern"]
    }
}

GREP_TOOL = {
    "name": "grep",
    "description": "ファイル内容をテキスト/正規表現で検索する。関数定義、クラス名、文字列の使用箇所などを探す時に使う。",
    "input_schema": {
        "type": "object",
        "properties": {
            "pattern": {"type": "string", "description": "検索パターン（正規表現対応）"},
            "path": {"type": "string", "description": "検索対象のディレクトリまたはファイル（省略時: D:/done）"},
            "glob": {"type": "string", "description": "対象ファイルのフィルタ（例: *.py, *.tsx）"},
            "context": {"type": "integer", "description": "前後に表示する行数（デフォルト: 2）"}
        },
        "required": ["pattern"]
    }
}


# ============================================
# スタジオ録画/エンコードツール（バックエンド実行）
# ============================================

STUDIO_RECORD_TOOL = {
    "name": "studio_record",
    "description": """HTMLファイルをPlaywright headless Chromiumで録画して.webmファイルを生成する。
バックエンド(FastAPI)プロセスで実行されるため、Bash経由のPlaywright録画より安定。
録画後のファイルパスを返す。""",
    "input_schema": {
        "type": "object",
        "properties": {
            "html_path": {"type": "string", "description": "録画対象のHTMLファイルパス（例: D:/dan-workspace/proposals/demo.html）"},
            "output_dir": {"type": "string", "description": "出力ディレクトリ（例: D:/dan-workspace/proposals/output）"},
            "duration_sec": {"type": "integer", "description": "録画秒数（例: 52）"},
            "width": {"type": "integer", "description": "ビューポート幅（デフォルト: 1920）"},
            "height": {"type": "integer", "description": "ビューポート高さ（デフォルト: 1080）"},
            "serve_dir": {"type": "string", "description": "HTTPサーバーのルートディレクトリ。指定時はHTMLをHTTP経由で開く（base64画像のクラッシュ回避）"},
            "pre_wait_ms": {"type": "integer", "description": "録画開始前の待機ミリ秒（デフォルト: 5000）"},
            "js_eval": {"type": "string", "description": "録画開始後に実行するJS（例: video要素の強制再生）"},
        },
        "required": ["html_path", "output_dir", "duration_sec"],
    },
}

STUDIO_ENCODE_TOOL = {
    "name": "studio_encode",
    "description": """FFmpegで動画を変換/エンコードする。WebM→MP4変換、解像度変更、コーデック変換などに使用。
バックエンドで実行されるため1080pエンコードもメモリ制限なしで動作する。""",
    "input_schema": {
        "type": "object",
        "properties": {
            "input_path": {"type": "string", "description": "入力動画ファイルパス"},
            "output_path": {"type": "string", "description": "出力動画ファイルパス（例: D:/dan-workspace/output/final.mp4）"},
            "width": {"type": "integer", "description": "出力幅（デフォルト: 1920）"},
            "height": {"type": "integer", "description": "出力高さ（デフォルト: 1080）"},
            "codec": {"type": "string", "description": "コーデック（デフォルト: libx264）"},
            "crf": {"type": "integer", "description": "品質 0-51（デフォルト: 20、低いほど高品質）"},
            "preset": {"type": "string", "description": "速度 ultrafast/fast/medium/slow（デフォルト: fast）"},
            "extra_args": {"type": "string", "description": "追加FFmpeg引数（デフォルト: -pix_fmt yuv420p -movflags +faststart）"},
        },
        "required": ["input_path", "output_path"],
    },
}

STUDIO_PROBE_TOOL = {
    "name": "studio_probe",
    "description": "動画ファイルのメタ情報（コーデック、解像度、長さ、サイズ）を取得する。",
    "input_schema": {
        "type": "object",
        "properties": {
            "path": {"type": "string", "description": "動画ファイルパス"},
        },
        "required": ["path"],
    },
}

STUDIO_EVALUATE_TOOL = {
    "name": "studio_evaluate",
    "description": """完成動画をGemini APIに送り、指定した基準で品質を評価する。
各基準についてOK/NG判定とタイムスタンプ付きの具体的な指摘を返す。
send_fileでユーザーに送る前に必ず実行し、NGがあれば修正してから送ること。""",
    "input_schema": {
        "type": "object",
        "properties": {
            "video_path": {"type": "string", "description": "評価対象の動画ファイルパス（MP4）"},
            "criteria": {"type": "string", "description": "評価基準（例: '1. 実写映像が5箇所で使われている 2. テキストが読める大きさ 3. トランジションが滑らか'）"},
        },
        "required": ["video_path", "criteria"],
    },
}

STUDIO_EXTRACT_FRAME_TOOL = {
    "name": "studio_extract_frame",
    "description": "動画から指定時刻のフレームをPNG画像として抽出する。動画の内容検証に使用。",
    "input_schema": {
        "type": "object",
        "properties": {
            "video_path": {"type": "string", "description": "動画ファイルパス"},
            "timestamp": {"type": "string", "description": "抽出時刻（例: '3', '1:30'）"},
            "output_path": {"type": "string", "description": "出力PNGパス"},
        },
        "required": ["video_path", "timestamp", "output_path"],
    },
}


def parse_tool_name(tool_name: str) -> Optional[Tuple[str, str]]:
    """
    Parse tool name into (skill_name, action).

    Args:
        tool_name: tool name string, e.g. ex_reservation_search

    Returns:
        (skill_name, action) or None
    """
    if tool_name == "save_credentials":
        return ("_save_credentials", "save")

    if tool_name == "get_credentials":
        return ("_get_credentials", "get")

    if tool_name == "check_skill":
        return ("_check_skill", "check")

    if tool_name == "browser":
        return ("_browser", "__from_params")

    # Legacy fallback: browser_open, browser_click etc. (in-flight sessions)
    if tool_name.startswith("browser_"):
        action = tool_name[len("browser_"):]
        return ("_browser", action)

    if tool_name == "read_url":
        return ("_jina", "read")

    if tool_name == "create_proposal":
        return ("_create_proposal", "create")

    if tool_name.startswith("studio_"):
        action = tool_name[len("studio_"):]
        return ("_studio_render", action)

    if tool_name == "read_file":
        return ("_read_file", "read")

    if tool_name == "write_file":
        return ("_write_file", "write")

    if tool_name == "edit_file":
        return ("_edit_file", "edit")

    if tool_name == "bash":
        return ("_bash", "run")

    # Prefer the longest matching skill prefix to avoid collisions.
    all_skills = SkillRegistry.list_all()
    matches: List[Tuple[int, str, str]] = []
    for skill in all_skills:
        skill_prefix = skill.name.replace("-", "_")
        if tool_name.startswith(skill_prefix + "_"):
            action = tool_name[len(skill_prefix) + 1:]
            matches.append((len(skill_prefix), skill.name, action))
    if matches:
        matches.sort(key=lambda item: item[0], reverse=True)
        _, skill_name, action = matches[0]
        return (skill_name, action)

    # Fallback: core skill prefixes (legacy behavior).
    for skill_prefix in CORE_SKILL_PREFIXES:
        if tool_name.startswith(skill_prefix + "_"):
            action = tool_name[len(skill_prefix) + 1:]
            skill_name = skill_prefix.replace("_", "-")
            return (skill_name, action)

    return None

SKILL_DIRECTORIES = [
    Path(__file__).parent / "skills",
    Path(__file__).parent.parent.parent.parent / ".claude" / "skills",
]


async def _record_issue_for_failure(
    result: Dict[str, Any],
    skill_name: str,
    action: str,
    params: Dict[str, Any],
    user_id: str,
    skill: Optional["Skill"] = None,
) -> None:
    """失敗時にイシューを記録（ツール実行共通）"""
    try:
        if result.get("success"):
            return
        if result.get("cancelled"):
            return
        if result.get("issue_recorded"):
            return
        if skill_name == "_jina":
            return

        error_type = result.get("error_type")
        if result.get("credentials_required") or error_type in (
            "credentials_required",
            "credentials_invalid",
            "session_expired",
        ):
            return

        from app.services.issue_tracker import IssueTracker, Issue, IssueType

        issue_type = IssueType.EXECUTION_FAILED
        if result.get("requires_user_input"):
            issue_type = IssueType.USER_INPUT_REQUIRED
        elif error_type in ("selector_not_found", "selector_outdated"):
            issue_type = IssueType.SELECTOR_OUTDATED
        elif action == "search":
            issue_type = IssueType.SEARCH_FAILED

        if skill_name == "_browser":
            service_type = "browser"
            service_name = params.get("url", "browser")
            domain = params.get("site")
            parent_skill = None
        else:
            service_type = skill.service_type if skill else "skill"
            service_name = skill.service_name if skill else skill_name
            domain = skill.domain if skill else None
            parent_skill = skill.parent_skill if skill else None

        original_wish = (
            params.get("task")
            or params.get("query")
            or params.get("prompt")
            or f"{skill_name}:{action}"
        )

        screenshots = []
        if isinstance(result.get("screenshots"), list):
            screenshots = result.get("screenshots", [])
        else:
            screenshot_path = result.get("screenshot_path") or result.get("screenshot")
            if screenshot_path:
                screenshots = [screenshot_path]
            else:
                browser_state = result.get("browser_state")
                if isinstance(browser_state, dict) and browser_state.get("screenshot_path"):
                    screenshots = [browser_state["screenshot_path"]]

        html_snapshot_path = result.get("html_snapshot_path")

        page_url = result.get("page_url")
        if not page_url:
            browser_state = result.get("browser_state")
            if isinstance(browser_state, dict):
                page_url = browser_state.get("url")

        error_message = result.get("error") or result.get("message") or "Unknown error"
        error_details = {
            "action": action,
            "params": params,
            "error_type": error_type,
            "details": result.get("details") or {},
        }

        issue = Issue(
            issue_type=issue_type,
            original_wish=original_wish,
            service_type=service_type,
            service_name=service_name,
            domain=domain,
            parent_skill=parent_skill,
            research_result={},
            error_message=error_message,
            error_details=error_details,
            user_id=user_id,
            screenshots=screenshots,
            html_snapshot_path=html_snapshot_path,
            page_url=page_url,
        )

        tracker = IssueTracker()
        await tracker.record_issue(issue)
    except Exception:
        logger.exception("Failed to record issue on tool failure")


@dataclass
class Skill:
    """スキル定義"""
    name: str
    display_name: str
    description: str
    service_type: Optional[str] = None
    service_name: Optional[str] = None
    domain: Optional[str] = None
    parent_skill: Optional[str] = None
    raw_content: str = ""
    skill_dir: Optional[Path] = None  # スキルディレクトリへのパス
    # Progressive Disclosure用の新規フィールド
    frontmatter: Dict[str, Any] = field(default_factory=dict)
    markdown_content: str = ""  # frontmatter除外後のMarkdown本文

    def get_action_manual(self, action: str) -> Optional[str]:
        """
        アクション固有のマニュアルを取得（Progressive Disclosure）

        Args:
            action: アクション名（search, cancel など）

        Returns:
            actions/{action}.md の内容、または None
        """
        if not self.skill_dir:
            return None

        action_file = self.skill_dir / "actions" / f"{action}.md"
        if action_file.exists():
            try:
                return action_file.read_text(encoding="utf-8")
            except Exception as e:
                logger.warning(f"Failed to load action manual {action_file}: {e}")
                return None
        return None

    def get_action_summary(self, action: str) -> str:
        """
        アクションの1行サマリを取得（ツールdescription用）

        Args:
            action: アクション名

        Returns:
            アクションの短い説明（最大100文字）
        """
        # actions/{action}.md から最初の説明文を抽出
        manual = self.get_action_manual(action)
        if not manual:
            return f"Execute {action} action"

        # 最初の非見出し行を取得
        lines = manual.strip().split('\n')
        for line in lines:
            line = line.strip()
            if line and not line.startswith('#'):
                return line[:100]

        return f"Execute {action} action"

    def list_available_actions(self) -> List[str]:
        """
        利用可能なアクション一覧を取得

        Returns:
            アクション名のリスト
        """
        if not self.skill_dir:
            return []

        actions_dir = self.skill_dir / "actions"
        if not actions_dir.exists():
            return []

        actions = []
        for action_file in actions_dir.glob("*.md"):
            actions.append(action_file.stem)
        return actions

    def get_parameters(self) -> Tuple[Dict[str, Dict[str, str]], List[str]]:
        """
        SKILL.mdからパラメータ定義を解析

        Returns:
            (properties, required): Anthropic Tool形式のproperties辞書とrequiredリスト
        """
        properties = {}
        required = []

        if not self.raw_content:
            return properties, required

        # パラメータテーブルを探す
        # 形式: | パラメータ | 必須 | 説明 | 例 |
        #       | location | ○ | 地域名 | 東京 |
        param_section = re.search(
            r'##\s*パラメータ\s*\n(.*?)(?=\n##|\Z)',
            self.raw_content,
            re.DOTALL
        )

        if not param_section:
            return properties, required

        section_content = param_section.group(1)

        # テーブル行をパース
        # | param_name | ○/× | description | example |
        table_rows = re.findall(
            r'\|\s*(\w+)\s*\|\s*([○×])\s*\|\s*([^|]+)\s*\|',
            section_content
        )

        for param_name, is_required, description in table_rows:
            # ヘッダー行をスキップ
            if param_name in ('パラメータ', 'parameter', 'name'):
                continue

            properties[param_name] = {
                "type": "string",
                "description": description.strip(),
            }

            if is_required == "○":
                required.append(param_name)

        return properties, required


    def get_group(self) -> str:
        """Return canonical group for listing/filtering."""
        if self.parent_skill:
            return self.parent_skill
        if self.service_name:
            return self.service_name
        if self.domain:
            return self.domain
        return self.name

    @staticmethod
    def _parse_frontmatter(content: str) -> Tuple[Dict[str, Any], str]:
        """
        YAML frontmatterとMarkdown本文を分離（Progressive Disclosure）

        Args:
            content: SKILL.mdの内容

        Returns:
            (frontmatter辞書, Markdown本文)
        """
        import yaml

        if not content.startswith("---"):
            return {}, content

        parts = content.split("---", 2)
        if len(parts) < 3:
            return {}, content

        try:
            frontmatter = yaml.safe_load(parts[1])
            markdown_content = parts[2].strip()
            return frontmatter or {}, markdown_content
        except yaml.YAMLError as e:
            logger.warning(f"Failed to parse YAML frontmatter: {e}")
            return {}, content

    @classmethod
    def from_file(cls, name: str, filepath: Path) -> "Skill":
        """SKILL.mdからスキルを読み込み（Progressive Disclosure対応）"""
        content = filepath.read_text(encoding="utf-8")

        # YAML frontmatterをパース（Progressive Disclosure）
        frontmatter, markdown_content = cls._parse_frontmatter(content)

        # name: frontmatter優先、なければディレクトリ名
        skill_name = frontmatter.get("name", name)

        # description: frontmatter優先（Progressive Disclosureの核心）
        # frontmatterのdescriptionには「いつこのスキルを使うべきか」が記載されている
        description = frontmatter.get("description", "")
        if not description:
            # フォールバック: 従来の方式
            desc_match = re.search(r'##\s*サービス概要\s*\n(.+?)(?=\n##|\Z)', content, re.DOTALL)
            if desc_match:
                description = desc_match.group(1).strip()[:200]

        # display_name: frontmatter優先、なければタイトルから
        display_name = frontmatter.get("display_name")
        if not display_name:
            title_match = re.search(r'^#\s+(.+)$', content, re.MULTILINE)
            if title_match:
                display_name = cls._normalize_display_name(title_match.group(1).strip())
            else:
                display_name = skill_name

        # parent_skill / domain: frontmatter優先
        parent_skill = frontmatter.get("parent_skill") or frontmatter.get("parent")
        if not parent_skill:
            parent_match = re.search(r'^\s*(parent_skill|parent)\s*:\s*(.+)$', content, re.MULTILINE | re.IGNORECASE)
            if parent_match:
                parent_skill = parent_match.group(2).strip()

        domain = frontmatter.get("domain") or frontmatter.get("site")
        if not domain:
            domain_match = re.search(r'^\s*(domain|site)\s*:\s*(.+)$', content, re.MULTILINE | re.IGNORECASE)
            if domain_match:
                domain = cls._normalize_domain(domain_match.group(2))
            else:
                url_match = re.search(r'https?://([^/\s]+)', content)
                if url_match:
                    domain = cls._normalize_domain(url_match.group(1))

        service_type, service_name = cls._guess_service(content, name)

        # If a local executor.py exists, treat as generated to use its executor.
        has_executor = (filepath.parent / "executor.py").exists()
        if has_executor:
            service_type = "generated"

        return cls(
            name=skill_name,
            display_name=display_name,
            description=description,
            service_type=service_type,
            service_name=service_name,
            domain=domain,
            parent_skill=parent_skill,
            raw_content=content,
            skill_dir=filepath.parent,
            # Progressive Disclosure用の新規フィールド
            frontmatter=frontmatter,
            markdown_content=markdown_content if markdown_content else content,
        )



    @staticmethod
    def _normalize_display_name(name: str) -> str:
        """Normalize display name (remove versions/parentheses)."""
        normalized = name.strip()
        normalized = re.sub(r'\s*\([^)]*\)\s*$', '', normalized)
        normalized = re.sub(r'\bSkill\b', '', normalized, flags=re.IGNORECASE)
        normalized = re.sub(r'\bv\d+\b', '', normalized, flags=re.IGNORECASE)
        normalized = re.sub(r'\s{2,}', ' ', normalized).strip()
        return normalized

    @staticmethod
    def _normalize_domain(value: str) -> str:
        """Normalize a domain string (strip scheme/path)."""
        val = value.strip().lower()
        val = re.sub(r'^https?://', '', val)
        val = val.split('/')[0]
        return val

    @staticmethod
    def _guess_service(content: str, name: str) -> Tuple[Optional[str], Optional[str]]:
        """コンテンツからサービスタイプを推測"""
        content_lower = content.lower()

        # 名前による判定を優先（最も確実）
        if name == "developer":
            return "developer", "developer"
        elif name == "ex-reservation":
            return "train", "ex_reservation"
        elif name == "frontend-design":
            return "frontend", "frontend_design"
        elif name == "amazon":
            return "product", "amazon"

        # 内容による判定（フォールバック）
        if "developer" in name or "開発機能" in content or "self-healing" in content_lower:
            return "developer", "developer"
        elif "ex予約" in content or "新幹線" in content:
            return "train", "ex_reservation"
        elif "amazon" in content_lower:
            return "product", "amazon"
        elif "楽天" in content:
            return "product", "rakuten"
        elif "高速バス" in content:
            return "bus", "willer"
        elif "電話" in content or "音声" in content:
            return "voice", "phone"

        # 自動生成されたスキル（executor.pyがあれば generated タイプ）
        # service_name は skill name を使用
        return "generated", name.replace("-", "_")


class SkillRegistry:
    """スキルの登録・検索"""

    _instance: Optional["SkillRegistry"] = None
    _skills: Dict[str, Skill]
    _loaded: bool

    def __new__(cls):
        if cls._instance is None:
            cls._instance = super().__new__(cls)
            cls._instance._skills = {}
            cls._instance._loaded = False
        return cls._instance

    @classmethod
    def load(cls) -> None:
        """全スキルを読み込み"""
        instance = cls()
        if instance._loaded:
            return

        def find_skills(directory: Path, depth: int = 0) -> None:
            """再帰的にSKILL.mdを検索（最大深度3）"""
            if depth > 3 or not directory.exists():
                return

            for path in directory.iterdir():
                if path.is_dir():
                    skill_file = path / "SKILL.md"
                    if skill_file.exists():
                        try:
                            skill = Skill.from_file(path.name, skill_file)
                            instance._skills[skill.name] = skill
                            logger.info(f"Loaded skill: {skill.name}")
                        except Exception as e:
                            logger.warning(f"Failed to load skill {path.name}: {e}")
                    else:
                        # サブディレクトリを再帰的に検索
                        find_skills(path, depth + 1)

        for skill_dir in SKILL_DIRECTORIES:
            find_skills(skill_dir)

        instance._loaded = True

    @classmethod
    def reload(cls) -> None:
        """Reload all skills from disk."""
        instance = cls()
        instance._skills = {}
        instance._loaded = False
        cls.load()

    @classmethod
    def get(cls, name: str) -> Optional[Skill]:
        """スキルを取得"""
        cls.load()
        return cls()._skills.get(name)

    @classmethod
    def list_all(cls) -> List[Skill]:
        """全スキルをリスト"""
        cls.load()
        return list(cls()._skills.values())

    @classmethod
    def get_prompt(cls, name: str) -> str:
        """スキルのプロンプト（SKILL.md内容）を取得"""
        skill = cls.get(name)
        return skill.raw_content if skill else ""

    @classmethod
    def get_action_manual(cls, skill_name: str, action: str) -> Optional[str]:
        """
        アクション固有のマニュアルを取得

        Args:
            skill_name: スキル名
            action: アクション名

        Returns:
            アクションマニュアルの内容、または None
        """
        skill = cls.get(skill_name)
        if skill:
            return skill.get_action_manual(action)
        return None


def parse_tool_call(response: str) -> Optional[Dict[str, Any]]:
    """
    LLMのレスポンスからツール呼び出しを検出・パース

    期待するフォーマット:
    ```
    [TOOL: ex-reservation search]
    departure: 東京
    arrival: 新大阪
    date: 2026-01-15
    time: 19:00
    ```

    Returns:
        {
            "skill": "ex-reservation",
            "action": "search",
            "params": {"departure": "東京", ...}
        }
        または None
    """
    # [TOOL: skill-name action] を検出
    match = re.search(r'\[TOOL:\s*(\S+)\s+(\w+)\]', response)
    if not match:
        return None

    skill_name = match.group(1)
    action = match.group(2)

    logger.debug("Found tool call: %s %s", skill_name, action)

    # パラメータを抽出（key: value 形式）
    params = {}
    tool_pos = match.end()
    remaining = response[tool_pos:]

    # 次の[TOOL:]または空行2つまでをパラメータとして扱う
    param_section = re.split(r'\n\n|\[TOOL:', remaining)[0]

    logger.debug("Param section:\n%s...", param_section[:300])

    for line in param_section.split('\n'):
        line = line.strip()
        if ':' in line and not line.startswith('['):
            key, value = line.split(':', 1)
            key = key.strip().lower().replace(' ', '_')
            value = value.strip()
            if key and value:
                params[key] = value
                logger.debug("Extracted param: %s=%s", key, value[:20] if len(value) > 20 else value)

    logger.debug("Total params extracted: %d", len(params))

    return {
        "skill": skill_name,
        "action": action,
        "params": params,
    }


async def execute_tool(
    tool_call: Dict[str, Any],
    user_id: str,
    credentials: Optional[Dict[str, str]] = None,
    session_id: Optional[str] = None,
) -> Dict[str, Any]:
    """
    ツールを実行

    Args:
        tool_call: parse_tool_call()の戻り値
        user_id: ユーザーID
        credentials: 認証情報
        session_id: セッションID（キャンセルチェック用）

    Returns:
        実行結果
    """
    skill_name = tool_call["skill"]
    action = tool_call["action"]
    params = tool_call["params"]

    # ★★★ スタジオ録画/エンコード（バックエンド実行）★★★
    if skill_name == "_studio_render":
        from app.services.studio_render_service import StudioRenderService
        svc = StudioRenderService()
        try:
            if action == "record":
                return await svc.record(**params)
            elif action == "encode":
                return await svc.encode(**params)
            elif action == "probe":
                return await svc.probe(**params)
            elif action == "extract_frame":
                return await svc.extract_frame(**params)
            elif action == "evaluate":
                return await svc.evaluate(**params)
            else:
                return {"success": False, "error": f"Unknown studio action: {action}"}
        except Exception as e:
            logger.error(f"[studio_{action}] Error: {e}", exc_info=True)
            return {"success": False, "error": str(e)}

    # ★★★ コード実行（外部依存なし）★★★
    if skill_name == "_exec_code":
        code = params.get("code", "")
        desc = params.get("description", "")
        if desc:
            logger.info(f"[EXEC] {desc[:80]}")
        from app.tools.code_executor import execute_python
        return await execute_python(code)

    # ★★★ ファイル読み込み ★★★
    if skill_name == "_read_file":
        path = params.get("path", "")
        if not path:
            return {"success": False, "error": "path が必要です"}
        try:
            p = Path(path)
            if not p.exists():
                return {"success": False, "error": f"ファイルが存在しません: {path}"}
            content = p.read_text(encoding="utf-8")
            return {"success": True, "path": path, "content": content}
        except Exception as e:
            return {"success": False, "error": f"読み取りエラー: {e}"}

    # ★★★ ファイル書き込み ★★★
    if skill_name == "_write_file":
        path = params.get("path", "")
        content = params.get("content", "")
        if not path:
            return {"success": False, "error": "path が必要です"}
        try:
            p = Path(path)
            p.parent.mkdir(parents=True, exist_ok=True)
            p.write_text(content, encoding="utf-8")
            return {"success": True, "path": path, "message": f"書き込み完了 ({len(content)} chars)"}
        except Exception as e:
            return {"success": False, "error": f"書き込みエラー: {e}"}

    # ★★★ ファイル編集（文字列置換）★★★
    if skill_name == "_edit_file":
        path = params.get("path", "")
        old_string = params.get("old_string", "")
        new_string = params.get("new_string", "")
        if not path:
            return {"success": False, "error": "path が必要です"}
        if not old_string:
            return {"success": False, "error": "old_string が必要です"}
        try:
            p = Path(path)
            if not p.exists():
                return {"success": False, "error": f"ファイルが存在しません: {path}"}
            content = p.read_text(encoding="utf-8")
            if old_string not in content:
                return {"success": False, "error": "old_string が見つかりません"}
            new_content = content.replace(old_string, new_string, 1)
            p.write_text(new_content, encoding="utf-8")
            return {"success": True, "path": path, "message": "編集完了"}
        except Exception as e:
            return {"success": False, "error": f"編集エラー: {e}"}

    # ★★★ シェルコマンド実行 ★★★
    if skill_name == "_bash":
        command = params.get("command", "")
        if not command:
            return {"success": False, "error": "command が必要です"}
        try:
            import subprocess
            import sys as _sys
            # Windows: Git Bash で実行（ls, find, grep 等が使える）
            if _sys.platform == "win32":
                git_bash = r"C:\Program Files\Git\usr\bin\bash.exe"
                result = subprocess.run(
                    [git_bash, "-c", command],
                    capture_output=True, timeout=120,
                    cwd="D:/done",
                )
                # Git Bash は UTF-8 で出力するので明示的にデコード
                result = subprocess.CompletedProcess(
                    result.args, result.returncode,
                    stdout=result.stdout.decode("utf-8", errors="replace") if result.stdout else "",
                    stderr=result.stderr.decode("utf-8", errors="replace") if result.stderr else "",
                )
            else:
                result = subprocess.run(
                    command, shell=True, capture_output=True, text=True, timeout=120,
                )
            output = result.stdout
            if result.stderr:
                output += "\n[STDERR]\n" + result.stderr
            return {
                "success": result.returncode == 0,
                "command": command,
                "exit_code": result.returncode,
                "output": output[:10000],
            }
        except subprocess.TimeoutExpired:
            return {"success": False, "error": f"タイムアウト (120秒): {command}"}
        except Exception as e:
            return {"success": False, "error": f"実行エラー: {e}"}

    # ★★★ ファイル検索（glob）★★★
    if skill_name == "_glob":
        pattern = params.get("pattern", "")
        search_path = params.get("path", "D:/done")
        if not pattern:
            return {"success": False, "error": "pattern が必要です"}
        try:
            import re as _re
            base = Path(search_path)
            if not base.exists():
                return {"success": False, "error": f"ディレクトリが存在しません: {search_path}"}

            # Python glob はブレース展開 {tsx,jsx} をサポートしないので手動展開
            brace_match = _re.search(r'\{([^}]+)\}', pattern)
            if brace_match:
                alternatives = brace_match.group(1).split(",")
                all_matches = []
                for alt in alternatives:
                    expanded = pattern[:brace_match.start()] + alt.strip() + pattern[brace_match.end():]
                    all_matches.extend(str(p) for p in base.glob(expanded))
                matches = sorted(set(all_matches))
            else:
                matches = sorted(str(p) for p in base.glob(pattern))

            # node_modules, .git, __pycache__ 等を除外
            exclude_dirs = {"node_modules", ".git", "__pycache__", ".next", "venv", ".venv"}
            filtered = [
                m for m in matches
                if not any(ex in m.replace("\\", "/").split("/") for ex in exclude_dirs)
            ]
            return {
                "success": True,
                "pattern": pattern,
                "path": search_path,
                "count": len(filtered),
                "files": filtered[:200],
                "truncated": len(filtered) > 200,
            }
        except Exception as e:
            return {"success": False, "error": f"glob エラー: {e}"}

    # ★★★ 内容検索（grep）★★★
    if skill_name == "_grep":
        pattern = params.get("pattern", "")
        search_path = params.get("path", "D:/done")
        file_glob = params.get("glob", "")
        context_lines = params.get("context", 2)
        if not pattern:
            return {"success": False, "error": "pattern が必要です"}
        try:
            import subprocess as sp
            import shutil
            # ripgrep (rg) のパスを検出
            rg_path = shutil.which("rg")
            if not rg_path:
                # winget インストール先を直接チェック
                winget_rg = Path.home() / "AppData/Local/Microsoft/WinGet/Links/rg.exe"
                if winget_rg.exists():
                    rg_path = str(winget_rg)
            if rg_path:
                cmd = [rg_path, "--no-heading", "-n", f"-C{context_lines}", "--max-count=50"]
                if file_glob:
                    cmd.extend(["--glob", file_glob])
                for ex in ["node_modules", ".git", "__pycache__", ".next", "venv"]:
                    cmd.extend(["--glob", f"!{ex}"])
                cmd.append(pattern)
                cmd.append(search_path)
                result = sp.run(cmd, capture_output=True, text=True, timeout=30, encoding="utf-8", errors="replace")
                output = result.stdout
            else:
                # findstr フォールバック
                fallback_cmd = f'findstr /S /N /R /C:"{pattern}" "{search_path}\\*"'
                if file_glob:
                    ext = file_glob.replace("*", "")
                    fallback_cmd = f'findstr /S /N /R /C:"{pattern}" "{search_path}\\*{ext}"'
                result = sp.run(fallback_cmd, shell=True, capture_output=True, text=True, timeout=30, encoding="utf-8", errors="replace")
                output = result.stdout
            # 出力を制限
            lines = output.splitlines()
            truncated = len(lines) > 500
            return {
                "success": True,
                "pattern": pattern,
                "path": search_path,
                "match_lines": len(lines),
                "output": "\n".join(lines[:500]),
                "truncated": truncated,
            }
        except Exception as e:
            return {"success": False, "error": f"grep エラー: {e}"}

    # 以下は外部依存あり
    from app.services.cancellation import CancellationRegistry

    # セッションIDを現在のコンテキストに設定（深い階層でもチェック可能に）
    if session_id:
        CancellationRegistry.set_current_session(session_id)

    # キャンセルチェック（ツール実行開始時）
    if session_id and CancellationRegistry.is_cancelled(session_id):
        logger.info(f"Tool execution cancelled before start: {session_id}")
        return {
            "success": False,
            "error": "処理がキャンセルされました",
            "cancelled": True,
        }

    # Executorを登録（初回のみ実行される）- 存在しない場合はスキップ
    try:
        from app.executors.registry import register_all_executors
        register_all_executors()
    except ImportError:
        pass  # registry が存在しない場合はスキップ

    # ★★★ 認証情報取得 ★★★
    if skill_name == "_get_credentials":
        service = params.get("service")
        if not service:
            return {"success": False, "error": "service が必要です"}

        # サービス名を正規化（小文字、ドメイン部分除去）
        service_normalized = _normalize_service_name(service)

        from app.services.credentials_service import get_credentials_service
        creds_service = get_credentials_service()

        # 正規化名で検索 → 元の名前でフォールバック
        stored_creds = await creds_service.get_credential(user_id, service_normalized)
        if not stored_creds and service_normalized != service:
            stored_creds = await creds_service.get_credential(user_id, service)

        if stored_creds:
            return {
                "success": True,
                "service": service_normalized,
                "login_id": stored_creds.get("id", ""),
                "password": stored_creds.get("password", ""),
                "message": f"{service} の認証情報が見つかりました",
            }
        else:
            return {
                "success": False,
                "service": service_normalized,
                "message": f"{service} の認証情報は保存されていません。ユーザーに聞いてください。",
            }

    # ★★★ 認証情報保存 ★★★
    if skill_name == "_save_credentials":
        service = params.get("service")
        copy_from = params.get("copy_from")
        login_id = params.get("login_id")
        password = params.get("password")

        if not service:
            return {
                "success": False,
                "error": "service が必要です",
            }

        # サービス名を正規化（小文字、ドメイン部分除去）
        service = _normalize_service_name(service)
        if copy_from:
            copy_from = _normalize_service_name(copy_from)

        from app.services.credentials_service import get_credentials_service
        creds_service = get_credentials_service()

        # copy_from が指定されている場合、コピー元から取得
        if copy_from:
            source_creds = await creds_service.get_credential(user_id, copy_from)
            if not source_creds:
                return {
                    "success": False,
                    "error": f"{copy_from}の認証情報が見つかりません。先に{copy_from}の認証情報を保存してください。",
                }
            login_id = source_creds.get("id")
            password = source_creds.get("password")

        # 部分更新: 片方だけ指定された場合、既存から補完
        if (login_id and not password) or (password and not login_id):
            existing = await creds_service.get_credential(user_id, service)
            if existing:
                if not login_id:
                    login_id = existing.get("id")
                if not password:
                    password = existing.get("password")

        # login_id, password のバリデーション
        if not login_id or not password:
            return {
                "success": False,
                "error": "login_id と password が必要です。新規登録の場合は両方、更新の場合は変更する方を指定してください。",
            }

        await creds_service.save_credential(
            user_id=user_id,
            service=service,
            credentials={"id": login_id, "password": password},
            credential_type="login",
        )

        return {"success": True}

    # ★★★ スキル確認（手順書取得）★★★
    if skill_name == "_check_skill":
        check_skill_name = params.get("skill_name")
        if not check_skill_name:
            return {
                "success": False,
                "error": "skill_name が必要です",
            }

        # スキルを検索
        skill = SkillRegistry.get(check_skill_name)
        if not skill:
            # 利用可能なスキル一覧を取得
            available_skills = [s.name for s in SkillRegistry.list_all()]
            return {
                "success": False,
                "error": f"スキル '{check_skill_name}' は存在しません。利用可能なスキル: {', '.join(available_skills) or 'なし'}",
            }

        # SKILL.md本文を取得
        skill_content = skill.markdown_content or skill.raw_content or ""

        # actions/*.md を全て取得
        action_manuals = []
        available_actions = skill.list_available_actions()
        for action_name in available_actions:
            manual = skill.get_action_manual(action_name)
            if manual:
                action_manuals.append(f"## アクション: {action_name}\n\n{manual}")

        # 結果を構築
        result_parts = []

        # スキル基本情報
        result_parts.append(f"# {skill.display_name}")
        if skill.description:
            result_parts.append(f"\n説明: {skill.description}\n")

        # SKILL.md本文
        if skill_content:
            result_parts.append("---")
            result_parts.append(skill_content)

        # アクションマニュアル
        if action_manuals:
            result_parts.append("\n---\n")
            result_parts.append("# アクション詳細\n")
            result_parts.append("\n\n".join(action_manuals))

        return {
            "success": True,
            "skill_name": skill.name,
            "display_name": skill.display_name,
            "description": skill.description,
            "manual": "\n".join(result_parts),
            "available_actions": available_actions,
        }

    # ★★★ 提案作成ツール ★★★
    if skill_name == "_create_proposal":
        return await _execute_create_proposal(params, user_id, session_id)

    # ★★★ ブラウザ直接操作ツール ★★★
    if skill_name == "_browser":
        real_action = action
        if real_action == "__from_params":
            real_action = params.pop("action", "screenshot")
        return await _execute_browser_tool(real_action, params)

    # ★★★ URL読み込み（Jina Reader）★★★
    if skill_name == "_jina":
        return await _execute_read_url(params)

    # ★★★ 最初にスキルの存在を確認（認証チェックより先）★★★
    # 存在しないスキルに対して「認証が必要」と誤った応答を返さないため
    skill = SkillRegistry.get(skill_name)
    if not skill:
        # 利用可能なスキル一覧を取得
        available_skills = [s.name for s in SkillRegistry.list_all()]
        return {
            "success": False,
            "error": f"スキル '{skill_name}' は存在しません。利用可能なスキル: {', '.join(available_skills) or 'なし'}",
            "error_type": "unknown",
        }

    # スキル名をそのままサービス名として使用（DBにはハイフン付きで保存されている）
    # service_name を優先し、未設定時は skill_name を使用（互換性維持）
    service_name = skill.service_name or skill_name  # ex_reservation / amazon など

    # 認証情報の取得: DBに保存済みの認証情報を取得
    # 認証情報がなければ Executor が credentials_required を返し、LLMが自然にユーザーに聞く
    if credentials is None:
        # まずDBから認証情報を取得
        from app.services.credentials_service import get_credentials_service
        creds_service = get_credentials_service()

        stored_creds = await creds_service.get_credential(user_id, service_name)
        # 互換性: 旧キー（skill_name）にも保存されていた場合はフォールバックして移行
        if not stored_creds and service_name != skill_name:
            legacy_creds = await creds_service.get_credential(user_id, skill_name)
            if legacy_creds:
                stored_creds = legacy_creds
                try:
                    migrate_creds = {
                        k: v
                        for k, v in legacy_creds.items()
                        if k not in {"id", "service", "credential_type"}
                    }
                    await creds_service.save_credential(
                        user_id=user_id,
                        service=service_name,
                        credentials=migrate_creds,
                        credential_type=legacy_creds.get("credential_type", "login"),
                    )
                except Exception:
                    pass  # Credential migration failed silently

        # ドメイン/親スキル名で保存されている認証情報もフォールバックして取得
        if not stored_creds:
            candidates = []
            if skill.parent_skill:
                candidates.append(skill.parent_skill)
            if skill.domain:
                domain = skill.domain.strip().lower()
                candidates.append(domain)
                if domain.startswith("www."):
                    candidates.append(domain[4:])
                base_domain = domain[4:] if domain.startswith("www.") else domain
                if "." in base_domain:
                    candidates.append(base_domain.split(".")[0])

            for candidate in dict.fromkeys(candidates):
                if not candidate or candidate == service_name:
                    continue
                fallback_creds = await creds_service.get_credential(user_id, candidate)
                if fallback_creds:
                    stored_creds = fallback_creds
                    try:
                        migrate_creds = {
                            k: v
                            for k, v in fallback_creds.items()
                            if k not in {"id", "service", "credential_type"}
                        }
                        await creds_service.save_credential(
                            user_id=user_id,
                            service=service_name,
                            credentials=migrate_creds,
                            credential_type=fallback_creds.get("credential_type", "login"),
                        )
                    except Exception:
                        pass  # Credential migration failed silently
                    break

        if stored_creds:
            # 統一スキーマ: credentials_service.py が正規化済みの {"id": ..., "password": ...} を返す
            credentials = {
                "id": stored_creds.get("id"),
                "password": stored_creds.get("password"),
            }
        # DBに認証情報がなければ credentials=None のままExecutorに渡す
        # Executor が credentials_required を返し、LLMが自然にユーザーに聞いて save_credentials で保存

    # ★★★ スキル呼び出し ★★★
    #
    # 設計思想:
    # - Dan が check_skill で手順書を取得し、browser_* ツールで自分で操作
    # - generated スキル: 独自の executor.py を持っているのでそのまま使用
    # - それ以外のスキル: Dan に手順書を返して browser_* で操作を促す

    # 自動生成されたスキルは独自のexecutor.pyを使用（例外）
    if skill.service_type == "generated":
        result = await _execute_generated_skill(skill, action, params, credentials=credentials, user_id=user_id)
        await _record_issue_for_failure(result, skill_name, action, params, user_id, skill)
        return result

    # 手順書ベースのスキル → check_skill + browser_* で操作する設計
    # ここに到達するのはスキルツールが直接呼ばれた場合（レガシー互換）
    skill_manual = _build_skill_manual(skill, action)
    logger.info(f"[EXECUTE_TOOL] Skill {skill_name}/{action} called directly, returning manual for browser_* usage")

    try:
        return {
            "success": True,
            "message": f"スキル '{skill.display_name}' の手順書を取得しました。browser ツールで操作してください。",
            "manual": skill_manual,
            "domain": skill.domain,
            "available_actions": skill.list_available_actions(),
        }
    except Exception as e:
        logger.exception(f"Tool execution error: {e}")
        result_dict = {"success": False, "error": str(e)}
        await _record_issue_for_failure(result_dict, skill_name, action, params, user_id, skill)
        return result_dict
    finally:
        # セッションIDをクリア
        if session_id:
            CancellationRegistry.set_current_session(None)


@dataclass
class FormattedToolResult:
    """
    フォーマットされたツール結果

    Vision API対応: テキストと画像を両方含められる
    """
    text: str
    images: List[Dict[str, Any]] = field(default_factory=list)  # Vision API用画像リスト

    def has_images(self) -> bool:
        """画像が含まれているか"""
        return len(self.images) > 0


def format_tool_result(
    result: Dict[str, Any],
    skill_name: str,
    action: str,
    skill: Optional["Skill"] = None,
) -> FormattedToolResult:
    """
    ツール実行結果をLLMに渡すフォーマットに変換（Progressive Disclosure対応）

    第一原理に基づいた設計:
    1. 差分があれば必ず報告
    2. ブラウザの実際の状態を報告
    3. 失敗時は理由と代替案を提示
    4. 決定ポイントのスクリーンショットをVision形式で含める（ダンが見えるように）

    Progressive Disclosure:
    - ツール実行時にスキル本文（markdown_content）を注入
    - アクションマニュアル（actions/*.md）を自動ロード
    - LLMはツール実行後に詳細情報を参照できる

    Args:
        result: execute_tool()の戻り値
        skill_name: スキル名
        action: アクション名
        skill: Skillオブジェクト（Progressive Disclosure用）

    Returns:
        FormattedToolResult: テキストメッセージと画像のリスト
    """
    images = []

    # ★ ブラウザツール: content blocks形式で画像+テキストを直接返す
    if skill_name == "_browser" and "content" in result:
        text_parts = []
        for block in result["content"]:
            if block.get("type") == "image":
                images.append(block)
            elif block.get("type") == "text":
                text_parts.append(block["text"])
        error = result.get("error")
        if error:
            text_parts.insert(0, f"エラー: {error}")
        # ゾーン判定リマインダー
        text_parts.append("[Zone] 次の操作前にGreen/Yellow/Red判定を行うこと。個人情報入力・購入確定はRed（確認必須）。ただしUSER.mdに保存済みの情報はそのまま使ってよい。")
        return FormattedToolResult(text="\n".join(text_parts), images=images)

    # スクリーンショットがあればVision API形式に変換
    screenshot_base64 = result.get("screenshot_base64")
    if screenshot_base64:
        images.append({
            "type": "image",
            "source": {
                "type": "base64",
                "media_type": "image/png",
                "data": screenshot_base64,
            },
        })
        logger.info(f"[VISION] スクリーンショットをメッセージに追加 ({len(screenshot_base64)} bytes)")

    lines = [f"[TOOL RESULT: {skill_name} {action}]"]

    # ★ Progressive Disclosure レベル2: スキル本文を注入
    if skill and skill.markdown_content:
        lines.append("\n---")
        lines.append("## スキルマニュアル")
        # 文字数制限（トークン効率のため）
        content = skill.markdown_content[:3000]
        lines.append(content)
        lines.append("---\n")

    # ★ Progressive Disclosure レベル3: アクションマニュアルを自動ロード
    if skill:
        action_manual = skill.get_action_manual(action)
        if action_manual:
            lines.append("\n---")
            lines.append(f"## {action} アクション詳細")
            lines.append(action_manual[:2000])
            lines.append("---\n")

    # 成功/失敗
    success = result.get("success", False)

    if not success:
        # エラーメッセージ
        error_msg = result.get("message") or result.get("error", "不明なエラー")
        lines.append(f"エラー: {error_msg}")

        # 失敗理由（第一原理: なぜ失敗したかを明示）
        if result.get("failure_reason"):
            lines.append(f"失敗理由: {result['failure_reason']}")

        # ブラウザ状態（第一原理: 実際の状態を報告）
        browser_state = result.get("browser_state")
        if browser_state:
            lines.append(f"\n【ブラウザ状態】")
            if isinstance(browser_state, dict):
                if browser_state.get("logged_in") is not None:
                    lines.append(f"  ログイン: {'済み' if browser_state['logged_in'] else '未ログイン'}")
                if browser_state.get("page_type"):
                    lines.append(f"  ページ: {browser_state['page_type']}")
                if browser_state.get("error_message"):
                    lines.append(f"  ページ上のエラー: {browser_state['error_message']}")

        # 代替案
        if result.get("suggested_alternatives"):
            lines.append(f"\n【代替案】")
            for alt in result["suggested_alternatives"]:
                lines.append(f"  - {alt}")

        return FormattedToolResult(text="\n".join(lines), images=images)

    # 検索結果の場合
    if action == "search" and "options" in result:
        # messageがあればそれを使う（座席表機能の詳細含む）
        if result.get("message"):
            lines.append(result['message'])
        else:
            # messageがなければoptions からフォーマット（従来の動作）
            options = result["options"]
            if not options:
                lines.append("該当する結果がありませんでした。")
            else:
                lines.append(f"{len(options)}件見つかりました:\n")
                for i, opt in enumerate(options[:5], 1):  # 最大5件
                    lines.append(f"{i}. {opt.get('title', '不明')}")
                    if opt.get("description"):
                        lines.append(f"   {opt['description']}")
                    if opt.get("price"):
                        lines.append(f"   料金: ¥{opt['price']:,}")
                    lines.append("")

        # 差分報告（第一原理: 要件と結果の差分を必ず報告）
        deviation = result.get("deviation")
        if deviation and isinstance(deviation, dict) and deviation.get("has_deviation"):
            lines.append("\n【重要: 要件との差分】")
            if deviation.get("reason"):
                lines.append(f"  {deviation['reason']}")
            if deviation.get("requested"):
                req = deviation["requested"]
                req_desc = []
                if req.get("seat_type"):
                    req_desc.append(req["seat_type"])
                if req.get("adjacent_empty"):
                    req_desc.append("隣空席希望")
                if req_desc:
                    lines.append(f"  要求された条件: {', '.join(req_desc)}")
            if deviation.get("actual"):
                act = deviation["actual"]
                if act.get("seat"):
                    lines.append(f"  実際に選択: {act['seat']}")
                if act.get("seat_type"):
                    lines.append(f"  実際の座席タイプ: {act['seat_type']}")
            if deviation.get("alternatives_checked"):
                lines.append(f"  確認済みの号車: {', '.join(deviation['alternatives_checked'])}")

        # ブラウザ状態
        browser_state = result.get("browser_state")
        if browser_state and isinstance(browser_state, dict):
            lines.append("\n【ブラウザ状態】")
            if browser_state.get("logged_in") is not None:
                lines.append(f"  ログイン: {'済み' if browser_state['logged_in'] else '未ログイン'}")
            if browser_state.get("page_type"):
                lines.append(f"  現在のページ: {browser_state['page_type']}")

        return FormattedToolResult(text="\n".join(lines), images=images)

    # 認証情報取得結果: login_id と password を明示的に含める
    if skill_name == "_get_credentials" and result.get("login_id"):
        lines.append(f"サービス: {result.get('service', '?')}")
        lines.append(f"ログインID: {result['login_id']}")
        pw = result.get('password', '')
        masked_pw = f"{pw[:2]}{'*' * (len(pw) - 2)}" if pw and len(pw) > 2 else '（なし）'
        lines.append(f"パスワード: {masked_pw}")
        return FormattedToolResult(text="\n".join(lines), images=images)

    # check_skill: manual フィールドにスキル本文が入っている
    manual = result.get("manual")
    if manual:
        lines.append(manual)
        return FormattedToolResult(text="\n".join(lines), images=images)

    # bash / read_file / write_file / edit_file: output を直接返す
    output = result.get("output")
    if output:
        lines.append(output)
    elif result.get("content"):
        # read_file の content
        lines.append(result["content"])
    else:
        lines.append(result.get('message', '完了'))

    # instructionがあれば追加（ツールからLLMへの指示）
    instruction = result.get("instruction")
    if instruction:
        lines.append(f"\n[指示] {instruction}")

    # 差分があれば追加
    deviation = result.get("deviation")
    if deviation and isinstance(deviation, dict) and deviation.get("has_deviation"):
        lines.append(f"\n【差分】{deviation.get('reason', '詳細不明')}")

    return FormattedToolResult(text="\n".join(lines), images=images)


# ============================================
# 自動生成スキルの実行
# ============================================

async def _execute_generated_skill(
    skill: Skill,
    action: str,
    params: Dict[str, Any],
    credentials: Optional[Dict[str, str]] = None,
    user_id: Optional[str] = None,
) -> Dict[str, Any]:
    """
    自動生成されたスキルを実行

    スキルディレクトリ内の executor.py を動的にインポートして実行する。
    BaseExecutorクラスまたはスタンドアロンのexecute()関数をサポート。

    Args:
        skill: Skillオブジェクト
        action: アクション名
        params: パラメータ

    Returns:
        実行結果
    """
    import importlib.util
    import inspect

    if not skill.skill_dir:
        return {
            "success": False,
            "error": f"スキル '{skill.name}' のディレクトリが見つかりません",
        }

    executor_path = skill.skill_dir / "executor.py"
    if not executor_path.exists():
        return {
            "success": False,
            "error": f"スキル '{skill.name}' の executor.py が見つかりません。check_skill で手順書を確認し、browser_* ツールで操作してください。",
        }

    try:
        # executor.py を動的にインポート
        # 相対インポートをサポートするため、パッケージとして設定
        import sys
        skill_dir = skill.skill_dir

        # スキルディレクトリを一時的にsys.pathに追加
        skill_dir_str = str(skill_dir)
        if skill_dir_str not in sys.path:
            sys.path.insert(0, skill_dir_str)

        # __init__.pyが無ければ作成（パッケージとして認識させるため）
        init_file = skill_dir / "__init__.py"
        if not init_file.exists():
            init_file.write_text("", encoding="utf-8")

        # パッケージ名を設定（相対インポート用）
        package_name = skill.name.replace("-", "_")
        if package_name not in sys.modules:
            import importlib.machinery
            package_spec = importlib.machinery.ModuleSpec(package_name, None)
            package_module = importlib.util.module_from_spec(package_spec)
            package_module.__path__ = [skill_dir_str]
            sys.modules[package_name] = package_module

        module_name = f"generated_skills.{package_name}"

        spec = importlib.util.spec_from_file_location(
            module_name,
            executor_path,
            submodule_search_locations=[skill_dir_str]
        )
        executor_module = importlib.util.module_from_spec(spec)

        # パッケージ情報を設定
        executor_module.__package__ = package_name
        sys.modules[module_name] = executor_module

        # selectorsモジュールも先にロード（相対インポート解決のため）
        selectors_path = skill_dir / "selectors.py"
        if selectors_path.exists():
            selectors_module_name = f"{package_name}.selectors"
            selectors_spec = importlib.util.spec_from_file_location(
                selectors_module_name,
                selectors_path
            )
            selectors_module = importlib.util.module_from_spec(selectors_spec)
            sys.modules[selectors_module_name] = selectors_module
            selectors_spec.loader.exec_module(selectors_module)

        spec.loader.exec_module(executor_module)

        logger.info(f"[GENERATED_SKILL] Executing {skill.name}.{action}")

        # 方法1: スタンドアロンの execute() 関数
        if hasattr(executor_module, "execute"):
            exec_fn = executor_module.execute
            sig = inspect.signature(exec_fn)
            call_kwargs = {"params": params, "credentials": credentials, "user_id": user_id}
            filtered = {k: v for k, v in call_kwargs.items() if k in sig.parameters}
            result = exec_fn(**filtered)
            if inspect.isawaitable(result):
                result = await result
            return result

        # 方法2: BaseExecutor を継承したクラス
        # クラス名は {SkillName}Executor の形式を探す（例: YahooWeatherExecutor）
        executor_class = None
        for name, obj in inspect.getmembers(executor_module, inspect.isclass):
            # BaseExecutorを継承しているクラスを探す（BaseExecutor自体は除く）
            if name.endswith("Executor") and name != "BaseExecutor":
                # BaseExecutorをインポートして継承チェック
                try:
                    from app.executors.base import BaseExecutor
                    if issubclass(obj, BaseExecutor) and obj is not BaseExecutor:
                        executor_class = obj
                        break
                except ImportError:
                    # BaseExecutorがインポートできない場合は名前で判定
                    executor_class = obj
                    break

        if executor_class:
            logger.info(f"[GENERATED_SKILL] Found executor class: {executor_class.__name__}")
            executor_instance = executor_class()

            # 生成されたスキルの多くは情報取得（search）が主目的
            # "execute" アクションが呼ばれた場合も search にマッピング
            # （BaseExecutor.execute は予約確定用で別のシグネチャ）
            effective_action = action
            if action in ("execute", "search_weather", "get", "fetch"):
                effective_action = "search"
                logger.info(f"[GENERATED_SKILL] Mapping action '{action}' to 'search'")

            # アクションに応じてメソッドを呼び出し
            if effective_action == "search" and hasattr(executor_instance, "search"):
                result = await executor_instance.search(params=params, credentials=credentials, user_id=user_id)
                return result.to_dict() if hasattr(result, "to_dict") else result
            elif hasattr(executor_instance, effective_action):
                method = getattr(executor_instance, effective_action)
                result = await method(params=params, credentials=credentials, user_id=user_id)
                return result.to_dict() if hasattr(result, "to_dict") else result
            elif hasattr(executor_instance, "search"):
                # デフォルトで search を呼び出し
                logger.info(f"[GENERATED_SKILL] Falling back to search for action '{action}'")
                result = await executor_instance.search(params=params, credentials=credentials, user_id=user_id)
                return result.to_dict() if hasattr(result, "to_dict") else result
            else:
                return {
                    "success": False,
                    "error": f"スキル '{skill.name}' の executor に '{action}' メソッドがありません",
                }

        return {
            "success": False,
            "error": f"スキル '{skill.name}' の executor.py に execute 関数または Executor クラスがありません",
        }

    except Exception as e:
        import traceback
        error_details = traceback.format_exc()
        logger.error(f"[GENERATED_SKILL] Execution failed: {e}\n{error_details}")
        # デバッグログにも出力
        debug_log = Path("D:/done/skill_analyze_debug.log")
        with open(debug_log, "a", encoding="utf-8") as f:
            f.write(f"\n=== GENERATED_SKILL ERROR ===\n")
            f.write(f"Skill: {skill.name}, Action: {action}\n")
            f.write(f"Error: {e}\n")
            f.write(f"Traceback:\n{error_details}\n")
        return {
            "success": False,
            "error": f"スキル実行エラー: {str(e)}",
        }


# ============================================
# スキル手順書構築
# ============================================

def _build_skill_manual(skill: Optional["Skill"], action: str) -> str:
    """
    スキルの手順書を構築

    SKILL.md と actions/*.md を結合して手順書を作成する。

    Args:
        skill: Skillオブジェクト
        action: アクション名

    Returns:
        手順書テキスト（なければ空文字列）
    """
    if not skill:
        return ""

    parts = []

    # SKILL.md の内容
    if skill.markdown_content:
        parts.append("# スキル概要")
        parts.append(skill.markdown_content)

    # actions/xxx.md の内容
    action_manual = skill.get_action_manual(action)
    if action_manual:
        parts.append(f"\n# {action} アクション手順")
        parts.append(action_manual)

    return "\n\n".join(parts)


# ============================================
# ブラウザ直接操作（Dan → browser.py）
# ============================================

# ブラウザ操作のタイムアウト設定（ミリ秒）
BROWSER_CLICK_TIMEOUT = 10000       # クリック要素検出
BROWSER_LOAD_TIMEOUT = 10000        # ページ遷移後のロード完了待ち
BROWSER_STATE_TIMEOUT = 3000        # スクショ前のロード完了待ち
BROWSER_SCREENSHOT_TIMEOUT = 5000   # スクリーンショット取得・要素リスト取得

async def _get_browser_state(page) -> Dict[str, Any]:
    """
    操作後のページ状態を取得（スクリーンショット + 要素リスト）

    全ブラウザツールがこの関数を呼んで結果を返す。
    Danは常にページを「見ている」状態になる。
    """
    # ページのロード完了を待つ（ナビゲーション中のエラー防止）
    try:
        await page.wait_for_load_state("domcontentloaded", timeout=BROWSER_STATE_TIMEOUT)
    except Exception:
        # タイムアウトしてもスクショは試みる
        await page.wait_for_timeout(500)

    # スクリーンショット取得（タイムアウト付き）
    try:
        screenshot = await asyncio.wait_for(
            page.screenshot_base64(full_page=False),
            timeout=BROWSER_SCREENSHOT_TIMEOUT / 1000,
        )
    except (asyncio.TimeoutError, Exception) as e:
        logger.warning(f"[BROWSER] Screenshot timed out or failed: {e}")
        screenshot = None

    # 要素リスト取得（タイムアウト付き）
    try:
        elements = await asyncio.wait_for(
            page.get_interactive_elements(),
            timeout=BROWSER_SCREENSHOT_TIMEOUT / 1000,
        )
    except (asyncio.TimeoutError, Exception) as e:
        logger.warning(f"[BROWSER] get_interactive_elements timed out or failed: {e}")
        elements = []

    # ページコンテキスト取得（タイムアウト付き）
    page_context = {}
    try:
        page_context = await asyncio.wait_for(
            page.get_page_context(),
            timeout=BROWSER_SCREENSHOT_TIMEOUT / 1000,
        )
    except (asyncio.TimeoutError, Exception) as e:
        logger.warning(f"[BROWSER] get_page_context timed out or failed: {e}")

    url = page.url
    title = await page.evaluate("document.title")

    # テキスト部分: URL + タイトル + ページ状態 + 要素一覧
    text_parts = [f"URL: {url}", f"タイトル: {title}"]

    # ページ状態セクション
    if page_context:
        text_parts.append("")
        text_parts.append("ページ状態:")

        # 見出し
        headings = page_context.get("headings", [])
        if headings:
            for h in headings:
                text_parts.append(f"  見出し: [{h.get('level', '')}] {h.get('text', '')}")
        else:
            text_parts.append("  見出し: なし")

        # フィードバック
        feedback = page_context.get("feedback", [])
        if feedback:
            for fb in feedback:
                text_parts.append(f"  フィードバック: 「{fb}」")
        else:
            text_parts.append("  フィードバック: なし")

        # モーダル
        modal = page_context.get("modal")
        if modal:
            text_parts.append(f"  モーダル: 「{modal}」")
        else:
            text_parts.append("  モーダル: なし")

        # ローディング
        is_loading = page_context.get("isLoading", False)
        text_parts.append(f"  ローディング: {'あり' if is_loading else 'なし'}")

        # バッジ
        badges = page_context.get("badges", [])
        if badges:
            badge_strs = [f"{b.get('context', '')}({b.get('value', '')})" for b in badges]
            text_parts.append(f"  バッジ: {', '.join(badge_strs)}")

        # 入力済みフォーム値
        filled = page_context.get("filledInputs", [])
        if filled:
            filled_strs = [f"{f.get('label', '?')}={f.get('value', '')}" for f in filled]
            text_parts.append(f"  入力済み: {', '.join(filled_strs)}")

    # 要素一覧
    text_parts.append("")
    text_parts.append("要素一覧:")
    for el in elements:
        ref = el.get("ref", "")
        tag = el.get("tag", "")
        text = el.get("text", "")
        el_type = el.get("type", "")
        role = el.get("role", "")
        states = el.get("states", [])
        label = []
        if tag:
            label.append(tag)
        if el_type:
            label.append(f'type={el_type}')
        if role and role != tag:
            label.append(f'role={role}')
        tag_info = ", ".join(label) if label else "element"
        states_str = f" ({', '.join(states)})" if states else ""
        text_parts.append(f"  {ref}: [{tag_info}]{states_str} {text}")

    # 検証リマインダー（モデルが毎回必ず読む位置に配置）
    text_parts.append("")
    text_parts.append("---")
    text_parts.append("確認義務: 上記のURL・タイトル・ページ状態・要素を見て、操作が成功したか判断せよ。")
    text_parts.append("証拠なく「完了しました」と報告してはならない。期待と異なるなら次の操作で修正せよ。")

    content = []
    if screenshot:
        content.append({
            "type": "image",
            "source": {
                "type": "base64",
                "media_type": screenshot["media_type"],
                "data": screenshot["base64"],
            },
        })
    content.append({
        "type": "text",
        "text": "\n".join(text_parts),
    })

    return {
        "success": True,
        "content": content,
    }


async def _execute_browser_tool(action: str, params: Dict[str, Any]) -> Dict[str, Any]:
    """
    ブラウザツールを実行

    Args:
        action: open, screenshot, click, type, scroll, select
        params: ツールパラメータ

    Returns:
        content blocks（画像+テキスト）を含む結果
    """
    from app.tools.browser import get_executor_page

    try:
        page = await get_executor_page()

        if action == "open":
            url = params.get("url")
            if not url:
                return {"success": False, "error": "url が必要です"}
            await page.goto(url)
            await page.wait_for_load_state("domcontentloaded", timeout=BROWSER_LOAD_TIMEOUT)
            return await _get_browser_state(page)

        elif action == "screenshot":
            return await _get_browser_state(page)

        elif action == "click":
            ref = params.get("ref")
            x = params.get("x")
            y = params.get("y")

            # クリック前のタブ数を記録
            try:
                tab_before = await page.get_tab_count()
                tab_count_before = tab_before.get("count", 1)
            except Exception:
                tab_count_before = 1

            if ref:
                # force=True: Amazonカルーセル等のオーバーレイによるクリック妨害を回避
                # data-dan-refで特定済みの要素なのでforceで安全
                await page.click_by_ref(ref, force=True, timeout=BROWSER_CLICK_TIMEOUT)
            elif x is not None and y is not None:
                await page.mouse.click(x, y)
            else:
                return {"success": False, "error": "ref または x,y座標が必要です"}

            # クリック後、新タブが開いたか確認
            await page.wait_for_timeout(500)
            try:
                tab_after = await page.get_tab_count()
                tab_count_after = tab_after.get("count", 1)
            except Exception:
                tab_count_after = tab_count_before

            if tab_count_after > tab_count_before:
                # 新タブが開いた → 自動で切り替え
                try:
                    switch_result = await page.switch_to_latest_tab()
                    if switch_result.get("switched"):
                        logger.info(f"[BROWSER] Auto-switched to new tab: {switch_result.get('url')}")
                except Exception as e:
                    logger.warning(f"[BROWSER] Failed to switch tab: {e}")
            else:
                # 同じタブでのページ遷移を待つ
                try:
                    await page.wait_for_load_state("domcontentloaded", timeout=BROWSER_LOAD_TIMEOUT)
                except Exception:
                    pass
            return await _get_browser_state(page)

        elif action == "type":
            ref = params.get("ref")
            text = params.get("text")
            press_enter = params.get("press_enter", False)
            if not ref or not text:
                return {"success": False, "error": "ref と text が必要です"}
            await page.fill_by_ref(ref, text)
            if press_enter:
                await page.keyboard.press("Enter")
                # Enter後のナビゲーション完了を待つ（"load"でリソース読み込みまで待機）
                try:
                    await page.wait_for_load_state("load", timeout=BROWSER_LOAD_TIMEOUT)
                except Exception:
                    # タイムアウト時はフォールバック
                    await page.wait_for_timeout(2000)
            return await _get_browser_state(page)

        elif action == "scroll":
            direction = params.get("direction", "down")
            delta = 500 if direction == "down" else -500
            await page.evaluate(f"window.scrollBy(0, {delta})")
            await page.wait_for_timeout(300)
            return await _get_browser_state(page)

        elif action == "back":
            await page.go_back()
            await page.wait_for_load_state("domcontentloaded", timeout=BROWSER_LOAD_TIMEOUT)
            return await _get_browser_state(page)

        elif action == "select":
            ref = params.get("ref")
            value = params.get("value")
            if not ref or not value:
                return {"success": False, "error": "ref と value が必要です"}
            # refからセレクタを構築して select_option を呼ぶ
            selector = f'[data-dan-ref="{ref}"]'
            await page.locator(selector).select_option(value)
            return await _get_browser_state(page)

        elif action == "evaluate":
            expression = params.get("expression")
            if not expression:
                return {"success": False, "error": "expression が必要です"}
            result = await page.evaluate(expression)
            state = await _get_browser_state(page)
            state["content"].insert(0, {"type": "text", "text": f"evaluate result: {result}"})
            return state

        elif action == "save_image":
            url = params.get("url")
            path = params.get("path")
            if not url or not path:
                return {"success": False, "error": "url と path が必要です"}
            result = await page.save_image(url, path)
            return {
                "success": True,
                "content": [{"type": "text", "text": f"画像を保存しました: {result}"}],
            }

        elif action == "content":
            html = await page.content()
            if len(html) > 50000:
                html = html[:50000] + "\n... (truncated)"
            return [{"type": "text", "text": html}]

        elif action == "keyboard_press":
            key = params.get("key")
            if not key:
                return {"success": False, "error": "key が必要です"}
            await page.keyboard.press(key)
            await page.wait_for_timeout(300)
            return await _get_browser_state(page)

        elif action == "hover":
            ref = params.get("ref")
            if ref:
                selector = f'[data-dan-ref="{ref}"]'
                await page.locator(selector).hover()
            elif params.get("x") is not None and params.get("y") is not None:
                await page.mouse.move(float(params["x"]), float(params["y"]))
            else:
                return {"success": False, "error": "ref または x,y が必要です"}
            await page.wait_for_timeout(300)
            return await _get_browser_state(page)

        elif action == "reload":
            await page.reload()
            await page.wait_for_load_state("domcontentloaded", timeout=BROWSER_LOAD_TIMEOUT)
            return await _get_browser_state(page)

        else:
            return {"success": False, "error": f"不明なブラウザアクション: {action}"}

    except Exception as e:
        logger.error(f"[BROWSER] Error in {action}: {e}", exc_info=True)
        # エラー時もスクリーンショットを取得できれば返す
        try:
            page = await get_executor_page()
            state = await _get_browser_state(page)
            # エラー情報をテキストに追加
            for item in state.get("content", []):
                if item.get("type") == "text":
                    item["text"] = f"エラー: {str(e)}\n\n{item['text']}"
            state["success"] = False
            state["error"] = str(e)
            return state
        except Exception:
            return {"success": False, "error": f"ブラウザ操作エラー: {str(e)}"}


# ============================================
# URL読み込み（Jina Reader）
# ============================================

async def _execute_read_url(params: Dict[str, Any]) -> Dict[str, Any]:
    """
    Jina ReaderでURLの内容を取得

    Args:
        params: {url}

    Returns:
        ページ内容（Markdown）
    """
    from app.tools.jina_reader import read_url

    url = params.get("url", "")
    if not url:
        return {"success": False, "error": "URLが指定されていません"}

    logger.info(f"[JINA] Reading: {url}")

    result = await read_url(url)

    if not result.get("success"):
        return {
            "success": False,
            "error": result.get("error", "ページの読み込みに失敗しました"),
            "url": url,
        }

    content = result.get("content", "")
    # 長い場合は先頭8000文字に切り詰め
    if len(content) > 8000:
        content = content[:8000] + "\n\n... (以降省略)"

    return {
        "success": True,
        "url": url,
        "content": content,
        "message": f"ページを読み込みました（{len(content)}文字）",
    }


# ============================================
# ディープリサーチ
# ============================================

def _get_project_service():
    """ProjectServiceのファクトリ（テスト時にmonkeypatch可能）

    MCPサーバーから呼ばれる場合、SupabaseClientのEncryptionService初期化で
    ENCRYPTION_KEYが未設定だとエラーになる。ProjectServiceは暗号化を使わないので
    直接supabase clientを作成して回避する。
    """
    try:
        from app.services.project_service import ProjectService
        return ProjectService()
    except (ValueError, Exception):
        # EncryptionService初期化失敗時: 直接クライアントを作成
        from app.services.project_service import ProjectService
        from app.config import settings
        from supabase import create_client
        service = object.__new__(ProjectService)
        key = settings.SUPABASE_SERVICE_ROLE_KEY or settings.SUPABASE_KEY
        service.supabase = create_client(settings.SUPABASE_URL, key)
        return service


async def _execute_create_proposal(
    params: Dict[str, Any],
    user_id: str,
    session_id: Optional[str] = None,
) -> Dict[str, Any]:
    """
    構造化された提案テキストを生成する。

    DB保存や承認フローは行わない。チャットのテキストとして返すだけ。
    ユーザーが「OK」「やって」等で承認すれば、観察者が計画を記録する。
    """
    title = params.get("title", "")
    steps_raw = params.get("steps", [])

    if not title:
        return {"success": False, "error": "タイトルが必要です"}
    if not steps_raw:
        return {"success": False, "error": "ステップが必要です"}

    # 提案内容をマークダウンで構築
    content_lines = [f"## 提案: {title}", ""]
    for i, desc in enumerate(steps_raw, 1):
        content_lines.append(f"{i}. {desc}")
    content = "\n".join(content_lines)

    return {
        "success": True,
        "message": f"以下の計画を提案します。承認いただければ着手します。\n\n{content}",
    }
