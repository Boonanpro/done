"""Run native voice transport tests without a handset, live calls, or API traffic."""
from __future__ import annotations

import argparse
import json
import os
from pathlib import Path
import re
import shutil
import subprocess
import time
import zipfile

ROOT = Path(__file__).resolve().parents[1]
TESTS = ("DanPcmQueueTest", "DanExternalAudioTest", "DanAtomSocketTest", "DanAudioLeaseTest")


def main() -> None:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--java-home", default=os.environ.get("JAVA_HOME"))
    parser.add_argument("--android-sdk", default=os.environ.get("ANDROID_HOME") or os.environ.get("ANDROID_SDK_ROOT"))
    args = parser.parse_args()
    java_home = Path(args.java_home) if args.java_home else None
    suffix = ".exe" if os.name == "nt" else ""
    javac = str(java_home / "bin" / ("javac" + suffix)) if java_home else shutil.which("javac")
    java = str(java_home / "bin" / ("java" + suffix)) if java_home else shutil.which("java")
    if not javac or not java:
        parser.error("Set JAVA_HOME or pass --java-home pointing to a JDK.")
    sdk = Path(args.android_sdk) if args.android_sdk else Path(os.environ.get("LOCALAPPDATA", "")) / "Android/Sdk"
    platforms = [p for p in (sdk / "platforms").glob("android-*") if p.name[8:].isdigit() and (p / "android.jar").exists()]
    if not platforms:
        parser.error("No Android platform jar; pass --android-sdk.")
    android_jar = max(platforms, key=lambda p: int(p.name[8:])) / "android.jar"
    plugin = (ROOT / "mobile/plugins/withDanVoiceCall.js").read_text(encoding="utf-8")
    match = re.search(r"io\.github\.webrtc-sdk:android:([\d.]+)", plugin)
    if not match:
        parser.error("Cannot find the pinned WebRTC version in withDanVoiceCall.js.")
    version = match.group(1)
    gradle = Path(os.environ.get("GRADLE_USER_HOME", str(Path.home() / ".gradle")))
    artifacts = list((gradle / "caches/modules-2/files-2.1/io.github.webrtc-sdk/android" / version).glob("*/*.aar"))
    if len(artifacts) != 1:
        parser.error("Expected one cached pinned WebRTC AAR. Resolve Android dependencies first.")
    work = ROOT / ".tmp/native-voice-tests"
    work.mkdir(parents=True, exist_ok=True)
    with zipfile.ZipFile(artifacts[0]) as archive:
        (work / "webrtc-classes.jar").write_bytes(archive.read("classes.jar"))
    classes = work / "classes"
    classes.mkdir(exist_ok=True)
    classpath = os.pathsep.join(map(str, (work / "webrtc-classes.jar", android_jar)))
    sources = [ROOT / "mobile/native/voice" / (name + ".java")
               for name in ("DanPcmQueue", "DanExternalAudio", "DanAtomSocket", "DanAudioLease")]
    sources += [ROOT / "tests/native" / (name + ".java") for name in TESTS]
    # Remove a previous report so a failed run cannot leave a stale green report.
    report = work / "report.json"
    report.unlink(missing_ok=True)
    subprocess.run([javac, "-classpath", classpath, "-d", str(classes), *map(str, sources)], check=True, timeout=60)
    results = []
    for name in TESTS:
        started = time.monotonic()
        result = subprocess.run([java, "-cp", str(classes) + os.pathsep + classpath, name],
                                check=True, timeout=20, capture_output=True, text=True)
        print(result.stdout.strip(), flush=True)
        results.append({"test": name, "passed": True, "seconds": round(time.monotonic() - started, 3)})
    report.write_text(json.dumps({"scope": "JVM and localhost TCP simulator; no handset/audio acceptance",
                                 "webrtc_version": version, "tests": results}, indent=2) + "\n", encoding="utf-8")
    print(f"Report: {report}")


if __name__ == "__main__":
    main()
