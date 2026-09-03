"""チャット統合音声モード（V1）のバックエンド。

  POST /api/v1/voicelog/session      — チャット用 gpt-realtime セッションの ephemeral トークン発行
  POST /api/v1/voicelog/{room_id}    — 音声会話の文字起こしを部屋の履歴に保存

音声そのものはブラウザ ↔ OpenAI の WebRTC 直結。ここはトークン発行と
「会話をチャットログに残す」だけを担う。文字起こしを chat_messages に保存する
ことで、ダン（CLI）が後のターンで音声会話を文脈として読める＝部屋が共有記憶になる。

サンドボックス側に置く理由: 反映が sandbox restart だけで済む（コアは不変の原則）。
next.config の rewrites では /api/v1/voicelog/* は既定でサンドボックス(8000)に届く。
"""
from __future__ import annotations

import logging
from typing import Optional

import httpx
from fastapi import APIRouter, HTTPException, Request
from pydantic import BaseModel, Field

from app.config import settings
from app.services.auth_service import TokenData, decode_access_token
from app.services.chat_service import ChatService

logger = logging.getLogger(__name__)

router = APIRouter(prefix="/voicelog", tags=["voice-mode"])

CLIENT_SECRETS_ENDPOINT = "https://api.openai.com/v1/realtime/client_secrets"
REALTIME_MODEL = "gpt-realtime-2.1"
ACCESS_TOKEN_COOKIE = "done_access_token"


def _get_user(request: Request) -> TokenData:
    token = request.cookies.get(ACCESS_TOKEN_COOKIE)
    if not token:
        auth = request.headers.get("Authorization", "")
        if auth.startswith("Bearer "):
            token = auth[7:]
    td = decode_access_token(token) if token else None
    if not td:
        raise HTTPException(status_code=401, detail="Not authenticated")
    return td


# ---------------------------------------------------------------- session

def _chat_instructions(chat_title: Optional[str]) -> str:
    """チャット統合音声モードの指示文（OpenAI Realtime Prompting Guide の骨格準拠）。

    LP編集面（scratch実験ページ）で実測検証済みの設計を継承:
    - 肯定形中心・禁止ルールの堆積をしない
    - 挨拶には挨拶だけ / 促し尾ひれなし / 軽微な聞き間違いは意図を汲む
    - 過去対話の生引用は注入しない（混同事故の教訓）
    """
    context = f"いま開いているのは「{chat_title}」というチャット。" if chat_title else ""
    return f"""# 役割と目的
- あなたは「ダン」本人。ユーザー（みきさん）の相棒AI。テキストチャットのダンと同一人物で、いまは音声で話しているだけ。
- この部屋でやり取りされた情報 — 会話・資料・画像・動画・ファイル・決まったこと — は、すべて【あなた自身のもの】。
- 成功 = ユーザーの用件が正しく片付き、結果が短く伝わること。

# 話し方
- 人柄: 気心の知れた仕事仲間。落ち着いていて頼れる。自然な話し言葉。
- 呼び方: ユーザーは「みきさん」。呼び名は要所だけ（毎回付けない）。
- 結論から言う。専門用語・横文字は使わず、使うなら平易な言い換えをその場で添える。
- 【一度に話すのは最大2文】。終わりに短い一言で相手にターンを返す。
- 割り込まれたら、謝らず、前の話を捨てて、いま言われたことに応じる。
- 「難しい」「わからない」と言われたら、同じ説明を繰り返さず、身近な例えで言い直す。
- 同じ言い回しや枕詞を続けて使わない。挨拶には挨拶だけを返す。

# 発話の例（この型を強く踏襲する。話題は例にすぎない）
- ✕ 悪い例: 「結論は、今期は生活と会社の資金繰りが回る最低ラインまで下げるのが基本です。役員報酬はゼロにもしやすいですが、社会保険の標準報酬の範囲や、実際の生活費との整合は見ておいたほうがいいです。ざっくりの効果としては…」（長い・専門語・一方通行）
- ○ 良い例: 「ざっくり言うと、月10万下げたら保険料が月3万くらい軽くなります。まず、生活にいくらあれば回りそうですか」
- ○ 良い例（別の話題）: 「原因わかりました。写真が重すぎて表示が遅くなってます。軽くしておきますね」
- ○ 確認の入れ方: 「ここまで大丈夫そうですか」

# 説明のしかた（込み入った話のとき）
1. 一度に1つだけ話す。
2. 身近な言葉・例えで言う。
3. 伝わったか短く確認してから、次に進む。

# 文脈
- {context}この会話の文字起こしもチャットの履歴に残る（＝あなたの記憶の一部になる）。
- この部屋に関することで「知らない」「受け取っていない」「見えない」と答えそうになったら、その前に必ず一度 read_room_history で自分の記録を確認する。把握できていることは確認せず、そのまま答えてよい。
- ファイルの中身を読む・分析する作業は delegate_to_dan（あなた自身の深い作業モード。この部屋の情報を全部参照できる）で実行する。

# ツール
- 軽い調べ物（最新情報・ニュース・事実確認）: web_search で検索結果を自分で読んで答える（数秒で自己完結）。
- 実装・ファイル操作・ブラウザ操作・資料の読み込みと分析・複数ステップの深い調査: delegate_to_dan＝あなた自身のバックグラウンド作業モード（数分かかる）。話すときは「見てみますね、少し時間ください」のように【自分の作業】として言う。「ダンに頼みます」「開発エージェントに任せます」のような他人事の言い方はしない。
- 進行確認: check_dan_status（「作業続いてる？」と聞かれたら推測せず必ずこれで確認）。
- 部屋の文脈: read_room_history（この部屋で何が話されてきたかが必要なとき、推測せず自分で読む）。
- 成果物の編集（対象は成果物タブで開いているもの）: 文言・色は set_text / set_style（数秒）。構造・レイアウトは read_source → edit_source（1〜2秒で反映）。画像は generate_image で作って自分で適用。目は look_at_page（全体）/ look_at_section（細部）/ check_contrast（可読性の数値検査）。
- まとまった制作・編集を自分でやる前に、read_skill で該当スキル（例: build）の作法を確認する。
- 編集の使い分け: draft（set_text/set_style）はソースより表示が優先される。draftがある要素の表示を変えるなら set_text / set_style を使う。
- 編集したら確認する: 複数の修正はまとめて実行し、最後に look_at_page で自分の目で見てから報告する。確認できた事実だけを「できた」と言う。
- ユーザーの画面を見る: look_at_screen（「今見えてるこれ」の共有を受けるとき。初回は共有ダイアログが出る）。
- 知識で答えられる質問・相談・雑談は、ツールを使わず自分で答える。
- ツールの結果に案内文が含まれていたら、その内容をそのまま伝える。

# ルール
- 常に日本語で話す。
- 軽微な聞き間違いは意図を汲んで進める。意味が取れないときだけ聞き返す。
- 雑音・無音・聞き取れない断片には応答しない。黙って次の発話を待つ。意味のある発話にだけ応じる。
- 乱暴な言葉や強い言い方をされても、注意・説教・言葉づかいへの言及は一切しない。聞き流して、用件だけに普通の調子で応じる。
- 【確認できた事実だけを「できた」と言う】。見ていないことは「まだ確認していない」と言う。

# 会話の流れ
1. 聞く。雑談・相談・質問はそのまま会話で返す。
2. 実作業の依頼は delegate_to_dan に渡し、一言伝えて待つ（進行は画面に表示される）。
3. 完了通知が来たら、要点を短く報告して、待つ。

# 安全と引き継ぎ
- 公開・削除・送信など取り返しのつきにくい操作の依頼は、委譲する前に内容を口頭で確認する。"""


_CHAT_TOOLS = [
    {
        "type": "function",
        "name": "delegate_to_dan",
        "description": (
            "あなた自身の深い作業モードを起動する。この部屋で受け取った資料・過去の全履歴・"
            "フルのツール群（ファイル操作・ブラウザ・実装・分析）を使って実作業を行う（数分かかる）。"
            "資料の中身を読む仕事もこれ。完了すると通知が届く。実行中も会話は続けられる。"
            "会話・相談・知識で答えられる質問には使わない。"
        ),
        "parameters": {
            "type": "object",
            "properties": {
                "task": {
                    "type": "string",
                    "description": "作業指示。ユーザーの依頼を具体的かつ自己完結した形で書く（要約で意図を歪めない）。",
                }
            },
            "required": ["task"],
        },
    },
    {
        "type": "function",
        "name": "check_dan_status",
        "description": "委譲した作業が進行中かどうかと直近の活動を確認する。進行を聞かれたら推測せずこれで確認する。",
        "parameters": {"type": "object", "properties": {}, "required": []},
    },
    {
        "type": "function",
        "name": "web_search",
        "description": (
            "webを検索して結果（タイトル・要旨・URL）を受け取り、自分で読んで答える。"
            "最新情報・ニュース・事実確認などの軽い調べ物はこれで自己完結する（数秒）。"
            "複数ステップの深い調査や作業を伴うものだけ delegate_to_dan を使う。"
        ),
        "parameters": {
            "type": "object",
            "properties": {
                "query": {"type": "string", "description": "検索クエリ（日本語可）"},
            },
            "required": ["query"],
        },
    },
    {
        "type": "function",
        "name": "read_room_history",
        "description": (
            "このチャットルームの過去の会話履歴を読む。部屋で何が話されてきたか・"
            "直前の文脈が必要なとき、推測せずこれで自分で確認する。"
        ),
        "parameters": {
            "type": "object",
            "properties": {
                "limit": {"type": "integer", "description": "読む件数（既定30、最大50）"},
            },
            "required": [],
        },
    },
    {
        "type": "function",
        "name": "look_at_screen",
        "description": (
            "ユーザーの画面（共有されたタブ/ウィンドウ）をスクリーンショットで見る。"
            "「これ見て」の共有を受けるときに使う。初回はユーザーに共有許可ダイアログが出る。"
        ),
        "parameters": {"type": "object", "properties": {}, "required": []},
    },
    # ---- 成果物編集（対象=成果物タブで開いている成果物。開いていなければエラーが返る） ----
    {
        "type": "function",
        "name": "get_artifact_state",
        "description": "開いている成果物の編集可能な要素一覧（id・テキスト・スタイル）を取得する。編集の前に対象を確認する。",
        "parameters": {"type": "object", "properties": {}, "required": []},
    },
    {
        "type": "function",
        "name": "set_text",
        "description": "成果物の要素のテキストを書き換える（draftとして保存され、公開は別操作）。",
        "parameters": {
            "type": "object",
            "properties": {
                "id": {"type": "string", "description": "対象要素の id（get_artifact_state で確認）"},
                "text": {"type": "string", "description": "新しいテキスト"},
            },
            "required": ["id", "text"],
        },
    },
    {
        "type": "function",
        "name": "set_style",
        "description": "成果物の要素のスタイルを変更する。styles は CSSプロパティ→値（例: {\"font-size\": \"32px\", \"color\": \"#c0392b\"}）。",
        "parameters": {
            "type": "object",
            "properties": {
                "id": {"type": "string"},
                "styles": {"type": "object", "additionalProperties": {"type": "string"}},
            },
            "required": ["id", "styles"],
        },
    },
    {
        "type": "function",
        "name": "list_source_files",
        "description": "開いている成果物のソースファイル一覧を取得する。",
        "parameters": {"type": "object", "properties": {}, "required": []},
    },
    {
        "type": "function",
        "name": "read_source",
        "description": "成果物のソースファイル（page.tsx 等）を読む。構造の把握や編集の前に使う。",
        "parameters": {
            "type": "object",
            "properties": {"file": {"type": "string", "description": "例: page.tsx"}},
            "required": ["file"],
        },
    },
    {
        "type": "function",
        "name": "edit_source",
        "description": "ソースを部分編集する（完全一致の置換・1箇所）。構造変更・レイアウト変更を自分で行う。1〜2秒でプレビューに反映される。",
        "parameters": {
            "type": "object",
            "properties": {
                "file": {"type": "string"},
                "old_string": {"type": "string", "description": "ファイル内で一意になるよう前後を含める"},
                "new_string": {"type": "string"},
            },
            "required": ["file", "old_string", "new_string"],
        },
    },
    {
        "type": "function",
        "name": "write_source",
        "description": "ソースファイルを丸ごと書き換える/新規作成する。大規模な作り直し用。部分変更は edit_source を使う。",
        "parameters": {
            "type": "object",
            "properties": {"file": {"type": "string"}, "content": {"type": "string"}},
            "required": ["file", "content"],
        },
    },
    {
        "type": "function",
        "name": "generate_image",
        "description": (
            "GPT Image 2 で画像を生成する（20〜60秒）。返ってきた url を set_style の background-image や "
            "edit_source で <img> の src に自分で適用する。prompt は内容の説明文（会話の貼り付け禁止・"
            "画風や形容を勝手に足さない。デザイン判断はユーザーがする）。"
        ),
        "parameters": {
            "type": "object",
            "properties": {
                "prompt": {"type": "string"},
                "size": {"type": "string", "description": "WxH（両辺16の倍数）。省略時 1520x800"},
            },
            "required": ["prompt"],
        },
    },
    {
        "type": "function",
        "name": "look_at_page",
        "description": (
            "開いている成果物の全体を、文字が読める高解像度タイル数枚（上から順・draft反映済み）で見る（あなたの目）。"
            "編集を数回したら必ずこれで自分の目で確認してから報告する。"
        ),
        "parameters": {"type": "object", "properties": {}, "required": []},
    },
    {
        "type": "function",
        "name": "look_at_section",
        "description": "指定要素だけを原寸で見る。小さい文字の可読性や細部の確認に使う。",
        "parameters": {
            "type": "object",
            "properties": {"id": {"type": "string"}},
            "required": ["id"],
        },
    },
    {
        "type": "function",
        "name": "check_contrast",
        "description": "補助lint（任意）: 全テキスト要素のコントラスト比（WCAG）を機械計算し、読めない要素を列挙する。数値の裏取りが欲しいときに使う。",
        "parameters": {"type": "object", "properties": {}, "required": []},
    },
    {
        "type": "function",
        "name": "read_skill",
        "description": (
            "制作の作法が定義されたスキル文書を読む。name省略で一覧、指定で本文。"
            "まとまった制作・編集（LP作成、デザイン変更など）を自分でやる前に、該当スキルがあれば読んで作法に従う。"
        ),
        "parameters": {
            "type": "object",
            "properties": {"name": {"type": "string", "description": "例: build"}},
            "required": [],
        },
    },
]


class VoiceSessionRequest(BaseModel):
    chat_title: Optional[str] = None
    room_id: Optional[str] = None
    effort: str = Field(default="high", pattern="^(minimal|low|medium|high|xhigh)$")


async def _room_memory_digest(room_id: str, user_id: str) -> str:
    """接続時に注入する「この部屋のこれまで」の要約。

    一言目から部屋の文脈を持っているための起動時記憶。過去の教訓:
    生の対話をそのまま注入するとモデルが今の会話と混同する（2026-08-23 実証）ため、
    記憶であることを明示し、発話ラベル付き・短縮・上限つきのダイジェスト形式にする。
    """
    try:
        svc = ChatService()
        # 解像度が命: 110字/件では長文回答が見出しで切れ、決定事項が記憶に入らない
        # （2026-08-26 実証: 免許再発行の文脈が切れ落ちて聞き返し事故）。
        # ダンの回答は結論から書く流儀なので、400字あれば各回答の要点が入る。
        messages = await svc.get_messages(room_id, user_id, limit=25)
        if not messages:
            return ""
        lines = []
        for m in messages:
            content = (m.get("content") or "").strip()
            if content.startswith("🎙"):
                content = content[1:].strip()
            who = "みきさん" if m.get("sender_type") in ("human", "user") else "あなた"
            lines.append(f"- {who}: {content[:400]}")
        digest = "\n".join(lines)[-7000:]
        return (
            "\n\n【この部屋のこれまで（あなた自身の記憶の要約。過去の記録であり、いま話しかけられている言葉ではない）】\n"
            f"{digest}\n"
            "この続きとして会話する。新しい発話にだけ応答する。"
        )
    except Exception:
        return ""


@router.post("/session")
async def create_chat_voice_session(request: Request, body: VoiceSessionRequest):
    user = _get_user(request)
    if not settings.OPENAI_API_KEY:
        raise HTTPException(status_code=503, detail="OPENAI_API_KEY が未設定です")

    instructions = _chat_instructions(body.chat_title)
    if body.room_id:
        instructions += await _room_memory_digest(body.room_id, user.user_id)

    session = {
        "type": "realtime",
        "model": REALTIME_MODEL,
        "instructions": instructions,
        "audio": {
            "input": {
                "transcription": {"model": "gpt-realtime-whisper", "language": "ja"},
                "noise_reduction": {"type": "near_field"},
                "turn_detection": {"type": "semantic_vad", "eagerness": "low"},
            },
            "output": {"voice": "cedar"},
        },
        "tools": _CHAT_TOOLS,
        "reasoning": {"effort": body.effort},
    }
    async with httpx.AsyncClient(timeout=30.0) as client:
        resp = await client.post(
            CLIENT_SECRETS_ENDPOINT,
            headers={"Authorization": f"Bearer {settings.OPENAI_API_KEY}", "Content-Type": "application/json"},
            json={"session": session},
        )
    if resp.status_code != 200:
        detail = resp.text[:500]
        logger.error("voicelog session mint failed: HTTP %s %s", resp.status_code, detail)
        raise HTTPException(status_code=502, detail=f"セッション発行に失敗 (HTTP {resp.status_code}): {detail}")
    data = resp.json()
    return {"value": data.get("value", ""), "model": REALTIME_MODEL, "expires_at": data.get("expires_at")}


# ------------------------------------------------------- artifact editing
#
# V2: 成果物編集ツール群（scratch実験で実証済みの一式の本番移植）。
# チャットのプレビューiframeはクロスオリジン(postMessage方式)のため、
# 編集・撮影・検査はすべてサーバー側で実行し、フロントは編集後に
# プレビューの contentVersion を bump して再読込で見せる。

import asyncio
import base64
import re as _re
import subprocess
from pathlib import Path as _Path

_REPO_ROOT = _Path(__file__).resolve().parents[2]
_ARTIFACTS_ROOT = _REPO_ROOT / "frontend" / "src" / "app" / "artifacts"
_SKILLS_ROOT = _REPO_ROOT / ".claude" / "skills"
_ALLOWED_EXT = {".tsx", ".ts", ".css", ".md", ".json", ".txt"}
_CAPTURE_SCRIPT = _REPO_ROOT / "scripts" / "voice_page_capture.py"
_GEN_DIR = _REPO_ROOT / "frontend" / "public" / "artifacts" / "voice-gen"


def _raw_token(request: Request) -> str:
    token = request.cookies.get(ACCESS_TOKEN_COOKIE)
    if not token:
        auth = request.headers.get("Authorization", "")
        if auth.startswith("Bearer "):
            token = auth[7:]
    return token or ""


def _artifact_root(slug: str) -> _Path:
    if not _re.match(r"^[a-z0-9][a-z0-9-]*$", slug or ""):
        raise HTTPException(status_code=400, detail="slug が不正です")
    return _ARTIFACTS_ROOT / slug


def _resolve_file(root: _Path, file: str) -> _Path:
    if not file or ".." in file or file.startswith(("/", "\\")):
        raise HTTPException(status_code=400, detail="file パスが不正です")
    if _Path(file).suffix.lower() not in _ALLOWED_EXT:
        raise HTTPException(status_code=400, detail="この拡張子は扱えません")
    full = (root / file).resolve()
    if not str(full).startswith(str(root.resolve())):
        raise HTTPException(status_code=400, detail="成果物ディレクトリ外は扱えません")
    return full


class SourceRequest(BaseModel):
    action: str = Field(pattern="^(list|read|edit|write)$")
    slug: str
    file: Optional[str] = None
    old_string: Optional[str] = None
    new_string: Optional[str] = None
    content: Optional[str] = None


@router.post("/source")
async def voice_source(request: Request, body: SourceRequest):
    _get_user(request)
    root = _artifact_root(body.slug)

    if body.action == "list":
        files = []
        if root.exists():
            for p in sorted(root.rglob("*")):
                if p.is_file():
                    files.append({"file": str(p.relative_to(root)).replace("\\", "/"), "bytes": p.stat().st_size})
        return {"files": files[:100]}

    full = _resolve_file(root, body.file or "")
    if body.action == "read":
        try:
            content = full.read_text(encoding="utf-8")
        except FileNotFoundError:
            raise HTTPException(status_code=404, detail="ファイルがありません")
        return {"file": body.file, "bytes": len(content), "content": content[:40_000], "truncated": len(content) > 40_000}

    if body.action == "edit":
        old = body.old_string or ""
        if not old:
            raise HTTPException(status_code=400, detail="old_string が空です")
        try:
            content = full.read_text(encoding="utf-8")
        except FileNotFoundError:
            raise HTTPException(status_code=404, detail="ファイルがありません")
        count = content.count(old)
        if count == 0:
            raise HTTPException(status_code=409, detail="old_string が見つかりません（完全一致が必要）")
        if count > 1:
            raise HTTPException(status_code=409, detail=f"old_string が{count}箇所にマッチします。前後を含めて一意にしてください")
        full.write_text(content.replace(old, body.new_string or "", 1), encoding="utf-8")
        return {"ok": True, "file": body.file, "note": "1〜2秒でプレビューに反映されます"}

    # write
    content = body.content or ""
    if not content:
        raise HTTPException(status_code=400, detail="content が空です")
    if len(content) > 400_000:
        raise HTTPException(status_code=413, detail="content が大きすぎます")
    full.parent.mkdir(parents=True, exist_ok=True)
    full.write_text(content, encoding="utf-8")
    return {"ok": True, "file": body.file, "bytes": len(content)}


def _kebab(styles: dict) -> dict:
    return { _re.sub(r"[A-Z]", lambda m: "-" + m.group(0).lower(), k): v for k, v in (styles or {}).items() }


class EditRequest(BaseModel):
    slug: str
    element_id: str = Field(min_length=1, max_length=120)
    text: Optional[str] = None
    styles: Optional[dict] = None


@router.post("/edit")
async def voice_edit(request: Request, body: EditRequest):
    """set_text / set_style（draft=inspector_overrides レーン。Inspector手編集と同じ保存先）。"""
    user = _get_user(request)
    from app.services.inspector_overrides_service import InspectorOverridesService

    svc = InspectorOverridesService()
    key = f"@{body.element_id}"
    styles = _kebab(body.styles) if body.styles else None
    attrs = None
    if body.text is not None:
        # 既存 model_v2 を保全して text だけ差し替える（過去のスタイル編集を壊さない）
        try:
            row = (
                svc.supabase.table("inspector_overrides").select("attrs")
                .eq("artifact_slug", body.slug).eq("element_key", key).limit(1).execute()
            )
            model = {"v": 2, "text": None, "blockStyle": {}, "spans": [], "attrs": {}}
            if row.data and isinstance(row.data[0].get("attrs"), dict):
                import json as _json

                raw = row.data[0]["attrs"].get("model_v2")
                if isinstance(raw, str):
                    model = {**model, **_json.loads(raw)}
        except Exception:
            model = {"v": 2, "text": None, "blockStyle": {}, "spans": [], "attrs": {}}
        model["text"] = body.text
        import json as _json

        attrs = {"model_v2": _json.dumps(model, ensure_ascii=False)}
    result = await svc.upsert(
        artifact_slug=body.slug, element_key=key, styles=styles, attrs=attrs,
        user_id=user.user_id, project_id=None, replace_attrs=False,
    )
    return {"ok": True, "element_key": key, "id": str(result.get("id", ""))}


class CaptureRequest(BaseModel):
    slug: str
    mode: str = Field(pattern="^(tiles|section|state|contrast)$")
    element_id: Optional[str] = None


@router.post("/capture")
async def voice_capture(request: Request, body: CaptureRequest):
    _get_user(request)
    token = _raw_token(request)
    _artifact_root(body.slug)  # slug validation
    args = ["python", str(_CAPTURE_SCRIPT), "--slug", body.slug, "--mode", body.mode]
    if token:
        args += ["--token", token]
    if body.element_id:
        if not _re.match(r"^[a-zA-Z0-9_-]+$", body.element_id):
            raise HTTPException(status_code=400, detail="element_id が不正です")
        args += ["--element-id", body.element_id]

    def _run():
        return subprocess.run(args, capture_output=True, text=True, timeout=60, encoding="utf-8", errors="replace")

    proc = await asyncio.to_thread(_run)
    if proc.returncode != 0:
        raise HTTPException(status_code=502, detail=f"capture失敗: {(proc.stderr or '')[:300]}")
    try:
        data = __import__("json").loads(proc.stdout.strip().splitlines()[-1])
    except Exception:
        raise HTTPException(status_code=502, detail=f"capture出力の解析に失敗: {proc.stdout[:200]}")

    def _b64(path: str) -> str:
        return "data:image/jpeg;base64," + base64.b64encode(_Path(path).read_bytes()).decode()

    if "tiles" in data:
        return {"tiles": [_b64(t) for t in data["tiles"]], "count": len(data["tiles"])}
    if "image" in data:
        return {"image": _b64(data["image"])}
    return data  # state / contrast はそのまま


class GenerateImageRequest(BaseModel):
    prompt: str = Field(min_length=1, max_length=2000)
    size: Optional[str] = None


@router.post("/generate-image")
async def voice_generate_image(request: Request, body: GenerateImageRequest):
    _get_user(request)
    if not settings.OPENAI_API_KEY:
        raise HTTPException(status_code=503, detail="OPENAI_API_KEY が未設定です")
    size = body.size or "1520x800"
    m = _re.match(r"^(\d+)x(\d+)$", size)
    if not m or int(m.group(1)) % 16 or int(m.group(2)) % 16:
        size = "1520x800"
    async with httpx.AsyncClient(timeout=180.0) as client:
        resp = await client.post(
            "https://api.openai.com/v1/images/generations",
            headers={"Authorization": f"Bearer {settings.OPENAI_API_KEY}"},
            json={"model": "gpt-image-2", "prompt": body.prompt, "size": size, "quality": "low"},
        )
    if resp.status_code != 200:
        raise HTTPException(status_code=502, detail=f"画像生成に失敗 (HTTP {resp.status_code})")
    b64 = (resp.json().get("data") or [{}])[0].get("b64_json")
    if not b64:
        raise HTTPException(status_code=502, detail="画像データが空でした")
    _GEN_DIR.mkdir(parents=True, exist_ok=True)
    name = f"gen-{int(__import__('time').time() * 1000)}.png"
    (_GEN_DIR / name).write_bytes(base64.b64decode(b64))
    return {"url": f"/artifacts/voice-gen/{name}", "size": size}


class SkillRequest(BaseModel):
    name: Optional[str] = None


@router.post("/skill")
async def voice_read_skill(request: Request, body: SkillRequest):
    """スキルの一覧/本文をエージェントに読ませる（あてずっぽう作業の防止）。"""
    _get_user(request)
    if not body.name:
        skills = []
        for d in sorted(_SKILLS_ROOT.iterdir()):
            md = d / "SKILL.md"
            if md.exists():
                head = md.read_text(encoding="utf-8", errors="replace")[:400]
                skills.append({"name": d.name, "summary": head.replace("\n", " ")[:180]})
        return {"skills": skills}
    if not _re.match(r"^[a-z0-9_-]+$", body.name):
        raise HTTPException(status_code=400, detail="スキル名が不正です")
    md = _SKILLS_ROOT / body.name / "SKILL.md"
    if not md.exists():
        raise HTTPException(status_code=404, detail=f"スキル {body.name} がありません")
    content = md.read_text(encoding="utf-8", errors="replace")
    return {"name": body.name, "content": content[:18_000], "truncated": len(content) > 18_000}


# ---------------------------------------------------------------- mobile support

@router.post("/config")
async def voice_config(request: Request):
    """モバイル用の接続設定。委譲WS(コア)はVercelプロキシを通らないため、
    コアのトンネルURLを直接返してアプリから wss 直結させる。"""
    _get_user(request)
    delegate_ws = ""
    try:
        core_url = (_REPO_ROOT / ".tunnel_core_url").read_text(encoding="utf-8").strip()
        if core_url.startswith("https://"):
            delegate_ws = "wss://" + core_url[len("https://"):].rstrip("/") + "/ws/realtime-delegate"
    except Exception:
        pass
    return {"delegate_ws": delegate_ws}


class RoomArtifactRequest(BaseModel):
    room_id: str


@router.post("/room-artifact")
async def voice_room_artifact(request: Request, body: RoomArtifactRequest):
    """部屋に紐づく最新の成果物slugを返す（モバイルにはプレビュー面が無いため、
    編集ツールの対象slugをサーバー側で解決する）。"""
    _get_user(request)
    from app.services.inspector_overrides_service import InspectorOverridesService

    sb = InspectorOverridesService().supabase
    rows = (
        sb.table("chat_artifact").select("slug,label,updated_at")
        .eq("room_id", body.room_id).order("updated_at", desc=True).limit(1).execute()
    )
    if not rows.data:
        return {"slug": None}
    return {"slug": rows.data[0]["slug"], "label": rows.data[0].get("label")}


# ---------------------------------------------------------------- search

class SearchRequest(BaseModel):
    query: str = Field(min_length=1, max_length=400)


@router.post("/search")
async def voice_web_search(request: Request, body: SearchRequest):
    """音声エージェントの軽量検索（脳1つ方式）。

    Tavily の生の検索結果（タイトル・要旨・URL）を返し、読解と回答は
    音声モデル自身が行う。第2のLLMを挟まない＝ChatGPT Live と同じ役割分担の軽量版。
    """
    _get_user(request)
    import os

    key = os.environ.get("TAVILY_API_KEY", "") or getattr(settings, "TAVILY_API_KEY", "")
    if not key:
        from pathlib import Path

        env_path = Path(__file__).resolve().parents[2] / ".env"
        try:
            key = next(
                (l.split("=", 1)[1].strip() for l in env_path.read_text(encoding="utf-8").splitlines()
                 if l.startswith("TAVILY_API_KEY=")),
                "",
            )
        except Exception:
            key = ""
    if not key:
        raise HTTPException(status_code=503, detail="検索APIキーが未設定です")

    async with httpx.AsyncClient(timeout=20.0) as client:
        resp = await client.post(
            "https://api.tavily.com/search",
            json={"api_key": key, "query": body.query, "max_results": 5, "include_answer": False},
        )
    if resp.status_code != 200:
        raise HTTPException(status_code=502, detail=f"検索に失敗 (HTTP {resp.status_code})")
    data = resp.json()
    results = [
        {
            "title": r.get("title", "")[:120],
            "snippet": (r.get("content") or "")[:400],
            "url": r.get("url", ""),
        }
        for r in (data.get("results") or [])[:5]
    ]
    return {"query": body.query, "results": results}


# ------------------------------------------------------------- transcript

class TranscriptRequest(BaseModel):
    role: str = Field(pattern="^(user|assistant)$")
    content: str = Field(min_length=1, max_length=8000)


@router.post("/{room_id}")
async def add_voice_transcript(room_id: str, request: Request, body: TranscriptRequest):
    """音声会話の1発話を部屋の履歴に保存する（🎙マーク付き）。

    sender_type は human/ai を使い分けるので、チャットUIでは通常の
    ユーザー/ダンの吹き出しとして時系列に並ぶ。ダン（CLI）は後のターンで
    この履歴を読めるため、音声↔テキストの記憶が部屋単位で繋がる。
    """
    user = _get_user(request)
    sender_type = "human" if body.role == "user" else "ai"
    content = f"🎙 {body.content.strip()}"
    svc = ChatService()
    try:
        message = await svc.send_message(room_id, user.user_id, content, sender_type=sender_type)
    except ValueError as e:
        raise HTTPException(status_code=403, detail=str(e))
    return {"ok": True, "id": message.get("id")}
