"""Single admission for native and application-requested Live backend work.

The transcript clock identifies which words a delegation actually saw. Silence
only schedules reasoning; it is not consent or evidence that an instruction is
complete. All authorization remains in the ordinary backend tools.
"""
import asyncio
import time
import re


class TurnIntake:
    def __init__(self, quiet_seconds=1.5):
        self.quiet_seconds = quiet_seconds
        self.revision = 0
        self.changed_at = 0.0
        self.timeline = []
        self.fragments = []
        self.handled = 0
        self.delegations = {}
        self.active = set()
        self.reserved = None
        self.reserved_event = None
        self.owners = {}
        self.closed = False
        self.has_work = False
        self.work_hint = False  # semantic intent can request reasoning, never authorize work

    def heard(self, text, end_ms, now=None):
        if self.closed or not text:
            return
        self.revision += 1
        self.changed_at = time.monotonic() if now is None else now
        self.timeline.append((end_ms, self.revision))
        self.fragments.append(text)

    def begin(self, key, offset_ms=None, client_event_id=None):
        if not key:
            return
        if key in self.delegations:
            self.active.add(key)
            return
        # Unknown timing cannot be promoted to the latest instruction. A forced
        # request has a pre-send reservation, even if its acknowledgement is late.
        revision = self.reserved
        if client_event_id and client_event_id == self.reserved_event:
            revision = self.reserved
        elif isinstance(offset_ms, (int, float)):
            revision = max((r for end, r in self.timeline
                            if isinstance(end, (int, float)) and end <= offset_ms), default=0)
        self.delegations[key] = revision or 0
        self.active.add(key)
        self.handled = max(self.handled, revision or 0)
        if self.reserved == revision:
            self.reserved = None

    def finish(self, key):
        self.active.discard(key)

    def work_accepted(self, key):
        self.has_work = True
        revision = self.delegations.get(key, 0)
        if revision:
            self.owners.setdefault(revision, key)

    def attention_only_since(self, revision):
        tail = re.sub(r'[\s、。！？!?]', '', ''.join(self.fragments[revision:]))
        return tail in {'聞いてる', '聞いてますか', '聞こえてる', '聞こえますか'}

    def reserve(self, now=None):
        now = time.monotonic() if now is None else now
        if (self.closed or self.active or self.reserved is not None
                or self.revision <= self.handled or now - self.changed_at < self.quiet_seconds):
            return None
        if any(self.attention_only_since(r) for r in self.owners):
            self.handled = self.revision
            return None
        self.reserved = self.handled = self.revision
        return self.reserved

    def reject(self, key):
        revision = self.delegations.get(key, 0)
        if self.closed:
            return 'call_closed'
        if not revision or (revision != self.revision and not self.attention_only_since(revision)):
            return 'newer_or_unassociated_speech'
        for admitted in self.owners:
            if admitted < revision and self.attention_only_since(admitted):
                revision = admitted
                break
        owner = self.owners.get(revision)
        if owner is not None and owner != key:
            return 'already_admitted'
        self.owners[revision] = key
        return None

    async def admit(self, key):
        # Do not mutate while further fragments of the request are arriving.
        remaining = self.quiet_seconds - (time.monotonic() - self.changed_at)
        if remaining > 0:
            await asyncio.sleep(remaining)
        return self.reject(key)

    def close(self):
        self.closed = True


async def dispatch_missing(intake, send, record):
    """Request reasoning once, never retry an uncertain send or API refusal."""
    while not intake.closed:
        await asyncio.sleep(.2)
        if not (intake.has_work or intake.work_hint):
            continue
        revision = intake.reserve()
        if revision is None:
            continue
        record('turn_dispatch_reserved', revision=revision)
        try:
            intake.reserved_event = f'dan-intake-{time.time_ns()}'
            await send({'type': 'response.create', 'event_id': intake.reserved_event})
        except Exception as exc:
            record('turn_dispatch_failed', error_type=type(exc).__name__)
            return
