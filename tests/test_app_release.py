"""アプリの最新版の登録（app/services/app_release.py）。2026-10-24 見直し: 試験用の接続先・署名違い・古い版を
登録できていた。確かめに外れたら何も置かない。"""
import json

import pytest

from app.services import app_release as ar

GOOD = {"package": "app.done.dan", "version_name": "1.0.75", "version_code": 74,
        "api_base": "https://dan.paina.info", "signers": [ar.SIGNER_SHA256]}


def test_problems_pass_for_production_apk():
    assert ar.problems(GOOD, {"version_name": "1.0.74", "version_code": 73}) == []
    assert ar.problems(GOOD, None) == []


@pytest.mark.parametrize("change, word", [
    ({"api_base": "https://x.trycloudflare.com"}, "接続先"),
    ({"api_base": None}, "接続先"),
    ({"signers": ["7da0" + "0" * 60]}, "署名"),
    ({"signers": []}, "署名"),
    ({"package": "com.other"}, "Done"),
    ({"version_code": 73}, "versionCode"),   # 今の最新と同じ
    ({"version_code": 72}, "versionCode"),   # 古い
])
def test_problems_refuse(change, word):
    found = ar.problems({**GOOD, **change}, {"version_name": "1.0.74", "version_code": 73})
    assert found and any(word in f for f in found)


def test_refused_or_dry_run_places_nothing(tmp_path, monkeypatch):
    apk = tmp_path / "a.apk"
    apk.write_bytes(b"x" * 10)
    monkeypatch.setattr(ar, "RELEASE_FILE", tmp_path / "release.json")
    monkeypatch.setattr(ar, "UPLOADS", tmp_path / "uploads")
    monkeypatch.setattr(ar, "apk_facts", lambda p: {**GOOD, "api_base": "http://10.0.2.2:8765"})
    with pytest.raises(ValueError):
        ar.publish(apk)
    monkeypatch.setattr(ar, "apk_facts", lambda p: GOOD)
    rec = ar.publish(apk, dry_run=True)
    assert rec["url"] is None
    assert not (tmp_path / "release.json").exists() and not (tmp_path / "uploads").exists()
    rec = ar.publish(apk, notes="作業中の1行")
    assert json.loads((tmp_path / "release.json").read_text())["version_code"] == 74
    assert (tmp_path / "uploads" / rec["url"].rsplit("/", 1)[1]).exists()
    # 同じ版をもう一度は登録しない
    with pytest.raises(ValueError):
        ar.publish(apk)


def test_note_installed_keeps_one_row_per_phone(tmp_path, monkeypatch):
    from app.services import app_release
    monkeypatch.setattr(app_release, "INSTALLS_FILE", tmp_path / "installs.json")
    app_release.note_installed("u1", "1.0.76", "75", "samsung SM-S921Q")
    app_release.note_installed("u1", "1.0.77", 76, "samsung SM-S921Q")
    app_release.note_installed("u1", "1.0.76", 75, "samsung SM-S911C")
    app_release.note_installed("u2", "1.0.77", 76, "x")
    app_release.note_installed("u1", "1.0.77", "bad", "y")
    rows = app_release.installed("u1")
    assert {(r["device"], r["version_name"]) for r in rows} == {("samsung SM-S921Q", "1.0.77"), ("samsung SM-S911C", "1.0.76")}
    assert len(app_release.installed()) == 3
