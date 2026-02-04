"""
E2Eテスト: フロントエンドからVisualAgentを動かしてissue記録を確認

本番に近い形でテスト:
1. チャットAPIを叩いてVisualAgentが呼ばれるリクエストを送信
2. エラーが発生するシナリオを実行
3. issueがDBに記録されるか確認
"""
import asyncio
import httpx
import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).parent.parent))

from app.services.issue_tracker import IssueTracker
from app.services.supabase_client import get_supabase_client

BASE_URL = "http://127.0.0.1:8000"


async def test_e2e_issue_recording():
    """E2Eテスト"""
    print("=" * 60)
    print("E2E Issue Recording Test")
    print("=" * 60)

    # 1. 初期状態を確認
    print("\n[1] Checking initial issue count...")
    tracker = IssueTracker()
    initial_issues = await tracker.get_open_issues(limit=100)
    initial_count = len(initial_issues)
    print(f"    Initial open issues: {initial_count}")

    # 2. セッションを作成
    print("\n[2] Creating chat session...")
    async with httpx.AsyncClient(timeout=180.0) as client:
        # セッション作成
        session_resp = await client.post(
            f"{BASE_URL}/api/chat/sessions",
            json={"user_id": "e6a171f8-acc0-481c-a51b-8df1916d5e5d"}
        )
        if session_resp.status_code != 200:
            print(f"    ERROR: Failed to create session: {session_resp.text}")
            return

        session_data = session_resp.json()
        session_id = session_data.get("session_id")
        print(f"    Session ID: {session_id}")

        # 3. VisualAgentが呼ばれるメッセージを送信
        # max_stepsが少ないので、複雑なタスクでエラーを誘発
        print("\n[3] Sending message to trigger VisualAgent...")
        message = "メルカリで中古のiPhone 15を探して、一番安いものを購入して"
        print(f"    Message: {message}")

        # SSEエンドポイントを使用
        print("\n[4] Waiting for response (this may take a while)...")
        response_text = ""
        try:
            async with client.stream(
                "POST",
                f"{BASE_URL}/api/chat/sessions/{session_id}/messages/stream",
                json={"message": message},
                timeout=180.0,
            ) as response:
                async for line in response.aiter_lines():
                    if line.startswith("data: "):
                        data = line[6:]
                        if data == "[DONE]":
                            break
                        # 進捗を表示
                        if "visual" in data.lower() or "step" in data.lower():
                            print(f"    {data[:80]}...")
                        response_text += data + "\n"
        except Exception as e:
            print(f"    Request error: {e}")

        print(f"\n    Response received (length: {len(response_text)} chars)")

    # 5. issueが記録されたか確認
    print("\n[5] Checking if issue was recorded...")
    await asyncio.sleep(2)  # DB反映待ち

    new_issues = await tracker.get_open_issues(limit=100)
    new_count = len(new_issues)
    print(f"    Open issues after test: {new_count}")

    if new_count > initial_count:
        print(f"    [OK] New issue(s) recorded: {new_count - initial_count}")

        # 最新のイシューを表示
        for issue in new_issues[:3]:
            if issue.get('id') not in [i.get('id') for i in initial_issues]:
                print(f"\n    New issue:")
                print(f"      ID: {issue.get('id')}")
                print(f"      Type: {issue.get('issue_type')}")
                print(f"      Site: {issue.get('service_name')}")
                print(f"      Page URL: {issue.get('page_url')}")
                print(f"      Screenshots: {issue.get('screenshots')}")
                print(f"      HTML Snapshot: {issue.get('html_snapshot_path')}")
    else:
        print("    [INFO] No new issues recorded")
        print("    This may be normal if VisualAgent succeeded or was not triggered")

    # 6. DBの全イシューを確認
    print("\n[6] All issues in DB:")
    wrapper = get_supabase_client()
    result = wrapper.client.table("issues").select(
        "id, issue_type, service_name, page_url, created_at"
    ).order("created_at", desc=True).limit(5).execute()

    if result.data:
        for issue in result.data:
            print(f"    - {issue.get('issue_type')}: {issue.get('service_name')} @ {issue.get('page_url', 'N/A')[:50]}")
    else:
        print("    No issues in DB")

    print("\n" + "=" * 60)
    print("E2E Test Complete")
    print("=" * 60)


if __name__ == "__main__":
    asyncio.run(test_e2e_issue_recording())
