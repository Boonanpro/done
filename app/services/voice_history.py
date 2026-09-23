"""Saved room messages for reconnects; no model call or synthetic summary."""


def room_history(messages, budget=7400):
    # UTF-8 bytes conservatively bound token count, including message overhead.
    # ChatService returns newest first; models need chronological history.
    kept = []
    remaining = budget
    for message in sorted(messages, key=lambda m: m.get('created_at') or '', reverse=True)[:96]:
        text = (message.get('content') or '').strip().removeprefix('🎙').strip()
        if not text:
            continue
        role = 'user' if message.get('sender_type') in ('human', 'user') else 'assistant'
        text = f"[{message.get('created_at', '')}] {text}"
        cost = len(text.encode('utf-8')) + 40
        if cost > remaining:
            if not kept and remaining > 200:
                raw = text.encode('utf-8')
                half = (remaining - 120) // 2
                text = raw[:half].decode('utf-8', errors='ignore') + '\n[…中略。全文は部屋の履歴に保存されています…]\n' + raw[-half:].decode('utf-8', errors='ignore')
            else:
                break
        kept.append({'type': 'message', 'role': role, 'content': [{
            'type': 'input_text' if role == 'user' else 'output_text', 'text': text}]})
        remaining -= len(text.encode('utf-8')) + 40
    return list(reversed(kept))
