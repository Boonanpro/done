"""Re-assign a vercel.app alias to the latest production deployment.

Usage:
    python scripts/reassign_artifact_alias.py salonboard-styleup-done.vercel.app
    python scripts/reassign_artifact_alias.py salonboard-styleup-done.vercel.app --project frontend
"""
from __future__ import annotations

import argparse
import asyncio
import sys

from app.tools.publish_site.vercel_domains import VercelError, get_vercel


async def main() -> int:
    parser = argparse.ArgumentParser()
    parser.add_argument("alias", help="Target alias host (e.g. foo-done.vercel.app)")
    parser.add_argument("--project", default="frontend", help="Vercel project name")
    args = parser.parse_args()

    vercel = await get_vercel()
    deployments = await vercel.list_deployments(args.project, target="production", limit=1)
    if not deployments:
        print(f"No READY production deployment found for project {args.project}", file=sys.stderr)
        return 1

    deployment = deployments[0]
    deployment_id = deployment.get("uid") or deployment.get("id")
    deployment_url = deployment.get("url") or "(unknown)"
    print(f"Latest production deployment: {deployment_id} ({deployment_url})")

    try:
        result = await vercel.assign_alias(deployment_id, args.alias)
    except VercelError as e:
        print(f"assign_alias failed: {e}", file=sys.stderr)
        return 2

    print(f"OK: {args.alias} now points to {deployment_id}")
    print(f"Result: {result}")
    return 0


if __name__ == "__main__":
    raise SystemExit(asyncio.run(main()))
