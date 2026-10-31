"""Experimental recovery admission, in session-relative milliseconds.

This does not send events or authorize tool execution. Callers must align their
audio clock, check the recognition, and handle late native delegations before
enabling writes. Reserve before sending: an uncertain send must not be retried.
"""
from dataclasses import dataclass
import math


@dataclass(frozen=True)
class Span:
    start_ms: int
    end_ms: int

    def __post_init__(self):
        if not (0 <= self.start_ms < self.end_ms):
            raise ValueError('Invalid speech interval')

    def overlaps(self, other):
        return self.start_ms < other.end_ms and other.start_ms < self.end_ms


class RecoveryLedger:
    def __init__(self):
        self.native = []
        self.reserved = []
        self.tool_times = []
        self.closed = False

    def observe_native(self, span):
        self.native.append(span)

    def observe_tool(self, at_ms):
        self.tool_times.append(at_ms)

    def reserve(self, span, *, now_ms, avg_logprob, no_speech_prob):
        """Recheck after ASR. Confidence is a rejection heuristic, not proof.

        Any partial native overlap is ambiguous: don't replay the whole request.
        A later independent utterance's transcript must not hide an earlier gap.
        Conservative tool guard: even a read may already have queued other work.
        """
        if self.closed or now_ms < span.end_ms + 1000:
            return False
        if span.end_ms - span.start_ms > 30000:
            return False
        if not all(math.isfinite(x) for x in (avg_logprob, no_speech_prob)):
            return False
        if avg_logprob < -0.4 or not 0 <= no_speech_prob < 0.5:
            return False
        if any(span.overlaps(s) for s in self.native + self.reserved):
            return False
        if any(span.start_ms <= t <= now_ms for t in self.tool_times):
            return False
        self.reserved.append(span)
        return True

    def close(self):
        self.closed = True
