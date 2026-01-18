"""
Tools - スキルとExecutorの橋渡し（B方式: キーワード検出）

LLMが [TOOL: skill-name action] と宣言 → コードが検出してExecutorを呼び出し
"""

import re
import logging
from pathlib import Path
from typing import Dict, Any, List, Optional, Tuple
from dataclasses import dataclass, field

logger = logging.getLogger(__name__)

# スキルディレクトリ
SKILL_DIRECTORIES = [
    Path(__file__).parent / "skills",
    Path(__file__).parent.parent.parent.parent / ".claude" / "skills",
]


@dataclass
class Skill:
    """スキル定義"""
    name: str
    display_name: str
    description: str
    service_type: Optional[str] = None
    service_name: Optional[str] = None
    raw_content: str = ""

    @classmethod
    def from_file(cls, name: str, filepath: Path) -> "Skill":
        """SKILL.mdからスキルを読み込み"""
        content = filepath.read_text(encoding="utf-8")

        # タイトル抽出
        display_name = name
        title_match = re.search(r'^#\s+(.+)$', content, re.MULTILINE)
        if title_match:
            display_name = title_match.group(1).strip()

        # 説明抽出
        description = ""
        desc_match = re.search(r'##\s*サービス概要\s*\n(.+?)(?=\n##|\Z)', content, re.DOTALL)
        if desc_match:
            description = desc_match.group(1).strip()[:200]

        # サービスタイプ推測
        service_type, service_name = cls._guess_service(content, name)

        return cls(
            name=name,
            display_name=display_name,
            description=description,
            service_type=service_type,
            service_name=service_name,
            raw_content=content,
        )

    @staticmethod
    def _guess_service(content: str, name: str) -> Tuple[Optional[str], Optional[str]]:
        """コンテンツからサービスタイプを推測"""
        content_lower = content.lower()

        if "ex予約" in content or "新幹線" in content or name == "ex-reservation":
            return "train", "ex_reservation"
        elif "amazon" in content_lower:
            return "product", "amazon"
        elif "楽天" in content:
            return "product", "rakuten"
        elif "高速バス" in content:
            return "bus", "willer"
        elif "電話" in content or "音声" in content:
            return "voice", "phone"

        return None, None


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

        for skill_dir in SKILL_DIRECTORIES:
            if not skill_dir.exists():
                continue

            for skill_path in skill_dir.iterdir():
                if skill_path.is_dir():
                    skill_file = skill_path / "SKILL.md"
                    if skill_file.exists():
                        try:
                            skill = Skill.from_file(skill_path.name, skill_file)
                            instance._skills[skill.name] = skill
                            logger.info(f"Loaded skill: {skill.name}")
                        except Exception as e:
                            logger.warning(f"Failed to load skill {skill_path.name}: {e}")

        instance._loaded = True

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

    print(f"[PARSE_DEBUG] Found tool call: {skill_name} {action}")

    # パラメータを抽出（key: value 形式）
    params = {}
    tool_pos = match.end()
    remaining = response[tool_pos:]

    # 次の[TOOL:]または[STATE:]または空行2つまでをパラメータとして扱う
    param_section = re.split(r'\n\n|\[TOOL:|\[STATE:', remaining)[0]

    print(f"[PARSE_DEBUG] Param section:\n{param_section[:300]}...")

    for line in param_section.split('\n'):
        line = line.strip()
        if ':' in line and not line.startswith('['):
            key, value = line.split(':', 1)
            key = key.strip().lower().replace(' ', '_')
            value = value.strip()
            if key and value:
                params[key] = value
                print(f"[PARSE_DEBUG] Extracted param: {key}={value[:20] if len(value) > 20 else value}")

    print(f"[PARSE_DEBUG] Total params extracted: {len(params)}")

    return {
        "skill": skill_name,
        "action": action,
        "params": params,
    }


async def execute_tool(
    tool_call: Dict[str, Any],
    user_id: str,
    credentials: Optional[Dict[str, str]] = None,
) -> Dict[str, Any]:
    """
    ツールを実行

    Args:
        tool_call: parse_tool_call()の戻り値
        user_id: ユーザーID
        credentials: 認証情報

    Returns:
        実行結果
    """
    from app.executors.registry import find_executor

    skill_name = tool_call["skill"]
    action = tool_call["action"]
    params = tool_call["params"]

    print(f"[TOOL_DEBUG] execute_tool called: skill={skill_name}, action={action}")
    print(f"[TOOL_DEBUG] params keys: {list(params.keys())}")
    print(f"[TOOL_DEBUG] credentials passed: {credentials is not None}")

    # 認証情報の取得優先順位:
    # 1. 引数で渡された credentials
    # 2. DBに保存済みの認証情報
    # 3. LLMがパラメータに含めた認証情報
    if credentials is None:
        # まずDBから認証情報を取得
        from app.services.credentials_service import get_credentials_service
        creds_service = get_credentials_service()

        # スキル名からサービス名を決定
        service_name = skill_name  # ex_reservation, amazon など
        stored_creds = await creds_service.get_credential(user_id, service_name)

        if stored_creds:
            print(f"[TOOL_DEBUG] Found stored credentials for {service_name}")
            # EX予約は member_id/password、他は username/password など
            if "member_id" in stored_creds:
                credentials = {
                    "member_id": stored_creds["member_id"],
                    "password": stored_creds["password"],
                }
            elif "username" in stored_creds:
                credentials = {
                    "username": stored_creds["username"],
                    "password": stored_creds["password"],
                }
            elif "email" in stored_creds:
                credentials = {
                    "email": stored_creds["email"],
                    "password": stored_creds["password"],
                }
            print(f"[TOOL_DEBUG] Using stored credentials: keys={list(credentials.keys())}")
        else:
            print(f"[TOOL_DEBUG] No stored credentials for {service_name}, checking params...")

            # DBに無ければパラメータから抽出（LLMがパラメータに含めた場合）
            cred_keys = ["user_id", "member_id", "login_id", "id", "username"]
            pass_keys = ["password", "pass", "pw"]

            extracted_id = None
            extracted_pass = None

            for key in cred_keys:
                if key in params:
                    extracted_id = params.pop(key)
                    print(f"[TOOL_DEBUG] Found credential ID with key: {key}")
                    break

            for key in pass_keys:
                if key in params:
                    extracted_pass = params.pop(key)
                    print(f"[TOOL_DEBUG] Found password with key: {key}")
                    break

            if extracted_id and extracted_pass:
                # EX予約は member_id を使用
                credentials = {"member_id": extracted_id, "password": extracted_pass}
                print(f"[TOOL_DEBUG] Extracted credentials: member_id={extracted_id[:3]}***")

                # 認証情報をDBに保存（次回から自動使用）
                await creds_service.save_credential(
                    user_id=user_id,
                    service=service_name,
                    credentials=credentials,
                    credential_type="login",
                )
                print(f"[TOOL_DEBUG] Saved credentials to DB for future use")
            else:
                # 認証情報が見つからない → ユーザーに要求
                print(f"[TOOL_DEBUG] Credentials not found, requesting from user")

                # サービスごとの認証情報フォーマット
                credential_formats = {
                    "ex_reservation": {
                        "display_name": "EX予約（SmartEX）",
                        "fields": ["member_id", "password"],
                        "labels": {"member_id": "会員ID", "password": "パスワード"},
                    },
                    "amazon": {
                        "display_name": "Amazon",
                        "fields": ["email", "password"],
                        "labels": {"email": "メールアドレス", "password": "パスワード"},
                    },
                }

                format_info = credential_formats.get(service_name, {
                    "display_name": service_name,
                    "fields": ["username", "password"],
                    "labels": {"username": "ユーザー名", "password": "パスワード"},
                })

                return {
                    "success": False,
                    "credentials_required": True,
                    "service": service_name,
                    "display_name": format_info["display_name"],
                    "fields": format_info["fields"],
                    "labels": format_info["labels"],
                    "message": f"{format_info['display_name']}の認証情報が必要です。",
                }

    # スキルを取得
    skill = SkillRegistry.get(skill_name)
    if not skill:
        return {
            "success": False,
            "error": f"Unknown skill: {skill_name}",
        }

    # Executorを取得
    # アクション名 → capability名のマッピング（registry登録名に合わせる）
    capability = action
    if action in ("book", "purchase", "reserve"):
        capability = "execute"
    elif action in ("cancel_reservation", "cancel"):
        capability = "cancel"
    elif action in ("list_reservations",):
        capability = "search"  # 予約一覧は検索機能で取得

    print(f"[TOOL_DEBUG] Looking for executor: service_type={skill.service_type}, service_name={skill.service_name}, capability={capability}")

    executor = find_executor(
        service_type=skill.service_type,
        service_name=skill.service_name,
        capability=capability,
    )

    print(f"[TOOL_DEBUG] find_executor returned: {executor}")

    if not executor:
        return {
            "success": False,
            "error": f"No executor for {skill.service_type}/{skill.service_name}",
        }

    print(f"[TOOL_DEBUG] Executing: {skill_name} {action}")
    print(f"[TOOL_DEBUG] Final params: {params}")
    print(f"[TOOL_DEBUG] Final credentials: {credentials is not None}")
    if credentials:
        print(f"[TOOL_DEBUG] Credentials keys: {list(credentials.keys())}")

    try:
        if action == "search":
            result = await executor.search(params=params, credentials=credentials, user_id=user_id)
            print(f"[TOOL_DEBUG] Search result success: {result.success}")
            print(f"[TOOL_DEBUG] Search result message: {result.message}")
            return result.to_dict()

        elif action in ("book", "execute", "purchase", "reserve"):
            # 購入/予約確定アクション
            # search結果から確認画面まで進んでいる状態で、購入を実行
            print(f"[TOOL_DEBUG] Book/Execute/Purchase action called")
            print(f"[TOOL_DEBUG] Has purchase method: {hasattr(executor, 'purchase')}")
            if hasattr(executor, "purchase"):
                # EXReservationExecutor等の購入メソッド
                print(f"[TOOL_DEBUG] Calling executor.purchase()...")
                result = await executor.purchase(params=params, credentials=credentials, user_id=user_id)
                print(f"[TOOL_DEBUG] Purchase result: {result}")
                return result if isinstance(result, dict) else {"success": result.success, "message": result.message}
            else:
                print(f"[TOOL_DEBUG] No purchase method found")
                return {
                    "success": False,
                    "error": f"{skill_name} は購入機能に対応していません",
                }

        elif action in ("cancel", "cancel_reservation"):
            # キャンセル/払戻アクション
            print(f"[TOOL_DEBUG] Cancel action called, calling executor.cancel()...")
            result = await executor.cancel(params=params, credentials=credentials, user_id=user_id)
            print(f"[TOOL_DEBUG] Cancel result: success={result.success}, message={result.message}")
            return {"success": result.success, "message": result.message}

        elif action == "list_reservations":
            # 予約一覧取得アクション
            print(f"[TOOL_DEBUG] List reservations action called")
            if hasattr(executor, "list_reservations"):
                result = await executor.list_reservations(params=params, credentials=credentials, user_id=user_id)
                return result.to_dict() if hasattr(result, 'to_dict') else result
            else:
                # list_reservationsがない場合、searchで代用
                result = await executor.search(params={"action": "list"}, credentials=credentials, user_id=user_id)
                return result.to_dict() if hasattr(result, 'to_dict') else result

        else:
            return {"success": False, "error": f"Unknown action: {action}"}

    except Exception as e:
        logger.exception(f"Tool execution error: {e}")
        return {"success": False, "error": str(e)}


def format_tool_result(result: Dict[str, Any], skill_name: str, action: str) -> str:
    """
    ツール実行結果をLLMに渡すフォーマットに変換

    Args:
        result: execute_tool()の戻り値
        skill_name: スキル名
        action: アクション名

    Returns:
        LLMに追加するメッセージ
    """
    if not result.get("success", False):
        # ExecutorSearchResult は 'message' を使用、その他は 'error' を使用
        error_msg = result.get("message") or result.get("error", "不明なエラー")
        return f"[TOOL RESULT: {skill_name} {action}]\nエラー: {error_msg}"

    # 検索結果の場合
    if action == "search" and "options" in result:
        options = result["options"]
        if not options:
            return f"[TOOL RESULT: {skill_name} {action}]\n該当する結果がありませんでした。"

        lines = [f"[TOOL RESULT: {skill_name} {action}]", f"{len(options)}件見つかりました:\n"]

        for i, opt in enumerate(options[:5], 1):  # 最大5件
            lines.append(f"{i}. {opt.get('title', '不明')}")
            if opt.get("description"):
                lines.append(f"   {opt['description']}")
            if opt.get("price"):
                lines.append(f"   料金: ¥{opt['price']:,}")
            lines.append("")

        return "\n".join(lines)

    # その他の結果
    return f"[TOOL RESULT: {skill_name} {action}]\n{result.get('message', '完了')}"
