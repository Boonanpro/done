"""
Native Tool Use 動作確認テスト

Phase 8: テスト・検証
- respond_to_user が呼ばれるか
- プロセスが回答に漏出しないか
"""

import asyncio
import sys
sys.path.insert(0, "D:/done")

from app.agent.v2.runner import AgentRunner
from app.agent.v2.session import Session


async def test_chat(message: str, test_name: str, session: Session):
    """チャットをテスト"""
    print(f"\n{'='*60}")
    print(f"テスト: {test_name}")
    print(f"入力: {message}")
    print("="*60)

    # コールバックでプロセスを収集
    reasoning_steps = []

    async def on_reasoning(step: str):
        reasoning_steps.append(step)
        print(f"  [PROCESS] {step}")

    try:
        runner = AgentRunner(session=session, on_reasoning_step=on_reasoning)
        result = await runner.process_message(message)

        print("\n--- 結果 ---")
        response_text = result.get("response", "")
        print(f"回答: {response_text}")
        print(f"プロセス数: {len(reasoning_steps)}")
        print(f"状態: {result.get('state', 'N/A')}")

        # プロセス漏出チェック
        leakage_patterns = [
            "を確認します",
            "を実行します",
            "を探します",
            "スクリーンショット",
            "ツール実行",
            "[STEP]",
            "[STATE:",
        ]

        leaked = []
        for pattern in leakage_patterns:
            if pattern in response_text:
                leaked.append(pattern)

        if leaked:
            print(f"\n[WARNING] プロセス漏出検出: {leaked}")
            return False
        else:
            print("\n[OK] プロセス漏出なし")
            return True

    except Exception as e:
        print(f"\n[ERROR] {type(e).__name__}: {e}")
        import traceback
        traceback.print_exc()
        return False


async def main():
    print("Native Tool Use 動作確認テスト")
    print("="*60)

    # Session初期化
    session = Session(
        session_id="test-native-tool-use",
        user_id="test-user"
    )

    results = []

    # テスト1: シンプルな雑談
    result1 = await test_chat(
        "こんにちは",
        "雑談テスト（respond_to_user確認）",
        session
    )
    results.append(("雑談テスト", result1))

    # テスト2: 質問への回答
    result2 = await test_chat(
        "1+1は何？",
        "簡単な質問テスト",
        session
    )
    results.append(("質問テスト", result2))

    # サマリー
    print("\n" + "="*60)
    print("テスト結果サマリー")
    print("="*60)
    for name, passed in results:
        status = "[PASS]" if passed else "[FAIL]"
        print(f"  {status} {name}")

    all_passed = all(r[1] for r in results)
    print(f"\n総合結果: {'SUCCESS' if all_passed else 'FAILURE'}")

    return all_passed


if __name__ == "__main__":
    success = asyncio.run(main())
    sys.exit(0 if success else 1)
