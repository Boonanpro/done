from app.services.chat_artifact_registration import (
    add_written_path,
    artifact_candidates_from_written_paths,
    artifact_slugs_from_written_paths,
    written_path_from_tool,
)


def test_written_path_from_claude_write_tool_windows_path():
    path = r"D:\done\frontend\src\app\artifacts\denki-knowledge\page.tsx"

    assert written_path_from_tool("Write", {"file_path": path}) == path


def test_add_written_path_deduplicates_preserving_order():
    paths: list[str] = []

    add_written_path(paths, "a")
    add_written_path(paths, "a")
    add_written_path(paths, "b")

    assert paths == ["a", "b"]


def test_artifact_candidates_include_root_page_from_windows_absolute_path():
    path = r"D:\done\frontend\src\app\artifacts\denki-knowledge\page.tsx"

    assert artifact_candidates_from_written_paths([path]) == [
        (
            "denki-knowledge",
            "/artifacts/denki-knowledge",
            "D:/done/frontend/src/app/artifacts/denki-knowledge/page.tsx",
        )
    ]


def test_artifact_candidates_include_nested_route_page():
    path = "frontend/src/app/artifacts/report-builder/admin/page.tsx"

    assert artifact_candidates_from_written_paths([path]) == [
        ("report-builder-admin", "/artifacts/report-builder/admin", path)
    ]


def test_artifact_candidates_ignore_non_entry_files():
    paths = [
        r"D:\done\frontend\src\app\artifacts\denki-knowledge\layout.tsx",
        r"D:\done\frontend\src\app\artifacts\denki-knowledge\components\Panel.tsx",
    ]

    assert artifact_candidates_from_written_paths(paths) == []


def test_artifact_slugs_from_written_paths_extracts_root_slugs_once():
    paths = [
        r"D:\done\frontend\src\app\artifacts\denki-knowledge\layout.tsx",
        r"D:\done\frontend\src\app\artifacts\denki-knowledge\page.tsx",
        "frontend/src/app/artifacts/report-builder/admin/page.tsx",
    ]

    assert artifact_slugs_from_written_paths(paths) == ["denki-knowledge", "report-builder"]
