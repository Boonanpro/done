"""
EXに電話番号を登録するヘルパースクリプト
Twilio番号 +18302591977 を登録し、OTP認証を自動化
"""
import os
import asyncio
import time
from datetime import datetime, timedelta
from dotenv import load_dotenv
from twilio.rest import Client

load_dotenv()

account_sid = os.getenv('TWILIO_ACCOUNT_SID')
auth_token = os.getenv('TWILIO_AUTH_TOKEN')

client = Client(account_sid, auth_token)

PHONE_NUMBER = "+18302591977"

def wait_for_otp_call(timeout_seconds=300):
    """
    OTP認証電話を待機して、録音からOTPコードを取得

    Args:
        timeout_seconds: タイムアウト時間（秒）

    Returns:
        str: OTPコード、取得できなければNone
    """
    print("=" * 70)
    print("Waiting for OTP call...")
    print("=" * 70)
    print()
    print(f"Phone number: {PHONE_NUMBER}")
    print(f"Timeout: {timeout_seconds} seconds")
    print()
    print("Please register this number in EX now.")
    print("This script will automatically detect the OTP call and extract the code.")
    print()

    start_time = datetime.utcnow()
    last_check_time = start_time

    while True:
        elapsed = (datetime.utcnow() - start_time).total_seconds()

        if elapsed > timeout_seconds:
            print()
            print("[TIMEOUT] No OTP call received within timeout period")
            return None

        # 5秒ごとにチェック
        time.sleep(5)

        # 最後のチェックから30秒以内の着信を確認
        date_after = datetime.utcnow() - timedelta(seconds=30)

        calls = client.calls.list(
            to=PHONE_NUMBER,
            start_time_after=date_after,
            limit=1
        )

        if calls:
            call = calls[0]
            print(f"[OK] Incoming call detected from {call.from_}")
            print(f"  Call SID: {call.sid}")
            print(f"  Status: {call.status}")
            print()

            # 通話が完了するまで待機（録音完了のため）
            print("Waiting for call to complete and recording to finish...")

            max_wait = 60  # 最大60秒待機
            for i in range(max_wait):
                time.sleep(2)

                # 通話情報を更新
                call = client.calls(call.sid).fetch()

                if call.status in ['completed', 'busy', 'failed', 'no-answer']:
                    print(f"  Call status: {call.status}")
                    break

                if i % 5 == 0:
                    print(f"  Still in progress... ({i*2}s)")

            # 録音を取得
            print()
            print("Retrieving recording...")

            # 録音が保存されるまで少し待機
            time.sleep(3)

            recordings = client.recordings.list(call_sid=call.sid, limit=1)

            if not recordings:
                print("  [WARN] No recording found for this call")
                print("  The call may have been too short or recording failed")
                print()
                continue

            recording = recordings[0]
            print(f"  Recording SID: {recording.sid}")
            print(f"  Duration: {recording.duration}s")
            print()

            # 録音URLを表示
            recording_url = f"https://api.twilio.com/2010-04-01/Accounts/{account_sid}/Recordings/{recording.sid}.mp3"
            print(f"Recording URL: {recording_url}")
            print("(Download with Twilio credentials)")
            print()

            # OTPコードを手動入力してもらう（文字起こしは別スクリプト）
            print("=" * 70)
            print("RECORDING CAPTURED")
            print("=" * 70)
            print()
            print("To extract OTP from recording:")
            print(f"  python scripts/transcribe_recording.py {recording.sid}")
            print()
            print("Or listen to the recording manually and enter OTP below:")
            print()

            try:
                otp = input("Enter OTP code (or press Enter to transcribe): ").strip()

                if otp:
                    return otp
                else:
                    # 文字起こしを試みる
                    print()
                    print("Attempting transcription...")

                    # transcribe_recording.pyの機能を呼び出す
                    try:
                        import sys
                        sys.path.insert(0, os.path.dirname(__file__))
                        from transcribe_recording import download_recording, transcribe_with_openai, extract_otp

                        audio_path = download_recording(recording.sid)
                        if audio_path:
                            transcript = transcribe_with_openai(audio_path)
                            if transcript:
                                otp = extract_otp(transcript)
                                if otp:
                                    print()
                                    print("=" * 70)
                                    print(f"OTP Code: {otp}")
                                    print("=" * 70)
                                    return otp

                            # クリーンアップ
                            if os.path.exists(audio_path):
                                os.remove(audio_path)
                    except Exception as e:
                        print(f"[ERROR] Transcription failed: {e}")
                        print("Please enter OTP manually")
                        otp = input("OTP code: ").strip()
                        return otp if otp else None

            except KeyboardInterrupt:
                print()
                print("[CANCELLED] User interrupted")
                return None

        # 進捗表示
        if int(elapsed) % 30 == 0 and elapsed > 0:
            print(f"Still waiting... ({int(elapsed)}s elapsed)")

if __name__ == "__main__":
    print()
    print("=" * 70)
    print("EX Phone Number Registration Helper")
    print("=" * 70)
    print()
    print("This script will help you register", PHONE_NUMBER, "in EX")
    print()
    print("Steps:")
    print("  1. Go to EX website and navigate to phone number registration")
    print("  2. Enter the number:", PHONE_NUMBER)
    print("  3. Click 'Send OTP' or '認証コードを送信'")
    print("  4. This script will automatically detect the call")
    print("  5. Enter the OTP code when prompted")
    print()

    input("Press Enter when you're ready to start...")
    print()

    otp_code = wait_for_otp_call(timeout_seconds=300)

    if otp_code:
        print()
        print("=" * 70)
        print(f"OTP CODE: {otp_code}")
        print("=" * 70)
        print()
        print("Enter this code in EX to complete registration.")
    else:
        print()
        print("Failed to retrieve OTP code.")
        print("Please check:")
        print("  1. The phone number was entered correctly in EX")
        print("  2. EX actually sent the OTP call")
        print("  3. Twilio number is configured correctly (run list_twilio_numbers.py)")
