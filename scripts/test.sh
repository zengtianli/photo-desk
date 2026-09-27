#!/bin/bash
set -euo pipefail
cd "$(dirname "$0")/.."

uv run python -m unittest discover -s tests

source /Users/tianli/Dev/tools/dev/lib/tools/macapp/xcode_env.sh
xcode_env_use macosx
mkdir -p build
xcrun swiftc \
  Sources/Models.swift Sources/BackendClient.swift Sources/ViewModel.swift \
  Sources/ProductControls.swift tests/product_controls.swift \
  -o build/accept-product-controls

# The checker uses fake hotkey registration and removes this isolated preference
# domain on exit. It never launches a window or synthesizes user input.
PHOTODESK_PREFERENCES_SUITE="PhotoDesk.Test.ProductControls.$(/usr/bin/uuidgen)" \
  build/accept-product-controls
