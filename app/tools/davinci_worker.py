"""
DaVinci Resolve ワーカースクリプト（Python 3.13専用）

親プロセス(Python 3.10)からsubprocessで呼ばれる。
stdinからJSON命令を受け取り、stdoutにJSON結果を返す。

使い方:
    echo '{"command":"connect","params":{}}' | python313 davinci_worker.py
"""
import sys
import os
import json
import time

# --- Resolve接続 ---

def _get_resolve():
    """DaVinci Resolveオブジェクトを取得"""
    os.add_dll_directory(r"C:\Program Files\Blackmagic Design\DaVinci Resolve")
    sys.path.insert(0, r"C:\ProgramData\Blackmagic Design\DaVinci Resolve\Support\Developer\Scripting\Modules")
    import DaVinciResolveScript as dvr
    resolve = dvr.scriptapp("Resolve")
    if resolve is None:
        raise ConnectionError(
            "DaVinci Resolveに接続できません。"
            "Resolveが起動していて、Preferences > System > General > "
            "External scripting using が 'Local' になっているか確認してください。"
        )
    return resolve


# --- コマンドハンドラ ---

def cmd_connect(resolve, params):
    return {
        "product": resolve.GetProductName(),
        "version": resolve.GetVersionString(),
        "current_page": resolve.GetCurrentPage(),
    }


def cmd_get_current_project(resolve, params):
    pm = resolve.GetProjectManager()
    proj = pm.GetCurrentProject()
    if proj is None:
        return {"name": None}
    return {
        "name": proj.GetName(),
        "timeline_count": proj.GetTimelineCount(),
        "fps": proj.GetSetting("timelineFrameRate"),
        "resolution": f"{proj.GetSetting('timelineResolutionWidth')}x{proj.GetSetting('timelineResolutionHeight')}",
    }


def cmd_create_project(resolve, params):
    name = params["name"]
    pm = resolve.GetProjectManager()

    project = pm.CreateProject(name)
    if project is None:
        # 同名プロジェクトが既に存在する場合はロードを試みる
        project = pm.LoadProject(name)
        if project is None:
            raise RuntimeError(f"プロジェクト '{name}' の作成・読み込みに失敗")
        return {"name": project.GetName(), "created": False}

    return {"name": project.GetName(), "created": True}


def cmd_create_timeline(resolve, params):
    pm = resolve.GetProjectManager()
    project = pm.GetCurrentProject()
    if project is None:
        raise RuntimeError("プロジェクトが開かれていません")

    # プロジェクト設定
    if "width" in params:
        project.SetSetting("timelineResolutionWidth", str(params["width"]))
    if "height" in params:
        project.SetSetting("timelineResolutionHeight", str(params["height"]))
    if "fps" in params:
        project.SetSetting("timelineFrameRate", str(params["fps"]))

    media_pool = project.GetMediaPool()
    timeline = media_pool.CreateEmptyTimeline(params["name"])
    if timeline is None:
        raise RuntimeError(f"タイムライン '{params['name']}' の作成に失敗")

    return {
        "name": timeline.GetName(),
        "fps": project.GetSetting("timelineFrameRate"),
        "resolution": f"{project.GetSetting('timelineResolutionWidth')}x{project.GetSetting('timelineResolutionHeight')}",
    }


def cmd_insert_title(resolve, params):
    pm = resolve.GetProjectManager()
    project = pm.GetCurrentProject()
    timeline = project.GetCurrentTimeline()
    if timeline is None:
        raise RuntimeError("タイムラインがありません")

    resolve.OpenPage("edit")
    time.sleep(1)

    # Fusion Title (Text+) を挿入
    title_item = timeline.InsertFusionTitleIntoTimeline("Text+")
    if title_item is None:
        raise RuntimeError("Text+ タイトルの挿入に失敗")

    # Fusion Compositionにアクセスしてテキストを設定
    time.sleep(1)
    comp = title_item.GetFusionCompByIndex(1)
    text_set = False
    if comp:
        tools = comp.GetToolList(False)
        for tool_id, tool in tools.items():
            if tool.GetAttrs()["TOOLS_RegID"] == "TextPlus":
                # フォント（日本語対応フォントをデフォルトに）
                font = params.get("font", "Yu Gothic UI")
                tool.SetInput("Font", font)
                # テキスト内容
                text = params.get("text", "")
                if text:
                    tool.SetInput("StyledText", text)
                # フォントサイズ
                if "font_size" in params:
                    tool.SetInput("Size", params["font_size"])
                # 文字色
                if "color" in params:
                    c = params["color"]
                    tool.SetInput("Red1", c.get("r", 1.0))
                    tool.SetInput("Green1", c.get("g", 1.0))
                    tool.SetInput("Blue1", c.get("b", 1.0))
                # 縦位置
                if "position_y" in params:
                    tool.SetInput("Center", {1: 0.5, 2: params["position_y"]})
                text_set = True
                break

    return {
        "name": title_item.GetName(),
        "duration": title_item.GetDuration(),
        "start": title_item.GetStart(),
        "end": title_item.GetEnd(),
        "text_set": text_set,
    }


def cmd_import_media(resolve, params):
    pm = resolve.GetProjectManager()
    project = pm.GetCurrentProject()
    media_pool = project.GetMediaPool()

    file_paths = params["file_paths"]
    # パスをWindowsネイティブパスに変換
    file_paths = [os.path.abspath(p) for p in file_paths]

    items = media_pool.ImportMedia(file_paths)
    if items is None or len(items) == 0:
        raise RuntimeError(f"メディアの読み込みに失敗: {file_paths}")

    return {
        "imported": [item.GetName() for item in items],
        "count": len(items),
    }


def cmd_append_to_timeline(resolve, params):
    pm = resolve.GetProjectManager()
    project = pm.GetCurrentProject()
    media_pool = project.GetMediaPool()
    timeline = project.GetCurrentTimeline()
    if timeline is None:
        raise RuntimeError("タイムラインがありません")

    # メディアプールのクリップを取得
    root = media_pool.GetRootFolder()
    clips = root.GetClipList()
    if not clips:
        raise RuntimeError("メディアプールにクリップがありません")

    # 特定のクリップ名が指定されていればフィルタ
    clip_names = params.get("clip_names")
    if clip_names:
        clips = [c for c in clips if c.GetName() in clip_names]
        if not clips:
            raise RuntimeError(f"指定されたクリップが見つかりません: {clip_names}")

    result = media_pool.AppendToTimeline(clips)
    if result is None:
        raise RuntimeError("タイムラインへの追加に失敗")

    return {
        "appended": len(result) if result else 0,
    }


def cmd_render(resolve, params):
    pm = resolve.GetProjectManager()
    project = pm.GetCurrentProject()

    resolve.OpenPage("deliver")
    time.sleep(0.5)

    output_dir = params["output_dir"]
    os.makedirs(output_dir, exist_ok=True)

    # フォーマット設定
    fmt = params.get("format", "mp4")
    format_map = {"mp4": "MP4", "mov": "QuickTime", "mkv": "MKV"}
    # NVIDIA GPUエンコードを優先（高速）、なければソフトウェア
    codec_map = {"mp4": "H264_NVIDIA", "mov": "H264_NVIDIA", "mkv": "H264_NVIDIA"}
    render_fmt = format_map.get(fmt, "MP4")
    render_codec = codec_map.get(fmt, "H264_NVIDIA")

    if not project.SetCurrentRenderFormatAndCodec(render_fmt, render_codec):
        # NVIDIA非対応ならソフトウェアH.264にフォールバック
        project.SetCurrentRenderFormatAndCodec(render_fmt, "H264")

    settings = {
        "SelectAllFrames": True,
        "TargetDir": output_dir,
        "CustomName": params.get("filename", "output"),
    }
    if "width" in params:
        settings["FormatWidth"] = str(params["width"])
    if "height" in params:
        settings["FormatHeight"] = str(params["height"])

    project.SetRenderSettings(settings)

    job_id = project.AddRenderJob()
    if not job_id:
        raise RuntimeError("レンダージョブの追加に失敗（タイムラインが空の可能性）")

    # レンダリング実行
    started = project.StartRendering(job_id)
    if not started:
        raise RuntimeError("レンダリングの開始に失敗")

    # 完了待ち
    while project.IsRenderingInProgress():
        time.sleep(0.5)

    status = project.GetRenderJobStatus(job_id)
    completion = status.get("CompletionPercentage", 0)
    time_ms = status.get("TimeTakenToRenderInMs", 0)

    # 出力ファイルを探す
    output_files = []
    if os.path.isdir(output_dir):
        output_files = [f for f in os.listdir(output_dir)
                       if f.startswith(params.get("filename", "output"))]

    return {
        "status": "completed" if completion == 100 else "failed",
        "completion": completion,
        "render_time_ms": time_ms,
        "output_dir": output_dir,
        "files": output_files,
    }


def cmd_close_project(resolve, params):
    pm = resolve.GetProjectManager()
    project = pm.GetCurrentProject()
    if project is None:
        return {"closed": False, "reason": "no project open"}

    name = project.GetName()
    pm.SaveProject()
    pm.CloseProject(project)

    if params.get("delete"):
        deleted = pm.DeleteProject(name)
        return {"closed": True, "deleted": deleted, "name": name}

    return {"closed": True, "name": name}


# --- ディスパッチャ ---

COMMANDS = {
    "connect": cmd_connect,
    "get_current_project": cmd_get_current_project,
    "create_project": cmd_create_project,
    "create_timeline": cmd_create_timeline,
    "insert_title": cmd_insert_title,
    "import_media": cmd_import_media,
    "append_to_timeline": cmd_append_to_timeline,
    "render": cmd_render,
    "close_project": cmd_close_project,
}


def main():
    # Windows環境でstdinの日本語が化けないようにUTF-8を強制
    if sys.platform.startswith("win"):
        sys.stdin.reconfigure(encoding="utf-8")
        sys.stdout.reconfigure(encoding="utf-8")
    raw = sys.stdin.read()
    try:
        request = json.loads(raw)
    except json.JSONDecodeError as e:
        print(json.dumps({"ok": False, "error": f"Invalid JSON: {e}"}))
        return

    command = request.get("command")
    params = request.get("params", {})

    if command not in COMMANDS:
        print(json.dumps({"ok": False, "error": f"Unknown command: {command}"}))
        return

    try:
        resolve = _get_resolve()
        result = COMMANDS[command](resolve, params)
        print(json.dumps({"ok": True, "data": result}, ensure_ascii=False))
    except Exception as e:
        print(json.dumps({"ok": False, "error": f"{type(e).__name__}: {e}"}, ensure_ascii=False))


if __name__ == "__main__":
    main()
