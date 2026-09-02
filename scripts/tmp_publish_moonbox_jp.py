"""moonbox-jp の最新ソースを専用Vercelプロジェクトへ公開する（単発）。"""
import asyncio
import sys

sys.path.insert(0, "D:/done")

from app.services.chat_artifact_service import ChatArtifactService
from app.services.artifact_publication_service import ArtifactPublicationService


async def main() -> None:
    svc = ChatArtifactService()
    rows = (
        svc.supabase.table(svc.table)
        .select("*")
        .eq("slug", "moonbox-jp")
        .execute()
    ).data or []
    if not rows:
        print("NOT FOUND")
        return
    artifact = rows[0]
    print("artifact_id:", artifact.get("id"), "user:", artifact.get("user_id"))
    release = await ArtifactPublicationService().deploy_dedicated_release(
        artifact, user_id=artifact.get("user_id")
    )
    print("status:", release.get("status"))
    print("url:", release.get("shared_url") or release.get("deployment_url"))
    print("project:", release.get("deployment_project"))


asyncio.run(main())
