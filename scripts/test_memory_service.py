"""
Test memory service - hybrid search with OpenAI embeddings
"""

import sys
sys.path.insert(0, "D:/done")

from app.services.memory_service import get_memory_service, WORKSPACE_DIR, MEMORY_DIR

def main():
    print("=" * 60)
    print("Memory Service Test")
    print("=" * 60)

    # Check directories
    print(f"\nWorkspace: {WORKSPACE_DIR}")
    print(f"Memory dir: {MEMORY_DIR}")
    print(f"Workspace exists: {WORKSPACE_DIR.exists()}")
    print(f"Memory dir exists: {MEMORY_DIR.exists()}")

    # Initialize service
    print("\n--- Initializing Memory Service ---")
    try:
        service = get_memory_service()
        print("OK: Service initialized")
    except Exception as e:
        print(f"ERROR: {e}")
        return

    # Create test memory file
    print("\n--- Creating Test Memory ---")
    test_content = """# 2026-02-06 会話ログ

## Amazon買い物
- 商品: アベンヌ ウォーター 50ml 4本セット
- 価格: 990円
- 状態: カートに入れた
- 購入予定日: 2026-02-07

## ユーザー情報
- 名前: 太郎
- 好きな色: 青
"""

    test_file = MEMORY_DIR / "2026-02-06.md"
    test_file.parent.mkdir(parents=True, exist_ok=True)
    test_file.write_text(test_content, encoding="utf-8")
    print(f"Created: {test_file}")

    # Index files
    print("\n--- Indexing Files ---")
    try:
        results = service.index_all()
        for filename, count in results.items():
            print(f"  {filename}: {count} chunks")
        print("OK: Indexing complete")
    except Exception as e:
        print(f"ERROR: {e}")
        import traceback
        traceback.print_exc()
        return

    # Test search
    print("\n--- Testing Search ---")
    test_queries = [
        "Amazon 買い物",
        "好きな色",
        "アベンヌ",
        "この前頼んだやつ",
    ]

    for query in test_queries:
        print(f"\nQuery: '{query}'")
        try:
            results = service.search(query, max_results=3)
            if results:
                for i, r in enumerate(results, 1):
                    print(f"  [{i}] {r['file_path']} (score: {r['score']})")
                    print(f"      {r['content'][:100]}...")
            else:
                print("  No results")
        except Exception as e:
            print(f"  ERROR: {e}")
            import traceback
            traceback.print_exc()

    print("\n" + "=" * 60)
    print("Test complete!")
    print("=" * 60)


if __name__ == "__main__":
    main()
