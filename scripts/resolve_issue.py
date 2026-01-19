"""
イシューを解決済みにする

使用例:
    python scripts/resolve_issue.py <issue_id>
    python scripts/resolve_issue.py <issue_id> --status in_progress
    python scripts/resolve_issue.py <issue_id> --status wont_fix
"""
import asyncio
import sys
from pathlib import Path

project_root = Path(__file__).parent.parent
sys.path.insert(0, str(project_root))

from app.services.issue_tracker import IssueTracker, IssueStatus


async def main():
    import argparse

    parser = argparse.ArgumentParser(description="イシューのステータスを更新")
    parser.add_argument("issue_id", help="イシューID")
    parser.add_argument(
        "--status",
        choices=["in_progress", "resolved", "wont_fix"],
        default="resolved",
        help="新しいステータス（デフォルト: resolved）",
    )

    args = parser.parse_args()

    tracker = IssueTracker()

    # イシュー情報を取得
    issue = await tracker.get_issue_details(args.issue_id)

    if not issue:
        print(f"Issue {args.issue_id} not found")
        sys.exit(1)

    print("=" * 80)
    print(f"Issue: {args.issue_id}")
    print("=" * 80)
    print(f"Type: {issue['issue_type']}")
    print(f"Service: {issue['service_name']} ({issue['service_type']})")
    print(f"Current Status: {issue['status']}")
    print()

    # ステータスを更新
    status_map = {
        "in_progress": IssueStatus.IN_PROGRESS,
        "resolved": IssueStatus.RESOLVED,
        "wont_fix": IssueStatus.WONT_FIX,
    }

    new_status = status_map[args.status]

    success = await tracker.update_issue_status(args.issue_id, new_status)

    if success:
        print(f"✅ Status updated to: {args.status}")
    else:
        print(f"❌ Failed to update status")
        sys.exit(1)


if __name__ == "__main__":
    asyncio.run(main())
