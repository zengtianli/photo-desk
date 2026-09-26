#!/bin/bash
set -euo pipefail
cd "$(dirname "$0")/.."
uv sync --locked --group build
python3 scripts/vendor_engine.py
# PHOTODESK_ENGINE_OUT (default build) puts engine/, pyinstaller/ and the spec elsewhere for trial builds.
OUT="${PHOTODESK_ENGINE_OUT:-build}"
uv run --group build python -m PyInstaller --noconfirm --name photo-engine --onedir \
  --distpath "$OUT/engine" --workpath "$OUT/pyinstaller" --specpath "$OUT" \
  --paths "$PWD/vendor" --add-data "$PWD/backend/defaults.yaml":. \
  --collect-all osxphotos --collect-all photoscript --collect-all ocrmac \
  --collect-all applescript --collect-data osxmetadata --collect-all utitools \
  --collect-data cgmetadata --collect-data rich_theme_manager --collect-data makelive \
  --collect-all bitstring --collect-all bitarray \
  --hidden-import Vision --hidden-import CoreML --hidden-import Photos \
  --recursive-copy-metadata osxphotos --copy-metadata ocrmac \
  backend/bridge.py
