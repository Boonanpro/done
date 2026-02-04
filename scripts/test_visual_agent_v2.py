"""
VisualAgent v2 テスト

公式loop.pyパターンに準拠した実装のテスト。
コールバック機構と計画フェーズの動作を確認。
"""

import asyncio
import sys
sys.path.insert(0, "D:/done")

from app.executors.visual.agent import VisualAgent
from app.executors.visual.recorder import BrowserRecorder


def on_plan(plan):
    """計画コールバック"""
    print("\n" + "="*50)
    print("[PLAN] Created")
    print("="*50)
    if plan:
        print(f"Summary: {plan.get('summary', 'N/A')}")
        steps = plan.get('steps', [])
        for i, step in enumerate(steps, 1):
            print(f"  {i}. {step}")
    print("="*50)
    print("Starting execution...\n")


def on_thinking(reasoning):
    """思考コールバック"""
    if reasoning:
        # 最初の100文字だけ表示
        preview = reasoning[:100] + "..." if len(reasoning) > 100 else reasoning
        print(f"[THINKING] {preview}")


def on_step(step_num, action_name, result):
    """ステップコールバック（1行で完結）"""
    if isinstance(result, dict):
        success = result.get("success", True)
    else:
        success = getattr(result, "success", True)

    icon = "[OK]" if success else "[NG]"
    print(f"Step {step_num}: {action_name} {icon}")


async def main():
    print("="*60)
    print("VisualAgent v2 テスト")
    print("公式loop.pyパターン + 計画フェーズ")
    print("="*60)

    # エージェント作成
    recorder = BrowserRecorder(user_id="test")
    agent = VisualAgent(
        recorder=recorder,
        max_steps=20,
        on_thinking=on_thinking,
        on_step=on_step,
        on_plan=on_plan,
    )

    # 楽天でテスト（座標精度確認用）
    task = "楽天市場で「アベンヌウォーター」を検索して、検索結果を確認する"

    print(f"\n[TASK] {task}\n")

    result = await agent.execute_task(
        task=task,
        site="rakuten.co.jp",
    )

    print("\n" + "="*60)
    print("[RESULT]")
    print("="*60)
    print(f"Success: {result.get('success')}")
    print(f"Message: {result.get('message', result.get('error', 'N/A'))}")
    print(f"Steps: {result.get('steps', 'N/A')}")
    print(f"Tokens: {result.get('total_tokens', 'N/A')}")

    # メッセージ蓄積の確認
    print(f"\n[MESSAGES] Count: {len(agent.messages)}")
    for i, msg in enumerate(agent.messages):
        role = msg.get("role", "?")
        content = msg.get("content", [])
        if isinstance(content, list):
            types = [c.get("type", "?") for c in content if isinstance(c, dict)]
            print(f"  {i+1}. {role}: {types}")
        else:
            print(f"  {i+1}. {role}: {type(content)}")


if __name__ == "__main__":
    asyncio.run(main())
