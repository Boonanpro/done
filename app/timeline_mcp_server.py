"""Timeline MCP server — the production agent's ONLY hands and eyes.

Launched per job by the agent runner with context in env:
  DAN_ROOM_ID / DAN_DRAFT_ID / DAN_JOB_ID
Every mutation goes through app.services.timeline_commands (validated, clamped);
Validated operations can publish live checkpoints with compare-and-swap;
the orchestrator records the final result after the session ends. Frames come back as inline images
so the model literally sees the composited draft.
"""

import asyncio
import threading
import base64
import json
import logging
import os
import re
import shutil
import subprocess
import sys
import time
import urllib.request
import uuid
from pathlib import Path

PROJECT_ROOT = os.path.dirname(os.path.abspath(__file__ + "/.."))
sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))
sys.path.insert(0, str(Path(__file__).resolve().parents[1]))

from mcp.server import Server  # noqa: E402
from mcp.server.stdio import stdio_server  # noqa: E402
import mcp.types as types  # noqa: E402

from app.services import timeline_draft as td  # noqa: E402
from app.services import timeline_commands as tc  # noqa: E402
from app.services import timeline_context as tcx  # noqa: E402

logger = logging.getLogger(__name__)

ROOM_ID = os.environ.get("DAN_ROOM_ID", "")
DRAFT_ID = os.environ.get("DAN_DRAFT_ID", "")
JOB_ID = os.environ.get("DAN_JOB_ID", "")
CONTENT_ID = os.environ.get("DAN_CONTENT_ID", "")
MAX_TOOL_CALLS = int(os.environ.get("DAN_MAX_TOOL_CALLS", "0"))
MAX_GENERATIONS = int(os.environ.get("DAN_MAX_GENERATIONS", "0"))

_VISUAL_LANE = {'anyOf': [{'type': 'integer', 'minimum': 0}, {'type': 'string', 'enum': ['front']}],
                'description': '映像レーン番号、またはfrontで実行時点の最前面に新規レーン。リンク音声などでレーン数が変わってもfrontなら番号の再計算は不要。'}

_calls = 0
_generations = 0
_draft_lock = threading.RLock()
_BACKGROUND_TOOLS = {'generate_speech','generate_image','watch_video','watch_render','measure_speech','render_frame','probe_audio','resolve_reference','analyze_reference','search_web_references','render_motion_project','present_references','read_presentations','revise_presentation'}

def _run_tool_thread(name,args):
    if name in _BACKGROUND_TOOLS:
        return asyncio.run(_dispatch(name,args))
    with _draft_lock:
        if td.refresh_checkpoint(ROOM_ID, DRAFT_ID):
            return _ok({'ok': False, 'human_edit_received': True,
                'note': 'ユーザーの手編集を取り込みました。最新のtimeline_outlineを読んでから必要な編集を続けてください。今回の操作は未実行です。'})
        result = asyncio.run(_dispatch(name,args))
        try:
            payload = json.loads(result[0].text)
        except (ValueError, AttributeError, IndexError):
            return result
        if not isinstance(payload, dict):
            return result
        if payload.get('ok') is not False:
            published = td.publish_checkpoint(ROOM_ID, DRAFT_ID)
            if published.get('published'):
                payload['timeline_updated'] = True
                result = _ok(payload)
            elif not published.get('ok'):
                return _ok({**payload, 'ok': False, 'saved_in_draft': True,
                    'conflict': published.get('conflict', False),
                    'error': ' / '.join(published.get('problems', []))})
        return result

def _track_asset(draft,aid):
    # A generation may finish after unrelated edits. Merge into the latest snapshot.
    with _draft_lock:
        current=td.load_draft(draft['room_id'],draft['draft_id'])
        td.track_generated_asset(current,aid)


app = Server("timeline")


def _room_dir() -> Path:
    return td._room_dir(ROOM_ID)


def _assets() -> dict:
    p = _room_dir() / "assets.json"
    if not p.exists():
        return {}
    data = json.loads(p.read_text(encoding="utf-8"))
    return {str(a.get("id")): a for a in data if isinstance(a, dict)}


def _load():
    return td.load_draft(ROOM_ID, DRAFT_ID)


def _frame_b64(path: Path) -> str:
    """Base64 PNG for the model's eyes, downscaled to half resolution — text stays
    readable at 540x960 while image tokens (and per-turn latency) drop ~4x."""
    try:
        from io import BytesIO

        from PIL import Image

        im = Image.open(path)
        if im.width > 600:
            im = im.resize((im.width // 2, im.height // 2), Image.LANCZOS)
            buf = BytesIO()
            im.save(buf, format="PNG")
            return base64.b64encode(buf.getvalue()).decode()
    except Exception:
        pass
    return base64.b64encode(path.read_bytes()).decode()


def _tool(name, description, props, required=None):
    return types.Tool(name=name, description=description,
                      inputSchema={"type": "object", "properties": props, "required": required or []})


_NUM = {"type": "number"}
_STR = {"type": "string"}


_CAPTION_STYLE = {'type':'object','additionalProperties':False,'properties':{
    'font':{'type':'string'},'fontSize':{'type':'number','description':'相対倍率。1が標準、1.25で25%大きい。'},
    'color':{'type':'string'},'outlineColor':{'type':'string'},'outlineWidth':{'type':'number'},
    'maxWidth':{'type':'number','description':'画面幅に対する比率。'},
    'textAlign':{'type':'string','enum':['left','center','right']},
    'x':{'type':'number','description':'中央からの横移動量。0が中央、正は右。画面幅に対する比率。'},
    'y':{'type':'number','description':'画面下端から上方向への位置。既定0.08が通常の下中央。0.5は中央付近、0.85は上部。画像の左上基準座標とは異なる。'}
}}

@app.list_tools()
async def list_tools() -> list[types.Tool]:
    return tool_definitions()


def tool_definitions() -> list[types.Tool]:
    return [
        _tool('apply_edits','複数のタイムライン操作をまとめて作業用下書きへ適用する。1操作でも失敗したら全操作を戻す。素材生成や外部操作は含めない。各操作は通常ツールと同じ引数。引数の値に {"$result":0,"path":"clip_id"} を置くと、このバッチの0番目の結果を参照できる（配列はcuts.0.clip_id等）。先行操作だけ参照可。',{'operations':{'type':'array','maxItems':100,'items':{'type':'object','properties':{'name':_STR,'args':{'type':'object'}},'required':['name','args']}}},['operations']),
        _tool('animate_clip','文字・映像・図形を一つのクリップのまま滑らかに動かす。posesは相対秒tとキャンバス比x,y,w,h。文字はデザイン全体への移動・拡大（標準0,0,1,1）、図形は領域そのもの。既存の動きを置換する。',{'clip_id':_STR,'poses':{'type':'array','items':{'type':'object'}},'easing':{'type':'string','enum':['linear','cubic_out','cubic_in_out']}},['clip_id','poses']),
        _tool('production_methods','制作方法の候補・必要素材・下書き方法・検証状態を必要時に読む。一覧外の表現も調査して作れる。',{'method_id':_STR}),
        _tool('prepare_motion_project','引数なしで、テイストを固定しない白紙の映像プロジェクトを準備する。既存映像の再編集はasset_idまたはproject_dirで別版にコピー。光学文字の演出を再利用したい場合だけtemplate=true。返されたHTMLの構図・尺・演出を通常のファイル操作で編集する。',{'asset_id':_STR,'project_dir':_STR,'template':{'type':'boolean'}}),
        _tool('write_motion_file','準備した作業用映像プロジェクトにHTML/CSS/JS等のテキストをUTF-8でそのまま保存する。シェルの引用符や日本語の文字化けを避けて制作できる。pathはプロジェクト内の相対パス。書き出し・配置は別操作。',{'project_dir':_STR,'path':_STR,'content':_STR},['project_dir','path','content']),
        _tool('render_motion_project','HTML/GSAPプロジェクトを検査・書き出しし、編集元の保存版付きで素材登録する。配置はadd_clip、部分差替えはset_clip_props(asset_id)で明示する。映像内の文字等は保存した元コードから再編集可能。',{'project_dir':_STR,'name':_STR},['project_dir']),
        _tool('search_web_references','Web全体から参考作品・制作資料を出典付きで検索。検索結果から映像を推測しない。',{'queries':{'type':'array','items':_STR}},['queries']),
        _tool('resolve_reference', '参考URL・部屋の素材IDを再生可能なitemと保存IDへ解決。X動画対応。分析前に提示できる。', {'source':_STR}, ['source']),
        _tool('read_references','作品に保存した参考素材と分析を読む。',{'reference_id':_STR}),
        _tool('analyze_reference','保存した参考をGeminiで映像・音声分析。動画はAgentic。同じ質問の結果は再利用。長い分析は提示や他作業と並行する。',{'reference_id':_STR,'question':_STR},['reference_id']),
        _tool('revise_presentation', __import__('app.services.editor_presentation',fromlist=['REVISE_DESCRIPTION']).REVISE_DESCRIPTION, __import__('app.services.editor_presentation',fromlist=['REVISE_PROPERTIES']).REVISE_PROPERTIES, ['item_id','changes']),
        _tool('read_presentations','提示した画像・動画・文字・3D等の履歴を読む。beforeで以前の提示を取得。',{'before':{'type':'number'},'limit':{'type':'integer'}}),
        _tool('present_references', __import__('app.services.editor_presentation',fromlist=['DESCRIPTION']).DESCRIPTION, {'items':{'type':'array','items':__import__('app.services.editor_presentation',fromlist=['ITEM_SCHEMA']).ITEM_SCHEMA}}, ['items']),
        _tool('ask_user','作業に必要な質問をエディターの音声・チャットへ届け、返答を待つ。回答後は同じ作業を続ける。',{'question':_STR},['question']),
        _tool('editor_help','エディターの保存・座標・提案仕様を読む。',{'topic':_STR},[]),
        _tool('report_result','下書きの作業・検品結果を記録する。achievedは依頼達成、needs_userは本人の操作待ち、blockedは進められない状態。この後に応答を終えるとアプリが下書きを本番へ検証・保存し、会話へ保存結果を通知する。保存前の本番画面を待つ必要はない。',{'outcome':{'type':'string','enum':['achieved','needs_user','blocked']},'summary':_STR},['outcome','summary']),
        _tool('read_project_chat','必要なときだけ、この部屋の通常チャットの履歴を読む。',{'limit':_NUM}),
        _tool('conversation_history','この作品のユーザーとダン両方の発言を役割付きで読む。短い「それで」等が何への回答か確認できる。assistantの提案をuserの指定と混同しない。beforeを渡すと以前の会話を読める。通常チャットは混入しない。',{'limit':_NUM,'before':_NUM}),
        _tool('check_skill', '制作スキルを読む。name省略で利用可能なスキル一覧。', {'name': _STR}),
        _tool("timeline_outline", "タイムライン全体の構造（レーン/クリップ/時刻/種類）を読む。作業前に必ず一度読むこと。", {}),
        _tool("list_assets", "部屋のアセット一覧（asset_id/ファイル名/種類/長さ）。配置ツールに渡すasset_idはここで確認する。", {}),
        _tool("timeline_transcript", "動画の発話内容（文字起こし）をタイムライン時刻つきで読む。内容理解はこれを根拠にする。",
              {"t0": _NUM, "t1": _NUM}),
        _tool('probe_audio', 'タイムライン音声をネイティブ再生経路で短く測定する。各対象クリップ冒頭最大0.5秒の復号・信号の有無を確認。全編の試聴や音質・同期の合否判定ではない。書き出し不要。', {'t0': _NUM, 't1': _NUM}, ['t0', 't1']),
        _tool("render_frame", "指定タイムライン時刻の合成後フレーム（カット/テロップ/ぼかし/画像すべて反映）を画像として見る。見た目の変更確認に使う。"
              "1回の呼び出しに約10秒かかるため、複数時刻を見るときは必ず ts で一括指定すること（1回分強の時間でまとめて返る）。",
              {"t": _NUM, "ts": {"type": "array", "items": _NUM, "maxItems": 8,
                                 "description": "複数時刻を一括レンダ（推奨）。tより優先"}}),
        _tool("append_clip", "ベースレーン末尾（またはat秒）に映像/画像クリップを追加。映像は音声も自動リンク。",
              {"asset_id": _STR, "source_start": _NUM, "duration": _NUM, "at": _NUM},
              ["asset_id", "duration"]),
        _tool("insert_clip", "ベースレーンのat秒に挿入。mode=ripple(以降を後ろへずらす)|overwrite(空きが必要)。",
              {"asset_id": _STR, "source_start": _NUM, "duration": _NUM, "at": _NUM, "mode": _STR},
              ["asset_id", "duration", "at"]),
        _tool("remove_clip", "クリップ削除（linked=trueで映像とリンク音声を一緒に）。",
              {"clip_id": _STR, "linked": {"type": "boolean"}}, ["clip_id"]),
        _tool("trim_clip", "クリップの端(left|right)をnew_time秒へ。A/Vリンクは同期して動く。",
              {"clip_id": _STR, "edge": _STR, "new_time": _NUM}, ["clip_id", "edge", "new_time"]),
        _tool("move_clip", "クリップ（とリンク相手）をnew_start秒へ移動。移動先が塞がっていれば失敗する。",
              {"clip_id": _STR, "new_start": _NUM}, ["clip_id", "new_start"]),
        _tool("add_overlay", "PiP映像または画像（ロゴ等）を正規化座標(x,y,width,height 0-1)でオーバーレイ。画像はアスペクト維持で枠内に収まる。",
              {"asset_id": _STR, "timeline_start": _NUM, "timeline_end": _NUM,
               "x": _NUM, "y": _NUM, "width": _NUM, "height": _NUM, "source_start": _NUM},
              ["asset_id", "timeline_start", "timeline_end", "x", "y", "width", "height"]),
        _tool("add_caption", "テロップ追加。styleは省略可。fontSizeは相対倍率(1=約64px基準)、color/outlineColorは色文字列、outlineWidthは相対幅、xは中央からの横移動(既定0)、yは下端から上への位置(既定0.08)。maxWidthは画面幅の比率。",
              {"text": _STR, "timeline_start": _NUM, "timeline_end": _NUM, "style": _CAPTION_STYLE, "lane": _VISUAL_LANE},
              ["text", "timeline_start", "timeline_end"]),
        _tool("insert_freeze", "既存クリップの1フレームを静止画クリップとしてtimeline_startからduration秒間挿入。",
              {"source_clip_id": _STR, "at_source_time": _NUM, "timeline_start": _NUM, "duration": _NUM},
              ["source_clip_id", "timeline_start", "duration"]),
        _tool("set_clip", "テロップの本文やスタイルを変更。",
              {"clip_id": _STR, "text": _STR, "style": _CAPTION_STYLE}, ["clip_id"]),
        _tool("measure_speech", "実際の再生音声から単語とタイムライン時刻を計測する。字幕に合わせて推測せず台詞の境界を確かめる。",{'start':_NUM,'end':_NUM},['start','end']),
        _tool("match_source_audio", "編集済み素材と別の収録素材で同じ発話を探す。reference側の時刻に対応するcandidate側の実測時刻と相関を返す。ずれが変化する場合は区間を細かく調べる。映像の確認も必要。",{'reference_asset_id':_STR,'candidate_asset_id':_STR,'times':{'type':'array','items':_NUM},'window':_NUM},['reference_asset_id','candidate_asset_id','times']),
        _tool("generate_image", "画像を生成して部屋のアセットとして登録し asset_id を返す。既存テイストはreference_asset_idsに静止画素材IDを指定して参照できる。model省略はgpt_image_2。aspect_ratio省略は作品の比率。",
              {"prompt": _STR, "aspect_ratio": _STR, "model": _STR,
               "reference_asset_ids":{"type":"array","items":_STR}}, ["prompt"]),
        _tool("generate_video", "許可済みの制作予算で動画を生成し、素材として登録する。provider省略はGoogle API直結でHiggsfieldクレジット不使用。Google modelはgemini-omni-1.1-flash。reference_mode=styleは参考のテイストから別内容を制作（参照動画3秒まで）、editは元動画の修正（10秒まで）。durationは希望尺で実際の尺は結果を読む。Higgsfieldは明示指定した場合のみ。結果は配置されないのでadd_clip等でタイムラインに置く。既存成果があればimport_mediaで再利用する。",
              {"prompt": _STR, "aspect_ratio": _STR, "duration": _NUM, "model": _STR,
               "provider": {"type":"string","enum":["google","higgsfield"]},
               "reference_mode":{"type":"string","enum":["style","edit"]},
               "reference_path": _STR, "resolution": _STR}, ["prompt"]),
        _tool("import_image", "実在の画像を部屋の素材として取り込み asset_id を返す。url にはWeb上の画像URL"
              "（WebSearch/WebFetchで見つけた本物のロゴ等）またはローカルファイルパスを指定。生成ではなく本物が必要な時はこちらを使う。",
              {"url": _STR, "name": _STR}, ["url"]),
        _tool("import_media", "Danが検索・生成・Bash処理などで得たローカル動画または音声を、この部屋の素材として取り込む。返るasset_idをappend_clipまたはadd_audioへ渡す。",
              {"path": _STR, "name": _STR}, ["path"]),
        _tool("add_audio", "登録済みの任意音声を音声レーンへ置く。BGM、効果音、ナレーションは同じ操作で扱う。",
              {"asset_id": _STR, "source_start": _NUM, "duration": _NUM, "at": _NUM,
               "volume": _NUM, "role": _STR}, ["asset_id", "duration"]),
        _tool("export_timeline", "現在のドラフトを最終動画として書き出し、通常Danが投稿・共有などに使える成果物アセットを返す。タイムラインを変更しない。", {}),
        _tool("validate_draft", "ドラフト全体を検証して問題リストを返す。作業の締めに必ず実行し、空になるまで直すこと。", {}),
        _tool("watch_video", "指定範囲の映像を『動画として』視聴する（動き・テンポ・話し方・音声込み。静止画のrender_frameでは分からないもの用）。"
              "questionに知りたいことを書くと視聴結果を答える。1回1〜2分かかるので範囲は要点に絞る（最大120秒）。",
              {"t0": _NUM, "t1": _NUM, "question": _STR}, ["t0", "t1"]),
        # ---- layers: region effects, generic clip edits, layering, speech, captions ----
        _tool("editor_state", "ユーザーが開いているエディタの『今』（開いているコンテンツ・再生位置・選択中クリップ）。"
              "『ここ』『このクリップ』『いま見ているところ』はこれで解決する。作業開始時に必ず一度読む。", {}),
        _tool("clips_at", "指定時刻に存在する全クリップ（全レーン、奥→手前）。『◯秒のところの字幕/枠/ぼかし』を特定する。",
              {"t": _NUM}, ["t"]),
        _tool("add_region", "領域効果クリップを映像レーンに置く: style=gaussian/soft(ぼかし) mosaic(モザイク) "
              "frame(矩形の枠線＝黄色枠などの強調) marker(マーカー塗り) spotlight(周囲を暗く) solid(塗り潰し) zoom。"
              "x,y,width,height は画面比の正規化座標(0-1、左上原点)。効果は自分より下のレーン全体に効くので、"
              "対象の絵より上のレーンに置かれる（自動）。動く対象は keys=[{t,x,y,w,h}](クリップ先頭からの秒)で追従。"
              "枠は color='#f5b800' opacity=1 のように色指定。ぼかしの強さは strength(2-64)。",
              {"timeline_start": _NUM, "timeline_end": _NUM, "x": _NUM, "y": _NUM, "width": _NUM, "height": _NUM,
               "style": _STR, "strength": _NUM, "color": _STR, "opacity": _NUM, "rotation": _NUM,
               "keys": {"type": "array", "items": {"type": "object"}}, "lane": _VISUAL_LANE},
              ["timeline_start", "timeline_end", "x", "y", "width", "height"]),
        _tool("set_region", "既存の領域効果（ぼかし/枠など）の矩形・スタイル・色・強さ・キーフレームを変更。keysは全置換、clear_keysで追従を解除。",
              {"clip_id": _STR, "x": _NUM, "y": _NUM, "width": _NUM, "height": _NUM, "style": _STR,
               "strength": _NUM, "color": _STR, "opacity": _NUM, "rotation": _NUM,
               "keys": {"type": "array", "items": {"type": "object"}}, "clear_keys": {"type": "boolean"}},
              ["clip_id"]),
        _tool("set_clip_props", "映像/画像/音声クリップの属性を変更: position{x,y,width,height}(表示枠) fit(cover|contain|stretch) "
              "crop{left,top,right,bottom}(表示枠を削る) transform_keys[{t,x,y,w,h}](寄り/パン) opacity volume muted speed(0.25-4) "
              "video_enabled asset_id(+source_start: 絵だけ差し替え、尺は不変) source_start(素材の使う位置をずらす) "
              "grade{ev,contrast,sat,temp,tint}は全置換。evは露出段数(0=無補正)、contrast/satは倍率(1=無補正、sat=0は白黒)、"
              "temp/tintは0が無補正。既存の他の補正を保つ場合は現在値も含める。grade=nullで補正解除。",
              {"clip_id": _STR, "props": {"type": "object", "properties": {
                  "position": {"type":"object"}, "fit": {"type":"string","enum":["cover","contain","stretch"]},
                  "crop": {"type":"object"}, "opacity": _NUM, "volume": _NUM, "muted": {"type":"boolean"},
                  "speed": _NUM, "source_start": _NUM, "asset_id": _STR, "role": _STR, "keep_duration": {"type":"boolean"},
                  "video_enabled": {"type":"boolean"}, "transform_keys": {"type":["array","null"],"items":{"type":"object"}},
                  "text": _STR, "style": {"type":"object"},
                  "grade": {"type":["object","null"],"properties":{k:_NUM for k in ['ev','contrast','sat','temp','tint']},"additionalProperties":False}
              },"additionalProperties":False}}, ["clip_id", "props"]),
        _tool("split_clip", "クリップ（とリンク相手）を at 秒で2つに分割。見た目は変わらない（素材位置・キーフレームも引き継ぐ）。"
              "atは秒数または秒数配列。複数の切れ目は一度に渡せる。返却の各clip_idを次の編集に使う。", {"clip_id": _STR, "at": {"anyOf":[_NUM,{"type":"array","items":_NUM,"minItems":1}]}}, ["clip_id", "at"]),
        _tool("add_clip", "映像/画像クリップを任意の映像レーンに置く汎用配置（ナレーションの上に被せるBロール、全画面の静止画、PiP）。"
              "lane省略=手前の空いているレーン（無ければ新規映像レーン）。映像は既定で音声無し(with_audio=trueでリンク音声も置く)。"
              "speedで早回し。position で表示枠。fit=contain既定。",
              {"asset_id": _STR, "timeline_start": _NUM, "duration": _NUM, "source_start": _NUM,
               "lane": _VISUAL_LANE, "fit": _STR, "position": {"type": "object"}, "speed": _NUM,
               "with_audio": {"type": "boolean"}, "volume": _NUM},
              ["asset_id", "timeline_start", "duration"]),
        _tool("generate_speech", "Qwen3-TTSはユーザー指定により停止中。このツールは新しい音声を生成しない。既存の音声素材を利用するか、許可された別の音声生成手段を選ぶ。"
              "wavを部屋の素材として登録し asset_id と長さを返す→add_audioで置く。textは表示用の正しい表記で書き、"
              "読み間違いそうな語は readings={'車検証':'しゃけんしょう'} で読みを指定（既定辞書あり）。voice省略=owner。",
              {"text": _STR, "voice": _STR, "readings": {"type": "object"}, "name": _STR}, ["text"]),
        _tool("auto_captions", "全文字幕: segments=[{t0,t1,text}] に『その範囲で話している正確な台本』を渡すと、"
              "発話の単語時刻に合わせて24文字以下に分割した字幕クリップを置く（範囲内の既存字幕は置き換え）。"
              "台本はテロップに出したい表記そのもの。合成音声や既存の計測に単語時刻があればwords=[開始秒,終了秒,文字]の配列で渡すと再文字起こしなしで配置する。時刻はタイムライン基準。文節で区切る。words省略時は音声を文字起こしする。",
              {"segments": {"type": "array", "items": {"type": "object"}}, "style": {"type": "object"},
               "replace": {"type": "boolean"}, "words": {"type":"array","items":{"type":"array"}}}, ["segments"]),
        _tool("watch_render", "指定範囲を『合成後の完成映像として』書き出してGeminiに視聴させる（ぼかし・枠・字幕・重ね全部込み、音声込み）。"
              "watch_videoは素材だけを見るが、こちらは視聴者が見るものそのもの。仕上がり検品に使う。1分の範囲で約1〜2分。",
              {"t0": _NUM, "t1": _NUM, "question": _STR}, ["t0", "t1"]),
    ]


from app.services.timeline_operations import resolve_results as _resolve_batch_results


from app.services.timeline_operations import split_at_times as _split_at_times


def _ok(payload) -> list[types.TextContent]:
    return [types.TextContent(type="text", text=json.dumps(payload, ensure_ascii=False))]


@app.call_tool()
async def call_tool(name: str, arguments: dict) -> list:
    global _calls, _generations
    from app.services import editor_job_updates
    updates=editor_job_updates.receive(ROOM_ID,JOB_ID) if JOB_ID else []
    scope_updates=editor_job_updates.scope_updates(ROOM_ID,JOB_ID) if JOB_ID else []
    if scope_updates:
        with _draft_lock:
            draft=_load()
            if draft.get('edit_scope') is not None:
                from app.services.timeline_scope import make_scope
                ids=list(draft['edit_scope']['clip_ids'])+[i for u in scope_updates for i in u.get('clip_ids',[])]
                draft['edit_scope']=make_scope(draft['base_sequence'],ids)
                td.save_draft(draft)
            editor_job_updates.mark_scope_applied(ROOM_ID,JOB_ID,scope_updates)
    if updates:
        return _ok({'ok':False,'instruction_updated':True,'updates':updates,
                    'note':'ユーザーから進行中の仕事への訂正です。今回のツールはまだ実行していません。最新の条件に計画を更新してから必要な操作を呼び直してください。指定サービスを勝手に代替しないでください。'})
    _calls += 1
    if MAX_TOOL_CALLS > 0 and _calls > MAX_TOOL_CALLS and name not in {'validate_draft','report_result','timeline_outline','editor_state','conversation_history','watch_render','render_frame','probe_audio'}:
        return _ok({"ok": False, "error": f"tool call limit ({MAX_TOOL_CALLS}) reached — validate and finish"})
    from app.services import editor_activity
    operation=editor_activity.start(ROOM_ID,JOB_ID,name,arguments or {})
    try:
        result=await _dispatch(name, arguments or {}) if name=='ask_user' else await asyncio.to_thread(_run_tool_thread,name,arguments or {})
        payload={}
        for block in result:
            if getattr(block,'type',None)=='text':
                try:payload=json.loads(block.text)
                except ValueError:continue
                if isinstance(payload,dict) and payload.get('ok') is False:break
        failed=isinstance(payload,dict) and payload.get('ok') is False
        editor_activity.finish(operation,failed,payload.get('error','') if isinstance(payload,dict) else '')
        return result
    except Exception as exc:  # noqa: BLE001 — the model must see the failure, not a dead pipe
        logger.exception("tool %s failed", name)
        editor_activity.finish(operation,True,str(exc))
        return _ok({"ok": False, "error": f"{type(exc).__name__}: {exc}"})


async def _dispatch(name: str, a: dict) -> list:
    global _generations
    draft = _load()
    seq = draft["sequence"]
    assets = _assets()
    if name in {'add_clip', 'add_caption', 'add_region'} and a.get('lane') == 'front':
        a = {**a, 'lane': len(seq.get('tracks', []))}
    if name == 'prepare_motion_project':
        from app.services.editor_motion_project import prepare
        source = a.get('project_dir')
        if a.get('asset_id'):
            source = ((assets.get(a['asset_id']) or {}).get('metadata') or {}).get('motion_source', {}).get('project_dir')
            if not source:
                return _ok({'ok':False,'error':'この素材には編集可能な映像プロジェクトが保存されていません'})
        return _ok(prepare(_room_dir(), source, bool(a.get('template'))))
    if name == 'write_motion_file':
        from app.services.editor_motion_project import write_file
        return _ok(write_file(_room_dir(), a['project_dir'], a['path'], a['content']))
    if name == 'render_motion_project':
        from app.services.editor_motion_project import render
        output, provenance = render(_room_dir(), a['project_dir'], _ffmpeg())
        result = _import_media(draft, str(output), a.get('name') or 'Editable motion')
        if result.get('ok'):
            with td.ContentsLock(ROOM_ID):
                p = _room_dir() / 'assets.json'
                rows = json.loads(p.read_text(encoding='utf-8'))
                for row in rows:
                    if row['id'] == result['asset_id']:
                        row.setdefault('metadata', {})['motion_source'] = provenance
                p.write_text(json.dumps(rows, ensure_ascii=False), encoding='utf-8')
            result['motion_source'] = provenance
            result['note'] = '元コードを保存済み。新規はadd_clip、対象場面の更新はset_clip_props(asset_id)。別場面・画面比率を変更せず、配置後の実物を確認する。'
        return _ok(result)
    if name=='apply_edits':
        allowed={'animate_clip','add_caption','set_clip','add_region','set_region','set_clip_props','add_clip','append_clip','insert_clip','remove_clip','trim_clip','move_clip','add_overlay','insert_freeze','add_audio','split_clip'}
        operations=a.get('operations')
        if not isinstance(operations,list) or not 1<=len(operations)<=100 or any(not isinstance(op,dict) or op.get('name') not in allowed or not isinstance(op.get('args'),dict) for op in operations):
            return _ok({'ok':False,'error':'タイムラインの編集操作を1〜100件指定してください。生成・保存・外部操作は含められません。'})
        results=[]
        try:
            with td.edit_transaction(ROOM_ID, DRAFT_ID):
                for op in operations:
                    result=await _dispatch(op['name'],_resolve_batch_results(op['args'], results))
                    value=json.loads(result[0].text)
                    if not value.get('ok'):
                        raise ValueError(value.get('error',str(value)))
                    results.append(value)
        except Exception as exc:
            return _ok({'ok':False,'rolled_back':True,'failed_operation':len(results),'error':str(exc)})
        return _ok({'ok':True,'results':results})
    if name=='production_methods':
        from app.services.editor_methods import read
        return _ok(read(a.get('method_id')))
    if name=='animate_clip':
        from app.services.timeline_motion import animate
        result=animate(seq,assets,a['clip_id'],a['poses'],a.get('easing','cubic_out'))
        if result.get('ok'):
            draft.setdefault('log',[]).append({'t':time.time(),'tool':name,'args':a})
            td.save_draft(draft)
        return _ok(result)
    if name=='search_web_references':
        from app.services.editor_reference_search import search_web
        return _ok(await search_web(a.get('queries')))
    if name in {'resolve_reference','read_references','analyze_reference'}:
        from app.services import editor_references as refs
        if name=='resolve_reference':
            return _ok(refs.resolve(ROOM_ID,draft['content_id'],a['source']))
        if name=='read_references':
            return _ok(refs.read(ROOM_ID,draft['content_id'],a.get('reference_id')))
        return _ok(refs.analyze(ROOM_ID,draft['content_id'],a['reference_id'],a.get('question','表現・構成・音・制作方法を分析してください')))
    if name=='editor_help':
        from app.services.editor_help import read
        return _ok(read(a.get('topic','operations')))
    if name=='read_presentations':
        from app.services.editor_presentation import history
        return _ok(history(ROOM_ID,draft['content_id'],before=a.get('before'),limit=a.get('limit',12)))
    if name=='revise_presentation':
        from app.services.editor_presentation import revise
        return _ok(revise(ROOM_ID,draft['content_id'],a['item_id'],a['changes']))
    if name=='present_references':
        from app.services.editor_presentation import resolve_and_present
        return _ok(await resolve_and_present(ROOM_ID,draft['content_id'],a.get('items')))
    if name=='ask_user':
        from app.services import editor_questions
        return _ok(await editor_questions.ask(ROOM_ID,JOB_ID,str(a['question'])))
    if name=='report_result':
        if a.get('outcome') not in {'achieved','needs_user','blocked'}:raise ValueError('Invalid outcome')
        draft['outcome']={'state':a['outcome'],'summary':str(a['summary'])}
        td.save_draft(draft)
        return _ok({'ok':True})
    if name=='read_project_chat':
        from app.services.supabase_client import get_supabase_client
        rows=get_supabase_client().client.table('chat_messages').select('sender_type,content,created_at').eq('room_id',ROOM_ID).order('created_at',desc=True).limit(max(1,min(int(a.get('limit',15)),50))).execute().data
        return _ok({'messages':list(reversed(rows or []))})
    if name=='conversation_history':
        from app.services import editor_project
        return _ok({'ok':True,**editor_project.dialogue(ROOM_ID,draft['content_id'],a.get('limit',30),a.get('before'))})

    if name == 'check_skill':
        from app.agent.v2.tools import SkillRegistry
        if a.get('name'):
            return _ok({'text': SkillRegistry.get_prompt(str(a['name']))})
        return _ok({'skills': [{'name': s.name, 'description': s.description} for s in SkillRegistry.list_all()]})

    if name == "timeline_outline":
        return [types.TextContent(type="text", text=tcx.timeline_outline(seq, assets))]

    if name == "list_assets":
        rows = []
        for aid, a in assets.items():
            meta = a.get("metadata") if isinstance(a.get("metadata"), dict) else {}
            dur = meta.get("duration")
            # 生成素材は元プロンプトを見せる — 作り直し指示の時に「そのクリップが
            # 何を描いているか」を引き継げる（欠落すると文脈が失われる: 2026-08-22実発生）
            gp = str(meta.get("prompt") or "").replace("\n", " ")
            rows.append(f"{aid}: {a.get('filename')} kind={a.get('kind')}"
                        + (f" duration={dur}s" if dur else "")
                        + (f" 生成元プロンプト=「{gp[:120]}」" if gp else "")
                        + (' 編集元あり: prepare_motion_project(asset_id)で再編集' if meta.get('motion_source') else ''))
        return [types.TextContent(type="text", text="\n".join(rows) or "(no assets)")]

    if name == 'measure_speech':
        from app.services.editor_workflows import measured_words
        start,end=float(a['start']),float(a['end'])
        if not 0<=start<end<=float(seq.get('duration',0))+.01:
            return _ok({'ok':False,'error':'invalid range'})
        words,evidence=measured_words(ROOM_ID,seq,start,end)
        return _ok({'ok':True,'words':words,'evidence':evidence})

    if name == "timeline_transcript":
        analyses = _load_analyses(assets)
        rows = tcx.timeline_transcript(seq, analyses, a.get("t0"), a.get("t1"))
        if not rows:
            return _ok({"ok": True, "transcript": [], "note": "no speech analysis available"})
        text = "\n".join(f"[{r['t0']:.1f}-{r['t1']:.1f}s] {r['text']}" for r in rows)
        return [types.TextContent(type="text", text=text)]

    if name == 'probe_audio':
        return _ok(tcx.probe_timeline_audio(seq, str(_room_dir()), float(a['t0']), float(a['t1'])))

    if name == "render_frame":
        ts = [float(v) for v in a.get("ts") or [] if isinstance(v, (int, float))][:8]
        if not ts and a.get("t") is not None:
            ts = [float(a["t"])]
        if not ts:
            return _ok({"ok": False, "error": "t or ts required"})
        res = tcx.render_timeline_frames(seq, str(_room_dir()), ts,
                                         out_dir=str(_room_dir() / "drafts"))
        if not res.get("ok"):
            return _ok(res)
        out: list = []
        for t, p in zip(ts, res["paths"]):
            out.append(types.TextContent(type="text", text=json.dumps({
                'time':t,'composited_frame_path':str(p),
                'active_caption_clips':[{'id':c.get('id'),'text':c['text']}
                    for track in seq.get('tracks',[]) for c in track.get('clips',[])
                    if c.get('text') and float(c.get('timeline_start',0))<=t<float(c.get('timeline_end',0))],
                'note':'字幕一覧はタイムライン上の情報。実際の表示は添付画像で確認。不一致が疑わしい場合はこの画像ファイルを直接開いて再確認できます。'
            },ensure_ascii=False)))
            out.append(types.ImageContent(type="image", data=_frame_b64(Path(p)), mimeType="image/png"))
        return out

    if name == "validate_draft":
        problems = tc.validate_sequence(seq, assets, asset_dir=str(_room_dir()))
        if draft.get('base_sequence') is not None:
            from app.services.timeline_scope import violations
            problems += violations(draft['base_sequence'], seq, draft.get('edit_scope'))
        baseline = set(draft.get("baseline_problems") or [])
        fresh = [p for p in problems if p not in baseline]
        return _ok({"ok": not fresh, "problems": fresh,
                    **({"note": f"既存タイムライン由来の問題{len(problems) - len(fresh)}件は無視されます"}
                       if len(problems) != len(fresh) else {})})

    if name == 'match_source_audio':
        from app.services.source_alignment import locate
        return _ok(locate(ROOM_ID,a['reference_asset_id'],a['candidate_asset_id'],a['times'],float(a.get('window',2))))
    if name == "generate_image":
        if str(a.get("model") or "gpt_image_2") not in {"gpt_image_2","gpt-image-2"}:
            return _ok({"ok":False,"error":"現在の制作予算では画像生成はGPT Image 2のみです。既存素材・図形・文字も使えます。"})
        if MAX_GENERATIONS and _generations >= MAX_GENERATIONS:
            return _ok({"ok": False, "error": f"generation limit ({MAX_GENERATIONS}) reached"})
        _generations += 1
        return _ok(_generate_image(draft, str(a.get("prompt") or ""), str(a.get("aspect_ratio") or seq.get('format') or "16:9"), a.get('reference_asset_ids') or [], 'gpt_image_2'))

    if name == "generate_video":
        if MAX_GENERATIONS and _generations >= MAX_GENERATIONS:
            return _ok({"ok": False, "error": "Generation limit reached for this job"})
        provider = a.get('provider', 'google')
        fmt = seq.get('format', '16:9')
        default_aspect = fmt if isinstance(fmt, str) else ('9:16' if float(fmt.get('height',720)) > float(fmt.get('width',1280)) else '16:9')
        aspect = a.get('aspect_ratio') or default_aspect
        if provider == 'google':
            from app.services import google_video
            if a.get('model') not in (None, '', google_video.MODEL, 'gemini_omni_flash_1_1'):
                return _ok({'ok':False,'error':'Google direct uses gemini-omni-1.1-flash; choose the requested provider explicitly'})
            _generations += 1
            result = google_video.generate(_room_dir(), str(a['prompt']), aspect,
                float(a.get('duration',5)), str(a.get('reference_path','')),
                str(a.get('reference_mode','style')), str(a.get('resolution','720p')))
            aid = uuid.uuid4().hex[:12]
            # Draft cleanup owns only its asset copy, never the durable provider
            # output shared by later retries or other drafts. No re-encoding.
            dest = _room_dir() / f'google_{aid}.mp4'
            shutil.copyfile(result['path'], dest)
            result = {**result, 'path': str(dest)}
            _register_media_asset(draft, aid, dest, 'video',
                filename_hint='Google Omni video', metadata=result['metadata'])
            return _ok({'ok':True,'asset_id':aid,**result,
                'note':'Place this asset in the timeline; generation alone does not update the editor.'})
        if provider != 'higgsfield':
            return _ok({'ok':False,'error':'Unknown video provider'})
        _generations += 1
        return _ok(_generate_video(draft, str(a['prompt']), aspect, float(a.get('duration',5)),
            str(a.get('model','gemini_omni_flash_1_1')),str(a.get('reference_path','')),
            str(a.get('resolution','720p'))))
    if name == "import_image":
        return _ok(_import_image(draft, str(a.get("url") or ""), str(a.get("name") or "")))

    if name == "import_media":
        return _ok(_import_media(draft, str(a.get("path") or ""), str(a.get("name") or "")))

    if name == "export_timeline":
        return _ok(_export_timeline(draft))

    if name == "watch_video":
        return _ok(_watch_video(seq, assets, float(a["t0"]), float(a["t1"]),
                                str(a.get("question") or "")))

    if name == "watch_render":
        return _ok(_watch_render(seq, float(a["t0"]), float(a["t1"]), str(a.get("question") or "")))

    if name == "editor_state":
        return _ok(_editor_state(seq, assets))

    if name == "clips_at":
        return _ok({"ok": True, "t": float(a["t"]), "clips": tc.clips_at(seq, assets, t=float(a["t"]))})

    if name == "generate_speech":
        return _ok(_generate_speech(draft, str(a.get("text") or ""), str(a.get("voice") or "owner"),
                                    a.get("readings") if isinstance(a.get("readings"), dict) else None,
                                    str(a.get("name") or "")))

    if name == "auto_captions":
        segs = [s for s in (a.get("segments") or []) if isinstance(s, dict)]
        res = _auto_captions(draft, seq, assets, segs,
                             a.get("style") if isinstance(a.get("style"), dict) else None,
                             bool(a.get("replace", True)), a.get('words'))
        return _ok(res)

    # ---- mutating commands on the draft ----
    cmd = {
        "add_region": lambda: tc.add_region(seq, timeline_start=float(a["timeline_start"]),
                                            timeline_end=float(a["timeline_end"]),
                                            x=float(a["x"]), y=float(a["y"]),
                                            width=float(a["width"]), height=float(a["height"]),
                                            style=str(a.get("style") or "gaussian"),
                                            strength=(float(a["strength"]) if a.get("strength") is not None else None),
                                            color=(str(a["color"]) if a.get("color") else None),
                                            opacity=(float(a["opacity"]) if a.get("opacity") is not None else None),
                                            rotation=(float(a["rotation"]) if a.get("rotation") is not None else None),
                                            keys=a.get("keys"),
                                            lane=(int(a["lane"]) if a.get("lane") is not None else None)),
        "set_region": lambda: tc.set_region(seq, clip_id=str(a["clip_id"]),
                                            x=(float(a["x"]) if a.get("x") is not None else None),
                                            y=(float(a["y"]) if a.get("y") is not None else None),
                                            width=(float(a["width"]) if a.get("width") is not None else None),
                                            height=(float(a["height"]) if a.get("height") is not None else None),
                                            style=(str(a["style"]) if a.get("style") else None),
                                            strength=(float(a["strength"]) if a.get("strength") is not None else None),
                                            color=(str(a["color"]) if a.get("color") else None),
                                            opacity=(float(a["opacity"]) if a.get("opacity") is not None else None),
                                            rotation=(float(a["rotation"]) if a.get("rotation") is not None else None),
                                            keys=a.get("keys"), clear_keys=bool(a.get("clear_keys", False))),
        "set_clip_props": lambda: tc.set_clip_props(seq, assets, clip_id=str(a["clip_id"]),
                                                    props=a.get("props") if isinstance(a.get("props"), dict) else {}),
        "split_clip": lambda: _split_at_times(seq, str(a['clip_id']), a['at']),
        "add_clip": lambda: tc.add_clip(seq, assets, asset_id=str(a["asset_id"]),
                                        timeline_start=float(a["timeline_start"]), duration=float(a["duration"]),
                                        source_start=float(a.get("source_start") or 0),
                                        lane=(int(a["lane"]) if a.get("lane") is not None else None),
                                        fit=str(a.get("fit") or "contain"),
                                        position=a.get("position") if isinstance(a.get("position"), dict) else None,
                                        speed=float(a.get("speed") or 1.0),
                                        with_audio=bool(a.get("with_audio", False)),
                                        volume=float(a.get("volume") if a.get("volume") is not None else 1.0)),
        "append_clip": lambda: tc.append_clip(seq, assets, asset_id=str(a["asset_id"]),
                                              source_start=float(a.get("source_start") or 0),
                                              duration=float(a["duration"]),
                                              at=(float(a["at"]) if a.get("at") is not None else None)),
        "insert_clip": lambda: tc.insert_clip(seq, assets, asset_id=str(a["asset_id"]),
                                              source_start=float(a.get("source_start") or 0),
                                              duration=float(a["duration"]), at=float(a["at"]),
                                              mode=str(a.get("mode") or "ripple")),
        "remove_clip": lambda: tc.remove_clip(seq, clip_id=str(a["clip_id"]),
                                              linked=bool(a.get("linked", True))),
        "trim_clip": lambda: tc.trim_clip(seq, assets, clip_id=str(a["clip_id"]),
                                          edge=str(a["edge"]), new_time=float(a["new_time"])),
        "move_clip": lambda: tc.move_clip(seq, clip_id=str(a["clip_id"]), new_start=float(a["new_start"])),
        "add_overlay": lambda: tc.add_overlay(seq, assets, asset_id=str(a["asset_id"]),
                                              timeline_start=float(a["timeline_start"]),
                                              timeline_end=float(a["timeline_end"]),
                                              x=float(a["x"]), y=float(a["y"]),
                                              width=float(a["width"]), height=float(a["height"]),
                                              source_start=float(a.get("source_start") or 0)),
        "add_caption": lambda: tc.add_caption(seq, text=str(a.get("text") or ""),
                                              timeline_start=float(a["timeline_start"]),
                                              timeline_end=float(a["timeline_end"]),
                                              lane=(int(a["lane"]) if a.get("lane") is not None else None),
                                              style=a.get("style") if isinstance(a.get("style"), dict) else None),
        "insert_freeze": lambda: tc.insert_freeze(seq, assets, source_clip_id=str(a["source_clip_id"]),
                                                  at_source_time=(float(a["at_source_time"]) if a.get("at_source_time") is not None else None),
                                                  timeline_start=float(a["timeline_start"]),
                                                  duration=float(a["duration"])),
        "set_clip": lambda: tc.set_clip(seq, clip_id=str(a["clip_id"]),
                                        text=(str(a["text"]) if a.get("text") is not None else None),
                                        style=a.get("style") if isinstance(a.get("style"), dict) else None),
        "add_audio": lambda: tc.add_audio(seq, assets, asset_id=str(a["asset_id"]),
                                            source_start=float(a.get("source_start") or 0),
                                            duration=float(a["duration"]), at=float(a.get("at") or 0),
                                            volume=float(a.get("volume") or 0.22),
                                            role=str(a.get("role") or "music")),
    }.get(name)
    if cmd is None:
        return _ok({"ok": False, "error": f"unknown tool: {name}"})
    result = cmd()
    if result.get("ok"):
        draft.setdefault("log", []).append({"t": time.time(), "tool": name, "args": a})
        td.save_draft(draft)
        if name in ("add_caption", "set_clip"):
            # rasterize the designed caption PNG NOW so export (and the transparency
            # check) always has the CURRENT text+style. set_clip args are partial —
            # bake from the clip's post-command state, not the args (a style-only
            # set_clip left the final-style PNG unbaked → invisible caption shipped)
            bk_text, bk_style = str(a.get("text") or ""), a.get("style")
            if name == "set_clip":
                for tr in seq.get("tracks") or []:
                    for cl in tr.get("clips") or []:
                        if str(cl.get("id")) == str(a.get("clip_id")):
                            bk_text = str(cl.get("text") or "")
                            bk_style = cl.get("style")
            note = _ensure_caption_png(bk_text,
                                       bk_style if isinstance(bk_style, dict) else None)
            if note:
                result["note"] = note
    return _ok(result)


def _ensure_caption_png(text: str, style: dict | None) -> str | None:
    import hashlib
    text = text.strip()
    if not text:
        return None
    design = dict(style or {})
    design.pop("x", None)
    design.pop("y", None)
    key_src = json.dumps({"w": 1080, "h": 1920, "t": text, "d": design, "words": []},
                         ensure_ascii=False, sort_keys=True)
    key = hashlib.sha1(key_src.encode()).hexdigest()[:16]
    cache_dir = _room_dir() / "caption-cache"
    cache_dir.mkdir(parents=True, exist_ok=True)
    png = cache_dir / f"{key}.png"
    if png.exists() and png.stat().st_size > 0:
        return None
    spec = cache_dir / f"_spec_agent_{key}.json"
    spec.write_text(json.dumps({
        "outW": 1080, "outH": 1920,
        "web_base": os.environ.get("DAN_CAPTION_RENDER_BASE", "http://127.0.0.1:3000"),
        "items": [{"png": str(png), "text": text, "time": 0.0, "design": design, "words": []}],
    }, ensure_ascii=False), encoding="utf-8")
    bake_err = ""
    dbg_log = cache_dir / f"_bake_dbg_{key}.log"
    dbg_log.unlink(missing_ok=True)
    try:
        script = Path(__file__).resolve().parents[1] / "scripts" / "render_caption_pngs.py"
        r = subprocess.run([sys.executable, str(script), str(spec)], capture_output=True,
                           text=True, encoding="utf-8", errors="replace",
                           stdin=subprocess.DEVNULL,
                           env={**os.environ, "RENDER_CAPTION_DEBUG_LOG": str(dbg_log)},
                           timeout=180, creationflags=getattr(subprocess, "CREATE_NO_WINDOW", 0))
        if not (png.exists() and png.stat().st_size > 0):
            bake_err = f"rc={r.returncode} stdout={(r.stdout or '')[-400:]} stderr={(r.stderr or '')[-800:]}"
    except Exception as exc:  # noqa: BLE001
        bake_err = f"spawn failed: {type(exc).__name__}: {exc}"
    finally:
        try:
            spec.unlink()
        except OSError:
            pass
    if bake_err:
        try:
            bake_err += "\nstages:\n" + (dbg_log.read_text(encoding="utf-8")
                                         if dbg_log.exists() else "(no stage log)")
        except OSError:
            pass
    dbg_log.unlink(missing_ok=True)
    if not (png.exists() and png.stat().st_size > 0):
        # 4連続失敗→原因不明タイムアウトの実ジョブ事故があった。失敗理由は
        # 揉み消さずログに残し、エージェントには「リトライで直らない」ことを伝える
        try:
            (cache_dir / "bake_error.log").write_text(
                f"{time.strftime('%Y-%m-%d %H:%M:%S')} key={key} text={text[:40]}\n{bake_err}\n",
                encoding="utf-8")
        except OSError:
            pass
        return ("テロップは追加済みだがデザインPNGの生成に失敗（この環境の不調で、リトライや"
                "スタイル変更では直らない。原因調査も不要——クリップはこのまま残してよく、"
                "プレビューを開いた時に自動生成される。他の作業を続けて完了させること）")
    try:
        # numpyは使わない: このMCPプロセスでは import numpy がDLL初期化で
        # 無期限ハングする（py-spy実証: create_module内で7分停止→ジョブ全損）。
        # PILのヒストグラムで同じ「不透明ピクセル数」を数える
        from PIL import Image
        hist = Image.open(png).convert("RGBA").getchannel("A").histogram()
        if sum(hist[11:]) < 50:
            png.unlink(missing_ok=True)
            return ("警告: このスタイルではテロップが透明にレンダリングされました。"
                    "styleを省略（既定デザイン）にするか、fontSizeは相対値(0.5〜2.0)で指定してください")
    except Exception:  # noqa: BLE001
        pass
    return None


def _load_analyses(assets: dict) -> dict:
    """Per-asset Whisper analysis cached on assets.json metadata.audio_analysis."""
    out: dict = {}
    for aid, a in assets.items():
        meta = a.get("metadata") if isinstance(a.get("metadata"), dict) else {}
        ana = meta.get("audio_analysis")
        if isinstance(ana, dict):
            out[aid] = ana
    return out


def _higgsfield_cli() -> str:
    """PATHにnpm binが無い環境(タスクスケジューラ起動の子プロセス)でも実体を解決する。"""
    found = shutil.which("higgsfield")
    if found:
        return found
    appdata = os.environ.get("APPDATA")
    if appdata:
        for name in ("higgsfield.cmd", "higgsfield"):
            cand = Path(appdata) / "npm" / name
            if cand.exists():
                return str(cand)
    return "higgsfield"


def _higgsfield_command():
    cli = Path(_higgsfield_cli())
    if cli.suffix.lower() in {'.cmd','.ps1'}:
        entry=cli.parent/'node_modules/@higgsfield/cli/bin/higgsfield.js'
        if entry.is_file():return [shutil.which('node') or 'node',str(entry)]
        raise RuntimeError('Higgsfield CLI entry point missing')
    return [str(cli)]


def _generated_image_url(value):
    if isinstance(value,list):
        return next((url for item in value if (url:=_generated_image_url(item))),None)
    if isinstance(value,dict):
        for key in ('results','result','outputs','output','images','image','result_url','image_url','download_url','url'):
            item=value.get(key)
            if isinstance(item,str) and item.startswith(('https://','http://')) and key in {'result_url','download_url','image_url','url','image'}:
                return item
            if isinstance(item,(list,dict)):
                found=_generated_image_url(item)
                if found:return found
        for key,item in value.items():
            if key not in {'params','parameters','input','inputs','medias','references','thumbnail','thumbnail_url'} and isinstance(item,(dict,list)):
                found=_generated_image_url(item)
                if found:return found
    return None


def _generate_image(draft: dict, prompt: str, aspect: str, reference_asset_ids=None, model='gpt_image_2') -> dict:
    prompt = " ".join(prompt.split())  # 改行入り引数は.cmdシムで後続引数ごと切断される
    if not prompt:
        return {"ok": False, "error": "empty prompt"}
    references=[]
    for aid in reference_asset_ids or []:
        a=_assets().get(aid,{})
        path=Path(a.get('local_path') or '')
        if not path.is_file() or path.suffix.lower() not in {'.png','.jpg','.jpeg','.webp'}:
            return {'ok':False,'error':f'Reference image missing: {aid}'}
        references += ['--image',str(path)]
    from datetime import datetime, timezone
    event_path=_room_dir()/'jobs'/JOB_ID/'events.jsonl'
    event_path.parent.mkdir(parents=True,exist_ok=True)
    with event_path.open('a',encoding='utf-8') as f:
        f.write(json.dumps({'created_at':datetime.now(timezone.utc).isoformat(),'type':'generation','model':model,
                           'text':f'{model}で画像を生成しています（参照画像{len(reference_asset_ids or [])}枚）'},ensure_ascii=False)+'\n')
    try:
        r = subprocess.run(
            _higgsfield_command() + ["generate", "create", model,
             "--prompt", prompt, "--aspect_ratio", aspect,
             "--wait", "--wait-timeout", "10m", "--json"] + references,
            capture_output=True, text=True, encoding="utf-8", errors="replace",
            timeout=660, shell=False, creationflags=getattr(subprocess,'CREATE_NO_WINDOW',0),
        )
    except subprocess.TimeoutExpired:
        return {"ok": False, "error": "image generation timeout (11m)"}
    out = (r.stdout or "") + (r.stderr or "")
    (event_path.parent/f'generation-{int(time.time())}.json').write_text(r.stdout or '',encoding='utf-8')
    try:
        url=_generated_image_url(json.loads(r.stdout)) if r.returncode==0 else None
    except ValueError:
        url=None
    if not url:
        return {"ok": False, "error": f"no result url in generator output: {out[-400:]}"}
    aid = uuid.uuid4().hex[:12]
    dest = _room_dir() / f"gen_{aid}.png"
    try:
        urllib.request.urlretrieve(url, dest)
    except Exception as exc:  # noqa: BLE001
        return {"ok": False, "error": f"download failed: {exc}"}
    provenance={'model':model,'prompt':prompt,'aspect_ratio':aspect,'reference_asset_ids':reference_asset_ids or []}
    _register_image_asset(draft, aid, dest, "generated",metadata=provenance)
    return {"ok": True, "asset_id": aid, "path": str(dest), 'provenance':provenance, "note": "add_overlay / append_clip でタイムラインに配置できます"}


def _find_generated_video_url(payload: object) -> str | None:
    """Read output media only; input references and thumbnails are not results."""
    if isinstance(payload, dict):
        if str(payload.get('status', '')).lower() in {'queued', 'pending', 'processing', 'failed'}:
            return None
        for key in ('result_url', 'video_url', 'download_url', 'url'):
            value = payload.get(key)
            if isinstance(value, str) and value.startswith(('https://', 'http://')):
                path = value.split('?', 1)[0].lower()
                if not path.endswith(('.jpg', '.jpeg', '.png', '.webp', '.gif')):
                    return value
        for key, value in payload.items():
            if key.lower() in {'params', 'input', 'inputs', 'medias', 'thumbnail', 'thumbnails', 'preview', 'reference', 'references'}:
                continue
            found = _find_generated_video_url(value)
            if found:
                return found
    elif isinstance(payload, list):
        for value in payload:
            found = _find_generated_video_url(value)
            if found:
                return found
    return None


def _generate_video(draft: dict, prompt: str, aspect: str, duration: float,
                    model: str, reference_path: str, resolution: str) -> dict:
    """Generate an editable video asset through Higgsfield.

    It intentionally returns only an asset. Placement, trimming, cropping, and
    approval remain normal timeline operations instead of provider side-effects.
    """
    prompt = " ".join(prompt.split())  # 改行入り引数は.cmdシムで後続引数ごと切断される
    if not prompt:
        return {"ok": False, "error": "empty prompt"}
    supported_models = {"seedance_2_5", "seedance_2_0", "kling3_0", "gemini_omni", "gemini_omni_flash_1_1"}
    if model not in supported_models:
        return {"ok": False, "error": f"unsupported Higgsfield video model: {model}"}
    if aspect not in {"16:9", "9:16", "4:3", "3:4", "1:1", "21:9", "auto"}:
        return {"ok": False, "error": f"unsupported aspect ratio: {aspect}"}
    if resolution not in {"480p", "720p", "1080p", "4k"}:
        return {"ok": False, "error": f"unsupported resolution: {resolution}"}

    # モデルごとの尺制約（実測: omniは11秒で `duration <= 10` の事前拒否）
    want = max(1, int(round(duration)))
    if model == "seedance_2_5":
        clip_duration = next((d for d in (5, 10, 15, 30) if d >= want), 30)
    elif model == "kling3_0":
        clip_duration = 5 if want <= 5 else 10
    elif model == "gemini_omni":
        clip_duration = max(2, min(10, want))
    else:
        clip_duration = min(15, want)
    cmd = _higgsfield_command() + ["generate", "create", model, "--prompt", prompt,
           "--duration", str(clip_duration), "--wait", "--wait-timeout", "20m", "--json"]
    if model == "seedance_2_5":
        # width/heightだけだと既定aspect(16:9)がサーバー側で勝つ — 両方渡す(実測)
        if aspect not in {"16:9", "9:16", "1:1"}:
            return {"ok": False, "error": "seedance_2_5 supports 16:9, 9:16, or 1:1 here"}
        dims = {"9:16": (720, 1280), "16:9": (1280, 720), "1:1": (720, 720)}[aspect]
        cmd += ["--width", str(dims[0]), "--height", str(dims[1]), "--aspect_ratio", aspect,
                "--resolution", "720p", "--generate_audio", "true"]
    elif model in {"gemini_omni","gemini_omni_flash_1_1"}:
        if aspect not in {"16:9", "9:16"}:
            return {"ok": False, "error": "gemini_omni supports only 16:9 or 9:16"}
        cmd += ["--aspect_ratio", aspect]
        if model=='gemini_omni_flash_1_1':
            h={'480p':720,'720p':720,'1080p':1080,'4k':2160}[resolution]
            dims=(int(h*16/9),h) if aspect=='16:9' else (h,int(h*16/9))
            cmd += ['--width',str(dims[0]),'--height',str(dims[1]),'--resolution',resolution if resolution!='480p' else '720p',
                    '--mode','image-to-video' if reference_path else 'text-to-video']
    else:
        cmd += ["--aspect_ratio", aspect]
    if model == "seedance_2_0":
        cmd += ["--resolution", resolution]
    elif model == "kling3_0" and aspect not in {"16:9", "9:16", "1:1"}:
        return {"ok": False, "error": "kling3_0 supports only 16:9, 9:16, or 1:1"}
    if reference_path:
        ref = Path(reference_path).expanduser()
        if not ref.is_file():
            return {"ok": False, "error": f"reference file not found: {reference_path}"}
        is_video = ref.suffix.lower() in {".mp4", ".mov", ".mkv", ".webm", ".m4v"}
        if model == "gemini_omni":
            return {"ok": False, "error": "gemini_omni reference is not supported here; use seedance_2_5/2_0"}
        if model == "kling3_0":
            if is_video:
                return {"ok": False, "error": "kling3_0 reference video is not supported here; use seedance_2_0"}
            cmd += ["--start-image", str(ref)]
        else:
            cmd += ["--video" if is_video else "--image", str(ref)]
    try:
        result = subprocess.run(
            cmd, capture_output=True, text=True, encoding="utf-8", errors="replace", timeout=1260,
            creationflags=getattr(subprocess, "CREATE_NO_WINDOW", 0),
        )
    except subprocess.TimeoutExpired:
        return {"ok": False, "error": "Higgsfield video generation timed out (21m)"}
    if result.returncode != 0:
        detail = ((result.stderr or result.stdout or "generation failed").strip())[-500:]
        return {"ok": False, "error": f"Higgsfield generation failed: {detail}"}
    try:
        url = _find_generated_video_url(json.loads(result.stdout))
    except json.JSONDecodeError:
        url = None
    if not url:
        return {"ok": False, "error": "Higgsfield returned no downloadable video URL"}

    aid = uuid.uuid4().hex[:12]
    dest = _room_dir() / f"higgs_{aid}.mp4"
    try:
        urllib.request.urlretrieve(url, dest)
    except Exception as exc:  # noqa: BLE001
        return {"ok": False, "error": f"generated video download failed: {exc}"}
    if not dest.exists() or dest.stat().st_size == 0:
        return {"ok": False, "error": "generated video download was empty"}
    meta: dict = {"generator": "higgsfield", "model": model, "prompt": prompt,
                  "requested_duration": clip_duration, "source_url": url}
    try:
        probe = subprocess.run(
            [_ffprobe(), "-v", "error", "-show_entries", "format=duration", "-of", "json", str(dest)],
            capture_output=True, text=True, timeout=30,
            creationflags=getattr(subprocess, "CREATE_NO_WINDOW", 0),
        )
        meta["duration"] = float((json.loads(probe.stdout).get("format") or {}).get("duration") or 0)
        if probe.returncode or meta['duration'] <= 0:
            return {'ok': False, 'error': '生成結果を動画として読み取れません。再生成せず、出力URLとファイル形式を確認してください。'}
    except Exception as exc:
        return {'ok': False, 'error': f'生成動画の検証に失敗しました: {exc}'}
    _register_media_asset(draft, aid, dest, "video", filename_hint=f"Higgsfield {model} clip", metadata=meta)
    return {"ok": True, "asset_id": aid, "kind": "video", "path": str(dest), "metadata": meta,
            "note": "Generated clip is ready. Place it with append_clip, insert_clip, or add_overlay."}


def _import_image(draft: dict, url: str, name: str) -> dict:
    """Bring a REAL image into the room (web URL or local path) — the general
    entry gate for authentic material (logos, product shots) as opposed to
    generated imitations. Converted to PNG (alpha preserved) and registered
    exactly like generated assets so failure-GC covers it too."""
    if not url.strip():
        return {"ok": False, "error": "url required"}
    aid = uuid.uuid4().hex[:12]
    raw = _room_dir() / f"imp_{aid}.bin"
    try:
        if re.match(r"^https?://", url):
            req = urllib.request.Request(url, headers={"User-Agent": "Mozilla/5.0"})
            with urllib.request.urlopen(req, timeout=60) as resp, open(raw, "wb") as f:
                f.write(resp.read(50 * 1024 * 1024))
        else:
            src = Path(url)
            if not src.exists():
                return {"ok": False, "error": f"file not found: {url}"}
            raw.write_bytes(src.read_bytes())
    except Exception as exc:  # noqa: BLE001
        return {"ok": False, "error": f"fetch failed: {exc}"}
    dest = _room_dir() / f"imp_{aid}.png"
    try:
        from PIL import Image
        im = Image.open(raw)
        im.load()
        if im.mode not in ("RGBA", "RGB"):
            im = im.convert("RGBA")
        im.save(dest, format="PNG")
    except Exception as exc:  # noqa: BLE001
        return {"ok": False, "error": f"not a usable image (png/jpg/webp等のみ。svgは不可): {exc}"}
    finally:
        try:
            raw.unlink()
        except OSError:
            pass
    _register_image_asset(draft, aid, dest, "local_path", filename_hint=name)
    return {"ok": True, "asset_id": aid, "path": str(dest),
            "size": f"{im.width}x{im.height}",
            "note": "add_overlay / append_clip でタイムラインに配置できます"}


def _import_media(draft: dict, path: str, name: str) -> dict:
    from app.services.editor_media import import_media
    result=import_media(ROOM_ID,path,name,origin=f'agent:{JOB_ID}')
    if result.get('ok'):_track_asset(draft,result['asset_id'])
    return result


def _ffmpeg() -> str:
    import shutil as _sh
    for c in (_sh.which("ffmpeg"), r"C:\Users\Owner\ffmpeg\bin\ffmpeg.exe", r"C:\ffmpeg\bin\ffmpeg.exe"):
        if c and Path(c).exists():
            return c
    raise RuntimeError("ffmpeg not found")


def _ffprobe() -> str:
    """Find ffprobe next to the selected ffmpeg binary when possible."""
    ffmpeg = _ffmpeg()
    candidates = (
        str(Path(ffmpeg).with_name("ffprobe.exe")),
        shutil.which("ffprobe"),
        r"C:\Users\Owner\ffmpeg\bin\ffprobe.exe",
        r"C:\ffmpeg\bin\ffprobe.exe",
    )
    for candidate in candidates:
        if candidate and Path(candidate).is_file():
            return candidate
    raise RuntimeError("ffprobe not found")


def _export_timeline(draft: dict) -> dict:
    """Render the isolated draft and publish its output as a room artifact."""
    if not CONTENT_ID:
        return {"ok": False, "error": "timeline export has no content context"}
    from app.api.production_asset_routes import _render_sequence_job

    export_id = f"{JOB_ID}_export"
    export_dir = _room_dir() / "jobs" / export_id
    export_dir.mkdir(parents=True, exist_ok=True)
    instruction = {"timeline": {"sequence": json.loads(json.dumps(draft["sequence"]))}}
    result = _render_sequence_job(ROOM_ID, export_id, CONTENT_ID, instruction, export_dir)
    if not result:
        return {"ok": False, "error": "timeline has no renderable base video clips"}
    return {"ok": True, **result, "note": "export is a reusable room asset"}


def _editor_state(seq: dict, assets: dict) -> dict:
    """What the user's editor shows right now (playhead / selection) + the clips under
    the playhead, so 'here' and 'this' resolve without guessing."""
    p = _room_dir() / "editor_state.json"
    try:
        st = p.stat()
        data = json.loads(p.read_text(encoding="utf-8"))
    except (OSError, ValueError):
        return {"ok": True, "open": False, "note": "エディタは開いていない（または状態が未公開）。時刻はユーザーの言葉から決める"}
    age = time.time() - st.st_mtime
    if age > 900:
        return {"ok": True, "open": False, "note": f"エディタの状態が古い（{age / 60:.0f}分前）"}
    same = str(data.get("content_id") or "") == CONTENT_ID
    out = {"ok": True, "open": True, "same_content": same, "playhead": data.get("playhead"),
           "playing": data.get("playing"), "selected": data.get("selected") or [], "age_s": round(age, 1)}
    if not same:
        out["note"] = f"エディタは別のコンテンツ({data.get('content_id')})を開いている。この作業対象は {CONTENT_ID}"
    try:
        t = float(data.get("playhead") or 0)
        out["clips_under_playhead"] = tc.clips_at(seq, assets, t=t)
    except (TypeError, ValueError):
        pass
    return out


def _generate_speech(draft: dict, text: str, voice: str, readings: dict | None, name: str) -> dict:
    """Cloned-voice narration → wav asset in the room (GPU-serialized subprocess)."""
    text = text.strip()
    if not text:
        return {"ok": False, "error": "text required"}
    from app.services import timeline_speech as tsp

    aid = uuid.uuid4().hex[:12]
    dest = _room_dir() / f"agent_{aid}.wav"
    res = tsp.synthesize(text, dest, voice=voice, readings=readings)
    if not res.get("ok"):
        return res
    meta = {"duration": float(res.get("duration") or 0), "text": text, "spoken": res.get("spoken"), "voice": voice}
    meta.update({k:res[k] for k in ('backend','pod_id','seconds','transfer_included_seconds') if res.get(k) is not None})
    _register_media_asset(draft, aid, dest, "audio", filename_hint=(name.strip() or text[:20]) + ".wav", metadata=meta)
    return {"ok": True, "asset_id": aid, "duration": meta["duration"], "spoken": res.get("spoken"),
            "seconds": res.get("seconds"), "gpu_wait": res.get("gpu_wait"),
            "backend":res.get('backend'), "pod_id":res.get('pod_id'),
            "note": "add_audio(asset_id, duration, at, volume=1.0, role='narration') で置く"}


def _auto_captions(draft: dict, seq: dict, assets: dict, segments: list, style: dict | None, replace: bool, words=None) -> dict:
    from app.services import timeline_captions as cap

    if not segments:
        return {"ok": False, "error": "segments=[{t0,t1,text}] が必要"}
    work = _room_dir() / "drafts" / f"cap_{draft['draft_id']}"
    res = cap.auto_captions(seq, assets, work, segments, style=style, replace=replace, words=words)
    if not res.get("ok"):
        return res
    draft.setdefault("log", []).append({"t": time.time(), "tool": "auto_captions", "args": {"segments": len(segments)}})
    td.save_draft(draft)
    notes = []
    st = res.get("style")
    for sp in res.get("specs") or []:
        n = _ensure_caption_png(sp["text"], st if isinstance(st, dict) else None)
        if n and n not in notes:
            notes.append(n)
    out = {"ok": True, "captions": res["captions"], "words_heard": res["words"],
           "placed": [{"start": s["start"], "end": s["end"], "text": s["text"]} for s in res.get("specs") or []]}
    if notes:
        out["note"] = notes[0]
    return out


def _watch_render(seq: dict, t0: float, t1: float, question: str) -> dict:
    """Export [t0,t1] of the DRAFT with the preview-parity native compositor (blur, frames,
    captions, overlays, audio) and let Gemini watch the result — the viewer's truth."""
    if t1 <= t0:
        return {"ok": False, "error": "t1 must be > t0"}
    if t1 - t0 > 120:
        return {"ok": False, "error": "範囲が長すぎます（最大120秒）。要点に絞って複数回に分けてください"}
    if not CONTENT_ID:
        return {"ok": False, "error": "no content context"}
    from app.api.production_asset_routes import _render_sequence_job

    export_id = f"{JOB_ID}_watch_{uuid.uuid4().hex[:6]}"
    export_dir = _room_dir() / "jobs" / export_id
    export_dir.mkdir(parents=True, exist_ok=True)
    instruction = {"timeline": {"sequence": json.loads(json.dumps(seq))},
                   "export_ranges": [[round(t0, 3), round(t1, 3)]], "no_register": True}
    try:
        result = _render_sequence_job(ROOM_ID, export_id, CONTENT_ID, instruction, export_dir)
    except Exception as exc:  # noqa: BLE001
        return {"ok": False, "error": f"render failed: {exc}"}
    path = (result or {}).get("output_path")
    if not path or not Path(path).exists():
        return {"ok": False, "error": "render produced no file"}
    from app.services.video_analyzer import _analyze_file_sync

    prompt = (f"これは完成映像の {t0:.1f}秒〜{t1:.1f}秒 を書き出したものです（字幕・ぼかし・枠・重ねはすべて反映済み）。"
              f"時刻はこの切り出し内の相対秒で述べてください。\n\n"
              + (question or "字幕と発話のタイミングのずれ、隠すべき情報（ナンバー・番号・社名）の露出、"
                             "音の切れ・不自然な繋ぎ、絵と話の食い違いを、時刻つきで列挙してください。問題が無ければ無いと言ってください。"))
    text = _analyze_file_sync(str(path), prompt)
    if not text:
        return {"ok": False, "error": "Gemini returned empty response"}
    return {"ok": True, "t0": t0, "t1": t1, "answer": text, "file": str(path),
            "note": "answer内の時刻は範囲先頭からの相対秒"}


def _watch_video(seq: dict, assets: dict, t0: float, t1: float, question: str) -> dict:
    """Gemini's eyes on the timeline: cut the base-lane footage for [t0,t1] into a
    small 640p mp4 (original audio included) and have Gemini watch it. This is the
    agent's only way to perceive MOTION and SOUND — render_frame only shows stills."""
    if t1 <= t0:
        return {"ok": False, "error": "t1 must be > t0"}
    if t1 - t0 > 120:
        return {"ok": False, "error": "範囲が長すぎます（最大120秒）。要点に絞って複数回に分けてください"}
    base = next((tr for tr in seq.get("tracks") or [] if tr.get("type") == "video"), None)
    if not base:
        return {"ok": False, "error": "no video track"}
    parts: list[Path] = []
    tmp_dir = _room_dir() / "drafts"
    tmp_dir.mkdir(parents=True, exist_ok=True)
    try:
        for c in sorted(base.get("clips") or [], key=lambda x: float(x.get("timeline_start") or 0)):
            ts, te = float(c.get("timeline_start") or 0), float(c.get("timeline_end") or 0)
            if te <= t0 or ts >= t1 or c.get("freeze"):
                continue
            asset = assets.get(str(c.get("asset_id") or "")) or {}
            src = asset.get("local_path") or asset.get("original_uri") or ""
            if not src or not Path(src).exists():
                continue
            ss = float(c.get("source_start") or 0) + (max(t0, ts) - ts)
            dur = min(t1, te) - max(t0, ts)
            if dur <= 0.05:
                continue
            part = tmp_dir / f"watch_{uuid.uuid4().hex[:8]}.mp4"
            r = subprocess.run(
                [_ffmpeg(), "-nostdin", "-y", "-ss", f"{ss:.3f}", "-t", f"{dur:.3f}", "-i", src,
                 "-vf", "scale=-2:640", "-c:v", "libx264", "-preset", "veryfast", "-crf", "28",
                 "-c:a", "aac", "-b:a", "96k", str(part)],
                capture_output=True, stdin=subprocess.DEVNULL, timeout=180,
                creationflags=getattr(subprocess, "CREATE_NO_WINDOW", 0),
            )
            if r.returncode == 0 and part.exists() and part.stat().st_size > 0:
                parts.append(part)
        if not parts:
            return {"ok": False, "error": "この範囲に切り出せる映像クリップがありません"}
        if len(parts) == 1:
            clip_path = parts[0]
        else:
            lst = tmp_dir / f"watch_{uuid.uuid4().hex[:8]}.txt"
            lst.write_text("".join(f"file '{p.as_posix()}'\n" for p in parts), encoding="utf-8")
            clip_path = tmp_dir / f"watch_{uuid.uuid4().hex[:8]}.mp4"
            r = subprocess.run(
                [_ffmpeg(), "-nostdin", "-y", "-f", "concat", "-safe", "0", "-i", str(lst), "-c", "copy", str(clip_path)],
                capture_output=True, stdin=subprocess.DEVNULL, timeout=120,
                creationflags=getattr(subprocess, "CREATE_NO_WINDOW", 0),
            )
            lst.unlink(missing_ok=True)
            if r.returncode != 0:
                return {"ok": False, "error": "segment concat failed"}
            parts.append(clip_path)
        from app.services.video_analyzer import _analyze_file_sync
        prompt = (
            f"これは動画タイムラインの {t0:.1f}秒〜{t1:.1f}秒 の切り出しです。"
            f"時刻に言及する時はこの切り出し内の相対秒で述べてください。\n\n"
            + (question or "この映像の内容（動き・話し方・音声・テンポ）を簡潔に説明してください。")
        )
        text = _analyze_file_sync(str(clip_path), prompt)
        if not text:
            return {"ok": False, "error": "Gemini returned empty response"}
        return {"ok": True, "t0": t0, "t1": t1, "answer": text,
                "note": "answer内の時刻は範囲先頭からの相対秒"}
    except subprocess.TimeoutExpired:
        return {"ok": False, "error": "video cut timeout"}
    except Exception as exc:  # noqa: BLE001
        return {"ok": False, "error": f"watch failed: {exc}"}
    finally:
        for p in parts:
            try:
                p.unlink()
            except OSError:
                pass


def _media_dims(path: Path) -> dict:
    """実寸(width/height)を返す。不変条件: 登録される素材は必ず実寸を持つ
    （クリップの形状保持計算の基準。欠落するとキャンバス切替で歪む）。"""
    try:
        r = subprocess.run(
            [_ffprobe(), "-v", "error", "-select_streams", "v:0",
             "-show_entries", "stream=width,height", "-of", "json", str(path)],
            capture_output=True, text=True, timeout=30,
            creationflags=getattr(subprocess, "CREATE_NO_WINDOW", 0),
        )
        s = (json.loads(r.stdout or "{}").get("streams") or [{}])[0]
        w, h = int(s.get("width") or 0), int(s.get("height") or 0)
        return {"width": w, "height": h} if w and h else {}
    except Exception:  # noqa: BLE001
        return {}


def _register_image_asset(draft: dict, aid: str, dest: Path, source_type: str,
                          filename_hint: str = "", metadata: dict | None = None) -> None:
    with td.ContentsLock(ROOM_ID):
        p = _room_dir() / "assets.json"
        data = json.loads(p.read_text(encoding="utf-8")) if p.exists() else []
        from datetime import datetime, timezone
        now = datetime.now(timezone.utc).isoformat()
        data.append({
            # ProductionAsset APIスキーマ完全準拠（status=readyや欠落フィールドは
            # 一覧APIを500にし部屋ごと開けなくした実績あり — 全フィールド明示）
            "id": aid, "room_id": ROOM_ID, "kind": "image", "source_type": source_type,
            "original_uri": str(dest.resolve()),
            "local_path": str(dest.resolve()), "filename": filename_hint or dest.name,
            "proxy_path": None, "proxy_url": None,
            "thumbnail_path": None, "thumbnail_url": None,
            "status": "proxy_ready", "metadata": {**_media_dims(dest),**(metadata or {})},
            "created_at": now, "updated_at": now,
            "generated_by": f"agent:{JOB_ID}",
        })
        p.write_text(json.dumps(data, ensure_ascii=False), encoding="utf-8")
    _track_asset(draft, aid)


def _register_media_asset(draft: dict, aid: str, dest: Path, kind: str,
                          filename_hint: str = "", metadata: dict | None = None) -> None:
    with td.ContentsLock(ROOM_ID):
        p = _room_dir() / "assets.json"
        data = json.loads(p.read_text(encoding="utf-8")) if p.exists() else []
        from datetime import datetime, timezone
        now = datetime.now(timezone.utc).isoformat()
        data.append({
            "id": aid, "room_id": ROOM_ID, "kind": kind, "source_type": "agent_workspace",
            "original_uri": str(dest.resolve()), "local_path": str(dest.resolve()),
            "filename": filename_hint or dest.name, "proxy_path": None, "proxy_url": None,
            "thumbnail_path": None, "thumbnail_url": None, "status": "ready",
            "metadata": {**(_media_dims(dest) if kind == "video" else {}), **(metadata or {})},
            "created_at": now, "updated_at": now,
            "generated_by": f"agent:{JOB_ID}",
        })
        p.write_text(json.dumps(data, ensure_ascii=False), encoding="utf-8")
    _track_asset(draft, aid)


async def main():
    async with stdio_server() as (read, write):
        await app.run(read, write, app.create_initialization_options())


if __name__ == "__main__":
    import asyncio
    if not ROOM_ID or not DRAFT_ID:
        print("DAN_ROOM_ID / DAN_DRAFT_ID required", file=sys.stderr)
        sys.exit(2)
    asyncio.run(main())
