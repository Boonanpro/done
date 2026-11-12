import json
import sys

import pytest

from app import paths
from app.api import production_asset_routes as R

pytestmark = pytest.mark.skipif(sys.platform == "win32", reason="Windows ではそのまま使う")


def test_local_file_rewrites_windows_done_paths():
    assert paths.local_file(r"D:\done\uploads\a\b.png") == f"{paths.DONE_ROOT.as_posix()}/uploads/a/b.png"
    assert paths.local_file("C:/Users/Owner/x.png") == "C:/Users/Owner/x.png"
    assert paths.local_file("https://example.com/a.png") == "https://example.com/a.png"
    assert paths.local_file("/Volumes/nas/a.mp4") == "/Volumes/nas/a.mp4"
    assert paths.local_file(None) is None


def test_library_reads_windows_era_assets(tmp_path, monkeypatch):
    room = "room-x"
    (tmp_path / room).mkdir()
    image = paths.DONE_ROOT / "uploads" / "production-assets" / room / "a.png"
    rows = [{"id": "a", "kind": "image", "local_path": rf"D:\done\uploads\production-assets\{room}\a.png"}]
    (tmp_path / room / "assets.json").write_text(json.dumps(rows), encoding="utf-8")
    monkeypatch.setattr(R, "ASSET_ROOT", tmp_path)
    assert R._read_assets(room)[0]["local_path"] == image.as_posix()
