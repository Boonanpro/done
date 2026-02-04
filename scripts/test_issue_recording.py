"""
イシュー記録機能の動作テスト

VisualAgentで意図的にエラーを発生させて:
1. issueがDBに記録されるか確認
2. スクショとHTMLがファイル保存されるか確認
"""
import asyncio
import sys
import uuid
from pathlib import Path

# プロジェクトルートをパスに追加
sys.path.insert(0, str(Path(__file__).parent.parent))

from app.executors.visual.agent import VisualAgent
from app.executors.visual.recorder import BrowserRecorder, LOGS_DIR
from app.services.issue_tracker import IssueTracker
from app.services.supabase_client import get_supabase_client


async def test_issue_recording():
    """イシュー記録のテスト"""
    print("=" * 60)
    print("Issue Recording Test")
    print("=" * 60)

    # 1. 記録前のイシュー数を確認
    print("\n[1] Checking initial issue count...")
    tracker = IssueTracker()
    initial_issues = await tracker.get_open_issues(limit=100)
    initial_count = len(initial_issues)
    print(f"    Initial open issues: {initial_count}")

    # 2. VisualAgentを作成して直接_record_issueをテスト
    print("\n[2] Creating VisualAgent and testing _record_issue directly...")
    # user_idをNoneにしてテスト（外部キー制約を回避）
    test_user_id = None
    print(f"    Test user ID: {test_user_id}")
    recorder = BrowserRecorder(user_id=test_user_id)
    agent = VisualAgent(recorder=recorder)

    # セッションを開始（_record_issueに必要）
    recorder.start_session(task="テスト用タスク: 楽天でアベンヌウォーター購入", site="rakuten.co.jp")

    # ブラウザを起動してスクリーンショットを取得
    from app.tools.browser import get_executor_page
    agent.page = await get_executor_page()
    await agent.page.goto("https://example.com")
    await agent.page.wait_for_timeout(2000)

    # スクリーンショットを取得
    screenshot_data = await agent.page.screenshot_base64()
    screenshot_base64 = screenshot_data.get("base64", "")
    print(f"    Screenshot size: {len(screenshot_base64)} bytes")

    # 直接_record_issueを呼び出し
    from app.services.issue_tracker import IssueType
    print("\n    Calling _record_issue directly...")
    await agent._record_issue(
        issue_type=IssueType.USER_INPUT_REQUIRED,
        error_message="テストエラー: レビュー投稿のドロップダウンが必須項目です",
        screenshot_base64=screenshot_base64,
        fallback_action="Amazonに切り替えて完遂",
    )
    print("    _record_issue called successfully")

    # 3. イシューが記録されたか確認
    print("\n[3] Checking if issue was recorded...")
    await asyncio.sleep(1)  # DB反映待ち

    new_issues = await tracker.get_open_issues(limit=100)
    new_count = len(new_issues)
    print(f"    Open issues after test: {new_count}")

    if new_count > initial_count:
        print(f"    OK: New issue(s) recorded: {new_count - initial_count}")

        # 最新のイシューを表示
        latest = new_issues[0]
        print(f"\n    Latest issue:")
        print(f"      ID: {latest.get('id')}")
        print(f"      Type: {latest.get('issue_type')}")
        print(f"      Task: {latest.get('original_wish')[:50]}...")
        print(f"      Site: {latest.get('service_name')}")
        print(f"      Page URL: {latest.get('page_url')}")
        print(f"      Screenshots: {latest.get('screenshots')}")
        print(f"      HTML Snapshot: {latest.get('html_snapshot_path')}")
    else:
        print("    NG: No new issues recorded")

    # 4. ファイルが保存されたか確認
    print("\n[4] Checking saved files...")
    session_id = recorder.session.id if recorder.session else None
    if session_id:
        issues_dir = LOGS_DIR / session_id / "issues"
        print(f"    Session ID: {session_id}")
        print(f"    Issues dir: {issues_dir}")

        if issues_dir.exists():
            files = list(issues_dir.iterdir())
            print(f"    Files in issues dir: {len(files)}")
            for f in files[:5]:
                print(f"      - {f.name} ({f.stat().st_size} bytes)")
            if files:
                print("    OK: Files saved successfully")
            else:
                print("    WARN: Issues dir exists but empty")
        else:
            print("    WARN: Issues dir not created (may be normal if no error occurred)")
    else:
        print("    WARN: No session ID available")

    # 5. DBのカラムが正しく機能しているか確認
    print("\n[5] Verifying DB columns...")
    wrapper = get_supabase_client()
    client = wrapper.client

    try:
        result = client.table("issues").select(
            "id, screenshots, html_snapshot_path, page_url, fallback_action"
        ).limit(1).execute()
        print("    OK: All new columns are accessible")
        if result.data:
            print(f"    Sample data: {result.data[0]}")
    except Exception as e:
        print(f"    NG: Column access error: {e}")

    print("\n" + "=" * 60)
    print("Test Complete")
    print("=" * 60)


if __name__ == "__main__":
    asyncio.run(test_issue_recording())
