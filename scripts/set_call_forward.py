"""
Twilio着信をあなたの携帯に転送
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
    phone_number = os.getenv('TWILIO_PHONE_NUMBER')
    
    # 転送先（あなたの携帯）
    forward_to = "+817083524060"
    
    client = Client(account_sid, auth_token)
    
    print(f"Setting up forwarding: {phone_number} -> {forward_to}")
    
    # TwiML URL (Twilio's built-in forwarding)
    # http://twimlets.com/forward?PhoneNumber=転送先番号
    forward_url = f"http://twimlets.com/forward?PhoneNumber={forward_to}"
    
    try:
        incoming_numbers = client.incoming_phone_numbers.list(phone_number=phone_number)
        if incoming_numbers:
            num = incoming_numbers[0]
            
            # Voice URL を転送用に設定
            updated = client.incoming_phone_numbers(num.sid).update(
                voice_url=forward_url,
                voice_method="GET"
            )
            
            print(f"\nSUCCESS!")
            print(f"Voice URL set to: {forward_url}")
            print(f"\nNow all calls to {phone_number} will be forwarded to {forward_to}")
            print("\nPress 自動音声案内発信 button on SmartEX!")
            
    except Exception as e:
        print(f"Error: {e}")


if __name__ == "__main__":
    main()

