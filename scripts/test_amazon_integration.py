"""
Amazon スキル統合テスト

ダンと会話してAmazonスキルが正しく機能するかテスト

使用方法:
    # テストユーザーで実行
    python scripts/test_amazon_integration.py

    # カスタムメッセージ
    python scripts/test_amazon_integration.py "アベンヌウォーター 50ml を探して"
"""

import asyncio
import sys
import os
import io
import requests
import json

# Windows コンソールの文字化け対策
if sys.platform == 'win32':
    sys.stdout = io.TextIOWrapper(sys.stdout.buffer, encoding='utf-8', errors='replace')
    sys.stderr = io.TextIOWrapper(sys.stderr.buffer, encoding='utf-8', errors='replace')

# プロジェクトルートをパスに追加
sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

BASE_URL = "http://127.0.0.1:8000/api/v1"


def test_health():
    """ヘルスチェック"""
    response = requests.get("http://127.0.0.1:8000/health")
    print(f"Health check: {response.status_code}")
    if response.status_code == 200:
        print(f"  Response: {response.json()}")
        return True
    return False


def get_test_token():
    """テストユーザーでログインしてトークンを取得"""
    # 環境変数またはデフォルトのテスト認証情報
    email = os.environ.get("TEST_EMAIL", "test@example.com")
    password = os.environ.get("TEST_PASSWORD", "testpassword")

    print(f"\nLogging in as {email}...")

    response = requests.post(
        f"{BASE_URL}/chat/login",
        json={"email": email, "password": password}
    )

    if response.status_code == 200:
        token = response.json().get("access_token")
        print(f"  Login successful!")
        return token
    else:
        print(f"  Login failed: {response.status_code}")
        print(f"  Response: {response.text}")

        # ユーザーが存在しない場合は作成を試みる
        print(f"\nTrying to register new user...")
        register_response = requests.post(
            f"{BASE_URL}/chat/register",
            json={
                "email": email,
                "password": password,
                "display_name": "Test User"
            }
        )

        if register_response.status_code == 200:
            print(f"  Registration successful! Logging in...")
            response = requests.post(
                f"{BASE_URL}/chat/login",
                json={"email": email, "password": password}
            )
            if response.status_code == 200:
                return response.json().get("access_token")
        else:
            print(f"  Registration failed: {register_response.status_code}")
            print(f"  Response: {register_response.text}")

    return None


def test_dan_message(token: str, message: str):
    """ダンにメッセージを送信してSSEレスポンスを受信"""
    print(f"\nSending message to Dan: {message}")
    print("=" * 60)

    headers = {
        "Authorization": f"Bearer {token}",
        "Content-Type": "application/json",
    }

    # SSEストリーミングで受信
    response = requests.post(
        f"{BASE_URL}/chat/dan/messages/stream",
        headers=headers,
        json={"content": message},
        stream=True,
        timeout=120,  # ブラウザ操作があるので長めに
    )

    print(f"Response status: {response.status_code}")

    if response.status_code != 200:
        print(f"Error: {response.text}")
        return

    # SSEイベントを処理
    print("\n--- SSE Events ---")
    ai_message = None

    for line in response.iter_lines():
        if line:
            line_str = line.decode('utf-8')
            if line_str.startswith('data: '):
                data_str = line_str[6:]  # 'data: ' を除去
                try:
                    data = json.loads(data_str)
                    event_type = data.get('type')

                    if event_type == 'process':
                        step = data.get('step', {})
                        label = step.get('label', '')
                        status = step.get('status', '')
                        print(f"  [{status}] {label}")

                    elif event_type == 'user_message':
                        msg = data.get('message', {})
                        print(f"\n  User: {msg.get('content', '')[:100]}...")

                    elif event_type == 'ai_message':
                        msg = data.get('message', {})
                        ai_message = msg.get('content', '')
                        print(f"\n  Dan: {ai_message[:200]}...")

                    elif event_type == 'error':
                        print(f"\n  ERROR: {data.get('message', '')}")

                    elif event_type == 'done':
                        print("\n  [DONE]")

                except json.JSONDecodeError:
                    print(f"  (non-JSON): {line_str}")

    print("\n" + "=" * 60)

    if ai_message:
        print(f"\n--- Full AI Response ---")
        print(ai_message)

    return ai_message


def main():
    # デフォルトのテストメッセージ
    default_message = "Amazonでアベンヌウォーター 50mlを探して"

    if len(sys.argv) > 1:
        message = " ".join(sys.argv[1:])
    else:
        message = default_message

    print("Amazon Skill Integration Test")
    print("=" * 60)

    # Step 1: ヘルスチェック
    if not test_health():
        print("Backend is not running!")
        print("Run: python scripts/start_backend.py")
        return

    # Step 2: 認証
    token = get_test_token()
    if not token:
        print("Failed to get authentication token!")
        print("Set TEST_EMAIL and TEST_PASSWORD environment variables")
        return

    # Step 3: ダンにメッセージ送信
    test_dan_message(token, message)


if __name__ == "__main__":
    main()
