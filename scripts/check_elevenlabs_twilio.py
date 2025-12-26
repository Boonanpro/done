# -*- coding: utf-8 -*-
"""Check ElevenLabs Twilio Integration"""
import sys
sys.stdout.reconfigure(encoding='utf-8')

from elevenlabs.client import ElevenLabs

API_KEY = "sk_11bd74a5e92e5229ef0bf097bf6aa2e88c38909f7fcd1dbc"

client = ElevenLabs(api_key=API_KEY)

print("=" * 60)
print("ElevenLabs Twilio Integration")
print("=" * 60)

# Check Twilio integration
twilio_client = client.conversational_ai.twilio
print("\nTwilio client methods:")
print([m for m in dir(twilio_client) if not m.startswith('_')])

# Check agents
print("\n" + "=" * 60)
print("Listing existing agents...")
print("=" * 60)

try:
    agents = client.conversational_ai.agents.list()
    if hasattr(agents, 'agents'):
        agent_list = agents.agents
    else:
        agent_list = list(agents)
    
    if not agent_list:
        print("No agents found. Need to create one.")
    else:
        for agent in agent_list:
            print(f"\nAgent ID: {agent.agent_id}")
            print(f"  Name: {agent.name}")
            if hasattr(agent, 'conversation_config'):
                print(f"  Config: {agent.conversation_config}")
except Exception as e:
    print(f"Error listing agents: {e}")

# Check phone numbers
print("\n" + "=" * 60)
print("Checking phone numbers...")
print("=" * 60)

try:
    phone_numbers = client.conversational_ai.phone_numbers
    print(f"Phone numbers client: {phone_numbers}")
    print(f"Methods: {[m for m in dir(phone_numbers) if not m.startswith('_')]}")
except Exception as e:
    print(f"Error: {e}")



