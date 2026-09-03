"""
A-1 ライブ検証: インスペクタの「画像再生成」が裏で叩く生成パイプライン
（OpenAI gpt-image-2 → Supabase Storage → 公開URL）が実際に通るかを確認する。

- 低画質($0.006)で1枚だけ生成
- 既存 generated_images の created_by を流用（FK安全）
- 返却URLが HTTP 200 で到達可能か確認
- 生成したテスト行 + Storage ファイルは最後に削除（汚さない）
"""
import asyncio
import sys
import pathlib

sys.path.insert(0, str(pathlib.Path(__file__).resolve().parent.parent))

from dotenv import load_dotenv
load_dotenv()  # .env を os.environ に展開（settings 経由でなくても確実にキーを得る）

import httpx
from app.services.image_generation_service import ImageGenerationService, BUCKET


async def main() -> int:
    svc = ImageGenerationService()

    # 既存行から有効な created_by を1つ拝借（FK制約を確実に満たす）
    existing = (
        svc.supabase.table(svc.table)
        .select("created_by")
        .not_.is_("created_by", "null")
        .limit(1)
        .execute()
    )
    if not existing.data:
        print("NG: generated_images に既存行がなく user_id を確保できない")
        return 1
    user_id = existing.data[0]["created_by"]
    print(f"使用 user_id: {user_id}")

    print("生成中（low quality, 1024x1024）...")
    rec = await svc.generate(
        prompt="A minimal test image: a single red circle centered on a plain white background.",
        user_id=user_id,
        size="1024x1024",
        quality="low",
    )
    url = rec.get("url")
    row_id = rec.get("id")
    path = rec.get("storage_path")
    print(f"OK: 生成成功 url={url}")
    print(f"    row_id={row_id} storage_path={path}")

    # URL 到達確認
    async with httpx.AsyncClient(timeout=30.0, follow_redirects=True) as client:
        r = await client.get(url)
        ct = r.headers.get("content-type", "")
        print(f"URL fetch: status={r.status_code} content-type={ct} bytes={len(r.content)}")
        reachable = r.status_code == 200 and len(r.content) > 1000

    # 後始末（テスト行 + Storage ファイル削除）
    cleaned = []
    try:
        if path:
            svc.supabase.storage.from_(BUCKET).remove([path])
            cleaned.append("storage")
    except Exception as e:
        print(f"storage 削除失敗(無視): {e}")
    try:
        if row_id:
            svc.supabase.table(svc.table).delete().eq("id", row_id).execute()
            cleaned.append("db row")
    except Exception as e:
        print(f"db 行削除失敗(無視): {e}")
    print(f"後始末: {', '.join(cleaned) if cleaned else 'なし'}")

    print("=" * 40)
    print("RESULT:", "PASS ✅ パイプライン疎通" if reachable else "FAIL ❌")
    return 0 if reachable else 1


if __name__ == "__main__":
    sys.exit(asyncio.run(main()))
