"""
日本の電話番号取得プロセス

1. Twilio認証テスト
2. 日本の番号検索
3. 料金確認
4. 購入（ユーザー承認後）
5. OTP受信設定
"""
import os
import sys
from pathlib import Path

project_root = Path(__file__).parent.parent
sys.path.insert(0, str(project_root))

from dotenv import load_dotenv
load_dotenv()

from twilio.rest import Client


def check_authentication():
    """Twilio認証テスト"""
    print("=" * 60)
    print("Step 1: Twilio認証テスト")
    print("=" * 60)

    account_sid = os.getenv('TWILIO_ACCOUNT_SID')
    auth_token = os.getenv('TWILIO_AUTH_TOKEN')

    if not account_sid or not auth_token:
        print("NG Twilio認証情報が.envに設定されていません")
        print("\n必要な環境変数:")
        print("  TWILIO_ACCOUNT_SID")
        print("  TWILIO_AUTH_TOKEN")
        return None

    try:
        client = Client(account_sid, auth_token)

        # アカウント情報を取得して認証テスト
        account = client.api.accounts(account_sid).fetch()

        print(f"OK 認証成功")
        print(f"  Account SID: {account.sid}")
        print(f"  Status: {account.status}")
        print(f"  Type: {account.type}")

        # 残高確認
        try:
            balance = client.balance.fetch()
            print(f"  Balance: {balance.balance} {balance.currency}")
        except Exception:
            print(f"  Balance: (取得できませんでした)")

        return client

    except Exception as e:
        print(f"NG 認証失敗: {e}")
        print("\nTwilioコンソールで認証情報を確認してください:")
        print("https://console.twilio.com/")
        return None


def search_japan_numbers(client):
    """日本の電話番号を検索（Voice + SMS対応を優先）"""
    print("\n" + "=" * 60)
    print("Step 2: 日本の電話番号を検索")
    print("=" * 60)

    all_numbers = []

    try:
        # 1. Mobile番号を検索（Voice + SMS対応の可能性が高い）
        print("\n[1] Mobile番号を検索中（Voice + SMS対応）...")
        try:
            mobile_numbers = client.available_phone_numbers('JP').mobile.list(limit=5)
            for num in mobile_numbers:
                if num.capabilities.get('voice') and num.capabilities.get('sms'):
                    all_numbers.append(num)
                    print(f"  OK 見つかりました: {num.phone_number} (Voice + SMS)")
        except Exception as e:
            print(f"  Mobile番号検索エラー: {e}")

        # 2. Local番号を検索（050番号）
        print("\n[2] Local番号を検索中（050番号）...")
        try:
            local_numbers = client.available_phone_numbers('JP').local.list(limit=10)
            for num in local_numbers:
                if num.capabilities.get('voice') and num.capabilities.get('sms'):
                    all_numbers.append(num)
                    print(f"  OK 見つかりました: {num.phone_number} (Voice + SMS)")
                elif num.capabilities.get('voice'):
                    all_numbers.append(num)
                    print(f"  見つかりました: {num.phone_number} (Voice のみ)")
        except Exception as e:
            print(f"  Local番号検索エラー: {e}")

        if not all_numbers:
            print("\nNG 利用可能な番号が見つかりませんでした")
            print("\n日本の番号には住所確認が必要な場合があります:")
            print("https://console.twilio.com/us1/develop/phone-numbers/regulatory-compliance")
            return None

        # Voice + SMS対応の番号を優先的にソート
        all_numbers.sort(key=lambda n: (
            n.capabilities.get('voice', False) and n.capabilities.get('sms', False),
            n.capabilities.get('voice', False)
        ), reverse=True)

        print("\n" + "-" * 60)
        print(f"合計 {len(all_numbers)}件の番号が見つかりました:\n")

        for i, num in enumerate(all_numbers[:5]):  # 最大5件表示
            has_voice = num.capabilities.get('voice', False)
            has_sms = num.capabilities.get('sms', False)

            status = ""
            if has_voice and has_sms:
                status = " ★推奨★"

            print(f"  [{i+1}] {num.phone_number}{status}")
            print(f"      Friendly: {num.friendly_name}")
            print(f"      Voice: {'○' if has_voice else '×'}")
            print(f"      SMS: {'○' if has_sms else '×'}")

            if has_voice and has_sms:
                print(f"      → 音声OTP・SMS OTP両方対応可能")
            elif has_voice:
                print(f"      → 音声OTPのみ対応（SMS OTP不可）")
            print()

        return all_numbers[:5]

    except Exception as e:
        print(f"NG エラー: {e}")

        if "regulatory" in str(e).lower() or "address" in str(e).lower():
            print("\n" + "=" * 60)
            print("日本の番号には住所確認が必要です")
            print("=" * 60)
            print("\n手順:")
            print("1. https://console.twilio.com/us1/develop/phone-numbers/regulatory-compliance")
            print("2. 'Regulatory Bundle' を作成（日本向け）")
            print("3. 住所・身分証明書を提出")
            print("4. 承認後、このスクリプトを再実行")

        return None


def get_pricing_info(client):
    """料金情報を取得"""
    print("\n" + "=" * 60)
    print("Step 3: 料金情報")
    print("=" * 60)

    try:
        # 日本の電話番号の料金を取得
        pricing = client.pricing.phone_numbers.countries('JP').fetch()

        print(f"国: {pricing.country}")

        if pricing.phone_number_prices:
            for price_info in pricing.phone_number_prices:
                number_type = price_info.get('number_type', 'unknown')
                base_price = price_info.get('base_price', 'N/A')
                current_price = price_info.get('current_price', 'N/A')

                print(f"\nタイプ: {number_type}")
                print(f"  初期費用: {base_price} USD")
                print(f"  月額料金: {current_price} USD")
        else:
            print("料金情報が取得できませんでした")
            print("\n一般的な日本の番号（050）の料金:")
            print("  初期費用: 約 $1.00 USD")
            print("  月額料金: 約 $1.00 USD")

        return True

    except Exception as e:
        print(f"料金情報取得エラー: {e}")
        print("\n一般的な日本の番号（050）の料金:")
        print("  初期費用: 約 $1.00 USD")
        print("  月額料金: 約 $1.00 USD")
        return True


def purchase_number(client, phone_number):
    """電話番号を購入"""
    print("\n" + "=" * 60)
    print("Step 4: 電話番号購入")
    print("=" * 60)

    print(f"\n購入する番号: {phone_number}")
    print("\nこの番号を購入すると課金されます。")
    print("概算: 初期費用 $1.00 + 月額 $1.00")

    response = input("\n購入しますか？ (yes/no): ")

    if response.lower() != 'yes':
        print("購入をキャンセルしました。")
        return None

    try:
        print("\n購入中...")

        # 番号を購入
        # Voice URLは後で設定するので、とりあえずデフォルト
        purchased = client.incoming_phone_numbers.create(
            phone_number=phone_number
        )

        print(f"\nOK 購入成功！")
        print(f"  Phone Number: {purchased.phone_number}")
        print(f"  SID: {purchased.sid}")
        print(f"  Friendly Name: {purchased.friendly_name}")

        return purchased

    except Exception as e:
        print(f"\nNG 購入失敗: {e}")
        return None


def configure_for_otp(client, phone_sid):
    """OTP受信用に設定"""
    print("\n" + "=" * 60)
    print("Step 5: OTP受信設定")
    print("=" * 60)

    print("\n次のステップ:")
    print("1. この番号をSmartEXに登録")
    print("2. Twilioで音声OTP受信のWebhookを設定")
    print("3. 音声を解析してOTPコードを抽出")

    print(f"\nPhone SID: {phone_sid}")
    print("\n設定方法はdocs/phase9c_voice_otp.mdを参照してください。")

    return True


def main():
    print("=" * 60)
    print("日本電話番号取得プロセス")
    print("=" * 60)
    print()

    # Step 1: 認証テスト
    client = check_authentication()
    if not client:
        return

    # Step 2: 番号検索
    available_numbers = search_japan_numbers(client)
    if not available_numbers:
        return

    # Step 3: 料金情報
    get_pricing_info(client)

    # Step 4: 購入（ユーザー承認）
    first_number = available_numbers[0].phone_number
    purchased = purchase_number(client, first_number)

    if purchased:
        # Step 5: OTP受信設定
        configure_for_otp(client, purchased.sid)

        print("\n" + "=" * 60)
        print("完了！")
        print("=" * 60)
        print(f"\n取得した番号: {purchased.phone_number}")
        print("\n.envファイルに追加してください:")
        print(f"TWILIO_JAPAN_PHONE_NUMBER={purchased.phone_number}")


if __name__ == "__main__":
    main()
