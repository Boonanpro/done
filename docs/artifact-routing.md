# Artifact Routing Policy

This policy keeps Dan-generated websites, tools, and dashboards from mixing
internal artifact paths with public preview paths.

## Canonical Roles

- `frontend/src/app/artifacts/<slug>/...`
  - Source location and internal workspace route.
  - Inspector/writeback targets this tree.
  - Do not expose this as the primary URL in generated navigation.

- `/preview/<slug>/...`
  - Public preview/share URL.
  - Full-screen preview and chat share actions should use this route.
  - It rewrites to `/artifacts/<slug>/...` internally.

- custom domain clean paths
  - Published websites should use `/`, `/contact`, `/services`, etc.
  - The domain rewrite maps those clean paths to the matching artifact route.
  - If a user reaches `/preview/<slug>/...` or `/artifacts/<slug>/...` on a
    configured custom domain, middleware redirects back to the clean path.

- `/demo/<slug>/...`
  - Proposal-video prototypes and temporary internal demos only.
  - Client deliverables should not be generated here.

## Link Rules For Generated Artifacts

Do not hard-code user navigation with `href="/artifacts/<slug>/..."`.

Use one of these patterns:

```tsx
import { ArtifactLink as Link } from "@/components/artifacts/artifact-link";

<Link href="/artifacts/example/contact">Contact</Link>
```

`ArtifactLink` preserves the visible URL family:

- browsing `/preview/example` links to `/preview/example/contact`
- browsing `/artifacts/example` links to `/artifacts/example/contact`
- browsing a configured custom domain links to `/contact`

For stored URLs, use helpers from `@/lib/artifact-paths`:

```ts
artifactWorkspacePath("example", "/contact");
artifactPreviewPath("example", "/contact");
artifactPublicPath("example", "/contact");
```

## Enforcement

`scripts/hook_artifact_link_guard.py` runs after Dan writes artifact files. It
rejects generated artifact code that hard-codes `/artifacts/<slug>` without
using the shared artifact link component or path helpers.

Custom domains are configured in middleware with `ARTIFACT_CUSTOM_DOMAINS` or
`NEXT_PUBLIC_ARTIFACT_CUSTOM_DOMAINS` using:

```txt
slug=example.com|www.example.com,other=other.example.com
```
