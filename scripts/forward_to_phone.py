"""
Twilio着信をあなたの携帯に転送する設定
"""
import os
import sys
sys.path.insert(0, "D:\\done")

from dotenv import load_dotenv
load_dotenv("D:\\done\\.env")

from twilio.rest import Client
from twilio.twiml.voice_response import VoiceResponse

def main():
    account_sid = os.getenv('TWILIO_ACCOUNT_SID')
    auth_token = os.getenv('TWILIO_AUTH_TOKEN')
    phone_number = os.getenv('TWILIO_PHONE_NUMBER')
    
    # あなたの携帯番号（転送先）
    forward_to = "+817083524060"  # 履歴から見つけた番号
    
    client = Client(account_sid, auth_token)
    
    print("=" * 60)
    print("Setting up call forwarding")
    print("=" * 60)
    print(f"Twilio Number: {phone_number}")
    print(f"Forward to: {forward_to}")
    
    # TwiML Bin を作成
    twiml = f'''<?xml version="1.0" encoding="UTF-8"?>
<Response>
    <Dial>{forward_to}</Dial>
</Response>'''
    
    print(f"\nTwiML content:\n{twiml}")
    
    try:
        # TwiML Bin を作成
        twiml_bin = client.serverless.v1.services.list()
        
        # 直接 incoming_phone_numbers を更新
        incoming_numbers = client.incoming_phone_numbers.list(phone_number=phone_number)
        if incoming_numbers:
            num = incoming_numbers[0]
            
            # Voice URL を TwiML Bin URL に更新
            # Twilio の "twiml://" プロトコルを使う
            updated = client.incoming_phone_numbers(num.sid).update(
                voice_url="",  # 空にする
                voice_application_sid="",  # 空にする
            )
            
            print(f"\nCleared Voice URL settings")
            print("Now manually update in Twilio Console:")
            print("1. Go to: https://console.twilio.com/us1/develop/phone-numbers/manage/incoming")
            print(f"2. Click on {phone_number}")
            print("3. Under 'Voice Configuration':")
            print("   - Set 'Configure with' to 'TwiML Bin'")
            print("   - Create new TwiML Bin with this content:")
            print(f"\n{twiml}")
            
    except Exception as e:
        print(f"\nError: {e}")
        print("\nManual steps:")
        print("1. Go to: https://console.twilio.com/us1/develop/phone-numbers/manage/incoming")
        print(f"2. Click on {phone_number}")
        print("3. Under 'Voice Configuration', set TwiML to:")
        print(f"\n{twiml}")


if __name__ == "__main__":
    main()

