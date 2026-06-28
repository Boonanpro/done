#!/usr/bin/env bash
# Launcher: set GStreamer-bundled-gi env for Python 3.9, force HW H.264 decode rank.
set -e
GST="/c/Users/Owner/gstreamer-poc"
PY39="/c/Users/Owner/AppData/Local/Programs/Python/Python39/python.exe"
export PATH="$GST/bin:$PATH"
export PYTHONPATH="$GST/lib/site-packages"
export GI_TYPELIB_PATH="$GST/lib/girepository-1.0"
export GST_PLUGIN_PATH="$GST/lib/gstreamer-1.0"
export GST_REGISTRY="$GST/registry.bin"
# Prefer DXVA (d3d11) H.264 decode end-to-end (zero-copy with d3d11 sink), NVDEC as backup.
export GST_PLUGIN_FEATURE_RANK="d3d11h264dec:512,nvh264dec:300"
CONTENT="/d/done/uploads/production-assets/bd05fcc0-c143-4d1c-828e-7624e087b6c1/contents.json"
ASSETS="/d/done/uploads/production-assets/bd05fcc0-c143-4d1c-828e-7624e087b6c1"
exec "$PY39" "$(dirname "$0")/poc1.py" "$CONTENT" "$ASSETS" "$@"
