# -*- coding: utf-8 -*-
"""ストリーミング出力のテキスト反復崩壊ガード (_TextLoopGuard) の回帰テスト。

背景: 文脈肥大でモデルが同じ出力行を延々と繰り返す崩壊
("court — proceeding:" x500 等) が発生。既存のループガードは「同一ツール
呼び出しの連続」しか見ず、テキスト反復は素通り→idleタイムアウトまで
ストリームに垂れ流され、しかもターンが完了しないため永続化もされない。
_TextLoopGuard は同一非空行の連続を検知して同じ復旧経路に乗せる。
関連メモリ: project_parse_error_poison_browser_bloat / project_dan_latency_root_cause
"""
import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))

from app.agent.cli_runner import _TextLoopGuard  # noqa: E402


def _fires(fragments, threshold=12):
    g = _TextLoopGuard(threshold)
    for f in fragments:
        if g.record(f):
            return True, g.sample
    return False, g.sample


def test_detects_repeated_line_blank_separated():
    """実際の崩壊パターン: 同一行が空行区切りで連発。"""
    fired, sample = _fires(["court — proceeding:\n\n"] * 20)
    assert fired
    assert "court" in sample


def test_detects_repeated_checklist_line():
    fired, _ = _fires(["course: ✅dengamisama ✅denkikanri3y ✅ohono1200\n"] * 20)
    assert fired


def test_detects_cyclic_repetition_not_just_consecutive():
    """実際の循環型崩壊: 数行が回り続け、同じ行が連続はしないが頻出する。

    "court 停止。" は毎回別の行を挟むので consecutive-only では捕まらない。
    窓内出現回数で数えることで検知する。
    """
    cycle = [
        "I run it now:\n",
        "court 停止。\n",
        "court — proceeding:\n",
        "court 停止。\n",
        "ok run:\n",
        "court 停止。\n",
        "Now executing:\n",
        "court 停止。\n",
    ]
    fired, sample = _fires(cycle * 6)
    assert fired
    assert sample == "court 停止。"


def test_detects_when_line_split_across_fragments():
    """ストリームのデルタは行をまたいで断片で届く。"""
    fired, _ = _fires((["court ", "— proce", "eding:\n"]) * 15)
    assert fired


def test_fires_exactly_at_threshold():
    g = _TextLoopGuard(12)
    fired_at = None
    for i in range(1, 30):
        if g.record("repeat this line\n"):
            fired_at = i
            break
    assert fired_at == 12


def test_normal_varied_text_does_not_fire():
    fired, _ = _fires([f"step {i}: editing file_{i}.tsx\n" for i in range(60)])
    assert not fired


def test_separator_rules_do_not_fire():
    """区切り線(英数字を含まない行)は誤検知させない。"""
    for sep in ("---\n", "======\n", "***\n", "| --- | --- |\n"):
        fired, _ = _fires([sep] * 30)
        assert not fired, f"separator {sep!r} should not trip the guard"


def test_japanese_repeated_line_is_caught():
    """CJKはalnum扱いなので日本語の反復も検知できる。"""
    fired, _ = _fires(["作業を続行します:\n"] * 20)
    assert fired


def test_threshold_zero_disables():
    fired, _ = _fires(["x\n"] * 50, threshold=0)
    assert not fired


def test_reset_clears_streak():
    g = _TextLoopGuard(12)
    for _ in range(11):
        assert not g.record("same line\n")
    g.reset()
    # after reset the streak restarts; 11 more must not fire
    for _ in range(11):
        assert not g.record("same line\n")


def test_tool_calls_between_repeated_text_prevent_false_positive():
    """妥当な「同じ一文 → ツール実行 → 繰り返し」は誤検知させない。

    sink は tool_use イベントごとに text_loop_guard.reset() を呼ぶ。ここでは
    その挙動を模して、同一ナレーション行ごとに reset を挟めば 30 回繰り返しても
    発火しないことを保証する（純テキスト連発の崩壊だけが残るようにする設計）。
    """
    g = _TextLoopGuard(12)
    fired = False
    for _ in range(30):
        if g.record("スクショを撮ります\n"):
            fired = True
            break
        g.reset()  # = sink が tool_use(screenshot) で呼ぶリセット
    assert not fired
