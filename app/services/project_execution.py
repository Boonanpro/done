"""
Project Execution Service

提案承認後にバックグラウンドでDanが計画をステップごとに実行する。
各ステップ: CLI実行 → 自己検証JSON抽出 → DB更新 → 次ステップへ。
Red操作は実行前にユーザー確認を待つ。
"""

import re
import json
import asyncio
import logging
from typing import List, Optional, Dict, Any

logger = logging.getLogger(__name__)

# ---------------------------------------------------------------------------
# Red操作判定
# ---------------------------------------------------------------------------
RED_KEYWORDS = ["購入", "確定", "送金", "振込", "削除", "解約", "個人情報", "【要操作】"]


def is_red_zone(step: dict) -> bool:
    """ステップがRed操作（ユーザー確認必須）かを判定"""
    desc = step.get("description", "")
    return any(kw in desc for kw in RED_KEYWORDS)


# ---------------------------------------------------------------------------
# ステップ単位のプロンプト
# ---------------------------------------------------------------------------
STEP_EXECUTION_PROMPT = """## 現在のタスク
ステップ {step_number}: {description}

{previous_results_section}

## 実行ルール
1. このステップだけを実行してください
2. 実行が完了したら、以下のフォーマットで自己検証結果を報告してください
3. 実際の成果物（スクショ、ファイル存在、画面のURL等）を確認した上で判定してください
4. 「やったつもり」ではなく「証拠がある」場合のみ completed にしてください

## ゾーン判断（各操作の実行前に必ず判定）
- **Green（即実行）**: 検索、閲覧、ツール作成、bashコマンド、ファイル操作、パッケージインストール
- **Yellow（実行→報告）**: フォーム入力（非個人情報）、カート追加、設定変更
- **Red（確認→実行）**: 個人情報入力、購入確定、取消不可操作 → 必ずユーザーに内容を示して確認を待つ

## 障害対応
- エラー → まず自分のツール（bash, browser, exec_code等）で解決を試みる
- OTP/2段階認証 → メールアプリやSMSをブラウザで開いてコードを自力取得する。取得できない場合のみユーザーに聞く
- 「できません」と止まることは禁止。必ず代替案を提示するか、ユーザーに助けを求める

## 検証報告フォーマット（必ずこの形式で最後に出力）

```json
{{
  "step_number": {step_number},
  "status": "completed" | "failed" | "partial",
  "summary": "何が達成されたかの1行要約",
  "evidence": "成功/失敗の根拠（URL、ファイルパス、画面の状態等）",
  "should_abort": false
}}
```
"""

FIRST_STEP_PREAMBLE = """以下の計画が承認されました。ステップごとに実行していきます。

## プロジェクト情報
- タイトル: {title}
- 説明: {description}

## 全体計画
{plan_content}

{team_context}

---

まず最初のステップから始めてください。

"""


def build_step_prompt(
    step: dict,
    previous_results: List[dict],
    title: str = "",
    description: str = "",
    plan_content: str = "",
    team_context: str = "",
    is_first_step: bool = False,
) -> str:
    """1ステップ分の実行プロンプトを組み立てる"""
    # 前のステップの結果セクション
    if previous_results:
        lines = []
        for r in previous_results:
            status_icon = "✅" if r.get("status") == "completed" else "❌" if r.get("status") == "failed" else "⚠️"
            lines.append(f"- {status_icon} ステップ {r.get('step_number', '?')}: {r.get('summary', '(要約なし)')}")
        prev_section = "## これまでの実行結果\n" + "\n".join(lines)
    else:
        prev_section = ""

    step_prompt = STEP_EXECUTION_PROMPT.format(
        step_number=step.get("step_number", "?"),
        description=step.get("description", ""),
        previous_results_section=prev_section,
    )

    # 最初のステップにはプロジェクト全体の文脈を付加
    if is_first_step:
        preamble = FIRST_STEP_PREAMBLE.format(
            title=title,
            description=description or "(説明なし)",
            plan_content=plan_content,
            team_context=team_context,
        )
        return preamble + step_prompt

    return step_prompt


# ---------------------------------------------------------------------------
# 自己検証JSONの抽出
# ---------------------------------------------------------------------------
def parse_step_verification(cli_output_text: str) -> dict:
    """CLIの出力テキストから自己検証JSONブロックを抽出する。

    Returns:
        dict with keys: step_number, status, summary, evidence, should_abort
    """
    default = {
        "status": "partial",
        "summary": "検証結果を抽出できず",
        "evidence": "",
        "should_abort": False,
    }

    if not cli_output_text:
        return default

    # 1. ```json ... ``` ブロックを探す（最後のものを優先）
    json_blocks = re.findall(
        r'```json\s*(\{.*?\})\s*```', cli_output_text, re.DOTALL
    )
    if json_blocks:
        try:
            parsed = json.loads(json_blocks[-1])
            if "status" in parsed:
                return parsed
        except (json.JSONDecodeError, ValueError):
            pass

    # 2. フォールバック: テキスト中の "status" を含むJSONオブジェクト
    matches = re.findall(
        r'\{[^{}]*"status"\s*:\s*"[^"]+?"[^{}]*\}', cli_output_text
    )
    if matches:
        try:
            parsed = json.loads(matches[-1])
            if "status" in parsed:
                return parsed
        except (json.JSONDecodeError, ValueError):
            pass

    # 3. 抽出失敗 → 安全側に倒す
    return default


# ---------------------------------------------------------------------------
# ステップごとの実行メインループ
# ---------------------------------------------------------------------------
async def run_stepwise_execution(
    project_id: str,
    room_id: str,
    user_id: str,
    proposal_id: str,
    title: str,
    description: str,
    steps: List[dict],
    plan_content: str = "",
    team_context: str = "",
    start_from_step: int = 1,
) -> None:
    """
    ステップごとに実行するメインループ。

    asyncio.create_task() で起動される。
    各ステップ: プロンプト送信 → CLI実行 → 自己検証JSON抽出 → DB更新。
    Red操作の前で一時停止してユーザー確認を待つ。

    Args:
        start_from_step: 実行を開始するステップ番号（再開時に使用）
    """
    from app.services.project_service import ProjectService
    from app.services.chat_service import ChatService
    from app.agent.cli_runner import process_message_cli

    project_service = ProjectService()
    chat_service = ChatService()
    had_error = False
    previous_results: List[dict] = []

    try:
        # SSEレスポンス完了を待つ
        await asyncio.sleep(2)

        logger.info(
            f"[StepExec] Starting stepwise execution for project {project_id} "
            f"from step {start_from_step}"
        )

        # プロジェクトステータスをin_progressに
        await project_service.update_project(
            project_id, user_id, status="in_progress"
        )

        # 開始メッセージ
        total = len(steps)
        await chat_service.send_dan_ai_message(
            user_id=user_id,
            content=f"承認された計画の実行を開始します（全{total}ステップ）...",
            room_id=room_id,
        )

        # 開始ステップより前のステップの結果を取得（再開時用）
        if start_from_step > 1:
            for s in steps:
                sn = s.get("step_number", 0)
                if sn < start_from_step:
                    st = s.get("status", "pending")
                    previous_results.append({
                        "step_number": sn,
                        "status": st,
                        "summary": s.get("description", ""),
                    })

        # --- ステップループ ---
        for step in steps:
            step_number = step.get("step_number", 0)

            # 開始ステップより前はスキップ
            if step_number < start_from_step:
                continue

            # Red操作チェック（実行前に確認）
            if is_red_zone(step):
                await _pause_for_confirmation(
                    project_id=project_id,
                    user_id=user_id,
                    room_id=room_id,
                    proposal_id=proposal_id,
                    step=step,
                    previous_results=previous_results,
                    project_service=project_service,
                    chat_service=chat_service,
                )
                return  # ユーザー確認後に /resume で再開される

            # ステップ開始をDB記録
            await project_service.update_step_status(
                proposal_id, step_number, "in_progress"
            )

            # 進捗メッセージ
            await chat_service.send_dan_ai_message(
                user_id=user_id,
                content=f"**ステップ {step_number}/{total}**: {step.get('description', '')}",
                room_id=room_id,
            )

            # プロンプト組み立て
            is_first = step_number == steps[0].get("step_number", 1)
            prompt = build_step_prompt(
                step=step,
                previous_results=previous_results,
                title=title,
                description=description,
                plan_content=plan_content,
                team_context=team_context,
                is_first_step=is_first and start_from_step == 1,
            )

            # CLI実行
            step_text_parts = []
            step_had_error = False

            async for event in process_message_cli(
                room_id=room_id,
                user_id=user_id,
                content=prompt,
                project_title=title,
                project_description=description,
                project_status="in_progress",
            ):
                etype = event["type"]

                if etype == "text":
                    if event["text"].strip():
                        step_text_parts.append(event["text"])
                        await chat_service.send_dan_ai_message(
                            user_id=user_id,
                            content=event["text"],
                            room_id=room_id,
                        )

                elif etype == "tool_use":
                    from app.api.project_routes import _format_tool_label
                    label = _format_tool_label(
                        event.get("name", ""), event.get("input", {})
                    )
                    await project_service.save_execution_event(
                        project_id=project_id,
                        room_id=room_id,
                        event_type="tool_use",
                        tool_name=event.get("name", ""),
                        tool_label=label,
                    )

                elif etype == "result":
                    result_text = event.get("text", "")
                    if result_text:
                        step_text_parts.append(result_text)

                elif etype == "error":
                    step_had_error = True
                    error_msg = event.get("message", "unknown error")
                    step_text_parts.append(f"エラー: {error_msg}")
                    await project_service.save_execution_event(
                        project_id=project_id,
                        room_id=room_id,
                        event_type="error",
                        content=error_msg[:500],
                    )

            # 自己検証JSONを抽出
            full_output = "\n".join(step_text_parts)
            verification = parse_step_verification(full_output)

            # CLIエラーが発生した場合は検証結果を上書き
            if step_had_error and verification.get("status") == "partial":
                verification["status"] = "failed"
                verification["summary"] = "CLIエラーが発生"

            v_status = verification.get("status", "partial")
            v_summary = verification.get("summary", "")
            v_should_abort = verification.get("should_abort", False)

            logger.info(
                f"[StepExec] Step {step_number} verification: "
                f"status={v_status}, summary={v_summary}"
            )

            # DB更新
            db_status = "completed" if v_status == "completed" else "failed"
            await project_service.update_step_status(
                proposal_id, step_number, db_status
            )

            # 結果を記録
            previous_results.append({
                "step_number": step_number,
                "status": v_status,
                "summary": v_summary,
                "evidence": verification.get("evidence", ""),
            })

            # 実行イベントとして記録
            await project_service.save_execution_event(
                project_id=project_id,
                room_id=room_id,
                event_type="step_verification",
                content=json.dumps(verification, ensure_ascii=False),
                metadata={"step_number": step_number},
            )

            # 失敗 + 中止すべき場合はループ終了
            if v_status == "failed" and v_should_abort:
                await chat_service.send_dan_ai_message(
                    user_id=user_id,
                    content=f"ステップ {step_number} が失敗し、後続ステップを中止します。\n理由: {v_summary}",
                    room_id=room_id,
                )
                had_error = True
                break

        # --- 全ステップ完了 ---
        completed_count = sum(
            1 for r in previous_results if r.get("status") == "completed"
        )
        failed_count = sum(
            1 for r in previous_results if r.get("status") == "failed"
        )

        summary_lines = ["## 完了報告\n"]
        for r in previous_results:
            icon = "✅" if r["status"] == "completed" else "❌" if r["status"] == "failed" else "⚠️"
            summary_lines.append(
                f"- {icon} ステップ {r['step_number']}: {r.get('summary', '')}"
            )
        summary_lines.append(
            f"\n完了: {completed_count}, 失敗: {failed_count}, 合計: {len(previous_results)}"
        )
        summary_text = "\n".join(summary_lines)

        await chat_service.send_dan_ai_message(
            user_id=user_id,
            content=summary_text,
            room_id=room_id,
        )

    except Exception as e:
        had_error = True
        logger.exception(
            f"[StepExec] Failed for project {project_id}: {e}"
        )
        try:
            chat_service = ChatService()
            await chat_service.send_dan_ai_message(
                user_id=user_id,
                content=f"実行中にエラーが発生しました: {e}",
                room_id=room_id,
            )
        except Exception:
            pass
    finally:
        try:
            ps = ProjectService()
            new_status = "paused" if had_error else "completed"
            await ps.update_project(project_id, user_id, status=new_status)
            logger.info(
                f"[StepExec] Project {project_id} status → {new_status}"
            )
        except Exception as e:
            logger.error(
                f"[StepExec] Failed to update status for {project_id}: {e}"
            )


# ---------------------------------------------------------------------------
# Red操作の確認待ち
# ---------------------------------------------------------------------------
async def _pause_for_confirmation(
    project_id: str,
    user_id: str,
    room_id: str,
    proposal_id: str,
    step: dict,
    previous_results: List[dict],
    project_service: Any,
    chat_service: Any,
) -> None:
    """プロジェクトを確認待ち状態にしてユーザー確認を待つ"""
    step_number = step.get("step_number", 0)
    step_desc = step.get("description", "")

    logger.info(
        f"[StepExec] Pausing for Red confirmation: "
        f"project={project_id}, step={step_number}"
    )

    # プロジェクトのmetadataに中断情報を保存
    await project_service.update_project(
        project_id, user_id,
        status="awaiting_confirmation",
        metadata={
            "pending_step": step_number,
            "proposal_id": proposal_id,
            "previous_results": previous_results,
            "confirmation_message": (
                f"ステップ {step_number} は確認が必要な操作を含みます:\n\n"
                f"**{step_desc}**\n\n"
                f"実行してよろしいですか？"
            ),
        },
    )

    # チャットに確認メッセージを送信
    await chat_service.send_dan_ai_message(
        user_id=user_id,
        content=(
            f"⚠️ **確認が必要です**\n\n"
            f"次のステップは慎重な操作を含みます:\n\n"
            f"**ステップ {step_number}: {step_desc}**\n\n"
            f"実行を続けるには「再開」を押してください。"
        ),
        room_id=room_id,
    )


# ---------------------------------------------------------------------------
# 旧API互換（build_execution_prompt / _detect_step_completion）
# ---------------------------------------------------------------------------
EXECUTION_PROMPT = """[Project Execution] 承認された計画を実行してください。

## プロジェクト情報
- タイトル: {title}
- 説明: {description}

## 承認された実行計画
{steps_text}

## 実行ルール
1. ステップを順番に1つずつ実行
2. 各ステップの開始時に「## ステップ N: ○○ を開始します」と宣言
3. 各ステップの完了時に結果を報告
4. 失敗した場合は理由を説明して次に進む（全体を止めない）
5. 全ステップ完了後に「## 完了報告」として全体をまとめる
6. 必要に応じてweb_search、browser_*、deep_research等のツールを使用
"""


def build_execution_prompt(title: str, description: str, steps: List[dict]) -> str:
    """旧API互換: 実行プロンプトを組み立てて返す"""
    steps_text = _format_steps(steps)
    return EXECUTION_PROMPT.format(
        title=title,
        description=description or "(説明なし)",
        steps_text=steps_text,
    )


def _format_steps(steps: List[dict]) -> str:
    """ステップリストをMarkdown化"""
    if not steps:
        return "(ステップなし)"
    lines = []
    for step in steps:
        num = step.get("step_number", "?")
        desc = step.get("description", "")
        lines.append(f"{num}. {desc}")
    return "\n".join(lines)


def _detect_step_completion(response_text: str, total_steps: int) -> List[dict]:
    """旧API互換: Regexベースのステップ完了判定（非推奨）"""
    results = []
    for i in range(1, total_steps + 1):
        pattern = rf"##\s*ステップ\s*{i}"
        if re.search(pattern, response_text):
            fail_pattern = rf"ステップ\s*{i}[^#]*?(失敗|エラー|できませんでした|スキップ)"
            if re.search(fail_pattern, response_text, re.DOTALL):
                results.append({"step_number": i, "status": "failed"})
            else:
                results.append({"step_number": i, "status": "completed"})
        else:
            results.append({"step_number": i, "status": "pending"})
    return results
