"""
Twilio録音を文字起こししてOTPを抽出
OpenAI Whisper APIまたはローカルWhisperを使用
"""
import os
import re
import requests
from dotenv import load_dotenv
from twilio.rest import Client

load_dotenv()

account_sid = os.getenv('TWILIO_ACCOUNT_SID')
auth_token = os.getenv('TWILIO_AUTH_TOKEN')
openai_api_key = os.getenv('OPENAI_API_KEY')

client = Client(account_sid, auth_token)

def download_recording(recording_sid: str, output_path: str = "recording.mp3"):
    """Twilio録音をダウンロード"""
    recording_url = f"https://api.twilio.com/2010-04-01/Accounts/{account_sid}/Recordings/{recording_sid}.mp3"

    print(f"Downloading recording {recording_sid}...")

    response = requests.get(recording_url, auth=(account_sid, auth_token))

    if response.status_code == 200:
        with open(output_path, 'wb') as f:
            f.write(response.content)
        print(f"  [OK] Saved to {output_path}")
        return output_path
    else:
        print(f"  [ERROR] Failed to download: {response.status_code}")
        return None

def transcribe_with_openai(audio_path: str) -> str:
    """OpenAI Whisper APIで文字起こし"""
    if not openai_api_key:
        print("[ERROR] OPENAI_API_KEY not found in .env")
        return None

    print(f"Transcribing with OpenAI Whisper API...")

    try:
        import openai
        openai.api_key = openai_api_key

        with open(audio_path, 'rb') as audio_file:
            transcript = openai.audio.transcriptions.create(
                model="whisper-1",
                file=audio_file,
                language="ja"
            )

        print(f"  [OK] Transcription complete")
        return transcript.text
    except Exception as e:
        print(f"  [ERROR] {e}")
        return None

def extract_otp(text: str) -> str:
    """テキストからOTPを抽出"""
    if not text:
        return None

    print(f"Transcript: {text}")
    print()

    # 連続した数字を探す
    digits = re.findall(r'\d+', text)
    for digit_group in digits:
        if len(digit_group) >= 4 and len(digit_group) <= 8:
            print(f"  -> OTP detected: {digit_group}")
            return digit_group

    return None

def get_latest_recording_sid(phone_number: str = "+18302591977", minutes: int = 10):
    """最新の録音SIDを取得"""
    from datetime import datetime, timedelta, timezone

    date_after = datetime.now(timezone.utc) - timedelta(minutes=minutes)

    calls = client.calls.list(
        to=phone_number,
        start_time_after=date_after,
        limit=5
    )

    for call in calls:
        recordings = client.recordings.list(call_sid=call.sid, limit=1)
        if recordings:
            return recordings[0].sid

    return None

if __name__ == "__main__":
    import sys

    # 引数で録音SIDを指定、なければ最新を取得
    if len(sys.argv) > 1:
        recording_sid = sys.argv[1]
    else:
        print("Getting latest recording...")
        recording_sid = get_latest_recording_sid()
        if not recording_sid:
            print("[ERROR] No recent recordings found")
            print()
            print("Usage:")
            print("  python scripts/transcribe_recording.py [RECORDING_SID]")
            exit(1)

    print("=" * 70)
    print(f"Transcribing recording: {recording_sid}")
    print("=" * 70)
    print()

    # 録音をダウンロード
    audio_path = download_recording(recording_sid)
    if not audio_path:
        exit(1)

    print()

    # 文字起こし
    transcript = transcribe_with_openai(audio_path)

    if transcript:
        print()
        otp = extract_otp(transcript)

        if otp:
            print()
            print("=" * 70)
            print(f"OTP Code: {otp}")
            print("=" * 70)
        else:
            print()
            print("=" * 70)
            print("No OTP found in transcript")
            print("=" * 70)

    # クリーンアップ
    if os.path.exists(audio_path):
        os.remove(audio_path)
        print()
        print(f"Cleaned up {audio_path}")
