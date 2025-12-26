# -*- coding: utf-8 -*-
"""Setup ElevenLabs Agent for Japanese AI Secretary with Claude"""
import sys
sys.stdout.reconfigure(encoding='utf-8')

from elevenlabs.client import ElevenLabs

API_KEY = "sk_11bd74a5e92e5229ef0bf097bf6aa2e88c38909f7fcd1dbc"

client = ElevenLabs(api_key=API_KEY)

print("=" * 60)
print("Setting up ElevenLabs Agent for Japanese AI Secretary")
print("=" * 60)

# Agent configuration
AGENT_ID = "agent_01jz0ky1e0e5fsdypr3vm442qh"

# System prompt for the AI secretary
SYSTEM_PROMPT = """あなたは「ダン」という名前のAI秘書です。
丁寧で親しみやすい日本語で応答してください。

役割:
- ユーザーの電話に応対する
- 用件を聞き取り、適切に対応する
- 必要に応じてメモを取る
- 重要な情報はユーザーに確認する

注意:
- 自然な会話を心がける
- 長すぎる応答は避ける
- 相手の話をよく聞く
- 不明点は確認する"""

# First message
FIRST_MESSAGE = "お電話ありがとうございます。AIアシスタントのダンです。ご用件をお伺いします。"

print("\n1. Updating agent configuration...")

try:
    # Update the agent to use Claude and Japanese settings
    updated_agent = client.conversational_ai.agents.update(
        agent_id=AGENT_ID,
        name="ダン (AI Secretary)",
        conversation_config={
            "agent": {
                "first_message": FIRST_MESSAGE,
                "language": "ja",
                "prompt": {
                    "prompt": SYSTEM_PROMPT,
                    "llm": "claude-3-5-sonnet",  # Use Claude
                    "temperature": 0.7,
                    "max_tokens": 500,
                }
            },
            "tts": {
                "model_id": "eleven_flash_v2_5",  # Fast model for low latency
                "voice_id": "JBFqnCBsd6RMkjVDRZzb",  # George - good for Japanese
            },
            "asr": {
                "quality": "high",
                "provider": "elevenlabs",
            },
            "turn": {
                "turn_timeout": 15.0,
                "silence_end_call_timeout": 60.0,
            }
        }
    )
    
    print(f"  [OK] Agent updated: {updated_agent.agent_id}")
    print(f"  Name: {updated_agent.name}")
    
except Exception as e:
    print(f"  [ERROR] Failed to update agent: {e}")
    print("\n  Trying to create a new agent instead...")
    
    try:
        new_agent = client.conversational_ai.agents.create(
            name="ダン (AI Secretary)",
            conversation_config={
                "agent": {
                    "first_message": FIRST_MESSAGE,
                    "language": "ja",
                    "prompt": {
                        "prompt": SYSTEM_PROMPT,
                        "llm": "claude-3-5-sonnet",
                        "temperature": 0.7,
                    }
                },
                "tts": {
                    "model_id": "eleven_flash_v2_5",
                    "voice_id": "JBFqnCBsd6RMkjVDRZzb",
                }
            }
        )
        print(f"  [OK] New agent created: {new_agent.agent_id}")
        AGENT_ID = new_agent.agent_id
    except Exception as e2:
        print(f"  [ERROR] Failed to create agent: {e2}")

# Now try to make a call via ElevenLabs Twilio integration
print("\n2. Attempting outbound call via ElevenLabs...")

try:
    result = client.conversational_ai.twilio.outbound_call(
        agent_id=AGENT_ID,
        agent_phone_number_id="",  # Need to configure in ElevenLabs
        customer_phone_number="+817083524060",
    )
    print(f"  [OK] Call initiated: {result}")
except Exception as e:
    print(f"  [ERROR] {e}")
    print("\n  Note: You need to configure Twilio in ElevenLabs dashboard:")
    print("  1. Go to https://elevenlabs.io/app/conversational-ai/settings")
    print("  2. Add Twilio credentials (Account SID, Auth Token)")
    print("  3. Add a phone number")

print("\n" + "=" * 60)
print("Setup complete!")
print("=" * 60)



