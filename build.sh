#!/bin/bash
set -euo pipefail
source /Users/tianli/Dev/tools/dev/lib/tools/macapp/xcode_env.sh
xcode_env_use macosx
cd "$(dirname "$0")"
/opt/homebrew/bin/python3 /Users/tianli/Dev/tools/dev/lib/tools/macapp/check_codingkeys.py "$PWD"
python3 scripts/vendor_engine.py
if [[ "${SKIP_ENGINE_BUILD:-0}" != 1 ]]; then bash scripts/build_engine.sh; fi
ENGINE="${PHOTODESK_ENGINE_OUT:-build}/engine/photo-engine"
[[ -x "$ENGINE/photo-engine" ]]
uv run python scripts/collect_notices.py
DISPLAY_NAME="$(sed -n 's/^display_name: //p' project.yaml)"
# PHOTODESK_DERIVED_DATA / PHOTODESK_BUILD_LOG redirect the Xcode products and log for trial
# builds (with --no-install); release.py packages the default build/DerivedData.
DD="${PHOTODESK_DERIVED_DATA:-build/DerivedData}"
LOG="${PHOTODESK_BUILD_LOG:-build/xcodebuild.log}"
mkdir -p build "$DD" "$(dirname "$LOG")"
# Release strips the main executable's local symbols and debug map (strip -D -x after the dSYM
# next to the product is written, so crash symbolication still works); behaviour is unchanged.
# STRIP_SWIFT_SYMBOLS=NO: Xcode's default adds -T, which leaves ~2,700 local symbols
# (Objective-C methods, closures) that a later strip -x cannot remove either.
xcodebuild -project PhotoDesk.xcodeproj -scheme PhotoDesk -configuration Release \
  -derivedDataPath "$DD" CODE_SIGNING_ALLOWED=NO \
  DEPLOYMENT_POSTPROCESSING=YES STRIP_INSTALLED_PRODUCT=YES STRIP_STYLE=non-global STRIP_SWIFT_SYMBOLS=NO \
  build > "$LOG" 2>&1 || {
  tail -70 "$LOG"; exit 1;
}
APP="$(cd "$DD" && pwd)/Build/Products/Release/PhotoDesk.app"
RES="$APP/Contents/Resources"
mkdir -p "$RES"
if [[ -d "$RES/Engine" ]]; then
  OLD_ENGINE="$HOME/.Trash/photodesk-engine-$(date +%Y%m%d-%H%M%S)"
  mv "$RES/Engine" "$OLD_ENGINE"
fi
ditto "$ENGINE" "$RES/Engine"
uv run python scripts/compress_icon.py icon/AppIcon.icns "$RES/AppIcon.icns"
cp build/THIRD_PARTY_NOTICES.txt "$RES/THIRD_PARTY_NOTICES.txt"
plutil -replace CFBundleDisplayName -string "$DISPLAY_NAME" "$APP/Contents/Info.plist"
plutil -replace CFBundleName -string "$DISPLAY_NAME" "$APP/Contents/Info.plist"
plutil -replace CFBundleIconFile -string AppIcon "$APP/Contents/Info.plist"
BUILD_NUMBER="$(git rev-list --count HEAD 2>/dev/null || echo 1)"
plutil -replace CFBundleVersion -string "$BUILD_NUMBER" "$APP/Contents/Info.plist"
# Strip the bundled engine's .so/.dylib and fail if any Mach-O in the app keeps local symbols.
python3 scripts/strip_release.py "$APP"
codesign --force --deep -s - "$APP"
codesign --verify --deep --strict "$APP"
if [[ "${1:-}" != --no-install ]]; then
  DEST="/Applications/$DISPLAY_NAME.app"
  if [[ -e "$DEST" ]]; then
    mv "$DEST" "$HOME/.Trash/PhotoDesk-$(date +%Y%m%d-%H%M%S).app"
  fi
  ditto "$APP" "$DEST"
  echo "已安装：$DEST"
fi
echo "构建完成：$APP"
