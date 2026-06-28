#!/usr/bin/env bash
# Launch the PoC-2 overlay app. Sets GStreamer env (inherited by the spawned GES player)
# and the POC2_* vars the Rust shell uses to spawn the player.
set -e
GST="/c/Users/Owner/gstreamer-poc"
PY39="/c/Users/Owner/AppData/Local/Programs/Python/Python39/python.exe"
HERE="$(cd "$(dirname "$0")" && pwd)"
C="D:/done/uploads/production-assets/bd05fcc0-c143-4d1c-828e-7624e087b6c1"

export PATH="$GST/bin:$PATH"
export PYTHONPATH="$GST/lib/site-packages"
export GI_TYPELIB_PATH="$GST/lib/girepository-1.0"
export GST_PLUGIN_PATH="$GST/lib/gstreamer-1.0"
export GST_REGISTRY="$GST/registry.bin"
export GST_PLUGIN_FEATURE_RANK="d3d11h264dec:512,nvh264dec:300"

# Windows-style path for python launched by the Rust process:
export POC2_PY39="C:/Users/Owner/AppData/Local/Programs/Python/Python39/python.exe"
export POC2_SCRIPT="$(cygpath -w "$HERE/../poc2_player.py")"
export POC2_CONTENT="$C/contents.json"
export POC2_ASSETS="$C"
echo "player script: $POC2_SCRIPT"

exec "$HERE/target/debug/poc2_overlay.exe"
