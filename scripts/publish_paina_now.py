"""paina 成果物を専用 Vercel プロジェクトへ再公開し、独自ドメインを付け直す。

`deploy_dedicated_release` は `--skip-domain` で配信するため、新しいデプロイには
paina.info などの独自ドメインが自動では付かない。付け直しを省くと 7/31 と同じ
「ドメインだけ古い/未接続」状態に戻るので、公開後に必ず alias を張り替える。
"""
import asyncio
import sys

sys.path.insert(0, "D:/done")

ARTIFACT_ID = "e02d2cca-ce63-4367-b3a7-ae78aadfe156"
USER_ID = "2582a188-ff24-4a4f-b989-6063034d90b2"
CUSTOM_DOMAINS = ["paina.info", "www.paina.info", "paina.com"]


async def main() -> None:
    from app.services.artifact_publication_service import ArtifactPublicationService
    from app.services.chat_artifact_service import ChatArtifactService
    from app.tools.publish_site.vercel_domains import get_vercel, VercelError

    artifacts = ChatArtifactService()
    artifact = await artifacts.get(ARTIFACT_ID, USER_ID)
    if not artifact:
        print("ARTIFACT NOT FOUND")
        return

    print("deploying...", flush=True)
    release = await ArtifactPublicationService().deploy_dedicated_release(
        artifact, user_id=USER_ID
    )
    print("deployed:", release.get("shared_url"), release.get("job_status"), flush=True)

    v = await get_vercel(USER_ID)
    project_id = str(release["deployment_project"])
    deployments = await v.list_deployments(project_id, target="production", limit=1)
    if not deployments:
        print("NO PRODUCTION DEPLOYMENT")
        return
    dpl = deployments[0]
    dpl_id = dpl.get("uid") or dpl.get("id")
    print("production deployment:", dpl_id, dpl.get("url"), flush=True)

    for domain in CUSTOM_DOMAINS:
        try:
            await v.assign_alias(dpl_id, domain)
            print("  alias ok:", domain, flush=True)
        except VercelError as exc:
            print("  alias FAILED:", domain, exc, flush=True)

    await artifacts.update(
        ARTIFACT_ID,
        {
            "publish_status": "live",
            "delivery_status": "ready",
            "last_publish_error": None,
        },
        USER_ID,
    )
    print("DONE", flush=True)


asyncio.run(main())
