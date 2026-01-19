"""
日本の電話番号の詳細価格と機能を確認
"""
import os
import sys
from pathlib import Path

project_root = Path(__file__).parent.parent
sys.path.insert(0, str(project_root))

from dotenv import load_dotenv
load_dotenv()

from twilio.rest import Client


def main():
    account_sid = os.getenv('TWILIO_ACCOUNT_SID')
    auth_token = os.getenv('TWILIO_AUTH_TOKEN')

    client = Client(account_sid, auth_token)

    print("=" * 60)
    print("日本電話番号の詳細価格と機能")
    print("=" * 60)

    # 利用可能な番号を取得（最初の5件）
    print("\nLocal番号（050）を検索中...")
    local_numbers = client.available_phone_numbers('JP').local.list(limit=5)

    for i, num in enumerate(local_numbers):
        print(f"\n[{i+1}] {num.phone_number}")
        print(f"  Friendly Name: {num.friendly_name}")
        print(f"  Voice: {'○' if num.capabilities.get('voice') else '×'}")
        print(f"  SMS: {'○' if num.capabilities.get('sms') else '×'}")

        # 価格情報をTwilioコンソールURLで案内
        print(f"\n  この番号の詳細価格を確認:")
        print(f"  https://console.twilio.com/us1/develop/phone-numbers/manage/search?IsoCountry=JP")

    # 価格情報API
    print("\n" + "=" * 60)
    print("日本の番号タイプ別価格")
    print("=" * 60)

    try:
        pricing = client.pricing.phone_numbers.countries('JP').fetch()

        print(f"\n国: {pricing.country} ({pricing.iso_country})")
        print(f"通貨: {pricing.price_unit}")

        if pricing.phone_number_prices:
            for price_info in pricing.phone_number_prices:
                number_type = price_info.get('number_type', 'unknown')
                base_price = price_info.get('base_price', 'N/A')
                current_price = price_info.get('current_price', 'N/A')

                print(f"\n■ {number_type}")
                print(f"  初期費用: {base_price}")
                print(f"  月額料金: {current_price}")

                # タイプ別の説明
                if number_type == 'local':
                    print(f"  説明: 050番号（IP電話番号）")
                    print(f"  機能: Voice のみ（SMS 非対応）")
                    print(f"  用途: 音声OTP受信（SmartEXなど）")
                elif number_type == 'national':
                    print(f"  説明: 市外局番付き番号（03, 06など）")
                    print(f"  機能: Voice のみ（SMS 非対応）")
                    print(f"  用途: 音声OTP受信 + より信頼性の高い番号")
                elif number_type == 'mobile':
                    print(f"  説明: 携帯電話番号（080, 090など）")
                    print(f"  機能: Voice + SMS対応の可能性あり")
                    print(f"  用途: 音声OTP + SMS OTP両方")

        print("\n" + "-" * 60)
        print("推奨:")
        print("  - SmartEX音声OTP用: Local番号（050）が最安でOK")
        print("  - SMS OTPも必要: Mobile番号（高額）または海外番号検討")
        print("-" * 60)

    except Exception as e:
        print(f"価格情報取得エラー: {e}")

        print("\n一般的な価格（参考）:")
        print("  Local（050）: 約700円/月")
        print("  National（市外局番）: 約3,111円/月")
        print("  Mobile: さらに高額")


if __name__ == "__main__":
    main()
