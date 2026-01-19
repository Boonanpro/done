"""
住所SIDを使って日本番号を購入
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
    
    address_sid = "AD983bcd404894ef02afa78d541e1ec4d3"
    japan_number = "+815017920839"
    forward_to = "+817083524060"
    
    print("=" * 60)
    print("Purchasing Japan Number with Address")
    print("=" * 60)
    print(f"Number: {japan_number}")
    print(f"Address SID: {address_sid}")
    
    try:
        purchased = client.incoming_phone_numbers.create(
            phone_number=japan_number,
            address_sid=address_sid,
            voice_url=f"http://twimlets.com/forward?PhoneNumber={forward_to}",
            voice_method="GET"
        )
        
        print(f"\nSUCCESS!")
        print(f"Phone Number: {purchased.phone_number}")
        print(f"Formatted: 050-1792-0839")
        print(f"\nCalls will be forwarded to: {forward_to}")
        print(f"\n*** Use 05017920839 for SmartEX registration ***")
        
    except Exception as e:
        print(f"Error: {e}")


if __name__ == "__main__":
    main()

