"""
DaVinci Resolve 提案動画テンプレート

HP制作の提案動画を自動生成する。
構成：タイトル → 課題 → 解決策 → 完成イメージ → 料金 → CTA

Python 3.13専用（davinci_worker.py経由で呼ばれる）
"""
import sys
import os
import time

# Resolve接続
os.add_dll_directory(r"C:\Program Files\Blackmagic Design\DaVinci Resolve")
sys.path.insert(0, r"C:\ProgramData\Blackmagic Design\DaVinci Resolve\Support\Developer\Scripting\Modules")
import DaVinciResolveScript as dvr


def build_proposal_video(data: dict, output_dir: str) -> dict:
    """
    提案動画を生成する。

    data = {
        "company_name": "株式会社ABC",
        "project_title": "ホームページ制作のご提案",
        "problems": ["既存サイトが古い", "スマホ未対応", "問い合わせが少ない"],
        "solutions": ["モダンなデザイン", "レスポンシブ対応", "お問い合わせ導線強化"],
        "price": "30万円（税別）",
        "cta_text": "まずはお気軽にご相談ください",
        "cta_contact": "info@example.com",
        "images": [],        # 完成イメージ画像パス（オプション）
        "bgm_path": None,    # BGMファイルパス（オプション）
    }
    """
    resolve = dvr.scriptapp("Resolve")
    if not resolve:
        return {"ok": False, "error": "Resolve not connected"}

    pm = resolve.GetProjectManager()

    # プロジェクト作成
    project_name = f"提案_{data['company_name']}_{int(time.time())}"
    proj = pm.CreateProject(project_name)
    if not proj:
        return {"ok": False, "error": f"Project creation failed: {project_name}"}

    proj.SetSetting("timelineResolutionWidth", "1920")
    proj.SetSetting("timelineResolutionHeight", "1080")
    proj.SetSetting("timelineFrameRate", "30")

    mp = proj.GetMediaPool()
    tl = mp.CreateEmptyTimeline("Proposal")
    resolve.OpenPage("edit")
    time.sleep(1)

    fps = 30

    # --- シーン構成 ---
    scenes = []

    # 1. タイトル（4秒）
    scenes.append({
        "type": "title",
        "text": data["company_name"],
        "subtext": data.get("project_title", ""),
        "size": 0.12,
        "color": {"r": 1.0, "g": 1.0, "b": 1.0},
        "bg_color": {"r": 0.08, "g": 0.15, "b": 0.30},
        "duration_sec": 4,
    })

    # 2. 課題（各3秒）
    problems = data.get("problems", [])
    if problems:
        # 課題ヘッダー
        scenes.append({
            "type": "title",
            "text": "現状の課題",
            "size": 0.10,
            "color": {"r": 1.0, "g": 0.85, "b": 0.3},
            "bg_color": {"r": 0.15, "g": 0.08, "b": 0.08},
            "duration_sec": 2,
        })
        for i, problem in enumerate(problems):
            scenes.append({
                "type": "title",
                "text": f"❌ {problem}",
                "size": 0.07,
                "color": {"r": 1.0, "g": 0.9, "b": 0.9},
                "bg_color": {"r": 0.15, "g": 0.08, "b": 0.08},
                "duration_sec": 3,
            })

    # 3. 解決策（各3秒）
    solutions = data.get("solutions", [])
    if solutions:
        scenes.append({
            "type": "title",
            "text": "解決策",
            "size": 0.10,
            "color": {"r": 0.3, "g": 1.0, "b": 0.6},
            "bg_color": {"r": 0.05, "g": 0.15, "b": 0.10},
            "duration_sec": 2,
        })
        for solution in solutions:
            scenes.append({
                "type": "title",
                "text": f"✅ {solution}",
                "size": 0.07,
                "color": {"r": 0.9, "g": 1.0, "b": 0.95},
                "bg_color": {"r": 0.05, "g": 0.15, "b": 0.10},
                "duration_sec": 3,
            })

    # 4. 完成イメージ（画像があれば各5秒）
    images = data.get("images", [])
    if images:
        scenes.append({
            "type": "title",
            "text": "完成イメージ",
            "size": 0.10,
            "color": {"r": 1.0, "g": 1.0, "b": 1.0},
            "bg_color": {"r": 0.10, "g": 0.10, "b": 0.20},
            "duration_sec": 2,
        })
        for img_path in images:
            scenes.append({
                "type": "image",
                "path": img_path,
                "duration_sec": 5,
                "zoom": 1.05,  # 微妙なズームで動きを出す
            })

    # 5. 料金（4秒）
    if data.get("price"):
        scenes.append({
            "type": "title",
            "text": "お見積り",
            "subtext": data["price"],
            "size": 0.10,
            "color": {"r": 1.0, "g": 1.0, "b": 1.0},
            "bg_color": {"r": 0.15, "g": 0.10, "b": 0.25},
            "duration_sec": 4,
        })

    # 6. CTA（4秒）
    cta_text = data.get("cta_text", "お気軽にご相談ください")
    cta_contact = data.get("cta_contact", "")
    scenes.append({
        "type": "title",
        "text": cta_text,
        "subtext": cta_contact,
        "size": 0.08,
        "color": {"r": 1.0, "g": 1.0, "b": 1.0},
        "bg_color": {"r": 0.08, "g": 0.15, "b": 0.30},
        "duration_sec": 4,
    })

    # --- シーン構築 ---
    for i, scene in enumerate(scenes):
        if scene["type"] == "title":
            _insert_title_scene(tl, comp_ref=None, resolve=resolve, scene=scene, fps=fps)
        elif scene["type"] == "image":
            _insert_image_scene(mp, tl, scene, fps)

    # --- BGM ---
    bgm_path = data.get("bgm_path")
    if bgm_path and os.path.exists(bgm_path):
        clips = mp.ImportMedia([os.path.abspath(bgm_path)])
        if clips:
            mp.AppendToTimeline([{"mediaPoolItem": clips[0], "mediaType": 2}])

    # --- レンダリング ---
    resolve.OpenPage("deliver")
    time.sleep(0.5)
    os.makedirs(output_dir, exist_ok=True)

    filename = f"proposal_{data['company_name']}"
    proj.SetCurrentRenderFormatAndCodec("MP4", "H264_NVIDIA")
    if not proj.SetCurrentRenderFormatAndCodec("MP4", "H264_NVIDIA"):
        proj.SetCurrentRenderFormatAndCodec("MP4", "H264")

    proj.SetRenderSettings({
        "SelectAllFrames": True,
        "TargetDir": output_dir,
        "CustomName": filename,
    })

    job_id = proj.AddRenderJob()
    if not job_id:
        return {"ok": False, "error": "Failed to add render job"}

    proj.StartRendering(job_id)
    while proj.IsRenderingInProgress():
        time.sleep(0.5)

    status = proj.GetRenderJobStatus(job_id)
    output_files = [f for f in os.listdir(output_dir) if f.startswith(filename)]

    return {
        "ok": True,
        "project_name": project_name,
        "render_status": status,
        "output_dir": output_dir,
        "files": output_files,
        "scene_count": len(scenes),
    }


def _insert_title_scene(tl, comp_ref, resolve, scene, fps):
    """テキストシーンをタイムラインに挿入"""
    item = tl.InsertFusionTitleIntoTimeline("Text+")
    if not item:
        return

    time.sleep(0.8)
    comp = item.GetFusionCompByIndex(1)
    if not comp:
        return

    tools = comp.GetToolList(False)

    # テキスト設定
    for tid, tool in tools.items():
        if tool.GetAttrs()["TOOLS_RegID"] == "TextPlus":
            tool.SetInput("Font", "Yu Gothic UI")

            # メインテキスト
            text = scene.get("text", "")
            subtext = scene.get("subtext", "")
            if subtext:
                tool.SetInput("StyledText", f"{text}\n\n{subtext}")
            else:
                tool.SetInput("StyledText", text)

            tool.SetInput("Size", scene.get("size", 0.08))

            color = scene.get("color", {"r": 1.0, "g": 1.0, "b": 1.0})
            tool.SetInput("Red1", color["r"])
            tool.SetInput("Green1", color["g"])
            tool.SetInput("Blue1", color["b"])
            break


def _insert_image_scene(mp, tl, scene, fps):
    """画像シーンをタイムラインに挿入"""
    path = scene["path"]
    if not os.path.exists(path):
        return

    clips = mp.ImportMedia([os.path.abspath(path)])
    if not clips:
        return

    duration = scene.get("duration_sec", 5) * fps
    result = mp.AppendToTimeline([{
        "mediaPoolItem": clips[0],
        "startFrame": 0,
        "endFrame": duration - 1,
    }])

    # ズーム効果
    if result and scene.get("zoom"):
        item = result[0]
        item.SetProperty("ZoomX", scene["zoom"])
        item.SetProperty("ZoomY", scene["zoom"])


if __name__ == "__main__":
    import json

    raw = sys.stdin.read()
    request = json.loads(raw)
    data = request.get("data", {})
    output_dir = request.get("output_dir", os.path.join(os.environ.get("TEMP", "."), "davinci_proposal"))

    result = build_proposal_video(data, output_dir)
    print(json.dumps(result, ensure_ascii=False))
