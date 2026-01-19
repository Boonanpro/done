"""
Twilio番号に着信した最新の録音からOTPコードを抽出
"""
import os
import re
from datetime import datetime, timedelta
from dotenv import load_dotenv
from twilio.rest import Client

load_dotenv()

account_sid = os.getenv('TWILIO_ACCOUNT_SID')
auth_token = os.getenv('TWILIO_AUTH_TOKEN')

client = Client(account_sid, auth_token)

PHONE_NUMBER = "+18302591977"

def extract_otp_from_text(text: str) -> str:
    """
    テキストからOTPコードを抽出

    日本語の音声認識結果から数字を探す:
    - "ワンツースリーフォーファイブシックス" -> "123456"
    - "1 2 3 4 5 6" -> "123456"
    - "認証コードは123456です" -> "123456"
    """
    if not text:
        return None

    print(f"Transcript: {text}")
    print()

    # パターン1: 連続した数字（最も一般的）
    digits = re.findall(r'\d+', text)
    for digit_group in digits:
        if len(digit_group) >= 4 and len(digit_group) <= 8:
            print(f"  -> OTP detected: {digit_group}")
            return digit_group

    # パターン2: 日本語の数字読み（カタカナ）
    japanese_digits = {
        'ゼロ': '0', 'れい': '0',
        'いち': '1', 'ワン': '1',
        'に': '2', 'ツー': '2',
        'さん': '3', 'スリー': '3',
        'よん': '4', 'し': '4', 'フォー': '4',
        'ご': '5', 'ファイブ': '5',
        'ろく': '6', 'シックス': '6',
        'なな': '7', 'しち': '7', 'セブン': '7',
        'はち': '8', 'エイト': '8',
        'きゅう': '9', 'く': '9', 'ナイン': '9',
    }

    result = []
    words = text.split()
    for word in words:
        for jp, digit in japanese_digits.items():
            if jp in word:
                result.append(digit)
                break

    if len(result) >= 4:
        otp = ''.join(result)
        print(f"  -> OTP detected from Japanese: {otp}")
        return otp

    return None

def get_voice_otp(minutes=5, auto_transcribe=False):
    """
    指定した分数以内に受信した最新の通話録音からOTPを抽出

    Args:
        minutes: 何分前までの録音を確認するか
        auto_transcribe: Twilioの自動文字起こしを使うか（有料）

    Returns:
        str: OTPコード、見つからなければNone
    """
    print(f"Checking recordings from last {minutes} minutes...")
    print(f"Phone number: {PHONE_NUMBER}")
    print()

    # 指定時間以降の着信通話を取得
    date_after = datetime.utcnow() - timedelta(minutes=minutes)

    calls = client.calls.list(
        to=PHONE_NUMBER,
        start_time_after=date_after,
        limit=10
    )

    if not calls:
        print("No calls found in the specified time range.")
        return None

    print(f"Found {len(calls)} call(s):")
    print()

    for call in calls:
        print(f"Call from: {call.from_}")
        print(f"  Time: {call.start_time}")
        print(f"  Status: {call.status}")
        print(f"  Duration: {call.duration}s")

        # この通話の録音を取得
        recordings = client.recordings.list(call_sid=call.sid)

        if not recordings:
            print("  -> No recordings found")
            print()
            continue

        for recording in recordings:
            print(f"  Recording SID: {recording.sid}")
            print(f"  Duration: {recording.duration}s")

            # 録音のURLを取得
            recording_url = f"https://api.twilio.com/2010-04-01/Accounts/{account_sid}/Recordings/{recording.sid}.mp3"
            print(f"  Audio URL: {recording_url}")

            # 文字起こしがある場合
            if recording.transcription:
                transcript = recording.transcription
                print(f"  Transcript: {transcript}")
                otp = extract_otp_from_text(transcript)
                if otp:
                    return otp
            else:
                print("  [WARN] No transcription available")
                print("  [INFO] To enable transcription, set transcribe=true in TwiML <Record>")
                print("  [INFO] Or manually transcribe using: scripts/transcribe_recording.py")
                print()
                print("  For now, you need to manually listen to the recording:")
                print(f"  {recording_url}")
                print("  (Use Twilio account credentials to download)")

        print()

    return None

if __name__ == "__main__":
    otp = get_voice_otp(minutes=10)

    if otp:
        print("=" * 70)
        print(f"OTP Code: {otp}")
        print("=" * 70)
    else:
        print("=" * 70)
        print("No OTP found")
        print("=" * 70)
        print()
        print("Next steps:")
        print("  1. Make sure setup_voice_otp_recording.py was run")
        print("  2. Trigger an OTP call to", PHONE_NUMBER)
        print("  3. Wait a few seconds for recording to complete")
        print("  4. Run this script again")
