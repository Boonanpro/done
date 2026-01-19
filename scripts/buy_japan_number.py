"""
Twilio で日本の電話番号（050）を購入
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
    print("Purchasing Japan Phone Number (050)")
    print("=" * 60)
    
    # 購入する番号
    number_to_buy = "+815017920839"
    
    try:
        print(f"\nPurchasing: {number_to_buy}")
        
        purchased = client.incoming_phone_numbers.create(
            phone_number=number_to_buy,
            voice_url="http://twimlets.com/forward?PhoneNumber=+817083524060",
            voice_method="GET"
        )
        
        print(f"\nSUCCESS!")
        print(f"Phone Number: {purchased.phone_number}")
        print(f"Friendly Name: {purchased.friendly_name}")
        print(f"SID: {purchased.sid}")
        print(f"\nThis number will forward calls to your mobile.")
        print(f"\nUse this number for SmartEX: 050-1792-0839")
        
    except Exception as e:
        print(f"Error: {e}")
        
        if "regulatory" in str(e).lower() or "address" in str(e).lower():
            print("\n" + "=" * 60)
            print("Japan numbers require address verification!")
            print("=" * 60)
            print("\n1. Go to: https://console.twilio.com/us1/develop/phone-numbers/regulatory-compliance")
            print("2. Create a 'Regulatory Bundle' for Japan")
            print("3. Submit your address/ID verification")
            print("4. After approval, run this script again")


if __name__ == "__main__":
    main()

