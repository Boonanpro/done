"""Saved room messages for reconnects; no model call or synthetic summary."""

# The Live session takes at most 8192 tokens of initial items (2026-10-02: a room whose newest messages were long reports
# with tables went over and every call failed with 400 "Initial items must not exceed 8192 tokens"). UTF-8 bytes were
# assumed to bound tokens; they do not for digits, symbols and table pipes. Counted with the model family's tokenizer,
# with room left for the wrapper text and the room's file list.
BUDGET_TOKENS = 6000


def _counter():
    try:
        import tiktoken
        encoding = tiktoken.get_encoding('o200k_base')
        return lambda text: len(encoding.encode(text))
    except Exception:
        return lambda text: len(text.encode('utf-8'))   # no tokenizer: bytes, an over-count for Japanese


def room_history(messages, budget=BUDGET_TOKENS):
    # ChatService returns newest first; models need chronological history.
    count = _counter()
    kept = []
    remaining = budget
    for message in sorted(messages, key=lambda m: m.get('created_at') or '', reverse=True)[:96]:
        text = (message.get('content') or '').strip().removeprefix('🎙').strip()
        if not text:
            continue
        role = 'user' if message.get('sender_type') in ('human', 'user') else 'assistant'
        text = f"[{message.get('created_at', '')}] {text}"
        cost = count(text) + 10
        if cost > remaining:
            if not kept and remaining > 200:
                # the newest message alone is too long: its head and tail, shortened until they fit
                keep = len(text) // 2
                while keep > 50:
                    short = text[:keep] + '\n[…中略。全文は部屋の履歴に保存されています…]\n' + text[-keep:]
                    if count(short) + 10 <= remaining:
                        text, cost = short, count(short) + 10
                        break
                    keep = keep * 3 // 4
                else:
                    break
            else:
                break
        kept.append({'type': 'message', 'role': role, 'content': [{
            'type': 'input_text' if role == 'user' else 'output_text', 'text': text}]})
        remaining -= cost
    return list(reversed(kept))
