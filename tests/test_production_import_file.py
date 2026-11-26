"""チャットに貼ったダンのファイルを、引きずってエディターの素材にする（2026-11-26）。"""
import shutil
import subprocess
from pathlib import Path

import pytest
from fastapi import FastAPI
from fastapi.testclient import TestClient

from app.api import production_asset_routes as r
from app.api.chat_artifact_routes import get_current_user

ROOM = "importfile-test-room"


@pytest.fixture()
def client(tmp_path, monkeypatch):
    uploads = tmp_path / "uploads"
    uploads.mkdir()
    monkeypatch.setattr(r, "UPLOADS_DIR", uploads)
    monkeypatch.setattr(r, "ASSET_ROOT", tmp_path / "assets")
    app = FastAPI()
    app.include_router(r.router, prefix="/api/v1")
    app.dependency_overrides[get_current_user] = lambda: None
    return TestClient(app), uploads


def _wav(path: Path, seconds: float = 2.0) -> None:
    ff = shutil.which("ffmpeg") or "/opt/homebrew/bin/ffmpeg"
    subprocess.run([ff, "-y", "-v", "error", "-f", "lavfi", "-i", f"sine=frequency=440:duration={seconds}", str(path)], check=True)


def test_import_chat_audio_gets_duration_and_name(client):
    c, uploads = client
    _wav(uploads / "abc.wav", 2.0)
    res = c.post("/api/v1/production-assets/import-file", json={"room_id": ROOM, "url": "https://dan.example/api/v1/files/abc.wav", "name": "Loop.wav"})
    assert res.status_code == 200, res.text
    a = res.json()
    assert a["kind"] == "audio"
    assert a["filename"] == "Loop.wav"
    assert abs(float(a["metadata"]["duration"]) - 2.0) < 0.1
    assert Path(a["local_path"]).is_file()
    assert Path(a["local_path"]).parent.name == ROOM  # この部屋の素材の場所に入る
    rows = r._read_assets(ROOM)
    assert rows[-1]["filename"] == "Loop.wav"


def test_import_rejects_outside_and_non_media(client):
    c, uploads = client
    (uploads / "note.txt").write_text("x")
    for url in ["/api/v1/files/../secret.wav", "/etc/passwd", "/api/v1/files/note.txt", "/api/v1/files/missing.wav", "/api/v1/files/sub%2F..%2Fx.wav"]:
        res = c.post("/api/v1/production-assets/import-file", json={"room_id": ROOM, "url": url})
        assert res.status_code in (400, 404), (url, res.status_code)


def test_upload_audio_probes_duration(client):
    c, uploads = client
    _wav(uploads / "tmp.wav", 1.5)
    with (uploads / "tmp.wav").open("rb") as f:
        res = c.post(f"/api/v1/production-assets/upload?room_id={ROOM}", files={"file": ("bgm.wav", f, "audio/wav")})
    assert res.status_code == 200, res.text
    assert abs(float(res.json()["metadata"]["duration"]) - 1.5) < 0.1
