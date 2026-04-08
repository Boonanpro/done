"""
DaVinci Resolve Python API フルテスト
- Resolve接続
- プロジェクト作成
- タイムライン作成
- タイトル挿入
- レンダリング設定 & 実行
"""
import sys
import os
import time

# DaVinci Resolve セットアップ
os.add_dll_directory(r'C:\Program Files\Blackmagic Design\DaVinci Resolve')
sys.path.insert(0, r'C:\ProgramData\Blackmagic Design\DaVinci Resolve\Support\Developer\Scripting\Modules')

print("=" * 60)
print("DaVinci Resolve API フルテスト")
print("=" * 60)

# Step 1: 接続
print("\n[1] Resolve に接続中...")
import DaVinciResolveScript as dvr
resolve = dvr.scriptapp("Resolve")
if resolve is None:
    print("  FAIL: resolve is None")
    sys.exit(1)
print(f"  OK: {resolve.GetProductName()} {resolve.GetVersionString()}")

# Step 2: テストプロジェクト作成
print("\n[2] テストプロジェクト作成...")
pm = resolve.GetProjectManager()
test_name = "_API_TEST_" + time.strftime("%Y%m%d_%H%M%S")

project = pm.CreateProject(test_name)
if project is None:
    print(f"  FAIL: CreateProject({test_name})")
    sys.exit(1)
print(f"  OK: {project.GetName()}")

# Step 3: タイムライン作成
print("\n[3] タイムライン作成...")
media_pool = project.GetMediaPool()
timeline = media_pool.CreateEmptyTimeline("TestTimeline")
if timeline is None:
    print("  FAIL: CreateEmptyTimeline")
    sys.exit(1)
print(f"  OK: {timeline.GetName()}")

# Step 4: テキスト(タイトル)挿入
print("\n[4] タイトル挿入...")
resolve.OpenPage("edit")
time.sleep(1)

title_item = timeline.InsertFusionTitleIntoTimeline("Text+")
if title_item is None:
    print("  WARN: Fusion Title 'Text+' failed, trying 'Text'...")
    title_item = timeline.InsertTitleIntoTimeline("Text")
if title_item is None:
    print("  WARN: Title 'Text' failed, trying generator...")
    title_item = timeline.InsertGeneratorIntoTimeline("Solid Color")

if title_item:
    print(f"  OK: inserted (duration={title_item.GetDuration()})")
    track_count = timeline.GetTrackCount("video")
    items = timeline.GetItemListInTrack("video", 1)
    print(f"  Video tracks: {track_count}, items on track 1: {len(items) if items else 0}")
else:
    print("  FAIL: no title/generator could be inserted")

# Step 5: レンダリング設定
print("\n[5] レンダリング設定...")
resolve.OpenPage("deliver")
time.sleep(1)

output_dir = os.path.join(os.environ.get("TEMP", r"C:\Temp"), "davinci_test")
os.makedirs(output_dir, exist_ok=True)

project.SetRenderSettings({
    "SelectAllFrames": True,
    "TargetDir": output_dir,
    "CustomName": "api_test_output",
})

current_fmt = project.GetCurrentRenderFormatAndCodec()
print(f"  Format: {current_fmt}")

job_id = project.AddRenderJob()
if job_id:
    print(f"  OK: render job {job_id}")

    # Step 6: レンダリング実行
    print("\n[6] レンダリング...")
    started = project.StartRendering(job_id)
    print(f"  StartRendering: {started}")

    if started:
        while project.IsRenderingInProgress():
            status = project.GetRenderJobStatus(job_id)
            pct = status.get("CompletionPercentage", "?")
            print(f"  {pct}%", end="\r", flush=True)
            time.sleep(0.5)
        final = project.GetRenderJobStatus(job_id)
        print(f"\n  Done: {final}")
        files = os.listdir(output_dir)
        print(f"  Output: {files}")
    else:
        print("  FAIL: rendering did not start")
else:
    print("  FAIL: AddRenderJob (timeline may be empty)")

# Step 7: クリーンアップ
print("\n[7] クリーンアップ...")
pm.CloseProject(project)
deleted = pm.DeleteProject(test_name)
print(f"  Project deleted: {deleted}")

print("\n" + "=" * 60)
print("テスト完了!")
print("=" * 60)
