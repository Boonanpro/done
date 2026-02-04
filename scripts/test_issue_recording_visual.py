"""
VisualAgent統合テスト: 実際のブラウザ操作でissue記録を確認

本番に近い形でテスト:
1. VisualAgentで実際のサイトを操作
2. max_stepsを小さくしてエラーを誘発
3. issueがDBに記録されるか確認
"""
import asyncio
import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).parent.parent))

from app.executors.visual.agent import VisualAgent
from app.executors.visual.recorder import BrowserRecorder, LOGS_DIR
from app.services.issue_tracker import IssueTracker


async def test_visual_agent_issue_recording():
    """VisualAgent統合テスト"""
    print("=" * 60)
    print("VisualAgent Integration Test - Issue Recording")
    print("=" * 60)

    # 1. 初期状態を確認
    print("\n[1] Checking initial issue count...")
    tracker = IssueTracker()
    initial_issues = await tracker.get_open_issues(limit=100)
    initial_count = len(initial_issues)
    print(f"    Initial open issues: {initial_count}")

    # 2. VisualAgentを作成（max_steps=2で確実にエラーを誘発）
    print("\n[2] Creating VisualAgent with max_steps=2...")
    recorder = BrowserRecorder(user_id=None)  # NULL user_id
    agent = VisualAgent(
        recorder=recorder,
        max_steps=2,  # 2ステップで強制終了
    )

    # 3. 実際のサイトでタスクを実行
    print("\n[3] Executing task on real site (rakuten.co.jp)...")
    print("    Task: 楽天でアベンヌウォーターを検索して購入")
    print("    max_steps=2 なので、必ず最大ステップエラーになるはず")

    result = await agent.execute_task(
        task="アベンヌウォーター 50ml を検索して、最安値の商品をカートに入れて購入手続きまで進めて",
        site="rakuten.co.jp",
        initial_url="https://www.rakuten.co.jp/",
    )

    print(f"\n    Task result: success={result.get('success')}")
    if result.get('error'):
        print(f"    Error: {result.get('error')[:100]}...")
    if result.get('message'):
        # 文字化け対策
        try:
            print(f"    Message: {result.get('message')[:100]}...")
        except:
            print(f"    Message: (encoding error)")
    print(f"    Steps executed: {result.get('steps', 'N/A')}")

    # 4. issueが記録されたか確認
    print("\n[4] Checking if issue was recorded...")
    await asyncio.sleep(2)  # DB反映待ち

    new_issues = await tracker.get_open_issues(limit=100)
    new_count = len(new_issues)
    print(f"    Open issues after test: {new_count}")

    if new_count > initial_count:
        print(f"    [OK] New issue(s) recorded: {new_count - initial_count}")

        # 新しいイシューを表示
        for issue in new_issues:
            if issue.get('id') not in [i.get('id') for i in initial_issues]:
                print(f"\n    New issue details:")
                print(f"      ID: {issue.get('id')}")
                print(f"      Type: {issue.get('issue_type')}")
                print(f"      Site: {issue.get('service_name')}")
                print(f"      Page URL: {issue.get('page_url')}")
                print(f"      Screenshots: {issue.get('screenshots')}")
                print(f"      HTML Snapshot: {issue.get('html_snapshot_path')}")
                print(f"      Fallback: {issue.get('fallback_action')}")
    else:
        print("    [NG] No new issues recorded")
        print("    Expected: EXECUTION_FAILED issue for max steps reached")

    # 5. ファイルが保存されたか確認
    print("\n[5] Checking saved files...")
    session_id = recorder.session.id if recorder.session else None
    if session_id:
        issues_dir = LOGS_DIR / session_id / "issues"
        print(f"    Session ID: {session_id}")
        print(f"    Issues dir: {issues_dir}")

        if issues_dir.exists():
            files = list(issues_dir.iterdir())
            print(f"    Files saved: {len(files)}")
            for f in files[:5]:
                print(f"      - {f.name} ({f.stat().st_size} bytes)")
            if files:
                print("    [OK] Files saved successfully")
        else:
            print("    [NG] Issues dir not created")
    else:
        print("    [WARN] No session ID available")

    print("\n" + "=" * 60)
    print("Integration Test Complete")
    print("=" * 60)

    # 結果を返す
    return new_count > initial_count


if __name__ == "__main__":
    success = asyncio.run(test_visual_agent_issue_recording())
    sys.exit(0 if success else 1)
