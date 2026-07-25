"""
サロンボード スタイルアップ補助ツール — 写真解析API

美容師がヘアスタイルの写真をアップロードすると、ホットペッパービューティー
「サロンボード」のスタイル投稿フォームに入力する全項目を、AI(Gemini Vision)が
自動で推定して返す。美容師に見せるデモ用のため認証不要。
"""
from __future__ import annotations

import asyncio
import json
import logging
import re
from typing import Any

from fastapi import APIRouter, File, HTTPException, UploadFile

from google import genai
from google.genai import types as genai_types

from app.config import settings

logger = logging.getLogger(__name__)

router = APIRouter(prefix="/salonboard-styleup", tags=["salonboard-styleup"])

MODEL = "gemini-2.5-pro"

# --- サロンボードのスタイル投稿フォームの選択肢定義 ---
CATEGORY_OPTIONS = ["レディース", "メンズ"]
LENGTH_OPTIONS = ["ベリーショート", "ショート", "ボブ", "ミディアム", "セミロング", "ロング"]
MENU_OPTIONS = ["パーマ", "ストレートパーマ・縮毛矯正", "エクステ", "ブリーチ"]
HAIR_AMOUNT_OPTIONS = ["少ない", "普通", "多い"]
HAIR_QUALITY_OPTIONS = ["柔らかい", "普通", "硬い"]
HAIR_THICKNESS_OPTIONS = ["細い", "普通", "太い"]
HAIR_CURL_OPTIONS = ["なし", "少し", "強い"]
AGE_OPTIONS = ["キッズ", "10代", "20代", "30代", "40代", "50代", "60代以上"]
FACE_OPTIONS = ["丸型", "卵型", "四角", "逆三角", "ベース", "面長"]

MAX_IMAGES = 3
MAX_IMAGE_BYTES = 12 * 1024 * 1024  # 12MB
ALLOWED_MIME = {"image/png", "image/jpeg", "image/webp", "image/bmp", "image/gif"}

ANALYSIS_PROMPT = """あなたは美容室のヘアカタログ制作に精通したプロのアシスタントです。
提供されたヘアスタイルの写真を見て、ホットペッパービューティーの「サロンボード」の
スタイル投稿フォームに入力する項目を、できる限り正確に判定してください。

# 出力形式
必ず次の構造のJSONだけを出力してください。前後に説明文やマークダウン記法を付けないこと。
各項目は {"value": 値, "confidence": 0〜1の数値, "reason": "判断理由(40字以内の日本語)"} の形です。

{
  "category": {"value": "「レディース」か「メンズ」", "confidence": 0.0, "reason": ""},
  "length": {"value": "「ベリーショート」「ショート」「ボブ」「ミディアム」「セミロング」「ロング」のいずれか", "confidence": 0.0, "reason": ""},
  "menu": {"value": ["「パーマ」「ストレートパーマ・縮毛矯正」「エクステ」「ブリーチ」から該当するものの配列。なければ空配列"], "confidence": 0.0, "reason": ""},
  "menu_text": {"value": "施術メニュー内容を簡潔に(例:「カット＋カラー」「カット＋ブリーチ＋カラー」「パーマ＋カット」。40字以内)", "confidence": 0.0, "reason": ""},
  "hair_amount": {"value": "「少ない」「普通」「多い」のいずれか。迷ったら「普通」", "confidence": 0.0, "reason": ""},
  "hair_quality": {"value": "「柔らかい」「普通」「硬い」のいずれか。迷ったら「普通」", "confidence": 0.0, "reason": ""},
  "hair_thickness": {"value": "「細い」「普通」「太い」のいずれか。迷ったら「普通」", "confidence": 0.0, "reason": ""},
  "hair_curl": {"value": "「なし」「少し」「強い」のいずれか。迷ったら「なし」", "confidence": 0.0, "reason": ""},
  "age": {"value": "「キッズ」「10代」「20代」「30代」「40代」「50代」「60代以上」のいずれか。迷ったら最も近い年代", "confidence": 0.0, "reason": ""},
  "face": {"value": "「丸型」「卵型」「四角」「逆三角」「ベース」「面長」のいずれか。迷ったら「卵型」", "confidence": 0.0, "reason": ""},
  "style_name": {"value": "スタイル名(30字以内)", "confidence": 0.0, "reason": ""},
  "comment": {"value": "スタイル紹介コメント(120字以内)", "confidence": 0.0, "reason": ""},
  "hashtags": {"value": ["ハッシュタグの配列。#は付けない。各20字以内。最大10個"], "confidence": 0.0, "reason": ""},
  "images": [{"angle": "「front」「side」「back」のいずれか", "confidence": 0.0, "reason": ""}]
}

# 判定ルール
- 髪の長さは肩の位置を基準に正確に判定する。耳上=ベリーショート、あご周り=ショート/ボブ、肩=ミディアム、肩下=セミロング、胸あたり=ロング。
- 明るい髪色や複雑なカラー(ハイトーン、グラデーション等)が見えたら menu に「ブリーチ」を含めることを検討する。
- はっきりしたウェーブ・カールがあれば menu に「パーマ」を含めることを検討する。直毛で不自然なほど真っ直ぐなら「ストレートパーマ・縮毛矯正」を検討する。
- 写真だけでは断定しにくい項目(髪量・髪質・太さ・クセ)も必ず選択肢から1つ選ぶ。迷う場合は髪量/髪質/太さは「普通」、クセは「なし」にして confidence を低め(0.3〜0.5)にする。
- 年代・顔型はモデルの見た目から推定する。断定が難しければ confidence を下げる。
- reason は必ず40字以内の日本語で、なぜその値にしたかを簡潔に書く。

# スタイル名・コメント・ハッシュタグの作り方
ホットペッパービューティーで検索されやすく、お客様が来店したくなる魅力的な内容にする。
写真の髪色・長さ・質感・雰囲気・季節感に合わせる。confidence は 0.9 でよい。
例:
- style_name: 「丸みショートボブ × ミルクティーベージュ」
- comment: 「柔らかい丸みのショートボブで小顔見せ。透明感のあるミルクティーベージュが肌をきれいに見せてくれます。乾かすだけで決まる扱いやすさも魅力。ダメージが気になる方にもおすすめのスタイルです。」
- hashtags: ["ショートボブ", "ミルクティーベージュ", "小顔ショート", "透明感カラー", "大人可愛い"]

写真が複数枚ある場合は、すべてを総合して判断してください。

# 撮影角度の判定（images 配列）
提供された各写真について、撮影角度を1枚ずつ判定し、images 配列に「写真の順番通り」に入れてください。
- front: 顔が正面から見える写真
- side: 横顔（顔のラインが横向き）が見える写真
- back: 後ろ姿・後頭部が中心の写真
写真が1枚なら images は1要素、3枚なら3要素にしてください。reason は判定理由を30字以内で書いてください。
"""


def _mime_of(upload: UploadFile) -> str:
    """アップロードファイルのMIMEタイプを判定する。"""
    ct = (upload.content_type or "").lower()
    if ct in ALLOWED_MIME:
        return ct
    name = (upload.filename or "").lower()
    if name.endswith(".png"):
        return "image/png"
    if name.endswith(".webp"):
        return "image/webp"
    if name.endswith(".gif"):
        return "image/gif"
    if name.endswith(".bmp"):
        return "image/bmp"
    return "image/jpeg"


def _strip_json(text: str) -> str:
    """```json ... ``` のコードフェンスを取り除く。"""
    t = text.strip()
    if t.startswith("```"):
        t = re.sub(r"^```[a-zA-Z]*\n?", "", t)
        t = re.sub(r"\n?```$", "", t)
    return t.strip()


def _analyze_sync(images: list[tuple[bytes, str]]) -> str:
    """Gemini Vision に写真を渡し、サロンボード項目のJSONテキストを得る。"""
    client = genai.Client(api_key=settings.GOOGLE_GEMINI_API_KEY)
    parts: list[Any] = [
        genai_types.Part.from_bytes(data=data, mime_type=mime)
        for data, mime in images
    ]
    n = len(images)
    header = (
        f"# 重要な前提\n"
        f"このリクエストには合計 {n} 枚の写真が添付されています。\n"
        f"後述の images 配列は必ず{n}要素返してください。i番目の要素は添付の i番目の写真に対する判定です。\n"
        f"images 以外の項目（fields）は{n}枚の写真を総合的に判断して1セットだけ返してください。\n\n"
    )
    parts.append(genai_types.Part(text=header + ANALYSIS_PROMPT))

    logger.info("salonboard-styleup: analyzing %d image(s) with %s", len(images), MODEL)
    response = client.models.generate_content(
        model=MODEL,
        contents=[genai_types.Content(parts=parts)],
        config=genai_types.GenerateContentConfig(
            response_mime_type="application/json",
            temperature=0.4,
        ),
    )
    return response.text or ""


def _clamp_confidence(raw: Any) -> float:
    try:
        return max(0.0, min(1.0, round(float(raw), 2)))
    except (TypeError, ValueError):
        return 0.0


def _coerce_single(raw: Any, options: list[str], default: str) -> dict:
    """単一選択フィールドを検証・正規化する。"""
    if not isinstance(raw, dict):
        return {"value": default, "confidence": 0.0, "reason": ""}
    value = raw.get("value", default)
    if value not in options:
        match = next(
            (o for o in options if o in str(value) or str(value) in o), None
        )
        value = match or default
    return {
        "value": value,
        "confidence": _clamp_confidence(raw.get("confidence")),
        "reason": str(raw.get("reason", ""))[:60],
    }


def _coerce_multi(raw: Any, options: list[str]) -> dict:
    """複数選択フィールド(メニュー内容)を検証・正規化する。"""
    if not isinstance(raw, dict):
        return {"value": [], "confidence": 0.0, "reason": ""}
    values = raw.get("value", [])
    if not isinstance(values, list):
        values = []
    clean = [v for v in values if v in options]
    return {
        "value": clean,
        "confidence": _clamp_confidence(raw.get("confidence")),
        "reason": str(raw.get("reason", ""))[:60],
    }


def _coerce_tags(raw: Any) -> dict:
    """ハッシュタグ配列を検証・正規化する。"""
    if not isinstance(raw, dict):
        return {"value": [], "confidence": 0.0, "reason": ""}
    values = raw.get("value", [])
    if not isinstance(values, list):
        values = []
    clean: list[str] = []
    for v in values:
        s = str(v).lstrip("#").strip()[:20]
        if s and s not in clean:
            clean.append(s)
    return {
        "value": clean[:10],
        "confidence": _clamp_confidence(raw.get("confidence")),
        "reason": str(raw.get("reason", ""))[:60],
    }


def _coerce_text(raw: Any, maxlen: int) -> dict:
    """テキストフィールド(スタイル名・コメント)を検証・正規化する。"""
    if not isinstance(raw, dict):
        return {"value": "", "confidence": 0.0, "reason": ""}
    return {
        "value": str(raw.get("value", ""))[:maxlen],
        "confidence": _clamp_confidence(raw.get("confidence")),
        "reason": str(raw.get("reason", ""))[:60],
    }


@router.get("/options")
async def get_form_options() -> dict:
    """サロンボードのスタイル投稿フォームの選択肢一覧を返す。"""
    return {
        "category": CATEGORY_OPTIONS,
        "length": LENGTH_OPTIONS,
        "menu": MENU_OPTIONS,
        "hair_amount": HAIR_AMOUNT_OPTIONS,
        "hair_quality": HAIR_QUALITY_OPTIONS,
        "hair_thickness": HAIR_THICKNESS_OPTIONS,
        "hair_curl": HAIR_CURL_OPTIONS,
        "age": AGE_OPTIONS,
        "face": FACE_OPTIONS,
    }


@router.post("/analyze")
async def analyze_style_photos(files: list[UploadFile] = File(...)) -> dict:
    """ヘアスタイル写真を解析し、サロンボードの入力項目を推定して返す。"""
    if not settings.GOOGLE_GEMINI_API_KEY:
        raise HTTPException(
            status_code=503, detail="画像解析の準備ができていません(APIキー未設定)"
        )
    if not files:
        raise HTTPException(status_code=400, detail="写真がありません")

    images: list[tuple[bytes, str]] = []
    for f in files[:MAX_IMAGES]:
        data = await f.read()
        if not data:
            continue
        if len(data) > MAX_IMAGE_BYTES:
            raise HTTPException(
                status_code=400, detail=f"画像のサイズが大きすぎます: {f.filename}"
            )
        images.append((data, _mime_of(f)))

    if not images:
        raise HTTPException(status_code=400, detail="有効な画像がありません")

    try:
        raw_text = await asyncio.to_thread(_analyze_sync, images)
    except Exception as e:  # noqa: BLE001
        logger.error("salonboard-styleup analyze failed: %s", e, exc_info=True)
        raise HTTPException(status_code=502, detail="画像解析に失敗しました")

    try:
        data = json.loads(_strip_json(raw_text))
    except json.JSONDecodeError as e:
        logger.error(
            "salonboard-styleup JSON parse failed: %s / raw=%s", e, raw_text[:500]
        )
        raise HTTPException(status_code=502, detail="解析結果の読み取りに失敗しました")

    # Gemini が複数写真の時に配列で返すことがあるため、最初のオブジェクトに正規化
    if isinstance(data, list):
        data = data[0] if data and isinstance(data[0], dict) else {}

    fields = {
        "category": _coerce_single(data.get("category"), CATEGORY_OPTIONS, "レディース"),
        "length": _coerce_single(data.get("length"), LENGTH_OPTIONS, "ミディアム"),
        "menu": _coerce_multi(data.get("menu"), MENU_OPTIONS),
        "hair_amount": _coerce_single(data.get("hair_amount"), HAIR_AMOUNT_OPTIONS, "普通"),
        "hair_quality": _coerce_single(data.get("hair_quality"), HAIR_QUALITY_OPTIONS, "普通"),
        "hair_thickness": _coerce_single(data.get("hair_thickness"), HAIR_THICKNESS_OPTIONS, "普通"),
        "hair_curl": _coerce_single(data.get("hair_curl"), HAIR_CURL_OPTIONS, "なし"),
        "age": _coerce_single(data.get("age"), AGE_OPTIONS, "20代"),
        "face": _coerce_single(data.get("face"), FACE_OPTIONS, "卵型"),
        "menu_text": _coerce_text(data.get("menu_text"), 100),
        "style_name": _coerce_text(data.get("style_name"), 30),
        "comment": _coerce_text(data.get("comment"), 120),
        "hashtags": _coerce_tags(data.get("hashtags")),
    }

    images_raw = data.get("images", [])
    if not isinstance(images_raw, list):
        images_raw = []
    result_images: list[dict] = []
    for img in images_raw[:MAX_IMAGES]:
        if not isinstance(img, dict):
            continue
        angle = img.get("angle", "front")
        if angle not in {"front", "side", "back"}:
            angle = "front"
        result_images.append({
            "angle": angle,
            "confidence": _clamp_confidence(img.get("confidence")),
            "reason": str(img.get("reason", ""))[:60],
        })

    return {
        "success": True,
        "image_count": len(images),
        "fields": fields,
        "images": result_images,
    }


# ============================================================
# 実投稿（本物Chromeでサロンボードへ登録）
# 投稿は数分かかるため、受付でジョブを作りバックグラウンドで実行。
# フロントは job_id で状況をポーリングする。状態はサーバー内(メモリ)で保持。
# ============================================================
import asyncio  # noqa: E402
import tempfile  # noqa: E402
import uuid  # noqa: E402
from pathlib import Path  # noqa: E402

from fastapi import Form  # noqa: E402
from app.services.salonboard_post_job_service import (  # noqa: E402
    SalonboardPostJobService,
    normalize_job_for_api,
)
from app.services.salonboard_credentials_service import (  # noqa: E402
    SalonboardCredentialsService,
)

# job_id -> {status, message, style_name}
_POST_JOBS: dict[str, dict] = {}
_POST_JOBS_MAX = 200


def _ext_for(upload: UploadFile) -> str:
    name = (upload.filename or "").lower()
    for e in (".png", ".jpg", ".jpeg", ".webp"):
        if name.endswith(e):
            return e
    return ".jpg"


@router.post("/post")
async def post_style(
    device_id: str = Form(...),
    fields: str = Form(...),
    images: str = Form("[]"),
    stylist_name: str = Form(""),
    files: list[UploadFile] = File(...),
) -> dict:
    """写真と項目を受け取り、実投稿ジョブを起動して job_id を返す。"""
    if not device_id:
        raise HTTPException(status_code=400, detail="device_id がありません")

    # 課金ゲート: 無料投稿枠（1件）を超えた未課金・未免除の利用者はブロックし、決済へ誘導する。
    cred_svc = SalonboardCredentialsService()
    entitlement = await cred_svc.get_entitlement(device_id)
    if not entitlement.get("allowed"):
        raise HTTPException(
            status_code=402,
            detail={
                "error": "payment_required",
                "reason": entitlement.get("reason"),
                "message": "無料でお試しいただける1回の投稿は完了しています。続けてご利用いただくには、月額プランへのお申し込みをお願いします。",
                "checkout_url": entitlement.get("checkout_url"),
            },
        )

    try:
        fields_dict = json.loads(fields)
        images_meta = json.loads(images) if images else []
    except json.JSONDecodeError:
        raise HTTPException(status_code=400, detail="項目データが不正です")
    if not files:
        raise HTTPException(status_code=400, detail="写真がありません")

    job_id = str(uuid.uuid4())
    job_dir = Path(tempfile.gettempdir()) / "salonboard_post" / job_id
    job_dir.mkdir(parents=True, exist_ok=True)
    photo_paths: list[str] = []
    for i, f in enumerate(files[:MAX_IMAGES]):
        data = await f.read()
        if not data:
            continue
        if len(data) > MAX_IMAGE_BYTES:
            raise HTTPException(status_code=400, detail="画像のサイズが大きすぎます")
        dest = job_dir / f"{i}{_ext_for(f)}"
        dest.write_bytes(data)
        photo_paths.append(str(dest))
    if not photo_paths:
        raise HTTPException(status_code=400, detail="有効な写真がありません")

    # 古いジョブの掃除
    if len(_POST_JOBS) > _POST_JOBS_MAX:
        for k in list(_POST_JOBS)[:-_POST_JOBS_MAX]:
            _POST_JOBS.pop(k, None)

    _POST_JOBS[job_id] = {"status": "pending", "message": "投稿を受け付けました", "style_name": None}
    job_service = SalonboardPostJobService()
    await job_service.create(
        job_id=job_id,
        device_id=device_id,
        fields=fields_dict,
        images_meta=images_meta,
        photo_count=len(photo_paths),
    )

    def _persist_status(status: str, message: str) -> None:
        async def _update() -> None:
            try:
                await job_service.update(job_id, status=status, message=message)
            except Exception as e:  # noqa: BLE001
                logger.warning("salonboard post job status persist failed: %s", e)

        try:
            asyncio.create_task(_update())
        except RuntimeError:
            pass

    def _cb(status: str, message: str) -> None:
        if job_id in _POST_JOBS:
            _POST_JOBS[job_id]["status"] = status
            _POST_JOBS[job_id]["message"] = message
        _persist_status(status, message)

    async def _runner() -> None:
        from app.services.salonboard_browser_session import run_style_post
        try:
            await job_service.update(job_id, status="running", message="投稿処理を開始しました")
            res = await run_style_post(
                device_id=device_id,
                photo_paths=photo_paths,
                fields=fields_dict,
                images_meta=images_meta,
                stylist_name=stylist_name or None,
                status_cb=_cb,
            )
            if res.get("ok"):
                _POST_JOBS[job_id] = {
                    "status": "done",
                    "message": res.get("message", "登録しました"),
                    "style_name": res.get("style_name"),
                    "style_id": res.get("style_id"),
                    "registered": res.get("registered"),
                    "published": res.get("published"),
                }
                await job_service.update(
                    job_id,
                    status="done",
                    message=res.get("message", "サロンボードに登録しました"),
                    style_name=res.get("style_name"),
                    style_id=res.get("style_id"),
                    registered=res.get("registered"),
                    published=res.get("published"),
                    result_data=res,
                )
                # 投稿成功時のみ回数を加算（無料枠の消費をここで確定する）。
                try:
                    await cred_svc.increment_posts(device_id)
                except Exception as e:  # noqa: BLE001
                    logger.warning("posts_used increment failed: %s", e)
            else:
                _POST_JOBS[job_id] = {
                    "status": "error",
                    "message": res.get("message", "投稿に失敗しました"),
                    "style_name": res.get("style_name"),
                    "style_id": res.get("style_id"),
                    "registered": res.get("registered"),
                    "published": res.get("published"),
                }
                await job_service.update(
                    job_id,
                    status="error",
                    message=res.get("message", "投稿に失敗しました"),
                    style_name=res.get("style_name"),
                    style_id=res.get("style_id"),
                    registered=res.get("registered"),
                    published=res.get("published"),
                    result_data=res,
                    error=res.get("message"),
                )
        except Exception as e:  # noqa: BLE001
            logger.error("salonboard post job failed: %s", e, exc_info=True)
            _POST_JOBS[job_id] = {"status": "error", "message": f"投稿中にエラー: {e}", "style_name": None}
            await job_service.update(
                job_id,
                status="error",
                message=f"投稿中にエラー: {e}",
                error=str(e),
            )

    asyncio.create_task(_runner())
    return {"job_id": job_id, "status": "pending"}


@router.get("/post-status/{job_id}")
async def post_status(job_id: str) -> dict:
    """投稿ジョブの状況を返す。"""
    persisted = await SalonboardPostJobService().get(job_id)
    if persisted:
        return normalize_job_for_api(job_id, persisted)
    job = _POST_JOBS.get(job_id)
    if not job:
        raise HTTPException(status_code=404, detail="ジョブが見つかりません")
    return {"job_id": job_id, **job}
