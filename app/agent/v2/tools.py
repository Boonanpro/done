"""
Tools - スキルとExecutorの橋渡し（Native Tool Use方式）

Anthropic Tool Use APIを使用して構造化された出力を実現。
LLMのテキスト出力がそのままユーザーへの返答になる。
"""

import re
import asyncio
import logging
import os
from pathlib import Path
from urllib.parse import urlparse
from typing import Dict, Any, List, Optional, Tuple
from dataclasses import dataclass, field

logger = logging.getLogger(__name__)
PROJECT_ROOT = Path(__file__).resolve().parent.parent.parent.parent
from app.workspace import resolve_cli_workspace
CLI_WORKSPACE = resolve_cli_workspace()

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
        SCHEDULE_FOLLOWUP_TOOL,
        WATCH_TOOL,
        SPLIT_TO_NEW_ROOM_TOOL,
        SAVE_CREDENTIALS_TOOL,
        GET_CREDENTIALS_TOOL,
        SAVE_TOTP_SECRET_TOOL,
        REMEMBER_PERSONAL_INFO_TOOL,
        GET_PERSONAL_INFO_TOOL,
        CHECK_SKILL_TOOL,
        READ_FILE_TOOL,
        WRITE_FILE_TOOL,
        EDIT_FILE_TOOL,
        BASH_TOOL,
        ATTACH_IMAGE_TOOL,
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
    "description": "ブラウザを操作する。操作後にスクリーンショットと要素一覧を返す。evaluate: JSを実行して結果を返す。content: ページのHTML全体を取得する。keyboard_press: キーを押す（Escape, Tab等）。hover: 要素にマウスを乗せる。reload: ページを再読み込み。solve_captcha: ページ上のreCAPTCHA/hCaptcha/Cloudflare Turnstileを2captcha経由で自動的に突破する（フォーム送信前に呼ぶ。ユーザーには絶対に丸投げしない）。fill_credential: 保存済みのログイン情報（パスワード/ID）を、値を一切表示せずに入力欄へ直接流し込む。get_credentialsではパスワードが伏せ字で返り自分で入力できないので、ログイン時はtypeではなくこれを使う（ref と、service または url を指定。field=password/username）。fill_totp_code: 認証アプリ(TOTP)の6桁コードをサーバー側で生成して入力欄(ref)に直接入れる。シード保管済みのサービスなら**SMSもメールも待たずに即座に**2段階認証を突破できる最優先の手段（ref と、service または url を指定）。wait_for_otp_from_app: SMS/メールで届く数字コードを自動取得して入力欄(ref)に入れる。wait_for_link_from_app: 数字コードではなく「タップして再設定/認証」形式のワンタイムURLが届くサービス（Instagramのパスワード再設定等）向け。届いたリンクを自動取得してこのブラウザで開く（refは不要）。リンクを本人に読ませない。",
    "input_schema": {
        "type": "object",
        "properties": {
            "action": {
                "type": "string",
                "enum": ["open", "open_target", "screenshot", "click", "type", "fill_credential", "fill_totp_code", "wait_for_otp_from_app", "wait_for_link_from_app", "scroll", "back", "select", "evaluate", "content", "keyboard_press", "hover", "reload", "save_image", "upload_file", "solve_captcha", "human_click", "human_drag", "puzzle_fit"],
                "description": "実行するアクション",
            },
            "url": {"type": "string", "description": "開くURL（action=open）。action=fill_credentialではログイン先URLで保存済み認証情報を照合するのに使える"},
            "ref": {"type": "string", "description": "操作対象の要素ref（例: @e1）"},
            "text": {"type": "string", "description": "入力テキスト（action=type）"},
            "field": {"type": "string", "enum": ["password", "username"], "description": "action=fill_credentialで入れる項目。password=保存済みパスワード, username=保存済みログインID（既定: password）"},
            "press_enter": {"type": "boolean", "description": "入力後にEnterを押すか（action=type / fill_credential, デフォルト: false）"},
            "timeout_seconds": {"type": "integer", "description": "待機のタイムアウト秒数（action=wait_for_otp_from_app は既定30 / wait_for_link_from_app は既定60）"},
            "service": {"type": "string", "description": "OTPのサービス絞り込み（例: amazon, ex_reservation）"},
            "source": {"type": "string", "enum": ["sms", "email"], "description": "OTP/リンクの受信元（action=wait_for_otp_from_app, wait_for_link_from_app）。SMS(Androidアプリ転送)=sms（既定）、メール=email。emailの場合は email_address を指定"},
            "email_address": {"type": "string", "description": "メールOTP/リンクの受信箱アドレス（source=email時）。例: shub6923@gmail.com。そのアドレスのアプリパスワードが未登録なら発行案内が返る"},
            "direction": {"type": "string", "enum": ["down", "up"], "description": "スクロール方向（action=scroll）"},
            "x": {"type": "integer", "description": "X座標（action=click / human_click / human_drag の始点）"},
            "y": {"type": "integer", "description": "Y座標（action=click / human_click / human_drag の始点）"},
            "to_x": {"type": "integer", "description": "ドラッグ先のX座標（action=human_drag）"},
            "to_y": {"type": "integer", "description": "ドラッグ先のY座標（action=human_drag）"},
            "coords": {"type": "string", "enum": ["image", "css"], "description": "human_click/human_drag の座標系。既定 image=スクリーンショット上で読んだ座標をそのまま渡してよい（縮小率は自動換算される）。css=ブラウザの実座標を直接指定する場合のみ"},
            "threshold": {"type": "number", "description": "答えてよい形状一致度の下限（action=puzzle_fit, 既定0.85）。これ未満なら答えずに『更新』で別の問題を引く"},
            "max_refresh": {"type": "integer", "description": "パズルを引き直す上限回数（action=puzzle_fit, 既定3）"},
            "value": {"type": "string", "description": "選択する値（action=select）"},
            "expression": {"type": "string", "description": "実行するJavaScriptコード（action=evaluate）"},
            "key": {"type": "string", "description": "押すキー（action=keyboard_press, 例: Escape, Tab, Enter, ArrowDown）"},
            "path": {"type": "string", "description": "保存先ファイルパス（action=save_image）／アップロードするローカルファイルの絶対パス（action=upload_file）"},
            "selector": {"type": "string", "description": "CSSセレクタ（action=upload_file でアップロードボタンをrefで指せない場合）"},
            "image_ref": {"type": "string", "description": "画像CAPTCHAの画像要素ref（action=solve_captcha, 任意。未指定なら自動検出）"},
            "input_ref": {"type": "string", "description": "画像CAPTCHAの入力欄ref（action=solve_captcha, 任意。未指定なら自動検出）"},
            "image_selector": {"type": "string", "description": "画像CAPTCHAの画像CSSセレクタ（action=solve_captcha, 任意）"},
            "input_selector": {"type": "string", "description": "画像CAPTCHAの入力欄CSSセレクタ（action=solve_captcha, 任意）"},
        },
        "required": ["action"]
    }
}

# ============================================
# URL読み込みツール（Jina Reader）
# ============================================

ATTACH_IMAGE_TOOL = {
    "name": "attach_image",
    "description": """画像をチャットに添付するための正規マーカーを取得する。

**画像をユーザーに見せたい時は、必ずこのツールを使うこと。** 自分で `[添付画像: ...]` を書いてはいけない（フォーマットを間違えると404になる）。

使い方:
1. このツールを呼ぶ → `marker` フィールド（例: `[添付画像: /api/v1/files/xxx.png]`）が返る
2. 次のアシスタント返答の本文に、その marker 文字列をそのまま貼り付ける

source の指定方法:
- すでに /api/v1/files/ にあるファイル名: "e63623f3-3408-...png"
- フルパス（uploads/ 外なら自動コピー）: "D:/done/foo.png", "C:\\\\Users\\\\Owner\\\\image.png"
- 既存 URL: "/api/v1/files/foo.png", "http://localhost:8000/api/v1/files/foo.png"
""",
    "input_schema": {
        "type": "object",
        "properties": {
            "source": {
                "type": "string",
                "description": "画像のファイル名・絶対パス・URL のいずれか"
            }
        },
        "required": ["source"]
    }
}

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

SCHEDULE_FOLLOWUP_TOOL = {
    "name": "schedule_followup",
    "description": """後で自分（ダン）を自動で起こして、外部サービスの状態を再確認し、続報を投稿する予約をする。

【使う場面】Vercelデプロイ、DNS反映、外部ビルドなど、Claude Code自身の背景作業ではなく、
外部サービスの完了を後で確認する必要がある時だけ使う。noteには確認対象（URL・ジョブID・確認内容）を具体的に書く。
単に「報告します」「お待ちください」と発言しただけでは使わない。ユーザーの返答待ちには絶対に使わない。
Claude Code自身が起動した背景作業は常駐セッションの完了イベントで続報されるため、この予約は不要。

【動作】delay_seconds 後にバックグラウンドのポーラーがあなたを新しいターンで起動し note を渡す。
その時あなたは結果を実際に確認してユーザーに日本語で報告する。まだ終わっていなければ、その新ターン
内でもう一度 schedule_followup を短い遅延で呼んで再予約してよい。

【例】Vercelデプロイ開始 → schedule_followup(note="new-attack-done.vercel.app のデプロイ完了を確認して結果を報告する", delay_seconds=120)""",
    "input_schema": {
        "type": "object",
        "properties": {
            "note": {"type": "string", "description": "起こされた時に何を確認して報告すべきか（具体的に書く）"},
            "delay_seconds": {"type": "integer", "description": "何秒後に起こすか（15以上）。デプロイ/ビルドなら90〜180が目安"},
        },
        "required": ["note", "delay_seconds"],
    },
}

SPLIT_TO_NEW_ROOM_TOOL = {
    "name": "split_to_new_room",
    "description": """脱線した話題を新しいチャット（部屋）に切り出し、そこで自分（ダン）が続きを話し始める。

【使う場面】ユーザーが「この話は新しいチャットで話そう」「別の部屋でやろう」「これは分けよう」等、
今の話題を別チャットに移したいと言った時。ユーザーに部屋を作らせない。自分でこのツールを呼ぶ。

【動作】新しいチャットを作成し、handoff の内容を持って数十秒以内にその部屋であなたが一言目を話し始める。

【handoff の書き方】新しい部屋の自分は元の部屋の会話を読めない。だから handoff に、
その話題の経緯・決まったこと・ユーザーの要望・次にやること・関係するURLやファイルパスを、
続きが迷わず再開できる粒度で書く（生ログのコピーではなく要約）。""",
    "input_schema": {
        "type": "object",
        "properties": {
            "title": {"type": "string", "description": "新しいチャットの名前（話題が一目で分かる短い日本語。例:「経費精算アプリの相談」）"},
            "handoff": {"type": "string", "description": "新しい部屋へ持ち込む引き継ぎメモ（経緯・決定事項・要望・次にやること・URL/パス）"},
        },
        "required": ["title", "handoff"],
    },
}

WATCH_TOOL = {
    "name": "watch",
    "description": """見張り（未来の約束）の登録・一覧・取消。あなた（ダン）はターンが終わると眠るため、頭の中の「後で確認します」「メールが来たら報告します」は実行されない。未来の約束は必ずこのツールでDBに登録すること。登録した見張りはダンコアが監視し、時刻・条件が来たらこの部屋であなたを起こす。

【3種類】
- at: 一回きりの時刻予約（「明日10時に確認」）。at か delay_seconds を指定。
- every: 定期実行。①秒間隔（interval_seconds、300以上）②毎月N日（monthly_day + time_of_day。31は月末に丸まる）③毎週X曜（weekly_day 0=月〜6=日 + time_of_day）。毎月の資料作成・送付、毎月の振込準備などの定期業務はこれで登録する。
- mail: 特定の差出人からのメール着信で起こす（「税理士からメールが来たら」）。mail_from に差出人アドレスまたはドメイン（例 "taxdr-kim.com"）。現在 iCloud 受信箱のみ対応。登録時点より前の既読メールでは起きない。

【使い方】
- 登録: watch(action="create", note="起こされた時に何を確認・報告するか", ...)。kind は指定パラメータから自動判定される（mail_from があれば mail、interval_seconds のみなら every、それ以外は at）。
- 一覧: watch(action="list") — この部屋の有効な見張りを返す。「今何を見張ってる？」に答える時に使う。
- 取消: watch(action="cancel", watch_id="...")。
- ブラウザ画面（OTP入力・ログイン途中など）を開いたまま待つ必要がある時だけ hold_browser=true。これを付けないと30分放置でブラウザは自動クローズされる。

【承認の扱い】不可逆な操作（送金の実行・外部への送信など）を含む定期業務は、原則「準備まで自動＋実行は承認」。ただしユーザーが「承認なしで実行して報告だけでいい」と明示した場合は、その旨を note に必ず書き込むこと（例:「承認不要・実行して結果を報告のみ」）。起こされたダンは note の記載に従う。

【規律】ユーザーの即時の返答待ちには使わない。定期見張りの起床ターン内で同じ見張りを再登録しない（自動継続する）。""",
    "input_schema": {
        "type": "object",
        "properties": {
            "action": {"type": "string", "enum": ["create", "list", "cancel"], "description": "create=登録 / list=一覧 / cancel=取消"},
            "note": {"type": "string", "description": "create時必須。起こされた時に何を確認して何を報告するか（具体的に）"},
            "at": {"type": "string", "description": "at用: 起こす日時 ISO形式（例 2026-08-25T10:00）。タイムゾーン無しはJSTと解釈"},
            "delay_seconds": {"type": "integer", "description": "at用: 何秒後に起こすか（atの代わり）"},
            "interval_seconds": {"type": "integer", "description": "every/mail用: 確認間隔秒（最小300。mailの既定600）"},
            "monthly_day": {"type": "integer", "description": "every用: 毎月の実行日（1〜31。31は月末に丸まる）"},
            "weekly_day": {"type": "integer", "description": "every用: 毎週の実行曜日（0=月〜6=日）"},
            "time_of_day": {"type": "string", "description": "monthly_day/weekly_day用: 実行時刻 HH:MM（JST、既定09:00）"},
            "mail_from": {"type": "string", "description": "mail用: 差出人アドレスまたはドメイン"},
            "mail_subject_contains": {"type": "string", "description": "mail用: 件名に含まれるべき文字列（任意）"},
            "hold_browser": {"type": "boolean", "description": "この部屋のブラウザを見張り解決まで自動クローズさせない（画面を開いたまま待つ時のみtrue）"},
            "watch_id": {"type": "string", "description": "cancel用: 対象の見張りID"},
        },
        "required": ["action"],
    },
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


# 照合語として意味を持たない一般語（これだけで一致させると無関係な記録を拾う）
_SERVICE_TOKEN_STOPWORDS = {
    "jp", "com", "co", "net", "org", "www", "login", "app", "web",
    "my", "account", "official", "biz", "site",
}


def _service_tokens(value: str) -> set:
    """サービス名から照合用の語を取り出す。"amazon_biz" → {"amazon_biz", "amazon"}"""
    s = _normalize_service_name(value)
    tokens = {
        t for t in re.split(r"[^a-z0-9]+", s)
        if len(t) >= 3 and t not in _SERVICE_TOKEN_STOPWORDS
    }
    if len(s) >= 3:
        tokens.add(s)
    return tokens


async def _suggest_credential_services(
    creds_service,
    user_id: str,
    service: Optional[str],
    url: Optional[str],
) -> List[str]:
    """
    完全一致で見つからなかった時に、保存済みのサービス名から近い候補を返す。

    取得は完全一致しか見ないため、名前を少し外すと「保存されていない」と読めてしまい、
    実際には保存済みの認証情報を「無い」と誤って断定する事故が起きた。
    ここでは名前だけを返す（パスワードは返さない）。
    """
    try:
        stored = await creds_service.list_credentials(user_id)
    except Exception as e:
        logger.warning(f"Failed to list credentials for suggestion: {e}")
        return []

    names = [row.get("service") for row in stored if row.get("service")]
    if not names:
        return []

    queries = set()
    if service:
        queries |= _service_tokens(service)
    if url:
        try:
            from app.services.credentials_service import _base_domain, _host
            host = _host(url)
            if host:
                queries |= _service_tokens(_base_domain(host))
        except Exception:
            pass

    matched: List[str] = []
    for name in names:
        low = name.strip().lower()
        if any(q in low or low in q for q in queries):
            matched.append(name)

    # 打ち間違い・語順違いも拾う
    if service:
        import difflib
        for name in difflib.get_close_matches(
            _normalize_service_name(service), names, n=3, cutoff=0.6
        ):
            if name not in matched:
                matched.append(name)

    return matched[:5]


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
            "login_url": {
                "type": "string",
                "description": "ログインページのURL/ドメイン（例: account.line.biz）。同じメールが複数サービスにある時、後で url 指定で正しい記録を引けるよう保存しておく"
            },
        },
        "required": ["service"],
    },
}

GET_CREDENTIALS_TOOL = {
    "name": "get_credentials",
    "description": """サービスの認証情報をDBから取得する。
ログインが必要なサイトを操作する前に、認証情報が保存済みか確認する時に使用。

★推奨: ログインページにいる時は `url` に今のページURLを渡す。
同じメールアドレスが複数サービスに別パスワードで保存されていても、
ログイン先ドメインで照合して正しい1件を引ける（メールで推測して取り違える事故を防ぐ）。
`service` 名が分かっているならそれでもよい。url と service は併用可（url優先）。

返される内容:
- 保存済みの場合: ログインID と パスワード
- 未保存の場合: 認証情報が見つからない旨のメッセージ（ユーザーに聞くこと）""",
    "input_schema": {
        "type": "object",
        "properties": {
            "service": {
                "type": "string",
                "description": "サービス名（例: amazon, rakuten, mercari）"
            },
            "url": {
                "type": "string",
                "description": "現在のログインページURL（例: https://account.line.biz/login）。ドメイン照合で正しい認証情報を引く"
            }
        },
    },
}

SAVE_TOTP_SECRET_TOOL = {
    "name": "save_totp_secret",
    "description": """認証アプリ(TOTP)のシードを暗号化保存する。以後そのサービスの2段階認証は
`browser(action="fill_totp_code")` だけで突破でき、SMSもメールも一切不要になる。

★シードとは: 認証アプリの登録画面に一度だけ表示される英数字の文字列（QRコードの中身）。
6桁コードは「シード＋現在時刻」から計算されているだけなので、シードを持てばダン自身が
同じコードを生成できる。6桁コード自体は使い捨てなので保存しない（保存するのはシード）。

★使うタイミング（重要）:
- サービスの2段階認証を新規に設定する時、SMSではなく必ず「認証アプリ」を選び、
  表示されたシード（またはQRの otpauth:// URI）をこのツールで保存してから有効化を完了する
- ユーザーがシード/QRの文字列を渡してきた時
- 既にSMS認証になっているサービスにログインできた時、設定画面から認証アプリ方式へ
  切り替えてシードを保存しておく（次回以降スマホが不要になる）

secret には以下のどちらを渡してもよい:
- otpauth://totp/... の URI 全体（QRを読めた場合はこれが確実。桁数や周期も自動で読む）
- 素のシード文字列（"abcd efgh ijkl" のような空白区切り・小文字でもよい）

保存済みのID/パスワードは消えない（統合される）。""",
    "input_schema": {
        "type": "object",
        "properties": {
            "service": {
                "type": "string",
                "description": "サービス名（例: meta, google, amazon）。既存の認証情報と同じ名前にすると1件に統合される"
            },
            "secret": {
                "type": "string",
                "description": "otpauth:// URI 全体、または素のbase32シード文字列"
            },
            "login_url": {
                "type": "string",
                "description": "ログインページのURL/ドメイン（例: facebook.com）。指定するとURL照合でも引ける"
            },
        },
        "required": ["service", "secret"],
    },
}

# ============================================
# 個人情報の記憶ツール（電話・カード・住所など）
# ============================================

REMEMBER_PERSONAL_INFO_TOOL = {
    "name": "remember_personal_info",
    "description": """ユーザーの個人情報（電話番号・クレジットカード・住所・誕生日など）を
暗号化して永続保存する。サービスのログイン情報ではない個人情報はこちらを使う
（ログインID/パスワードは save_credentials を使う）。

★重要: ユーザーが個人情報を口にした瞬間に、聞き返さず即座にこのツールで保存すること。
保存した情報はシステムプロンプトにマスク表示で常時注入され、次回以降のセッションでも
「保有済み」として認識される。一度教われば二度と聞き直さないのが目的。

使用例:
- 「俺の電話は090-1234-5678」→ field_key:"phone", value:"090-1234-5678"
- 「カードはVISAの4111 1111 1111 1111、有効期限12/28」→ field_key:"credit_card", value:"4111111111111111 exp12/28", label:"VISA"
- 「実家の住所は◯◯」→ field_key:"address_home", value:"...", category:"address"

実値はDBに暗号化保存され、平文ではどこにも残らない。""",
    "input_schema": {
        "type": "object",
        "properties": {
            "field_key": {
                "type": "string",
                "description": "情報の種類キー（例: phone, credit_card, address_home, birthday, email）。同じキーで再保存すると上書き更新される。"
            },
            "value": {
                "type": "string",
                "description": "保存する実値（電話番号・カード番号など）。そのまま暗号化される。"
            },
            "category": {
                "type": "string",
                "description": "分類（contact / payment / address / identity / other）。省略時は field_key から自動推論。"
            },
            "label": {
                "type": "string",
                "description": "人間向けラベル（例: 'メインのVISA', '会社用携帯'）。省略可。"
            },
        },
        "required": ["field_key", "value"],
    },
}

GET_PERSONAL_INFO_TOOL = {
    "name": "get_personal_info",
    "description": """保存済みの個人情報の実値を復号して取得する。
フォーム入力・予約・購入など、実値が必要な操作の直前に使う。

システムプロンプトの「保存済み個人情報」一覧にある field_key を指定すると、
マスクされていない実際の値が返る。一覧に無い情報はユーザーに聞くこと。""",
    "input_schema": {
        "type": "object",
        "properties": {
            "field_key": {
                "type": "string",
                "description": "取得する情報のキー（例: phone, credit_card, address_home）"
            }
        },
        "required": ["field_key"],
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

    if tool_name == "save_totp_secret":
        return ("_save_totp_secret", "save")

    if tool_name == "remember_personal_info":
        return ("_remember_personal_info", "save")

    if tool_name == "get_personal_info":
        return ("_get_personal_info", "get")

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

    if tool_name == "schedule_followup":
        return ("_followup", "schedule")

    if tool_name == "watch":
        return ("_watch", "manage")

    if tool_name == "split_to_new_room":
        return ("_split_room", "split")

    if tool_name == "attach_image":
        return ("_attach_image", "attach")

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

        # 内容による判定（フォールバック）
        if "developer" in name or "開発機能" in content or "self-healing" in content_lower:
            return "developer", "developer"
        elif "ex予約" in content or "新幹線" in content:
            return "train", "ex_reservation"
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

    # ★★★ 画像添付マーカー生成 ★★★
    if skill_name == "_attach_image":
        return await _execute_attach_image(params)

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
                    cwd=str(PROJECT_ROOT),
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
        search_path = params.get("path", str(PROJECT_ROOT))
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
        search_path = params.get("path", str(PROJECT_ROOT))
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
        url = params.get("url")
        if not service and not url:
            return {"success": False, "error": "service または url が必要です"}

        from app.services.credentials_service import get_credentials_service
        creds_service = get_credentials_service()

        stored_creds = None
        matched_service = None

        # 1) URL（ログイン先ドメイン）で照合 — 同一メール複数サービスの取り違えを防ぐ最優先経路
        if url:
            from app.services.credentials_service import narrow_url_matches
            url_matches = narrow_url_matches(
                await creds_service.find_credentials_by_url(user_id, url)
            )
            if len(url_matches) == 1:
                stored_creds = url_matches[0]
                matched_service = stored_creds.get("service")
            elif len(url_matches) > 1 and not service:
                # 同一ドメインに複数アカウント（例: Instagram の個人用と事業用）。
                # 1件目を黙って返すと別アカウントのパスワードを渡すことになる。
                names = [m.get("service") for m in url_matches if m.get("service")]
                return {
                    "success": False,
                    "service": None,
                    "suggestions": names,
                    "message": (
                        f"{url} には複数の認証情報が保存されています: {', '.join(names)}。"
                        "どれを使うか service で指定して取り直すこと。"
                    ),
                }

        # 2) サービス名で取得（正規化 → 元の名前でフォールバック）
        if not stored_creds and service:
            service_normalized = _normalize_service_name(service)
            stored_creds = await creds_service.get_credential(user_id, service_normalized)
            if not stored_creds and service_normalized != service:
                stored_creds = await creds_service.get_credential(user_id, service)
            if stored_creds:
                matched_service = service_normalized

        if stored_creds:
            return {
                "success": True,
                "service": matched_service,
                "login_id": stored_creds.get("id", ""),
                "password": stored_creds.get("password", ""),
                "message": f"{matched_service} の認証情報が見つかりました",
            }
        else:
            label = service or url
            suggestions = await _suggest_credential_services(
                creds_service, user_id, service, url
            )
            if suggestions:
                message = (
                    f"{label} という名前では見つかりませんでした。"
                    f"似た名前で保存済み: {', '.join(suggestions)}。"
                    "この中に目的のものがあれば service をその名前にして取り直すこと。"
                    "候補を確認せずに「保存されていない」と判断しないこと。"
                )
            else:
                message = f"{label} の認証情報は保存されていません。ユーザーに聞いてください。"
            return {
                "success": False,
                "service": matched_service,
                "suggestions": suggestions,
                "message": message,
            }

    # ★★★ 認証情報保存 ★★★
    if skill_name == "_save_credentials":
        service = params.get("service")
        copy_from = params.get("copy_from")
        login_id = params.get("login_id")
        password = params.get("password")
        login_url = params.get("login_url")

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
            login_url=login_url,
        )

        return {"success": True}

    # ★★★ 認証アプリ(TOTP)シードの保存 ★★★
    if skill_name == "_save_totp_secret":
        service = params.get("service")
        secret = params.get("secret")
        if not service or not secret:
            return {"success": False, "error": "service と secret が必要です"}

        service = _normalize_service_name(service)

        from app.services.totp_service import parse_totp_uri, generate_code, TOTPError
        try:
            parsed = parse_totp_uri(secret)
        except TOTPError as exc:
            # 値そのものは返さない
            return {"success": False, "error": str(exc)}

        from app.services.credentials_service import get_credentials_service
        creds_service = get_credentials_service()
        result = await creds_service.save_totp_secret(
            user_id=user_id,
            service=service,
            secret=parsed["secret"],
            digits=parsed["digits"],
            period=parsed["period"],
            algorithm=parsed["algorithm"],
            login_url=params.get("login_url"),
        )
        if not result.get("success"):
            return {"success": False, "error": result.get("message", "保存に失敗しました")}

        # 保存直後に一度生成して、実際にコードが作れる状態か確かめる（値は返さない）。
        # 登録画面で確認コードを求められた時、ここで失敗に気付けないと詰む。
        try:
            generate_code(
                parsed["secret"],
                digits=parsed["digits"],
                period=parsed["period"],
                algorithm=parsed["algorithm"],
            )
        except TOTPError as exc:
            return {"success": False, "error": f"保存しましたがコード生成に失敗します: {exc}"}

        return {
            "success": True,
            "service": service,
            "message": (
                f"{service} の認証アプリのシードを保存しました。"
                f"以後は browser(action=\"fill_totp_code\", service=\"{service}\", ref=\"...\") で"
                "SMSを待たずに2段階認証を突破できます。"
                "登録画面で確認コードを求められている場合は、そのまま fill_totp_code で入力してください。"
            ),
        }

    # ★★★ 個人情報の保存（電話・カード・住所等）★★★
    if skill_name == "_remember_personal_info":
        field_key = params.get("field_key")
        value = params.get("value")
        if not field_key or value is None or value == "":
            return {"success": False, "error": "field_key と value が必要です"}

        from app.services.personal_info_service import get_personal_info_service
        pinfo = get_personal_info_service()
        result = await pinfo.save(
            user_id=user_id,
            field_key=field_key,
            value=value,
            category=params.get("category", ""),
            label=params.get("label", ""),
        )
        if result.get("success"):
            return {
                "success": True,
                "field_key": result.get("field_key"),
                "masked_hint": result.get("masked_hint"),
                "message": f"{result.get('field_key')} を保存しました（{result.get('masked_hint')}）。次回以降も覚えています。",
            }
        return {"success": False, "error": result.get("error", "保存に失敗しました")}

    # ★★★ 個人情報の取得（復号）★★★
    if skill_name == "_get_personal_info":
        field_key = params.get("field_key")
        if not field_key:
            return {"success": False, "error": "field_key が必要です"}

        from app.services.personal_info_service import get_personal_info_service
        pinfo = get_personal_info_service()
        info = await pinfo.get(user_id, field_key)
        if info and info.get("value") is not None:
            return {
                "success": True,
                "field_key": info.get("field_key"),
                "value": info.get("value"),
                "label": info.get("label"),
            }
        return {
            "success": False,
            "field_key": field_key,
            "message": f"{field_key} は保存されていません。ユーザーに聞いてください。",
        }

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

    # ★★★ ブラウザ直接操作ツール ★★★
    if skill_name == "_browser":
        real_action = action
        if real_action == "__from_params":
            real_action = params.pop("action", "screenshot")
        return await _execute_browser_tool(real_action, params)

    # ★★★ URL読み込み（Jina Reader）★★★
    if skill_name == "_jina":
        return await _execute_read_url(params)

    # ★★★ 続報の予約（後で自動で起こして報告させる）★★★
    if skill_name == "_followup":
        return await _execute_schedule_followup(params, session_id, user_id)

    # ★★★ 見張り（未来の約束の登録・一覧・取消）★★★
    if skill_name == "_watch":
        return await _execute_watch(params, session_id, user_id)

    # ★★★ 脱線した話題を新しいチャットに切り出す ★★★
    if skill_name == "_split_room":
        return await _execute_split_to_new_room(params, session_id, user_id)

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
        debug_log = PROJECT_ROOT / "skill_analyze_debug.log"
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

_browser_auth_state: Dict[str, Any] = {
    "target_url": None,
    "login_url": None,
}


def _looks_like_login_url(url: str) -> bool:
    """Conservatively detect explicit login pages without inspecting credentials."""
    parsed = urlparse(url)
    haystack = f"{parsed.path}?{parsed.query}".lower()
    return any(token in haystack for token in (
        "/login", "/signin", "/sign-in", "/auth/login", "/account/login",
        "login=", "signin=", "sign_in=",
    ))


# 確認コードの入力欄が「1桁ずつ6個」に分かれているサイト向け。
# ref の欄へ6桁をまとめて入れると maxlength=1 で先頭1桁に切られ、
# 「コードが未入力」として弾かれる（2captcha の 2FA 画面がこれ）。
# 値は引数で渡し、戻り値には入れ方だけを返す（コードを外に出さない）。
_FILL_CODE_JS = """
(args) => {
  const code = String(args.code || '').trim();
  const target = document.querySelector(
    '[data-dan-ref="' + String(args.ref || '').replace('@', '') + '"]'
  );
  if (!target || !code) return {mode: 'none'};

  const setValue = (el, v) => {
    const setter = Object.getOwnPropertyDescriptor(
      window.HTMLInputElement.prototype, 'value'
    ).set;
    setter.call(el, v);
    el.dispatchEvent(new Event('input', {bubbles: true}));
    el.dispatchEvent(new Event('change', {bubbles: true}));
  };
  const isDigitBox = (el) => el.tagName === 'INPUT' && el.maxLength === 1;

  if (!isDigitBox(target)) return {mode: 'single'};

  const scope = target.form || target.closest('form, fieldset, div') || document;
  let boxes = [...scope.querySelectorAll('input')].filter(isDigitBox);
  if (boxes.length < code.length) {
    boxes = [...document.querySelectorAll('input')].filter(isDigitBox);
  }
  const start = Math.max(0, boxes.indexOf(target));
  const slice = boxes.slice(start, start + code.length);
  if (slice.length < code.length) return {mode: 'short'};

  slice.forEach((el, i) => { el.focus(); setValue(el, code[i]); });
  slice[slice.length - 1].focus();

  // 分割UIの裏で実際に送信される集約欄にも同じ値を入れておく
  const form = target.form;
  if (form) {
    for (const el of form.querySelectorAll('input')) {
      if (isDigitBox(el)) continue;
      const name = ((el.name || '') + ' ' + (el.id || '')).toLowerCase();
      if (/code|otp|token|2fa/.test(name)) setValue(el, code);
    }
  }
  return {mode: 'split', digits: slice.length};
}
"""


async def _fill_code_into_inputs(page, ref: str, code: str) -> str:
    """確認コードを入力欄へ入れる。1桁ずつに分かれたUIなら各桁へ配る。

    分割されていない普通の欄なら従来どおり fill_by_ref に任せる。
    """
    try:
        result = await page.evaluate(_FILL_CODE_JS, {"ref": ref, "code": code})
    except Exception as exc:  # JS 実行に失敗しても通常入力で続行する
        logger.warning(f"確認コードの分割入力に失敗、通常入力にフォールバック: {exc}")
        result = None

    if isinstance(result, dict) and result.get("mode") == "split":
        return "split"

    await page.fill_by_ref(ref, code)
    return "single"


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

    # 添付する写真は縮小されている。写真から座標を読んで操作する時に換算を
    # 忘れると、掴む位置が対象の外に落ちて「何も動かない」状態になるため、
    # 倍率と「換算は自動」であることを毎回明示する。
    if isinstance(screenshot, dict) and screenshot.get("shot_scale"):
        s = float(screenshot["shot_scale"])
        if abs(s - 1.0) > 0.001:
            text_parts.append(
                f"写真の縮小率: {s:.3f}（実座標の{s:.3f}倍で表示）。"
                "human_click / human_drag は写真上の座標をそのまま渡せば自動換算されます"
                "（手計算不要）。"
            )

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
        # パスワード欄の値（保存済み認証情報を fill_credential で入れた場合など）は
        # 要素一覧に平文で出さない。入力済みかどうかだけ分かるようマスクする。
        if el_type == "password" and text:
            text = "••••••••（入力済み・非表示）"
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

        if action in {"open", "open_target"}:
            url = params.get("url")
            if not url:
                return {"success": False, "error": "url が必要です"}
            if action == "open" and _looks_like_login_url(url):
                return {
                    "success": False,
                    "error": (
                        "Direct navigation to a login page is blocked. "
                        "Use browser(action=\"open_target\", url=\"<actual destination>\") first "
                        "so the existing authenticated session can be reused."
                    ),
                }
            await page.goto(url)
            await page.wait_for_load_state("domcontentloaded", timeout=BROWSER_LOAD_TIMEOUT)
            if action == "open_target" and not _looks_like_login_url(page.url):
                # Apple等はDOM構築後にJSでログイン画面へ飛ぶ。ここで待たずにURLを見ると
                # 「ログイン済み」と誤判定し、後続のclickがログインガードでgo_backされる。
                # networkidleは常時通信のあるサイトでは来ないので、URL自体をポーリングする。
                # ブラウザ起動直後は遷移が終わるまで about:blank が返り続けることがある。
                # URLが確定するまでは判定を保留しないと、同じく誤判定になる。
                settled_polls = 0
                for _ in range(100):  # 最大20秒
                    current_url = page.url or ""
                    if not current_url or current_url.startswith("about:"):
                        await page.wait_for_timeout(200)
                        continue
                    if _looks_like_login_url(current_url):
                        break
                    settled_polls += 1
                    if settled_polls >= 30:  # URL確定後の遅延リダイレクト待ちは6秒
                        break
                    await page.wait_for_timeout(200)
            state = await _get_browser_state(page)
            if action == "open_target":
                _browser_auth_state["target_url"] = url
                _browser_auth_state["login_url"] = page.url if _looks_like_login_url(page.url) else None
                message = (
                    "Target page opened first. Authentication is required because the site redirected to a login page."
                    if _browser_auth_state["login_url"]
                    else "Target page opened first. Existing browser session was reused; do not log in again."
                )
                state["content"].insert(0, {"type": "text", "text": message})
            else:
                _browser_auth_state["target_url"] = None
                _browser_auth_state["login_url"] = None
            return state

        elif action == "screenshot":
            return await _get_browser_state(page)

        elif action == "solve_captcha":
            # reCAPTCHA(v2/v3/Enterprise) / hCaptcha / Cloudflare Turnstile（トークン型）と
            # 画像文字CAPTCHA（歪んだ文字を読む型）を 2captcha経由で自動突破する。
            # フォーム送信前・ログイン前に呼ぶ。ユーザーへ丸投げしない。
            from app.tools.captcha_solver import (
                solve_page_captchas,
                solve_image_captcha,
                CaptchaNotConfigured,
                CaptchaError,
            )

            def _ref_to_sel(v):
                if not v:
                    return None
                return f'[data-dan-ref="{str(v).lstrip("@")}"]'

            image_selector = params.get("image_selector") or _ref_to_sel(params.get("image_ref"))
            input_selector = params.get("input_selector") or _ref_to_sel(params.get("input_ref"))

            try:
                summary = await solve_page_captchas(page)
                parts = []
                if summary["count"]:
                    types = ", ".join(s["type"] for s in summary["solved"])
                    parts.append(f"トークン型captchaを突破（{summary['count']}件: {types}）")
                # 画像文字CAPTCHA（トークン型が無い／指定がある場合に試行）
                if summary["count"] == 0 or image_selector:
                    img = await solve_image_captcha(page, image_selector, input_selector)
                    if img.get("found"):
                        parts.append(f"画像文字CAPTCHAを突破（『{img['text']}』を入力欄に記入）")
            except CaptchaNotConfigured as e:
                return {"success": False, "error": f"2captcha未設定（.envのTWOCAPTCHA_API_KEY）: {e}"}
            except CaptchaError as e:
                state = await _get_browser_state(page)
                state["content"].insert(0, {"type": "text", "text": f"captcha自動解決に失敗しました: {e}"})
                return state

            state = await _get_browser_state(page)
            if not parts:
                msg = "このページにcaptchaは検出されませんでした。そのまま送信/ログインして問題ありません。"
            else:
                msg = (
                    "captchaを自動突破しました（" + " / ".join(parts) + "）。"
                    "続けて送信/ログインボタンをクリックしてください。ユーザーには丸投げしないこと。"
                )
            state["content"].insert(0, {"type": "text", "text": msg})
            return state

        elif action == "click":
            ref = params.get("ref")
            x = params.get("x")
            y = params.get("y")
            login_was_authorized = bool(_browser_auth_state.get("login_url"))

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
            if _looks_like_login_url(page.url) and not login_was_authorized:
                try:
                    await page.go_back()
                    await page.wait_for_load_state("domcontentloaded", timeout=BROWSER_LOAD_TIMEOUT)
                except Exception:
                    pass
                state = await _get_browser_state(page)
                state["success"] = False
                state["error"] = (
                    "Navigation to a login page was blocked because the actual destination "
                    "was not checked first. Use open_target with the destination URL."
                )
                return state
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

        elif action == "fill_credential":
            # 保存済みのログイン情報（パスワード/ID）を、値をモデルに一切見せずに入力欄へ流し込む。
            # get_credentials はパスワードを伏せ字で返すため type では入力できない。ここで
            # サーバ側で復号した実値を直接 Playwright の入力欄へ入れる。戻り値に値は含めない。
            ref = params.get("ref")
            field = (params.get("field") or "password").lower()
            service = params.get("service")
            url = params.get("url")
            if not ref:
                return {"success": False, "error": "ref が必要です"}
            if not service and not url:
                return {"success": False, "error": "service または url が必要です"}
            if field not in {"password", "username"}:
                return {"success": False, "error": "field は 'password' か 'username' を指定してください"}

            user_id = os.environ.get("DAN_USER_ID", "00000000-0000-0000-0000-000000000001")
            from app.services.credentials_service import get_credentials_service
            creds_service = get_credentials_service()

            stored_creds = None
            # 1) ログイン先URLで照合（同一メール複数サービスの取り違え防止・最優先）
            if url:
                from app.services.credentials_service import narrow_url_matches
                url_matches = narrow_url_matches(
                    await creds_service.find_credentials_by_url(user_id, url)
                )
                if len(url_matches) == 1:
                    stored_creds = url_matches[0]
                elif len(url_matches) > 1 and not service:
                    # 同一ドメインに複数アカウント。取り違えたパスワードを流し込むと
                    # ログイン失敗が続くだけでなく、アカウントがロックされることもある。
                    names = [m.get("service") for m in url_matches if m.get("service")]
                    return {
                        "success": False,
                        "error": (
                            f"{url} には複数の認証情報が保存されています: {', '.join(names)}。"
                            "どれを入力するか service で指定してください。"
                        ),
                    }
            # 2) サービス名で取得（正規化 → 元の名前でフォールバック）
            if not stored_creds and service:
                service_normalized = _normalize_service_name(service)
                stored_creds = await creds_service.get_credential(user_id, service_normalized)
                if not stored_creds and service_normalized != service:
                    stored_creds = await creds_service.get_credential(user_id, service)

            if not stored_creds:
                label = service or url
                suggestions = await _suggest_credential_services(
                    creds_service, user_id, service, url
                )
                hint = (
                    f" 似た名前で保存済み: {', '.join(suggestions)}。service を指定し直してください。"
                    if suggestions else " ユーザーに聞いてください。"
                )
                return {"success": False, "error": f"{label} の認証情報が保存されていません。{hint}"}

            value = stored_creds.get("password", "") if field == "password" else stored_creds.get("id", "")
            if not value:
                return {"success": False, "error": f"保存された認証情報に {field} がありません"}

            await page.fill_by_ref(ref, value)

            if params.get("press_enter", False):
                await page.keyboard.press("Enter")
                try:
                    await page.wait_for_load_state("load", timeout=BROWSER_LOAD_TIMEOUT)
                except Exception:
                    await page.wait_for_timeout(2000)

            field_label = "パスワード" if field == "password" else "ログインID"
            # 値は絶対に返さない。入力できたことだけを伝える。
            return {
                "success": True,
                "content": [{
                    "type": "text",
                    "text": (
                        f"保存済みの{field_label}を {ref} に入力しました（値は非表示）。"
                        "続けて必要ならサインイン/送信ボタンを click してください。"
                        "状態を見る場合は screenshot を呼ぶ（パスワード欄の値はマスクされます）。"
                    ),
                }],
            }

        elif action in ("human_click", "human_drag"):
            # 人間らしいポインタ操作。CAPTCHAは「答えが合っているか」だけでなく
            # 「どう操作したか」も採点する。座標へ瞬間移動して押すだけの操作は
            # 機械と判定され、正しい位置に置いても「誤った返答」で弾かれる。
            # 曲線を描いて近づき、緩急と微細なブレを混ぜ、押下前後に間を置く。
            x, y = params.get("x"), params.get("y")
            if x is None or y is None:
                return {"success": False, "error": "x と y が必要です"}

            from app.tools.human_pointer import HumanPointer
            from app.tools.browser import get_last_shot_scale, image_to_css

            # スクリーンショットは縮小して渡しているので、写真から読んだ座標と
            # 実際のクリック座標は一致しない。既定を「写真の座標」にして、ここで
            # 換算する。手計算に頼ると掴む位置が対象の外に落ち、図形が動かない
            # まま時間だけ溶ける（実際にそれで何度も失敗した）。
            coords = (params.get("coords") or "image").lower()
            scale = get_last_shot_scale()
            conv = image_to_css if coords == "image" else (lambda a, b: (a, b))

            pointer = HumanPointer(page)
            cx, cy = conv(float(x), float(y))

            if action == "human_drag":
                to_x, to_y = params.get("to_x"), params.get("to_y")
                if to_x is None or to_y is None:
                    return {"success": False, "error": "human_drag には to_x と to_y が必要です"}
                tx, ty = conv(float(to_x), float(to_y))
                await pointer.drag(cx, cy, tx, ty)
                note = (
                    f"({x},{y}) から ({to_x},{to_y}) へ人間らしい軌道でドラッグしました"
                    f"（写真座標→実座標に換算: 倍率{scale:.3f} → 実際は ({cx:.0f},{cy:.0f})→({tx:.0f},{ty:.0f})）。"
                )
            else:
                await pointer.click(cx, cy)
                note = (
                    f"({x},{y}) を人間らしい動きでクリックしました"
                    f"（写真座標→実座標に換算: 倍率{scale:.3f} → 実際は ({cx:.0f},{cy:.0f})）。"
                )

            state = await _get_browser_state(page)
            state["success"] = True
            state["content"] = [{"type": "text", "text": note}] + (state.get("content") or [])
            return state

        elif action == "puzzle_fit":
            # 「図形をはめる」パズルを、確信が持てる時だけ答える。
            # 撮影→形状の一致度計算→判定→ドラッグを1回の呼び出しで完結させる。
            # 目視で座標を割り出していると、調べている間にチャレンジが時間切れに
            # なって最初からやり直しになるため。
            # 一致度が閾値に届かない時は答えず、『更新』で別の問題を引き直す。
            # 誤答はEpic側の警戒を上げるので、精度の低い回答を出す方が損になる。
            from app.tools.puzzle_fit import solve_shape_puzzle

            result = await solve_shape_puzzle(
                page,
                threshold=float(params.get("threshold") or 0.85),
                max_refresh=int(params.get("max_refresh") or 3),
            )
            if result.get("answered"):
                note = (
                    f"一致度 {result['score']}（次点 {result['runner_up']}）で確信が持てたので、"
                    f"({result['from']['x']},{result['from']['y']}) から "
                    f"({result['to']['x']},{result['to']['y']}) へ人間らしい軌道で運びました。"
                    f"引き直し {len(result['attempts']) - 1} 回。"
                )
            else:
                tried = " / ".join(
                    f"{a['attempt']}問目 一致度{a['score']}" for a in result.get("attempts", [])
                )
                note = (
                    f"確信が持てないので答えていません。{result.get('reason')}"
                    + (f"（{tried}）" if tried else "")
                )
            state = await _get_browser_state(page)
            state["success"] = True
            state["content"] = [{"type": "text", "text": note}] + (state.get("content") or [])
            return state

        elif action == "fill_totp_code":
            # 認証アプリ(TOTP)のコードをサーバー側で生成して入力欄へ直接入れる。
            # シードと現在時刻から計算するだけなので、SMS/メールの到着を待つ必要がない。
            # fill_credential と同様、生成した値はモデルに一切返さない。
            ref = params.get("ref")
            service = params.get("service")
            url = params.get("url")
            if not ref:
                return {"success": False, "error": "ref が必要です"}
            if not service and not url:
                return {"success": False, "error": "service または url が必要です"}

            user_id = os.environ.get("DAN_USER_ID", "00000000-0000-0000-0000-000000000001")
            from app.services.credentials_service import get_credentials_service
            creds_service = get_credentials_service()

            stored_creds = None
            # 1) ログイン先URLで照合（同一ドメイン複数アカウントの取り違え防止）
            if url:
                from app.services.credentials_service import narrow_url_matches
                url_matches = narrow_url_matches(
                    await creds_service.find_credentials_by_url(user_id, url)
                )
                with_totp = [m for m in url_matches if m.get("totp_secret")]
                if len(with_totp) == 1:
                    stored_creds = with_totp[0]
                elif len(with_totp) > 1 and not service:
                    names = [m.get("service") for m in with_totp if m.get("service")]
                    return {
                        "success": False,
                        "error": (
                            f"{url} には認証アプリのシードが複数保存されています: {', '.join(names)}。"
                            "どれを使うか service で指定してください。"
                        ),
                    }
            # 2) サービス名で取得（正規化 → 元の名前でフォールバック）
            if not stored_creds and service:
                service_normalized = _normalize_service_name(service)
                stored_creds = await creds_service.get_credential(user_id, service_normalized)
                if not stored_creds and service_normalized != service:
                    stored_creds = await creds_service.get_credential(user_id, service)

            if not stored_creds or not stored_creds.get("totp_secret"):
                label = service or url
                return {
                    "success": False,
                    "error": (
                        f"{label} には認証アプリ(TOTP)のシードが保存されていません。"
                        "このサービスはまだ認証アプリ方式になっていない可能性があります。"
                        "SMS/メールで認証を進め、ログインできたら設定画面で認証アプリ方式に切り替えて "
                        "save_totp_secret でシードを保存してください（次回からSMS不要になります）。"
                    ),
                }

            from app.services.totp_service import (
                generate_from_stored,
                seconds_remaining,
                TOTPError,
            )
            try:
                generated = generate_from_stored(stored_creds)
                # 残り僅かだと入力中に切り替わって弾かれる。次の窓まで待ってから入れる。
                if generated["seconds_remaining"] <= 3:
                    await page.wait_for_timeout(
                        (generated["seconds_remaining"] + 1) * 1000
                    )
                    generated = generate_from_stored(stored_creds)
            except TOTPError as exc:
                return {"success": False, "error": str(exc)}

            await _fill_code_into_inputs(page, ref, generated["code"])

            if params.get("press_enter", False):
                await page.keyboard.press("Enter")
                try:
                    await page.wait_for_load_state("load", timeout=BROWSER_LOAD_TIMEOUT)
                except Exception:
                    await page.wait_for_timeout(2000)

            # 値は絶対に返さない。入力できたことと、残り有効秒数だけ伝える。
            return {
                "success": True,
                "content": [{
                    "type": "text",
                    "text": (
                        f"認証アプリのコードを生成して {ref} に入力しました（値は非表示・"
                        f"残り約{generated['seconds_remaining']}秒有効）。"
                        "続けて送信ボタンを click してください。"
                        "コードが拒否された場合は時刻ずれの可能性があるので、もう一度この操作を呼べば"
                        "新しいコードが入ります。"
                    ),
                }],
            }

        elif action == "wait_for_otp_from_app":
            timeout_seconds = max(1, min(int(params.get("timeout_seconds", 30)), 120))
            user_id = os.environ.get("DAN_USER_ID", "00000000-0000-0000-0000-000000000001")
            source = (params.get("source") or "sms").lower()
            email_address = params.get("email_address")
            ref = params.get("ref")

            from app.services.otp_service import get_otp_service
            otp_service = get_otp_service()

            # メールOTPモード: そのアドレスの受信箱を読めるか確認。読めなければ
            # 「ただ聞く」のではなくアプリパスワード発行のオンボーディングを案内する。
            # ref（入力欄）を要求する前にチェックするので、案内だけ単体で試せる。
            if source == "email" and email_address:
                if not await otp_service.has_imap_access(user_id, email_address):
                    from app.services.otp_service import app_password_guidance
                    g = app_password_guidance(email_address)
                    return {
                        "success": False,
                        "needs_app_password": True,
                        "email_address": email_address,
                        "error": (
                            f"{email_address} の受信箱を読む手段（アプリパスワード）が未登録のため、"
                            f"メールに届くOTPを自動取得できません。ユーザーにこう案内してください:\n"
                            f"「{g['note']} で発行したアプリパスワードを、ここに貼ってください」\n"
                            f"貼られたら save_credentials(service=\"{g['service']}\", login_id=\"{email_address}\", "
                            f"password=\"<アプリパスワード>\") で保存し、この操作を再実行する。ブラウザは閉じない。"
                        ),
                    }

            if not ref:
                return {"success": False, "error": "ref is required"}

            otp_code = await otp_service.wait_for_otp(
                user_id=user_id,
                service=params.get("service"),
                source=source,
                email_address=email_address,
                timeout_seconds=timeout_seconds,
                poll_interval=2,
            )

            if not otp_code:
                state = await _get_browser_state(page)
                state["success"] = False
                src_label = "メール" if source == "email" else "Androidアプリ(SMS)"
                hint = ""
                if source == "sms":
                    try:
                        dev = await otp_service.get_apk_otp_device_status(user_id)
                        hint = (
                            f" Forwarder device status: enabled={dev.get('enabled')}, "
                            f"device={dev.get('device_name')}, last_received_at={dev.get('last_received_at')}."
                            " If the user says the SMS DID arrive on their phone, the app's local"
                            " forwarding setting was probably lost (reinstall/logout) — ask them to"
                            " open the Dan app once (opening it self-repairs the setting) and then"
                            " resend the code, instead of asking them to read the code aloud."
                        )
                    except Exception:
                        pass
                state["error"] = (
                    f"No OTP arrived from {src_label} within {timeout_seconds} seconds."
                    + hint
                    + " Keep this browser page open. If a resend is not possible, ask the user to enter the code manually."
                )
                return state

            await _fill_code_into_inputs(page, ref, otp_code)
            if params.get("press_enter", False):
                await page.keyboard.press("Enter")
                try:
                    await page.wait_for_load_state("domcontentloaded", timeout=BROWSER_LOAD_TIMEOUT)
                except Exception:
                    await page.wait_for_timeout(1000)

            state = await _get_browser_state(page)
            state["content"].insert(0, {
                "type": "text",
                "text": "OTP was received from the Android app and entered without exposing the code.",
            })
            return state

        elif action == "wait_for_link_from_app":
            # 数字コードではなく「タップして再設定」形式のワンタイムURLが届く
            # サービス向け。届いたリンクをこのブラウザで開くところまでやる。
            timeout_seconds = max(1, min(int(params.get("timeout_seconds", 60)), 180))
            user_id = os.environ.get("DAN_USER_ID", "00000000-0000-0000-0000-000000000001")
            source = (params.get("source") or "sms").lower()
            email_address = params.get("email_address")

            from app.services.otp_service import get_otp_service
            otp_service = get_otp_service()

            if source == "email" and email_address:
                if not await otp_service.has_imap_access(user_id, email_address):
                    from app.services.otp_service import app_password_guidance
                    g = app_password_guidance(email_address)
                    return {
                        "success": False,
                        "needs_app_password": True,
                        "email_address": email_address,
                        "error": (
                            f"{email_address} の受信箱を読む手段（アプリパスワード）が未登録のため、"
                            f"メールに届くワンタイムURLを自動取得できません。ユーザーにこう案内してください:\n"
                            f"「{g['note']} で発行したアプリパスワードを、ここに貼ってください」\n"
                            f"貼られたら save_credentials(service=\"{g['service']}\", login_id=\"{email_address}\", "
                            f"password=\"<アプリパスワード>\") で保存し、この操作を再実行する。ブラウザは閉じない。"
                        ),
                    }

            link_url = await otp_service.wait_for_link(
                user_id=user_id,
                service=params.get("service"),
                source=source,
                email_address=email_address,
                timeout_seconds=timeout_seconds,
                poll_interval=2,
            )

            if not link_url:
                state = await _get_browser_state(page)
                state["success"] = False
                src_label = "メール" if source == "email" else "Androidアプリ(SMS)"
                hint = ""
                if source == "sms":
                    try:
                        dev = await otp_service.get_apk_otp_device_status(user_id)
                        hint = (
                            f" Forwarder device status: enabled={dev.get('enabled')}, "
                            f"device={dev.get('device_name')}, last_received_at={dev.get('last_received_at')}."
                            " If the user says the SMS DID arrive on their phone, the app's local"
                            " forwarding setting was probably lost (reinstall/logout) — ask them to"
                            " open the Dan app once (opening it self-repairs the setting) and then"
                            " resend the link."
                        )
                    except Exception:
                        pass
                state["error"] = (
                    f"No one-time link arrived from {src_label} within {timeout_seconds} seconds."
                    + hint
                    + " Keep this browser page open. Ask the user to paste the link only as a last resort."
                )
                return state

            await page.goto(link_url)
            try:
                await page.wait_for_load_state("domcontentloaded", timeout=BROWSER_LOAD_TIMEOUT)
            except Exception:
                await page.wait_for_timeout(1000)

            link_host = link_url.split("//", 1)[-1].split("/", 1)[0]
            state = await _get_browser_state(page)
            state["content"].insert(0, {
                "type": "text",
                "text": (
                    f"One-time link received from the Android app ({link_host}) and opened in this browser. "
                    "The link itself is single-use and is not shown here."
                ),
            })
            return state

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

        elif action == "upload_file":
            path = params.get("path")
            if not path:
                return {"success": False, "error": "path（アップロードするファイルの絶対パス）が必要です"}
            import os as _os
            if not _os.path.exists(path):
                return {"success": False, "error": f"ファイルが見つかりません: {path}"}
            try:
                await page.upload_file(
                    files=[path],
                    ref=params.get("ref"),
                    selector=params.get("selector"),
                )
            except Exception as e:
                return {"success": False, "error": f"アップロードに失敗しました: {e}"}
            state = await _get_browser_state(page)
            state["content"].insert(0, {"type": "text", "text": f"ファイルを渡しました: {path}"})
            return state

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

async def _execute_attach_image(params: Dict[str, Any]) -> Dict[str, Any]:
    """
    画像をチャットに添付するための正規マーカーを生成する。

    source は以下のいずれか:
    - /api/v1/files/<filename> 形式の URL（絶対/相対）
    - uploads/ 配下のファイル名（例: "abc.png"）
    - 任意の絶対ローカルパス（uploads/ 外なら自動で UUID 名にコピー）
    """
    import re as _re
    import shutil as _shutil
    import uuid as _uuid

    source = (params.get("source") or "").strip()
    if not source:
        return {"success": False, "error": "source が必要です"}

    upload_dir = Path(__file__).resolve().parent.parent.parent.parent / "uploads"
    upload_dir.mkdir(parents=True, exist_ok=True)

    image_exts = {".png", ".jpg", ".jpeg", ".gif", ".webp", ".bmp"}
    filename: Optional[str] = None

    api_match = _re.search(r"/api/v1/files/([^/?#\s)\"']+)", source)
    if api_match:
        candidate = api_match.group(1)
        if (upload_dir / candidate).exists():
            filename = candidate
        else:
            return {
                "success": False,
                "error": f"指定ファイルが uploads/ に存在しません: {candidate}",
            }
    else:
        src_path = Path(source)
        if src_path.is_absolute():
            if not src_path.exists():
                return {
                    "success": False,
                    "error": f"ファイルが存在しません: {source}",
                }
            if src_path.suffix.lower() not in image_exts:
                return {
                    "success": False,
                    "error": f"画像ファイルではありません（拡張子: {src_path.suffix}）",
                }
            try:
                same_dir = src_path.resolve().parent == upload_dir.resolve()
            except Exception:
                same_dir = False
            if same_dir:
                filename = src_path.name
            else:
                filename = f"{_uuid.uuid4()}{src_path.suffix.lower()}"
                _shutil.copy2(src_path, upload_dir / filename)
        else:
            candidate_path = upload_dir / source
            if candidate_path.exists():
                filename = source
            else:
                return {
                    "success": False,
                    "error": f"uploads/ にファイルが見つかりません: {source}",
                }

    url = f"/api/v1/files/{filename}"
    marker = f"[添付画像: {url}]"
    logger.info(f"[ATTACH_IMAGE] marker={marker}")
    return {
        "success": True,
        "filename": filename,
        "url": url,
        "marker": marker,
        "instruction": (
            "次のアシスタント返答の本文に、上記 marker 文字列をそのまま貼り付けてください。"
            "改変・括弧追加・URL置換は一切しないこと。複数枚なら改行区切りで列挙。"
        ),
    }


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


async def _execute_schedule_followup(
    params: Dict[str, Any],
    session_id: Optional[str],
    user_id: Optional[str],
) -> Dict[str, Any]:
    """Register a deferred follow-up. room_id = session_id (the MCP server passes
    DAN_SESSION_ID as session_id, which is the room). A dan-core poller later
    re-invokes Dan with the note to actually check + report to chat."""
    import asyncio as _aio
    from app.services.followups import schedule_followup as _schedule

    room_id = session_id or ""
    if not room_id:
        return {"success": False, "error": "room_id (session) が不明なため続報を予約できません。"}

    note = params.get("note", "")
    delay = params.get("delay_seconds", 120)
    try:
        res = await _aio.to_thread(_schedule, room_id, note, delay, user_id)
    except Exception as e:
        return {"success": False, "error": f"続報の予約に失敗しました: {e}"}

    return {
        "success": bool(res.get("scheduled")),
        "message": res.get("message", ""),
        "fire_at": res.get("fire_at"),
    }


async def _execute_split_to_new_room(
    params: Dict[str, Any],
    session_id: Optional[str],
    user_id: Optional[str],
) -> Dict[str, Any]:
    """Split a drifted topic into a brand-new chat (project + room).

    1. Create a project (= sidebar chat) whose room is the new home of the topic.
       origin_room_id records where it was split from; the CLI model choice of
       the origin project is inherited.
    2. Register a `handoff` watch on the new room. The dan-core poller fires it on
       its next cycle and Dan speaks first there with the handoff memo. (This runs
       in the MCP subprocess, which dies with the turn — so the turn itself is
       driven by dan-core via the watch table, not from here.)
    The screen is NOT switched: the user opens the new chat from the sidebar
    (sidebar polls /projects every 10s).
    """
    import asyncio as _aio
    from app.services import followups as _fu
    from app.services.project_service import ProjectService
    from app.services.supabase_client import get_supabase_client

    origin_room_id = session_id or ""
    if not origin_room_id or not user_id:
        return {"success": False, "error": "room_id/user_id が不明なため新しいチャットを作れません。"}

    title = (params.get("title") or "").strip()[:80]
    handoff = (params.get("handoff") or "").strip()
    if not title:
        return {"success": False, "error": "title（新しいチャットの名前）が必要です。"}
    if not handoff:
        return {"success": False, "error": "handoff（引き継ぎメモ）が空です。新しい部屋の自分は元の会話を読めないので、経緯と次にやることを書いてください。"}

    def _origin_metadata() -> Optional[dict]:
        try:
            r = (
                get_supabase_client().client.table("projects")
                .select("metadata").eq("room_id", origin_room_id).limit(1).execute()
            )
            md = (r.data or [{}])[0].get("metadata") or {}
            model = md.get("model")
            return {"model": model} if model else None
        except Exception:
            return None

    try:
        metadata = await _aio.to_thread(_origin_metadata)
        project = await ProjectService().create_project(
            user_id=user_id,
            title=title,
            description=handoff[:2000],
            origin_room_id=origin_room_id,
            metadata=metadata,
        )
    except Exception as e:
        return {"success": False, "error": f"新しいチャットの作成に失敗しました: {e}"}

    new_room_id = project.get("room_id")
    if not new_room_id:
        return {"success": False, "error": "新しいチャットは作れましたが部屋IDが取れませんでした。"}

    try:
        res = await _aio.to_thread(
            _fu.create_watch, new_room_id, user_id, "handoff", handoff, spec={"origin_room_id": origin_room_id},
        )
    except Exception as e:
        res = {"scheduled": False, "message": str(e)}

    if not res.get("scheduled"):
        return {
            "success": True,
            "project_id": project.get("id"),
            "room_id": new_room_id,
            "title": title,
            "auto_start": False,
            "message": (
                f"新しいチャット「{title}」を作りました（サイドバーに表示されます）が、"
                f"自動起動の登録に失敗しました: {res.get('message')}。ユーザーがその部屋を開いて話しかければ続きができます。"
            ),
        }

    return {
        "success": True,
        "project_id": project.get("id"),
        "room_id": new_room_id,
        "title": title,
        "auto_start": True,
        "message": (
            f"新しいチャット「{title}」を作りました。"
            f"数十秒以内にその部屋で自分（ダン）が引き継ぎの一言目を話し始めます。"
        ),
    }


async def _execute_watch(
    params: Dict[str, Any],
    session_id: Optional[str],
    user_id: Optional[str],
) -> Dict[str, Any]:
    """Manage watches (standing instructions). room_id = session_id, same as
    schedule_followup. The dan-core poller fires them by kind (at/every/mail)."""
    import asyncio as _aio
    from datetime import datetime, timedelta, timezone
    from app.services import followups as _fu

    room_id = session_id or ""
    if not room_id:
        return {"success": False, "error": "room_id (session) が不明なため見張りを操作できません。"}

    action = (params.get("action") or "").strip()

    if action == "list":
        rows = await _aio.to_thread(_fu.list_watches, room_id)
        items = [
            {
                "id": r.get("id"),
                "kind": r.get("kind"),
                "note": r.get("plain_note"),
                "next_fire_at": r.get("fire_at"),
                "spec": {k: v for k, v in (r.get("spec") or {}).items()
                         if k != "consecutive_errors"},
            }
            for r in rows
        ]
        return {"success": True, "count": len(items), "watches": items,
                "message": f"この部屋の有効な見張りは {len(items)} 件です。"}

    if action == "cancel":
        wid = (params.get("watch_id") or "").strip()
        if not wid:
            return {"success": False, "error": "cancel には watch_id が必要です。"}
        ok = await _aio.to_thread(_fu.cancel_watch, wid, room_id)
        return {"success": ok,
                "message": "見張りを取り消しました。" if ok
                else "対象の見張りが見つかりません（既に完了・取消済みの可能性）。"}

    if action != "create":
        return {"success": False, "error": "action は create / list / cancel のいずれかです。"}

    note = params.get("note") or ""
    mail_from = (params.get("mail_from") or "").strip()
    interval = params.get("interval_seconds")
    spec: Dict[str, Any] = {}
    if params.get("hold_browser"):
        spec["hold_browser"] = True

    fire_at_dt = None
    at_raw = (params.get("at") or "").strip()
    if at_raw:
        try:
            dt = datetime.fromisoformat(at_raw.replace("Z", "+00:00"))
        except ValueError:
            return {"success": False,
                    "error": f"at の日時を解釈できません: {at_raw}（例 2026-08-25T10:00）"}
        if dt.tzinfo is None:
            dt = dt.replace(tzinfo=timezone(timedelta(hours=9)))  # タイムゾーン無しはJST
        fire_at_dt = dt

    monthly_day = params.get("monthly_day")
    weekly_day = params.get("weekly_day")
    if mail_from:
        kind = "mail"
        spec["from"] = mail_from
        if (params.get("mail_subject_contains") or "").strip():
            spec["subject_contains"] = params["mail_subject_contains"].strip()
        if interval:
            spec["interval_seconds"] = interval
    elif monthly_day is not None or weekly_day is not None:
        kind = "every"
        if monthly_day is not None:
            spec["monthly_day"] = int(monthly_day)
        else:
            spec["weekly_day"] = int(weekly_day)
        if (params.get("time_of_day") or "").strip():
            spec["time_of_day"] = params["time_of_day"].strip()
    elif interval:
        kind = "every"
        spec["interval_seconds"] = interval
    else:
        kind = "at"

    try:
        res = await _aio.to_thread(
            _fu.create_watch, room_id, user_id, kind, note,
            fire_at=fire_at_dt, delay_seconds=params.get("delay_seconds"), spec=spec,
        )
    except Exception as e:
        return {"success": False, "error": f"見張りの登録に失敗しました: {e}"}

    return {"success": bool(res.get("scheduled")), "id": res.get("id"),
            "kind": kind, "fire_at": res.get("fire_at"),
            "message": res.get("message", "")}


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


