"""Test: Send message via SSE API, wait for project creation + auto-proposal"""
import sys
import json
import os
import time

sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))

import httpx

BASE = "http://localhost:8000/api/v1"
OUTPUT_FILE = os.path.join(os.environ['TEMP'], 'sse_output.txt')

MESSAGE = "noteで月30万円稼ぎたいので、投稿システムを作ってください。あまり執筆に時間をかけたくないので俺が下書きをラフに書いたら、あなたがそれを読んでいて興味を惹く構成に仮清書して、最終的に私が構成して送信ボタンを押したら、ノートに自動で投稿されるようなシステムを作ってほしいです。noteのアカウントも持ってないのでアカウント開設やお金を受け取るところの設定までお願いします。アカウントに使うメールは0aw325171@gmail.comが良いです。"

with open("test_token.txt") as f:
    token = f.read().strip()

headers = {"Authorization": f"Bearer {token}"}

print(f"[1] Sending message to main chat...")

events = []
project_id = None

with httpx.Client(timeout=300.0) as client:
    with client.stream(
        "POST",
        f"{BASE}/chat/dan/messages/stream",
        json={"content": MESSAGE},
        headers=headers,
    ) as response:
        print(f"    Status: {response.status_code}")
        if response.status_code != 200:
            print(f"    ERROR: {response.read().decode()}")
            sys.exit(1)

        buffer = ""
        for chunk in response.iter_text():
            buffer += chunk
            while "\n\n" in buffer:
                event_str, buffer = buffer.split("\n\n", 1)
                for line in event_str.strip().split("\n"):
                    if line.startswith("data: "):
                        data_str = line[6:]
                        try:
                            data = json.loads(data_str)
                            event_type = data.get("type", "")
                            events.append(data)

                            if event_type == "text_delta":
                                print(data.get("text", ""), end="", flush=True)
                            elif event_type == "tool_use":
                                print(f"\n[TOOL] {data.get('name', '')}")
                            elif event_type == "process":
                                label = data.get("step", {}).get("label", "")
                                print(f"\n[PROCESS] {label}")
                            elif event_type == "project_created":
                                project_id = data.get("project_id")
                                print(f"\n[PROJECT CREATED] {project_id}")
                            elif event_type == "done":
                                print(f"\n[DONE]")
                            elif event_type == "ai_message":
                                ai_content = data.get("message", {}).get("content", "")
                                print(f"\n[AI] {ai_content[:200]}")
                            elif event_type in ("user_message", "voice_announcement", "reasoning"):
                                pass
                            else:
                                print(f"\n[{event_type}]")
                        except json.JSONDecodeError:
                            pass

# Save events
with open(OUTPUT_FILE, 'w', encoding='utf-8') as f:
    json.dump(events, f, ensure_ascii=False, indent=2)

print(f"\n\n[2] Message sent. Waiting for auto-proposal...")

# Find project_id from events if not captured
if not project_id:
    for e in events:
        if e.get("type") == "process":
            label = e.get("step", {}).get("label", "")
            if "プロジェクト" in label and "作成" in label:
                print(f"    Project creation detected: {label}")

# Poll for proposal
from app.services.project_service import ProjectService
ps = ProjectService()

# Find the new project
projects = ps.supabase.table("projects").select("id, title, room_id, status").order("created_at", desc=True).limit(1).execute()
if projects.data:
    proj = projects.data[0]
    project_id = proj["id"]
    print(f"    Project: {proj['title']} (status={proj['status']})")

    # Wait for proposal (up to 5 minutes)
    for i in range(60):
        time.sleep(5)
        proposals = ps.supabase.table("project_proposals").select("id, status, content").eq("project_id", project_id).order("created_at", desc=True).limit(1).execute()
        if proposals.data:
            p = proposals.data[0]
            print(f"\n[PROPOSAL READY] status={p['status']}, length={len(p.get('content', ''))}")
            # Save proposal content
            with open(os.path.join(os.environ['TEMP'], 'proposal.txt'), 'w', encoding='utf-8') as f:
                f.write(p.get('content', ''))
            print(f"    Saved to proposal.txt")
            break
        print(f"    Waiting for proposal... {(i+1)*5}s")
    else:
        print("    TIMEOUT: No proposal after 5 minutes")
else:
    print("    ERROR: No project found")

print("[DONE]")
