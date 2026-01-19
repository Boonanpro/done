"""
Twilio番号 +18302591977 に着信時、自動録音してOTP取得できるように設定
"""
import os
from dotenv import load_dotenv
from twilio.rest import Client

load_dotenv()

account_sid = os.getenv('TWILIO_ACCOUNT_SID')
auth_token = os.getenv('TWILIO_AUTH_TOKEN')

client = Client(account_sid, auth_token)

PHONE_NUMBER = "+18302591977"

# 録音するTwiML（着信を自動応答して全て録音）
# このTwiMLはtwimlets.comの公開サービスを使用
RECORDING_TWIML_URL = "http://twimlets.com/voicemail?Email=&Message=%E6%8E%A5%E7%B6%9A%E3%81%97%E3%81%A6%E3%81%84%E3%81%BE%E3%81%99&Transcribe=false"

print("=" * 70)
print(f"Setting up Voice OTP Recording for {PHONE_NUMBER}")
print("=" * 70)
print()

# 電話番号を取得
numbers = client.incoming_phone_numbers.list(phone_number=PHONE_NUMBER)

if not numbers:
    print(f"Error: Phone number {PHONE_NUMBER} not found")
    exit(1)

number = numbers[0]

print("Current configuration:")
print(f"  Voice URL: {number.voice_url}")
print(f"  Voice Method: {number.voice_method}")
print()

try:
    # オプション1: 簡単な方法 - 通話録音を有効化
    print("Enabling call recording for all incoming calls...")

    # 電話番号の設定を更新して、全ての通話を自動録音
    number.update(
        voice_url=RECORDING_TWIML_URL,
        voice_method='GET',
        status_callback_method='POST'
    )

    print("  [OK] Voice recording enabled!")
    print()
    print("=" * 70)
    print("SETUP COMPLETE")
    print("=" * 70)
    print()
    print(f"Phone number {PHONE_NUMBER} is now configured to:")
    print("  1. Auto-answer incoming calls with Japanese greeting")
    print("  2. Record the entire call (voicemail)")
    print("  3. Recordings accessible via Twilio API")
    print()
    print("Current Voice URL:", RECORDING_TWIML_URL)
    print()
    print("Next steps:")
    print("  1. Test by calling", PHONE_NUMBER)
    print("  2. Check recordings: python scripts/get_voice_otp.py")
    print("  3. Register this number in EX")
    print("  4. When OTP call comes, extract code from recording")
    print()
    print("For transcription:")
    print("  python scripts/transcribe_recording.py [RECORDING_SID]")

except Exception as e:
    print(f"Error: {e}")
    import traceback
    traceback.print_exc()
