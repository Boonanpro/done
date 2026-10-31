"""Yield an ongoing spoken answer when new caller speech arrives.

Transcript timestamps are used only to group fragments, never to infer consent,
request completion, or cancellation of work. No canned reply is injected.
"""
import math


class Interruption:
    def __init__(self):
        self.output_end = None
        self.input_end = None
        self.signalled = False

    def observe(self, event):
        kind = event.get('type')
        start, end = event.get('start_ms'), event.get('end_ms')
        if not all(isinstance(v, (int, float)) and math.isfinite(v) for v in (start, end)) or end < start:
            return False
        if kind == 'session.output_transcript.delta':
            if event.get('delta'):
                self.output_end = max(end, self.output_end or end)
            return False
        if kind != 'session.input_transcript.delta' or not event.get('delta', '').strip():
            return False
        if self.input_end is not None and end <= self.input_end:
            return False
        if self.input_end is None or start - self.input_end > 700:
            self.signalled = False
        self.input_end = end
        if self.signalled or self.output_end is None or not -400 <= start - self.output_end <= 700:
            return False
        self.signalled = True
        return True

    async def handle(self, event, send, record):
        if not self.observe(event):
            return
        # This event steers the frontend only. It must not cancel the worker or
        # fabricate a tool result. Scope to this interruption; later turns resume.
        await send({'type': 'session.instructions.append', 'delegation_id': None,
                    'event_id': f'dan-yield-{event["end_ms"]}',
                    'content': '今、あなたが返答している途中で本人が話し始めました。この割り込みでは、元の説明を続けず、本人の続く言葉を聞いてください。質問や追加指示ならその内容に先に応答し、短い確認には短く答えてください。相づちだけなら新しい質問として扱わず、説明を最初から繰り返さないでください。返答の文言は本人の話に合わせてください。これは作業の停止や完了を意味しません。変更や停止の実操作は通常の道具で行ってください。この指示は今回の割り込みだけに適用します。'})
        record('conversation_yield', input_end_ms=event['end_ms'])
