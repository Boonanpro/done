import importlib.util
import json
import subprocess
import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
spec = importlib.util.spec_from_file_location("hook_reply_check", ROOT / "scripts" / "hook_reply_check.py")
rc = importlib.util.module_from_spec(spec)
spec.loader.exec_module(rc)


def ids(reply, ask=""):
    return [h["id"] for h in rc.check(reply, ask)]


def test_scolded_shapes_are_found():
    # 10/22〜10/25 に並行作業の報告が丸ごと英語で届いた
    assert "english" in ids("The fixes are built, but only the new speaking rules are live so far. The other two start working once Dan restarts.")
    assert "interim" in ids("2枚とも、今のダンに入れる作業を始めました。終わったら知らせます。")
    assert "interim" in ids("本人の画面を確かめた結果を足します。パソコンで開いている顧客管理のタブは、もう新しい版になっています。")
    assert "test-count" in ids("直しました。試験は、新しく足した物も含めて117個すべて通りました。")
    assert "dev-flow" in ids("PR #624 を作りました。まだマージはしていません。")
    assert "roles" in ids("確かめ役が見つけた8件を全部直しました。")


def test_owner_words_and_quiet_reply_pass():
    assert ids("WATCH_NO_CHANGE") == []
    assert "dev-flow" not in ids("コミットしてPR #700 をマージしました。", ask="修正をコミットプッシュして")
    assert "roles" not in ids("「WATCH_NO_CHANGE」が画面に出ないようにしました。", ask="そのWATCH_NO_CHANGEもいらん")
    assert ids("了解、それで注文するね。合計1,135円、到着は14:08〜14:19。") == []
    # 部品やリンクの中の英語は数えない
    assert ids("ページを作りました。\n```openui-lang\nroot = Button(\"Open the page now please\", \"https://example.com\")\n```") == []


def _run(payload):
    store = str(payload.pop("_dir"))
    p = subprocess.run([sys.executable, str(ROOT / "scripts" / "hook_reply_check.py")], input=json.dumps(payload),
                       capture_output=True, text=True, encoding="utf-8", env={"DAN_REPLY_CHECK_DIR": store, "PATH": ""})
    return p.stdout


def test_blocks_once_then_passes(tmp_path):
    tr = tmp_path / "t.jsonl"
    tr.write_text(json.dumps({"type": "user", "message": {"role": "user", "content": "<latest_user_message>どうなった？</latest_user_message>"}},
                             ensure_ascii=False) + "\n", encoding="utf-8")
    body = {"hook_event_name": "Stop", "session_id": "s1", "transcript_path": str(tr),
            "last_assistant_message": "直しました。終わったら知らせます。"}
    first = _run({**body, "_dir": tmp_path})
    assert json.loads(first)["decision"] == "block" and "返事の全部" in json.loads(first)["reason"]
    assert _run({**body, "_dir": tmp_path}) == ""                     # 同じ返事は2回止めない
    assert _run({**body, "stop_hook_active": True, "session_id": "s2", "_dir": tmp_path}) == ""


def test_owner_word_read_from_transcript(tmp_path):
    tr = tmp_path / "t.jsonl"
    tr.write_text(json.dumps({"type": "user", "message": {"role": "user", "content": [{"type": "text", "text": "<latest_user_message>PRは出した？</latest_user_message>"}]}},
                             ensure_ascii=False) + "\n", encoding="utf-8")
    out = _run({"hook_event_name": "Stop", "session_id": "s3", "transcript_path": str(tr),
                "last_assistant_message": "PR #701 を出して、マージまで済みました。", "_dir": tmp_path})
    assert out == ""
