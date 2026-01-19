"""
Agent v2 テストスクリプト

会話の文脈が維持されるかを確認する。
特に「認証情報を渡したら認識されるか」をテスト。
ツール連携のテストも含む。
"""

import asyncio
import sys
sys.path.insert(0, "D:\\done")

from app.agent.v2.runner import create_runner
from app.agent.v2.tools import SkillRegistry, parse_tool_call


async def test_conversation():
    """会話の文脈テスト"""
    print("=" * 60)
    print("Agent v2 テスト: 会話の文脈維持")
    print("=" * 60)

    # コールバック関数（推論ステップをリアルタイム表示）
    async def on_step(step: str):
        print(f"  [STEP] {step}")

    # テスト用UUID（実際のDBには保存されないがフォーマットは正しい）
    import uuid
    test_user_id = str(uuid.uuid4())
    test_session_id = str(uuid.uuid4())

    # Runner作成
    runner = await create_runner(
        session_id=test_session_id,
        user_id=test_user_id,
        on_reasoning_step=on_step,
    )

    # テスト会話
    conversations = [
        "新幹線を予約したい",
        "新大阪から博多、明日の19時",
        # "123456 と password",  # 認証情報（実際のテストでは有効な値が必要）
    ]

    for i, message in enumerate(conversations, 1):
        print(f"\n--- ターン {i} ---")
        print(f"User: {message}")
        print()

        result = await runner.process_message(message)

        print(f"State: {result['state']}")
        print(f"Dan: {result['response']}")

        if result.get("error"):
            print(f"Error: {result['error']}")

    # セッションの状態を確認
    print("\n" + "=" * 60)
    print("セッション内のMessages配列:")
    print("=" * 60)
    for msg in runner.session.messages:
        role = msg["role"].upper()
        content = msg["content"][:100] + "..." if len(msg["content"]) > 100 else msg["content"]
        print(f"[{role}] {content}")


async def test_credentials_recognition():
    """認証情報認識テスト"""
    print("\n" + "=" * 60)
    print("Agent v2 テスト: 認証情報の認識")
    print("=" * 60)

    async def on_step(step: str):
        print(f"  [STEP] {step}")

    # テスト用UUID
    import uuid
    test_user_id = str(uuid.uuid4())
    test_session_id = str(uuid.uuid4())

    runner = await create_runner(
        session_id=test_session_id,
        user_id=test_user_id,
        on_reasoning_step=on_step,
    )

    # シナリオ: 認証情報を聞かれて、渡す
    conversations = [
        "EX予約で新幹線を検索して",
        # この後、ダンが「認証情報をください」と言うはず
        # 次のメッセージで認証情報を渡す
        "会員IDは1234567890でパスワードはMyPass123です",
        # ダンは「認証情報を受け取りました」と理解するはず
    ]

    for i, message in enumerate(conversations, 1):
        print(f"\n--- ターン {i} ---")
        print(f"User: {message}")

        result = await runner.process_message(message)

        print(f"State: {result['state']}")
        print(f"Dan: {result['response'][:200]}...")

    print("\n[確認ポイント]")
    print("- ダンが2回目で「認証情報を受け取りました」と理解しているか？")
    print("- 「もう一度認証情報をください」と言っていないか？")


def test_skill_loading():
    """スキル読み込みテスト"""
    print("\n" + "=" * 60)
    print("テスト: スキル読み込み")
    print("=" * 60)

    SkillRegistry.load()
    skills = SkillRegistry.list_all()

    print(f"読み込まれたスキル数: {len(skills)}")
    for skill in skills:
        print(f"  - {skill.name}: {skill.display_name}")
        print(f"    service_type: {skill.service_type}")
        print(f"    service_name: {skill.service_name}")

    # EX予約スキルが読み込まれているか確認
    ex_skill = SkillRegistry.get("ex-reservation")
    if ex_skill:
        print("\n✅ EX予約スキルが正常に読み込まれました")
    else:
        print("\n❌ EX予約スキルが見つかりません")


def test_tool_parse():
    """ツールパーステスト"""
    print("\n" + "=" * 60)
    print("テスト: ツール呼び出しパース")
    print("=" * 60)

    # テストケース
    test_cases = [
        # 正常ケース
        """[STATE: RESEARCH]
[TOOL: ex-reservation search]
departure: 東京
arrival: 新大阪
date: 2026-01-20
time: 19:00

検索中です...""",

        # パラメータなしケース
        """[TOOL: ex-reservation search]
東京から新大阪まで検索します""",

        # ツールなしケース
        """こんにちは。新幹線の予約ですね。""",
    ]

    for i, test in enumerate(test_cases, 1):
        print(f"\n--- ケース {i} ---")
        print(f"入力: {test[:50]}...")
        result = parse_tool_call(test)
        if result:
            print(f"✅ パース成功:")
            print(f"   skill: {result['skill']}")
            print(f"   action: {result['action']}")
            print(f"   params: {result['params']}")
        else:
            print("   ツール呼び出しなし")


async def test_tool_execution():
    """ツール実行テスト（実際のExecutorを呼ぶ）"""
    print("\n" + "=" * 60)
    print("テスト: ツール実行（会話フロー）")
    print("=" * 60)

    async def on_step(step: str):
        print(f"  [STEP] {step}")

    import uuid
    test_user_id = str(uuid.uuid4())
    test_session_id = str(uuid.uuid4())

    runner = await create_runner(
        session_id=test_session_id,
        user_id=test_user_id,
        on_reasoning_step=on_step,
    )

    # ツール呼び出しを誘発するメッセージ
    message = "東京から新大阪、1月20日19時の新幹線を検索して"
    print(f"\nUser: {message}")

    result = await runner.process_message(message)

    print(f"\nState: {result['state']}")
    print(f"Response: {result['response'][:300]}...")

    if result.get("tool_results"):
        print(f"\n🔧 ツール実行結果:")
        for tr in result["tool_results"]:
            print(f"   {tr['tool']['skill']} {tr['tool']['action']}")
            print(f"   success: {tr['result'].get('success')}")
    else:
        print("\n⚠️ ツールは実行されませんでした")


if __name__ == "__main__":
    print("テストを開始します...\n")

    # スキル読み込みテスト
    test_skill_loading()

    # パーステスト
    test_tool_parse()

    # 会話テスト（LLM呼び出しあり）
    print("\n" + "=" * 60)
    print("LLMを使ったテストを実行しますか？ (y/n)")
    print("=" * 60)

    choice = input().strip().lower()
    if choice == "y":
        # 基本テスト
        asyncio.run(test_conversation())

        # 認証情報テスト
        asyncio.run(test_credentials_recognition())

        # ツール実行テスト
        asyncio.run(test_tool_execution())

    print("\n\nテスト完了")
