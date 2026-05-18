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
HAIR_AMOUNT_OPTIONS = ["設定しない", "少ない", "普通", "多い"]
HAIR_QUALITY_OPTIONS = ["設定しない", "柔らかい", "普通", "硬い"]
HAIR_THICKNESS_OPTIONS = ["設定しない", "細い", "普通", "太い"]
HAIR_CURL_OPTIONS = ["設定しない", "なし", "少し", "強い"]
AGE_OPTIONS = ["設定しない", "キッズ", "10代", "20代", "30代", "40代", "50代", "60代以上"]
FACE_OPTIONS = ["設定しない", "丸型", "卵型", "四角", "逆三角", "ベース", "面長"]

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
  "hair_amount": {"value": "「設定しない」「少ない」「普通」「多い」のいずれか", "confidence": 0.0, "reason": ""},
  "hair_quality": {"value": "「設定しない」「柔らかい」「普通」「硬い」のいずれか", "confidence": 0.0, "reason": ""},
  "hair_thickness": {"value": "「設定しない」「細い」「普通」「太い」のいずれか", "confidence": 0.0, "reason": ""},
  "hair_curl": {"value": "「設定しない」「なし」「少し」「強い」のいずれか", "confidence": 0.0, "reason": ""},
  "age": {"value": "「設定しない」「キッズ」「10代」「20代」「30代」「40代」「50代」「60代以上」のいずれか", "confidence": 0.0, "reason": ""},
  "face": {"value": "「設定しない」「丸型」「卵型」「四角」「逆三角」「ベース」「面長」のいずれか", "confidence": 0.0, "reason": ""},
  "style_name": {"value": "スタイル名(30字以内)", "confidence": 0.0, "reason": ""},
  "comment": {"value": "スタイル紹介コメント(120字以内)", "confidence": 0.0, "reason": ""},
  "hashtags": {"value": ["ハッシュタグの配列。#は付けない。各20字以内。最大10個"], "confidence": 0.0, "reason": ""}
}

# 判定ルール
- 髪の長さは肩の位置を基準に正確に判定する。耳上=ベリーショート、あご周り=ショート/ボブ、肩=ミディアム、肩下=セミロング、胸あたり=ロング。
- 明るい髪色や複雑なカラー(ハイトーン、グラデーション等)が見えたら menu に「ブリーチ」を含めることを検討する。
- はっきりしたウェーブ・カールがあれば menu に「パーマ」を含めることを検討する。直毛で不自然なほど真っ直ぐなら「ストレートパーマ・縮毛矯正」を検討する。
- 写真だけでは断定しにくい項目(髪量・髪質・太さ・クセ)は、最も可能性が高い値を選びつつ confidence を低め(0.3〜0.5)にする。判断が全くつかなければ value を「設定しない」にする。
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
    parts.append(genai_types.Part(text=ANALYSIS_PROMPT))

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
        "value": clean[:20],
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

    fields = {
        "category": _coerce_single(data.get("category"), CATEGORY_OPTIONS, "レディース"),
        "length": _coerce_single(data.get("length"), LENGTH_OPTIONS, "ミディアム"),
        "menu": _coerce_multi(data.get("menu"), MENU_OPTIONS),
        "hair_amount": _coerce_single(data.get("hair_amount"), HAIR_AMOUNT_OPTIONS, "設定しない"),
        "hair_quality": _coerce_single(data.get("hair_quality"), HAIR_QUALITY_OPTIONS, "設定しない"),
        "hair_thickness": _coerce_single(data.get("hair_thickness"), HAIR_THICKNESS_OPTIONS, "設定しない"),
        "hair_curl": _coerce_single(data.get("hair_curl"), HAIR_CURL_OPTIONS, "設定しない"),
        "age": _coerce_single(data.get("age"), AGE_OPTIONS, "設定しない"),
        "face": _coerce_single(data.get("face"), FACE_OPTIONS, "設定しない"),
        "style_name": _coerce_text(data.get("style_name"), 30),
        "comment": _coerce_text(data.get("comment"), 120),
        "hashtags": _coerce_tags(data.get("hashtags")),
    }

    return {"success": True, "image_count": len(images), "fields": fields}
