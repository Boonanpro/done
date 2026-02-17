"""
Project Execution Service

提案承認後にバックグラウンドでDanが計画を実行する。
asyncio.create_task() で呼ばれる非同期タスク。
"""

import re
import asyncio
import logging
from typing import List, Optional

logger = logging.getLogger(__name__)

# 実行プロンプト
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

## ゾーン判断（各操作の実行前に必ず判定）
- **Green（即実行）**: 検索、閲覧、ツール作成、bashコマンド、ファイル操作、パッケージインストール
- **Yellow（実行→報告）**: フォーム入力（非個人情報）、カート追加、設定変更
- **Red（確認→実行）**: 個人情報入力、購入確定、取消不可操作 → 必ずユーザーに内容を示して確認を待つ

### Red判定の具体例
- 氏名・住所・電話番号・生年月日・メールアドレスの入力（※USER.mdに保存済みの情報はYellow扱い＝そのまま使ってよい）
- クレジットカード情報の入力
- 「注文を確定する」「購入する」ボタンのクリック
- アカウント削除、解約、退会の実行
- 送金・振込の実行

### 障害対応
- エラー → まず自分のツール（bash, browser, exec_code等）で解決を試みる
- ツール不足 → 必要なスクリプトを書いて実行する
- OTP/2段階認証 → 「認証コードを教えてください」とユーザーに聞く
- CAPTCHA → スクリーンショットを見せて「この画像の文字を教えてください」と聞く
- ログイン要求 → 「ログインが必要です。ID/パスワードを教えてください」と聞く
- 「できません」と止まることは禁止。必ず代替案を提示するか、ユーザーに助けを求める
"""


def build_execution_prompt(title: str, description: str, steps: List[dict]) -> str:
    """実行プロンプトを組み立てて返す（外部から呼び出し可能）"""
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
    """
    Danの応答テキストから各ステップの完了/失敗を推定。

    Returns:
        [{"step_number": 1, "status": "completed"}, ...]
    """
    results = []

    for i in range(1, total_steps + 1):
        # 「ステップ N」が言及されているかチェック
        pattern = rf"##\s*ステップ\s*{i}"
        if re.search(pattern, response_text):
            # 失敗パターンをチェック
            fail_pattern = rf"ステップ\s*{i}[^#]*?(失敗|エラー|できませんでした|スキップ)"
            if re.search(fail_pattern, response_text, re.DOTALL):
                results.append({"step_number": i, "status": "failed"})
            else:
                results.append({"step_number": i, "status": "completed"})
        else:
            # 言及なし = pending のまま
            results.append({"step_number": i, "status": "pending"})

    return results


async def run_project_execution(
    project_id: str,
    room_id: str,
    user_id: str,
    proposal_id: str,
    title: str,
    description: str,
    steps: List[dict],
) -> None:
    """
    バックグラウンドで承認された計画を実行する。

    asyncio.create_task() で起動される。
    """
    try:
        # SSEレスポンス完了を待つ
        await asyncio.sleep(2)

        logger.info(f"[ProjectExec] Starting execution for project {project_id}")

        # プロジェクトステータスをin_progressに
        from app.services.project_service import ProjectService
        project_service = ProjectService()
        await project_service.update_project(
            project_id, user_id, status="in_progress"
        )

        # Runnerを作成してプロンプトを送信
        from app.agent.v2.runner import create_runner

        runner = await create_runner(
            session_id=room_id,
            user_id=user_id,
        )

        steps_text = _format_steps(steps)
        prompt = EXECUTION_PROMPT.format(
            title=title,
            description=description or "(説明なし)",
            steps_text=steps_text,
        )

        result = await runner.process_message(prompt)
        response_text = result.get("response", "")

        if not response_text:
            logger.warning(f"[ProjectExec] Empty response for project {project_id}")
            return

        logger.info(
            f"[ProjectExec] Got response for project {project_id}: "
            f"{len(response_text)} chars"
        )

        # 1. チャットメッセージとして保存
        from app.services.chat_service import ChatService
        chat_service = ChatService()
        await chat_service.send_dan_ai_message(
            user_id=user_id,
            content=response_text,
            room_id=room_id,
        )

        # 2. ステップ完了状況を推定してDB更新
        total_steps = len(steps)
        if total_steps > 0:
            step_results = _detect_step_completion(response_text, total_steps)
            for sr in step_results:
                await project_service.update_step_status(
                    proposal_id, sr["step_number"], sr["status"]
                )

        # 3. プロジェクトステータスをcompletedに
        await project_service.update_project(
            project_id, user_id, status="completed"
        )

        logger.info(f"[ProjectExec] Completed for project {project_id}")

    except Exception as e:
        logger.exception(f"[ProjectExec] Failed for project {project_id}: {e}")
        # 失敗時もステータスを更新（paused にして手動対応可能に）
        try:
            from app.services.project_service import ProjectService
            ps = ProjectService()
            await ps.update_project(project_id, user_id, status="paused")
        except Exception:
            pass
