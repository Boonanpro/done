# -*- coding: utf-8 -*-
"""Verify the context-preserving auto-heal helpers (deterministic, mocked DB).

  (1) _is_parse_error_text detects the CLI's unparseable-tool-call error.
  (2) _build_reseed_context rebuilds recent history for a fresh session BUT
      filters out contaminated lines (leaked <invoke> text / parse errors) so
      the reseed can't re-poison — while keeping the clean conversation so the
      user never has to re-explain.
"""
import sys

sys.path.insert(0, "D:/done")

import app.agent.cli_runner as cr  # noqa: E402
import app.services.supabase_client as sbmod  # noqa: E402


class _FakeQuery:
    def __init__(self, data):
        self._data = data

    def select(self, *a, **k):
        return self

    def eq(self, *a, **k):
        return self

    def order(self, *a, **k):
        return self

    def limit(self, *a, **k):
        return self

    def execute(self):
        return type("R", (), {"data": self._data})()


class _FakeClient:
    def __init__(self, data):
        self._data = data

    def table(self, _name):
        return _FakeQuery(self._data)


def main() -> int:
    fails = []

    # (1) parse-error detection
    if not cr._is_parse_error_text("The model's tool call could not be parsed (retry also failed)."):
        fails.append("parse-error text not detected")
    if cr._is_parse_error_text("ふつうの返信です"):
        fails.append("benign text wrongly flagged as parse error")

    # (2) reseed filters contamination, keeps clean history
    rows = [  # newest first (matches the order(desc=True) query)
        {"sender_type": "ai", "content": "course\n<invoke name=\"Edit\">...", "created_at": "t4"},
        {"sender_type": "ai", "content": "The model's tool call could not be parsed (retry also failed).", "created_at": "t3"},
        {"sender_type": "human", "content": "左の一覧をスクロールできるようにして", "created_at": "t2"},
        {"sender_type": "ai", "content": "スクロールできるよう直しました", "created_at": "t1"},
    ]
    fake = type("SB", (), {"client": _FakeClient(rows)})()
    sbmod.get_supabase_client = lambda: fake

    ctx = cr._build_reseed_context("room-x")
    print(f"reseed len={len(ctx)}")
    if "<invoke" in ctx or "could not be parsed" in ctx:
        fails.append("contamination leaked into reseed context")
    if "左の一覧をスクロール" not in ctx or "直しました" not in ctx:
        fails.append("clean history missing from reseed context")
    if "<conversation_so_far>" not in ctx:
        fails.append("reseed wrapper missing")

    # empty history -> empty reseed
    fake_empty = type("SB", (), {"client": _FakeClient([])})()
    sbmod.get_supabase_client = lambda: fake_empty
    if cr._build_reseed_context("room-y") != "":
        fails.append("empty history should yield empty reseed")

    if fails:
        print("\n=== FAIL ===")
        for x in fails:
            print("  -", x)
        return 1
    print("\n=== PASS: parse-error detected; reseed keeps clean history, drops contamination ===")
    return 0


if __name__ == "__main__":
    sys.exit(main())
