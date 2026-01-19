"""
日本の050番号を購入（Voice OTP用）
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
    print("=" * 60)
    print("日本050番号購入")
    print("=" * 60)

    account_sid = os.getenv('TWILIO_ACCOUNT_SID')
    auth_token = os.getenv('TWILIO_AUTH_TOKEN')

    if not account_sid or not auth_token:
        print("NG Twilio認証情報が.envに設定されていません")
        return

    client = Client(account_sid, auth_token)

    try:
        # Step 1: 認証確認
        print("\n[1] Twilio認証確認...")
        account = client.api.accounts(account_sid).fetch()
        print(f"OK Account: {account.sid}")

        # Step 2: 050番号を検索
        print("\n[2] 050番号を検索中...")
        available_numbers = client.available_phone_numbers('JP').local.list(limit=3)

        if not available_numbers:
            print("NG 利用可能な050番号が見つかりませんでした")
            return

        print(f"OK {len(available_numbers)}件の050番号が見つかりました:\n")

        for i, num in enumerate(available_numbers):
            print(f"  [{i+1}] {num.phone_number}")
            print(f"      Voice: {'○' if num.capabilities.get('voice') else '×'}")
            print(f"      SMS: {'○' if num.capabilities.get('sms') else '×'}")

        # 最初の番号を選択
        selected_number = available_numbers[0].phone_number

        # Step 3: 購入確認
        print("\n" + "=" * 60)
        print("購入内容")
        print("=" * 60)
        print(f"\n番号: {selected_number}")
        print(f"タイプ: 050番号（Local）")
        print(f"料金: 約700円/月")
        print(f"機能: Voice（音声OTP受信可能）")
        print(f"用途: SmartEX音声OTP自動化")

        response = input("\nこの番号を購入しますか？ (yes/no): ")

        if response.lower() != 'yes':
            print("\n購入をキャンセルしました。")
            return

        # Step 4: 購入実行
        print("\n[3] 番号を購入中...")

        purchased = client.incoming_phone_numbers.create(
            phone_number=selected_number,
            friendly_name="SmartEX OTP Number"
        )

        print("\n" + "=" * 60)
        print("購入成功！")
        print("=" * 60)
        print(f"\n電話番号: {purchased.phone_number}")
        print(f"SID: {purchased.sid}")
        print(f"Friendly Name: {purchased.friendly_name}")

        # 日本形式で表示（050-1234-5678）
        phone_jp = purchased.phone_number.replace('+81', '0')
        if len(phone_jp) == 11:
            formatted = f"{phone_jp[:3]}-{phone_jp[3:7]}-{phone_jp[7:]}"
            print(f"\n日本形式: {formatted}")
            print(f"\nSmartEXに登録する番号: {formatted}")

        # Step 5: 次のステップ案内
        print("\n" + "=" * 60)
        print("次のステップ")
        print("=" * 60)
        print("\n1. SmartEXに電話番号を登録")
        print(f"   → マイページで {formatted} を登録")
        print("\n2. .envファイルに追加")
        print(f"   EX_OTP_PHONE_NUMBER={purchased.phone_number}")
        print("\n3. Twilio Webhook設定（音声OTP受信用）")
        print("   → 後で自動設定スクリプトを実行")

        print("\n" + "=" * 60)
        print("完了！")
        print("=" * 60)

    except Exception as e:
        print(f"\nエラー: {e}")
        import traceback
        traceback.print_exc()


if __name__ == "__main__":
    main()
