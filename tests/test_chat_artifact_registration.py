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


def test_nested_route_page_collapses_to_root_card():
    # A nested route page belongs to its root artifact, not a separate card.
    path = "frontend/src/app/artifacts/report-builder/admin/page.tsx"

    assert artifact_candidates_from_written_paths([path]) == [
        ("report-builder", "/artifacts/report-builder", path)
    ]


def test_multipage_site_collapses_to_one_card():
    # A multi-page site (root + nested routes under one slug dir) must register
    # as exactly ONE card whose preview_url is the root entry. This is the
    # structural guarantee: any future multi-page artifact -> a single card.
    root = "frontend/src/app/artifacts/paina/page.tsx"
    paths = [
        root,
        "frontend/src/app/artifacts/paina/business/page.tsx",
        "frontend/src/app/artifacts/paina/contact/page.tsx",
        "frontend/src/app/artifacts/paina/components/hero.tsx",  # non-entry, ignored
    ]

    assert artifact_candidates_from_written_paths(paths) == [
        ("paina", "/artifacts/paina", root)
    ]


def test_multipage_prefers_root_page_even_when_written_after_nested():
    # Order independence: the root page is the representative source path even
    # if a nested page was written first.
    paths = [
        "frontend/src/app/artifacts/paina/business/page.tsx",
        "frontend/src/app/artifacts/paina/page.tsx",
    ]

    assert artifact_candidates_from_written_paths(paths) == [
        ("paina", "/artifacts/paina", "frontend/src/app/artifacts/paina/page.tsx")
    ]


def test_distinct_root_slugs_stay_separate_cards():
    # Genuinely different artifacts (different root dirs) remain separate cards.
    paths = [
        "frontend/src/app/artifacts/paina/page.tsx",
        "frontend/src/app/artifacts/kittoku/page.tsx",
    ]

    assert artifact_candidates_from_written_paths(paths) == [
        ("paina", "/artifacts/paina", "frontend/src/app/artifacts/paina/page.tsx"),
        ("kittoku", "/artifacts/kittoku", "frontend/src/app/artifacts/kittoku/page.tsx"),
    ]


def test_nested_only_writes_still_register_root_card():
    # Editing only a sub-page of an existing site still maps to the root card.
    path = "frontend/src/app/artifacts/paina/contact/page.tsx"

    assert artifact_candidates_from_written_paths([path]) == [
        ("paina", "/artifacts/paina", path)
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
