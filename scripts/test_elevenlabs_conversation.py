# -*- coding: utf-8 -*-
"""Test ElevenLabs Conversational AI API"""
import sys
sys.stdout.reconfigure(encoding='utf-8')

from elevenlabs.client import ElevenLabs

API_KEY = "sk_11bd74a5e92e5229ef0bf097bf6aa2e88c38909f7fcd1dbc"

client = ElevenLabs(api_key=API_KEY)

print("=" * 60)
print("ElevenLabs Conversational AI Features")
print("=" * 60)

# Check what's available in conversational_ai
print("\nConversational AI client attributes:")
conv_ai = client.conversational_ai
print(dir(conv_ai))

# Check if there are agents
print("\n" + "=" * 60)
print("Checking for agents...")
print("=" * 60)

try:
    # Try to list agents
    if hasattr(conv_ai, 'agents'):
        print("Agents available!")
        agents = conv_ai.agents
        print(f"  Agents client: {agents}")
        print(f"  Methods: {[m for m in dir(agents) if not m.startswith('_')]}")
except Exception as e:
    print(f"Error: {e}")

print("\n" + "=" * 60)
print("Available features in ElevenLabs client:")
print("=" * 60)

features = [
    'text_to_speech',
    'speech_to_text', 
    'conversational_ai',
    'voices',
    'models',
]

for feature in features:
    if hasattr(client, feature):
        obj = getattr(client, feature)
        methods = [m for m in dir(obj) if not m.startswith('_')]
        print(f"\n{feature}:")
        print(f"  Methods: {methods[:10]}")



