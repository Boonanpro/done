# -*- coding: utf-8 -*-
"""Read-only: the MOST RECENT run + its room's NEWEST messages, to see the
just-now test 4 and pinpoint the duplication under the current code."""
import sys, os
sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))
from app.services.supabase_client import get_supabase_client

sb = get_supabase_client().client

run = (sb.table("agent_runs").select("id,room_id,state,created_at")
       .order("created_at", desc=True).limit(1).execute())
if not run.data:
    print("no runs"); sys.exit(0)
r = run.data[0]
rid = r["room_id"]
print(f"=== most recent run {r['id'][:8]} state={r['state']} created={r['created_at']} room={rid} ===")

msgs = (sb.table("chat_messages").select("id,sender_type,content,created_at,ai_context")
        .eq("room_id", rid).order("created_at", desc=True).limit(10).execute())
print("--- newest 10 messages (newest first) ---")
for m in msgs.data:
    c = (m.get("content") or "").replace("\n", " ")[:60]
    blocks = (m.get("ai_context") or {}).get("blocks") if m.get("ai_context") else None
    bsum = ""
    if blocks:
        bsum = " | blocks=[" + ",".join(b.get("type", "?") + ":" + ((b.get("text") or b.get("label") or "")[:14]) for b in blocks) + "]"
    print(f"  [{m['created_at'][11:19]}] {m['sender_type']}: {c}{bsum}")

ev = (sb.table("execution_events").select("event_type,tool_label,content,created_at")
      .eq("run_id", r["id"]).order("created_at", desc=False).limit(30).execute())
print(f"--- run events ({len(ev.data)}) ---")
for e in ev.data:
    lbl = e.get("tool_label") or (e.get("content") or "")
    print(f"  [{e['created_at'][11:19]}] {e['event_type']}: {str(lbl)[:55]}")
