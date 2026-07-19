"""Regression tests for safe multi-device artifact publishing."""

from pathlib import Path

from app.services import artifact_git_publish as publisher


def _setup(monkeypatch, tmp_path: Path) -> tuple[Path, Path, list[str]]:
    project = tmp_path / "done"
    canonical = tmp_path / "canonical"
    source = project / "frontend" / "src" / "app" / "artifacts" / "sample"
    target = canonical / "src" / "app" / "artifacts" / "sample"
    source.mkdir(parents=True)
    target.mkdir(parents=True)
    (source / "page.tsx").write_text("base", encoding="utf-8")
    (target / "page.tsx").write_text("base", encoding="utf-8")
    monkeypatch.setattr(publisher, "PROJECT_ROOT", project)
    monkeypatch.setattr(publisher, "TMP_DIR", tmp_path / "tmp")
    monkeypatch.setattr(publisher, "ARTIFACT_BASES_DIR", tmp_path / "bases")
    return source, canonical, ["frontend/src/app/artifacts/sample"]


def test_first_publish_seeds_a_base_only_when_local_is_current(monkeypatch, tmp_path):
    source, canonical, paths = _setup(monkeypatch, tmp_path)

    assert publisher._guard_and_apply_local_changes(canonical, "sample", paths) == ""
    assert (tmp_path / "bases/sample/src/app/artifacts/sample/page.tsx").read_text() == "base"

    source.joinpath("page.tsx").write_text("stale-local", encoding="utf-8")
    message = publisher._guard_and_apply_local_changes(canonical, "other-sample", paths)
    assert "中止" in message
    assert (canonical / "src/app/artifacts/sample/page.tsx").read_text() == "base"


def test_conflicting_second_device_edit_is_rejected_without_overwrite(monkeypatch, tmp_path):
    source, canonical, paths = _setup(monkeypatch, tmp_path)
    assert publisher._guard_and_apply_local_changes(canonical, "sample", paths) == ""

    source.joinpath("page.tsx").write_text("first-device", encoding="utf-8")
    assert publisher._guard_and_apply_local_changes(canonical, "sample", paths) == ""
    publisher._snapshot_current_source("sample", paths)

    source.joinpath("page.tsx").write_text("second-device", encoding="utf-8")
    (canonical / "src/app/artifacts/sample/page.tsx").write_text("first-device-newer", encoding="utf-8")

    message = publisher._guard_and_apply_local_changes(canonical, "sample", paths)
    assert "中止" in message
    assert (canonical / "src/app/artifacts/sample/page.tsx").read_text() == "first-device-newer"


def test_new_artifact_can_publish_from_an_empty_canonical_tree(monkeypatch, tmp_path):
    source, canonical, paths = _setup(monkeypatch, tmp_path)
    target = canonical / "src/app/artifacts/sample/page.tsx"
    target.unlink()
    target.parent.rmdir()

    assert publisher._guard_and_apply_local_changes(canonical, "sample", paths) == ""
    assert target.read_text() == "base"
