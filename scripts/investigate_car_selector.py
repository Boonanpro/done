"""
号車選択セレクタの調査スクリプト

ダンと同じOTP自動化ロジックを使用：
1. DBから認証情報を取得
2. ログイン→OTP自動処理
3. 検索→列車選択→座席選択画面
4. 座席表を開いてセレクタを調査
"""

import asyncio
import sys
sys.path.insert(0, "D:/done")

from app.tools.browser import get_executor_page
from app.executors.ex_reservation.login import login, check_logged_in, request_otp, close_otp_dialog, enter_otp
from app.executors.ex_reservation.search import search_trains, select_train
from app.executors.ex_reservation.models import SearchParams
from app.executors.ex_reservation.seat import select_product
from app.executors.ex_reservation.seat_map import open_seat_map
from app.executors.ex_reservation.constants import TIMEOUTS
from app.services.supabase_client import get_supabase_client
from app.services.encryption import get_encryption_service
from app.services.otp_service import get_otp_service


async def get_ex_credentials():
    """DBからex_reservationの認証情報を取得"""
    supabase = get_supabase_client().client
    encryption = get_encryption_service()

    # ex_reservationの認証情報を持っているユーザーを検索
    result = supabase.table("credentials").select("*").eq(
        "service_name", "ex_reservation"
    ).limit(1).execute()

    if not result.data:
        print("ex_reservationの認証情報がDBに存在しません")
        return None, None

    stored = result.data[0]
    user_id = stored["user_id"]
    print(f"user_id: {user_id}")

    # 復号
    encrypted_bytes = stored["encrypted_data"].encode('utf-8')
    decrypted = encryption.decrypt_dict(encrypted_bytes)
    decrypted.pop("_credential_type", None)

    return user_id, decrypted


async def handle_otp(page, user_id):
    """OTP認証を処理（ダンと同じロジック）"""
    print("OTP認証を処理中...")

    # SMS送信ボタンをクリック
    otp_request_result = await request_otp(page)
    if not otp_request_result.success:
        print(f"OTP送信失敗: {otp_request_result.message}")
        return False

    # ダイアログを閉じる
    await close_otp_dialog(page)

    # OTPを取得
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

    # OTPを入力
    otp_login_result = await enter_otp(page, otp_code)
    if not otp_login_result.success:
        print(f"OTP認証失敗: {otp_login_result.message}")
        return False

    print("OTP認証成功")
    return True


async def investigate():
    """座席表の号車選択セレクタを調査"""

    # 認証情報を取得
    user_id, credentials = await get_ex_credentials()
    if not credentials:
        return

    print(f"認証情報取得: member_id={credentials.get('member_id', '')[:3]}***")

    page = await get_executor_page()
    print(f"現在のURL: {page.url}")

    # ログイン確認
    logged_in = await check_logged_in(page)
    print(f"ログイン状態: {logged_in}")

    if not logged_in:
        print("ログイン中...")
        login_result = await login(
            page,
            credentials.get("member_id", ""),
            credentials.get("password", ""),
        )
        print(f"ログイン結果: success={login_result.success}, requires_otp={login_result.requires_otp}")

        if login_result.requires_otp:
            if not await handle_otp(page, user_id):
                print("OTP処理に失敗しました")
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
    print(f"検索結果: success={search_result.success}, 列車数={len(search_result.trains)}")

    if not search_result.success or not search_result.trains:
        print("検索に失敗しました")
        # スクリーンショットを撮って終了
        await page.screenshot(path="investigation_search_failed.png")
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
    else:
        await page.wait_for_timeout(3000)

    # ここから調査開始
    print("\n" + "="*60)
    print("号車選択セレクタの調査")
    print("="*60)

    # JavaScriptで全てのselect要素の情報を取得
    select_info = await page.evaluate("""
        () => {
            const result = {
                pc_sel1: null,
                all_selects: []
            };

            // #pc-sel1 の情報
            const pcSel1 = document.querySelector('#pc-sel1');
            if (pcSel1) {
                result.pc_sel1 = {
                    tag: pcSel1.tagName,
                    id: pcSel1.id,
                    name: pcSel1.name || '',
                    className: pcSel1.className || '',
                    options: []
                };
                if (pcSel1.tagName === 'SELECT') {
                    const options = pcSel1.querySelectorAll('option');
                    options.forEach((opt, i) => {
                        result.pc_sel1.options.push({
                            index: i,
                            value: opt.value,
                            text: opt.textContent.trim(),
                            selected: opt.selected
                        });
                    });
                }
            }

            // 全select要素
            const selects = document.querySelectorAll('select');
            selects.forEach((sel, i) => {
                const selInfo = {
                    index: i,
                    id: sel.id || '',
                    name: sel.name || '',
                    className: sel.className || '',
                    options: []
                };
                const options = sel.querySelectorAll('option');
                options.forEach((opt, j) => {
                    selInfo.options.push({
                        index: j,
                        value: opt.value,
                        text: opt.textContent.trim(),
                        selected: opt.selected
                    });
                });
                result.all_selects.push(selInfo);
            });

            return result;
        }
    """)

    # 1. #pc-sel1 を確認
    if select_info.get("pc_sel1"):
        pc_sel1_info = select_info["pc_sel1"]
        print(f"\n[FOUND] #pc-sel1 が存在します")
        print(f"  タグ名: {pc_sel1_info['tag']}")
        print(f"  オプション数: {len(pc_sel1_info['options'])}")

        for opt in pc_sel1_info["options"]:
            print(f"    [{opt['index']}] value='{opt['value']}' text='{opt['text']}' selected={opt['selected']}")
    else:
        print("\n[NOT FOUND] #pc-sel1 は存在しません")

    # 2. 全select要素を探す
    print("\n" + "-"*40)
    print("全select要素を探索...")

    all_selects = select_info.get("all_selects", [])
    print(f"\nselect要素の数: {len(all_selects)}")

    for sel in all_selects:
        opts = sel["options"]
        first_text = opts[0]["text"] if opts else ""
        last_text = opts[-1]["text"] if opts else ""

        print(f"\n  [{sel['index']}] id='{sel['id']}' name='{sel['name']}' class='{sel['className']}'")
        print(f"      オプション数: {len(opts)}")
        if first_text:
            print(f"      最初: '{first_text[:50]}'")
        if last_text:
            print(f"      最後: '{last_text[:50]}'")

        # 号車関連かチェック
        is_car_related = (
            "号車" in first_text or
            "号車" in last_text or
            "car" in sel["id"].lower() or
            "sel" in sel["id"]
        )
        if is_car_related:
            print(f"      ★ 号車選択の可能性あり！")
            print(f"      全オプション:")
            for opt in opts[:15]:
                print(f"        [{opt['index']}] value='{opt['value']}' text='{opt['text']}'")

    # 3. 座席表エリアのHTML
    print("\n" + "-"*40)
    print("座席表エリアのHTML構造...")

    seat_area_html = await page.evaluate("""
        () => {
            const seatArea = document.querySelector('.seat-select');
            return seatArea ? seatArea.innerHTML : null;
        }
    """)

    if seat_area_html:
        # HTMLをファイルに保存
        with open("seat_map_html.txt", "w", encoding="utf-8") as f:
            f.write(seat_area_html)
        print(f"座席表HTML保存: seat_map_html.txt ({len(seat_area_html)}文字)")

        # selectタグ部分だけ抽出
        import re
        select_matches = re.findall(r'<select[^>]*>.*?</select>', seat_area_html, re.DOTALL)
        print(f"\nselect要素数（HTML内）: {len(select_matches)}")
        for i, sel_html in enumerate(select_matches[:3]):
            print(f"\n  [{i}] {sel_html[:300]}...")
    else:
        print(".seat-select 要素が見つかりません")

    # 4. スクリーンショット
    screenshot_path = "car_selector_investigation.png"
    await page.screenshot(path=screenshot_path)
    print(f"\n\nスクリーンショット保存: {screenshot_path}")

    print("\n" + "="*60)
    print("調査完了")
    print("="*60)


if __name__ == "__main__":
    asyncio.run(investigate())
