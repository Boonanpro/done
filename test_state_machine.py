"""
StateMachine動作確認スクリプト
"""
import asyncio
import os
import sys

# Windows PowerShellのエンコード問題対策
sys.stdout.reconfigure(encoding='utf-8', errors='replace')

# プロジェクトルートをパスに追加
sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))

from app.agent.state_machine import StateMachine


async def test_task_message():
    """タスクメッセージのテスト"""
    print("=" * 60)
    print("テスト1: タスクメッセージ（新幹線予約）")
    print("=" * 60)
    
    message = "明日18時に新大阪から博多まで行きたい"
    print(f"\n[送信] {message}")
    
    sm = StateMachine(session_id="test-1", user_id="user-1")
    
    result = await sm.process_message(message)
    
    print(f"\n[状態] {result.get('state')}")
    print(f"\n[ナレーション]")
    for step in result.get('reasoning_steps', []):
        print(f"  - {step}")
    print(f"\n[応答]\n{result.get('response')}")
    
    return result


async def test_chat_message():
    """雑談メッセージのテスト"""
    print("\n" + "=" * 60)
    print("テスト2: 雑談メッセージ")
    print("=" * 60)
    
    message = "おはよう"
    print(f"\n[送信] {message}")
    
    sm = StateMachine(session_id="test-2", user_id="user-1")
    
    result = await sm.process_message(message)
    
    print(f"\n[状態] {result.get('state')}")
    print(f"\n[ナレーション]")
    for step in result.get('reasoning_steps', []):
        print(f"  - {step}")
    print(f"\n[応答]\n{result.get('response')}")
    print(f"\n[雑談判定] {result.get('is_chat', False)}")
    
    return result


async def main():
    print("StateMachine 動作確認開始\n")
    
    # テスト1: タスク
    try:
        await test_task_message()
    except Exception as e:
        print(f"エラー: {e}")
        import traceback
        traceback.print_exc()
    
    # テスト2: 雑談
    try:
        await test_chat_message()
    except Exception as e:
        print(f"エラー: {e}")
        import traceback
        traceback.print_exc()
    
    print("\n" + "=" * 60)
    print("動作確認完了")
    print("=" * 60)


if __name__ == "__main__":
    asyncio.run(main())
