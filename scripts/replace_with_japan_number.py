"""
米国番号を削除して日本番号を購入
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
    print("Step 1: Delete US Number")
    print("=" * 60)
    
    us_number = "+16316145862"
    
    try:
        # 米国番号を検索
        incoming_numbers = client.incoming_phone_numbers.list(phone_number=us_number)
        
        if incoming_numbers:
            num = incoming_numbers[0]
            print(f"Found: {num.phone_number} (SID: {num.sid})")
            print("Deleting...")
            
            client.incoming_phone_numbers(num.sid).delete()
            print("DELETED!")
        else:
            print(f"Number {us_number} not found")
            
    except Exception as e:
        print(f"Error deleting: {e}")
        return
    
    print("\n" + "=" * 60)
    print("Step 2: Purchase Japan Number")
    print("=" * 60)
    
    japan_number = "+815017920839"
    forward_to = "+817083524060"
    
    try:
        print(f"Purchasing: {japan_number}")
        
        purchased = client.incoming_phone_numbers.create(
            phone_number=japan_number,
            voice_url=f"http://twimlets.com/forward?PhoneNumber={forward_to}",
            voice_method="GET"
        )
        
        print(f"\nSUCCESS!")
        print(f"New Phone Number: {purchased.phone_number}")
        print(f"Formatted: 050-1792-0839")
        print(f"\nCalls will be forwarded to: {forward_to}")
        print(f"\n*** Use 05017920839 for SmartEX registration ***")
        
    except Exception as e:
        print(f"Error purchasing: {e}")


if __name__ == "__main__":
    main()

