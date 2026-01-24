"""
Tools - スキルとExecutorの橋渡し（Native Tool Use方式）

Anthropic Tool Use APIを使用して構造化された出力を実現。
プロセス（テキストブロック）と回答（respond_to_userツール）を100%分離。
"""

import re
import logging
from pathlib import Path
from typing import Dict, Any, List, Optional, Tuple
from dataclasses import dataclass, field

logger = logging.getLogger(__name__)


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
    skill_actions = {
        "ex-reservation": {
            "search": {
                "description": "新幹線を検索し、確認画面まで進む",
                "parameters": {
                    "departure": {"type": "string", "description": "出発駅（例: 東京）"},
                    "arrival": {"type": "string", "description": "到着駅（例: 新大阪）"},
                    "date": {"type": "string", "description": "乗車日（YYYY-MM-DD形式）"},
                    "time": {"type": "string", "description": "出発時刻（HH:MM形式）"},
                    "seat_position": {"type": "string", "description": "座席位置（窓側/通路側）", "optional": True},
                    "specific_seat": {"type": "string", "description": "特定座席（例: 5号車3番A席）", "optional": True},
                },
                "required": ["departure", "arrival", "date", "time"],
            },
            "cancel": {
                "description": "予約をキャンセル（払戻）",
                "parameters": {
                    "reservation_id": {"type": "string", "description": "予約番号", "optional": True},
                },
                "required": [],
            },
        },
        "amazon": {
            "search": {
                "description": "Amazon.co.jpで商品を検索",
                "parameters": {
                    "query": {"type": "string", "description": "検索キーワード"},
                    "target": {"type": "string", "description": "探している商品の詳細（サイズ、個数等）", "optional": True},
                },
                "required": ["query"],
            },
            "scroll": {
                "description": "ページをスクロールして商品を探す",
                "parameters": {
                    "direction": {"type": "string", "description": "スクロール方向（up/down）"},
                },
                "required": ["direction"],
            },
            "click_product": {
                "description": "商品をクリックして詳細ページを開く",
                "parameters": {
                    "x": {"type": "number", "description": "クリックするX座標"},
                    "y": {"type": "number", "description": "クリックするY座標"},
                    "asin": {"type": "string", "description": "Amazon商品ID（ASIN）", "optional": True},
                },
                "required": ["x", "y"],
            },
            "add_to_cart": {
                "description": "商品をカートに追加",
                "parameters": {
                    "quantity": {"type": "number", "description": "数量"},
                },
                "required": [],
            },
            "checkout": {
                "description": "レジに進む",
                "parameters": {},
                "required": [],
            },
            "purchase": {
                "description": "注文を確定",
                "parameters": {},
                "required": [],
            },
        },
        "developer": {
            "investigate": {
                "description": "エラーを調査して原因を特定",
                "parameters": {
                    "error_message": {"type": "string", "description": "エラーメッセージ"},
                    "context": {"type": "string", "description": "エラーが発生した状況", "optional": True},
                },
                "required": ["error_message"],
            },
            "fix": {
                "description": "特定されたエラーを修正",
                "parameters": {
                    "file_path": {"type": "string", "description": "修正対象ファイル"},
                    "fix_description": {"type": "string", "description": "修正内容"},
                },
                "required": ["file_path", "fix_description"],
            },
        },
    }

    # スキルのアクション定義を取得
    actions = skill_actions.get(skill.name, {})

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

    return tools


def get_all_skill_tools() -> List[Dict[str, Any]]:
    """
    全スキルのツール定義を取得

    Returns:
        全スキルのAnthropic Tool形式のリスト
    """
    SkillRegistry.load()
    all_tools = []

    for skill in SkillRegistry.list_all():
        tools = convert_skill_to_tools(skill)
        all_tools.extend(tools)

    return all_tools


def parse_tool_name(tool_name: str) -> Optional[Tuple[str, str]]:
    """
    ツール名からスキル名とアクションを抽出

    Args:
        tool_name: ツール名（例: ex_reservation_search）

    Returns:
        (skill_name, action) のタプル、または None
    """
    # respond_to_user は特別扱い
    if tool_name == "respond_to_user":
        return None

    # スキル名とアクションを分離
    # ex_reservation_search → ex-reservation, search
    # amazon_click_product → amazon, click_product

    known_skills = ["ex_reservation", "amazon", "developer"]

    for skill_prefix in known_skills:
        if tool_name.startswith(skill_prefix + "_"):
            action = tool_name[len(skill_prefix) + 1:]
            # ex_reservation → ex-reservation に戻す
            skill_name = skill_prefix.replace("_", "-")
            return (skill_name, action)

    return None

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
    skill_dir: Optional[Path] = None  # スキルディレクトリへのパス

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
            skill_dir=filepath.parent,  # SKILL.mdの親ディレクトリ
        )

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
    from app.executors.registry import find_executor, register_all_executors

    # Executorを登録（初回のみ実行される）
    register_all_executors()

    skill_name = tool_call["skill"]
    action = tool_call["action"]
    params = tool_call["params"]

    # リトライハンドラをインポート
    from app.agent.v2.retry_handler import with_session_retry

    print(f"[TOOL_DEBUG] execute_tool called: skill={skill_name}, action={action}")
    print(f"[TOOL_DEBUG] params keys: {list(params.keys())}")
    print(f"[TOOL_DEBUG] credentials passed: {credentials is not None}")

    # ★★★ 最初にスキルの存在を確認（認証チェックより先）★★★
    # 存在しないスキルに対して「認証が必要」と誤った応答を返さないため
    skill = SkillRegistry.get(skill_name)
    if not skill:
        print(f"[TOOL_DEBUG] Unknown skill: {skill_name}")
        return {
            "success": False,
            "error": f"スキル '{skill_name}' は存在しません。利用可能なスキル: amazon, ex-reservation, developer",
            "error_type": "unknown",
        }

    # 認証不要なアクション（これらはcredentials無しで実行可能）
    actions_not_requiring_auth = {
        "amazon": ["search", "scroll", "click_product"],  # 検索・スクロール・商品詳細はログイン不要
        "developer": ["investigate", "fix", "analyze"],  # 開発系は認証不要
    }

    # このアクションが認証不要かチェック
    skip_auth = action in actions_not_requiring_auth.get(skill_name, [])
    if skip_auth:
        print(f"[TOOL_DEBUG] Action '{action}' does not require authentication, skipping credential check")

    # スキル名からサービス名を決定（ハイフンをアンダースコアに変換）
    service_name = skill_name.replace("-", "_")  # ex-reservation → ex_reservation

    # 認証情報の取得優先順位:
    # 1. 引数で渡された credentials
    # 2. DBに保存済みの認証情報
    # 3. LLMがパラメータに含めた認証情報
    #
    # 重要: 認証不要アクションでも認証情報があれば渡す（ログイン済みブラウザ活用）
    #       認証不要アクションで認証情報がなくても、Executorに処理を委ねる
    if credentials is None:
        # まずDBから認証情報を取得
        from app.services.credentials_service import get_credentials_service
        creds_service = get_credentials_service()

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
            elif not skip_auth:
                # 認証が必要なアクションで認証情報が見つからない → ユーザーに要求
                # 重要: 認証不要アクション（skip_auth=True）の場合はExecutorに委ねる
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
                    "error_type": "credentials_required",
                    "credentials_required": True,
                    "service": service_name,
                    "display_name": format_info["display_name"],
                    "fields": format_info["fields"],
                    "labels": format_info["labels"],
                    "message": f"{format_info['display_name']}の認証情報が必要です。",
                }

    # Executorを取得（スキルは既に上で検証済み）
    # アクション名 → capability名のマッピング（registry登録名に合わせる）
    capability = action
    if action in ("book", "purchase", "reserve"):
        capability = "execute"
    elif action in ("cancel_reservation", "cancel"):
        capability = "cancel"
    elif action in ("list_reservations",):
        capability = "search"  # 予約一覧は検索機能で取得

    # Developer skillは全アクションをsearch経由で実行
    if skill.service_type == "developer":
        capability = "search"

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
        # Developer skill: actionをparamsに含めてsearchに渡す
        if skill.service_type == "developer":
            print(f"[TOOL_DEBUG] Developer skill detected, routing action={action} through search")
            params["action"] = action
            result = await executor.search(params=params, credentials=credentials, user_id=user_id)
            print(f"[TOOL_DEBUG] Developer result success: {result.success}")
            try:
                print(f"[TOOL_DEBUG] Developer result message: {result.message}")
            except UnicodeEncodeError:
                safe_msg = result.message.encode('cp932', errors='replace').decode('cp932')
                print(f"[TOOL_DEBUG] Developer result message: {safe_msg}")
            return result.to_dict()

        elif action == "search":
            # セッション切れ自動再試行ラッパー
            result = await with_session_retry(
                executor=executor,
                operation=lambda: executor.search(params=params, credentials=credentials, user_id=user_id),
                credentials=credentials,
                user_id=user_id,
            )
            print(f"[TOOL_DEBUG] Search result success: {result.success}")
            # Windows cp932対策: ¥記号等のUnicode文字を安全に出力
            try:
                print(f"[TOOL_DEBUG] Search result message: {result.message}")
            except UnicodeEncodeError:
                safe_msg = result.message.encode('cp932', errors='replace').decode('cp932')
                print(f"[TOOL_DEBUG] Search result message: {safe_msg}")
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
                try:
                    print(f"[TOOL_DEBUG] Purchase result: {result}")
                except UnicodeEncodeError:
                    print(f"[TOOL_DEBUG] Purchase result: (message contains special characters)")
                return result if isinstance(result, dict) else {"success": result.success, "message": result.message}
            else:
                print(f"[TOOL_DEBUG] No purchase method found")
                return {
                    "success": False,
                    "error": f"{skill_name} は購入機能に対応していません",
                }

        elif action in ("cancel", "cancel_reservation"):
            # キャンセル/払戻アクション（セッション切れ自動再試行ラッパー）
            print(f"[TOOL_DEBUG] Cancel action called, calling executor.cancel()...")
            result = await with_session_retry(
                executor=executor,
                operation=lambda: executor.cancel(params=params, credentials=credentials, user_id=user_id),
                credentials=credentials,
                user_id=user_id,
            )
            try:
                print(f"[TOOL_DEBUG] Cancel result: success={result.success}, message={result.message}")
            except UnicodeEncodeError:
                safe_msg = result.message.encode('cp932', errors='replace').decode('cp932')
                print(f"[TOOL_DEBUG] Cancel result: success={result.success}, message={safe_msg}")
            return {"success": result.success, "message": result.message}

        elif action == "add_to_cart":
            # Amazon カート追加アクション（セッション切れ自動再試行ラッパー）
            print(f"[TOOL_DEBUG] Add to cart action called")
            if hasattr(executor, "add_to_cart"):
                result = await with_session_retry(
                    executor=executor,
                    operation=lambda: executor.add_to_cart(params=params, credentials=credentials, user_id=user_id),
                    credentials=credentials,
                    user_id=user_id,
                )
                try:
                    print(f"[TOOL_DEBUG] Add to cart result: success={result.success}, message={result.message}")
                except UnicodeEncodeError:
                    safe_msg = result.message.encode('cp932', errors='replace').decode('cp932')
                    print(f"[TOOL_DEBUG] Add to cart result: success={result.success}, message={safe_msg}")
                return {"success": result.success, "message": result.message, "details": result.details}
            else:
                return {"success": False, "error": f"{skill_name} は add_to_cart に対応していません"}

        elif action == "order_history":
            # Amazon 注文履歴アクション（セッション切れ自動再試行ラッパー）
            print(f"[TOOL_DEBUG] Order history action called")
            if hasattr(executor, "order_history"):
                result = await with_session_retry(
                    executor=executor,
                    operation=lambda: executor.order_history(params=params, credentials=credentials, user_id=user_id),
                    credentials=credentials,
                    user_id=user_id,
                )
                try:
                    print(f"[TOOL_DEBUG] Order history result: success={result.success}, message={result.message}")
                except UnicodeEncodeError:
                    safe_msg = result.message.encode('cp932', errors='replace').decode('cp932')
                    print(f"[TOOL_DEBUG] Order history result: success={result.success}, message={safe_msg}")
                return {"success": result.success, "message": result.message, "details": result.details}
            else:
                return {"success": False, "error": f"{skill_name} は order_history に対応していません"}

        elif action == "list_reservations":
            # 予約一覧取得アクション（セッション切れ自動再試行ラッパー）
            print(f"[TOOL_DEBUG] List reservations action called")
            if hasattr(executor, "list_reservations"):
                result = await with_session_retry(
                    executor=executor,
                    operation=lambda: executor.list_reservations(params=params, credentials=credentials, user_id=user_id),
                    credentials=credentials,
                    user_id=user_id,
                )
                return result.to_dict() if hasattr(result, 'to_dict') else result
            else:
                # list_reservationsがない場合、searchで代用
                result = await with_session_retry(
                    executor=executor,
                    operation=lambda: executor.search(params={"action": "list"}, credentials=credentials, user_id=user_id),
                    credentials=credentials,
                    user_id=user_id,
                )
                return result.to_dict() if hasattr(result, 'to_dict') else result

        elif action == "checkout":
            # Amazon チェックアウトアクション（セッション切れ自動再試行ラッパー）
            print(f"[TOOL_DEBUG] Checkout action called")
            if hasattr(executor, "checkout"):
                result = await with_session_retry(
                    executor=executor,
                    operation=lambda: executor.checkout(params=params, credentials=credentials, user_id=user_id),
                    credentials=credentials,
                    user_id=user_id,
                )
                try:
                    print(f"[TOOL_DEBUG] Checkout result: success={result.success}, message={result.message}")
                except UnicodeEncodeError:
                    safe_msg = result.message.encode('cp932', errors='replace').decode('cp932')
                    print(f"[TOOL_DEBUG] Checkout result: success={result.success}, message={safe_msg}")
                return {"success": result.success, "message": result.message, "details": getattr(result, 'details', None)}
            else:
                return {"success": False, "error": f"{skill_name} は checkout に対応していません"}

        elif action == "scroll":
            # Amazon Vision: スクロールアクション
            print(f"[TOOL_DEBUG] Scroll action called")
            if hasattr(executor, "scroll"):
                result = await executor.scroll(params=params, credentials=credentials, user_id=user_id)
                try:
                    print(f"[TOOL_DEBUG] Scroll result: success={result.success}, message={result.message}")
                except UnicodeEncodeError:
                    safe_msg = result.message.encode('cp932', errors='replace').decode('cp932')
                    print(f"[TOOL_DEBUG] Scroll result: success={result.success}, message={safe_msg}")
                return {"success": result.success, "message": result.message, "details": getattr(result, 'details', None)}
            else:
                return {"success": False, "error": f"{skill_name} は scroll に対応していません"}

        elif action == "click_product":
            # Amazon Vision: 商品クリックアクション
            print(f"[TOOL_DEBUG] Click product action called")
            if hasattr(executor, "click_product"):
                result = await executor.click_product(params=params, credentials=credentials, user_id=user_id)
                try:
                    print(f"[TOOL_DEBUG] Click product result: success={result.success}, message={result.message}")
                except UnicodeEncodeError:
                    safe_msg = result.message.encode('cp932', errors='replace').decode('cp932')
                    print(f"[TOOL_DEBUG] Click product result: success={result.success}, message={safe_msg}")
                return {"success": result.success, "message": result.message, "details": getattr(result, 'details', None)}
            else:
                return {"success": False, "error": f"{skill_name} は click_product に対応していません"}

        else:
            return {"success": False, "error": f"Unknown action: {action}"}

    except Exception as e:
        logger.exception(f"Tool execution error: {e}")
        return {"success": False, "error": str(e)}


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


def format_tool_result(result: Dict[str, Any], skill_name: str, action: str) -> FormattedToolResult:
    """
    ツール実行結果をLLMに渡すフォーマットに変換

    第一原理に基づいた設計:
    1. 差分があれば必ず報告
    2. ブラウザの実際の状態を報告
    3. 失敗時は理由と代替案を提示
    4. 決定ポイントのスクリーンショットをVision形式で含める（ダンが見えるように）

    Args:
        result: execute_tool()の戻り値
        skill_name: スキル名
        action: アクション名

    Returns:
        FormattedToolResult: テキストメッセージと画像のリスト
    """
    images = []

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

    # その他の結果
    lines.append(result.get('message', '完了'))

    # 差分があれば追加
    deviation = result.get("deviation")
    if deviation and isinstance(deviation, dict) and deviation.get("has_deviation"):
        lines.append(f"\n【差分】{deviation.get('reason', '詳細不明')}")

    return FormattedToolResult(text="\n".join(lines), images=images)
