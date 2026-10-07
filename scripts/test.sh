#!/bin/bash
set -euo pipefail
cd "$(dirname "$0")/.."

source /Users/tianli/Dev/tools/dev/lib/tools/macapp/xcode_env.sh
xcode_env_use macosx
mkdir -p build/lifecycle
# The app executable itself, from the same sources as the Xcode target: tests/test_lifecycle_cli.py drives its
# command entry (config, update, shortcuts, login, automation, cancel) in an isolated copy with a test bundle
# identifier, a PhotoDesk.Test.* preferences domain and temporary folders. No window, no Dock icon, no input.
xcrun swiftc -parse-as-library -O -target arm64-apple-macos15.0 Sources/*.swift Sources/Shared/*.swift \
  -o build/lifecycle/PhotoDesk
PHOTODESK_NATIVE="$PWD/build/lifecycle/PhotoDesk" uv run python -m unittest discover -s tests

xcrun swiftc \
  Sources/Models.swift Sources/BackendClient.swift Sources/ViewModel.swift \
  Sources/ProductControls.swift tests/product_controls.swift \
  -o build/accept-product-controls

# The checker uses fake hotkey registration and removes this isolated preference
# domain on exit. It never launches a window or synthesizes user input.
suite="PhotoDesk.Test.ProductControls.$(/usr/bin/uuidgen)"
# removePersistentDomain leaves an empty plist behind; drop it with the domain.
trap 'defaults delete "$suite" >/dev/null 2>&1 || true; rm -f "$HOME/Library/Preferences/$suite.plist"' EXIT
PHOTODESK_PREFERENCES_SUITE="$suite" build/accept-product-controls
