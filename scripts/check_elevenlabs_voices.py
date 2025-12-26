# -*- coding: utf-8 -*-
"""Check ElevenLabs voices and models for Japanese support"""
from elevenlabs.client import ElevenLabs
import sys

# Set UTF-8 encoding for Windows
sys.stdout.reconfigure(encoding='utf-8')

API_KEY = "sk_11bd74a5e92e5229ef0bf097bf6aa2e88c38909f7fcd1dbc"

client = ElevenLabs(api_key=API_KEY)

print("=" * 60)
print("ElevenLabs Available Models (2025)")
print("=" * 60)

try:
    models = client.models.get_all()
    for model in models:
        print(f"\nModel ID: {model.model_id}")
        print(f"  Name: {model.name}")
        print(f"  Description: {model.description[:100] if model.description else 'N/A'}...")
        if hasattr(model, 'languages'):
            langs = [l.name for l in model.languages] if model.languages else []
            if 'Japanese' in langs or 'ja' in str(langs).lower():
                print(f"  Languages: {langs[:10]}... (JAPANESE SUPPORTED!)")
            else:
                print(f"  Languages: {langs[:5]}...")
except Exception as e:
    print(f"Error fetching models: {e}")

print("\n" + "=" * 60)
print("ElevenLabs Available Voices")
print("=" * 60)

try:
    voices_response = client.voices.get_all()
    voices = voices_response.voices if hasattr(voices_response, 'voices') else voices_response
    
    print(f"\nTotal voices: {len(voices)}")
    print("\nVoices with Japanese support or multilingual:")
    
    for voice in voices[:20]:  # First 20 voices
        labels = voice.labels if hasattr(voice, 'labels') else {}
        print(f"\n  Voice ID: {voice.voice_id}")
        print(f"  Name: {voice.name}")
        if hasattr(voice, 'description') and voice.description:
            print(f"  Description: {voice.description[:80]}...")
        if labels:
            print(f"  Labels: {labels}")
            
except Exception as e:
    print(f"Error fetching voices: {e}")

print("\n" + "=" * 60)
print("Recommended for Japanese (2025):")
print("=" * 60)
print("- eleven_multilingual_v2: Best quality for Japanese")
print("- eleven_turbo_v2_5: Fastest, good quality")
print("=" * 60)



