"""
ElevenLabsに登録されている電話番号を確認
"""
import sys
sys.stdout.reconfigure(encoding='utf-8')

from elevenlabs.client import ElevenLabs

API_KEY = "sk_11bd74a5e92e5229ef0bf097bf6aa2e88c38909f7fcd1dbc"
client = ElevenLabs(api_key=API_KEY)

print("=" * 70)
print("ElevenLabs Phone Numbers")
print("=" * 70)
print()

try:
    # エージェント一覧を取得
    agents = client.conversational_ai.agents.get_all()
    
    for agent in agents:
        print(f"Agent: {agent.name} (ID: {agent.agent_id})")
        
        # 電話番号を取得しようとする
        try:
            # Phone numbers might be in agent details
            print(f"  Details: {agent}")
        except Exception as e:
            print(f"  Error getting details: {e}")
        print()
        
except Exception as e:
    print(f"Error: {e}")
    import traceback
    traceback.print_exc()
