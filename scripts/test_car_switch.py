"""
号車切り替えテスト

座席表が開いた状態で:
1. 現在の号車番号を取得
2. 利用可能な号車一覧を取得
3. 別の号車に切り替え
4. 切り替え後の号車番号を確認
"""

import asyncio
import sys
sys.path.insert(0, "D:/done")

from app.tools.browser import get_executor_page
from app.executors.ex_reservation.login import login, check_logged_in, request_otp, close_otp_dialog, enter_otp
from app.executors.ex_reservation.search import search_trains, select_train
from app.executors.ex_reservation.models import SearchParams
from app.executors.ex_reservation.seat import select_product
from app.executors.ex_reservation.seat_map import (
    open_seat_map,
    get_all_car_numbers,
    change_car_number,
    _get_current_car_number,
    get_seat_map_info,
)
from app.executors.ex_reservation.constants import TIMEOUTS
from app.services.supabase_client import get_supabase_client
from app.services.encryption import get_encryption_service
from app.services.otp_service import get_otp_service


async def get_ex_credentials():
    """DBからex_reservationの認証情報を取得"""
    supabase = get_supabase_client().client
    encryption = get_encryption_service()

    result = supabase.table("credentials").select("*").eq(
        "service_name", "ex_reservation"
    ).limit(1).execute()

    if not result.data:
        print("ex_reservationの認証情報がDBに存在しません")
        return None, None

    stored = result.data[0]
    user_id = stored["user_id"]
    encrypted_bytes = stored["encrypted_data"].encode('utf-8')
    decrypted = encryption.decrypt_dict(encrypted_bytes)
    decrypted.pop("_credential_type", None)

    return user_id, decrypted


async def handle_otp(page, user_id):
    """OTP認証を処理"""
    print("OTP認証を処理中...")

    otp_request_result = await request_otp(page)
    if not otp_request_result.success:
        print(f"OTP送信失敗: {otp_request_result.message}")
        return False

    await close_otp_dialog(page)

    print("OTPの到着を待機中...")
    otp_service = get_otp_service()
    otp_code = await otp_service.wait_for_otp(
        user_id=user_id,
        service="ex_reservation",
        source="email",
        timeout_seconds=TIMEOUTS["otp_wait"] // 1000,
        poll_interval=5,
    )

    if not otp_code:
        print("OTPタイムアウト")
        return False

    print(f"OTP受信: {otp_code[:2]}****")

    otp_login_result = await enter_otp(page, otp_code)
    if not otp_login_result.success:
        print(f"OTP認証失敗: {otp_login_result.message}")
        return False

    print("OTP認証成功")
    return True


async def test_car_switch():
    """号車切り替えテスト"""

    # 認証情報を取得
    user_id, credentials = await get_ex_credentials()
    if not credentials:
        return

    print(f"認証情報取得: member_id={credentials.get('member_id', '')[:3]}***")

    page = await get_executor_page()
    print(f"現在のURL: {page.url}")

    # ログイン確認
    logged_in = await check_logged_in(page)
    if not logged_in:
        print("ログイン中...")
        login_result = await login(
            page,
            credentials.get("member_id", ""),
            credentials.get("password", ""),
        )
        if login_result.requires_otp:
            if not await handle_otp(page, user_id):
                return
        elif not login_result.success:
            print(f"ログイン失敗: {login_result.message}")
            return

    # 検索実行
    print("\n検索を実行します...")
    search_params = SearchParams(
        departure="新大阪",
        arrival="東京",
        date="2026-01-30",
        time="09:00",
        seat_position="窓側E",
        prefer_adjacent_empty=True,
    )

    search_result = await search_trains(page, search_params)
    if not search_result.success or not search_result.trains:
        print("検索に失敗しました")
        return

    # 最初の列車を選択
    train = search_result.trains[0]
    print(f"\n列車を選択: {train.train_name} {train.departure_time}発")
    if not await select_train(page, 0):
        print("列車選択に失敗しました")
        return

    await page.wait_for_timeout(2000)

    # 商品を選択
    print("\n商品を選択中...")
    if not await select_product(page, 0):
        print("商品選択に失敗しました")
        return

    await page.wait_for_timeout(2000)

    # 座席表を開く
    print("\n座席表を開きます...")
    if not await open_seat_map(page):
        print("座席表を開けませんでした")
        return

    await page.wait_for_timeout(3000)

    # ========================================
    # テスト開始
    # ========================================
    print("\n" + "="*60)
    print("号車切り替えテスト")
    print("="*60)

    # 1. 現在の号車番号を取得
    current_car = await _get_current_car_number(page)
    print(f"\n[1] 現在の号車: {current_car}号車")

    # 2. 利用可能な号車一覧を取得
    all_cars = await get_all_car_numbers(page)
    print(f"[2] 利用可能な号車: {all_cars}")

    if len(all_cars) < 2:
        print("切り替え可能な号車が1つしかありません")
        return

    # 3. 別の号車に切り替え
    # 現在の号車以外の最初の号車を選択
    target_car = next((c for c in all_cars if c != current_car), all_cars[0])
    print(f"\n[3] {target_car}号車に切り替え中...")

    success = await change_car_number(page, target_car)
    print(f"    切り替え結果: {'成功' if success else '失敗'}")

    # 4. 切り替え後の号車番号を確認
    new_car = await _get_current_car_number(page)
    print(f"[4] 切り替え後の号車: {new_car}号車")

    # 5. 座席情報を取得
    print("\n[5] 座席情報を取得中...")
    seat_info = await get_seat_map_info(page)
    if seat_info:
        print(f"    号車: {seat_info.car_number}号車")
        print(f"    空席数: {len(seat_info.available_seats)}")
        print(f"    空席例: {seat_info.available_seats[:5]}")
    else:
        print("    座席情報の取得に失敗しました")

    # 検証
    print("\n" + "="*60)
    if success and new_car == target_car:
        print("✓ 号車切り替えテスト成功!")
    else:
        print("✗ 号車切り替えテスト失敗")
        print(f"  期待: {target_car}号車, 実際: {new_car}号車")
    print("="*60)

    # スクリーンショット
    await page.screenshot(path="car_switch_test_result.png")
    print("\nスクリーンショット保存: car_switch_test_result.png")


if __name__ == "__main__":
    asyncio.run(test_car_switch())
