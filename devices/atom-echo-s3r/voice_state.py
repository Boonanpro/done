"""Device intent is authoritative; session readiness is a short-lived lease."""
import struct
import time

HEADER = struct.Struct('<III')  # flags, boot nonce, intent revision


class VoiceGate:
    def __init__(self):
        self.connected = False
        self.requested = False
        self.boot = self.revision = 0
        self.ready_until = 0.
        self.pending = None
        self.wake_enabled = False

    def receive(self, header):
        flags, boot, revision = HEADER.unpack(header)
        changed = (boot, revision) != (self.boot, self.revision)
        if changed:
            self.ready_until = 0
            if self.pending and self.pending[:2] != (boot, revision): self.pending = None
        self.connected = True
        self.boot, self.revision, self.requested = boot, revision, bool(flags & 1)
        if self.pending and self.pending[:2] == (boot, revision) and self.pending[2] == self.requested:
            self.pending = None
        if not self.requested: self.ready_until = 0
        return changed

    @property
    def wanted(self):
        return self.requested and not (self.pending and not self.pending[2])

    def control(self, enabled):
        self.pending = None if self.connected and self.requested == enabled else (self.boot, self.revision, enabled)
        self.ready_until = 0

    def lease(self, boot, revision, active):
        if (boot, revision) != (self.boot, self.revision): return False
        self.ready_until = time.monotonic() + 2 if active and self.connected and self.wanted else 0
        return True

    @property
    def ready(self):
        return self.connected and self.wanted and time.monotonic() < self.ready_until

    def outgoing(self):
        flags = 1 if self.ready else 0
        if self.wake_enabled and not self.requested: flags |= 8
        if self.pending:
            boot, rev, enabled = self.pending
            flags = 4 if enabled else 2
            # Compare-and-set: an older host command cannot undo a later button press.
            return HEADER.pack(flags, boot, rev)
        return HEADER.pack(flags, self.boot, self.revision)

    def disconnected(self):
        self.connected = False
        self.ready_until = 0

    def status(self):
        return {'requested': self.wanted, 'device_requested': self.requested,
                'voice_ready': self.ready, 'boot': self.boot, 'revision': self.revision,
                'control_pending': self.pending is not None}
