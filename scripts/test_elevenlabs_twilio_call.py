# -*- coding: utf-8 -*-
"""Test ElevenLabs + Twilio Outbound Call"""
import sys
sys.stdout.reconfigure(encoding='utf-8')

from elevenlabs.client import ElevenLabs

API_KEY = "sk_11bd74a5e92e5229ef0bf097bf6aa2e88c38909f7fcd1dbc"

client = ElevenLabs(api_key=API_KEY)

print("=" * 60)
print("ElevenLabs + Twilio Outbound Call Test")
print("=" * 60)

# First, check the existing agent
print("\n1. Checking existing agent...")
try:
    agent = client.conversational_ai.agents.get(agent_id="agent_01jz0ky1e0e5fsdypr3vm442qh")
    print(f"  Agent ID: {agent.agent_id}")
    print(f"  Name: {agent.name}")
    if hasattr(agent, 'conversation_config'):
        config = agent.conversation_config
        print(f"  Config: {config}")
except Exception as e:
    print(f"  Error: {e}")

# Check Twilio integration methods
print("\n2. Checking Twilio integration...")
try:
    twilio = client.conversational_ai.twilio
    print(f"  Methods: {[m for m in dir(twilio) if not m.startswith('_')]}")
    
    # Try to make an outbound call
    print("\n3. Attempting outbound call via ElevenLabs...")
    print("  (This requires Twilio credentials to be configured in ElevenLabs)")
    
    # Check if we need to configure Twilio in ElevenLabs first
    print("\n  Note: You need to configure Twilio credentials in ElevenLabs dashboard first:")
    print("  https://elevenlabs.io/app/conversational-ai/settings")
    
except Exception as e:
    print(f"  Error: {e}")

# Alternative: Use ElevenLabs for TTS only, handle Twilio separately
print("\n" + "=" * 60)
print("Alternative Approach: Use ElevenLabs TTS with Twilio Media Streams")
print("=" * 60)
print("""
1. Twilio receives call
2. Twilio Media Streams sends audio to our WebSocket
3. Our server:
   - Receives audio from Twilio
   - Sends to ElevenLabs STT (speech_to_text.realtime)
   - Sends text to Claude for response
   - Sends response to ElevenLabs TTS (text_to_speech.stream)
   - Sends audio back to Twilio
4. User hears AI response
""")

