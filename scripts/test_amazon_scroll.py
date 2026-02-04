"""Test Amazon scroll action directly"""
import sys
import os
import io
import requests
import json

if sys.platform == 'win32':
    sys.stdout = io.TextIOWrapper(sys.stdout.buffer, encoding='utf-8', errors='replace')
    sys.stderr = io.TextIOWrapper(sys.stderr.buffer, encoding='utf-8', errors='replace')

BASE_URL = "http://127.0.0.1:8000/api/v1"
EMAIL = "0aw325171@gmail.com"
PASSWORD = "Bold1315"

def main():
    # Message that explicitly asks to scroll
    message = "Amazonで検索した後、scroll downで下にスクロールして"

    print("Amazon Scroll Test")
    print("=" * 60)

    response = requests.get("http://127.0.0.1:8000/health")
    print(f"Health check: {response.status_code}")

    print(f"\nLogging in...")
    response = requests.post(
        f"{BASE_URL}/chat/login",
        json={"email": EMAIL, "password": PASSWORD}
    )

    if response.status_code != 200:
        print(f"Login failed: {response.text}")
        return

    token = response.json().get("access_token")
    print("Login successful!")

    print(f"\nSending: {message}")
    print("=" * 60)

    headers = {
        "Authorization": f"Bearer {token}",
        "Content-Type": "application/json",
    }

    response = requests.post(
        f"{BASE_URL}/chat/dan/messages/stream",
        headers=headers,
        json={"content": message},
        stream=True,
        timeout=180,
    )

    print(f"Response status: {response.status_code}")

    if response.status_code != 200:
        print(f"Error: {response.text}")
        return

    print("\n--- SSE Events ---")
    ai_message = None

    for line in response.iter_lines():
        if line:
            line_str = line.decode('utf-8')
            if line_str.startswith('data: '):
                data_str = line_str[6:]
                try:
                    data = json.loads(data_str)
                    event_type = data.get('type')

                    if event_type == 'process':
                        step = data.get('step', {})
                        label = step.get('label', '')
                        status = step.get('status', '')
                        print(f"  [{status}] {label}")

                    elif event_type == 'ai_message':
                        msg = data.get('message', {})
                        ai_message = msg.get('content', '')
                        print(f"\n  Dan: {ai_message[:400]}...")

                    elif event_type == 'done':
                        print("\n  [DONE]")

                except json.JSONDecodeError:
                    pass

    print("\n" + "=" * 60)
    if ai_message:
        print(f"\n--- Full Response ---")
        print(ai_message[:800])

if __name__ == "__main__":
    main()
