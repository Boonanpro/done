"""Offline validation for the message-search ILIKE query.

Talks to Supabase directly (no app.config, no server restart) to confirm the
full-history keyword search returns the expected message, in newest-first order,
with the same escaping the service uses.
"""
import os

from dotenv import dotenv_values
from supabase import create_client


def _escape(q: str) -> str:
    return q.replace("\\", "\\\\").replace("%", "\\%").replace("_", "\\_")


def search(client, room_id: str, query: str, limit: int = 50):
    q = (query or "").strip()
    if not q:
        return []
    escaped = _escape(q)
    res = (
        client.table("chat_messages")
        .select("id, room_id, sender_type, content, created_at")
        .eq("room_id", room_id)
        .ilike("content", f"%{escaped}%")
        .order("created_at", desc=True)
        .limit(limit)
        .execute()
    )
    return res.data or []


def main():
    env = dotenv_values(".env")
    url = env.get("SUPABASE_URL") or os.environ.get("SUPABASE_URL")
    key = env.get("SUPABASE_SERVICE_ROLE_KEY") or env.get("SUPABASE_KEY")
    client = create_client(url, key)

    # Find a room that has messages.
    members = client.table("chat_room_members").select("room_id").limit(50).execute()
    room_id = None
    total = 0
    for m in members.data or []:
        cnt = client.table("chat_messages").select("id", count="exact").eq("room_id", m["room_id"]).limit(1).execute()
        if (cnt.count or 0) > 0:
            room_id, total = m["room_id"], cnt.count
            break
    if not room_id:
        print("no room with messages")
        return
    print(f"room={room_id} total_messages={total}")

    # Derive a keyword that definitely exists in some message.
    sample = (
        client.table("chat_messages")
        .select("id, content, created_at")
        .eq("room_id", room_id)
        .neq("content", "")
        .order("created_at", desc=True)
        .limit(60)
        .execute()
    )
    keyword = None
    target_id = None
    for row in sample.data or []:
        c = (row.get("content") or "").replace("\n", " ")
        for token in c.split(" "):
            token = token.strip("。、!？?.,:：「」()（）#*-")
            if len(token) >= 3 and not token.startswith("["):
                keyword, target_id = token[:8], row["id"]
                break
        if keyword:
            break
    keyword = keyword or "ダン"
    print(f"keyword={keyword!r} expect_to_contain={target_id}")

    results = search(client, room_id, keyword, 50)
    print(f"hits={len(results)}")
    for r in results[:5]:
        print(f"  - {r['created_at']} [{r['sender_type']}] {(r['content'] or '')[:60]!r}")

    found_target = any(r["id"] == target_id for r in results)
    ordered = all(results[i]["created_at"] >= results[i + 1]["created_at"] for i in range(len(results) - 1))
    print(f"found_expected_message={found_target}")
    print(f"newest_first={ordered}")
    print(f"empty_query_returns_empty={search(client, room_id, '   ') == []}")

    # Wildcard-escaping: a literal '%' must not behave as a wildcard.
    pct = search(client, room_id, "%", 5)
    print(f"literal_percent_hits={len(pct)} (0 unless a message literally contains '%')")


if __name__ == "__main__":
    main()
