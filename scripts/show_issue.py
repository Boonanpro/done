"""
イシュー詳細を表示

使用例:
    python scripts/show_issue.py <issue_id>
"""
import asyncio
import sys
from pathlib import Path
import json

project_root = Path(__file__).parent.parent
sys.path.insert(0, str(project_root))

from app.services.issue_tracker import IssueTracker


async def main():
    if len(sys.argv) < 2:
        print("Usage: python scripts/show_issue.py <issue_id>")
        sys.exit(1)

    issue_id = sys.argv[1]

    tracker = IssueTracker()

    issue = await tracker.get_issue_details(issue_id)

    if not issue:
        print(f"Issue {issue_id} not found")
        sys.exit(1)

    print("=" * 80)
    print(f"Issue Details: {issue_id}")
    print("=" * 80)
    print()

    print(f"Type: {issue['issue_type']}")
    print(f"Status: {issue['status']}")
    print(f"Priority: {issue['priority']} (発生回数)")
    print()

    print(f"Service Type: {issue['service_type']}")
    print(f"Service Name: {issue['service_name']}")
    print()

    print(f"Error Message: {issue['error_message']}")
    print()

    print("Created: ", issue['created_at'])
    print("Updated: ", issue['updated_at'])
    print("Last Occurred: ", issue['last_occurred_at'])
    if issue.get('resolved_at'):
        print("Resolved: ", issue['resolved_at'])
    print()

    # 推論結果
    if issue.get('research_result'):
        print("-" * 80)
        print("Research Result (AI推論結果):")
        print("-" * 80)
        research = issue['research_result']
        print(f"  Task Type: {research.get('task_type')}")
        print(f"  Service Display Name: {research.get('service_display_name')}")
        print(f"  Params: {json.dumps(research.get('params', {}), indent=4, ensure_ascii=False)}")
        print()

    # 提案される解決策
    if issue.get('suggested_solutions'):
        print("-" * 80)
        print("Suggested Solutions:")
        print("-" * 80)
        for i, solution in enumerate(issue['suggested_solutions'], 1):
            print(f"{i}. {solution.get('type', 'N/A')}")
            print(f"   Description: {solution.get('description', 'N/A')}")
            print(f"   Estimated Effort: {solution.get('estimated_effort', 'unknown')}")
            if solution.get('suggested_file'):
                print(f"   Suggested File: {solution['suggested_file']}")
            if solution.get('suggested_steps'):
                print(f"   Steps:")
                for step in solution['suggested_steps']:
                    print(f"      - {step}")
            print()

    # 発生履歴
    if issue.get('occurrences'):
        print("-" * 80)
        print(f"Occurrences (最新{len(issue['occurrences'])}件):")
        print("-" * 80)
        for i, occ in enumerate(issue['occurrences'], 1):
            print(f"{i}. {occ['occurred_at']}")
            print(f"   Wish: {occ['original_wish']}")
            print(f"   Error: {occ['error_message']}")
            print()

    print("=" * 80)


if __name__ == "__main__":
    asyncio.run(main())
