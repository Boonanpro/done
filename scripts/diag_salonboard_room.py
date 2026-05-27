# -*- coding: utf-8 -*-
"""Read-only diagnosis: what's actually persisted for the サロンボード room."""
import sys, os
sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))
from app.services.supabase_client import get_supabase_client

sb = get_supabase_client().client

proj = sb.table("projects").select("id,title,room_id,status,updated_at").ilike("title", "%サロンボード%").execute()
if not proj.data:
    print("No project matching サロンボード")
    sys.exit(0)
for p in proj.data:
    rid = p["room_id"]
    print(f"=== PROJECT {p['title']} status={p.get('status')} room={rid} updated={p.get('updated_at')} ===")
    msgs = (sb.table("chat_messages").select("sender_type,content,created_at")
            .eq("room_id", rid).order("created_at", desc=True).limit(8).execute())
    print("--- last messages (newest first) ---")
    for m in msgs.data:
        c = (m.get("content") or "").replace("\n", " ")[:90]
        print(f"  [{m['created_at']}] {m['sender_type']}: {c}")
    ev = (sb.table("execution_events").select("event_type,tool_label,content,created_at")
          .eq("room_id", rid).order("created_at", desc=True).limit(15).execute())
    print("--- last execution_events (newest first) ---")
    for e in ev.data:
        lbl = e.get("tool_label") or (e.get("content") or "")
        print(f"  [{e['created_at']}] {e['event_type']}: {str(lbl)[:70]}")
