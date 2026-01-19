"""
Twilio で日本の電話番号（050）を検索・購入
"""
import os
import sys
sys.path.insert(0, "D:\\done")

from dotenv import load_dotenv
load_dotenv("D:\\done\\.env")

from twilio.rest import Client

def main():
    account_sid = os.getenv('TWILIO_ACCOUNT_SID')
    auth_token = os.getenv('TWILIO_AUTH_TOKEN')
    
    client = Client(account_sid, auth_token)
    
    print("=" * 60)
    print("Search for Japan Phone Numbers (050)")
    print("=" * 60)
    
    try:
        # 日本の電話番号を検索
        available_numbers = client.available_phone_numbers('JP').local.list(limit=10)
        
        if available_numbers:
            print(f"\nFound {len(available_numbers)} available numbers:\n")
            for i, num in enumerate(available_numbers):
                print(f"  [{i+1}] {num.phone_number}")
                print(f"      Friendly: {num.friendly_name}")
                print(f"      Voice: {num.capabilities.get('voice', False)}")
                print(f"      SMS: {num.capabilities.get('sms', False)}")
                print()
            
            # 最初の番号を購入
            print("-" * 60)
            response = input("Purchase the first number? (yes/no): ")
            
            if response.lower() == 'yes':
                number_to_buy = available_numbers[0].phone_number
                print(f"\nPurchasing: {number_to_buy}")
                
                purchased = client.incoming_phone_numbers.create(
                    phone_number=number_to_buy,
                    voice_url="http://twimlets.com/forward?PhoneNumber=+817083524060",
                    voice_method="GET"
                )
                
                print(f"\nSUCCESS!")
                print(f"Phone Number: {purchased.phone_number}")
                print(f"SID: {purchased.sid}")
                print(f"\nThis number is ready to receive calls and forward to your mobile.")
            else:
                print("Purchase cancelled.")
        else:
            print("No available numbers found in Japan.")
            print("\nTrying to list available number types...")
            
    except Exception as e:
        print(f"Error: {e}")
        print("\nNote: Japan numbers may require address verification.")
        print("Check: https://console.twilio.com/us1/develop/phone-numbers/regulatory-compliance")


if __name__ == "__main__":
    main()

