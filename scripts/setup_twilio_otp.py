"""
Twilio電話番号のVoice URLを設定して、着信を録音・文字起こしする
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
    
    client = Client(account_sid, auth_token)
    
    print("=" * 60)
    print("Setting up Twilio for OTP reception")
    print("=" * 60)
    
    # TwiML Binを使って着信を録音・文字起こし
    # Record + Transcribe で音声をテキスト化
    twiml_content = '''<?xml version="1.0" encoding="UTF-8"?>
<Response>
    <Say language="ja-JP">はい、録音を開始します。</Say>
    <Record 
        maxLength="30" 
        transcribe="true" 
        transcribeCallback="https://webhook.site/unique-id"
        playBeep="false"
    />
    <Say language="ja-JP">録音を終了しました。</Say>
</Response>'''
    
    print("\nTwiML for OTP recording:")
    print(twiml_content)
    
    # 電話番号の設定を更新
    print(f"\nUpdating phone number: {phone_number}")
    
    try:
        incoming_numbers = client.incoming_phone_numbers.list(phone_number=phone_number)
        if incoming_numbers:
            num = incoming_numbers[0]
            
            # TwiML Bin URL を使うか、直接 TwiML を返すエンドポイントが必要
            # ここでは簡易的に、Record + Gather を使う
            # 実際には webhook エンドポイントを用意する必要がある
            
            print(f"\nCurrent Voice URL: {num.voice_url}")
            print(f"Current Voice Method: {num.voice_method}")
            
            # 方法1: TwiML Bin を作成してそのURLを設定
            # 方法2: 自前のサーバーでTwiMLを返す
            
            print("\n" + "=" * 60)
            print("OPTIONS:")
            print("=" * 60)
            print("\n1. Use Twilio Console to create TwiML Bin:")
            print("   - Go to: https://console.twilio.com/us1/develop/twiml-bins")
            print("   - Create new TwiML Bin with the above content")
            print("   - Copy the URL and set it as Voice URL")
            print("\n2. Or use this simple TwiML that just records:")
            
            simple_twiml = "https://handler.twilio.com/twiml/EHxxxxxx"
            print(f"   Voice URL: {simple_twiml}")
            
        else:
            print(f"Phone number {phone_number} not found")
            
    except Exception as e:
        print(f"Error: {e}")


if __name__ == "__main__":
    main()

