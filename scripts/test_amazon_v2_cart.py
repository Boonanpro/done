"""
Amazon Executor v2 カート・チェックアウトテスト
"""

import asyncio
import sys
sys.path.insert(0, "D:/done")

from app.executors.amazon.executor import AmazonExecutor


async def test_add_to_cart():
    """カート追加テスト"""
    print("=" * 60)
    print("Amazon Executor v2 - Cart & Checkout Test")
    print("=" * 60)

    executor = AmazonExecutor()

    # テスト用ASIN（アベンヌウォーター 50ml ¥689）
    test_asin = "B015KMYMQ0"

    print(f"\n[Test 1] Add to cart: ASIN={test_asin}")
    result = await executor.add_to_cart({
        "asin": test_asin,
        "quantity": 1
    })

    print(f"  Success: {result.success}")
    print(f"  Message: {result.message[:100] if result.message else 'None'}...")

    # 結果をファイルに保存
    with open("amazon_cart_test_result.txt", "w", encoding="utf-8") as f:
        f.write(f"=== Add to Cart Test ===\n")
        f.write(f"ASIN: {test_asin}\n")
        f.write(f"Success: {result.success}\n")
        f.write(f"Message: {result.message}\n")
        if result.details:
            f.write(f"Details: {result.details}\n")

    if not result.success:
        print("  Cart addition failed, skipping checkout test")
        return

    return result


async def test_checkout():
    """チェックアウトテスト"""
    print("\n[Test 2] Proceed to checkout")

    executor = AmazonExecutor()
    result = await executor.checkout({})

    print(f"  Success: {result.success}")
    print(f"  Message: {result.message[:100] if result.message else 'None'}...")

    # 結果をファイルに追記
    with open("amazon_cart_test_result.txt", "a", encoding="utf-8") as f:
        f.write(f"\n=== Checkout Test ===\n")
        f.write(f"Success: {result.success}\n")
        f.write(f"Message: {result.message}\n")
        if result.details:
            f.write(f"Details: {result.details}\n")

    return result


async def main():
    # カート追加テスト
    cart_result = await test_add_to_cart()

    if cart_result and cart_result.success:
        # チェックアウトテスト
        await test_checkout()

    print("\n" + "=" * 60)
    print("Results saved to: amazon_cart_test_result.txt")
    print("=" * 60)


if __name__ == "__main__":
    asyncio.run(main())
