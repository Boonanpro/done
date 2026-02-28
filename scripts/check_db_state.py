"""Check current state of user's projects and rooms."""
import os, sys, json
sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))
from dotenv import load_dotenv
load_dotenv(os.path.join(os.path.dirname(os.path.dirname(os.path.abspath(__file__))), '.env'))
from supabase import create_client

sb = create_client(
    os.environ.get("NEXT_PUBLIC_SUPABASE_URL") or os.environ.get("SUPABASE_URL"),
    os.environ.get("SUPABASE_SERVICE_ROLE_KEY")
)

REAL_USER = "2582a188-ff24-4a4f-b989-6063034d90b2"

# 1. Check all projects for user
print("=== PROJECTS FOR USER ===")
projects = sb.table("projects").select("id, title, room_id, status, created_at").eq("user_id", REAL_USER).order("created_at").execute()
print(f"Total: {len(projects.data)}")
for p in projects.data:
    room_tag = p.get('room_id', 'NO ROOM')
    print(f"  [{p['status']}] {p['title']} | room={room_tag} | created={p['created_at']}")

# 2. Check all chat rooms where user is a member
print("\n=== CHAT ROOMS (member) ===")
memberships = sb.table("chat_room_members").select("room_id").eq("user_id", REAL_USER).execute()
room_ids = [m["room_id"] for m in memberships.data]
print(f"Total memberships: {len(room_ids)}")

# 3. Check which rooms are project type
if room_ids:
    rooms = sb.table("chat_rooms").select("id, room_type, created_at").in_("id", room_ids).order("created_at").execute()
    project_rooms = [r for r in rooms.data if r.get("room_type") == "project"]
    other_rooms = [r for r in rooms.data if r.get("room_type") != "project"]
    print(f"Project rooms: {len(project_rooms)}")
    print(f"Other rooms: {len(other_rooms)}")

    # 4. Check which project rooms have a project row linked
    project_room_ids = {r["id"] for r in project_rooms}
    linked_room_ids = {p["room_id"] for p in projects.data if p.get("room_id")}
    orphaned = project_room_ids - linked_room_ids
    print(f"\nLinked to a project: {len(project_room_ids & linked_room_ids)}")
    print(f"Orphaned (no project row): {len(orphaned)}")

    if orphaned:
        print("\nOrphaned rooms:")
        for rid in orphaned:
            r = next((x for x in project_rooms if x["id"] == rid), None)
            # Get first message
            msgs = sb.table("chat_messages").select("content").eq("room_id", rid).eq("sender_type", "human").order("created_at").limit(1).execute()
            first = msgs.data[0]["content"][:60] if msgs.data else "(no msg)"
            print(f"  {rid} | created={r['created_at']} | msg={first}")

# 5. Check projects with room_id that doesn't exist in chat_rooms
print("\n=== PROJECTS WITH MISSING ROOMS ===")
all_room_ids_in_db = {r["id"] for r in rooms.data} if room_ids else set()
for p in projects.data:
    if p.get("room_id") and p["room_id"] not in all_room_ids_in_db:
        print(f"  MISSING ROOM: project={p['title']} room={p['room_id']}")

# 6. Check if any rooms have messages
print("\n=== MESSAGE COUNTS FOR PROJECT ROOMS ===")
for r in project_rooms[:5]:  # sample
    count = sb.table("chat_messages").select("id", count="exact").eq("room_id", r["id"]).execute()
    print(f"  room={r['id'][:8]}... msgs={count.count}")
