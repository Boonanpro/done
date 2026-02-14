"""
AgentRunner - 会話ループのメインロジック（Native Tool Use方式）

Messages配列を維持しながらLLMと対話する。
状態機械なし - LLMが自律的に判断する。

アーキテクチャ:
- ブートストラップファイル: ~/.dan/workspace/ からペルソナ・ルールを読み込み
- Native Tool Use: LLMがツールを呼び出して操作を実行
- テキスト出力がそのままユーザーへの返答になる
- 自己学習: ダンがワークスペースファイルを読み書きして学習
"""

import re
import logging
import asyncio
from typing import Optional, Dict, Any, Callable, Awaitable, List
from pathlib import Path

import anthropic

from app.agent.v2.session import Session, get_session_store
from app.agent.v2.tools import (
    execute_tool, format_tool_result, FormattedToolResult, SkillRegistry,
    get_all_skill_tools, parse_tool_name,
)
from app.config import settings

logger = logging.getLogger(__name__)


def safe_print(msg: str) -> None:
    """Windows cp932でも安全にprint（エンコードできない文字は置換）"""
    try:
        print(msg)
    except UnicodeEncodeError:
        # エンコードできない文字を ? に置換して出力
        safe_msg = msg.encode('cp932', errors='replace').decode('cp932')
        print(safe_msg)


# コアプロンプト（不変）
CORE_PROMPT = "You are Dan, a personal AI assistant."

# ツール実行の最大ループ回数（安全弁として30回を超えたら強制終了）
MAX_TOOL_LOOPS = 30

# 音声アナウンス: ツール種別ごとのフォールバックメッセージ
# Claude が reasoning_text を出力している場合はそちらを優先する
VOICE_ANNOUNCEMENTS: Dict[str, str] = {
    "_browser": "サイトを確認しますね",
    "_check_skill": "確認しますね",
    "_deep_research": "詳しく調べてみますね",
    "_jina": "ページを読んでいます",
    "_exec_code": "コードを実行しています",
}

# プロジェクトコンテキストテンプレート
PROJECT_CONTEXT_TEMPLATE = """## プロジェクトモード

これはプロジェクト専用チャットです。通常の雑談ではありません。

### プロジェクト情報
- タイトル: {title}
- 説明: {description}
- ステータス: {status}

### プロジェクトモードの行動指針
1. 仮説ドリブン: まず仮説を立て、それを検証するために調査する。調査結果から結論を導く
2. 結論ファースト: 社長（ユーザー）への報告は常に結論から。「何をする・結果どうなる・社長がやること」を最初に伝える
3. 自律実行: 下記のゾーン判断に従い自律的に実行する
4. 障害自力解決: 障害に遭遇したら自分のツール（bash, write_file, browser等）で解決を試みる
5. 反復改善: フィードバックを受けて計画を差分で更新
6. 実行可能性重視: 抽象的なアドバイスではなく具体的なステップ

### ゾーン判断（各操作の実行前に必ず判定）
- **Green（即実行）**: 検索、閲覧、ツール作成、bashコマンド、ファイル操作、パッケージインストール
- **Yellow（実行→報告）**: フォーム入力（非個人情報）、カート追加、設定変更
- **Red（確認→実行）**: 個人情報入力、購入確定、取消不可操作 → 必ずユーザーに内容を示して確認を待つ

#### Red判定の具体例（推測で入力してはいけない）
- 氏名・住所・電話番号・生年月日・メールアドレスの入力（※USER.mdに保存済みの情報はYellow扱い＝そのまま使ってよい）
- クレジットカード情報の入力
- 「注文を確定する」「購入する」ボタンのクリック
- アカウント削除、解約、退会の実行

#### 障害対応（「できません」と止まることは禁止）
- エラー → まず自分のツール（bash, browser, exec_code等）で解決を試みる
- OTP/2段階認証 → 「認証コードを教えてください」とユーザーに聞く
- CAPTCHA → スクリーンショットを見せて「この画像の文字を教えてください」と聞く
- ログイン要求 → 「ログインが必要です。ID/パスワードを教えてください」と聞く
- 必ず代替案を提示するか、ユーザーに助けを求めること"""

# コンパクション設定
COMPACTION_THRESHOLD = 80000  # この文字数を超えたらコンパクション発動
COMPACTION_KEEP_RECENT = 10   # コンパクション時に残す最新メッセージ数

# 使用するモデル
MODEL_DEFAULT = "claude-sonnet-4-5-20250929"      # 日常チャット（$3/$15）
MODEL_HEAVY = "claude-opus-4-6"                   # プロジェクト実行（$5/$25）

# ============================================
# Native Tool Use: ツール定義
# ============================================
# LLMのテキスト出力がそのままユーザーへの返答になる


def get_core_prompt() -> str:
    """コアプロンプトを返す"""
    return CORE_PROMPT


# ブートストラップファイルのディレクトリ
WORKSPACE_DIR = Path.home() / ".dan" / "workspace"


def load_bootstrap_file(filename: str) -> str:
    """ブートストラップファイルを読み込む（~/.dan/workspace/）"""
    filepath = WORKSPACE_DIR / filename
    if filepath.exists():
        try:
            return filepath.read_text(encoding="utf-8")
        except Exception as e:
            logger.warning(f"Failed to load bootstrap file {filename}: {e}")
    return ""


def load_all_bootstrap_files() -> str:
    """全ブートストラップファイルを読み込んで結合（順番重要: RULES.md を最後に）"""
    parts = []

    # 1. USER.md - ユーザー情報
    user = load_bootstrap_file("USER.md")
    if user:
        parts.append(f"## ユーザー情報\n\n{user}")

    # 2. MEMORY.md - 長期記憶
    memory = load_bootstrap_file("MEMORY.md")
    if memory:
        parts.append(f"## 長期記憶\n\n{memory}")

    # 3. 直近の日別メモリ（yesterday + today）
    from datetime import datetime, timedelta
    today = datetime.now().strftime("%Y-%m-%d")
    yesterday = (datetime.now() - timedelta(days=1)).strftime("%Y-%m-%d")
    for date_str in [yesterday, today]:
        daily = load_bootstrap_file(f"memory/{date_str}.md")
        if daily:
            # サイズ上限: 1ファイルあたり最大4000文字（末尾=最新部分を優先）
            if len(daily) > 4000:
                daily = daily[-4000:]
            parts.append(f"## 会話ログ ({date_str})\n\n{daily}")

    # 4. SOUL.md - ペルソナ
    soul = load_bootstrap_file("SOUL.md")
    if soul:
        parts.append(f"## ペルソナ\n\n{soul}")

    # 5. RULES.md - 運用ルール（最後に配置 = recency bias で効きやすい）
    rules = load_bootstrap_file("RULES.md")
    if rules:
        parts.append(rules)  # RULES.md は既にタイトル含むのでそのまま

    if parts:
        return "\n\n---\n\n".join(parts)
    return ""


class AgentRunner:
    """
    会話ループを実行するクラス

    使い方:
        runner = AgentRunner(session)
        result = await runner.process_message("新幹線を予約したい")
    """

    def __init__(
        self,
        session: Session,
        on_reasoning_step: Optional[Callable[[str], Awaitable[None]]] = None,
        on_voice_announcement: Optional[Callable[[str], Awaitable[None]]] = None,
    ):
        self.session = session
        self._on_reasoning_step = on_reasoning_step
        self._on_voice_announcement = on_voice_announcement

        # LLMクライアント
        if settings.ANTHROPIC_API_KEY:
            self.llm_client = anthropic.AsyncAnthropic(
                api_key=settings.ANTHROPIC_API_KEY
            )
        else:
            self.llm_client = None
            logger.warning("ANTHROPIC_API_KEY not set")

    async def process_message(
        self,
        user_message: str,
        credentials: Optional[Dict[str, str]] = None,
    ) -> Dict[str, Any]:
        """
        ユーザーメッセージを処理（Native Tool Use方式）

        Args:
            user_message: ユーザーのメッセージ
            credentials: 認証情報（オプション）

        Returns:
            {
                "response": ユーザーへの応答（テキストブロックから抽出）,
                "state": 現在の状態,
                "reasoning_steps": 推論過程,
                "tool_results": ツール実行結果（あれば）,
            }
        """
        try:
            print(f"[RUNNER_DEBUG] Starting process_message for user {self.session.user_id}")
            safe_print(f"[RUNNER_DEBUG] Message: {user_message[:50]}...")

            # 現在のセッションIDをコンテキストに設定（キャンセルチェック用）
            from app.services.cancellation import CancellationRegistry
            CancellationRegistry.set_current_session(self.session.session_id)

            # 0.5. Deterministic skill lookup routing (bypass LLM)
            skill_lookup_response = self._maybe_handle_skill_lookup(user_message)
            if skill_lookup_response:
                self.session.clear_reasoning_steps()
                self.session.add_user_message(user_message)
                self.session.add_assistant_message(skill_lookup_response)
                store = get_session_store()
                await store.save(self.session)
                return {
                    "response": skill_lookup_response,
                    "state": self.session.current_state.value,
                    "reasoning_steps": self.session.reasoning_steps,
                }

            # 1. 推論ステップをクリア（新しいターン）
            self.session.clear_reasoning_steps()

            # 2. ユーザーメッセージを追加
            self.session.add_user_message(user_message)

            # 3. LLM呼び出し→ツール実行ループ（Native Tool Use）
            tool_results = []
            user_response = None
            print(f"[RUNNER_DEBUG] Starting LLM loop, state: {self.session.current_state.value}")

            for loop_count in range(MAX_TOOL_LOOPS + 1):
                # キャンセルチェック
                from app.services.cancellation import CancellationRegistry
                if CancellationRegistry.is_cancelled(self.session.session_id):
                    logger.info(f"Session {self.session.session_id} cancelled at loop start")
                    return {
                        "response": "処理が中断されました。",
                        "state": self.session.current_state.value,
                        "reasoning_steps": self.session.reasoning_steps,
                        "cancelled": True,
                    }

                print(f"[RUNNER_DEBUG] Calling LLM with tools (loop {loop_count})...")

                # LLMをTool Use APIで呼び出し
                response = await self._call_llm_with_tools()

                # レスポンスを処理
                parsed = await self._process_llm_response(response)

                # アシスタントメッセージを追加
                self.session.add_assistant_message_from_response(response)

                # ユーザー回答を抽出
                if parsed["user_response"]:
                    user_response = parsed["user_response"]
                # ツール呼び出しがない、または最大ループに達した場合は終了
                if not parsed["tool_calls"] or loop_count >= MAX_TOOL_LOOPS:
                    # ツールなしの場合でもreasoning_textがあればSSEに流す
                    if parsed["reasoning_text"] and self._on_reasoning_step:
                        await self._on_reasoning_step(parsed["reasoning_text"])
                    print(f"[RUNNER_DEBUG] No more tool calls or max loops reached")
                    break

                # ツールを実行
                reasoning_text = parsed["reasoning_text"] or ""
                first_tool = True

                # 音声アナウンス: 最初のツール実行前にユーザー向けメッセージを送出
                if self._on_voice_announcement and parsed["tool_calls"]:
                    first_skill = parsed["tool_calls"][0]["skill"]
                    if reasoning_text:
                        # Claude が出力したテキストの最初の一文を使う
                        voice_text = self._extract_first_sentence(reasoning_text)
                    else:
                        # フォールバック: ツール種別から定型メッセージ
                        voice_text = VOICE_ANNOUNCEMENTS.get(first_skill, "少々お待ちください")
                    await self._on_voice_announcement(voice_text)

                for tool_call in parsed["tool_calls"]:
                    # ツール実行前にもキャンセルチェック
                    if CancellationRegistry.is_cancelled(self.session.session_id):
                        logger.info(f"Session {self.session.session_id} cancelled before tool execution")
                        # 未実行の操作にダミー結果を挿入（ペア崩れ防止）
                        for remaining in parsed["tool_calls"]:
                            self.session.add_tool_result(
                                remaining["tool_use_id"],
                                "[操作が中断されました]",
                            )
                        return {
                            "response": "処理が中断されました。",
                            "state": self.session.current_state.value,
                            "reasoning_steps": self.session.reasoning_steps,
                            "cancelled": True,
                        }

                    tool_use_id = tool_call["tool_use_id"]
                    skill_name = tool_call["skill"]
                    action = tool_call["action"]
                    params = tool_call["params"]

                    # ツール名を整形（browser_open, check_skill等）
                    if skill_name.startswith("_"):
                        tool_label = f"{skill_name[1:]}_{action}" if action else skill_name[1:]
                    else:
                        tool_label = f"{skill_name}_{action}" if action else skill_name

                    # check_skillはスキル名もログに含める
                    if skill_name == "_check_skill":
                        log_msg = f"Executing tool: check_skill({params.get('skill_name', '?')})"
                    else:
                        log_msg = f"Executing tool: {skill_name} {action}"
                    logger.info(log_msg)
                    # ツール実行ログをファイルにも記録
                    try:
                        from datetime import datetime
                        from pathlib import Path
                        _log_path = Path(__file__).parent.parent.parent.parent / "logs" / "tool_calls.log"
                        with open(_log_path, "a", encoding="utf-8") as f:
                            f.write(f"[{datetime.now().isoformat()}] {log_msg} params={params}\n")
                    except Exception:
                        pass
                    # SSE表示: 「LLMの独り言 ツール名」or フォールバック「ツール名」
                    if self._on_reasoning_step:
                        if first_tool and reasoning_text:
                            await self._on_reasoning_step(f"{reasoning_text} {tool_label}")
                        else:
                            await self._on_reasoning_step(tool_label)
                    first_tool = False

                    result = await execute_tool(
                        tool_call=tool_call,
                        user_id=self.session.user_id,
                        credentials=credentials,
                        session_id=self.session.session_id,
                    )

                    # エラータイプに基づいて処理を分岐
                    error_type = result.get("error_type")

                    # 認証情報が必要な場合: tool_resultを追加してLLMに処理を任せる
                    # LLMが自然な言葉でユーザーに聞き、save_credentialsで保存する
                    if result.get("credentials_required") or error_type in (
                        "credentials_required",
                        "credentials_invalid",
                        "session_expired",
                    ):
                        service_name = result.get("service") or result.get("service_name") or skill_name or "unknown"
                        display_name = result.get("display_name") or result.get("service_display_name") or service_name
                        self.session.add_tool_result(
                            tool_use_id=tool_use_id,
                            content=f"認証情報が必要です: {display_name}。ユーザーにログイン情報を聞いて、教えてもらったら save_credentials ツールで保存してください。"
                        )
                        # returnせずに続行し、LLMに応答を生成させる

                    # エラーログ
                    if error_type and not result.get("success"):
                        logger.info(f"Tool error: type={error_type}, recoverable={result.get('recoverable', True)}")

                    tool_results.append({
                        "tool": tool_call,
                        "result": result,
                    })

                    # ブラウザ操作のログを記録（学習システム用）
                    if skill_name == "_browser":
                        try:
                            from app.services import learning_service
                            from urllib.parse import urlparse

                            # 結果テキストからページ情報と要素情報を抽出
                            url = params.get("url", "")
                            page_url = ""
                            page_title = ""
                            element_tag = ""
                            element_text = ""
                            ref = params.get("ref", "")

                            for block in result.get("content", []):
                                if not (isinstance(block, dict) and block.get("type") == "text"):
                                    continue
                                for line in block["text"].split("\n"):
                                    if line.startswith("URL: "):
                                        page_url = line[5:].strip()
                                    elif line.startswith("タイトル: "):
                                        page_title = line[len("タイトル: "):].strip()
                                    elif ref and line.strip().startswith(f"{ref}:"):
                                        # "@e3: [button] カートに入れる" から要素情報を抽出
                                        after_ref = line.split(":", 1)[1].strip()
                                        if after_ref.startswith("["):
                                            bracket_end = after_ref.find("]")
                                            if bracket_end > 0:
                                                element_tag = after_ref[1:bracket_end]
                                                element_text = after_ref[bracket_end + 1:].strip()[:100]
                                break

                            site = None
                            if page_url:
                                site = urlparse(page_url).netloc
                            elif url:
                                site = urlparse(url).netloc

                            await learning_service.record_action_event(
                                session_id=self.session.session_id,
                                action_name=f"browser_{action}",
                                technical_success=result.get("success", False),
                                context={
                                    "page_url": page_url,
                                    "page_title": page_title,
                                    "element_tag": element_tag,
                                    "element_text": element_text,
                                },
                                user_id=self.session.user_id,
                                site=site,
                                skill_name="_browser",
                                action_params=params,
                            )
                        except Exception as e:
                            logger.debug(f"Failed to record browser event: {e}")

                    # ツール結果をtool_result形式でメッセージに追加
                    # Progressive Disclosure: スキル情報を渡してマニュアルを注入
                    skill = SkillRegistry.get(skill_name)
                    formatted = format_tool_result(result, skill_name, action, skill=skill)
                    self.session.add_tool_result(
                        tool_use_id=tool_use_id,
                        content=formatted.text,
                        images=formatted.images if formatted.has_images() else None,
                    )

                    if self._on_reasoning_step:
                        message = result.get("message", "")
                        if not result.get("success"):
                            # エラー時だけ表示
                            await self._on_reasoning_step(message or f"{skill_name} {action} 失敗")
                        elif message and len(message) < 100:
                            # 具体的な結果メッセージがあればそのまま表示
                            await self._on_reasoning_step(message)

            # 4. セッションを保存
            store = get_session_store()
            await store.save(self.session)

            # 5. コンパクションチェック
            await self._check_and_compact()

            # フォールバック: テキスト出力がなかった場合
            if not user_response:
                logger.warning("No text response from LLM, using fallback")
                user_response = "処理が完了しました。"

            # ブラウザセッションIDを抽出（スキル化用）
            # browser_* ツールが使われた場合、session_id をブラウザセッションIDとして返す
            browser_session_id = None
            created_project_id = None
            for tool_result in tool_results:
                tool_call_data = tool_result.get("tool", {})
                if tool_call_data.get("skill") == "_browser":
                    browser_session_id = self.session.session_id
                if tool_call_data.get("skill") == "_create_project":
                    result_data = tool_result.get("result", {})
                    if result_data.get("success"):
                        created_project_id = result_data.get("project_id")

            return {
                "response": user_response,
                "state": self.session.current_state.value,
                "reasoning_steps": self.session.reasoning_steps,
                "tool_results": tool_results,
                "browser_session_id": browser_session_id,  # スキル化用
                "created_project_id": created_project_id,
            }

        except Exception as e:
            import traceback
            from app.services.cancellation import CancelledError

            # キャンセルされた場合は正常終了として扱う
            if isinstance(e, CancelledError):
                logger.info(f"Session {self.session.session_id} cancelled")
                return {
                    "response": "処理がキャンセルされました。",
                    "state": self.session.current_state.value,
                    "reasoning_steps": self.session.reasoning_steps,
                    "cancelled": True,
                }

            error_details = traceback.format_exc()
            print(f"[RUNNER_ERROR] Exception in process_message:")
            print(f"[RUNNER_ERROR] {error_details}")
            logger.exception(f"Error in process_message: {e}")

            # ★★★ 重要: エラー発生時はキャッシュをクリア ★★★
            # メモリ上のセッションが不整合な状態（tool_useあり、tool_resultなし）に
            # なっている可能性があるため、キャッシュから削除して次回DBから再読み込み
            store = get_session_store()
            store.invalidate_cache(self.session.session_id, self.session.user_id)
            logger.info(f"Session cache invalidated due to error: {self.session.session_id}")

            return {
                "response": "申し訳ありません。エラーが発生しました。",
                "state": self.session.current_state.value,
                "reasoning_steps": self.session.reasoning_steps,
                "error": str(e),
            }
        finally:
            # セッションIDをクリア
            from app.services.cancellation import CancellationRegistry
            CancellationRegistry.set_current_session(None)

    def _build_system_prompt(self) -> str:
        """
        システムプロンプトを構築

        順番（recency bias 考慮: 重要なルールは最後）:
        1. コアID
        2. 現在の日時
        3. 利用可能なツール一覧
        4. 利用可能なスキル一覧
        5. ブートストラップファイル（USER → MEMORY → yesterday/today → SOUL → RULES）
        """
        print("[RUNNER_DEBUG] Building system prompt...")
        parts = []

        # 1. コアプロンプト
        parts.append(get_core_prompt())
        print(f"[RUNNER_DEBUG] Core prompt added")

        # 2. 現在日時
        from datetime import datetime
        now = datetime.now()
        weekdays = ['月', '火', '水', '木', '金', '土', '日']
        datetime_section = f"""## 現在の日時
- 今日: {now.strftime('%Y年%m月%d日')}（{weekdays[now.weekday()]}曜日）
- 現在時刻: {now.strftime('%H:%M')}"""
        parts.append(datetime_section)

        # 2.5. プロジェクトコンテキスト（プロジェクトチャットの場合のみ）
        project_context = self._get_project_context()
        if project_context:
            parts.append(project_context)
            print(f"[RUNNER_DEBUG] Project context injected")

        # 3. 利用可能なツール一覧
        tools_section = self._build_tools_list_section()
        if tools_section:
            parts.append(tools_section)

        # 4. 利用可能なスキル一覧
        skill_list = self._build_skill_list_section()
        if skill_list:
            parts.append(skill_list)

        # 5. ブートストラップファイル（RULES.md が最後に来る）
        bootstrap = load_all_bootstrap_files()
        if bootstrap:
            parts.append(bootstrap)
            print(f"[RUNNER_DEBUG] Bootstrap files loaded: {len(bootstrap)} chars")

        system = "\n\n---\n\n".join(parts)
        print(f"[RUNNER_DEBUG] Total system prompt: {len(system)} chars")
        return system

    def _build_tools_list_section(self) -> str:
        """利用可能なツール一覧を構築"""
        tools = self._get_tools()
        lines = ["## 利用可能なツール"]
        for tool in tools:
            # サーバーサイドツール（web_search等）はtype fieldで識別
            if tool.get("type", "").startswith("web_search"):
                lines.append(f"- `web_search`: Web検索（自動実行。回答に最新情報が必要な場合にClaudeが自動で使用）")
                continue
            name = tool.get("name", "")
            desc = tool.get("description", "").split("\n")[0]  # 1行目のみ
            lines.append(f"- `{name}`: {desc}")
        lines.append("- `create_project`: ユーザーの依頼をプロジェクトとして登録（複数ステップのタスクに使用）")
        lines.append("")
        lines.append("### コード操作のツール選択ルール（必須）")
        lines.append("- ファイルを探す → `bash`（例: `find D:/done/frontend -name '*.tsx'`）")
        lines.append("- ファイル内容を検索 → `bash`（例: `grep -rn 'useState' D:/done/frontend/src/`）")
        lines.append("- ファイルを読む → `read_file`")
        lines.append("- ファイルを書く/編集 → `write_file` / `edit_file`")
        return "\n".join(lines)

    def _build_skill_list_section(self) -> str:
        """スキル一覧（description のみ）"""
        skills = SkillRegistry.list_all()
        if not skills:
            return ""

        lines = ["## 利用可能なスキル"]
        lines.append("")
        for skill in skills:
            lines.append(f"- `{skill.name}`: {skill.description}")
        lines.append("")
        lines.append("### スキル使用ルール（必須）")
        lines.append("")
        lines.append("1. ユーザーの依頼が上記スキルに該当する場合、**必ず最初に `check_skill` ツールで手順書を取得すること**。手順書なしで自己流で操作してはいけない。")
        lines.append("2. 手順書を取得したら、その手順に従って `browser_open`/`browser_click`/`browser_type` 等で操作する。")
        lines.append("3. 該当するスキルがない場合は、自分の判断でブラウザ操作して構わない。")
        return "\n".join(lines)


    def _get_project_context(self) -> Optional[str]:
        """session_idでprojectsテーブルを引き、プロジェクトコンテキストを返す"""
        try:
            from app.services.project_service import ProjectService
            service = ProjectService()
            # synchronous Supabase call (no await needed)
            result = (
                service.supabase.table("projects")
                .select("title, description, status")
                .eq("room_id", self.session.session_id)
                .execute()
            )
            if result.data:
                project = result.data[0]
                return PROJECT_CONTEXT_TEMPLATE.format(
                    title=project.get("title", ""),
                    description=project.get("description", "") or "(なし)",
                    status=project.get("status", "planning"),
                )
        except Exception as e:
            logger.warning(f"Failed to get project context: {e}")
        return None

    def _normalize_skill_token(self, text: str) -> str:
        """Normalize skill tokens for lookup (ASCII-only, stable matching)."""
        import re
        normalized = re.sub(r"[^a-z0-9]+", "_", text.lower())
        normalized = normalized.strip("_")
        return normalized

    def _find_skill_for_lookup(self, message: str, allow_substring: bool) -> Optional["Skill"]:
        """Find a skill by exact/substring match against normalized aliases."""
        SkillRegistry.reload()
        skills = SkillRegistry.list_all()
        if not skills:
            return None

        alias_map: Dict[str, Any] = {}
        for skill in skills:
            variants = {
                skill.name,
                skill.name.replace("-", "_"),
                skill.name.replace("_", "-"),
                skill.display_name,
            }
            for variant in variants:
                key = self._normalize_skill_token(variant)
                if key:
                    alias_map.setdefault(key, skill)

        normalized_msg = self._normalize_skill_token(message)
        if normalized_msg in alias_map:
            return alias_map[normalized_msg]

        if allow_substring:
            for key, skill in sorted(alias_map.items(), key=lambda item: len(item[0]), reverse=True):
                if key and key in normalized_msg:
                    return skill

        return None

    def _build_skill_list_response(self, skills: List["Skill"]) -> str:
        limit = 30
        lines = [f"スキル一覧: {len(skills)}件"]
        lines.append("")
        for skill in skills[:limit]:
            lines.append(f"- {skill.display_name} (`{skill.name}`)")
        if len(skills) > limit:
            lines.append(f"... 他 {len(skills) - limit} 件")
        lines.append("")
        lines.append("詳細は<skill_name>で確認できます。")
        return "\n".join(lines)

    def _build_skill_detail_response(self, skill: "Skill") -> str:
        actions = skill.list_available_actions()
        tools = []
        for action in actions:
            tools.append(f"`{skill.name.replace('-', '_')}_{action}`")

        lines = [f"{skill.display_name} (`{skill.name}`)"]
        if skill.description:
            lines.append(f"- 説明: {skill.description}")
        if tools:
            lines.append(f"- ツール: {', '.join(tools)}")
        return "\n".join(lines)


    def _maybe_handle_skill_lookup(self, user_message: str) -> Optional[str]:
        """Return a direct response when the user asks about skills or lists them."""
        message = (user_message or "").strip()
        if not message:
            return None

        lower = message.lower()

        list_triggers = [
            "skill list",
            "skills",
            "list skills",
            "available skills",
        ]
        if any(t in lower for t in list_triggers) or "スキル一覧" in message or "スキルリスト" in message:
            skills = SkillRegistry.list_all()
            return self._build_skill_list_response(skills)

        lookup_triggers = [
            "what is",
            "what's",
            "about",
            "help",
            "details",
        ]
        has_lookup_trigger = any(t in lower for t in lookup_triggers)
        if "詳細" in message or "使い方" in message or "ヘルプ" in message or "教えて" in message or "説明" in message:
            has_lookup_trigger = True

        ascii_short = (len(message) <= 40 and len(message) >= 4 and all(ord(c) < 128 for c in message) and ("_" in message or "-" in message or message.isalnum()))
        if not has_lookup_trigger and not ascii_short and "スキル" not in message and "skill" not in lower:
            return None

        skill = self._find_skill_for_lookup(message, allow_substring=has_lookup_trigger)
        if skill:
            return self._build_skill_detail_response(skill)

        if has_lookup_trigger and ("スキル" in message or "skill" in lower):
            skills = SkillRegistry.list_all()
            return self._build_skill_list_response(skills)

        return None

    @staticmethod
    def _extract_first_sentence(text: str) -> str:
        """テキストから最初の一文を抽出（音声アナウンス用）"""
        # 日本語・英語の文末を検出
        for i, ch in enumerate(text):
            if ch in ("。", "！", "？", "!", "?", "\n"):
                sentence = text[:i + 1].strip()
                if len(sentence) >= 2:
                    return sentence
        # 文末が見つからない場合はそのまま（ただし100文字で切る）
        return text[:100].strip()

    def _get_model(self, task: str = "default") -> str:
        """
        タスクに応じたモデルを返す。

        - "default": 日常チャット → Haiku / プロジェクトチャット → Opus
        - "heavy": 強制Opus
        - "compaction": 強制Haiku（要約は簡単）

        プロジェクトチャット内の場合は自動的にOpusを使う（結果はキャッシュ）。
        """
        if task == "compaction":
            return MODEL_DEFAULT

        if task == "heavy":
            return MODEL_HEAVY

        # プロジェクトチャット判定（キャッシュ）
        if not hasattr(self, "_is_project_chat"):
            self._is_project_chat = False
            try:
                from app.services.project_service import ProjectService
                service = ProjectService()
                result = (
                    service.supabase.table("projects")
                    .select("id")
                    .eq("room_id", self.session.session_id)
                    .execute()
                )
                self._is_project_chat = bool(result.data)
            except Exception:
                pass

        if self._is_project_chat:
            return MODEL_HEAVY

        return MODEL_DEFAULT

    def _get_tools(self) -> List[Dict[str, Any]]:
        """
        LLMに渡すツール一覧を取得

        Returns:
            クライアントサイドツール + サーバーサイドツール（web_search）
        """
        tools = get_all_skill_tools()
        # Anthropic server-side web search
        tools.append({
            "type": "web_search_20250305",
            "name": "web_search",
            "max_uses": 5,
            "user_location": {
                "type": "approximate",
                "country": "JP",
                "timezone": "Asia/Tokyo",
            },
        })
        return tools

    async def _call_llm_with_tools(self) -> "anthropic.types.Message":
        """
        LLMをTool Use APIで呼び出す（529/overloaded時は自動リトライ）

        Returns:
            Anthropic Message オブジェクト（content blocksを含む）
        """
        if not self.llm_client:
            raise RuntimeError("LLMクライアントが設定されていません")

        messages = self.session.get_messages_for_llm()
        system_prompt = self._build_system_prompt()
        model = self._get_model()
        tools = self._get_tools()

        print(f"[LLM_DEBUG] Calling LLM with {len(tools)} tools")
        print(f"[LLM_DEBUG] Tool names: {[t['name'] for t in tools]}")

        max_retries = 3
        for attempt in range(max_retries):
            try:
                response = await self.llm_client.messages.create(
                    model=model,
                    max_tokens=4000,
                    system=system_prompt,
                    messages=messages,
                    tools=tools,
                    thinking={
                        "type": "enabled",
                        "budget_tokens": 1024,
                    },
                )

                print(f"[LLM_DEBUG] Response stop_reason: {response.stop_reason}")
                print(f"[LLM_DEBUG] Response content blocks: {len(response.content)}")

                return response
            except anthropic.APIStatusError as e:
                if e.status_code == 529 and attempt < max_retries - 1:
                    wait_sec = 2 ** attempt  # 1s, 2s, 4s
                    logger.warning(f"[LLM] API overloaded (529), retrying in {wait_sec}s (attempt {attempt + 1}/{max_retries})")
                    if self._on_reasoning_step:
                        await self._on_reasoning_step(f"APIが混雑中です。{wait_sec}秒後にリトライします...")
                    await asyncio.sleep(wait_sec)
                    continue
                raise

    async def _process_llm_response(
        self,
        response: "anthropic.types.Message",
    ) -> Dict[str, Any]:
        """
        LLMレスポンスのcontent blocksを処理

        textブロックをツールブロックとの位置関係で分類:
        - ツールより前のtext → reasoning_text（プロセスモニター向け）
        - ツールより後のtext → user_response（ユーザーへの回答）
        - ツールがない場合 → 全textがuser_response

        Returns:
            {
                "user_response": ユーザー回答（最後のツール以降のテキスト）,
                "reasoning_text": 推論テキスト（ツール前のテキスト、SSE向け）,
                "tool_calls": 実行すべきスキルツール呼び出しリスト,
                "stop_reason": LLMの停止理由,
            }
        """
        tool_calls = []

        # Pass 1: 全ブロックをインデックス付きで分類
        # 最後のツール系ブロックの位置を特定する
        last_tool_index = -1
        for i, block in enumerate(response.content):
            if block.type in ("tool_use", "server_tool_use", "web_search_tool_result"):
                last_tool_index = i

        # Pass 2: textブロックを位置で振り分け
        reasoning_parts = []
        response_parts = []

        for i, block in enumerate(response.content):
            if block.type == "thinking":
                # Extended Thinking: 内部推論（分析・計画）。表示せずスキップ
                print(f"[LLM_DEBUG] Thinking block: {block.thinking[:80]}...")
                continue

            elif block.type == "text":
                text = block.text.strip()
                if not text:
                    continue

                if last_tool_index < 0:
                    # ツールなし → 全textがresponse
                    response_parts.append(text)
                elif i <= last_tool_index:
                    # ツールより前 → reasoning
                    reasoning_parts.append(text)
                else:
                    # ツールより後 → response
                    response_parts.append(text)

                safe_print(f"[LLM_DEBUG] Text block ({'reasoning' if i <= last_tool_index and last_tool_index >= 0 else 'response'}): {text[:50]}...")

            elif block.type == "tool_use":
                tool_name = block.name
                tool_input = block.input
                tool_use_id = block.id

                print(f"[LLM_DEBUG] Tool use: {tool_name}")

                parsed = parse_tool_name(tool_name)
                if parsed:
                    skill_name, action = parsed
                    tool_calls.append({
                        "tool_use_id": tool_use_id,
                        "skill": skill_name,
                        "action": action,
                        "params": tool_input,
                    })
                    print(f"[LLM_DEBUG] Skill tool: {skill_name} {action}")

            elif block.type == "server_tool_use":
                print(f"[LLM_DEBUG] Server tool use: {block.name}")

            elif block.type == "web_search_tool_result":
                print(f"[LLM_DEBUG] Web search result received")

        user_response = "\n\n".join(response_parts) if response_parts else None
        reasoning_text = "\n".join(reasoning_parts) if reasoning_parts else None

        return {
            "user_response": user_response,
            "reasoning_text": reasoning_text,
            "tool_calls": tool_calls,
            "stop_reason": response.stop_reason,
        }

    async def _check_and_compact(self) -> None:
        """
        コンパクションが必要かチェックし、必要なら実行

        1. トークン数が閾値を超えたらメモリフラッシュを実行
        2. LLMに重要情報を memory/ に保存させる
        3. 古いメッセージを削除し、要約を残す
        """
        token_count = self.session.estimate_token_count()
        logger.debug(f"Token count: {token_count} / {COMPACTION_THRESHOLD}")

        if token_count < COMPACTION_THRESHOLD:
            return

        logger.info(f"Compaction triggered: {token_count} tokens")

        if self._on_reasoning_step:
            await self._on_reasoning_step("📝 会話が長くなったので記憶を整理中...")

        try:
            # メモリフラッシュ: LLMに重要情報を保存させる
            summary = await self._flush_to_memory()

            # 要約生成に失敗した場合はコンパクション中止（文脈喪失を防ぐ）
            if not summary or summary == "会話の要約が生成されませんでした。":
                logger.warning("Summary generation failed, aborting compaction to preserve context")
                if self._on_reasoning_step:
                    await self._on_reasoning_step("⚠️ 要約生成に失敗したため、記憶整理をスキップしました")
                return

            # 古いメッセージを削除し、要約を残す
            removed = self.session.compact(summary, keep_recent=COMPACTION_KEEP_RECENT)
            logger.info(f"Compacted: removed {removed} messages, kept {COMPACTION_KEEP_RECENT}")

            # セッションを再保存
            store = get_session_store()
            await store.save(self.session)

            if self._on_reasoning_step:
                await self._on_reasoning_step(f"✅ 記憶を整理しました（{removed}件のメッセージを要約）")

        except Exception as e:
            logger.exception(f"Compaction failed: {e}")
            # コンパクション失敗は致命的ではない、続行

    @staticmethod
    def _strip_images_for_summary(messages: List[Dict[str, Any]]) -> List[Dict[str, Any]]:
        """
        メッセージから画像を除外し、テキストのみのコピーを返す。

        要約生成にスクリーンショットは不要。画像を除外することで
        トークン消費を大幅に削減し、要約LLM呼び出しの成功率を上げる。
        """
        import copy
        stripped = []
        for msg in messages:
            content = msg.get("content", "")
            if isinstance(content, str):
                stripped.append(msg)
            elif isinstance(content, list):
                new_blocks = []
                for block in content:
                    if not isinstance(block, dict):
                        new_blocks.append(block)
                        continue
                    btype = block.get("type", "")
                    # 画像ブロックをスキップ
                    if btype == "image":
                        continue
                    # tool_result内の画像もスキップ
                    if btype == "tool_result":
                        inner = block.get("content", "")
                        if isinstance(inner, list):
                            filtered = [b for b in inner if not (isinstance(b, dict) and b.get("type") == "image")]
                            if filtered:
                                new_block = copy.copy(block)
                                new_block["content"] = filtered
                                new_blocks.append(new_block)
                            else:
                                # テキストもない場合はプレースホルダー
                                new_block = copy.copy(block)
                                new_block["content"] = "[スクリーンショット]"
                                new_blocks.append(new_block)
                            continue
                        new_blocks.append(block)
                        continue
                    new_blocks.append(block)
                if new_blocks:
                    stripped.append({"role": msg["role"], "content": new_blocks})
            else:
                stripped.append(msg)
        return stripped

    async def _flush_to_memory(self) -> str:
        """
        メモリフラッシュ: 会話の全トピックを圧縮してメモリファイルに保存

        LLMの役割は「選別」ではなく「圧縮」。全てのやり取りを漏れなく要約する。

        Returns:
            会話の要約テキスト
        """
        from datetime import datetime

        # フラッシュ用のシステムプロンプト（圧縮機として指示）
        flush_system = """あなたは会話ログの圧縮係です。

以下の会話の全内容を箇条書きで要約してください。

ルール:
- 全てのトピック・やり取りを漏れなく含める。省略禁止。
- 各トピックは1-2行で簡潔に。
- ユーザーの質問・相談内容、それに対する回答・結果を両方含める。
- 具体的な固有名詞（店名、商品名、URL、金額等）は省略せず残す。
- 「重要かどうか」の判断はしない。全て記録する。
- テキスト出力のみ。ツールは使わない。
"""

        # フラッシュ用のメッセージ（画像を除外してトークン節約）
        flush_messages = self._strip_images_for_summary(
            self.session.get_messages_for_llm()
        )
        flush_messages.append({
            "role": "user",
            "content": "上記の会話の全内容を箇条書きで要約してください。省略禁止。"
        })

        # LLM呼び出し（ツールなし、テキスト出力のみ）— 圧縮はHaikuで十分
        response = await self.llm_client.messages.create(
            model=self._get_model(task="compaction"),
            max_tokens=4000,
            system=flush_system,
            messages=flush_messages,
        )

        # テキスト出力を要約として使用
        summary = "会話の要約が生成されませんでした。"
        text_parts = []
        for block in response.content:
            if block.type == "text":
                text_parts.append(block.text.strip())

        if text_parts:
            summary = "\n\n".join(text_parts)

        # 要約を日付ファイルに上書き保存（ブートストラップ + search_memory 両方で利用可能）
        if summary and summary != "会話の要約が生成されませんでした。":
            date_str = datetime.now().strftime("%Y-%m-%d")
            memory_dir = WORKSPACE_DIR / "memory"
            memory_dir.mkdir(parents=True, exist_ok=True)
            filepath = memory_dir / f"{date_str}.md"
            filepath.write_text(
                f"# {date_str} 会話ログ（最終更新: {datetime.now().strftime('%H:%M')}）\n\n{summary}",
                encoding="utf-8",
            )
            logger.info(f"Compaction summary saved to {filepath}")

        # MEMORY.md（長期記憶）の自動更新
        if summary and summary != "会話の要約が生成されませんでした。":
            await self._update_long_term_memory(summary)

        return summary

    async def _update_long_term_memory(self, conversation_summary: str) -> None:
        """
        MEMORY.mdを自動更新する。

        現在のMEMORY.mdの内容と会話要約を渡し、
        長期記憶として残すべき情報を統合した更新版を生成する。
        """
        memory_file = WORKSPACE_DIR / "MEMORY.md"
        current_memory = ""
        if memory_file.exists():
            current_memory = memory_file.read_text(encoding="utf-8")

        system = """あなたは長期記憶の管理係です。

「現在の長期記憶」と「今回の会話要約」を見て、長期記憶の更新版を出力してください。

長期記憶に残すべき情報:
- ユーザーの好み・習慣（よく使うサービス、好きなブランド等）
- アカウント情報（メールアドレス、住所、ユーザー名等）
- 繰り返し参照される事実（家族構成、仕事、定期的な予定等）
- 重要な決定事項（購入したもの、契約したサービス等）
- Danの動作に関するフィードバック（こうしてほしい、これはやめて等）

ルール:
- 現在の長期記憶にある情報は保持する（消さない）
- 新しい情報があれば追加する
- 古い情報が更新された場合は最新に書き換える
- 一時的な話題（天気、一回きりの質問等）は含めない
- Markdown形式で、セクション分けして整理する
- テキスト出力のみ。ツールは使わない。
"""

        messages = [
            {
                "role": "user",
                "content": f"## 現在の長期記憶\n\n{current_memory}\n\n---\n\n## 今回の会話要約\n\n{conversation_summary}\n\n---\n\n上記を統合した、更新版の長期記憶をMarkdownで出力してください。",
            }
        ]

        try:
            response = await self.llm_client.messages.create(
                model=self._get_model(task="compaction"),
                max_tokens=2000,
                system=system,
                messages=messages,
            )

            text_parts = []
            for block in response.content:
                if block.type == "text":
                    text_parts.append(block.text.strip())

            if text_parts:
                updated_memory = "\n\n".join(text_parts)
                memory_file.write_text(updated_memory, encoding="utf-8")
                logger.info("MEMORY.md updated with long-term memory")
        except Exception as e:
            logger.warning(f"Failed to update MEMORY.md: {e}")



async def create_runner(
    session_id: str,
    user_id: str,
    on_reasoning_step: Optional[Callable[[str], Awaitable[None]]] = None,
    on_voice_announcement: Optional[Callable[[str], Awaitable[None]]] = None,
) -> AgentRunner:
    """
    AgentRunnerを作成（セッションを自動取得）

    使い方:
        runner = await create_runner(room_id, user_id, on_step_callback)
        result = await runner.process_message("新幹線を予約したい")
    """
    store = get_session_store()
    session = await store.get_or_create(session_id, user_id)

    return AgentRunner(
        session=session,
        on_reasoning_step=on_reasoning_step,
        on_voice_announcement=on_voice_announcement,
    )
