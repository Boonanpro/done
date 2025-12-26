# -*- coding: utf-8 -*-
"""Test ElevenLabs TTS with Japanese - High Quality"""
import sys
sys.stdout.reconfigure(encoding='utf-8')

from elevenlabs.client import ElevenLabs
from elevenlabs import play, save
import os

API_KEY = "sk_11bd74a5e92e5229ef0bf097bf6aa2e88c38909f7fcd1dbc"

client = ElevenLabs(api_key=API_KEY)

# Japanese text to speak
text = "こんにちは。私はAIアシスタントのダンです。何かお手伝いできることはありますか？"

print(f"Text: {text}")
print()

# Try different models for best Japanese quality
models_to_try = [
    ("eleven_multilingual_v2", "Best quality multilingual"),
    ("eleven_turbo_v2_5", "Fast turbo model"),
]

# Use a multilingual voice
voice_id = "JBFqnCBsd6RMkjVDRZzb"  # George - warm British accent, good for multilingual
voice_name = "George"

print(f"Using voice: {voice_name} ({voice_id})")
print()

for model_id, model_desc in models_to_try:
    print(f"Testing model: {model_id} ({model_desc})")
    try:
        audio = client.text_to_speech.convert(
            voice_id=voice_id,
            text=text,
            model_id=model_id,
            output_format="mp3_44100_128",
        )
        
        # Save to file
        filename = f"elevenlabs_test_{model_id.replace('-', '_')}.mp3"
        
        # Convert generator to bytes
        audio_bytes = b"".join(audio)
        
        with open(filename, "wb") as f:
            f.write(audio_bytes)
        
        print(f"  [OK] Saved: {filename} ({len(audio_bytes)} bytes)")
        
    except Exception as e:
        print(f"  [ERROR] {e}")
    print()

print("=" * 60)
print("Test completed! Check the generated MP3 files.")
print("=" * 60)



