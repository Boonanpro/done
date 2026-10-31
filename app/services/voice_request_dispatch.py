"""Bounded watchdog for native transcript turns that did not reach Responses.

No ASR text or inferred approval is introduced here. The API backend receives its
existing conversation. Experimental until live automatic-delegation races have
been checked. A reserved request is never retried after an uncertain send.
"""
class RequestDispatch:
    def __init__(self, quiet_seconds=1.5):
        self.quiet_seconds = quiet_seconds
        self.revision = 0
        self.handled = 0
        self.changed_at = 0.0
        self.busy = False
        self.closed = False

    def heard(self, text, now):
        if not text or self.closed:
            return
        self.revision += 1
        self.changed_at = now

    def backend_started(self):
        # A response.created acknowledgement or tool continuation can arrive
        # after reserve(), and must not swallow a newer user correction.
        if self.busy:
            return
        self.busy = True
        self.handled = self.revision

    def backend_finished(self):
        self.busy = False

    def reserve(self, now):
        if (self.closed or self.busy or self.revision <= self.handled
                or now - self.changed_at < self.quiet_seconds):
            return None
        self.handled = self.revision
        self.busy = True
        return self.revision

    def close(self):
        self.closed = True
