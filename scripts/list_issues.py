"""
イシュー一覧を表示

実装すべき機能のイシューを優先度順に表示する。

使用例:
    python scripts/list_issues.py
    python scripts/list_issues.py --type executor_missing
    python scripts/list_issues.py --service-type airline
"""
import asyncio
import sys
from pathlib import Path

project_root = Path(__file__).parent.parent
sys.path.insert(0, str(project_root))

from app.services.issue_tracker import IssueTracker


async def main():
    import argparse

    parser = argparse.ArgumentParser(description="イシュー一覧を表示")
    parser.add_argument(
        "--type",
        help="イシュータイプでフィルタ (executor_missing, selector_outdated, search_failed, execution_failed)",
    )
    parser.add_argument(
        "--service-type",
        help="サービスタイプでフィルタ (airline, train, bus, hotel, product)",
    )
    parser.add_argument(
        "--limit",
        type=int,
        default=50,
        help="表示件数（デフォルト: 50）",
    )

    args = parser.parse_args()

    tracker = IssueTracker()

    print("=" * 80)
    print("Open Issues（優先度順）")
    print("=" * 80)
    print()

    issues = await tracker.get_open_issues(
        issue_type=args.type,
        service_type=args.service_type,
        limit=args.limit,
    )

    if not issues:
        print("オープンなイシューはありません。")
        return

    for i, issue in enumerate(issues, 1):
        print(f"{i}. [Priority: {issue['priority']}] {issue['service_name'] or issue['service_type'] or 'Unknown'}")
        print(f"   Type: {issue['issue_type']}")
        print(f"   Service: {issue['service_name']} ({issue['service_type']})")
        print(f"   Error: {issue['error_message']}")
        print(f"   Created: {issue['created_at']}")
        print(f"   Last occurred: {issue['last_occurred_at']}")
        print(f"   ID: {issue['id']}")
        print()

        # 提案される解決策を表示
        if issue.get("suggested_solutions"):
            solutions = issue["suggested_solutions"]
            if solutions:
                print(f"   💡 Suggested Solution:")
                for solution in solutions[:1]:  # 最初の1つだけ表示
                    print(f"      - {solution.get('description', 'N/A')}")
                    print(f"      - Effort: {solution.get('estimated_effort', 'unknown')}")
                print()

    print("=" * 80)
    print(f"Total: {len(issues)} open issues")
    print("=" * 80)
    print()
    print("詳細を見る: python scripts/show_issue.py <issue_id>")
    print("解決済みにする: python scripts/resolve_issue.py <issue_id>")


if __name__ == "__main__":
    asyncio.run(main())
