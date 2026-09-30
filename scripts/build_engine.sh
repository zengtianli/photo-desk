#!/bin/bash
set -euo pipefail
cd "$(dirname "$0")/.."
uv sync --locked --group build
# PHOTODESK_ENGINE_OUT (default build) puts engine/, pyinstaller/ and the spec elsewhere for trial builds.
OUT="${PHOTODESK_ENGINE_OUT:-build}"
uv run --group build python -m PyInstaller --noconfirm --name photo-engine --onedir \
  --distpath "$OUT/engine" --workpath "$OUT/pyinstaller" --specpath "$OUT" \
  --add-data "$PWD/backend/defaults.yaml":. \
  --hidden-import photocli.cli --hidden-import photocli.backup \
  --hidden-import photocli.dedup --hidden-import photocli.shared \
  --hidden-import desk_cli --hidden-import preferences --hidden-import journey \
  --hidden-import CoreFoundation --hidden-import Foundation \
  --collect-all osxphotos --collect-all photoscript --collect-all ocrmac \
  --collect-all applescript --collect-data osxmetadata --collect-all utitools \
  --collect-data cgmetadata --collect-data rich_theme_manager --collect-data makelive \
  --collect-all bitstring --collect-all bitarray \
  --hidden-import Vision --hidden-import CoreML --hidden-import Photos \
  --recursive-copy-metadata osxphotos --copy-metadata ocrmac \
  backend/bridge.py
