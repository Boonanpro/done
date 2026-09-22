"""Classify a path as Dan infrastructure, artifact, demo, or ignored.

This is the single source of truth used by every layer that needs to know
"which scope does this file belong to":

- Pre-commit hook (``hook_mixed_scope_guard.py``) blocks commits that mix
  Dan infra with an artifact (or two different artifacts).
- CI workflow (``.github/workflows/scope-check.yml``) runs the same check
  on every PR diff.
- Inspector writeback validates that it never writes outside the artifact
  it was asked to edit.
- ``scope_diff.py`` exposes the classification of currently-staged files
  to humans.

The classifications:
- ``infra``: Dan's own backend / frontend infrastructure / shared
  components / build config. Changes here affect every artifact and the
  Dan app itself.
- ``artifact:<slug>``: code or assets that belong to a specific
  customer-facing artifact (e.g. ``kittoku``, ``salonboard-styleup``).
- ``demo:<name>``: ``frontend/src/app/scratch/<name>/`` prototype space.
  The legacy ``frontend/src/app/demo`` route is intentionally unsupported.
- ``ignored``: generated / vendor / lockfile / tunnel state - safe to
  mix in any commit because it has no human-edited intent.
- ``ambiguous``: did not match any rule. The caller should treat this
  as a hard error (we cannot guarantee scope safety) until a rule is
  added.

The contract is intentionally a pure function of the path string - no
filesystem access, no git access - so it can be invoked identically by
hooks, CI, and humans.
"""
from __future__ import annotations

import fnmatch
from dataclasses import dataclass
from typing import Iterable


@dataclass(frozen=True)
class Scope:
    kind: str  # "infra" | "artifact" | "demo" | "ignored" | "ambiguous"
    name: str | None = None  # slug for artifact, name for demo

    def __str__(self) -> str:
        if self.name:
            return f"{self.kind}:{self.name}"
        return self.kind

    @property
    def is_blocking(self) -> bool:
        """Does this scope participate in mix detection?"""
        return self.kind in ("infra", "artifact", "ambiguous")


# ---------------------------------------------------------------------------
# Rules
#
# Order matters: the first rule that matches wins. List more specific
# patterns before more general ones.
# ---------------------------------------------------------------------------

# Paths that contribute no semantic intent (lock files, generated assets,
# tunnel state, OS junk). Safe to appear in any commit.
_IGNORED_PATTERNS: tuple[str, ...] = (
    ".tunnel_*",
    "*.lock",
    "*.log",
    "package-lock.json",
    "frontend/package-lock.json",
    "frontend/.next/**",
    "frontend/public/artifacts/*/icon-*.png",
    "node_modules/**",
    "frontend/node_modules/**",
    "**/__pycache__/**",
    "**/.pytest_cache/**",
    "**/.mypy_cache/**",
    "**/.ruff_cache/**",
    ".vercel/**",
    "frontend/.vercel/**",
    "sandbox.log",
    ".env*",
)

# frontend/public/<dir>/ ownership map. Required because public asset
# directory names do not match artifact slugs (e.g. "kikkawa" belongs to
# the "kittoku" artifact, named differently for historical reasons).
# Keys are the directory under frontend/public/.
_PUBLIC_DIR_TO_OWNER: dict[str, Scope] = {
    "kikkawa": Scope("artifact", "kittoku"),
    # LP mock images served at a public (non-/artifacts) path so unauthenticated
    # ad visitors can load them. Currently only the salonboard-monitor LP uses
    # this folder; revisit if another artifact's mocks are added here.
    "lp-mocks": Scope("artifact", "salonboard-monitor"),
    # amagasaki-hero.{mp4,png} files live directly under public/ but are
    # scratch assets used only by frontend/src/app/scratch/amagasaki-sales-dashboard.
    # They are listed here as a prefix match.
}

# Public asset directories that are SHARED across artifacts (or otherwise not
# owned by a single artifact). These must stay infra; everything else under
# frontend/public/<dir>/ defaults to artifact:<dir> (see classify step 5).
_PUBLIC_SHARED_DIRS: frozenset[str] = frozenset({
    "models",  # shared 3D assets (e.g. garbage_truck) used by multiple artifacts
    "fonts",   # bundled OFL caption fonts, used by the production-tab caption renderer
})

# Top-level public files (no directory) that belong to specific prototypes.
_PUBLIC_FILE_TO_OWNER: dict[str, Scope] = {
    "amagasaki-hero.mp4": Scope("demo", "amagasaki-sales-dashboard"),
    "amagasaki-hero.png": Scope("demo", "amagasaki-sales-dashboard"),
    "inspection-template.docx": Scope("artifact", "inspection-report"),
    "inspection-template.xlsm": Scope("artifact", "inspection-report"),
    "annual-inspection-template.xlsm": Scope("artifact", "inspection-report"),
    "denki-knowledge-index.json": Scope("artifact", "denki-knowledge"),
}

# frontend/src/app/api/<dir>/ ownership overrides for API route dirs whose name
# does not match the artifact slug (default is artifact:<dir>). Required so the
# publish mirror (artifact_files_for_slug) ships the API together with the page.
_APP_API_DIR_TO_OWNER: dict[str, Scope] = {
    "denki-qa": Scope("artifact", "denki-knowledge"),
}

# Patterns that are infrastructure (Dan core / shared frontend).
_INFRA_PATTERNS: tuple[str, ...] = (
    # Shared editable-motion starter loaded by editor_motion_project.prepare.
    # Deliberately exclude comparison recordings, renders and other videos.
    "videos/reference-01-finish/index.html",
    "videos/reference-01-finish/hyperframes.json",
    "videos/reference-01-finish/package.json",
    "videos/reference-01-finish/meta.json",
    "videos/reference-01-finish/assets/Inter.ttf",
    "videos/reference-01-finish/assets/Inter-OFL.txt",
    "videos/reference-01-finish/assets/gsap.min.js",
    # backend
    "app/**",
    # standalone services (phone voice bridge etc.)
    "services/**",
    # Dan's wearable voice device, bridge, firmware and provisioning tools.
    "devices/atom-echo-s3r/**",
    # repo-root tooling manifests
    "skills-lock.json",
    # ops / tooling
    "scripts/**",
    "tests/**",
    "tests_e2e/**",
    "mobile/**",
    "supabase/**",
    ".github/**",
    ".githooks/**",
    ".claude/**",
    ".cursor/**",
    "docs/**",
    # frontend infra
    "frontend/next.config.*",
    "frontend/.gitignore",
    "frontend/package.json",
    "frontend/tsconfig.json",
    "frontend/tsconfig.*.json",   # type-check variants (voice-note-check etc.)
    "frontend/.vercelignore",
    "frontend/public/*-worklet.js",   # audio worklets of the voice transports (atom / gemini)
    "frontend/tailwind.config.*",
    "frontend/postcss.config.*",
    "frontend/eslint.config.*",
    "frontend/components.json",
    "frontend/src/components/**",
    "frontend/src/lib/**",
    "frontend/src/hooks/**",
    "frontend/src/stores/**",
    "frontend/src/types/**",
    "frontend/src/middleware.ts",
    # Dan's own pages (everything in app/ except /artifacts/,
    # /scratch/, and the artifact-specific api routes which are matched
    # by _ARTIFACT_API_PREFIXES below).
    "frontend/src/app/*.tsx",
    "frontend/src/app/*.ts",
    "frontend/src/app/*.css",
    "frontend/src/app/favicon.ico",
    # Dan dashboards / utility pages
    "frontend/src/app/chat/**",
    "frontend/src/app/collab/**",
    "frontend/src/app/dan-notion/**",
    "frontend/src/app/domain-setup/**",
    "frontend/src/app/friends/**",
    "frontend/src/app/login/**",
    "frontend/src/app/meeting/**",
    "frontend/src/app/notes/**",
    "frontend/src/app/register/**",
    "frontend/src/app/settings/**",
    "frontend/src/app/studio/**",
    "frontend/src/app/test-inspector/**",
    "frontend/src/app/today/**",
    "frontend/src/app/voice/**",
    # generic public assets (PWA, icons, service worker, manifest)
    "frontend/public/favicon.ico",
    "frontend/public/icon-*.png",
    "frontend/public/manifest.json",
    "frontend/public/sw.js",
    "frontend/public/workbox-*.js",
    "frontend/public/audio-worklet-processor.js",
    "frontend/public/atom-wifi-worklet.js",
    "frontend/public/file.svg",
    "frontend/public/globe.svg",
    "frontend/public/next.svg",
    "frontend/public/vercel.svg",
    "frontend/public/window.svg",
    # /artifacts/{layout.tsx,_seo/**,publish/**} are Dan infra inside the
    # artifacts route group (shared chrome + 全成果物共通のSEO構造化データ +
    # publish flow page). _seo/ は slug ではなく全成果物共通のヘルパー置き場。
    "frontend/src/app/artifacts/layout.tsx",
    "frontend/src/app/artifacts/_seo/**",
    "frontend/src/app/artifacts/publish/**",
    # API v1 is Dan backend; artifact-specific api routes are matched
    # below by _ARTIFACT_API_PREFIXES.
    "frontend/src/app/api/v1/**",
    # generated TypeScript API client lives in frontend/src/types/api.ts
    # (already matched above) and route stubs under frontend/src/app/api/v1/.
    # repo-root config and docs
    "*.md",
    "CLAUDE.md",
    "RULES.md",
    "MEMORY.md",
    ".gitignore",
    ".gitattributes",
    "pyproject.toml",
    "requirements*.txt",
    "next.config.*",
    "tsconfig.json",
    "package.json",
    ".dockerignore",
    "Dockerfile",
    "docker-compose*.yml",
)


def _match_any(path: str, patterns: Iterable[str]) -> bool:
    return any(fnmatch.fnmatchcase(path, pat) for pat in patterns)


def _normalize(path: str) -> str:
    """Normalize a git-style path: forward slashes, no leading ./ ."""
    p = path.replace("\\", "/")
    while p.startswith("./"):
        p = p[2:]
    return p.lstrip("/")


def classify(path: str) -> Scope:
    """Return the scope of a single repo-relative path.

    The path uses forward slashes (git format). Trailing slashes are
    tolerated (treated as a directory).
    """
    p = _normalize(path)
    if not p:
        return Scope("ambiguous")

    # Strip directory trailing slash for matching purposes.
    p_match = p.rstrip("/")

    # 1. Ignored (generated / vendor / lock / tunnel state).
    if _match_any(p_match, _IGNORED_PATTERNS):
        return Scope("ignored")

    # 2. Artifact sources: frontend/src/app/artifacts/<slug>/...
    if p_match.startswith("frontend/src/app/artifacts/"):
        rest = p_match[len("frontend/src/app/artifacts/"):]
        # /artifacts/{layout.tsx,_seo/**,publish/**} are Dan infra (caught
        # below by the infra rule list as well, but handle explicitly to make
        # ordering robust). _seo/ は slug ではなく全成果物共通のSEOヘルパー。
        if rest in {"layout.tsx"} or rest.startswith(("publish/", "_seo/")):
            return Scope("infra")
        if rest.startswith("[slug]/"):
            return Scope("infra")
        head = rest.split("/", 1)[0]
        if head:
            return Scope("artifact", head)
        return Scope("ambiguous")

    # 3. Artifact-specific API routes: frontend/src/app/api/<slug>/...
    if p_match.startswith("frontend/src/app/api/"):
        rest = p_match[len("frontend/src/app/api/"):]
        head = rest.split("/", 1)[0]
        # api/v1/** is Dan backend (handled by infra rules below).
        if head == "v1":
            return Scope("infra")
        owner = _APP_API_DIR_TO_OWNER.get(head)
        if owner:
            return owner
        if head:
            return Scope("artifact", head)

    # 4. Scratch prototype space. Legacy frontend/src/app/demo is unsupported.
    for demo_root in ("frontend/src/app/scratch/",):
        if p_match.startswith(demo_root):
            rest = p_match[len(demo_root):]
            head = rest.split("/", 1)[0]
            if head:
                return Scope("demo", head)

    # 5. frontend/public/<dir>/...
    if p_match.startswith("frontend/public/"):
        rest = p_match[len("frontend/public/"):]
        if "/" in rest:
            head, tail = rest.split("/", 1)
            # public/artifacts/<slug>/... is owned by that <slug> (icons are
            # already caught as ignored in step 1).
            if head == "artifacts":
                inner = tail.split("/", 1)[0]
                if inner:
                    return Scope("artifact", inner)
            owner = _PUBLIC_DIR_TO_OWNER.get(head)
            if owner:
                return owner
            # Shared/non-artifact public dirs stay infra.
            if head in _PUBLIC_SHARED_DIRS:
                return Scope("infra")
            # Default: a public asset directory is owned by the artifact of the
            # same name (e.g. frontend/public/paina/ -> artifact:paina). This
            # lets a new artifact publish its assets without a manual rule edit.
            # Name mismatches (kikkawa->kittoku) and shared dirs are handled
            # above and take precedence.
            return Scope("artifact", head)
        else:
            # public/<file> (no subdirectory)
            owner = _PUBLIC_FILE_TO_OWNER.get(rest)
            if owner:
                return owner

    # 6. Infra (catch-all for Dan-owned code/config).
    if _match_any(p_match, _INFRA_PATTERNS):
        return Scope("infra")

    # 7. Could not classify.
    return Scope("ambiguous")


def classify_paths(paths: Iterable[str]) -> list[tuple[str, Scope]]:
    return [(p, classify(p)) for p in paths]


# ---------------------------------------------------------------------------
# Mix detection
# ---------------------------------------------------------------------------


@dataclass(frozen=True)
class MixVerdict:
    ok: bool
    reason: str
    infra_files: tuple[str, ...]
    artifact_groups: dict[str, tuple[str, ...]]
    ambiguous_files: tuple[str, ...]


def detect_mix(paths: Iterable[str]) -> MixVerdict:
    """Return a verdict on whether a set of paths can be committed together.

    Rules:
    - Multiple files in the same ``artifact:<slug>`` are fine.
    - Multiple files all in ``infra`` are fine.
    - ``demo:*`` and ``ignored`` never cause a mix (neutral).
    - ``infra`` + any ``artifact:*`` is a mix - block.
    - Two or more distinct ``artifact:<slug>`` values is a mix - block.
    - Any ``ambiguous`` is a hard error - block until a rule is added.
    """
    infra: list[str] = []
    artifacts: dict[str, list[str]] = {}
    ambiguous: list[str] = []
    for p, s in classify_paths(paths):
        if s.kind == "infra":
            infra.append(p)
        elif s.kind == "artifact" and s.name:
            artifacts.setdefault(s.name, []).append(p)
        elif s.kind == "ambiguous":
            ambiguous.append(p)
        # demo and ignored intentionally ignored.

    artifact_groups = {k: tuple(v) for k, v in artifacts.items()}

    if ambiguous:
        return MixVerdict(
            ok=False,
            reason=(
                "未分類のパスがある: 各 path の scope を scope_classifier の "
                "ルールに追加してから再試行してください"
            ),
            infra_files=tuple(infra),
            artifact_groups=artifact_groups,
            ambiguous_files=tuple(ambiguous),
        )

    if infra and artifacts:
        slugs = ", ".join(sorted(artifacts.keys()))
        return MixVerdict(
            ok=False,
            reason=(
                f"Dan infra と artifact ({slugs}) の変更が同じ commit に混在。"
                " 別 commit に分けてください"
            ),
            infra_files=tuple(infra),
            artifact_groups=artifact_groups,
            ambiguous_files=tuple(ambiguous),
        )

    if len(artifacts) > 1:
        slugs = ", ".join(sorted(artifacts.keys()))
        return MixVerdict(
            ok=False,
            reason=(
                f"複数の artifact ({slugs}) の変更が同じ commit に混在。"
                " 1 artifact = 1 commit にしてください"
            ),
            infra_files=tuple(infra),
            artifact_groups=artifact_groups,
            ambiguous_files=tuple(ambiguous),
        )

    return MixVerdict(
        ok=True,
        reason="ok",
        infra_files=tuple(infra),
        artifact_groups=artifact_groups,
        ambiguous_files=(),
    )
