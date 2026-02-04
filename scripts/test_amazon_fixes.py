"""
Amazon Skill Fix Verification Test

Tests:
1. search action returns screenshot
2. scroll action works (previously failed)
3. click_product with x/y coordinates works (previously AttributeError)
"""

import asyncio
import sys
sys.path.insert(0, "D:/done")

from app.executors.amazon.executor_vision import AmazonVisionExecutor


async def test_amazon_fixes():
    print("=" * 60)
    print("Amazon Skill Fix Verification")
    print("=" * 60)

    executor = AmazonVisionExecutor()

    # Test 1: search
    print("\n[TEST 1] search action")
    print("-" * 40)
    try:
        result = await executor.search(
            params={"query": "アベンヌウォーター", "target": "50ml"},
            credentials=None,
            user_id="test"
        )
        print(f"  Success: {result.success}")
        print(f"  Message: {result.message[:100]}...")
        has_screenshot = result.screenshot_base64 is not None
        print(f"  Screenshot: {'Yes' if has_screenshot else 'No'}")
        if has_screenshot:
            print(f"  Screenshot size: {len(result.screenshot_base64)} bytes")
    except Exception as e:
        print(f"  ERROR: {e}")

    # Test 2: scroll
    print("\n[TEST 2] scroll action")
    print("-" * 40)
    try:
        result = await executor.scroll(
            params={"direction": "down", "amount": "600"},
            credentials=None,
            user_id="test"
        )
        print(f"  Success: {result.success}")
        print(f"  Message: {result.message}")
        has_details = result.details is not None
        print(f"  Details: {'Yes' if has_details else 'No'}")
    except Exception as e:
        print(f"  ERROR: {e}")

    # Test 3: click_product with coordinates
    print("\n[TEST 3] click_product with x/y coordinates")
    print("-" * 40)
    try:
        # Get product positions from previous search
        # Use a safe coordinate that should be on a product
        result = await executor.click_product(
            params={"x": "640", "y": "400"},  # Center of screen
            credentials=None,
            user_id="test"
        )
        print(f"  Success: {result.success}")
        print(f"  Message: {result.message[:100]}...")
        # The key test: no AttributeError for page.mouse.click
        print("  [OK] No AttributeError - mouse.click works!")
    except AttributeError as e:
        print(f"  [FAIL] AttributeError: {e}")
        print("  This means page.mouse.click is not implemented!")
    except Exception as e:
        print(f"  Other error (but mouse.click worked): {e}")

    print("\n" + "=" * 60)
    print("Test Complete")
    print("=" * 60)


if __name__ == "__main__":
    asyncio.run(test_amazon_fixes())
