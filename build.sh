#!/bin/bash
set -euo pipefail
source /Users/tianli/Dev/tools/dev/lib/tools/macapp/xcode_env.sh
xcode_env_use macosx
cd "$(dirname "$0")"
/opt/homebrew/bin/python3 /Users/tianli/Dev/tools/dev/lib/tools/macapp/check_codingkeys.py "$PWD"
python3 scripts/vendor_engine.py
if [[ "${SKIP_ENGINE_BUILD:-0}" != 1 ]]; then bash scripts/build_engine.sh; fi
[[ -x build/engine/photo-engine/photo-engine ]]
uv run python scripts/collect_notices.py
DISPLAY_NAME="$(sed -n 's/^display_name: //p' project.yaml)"
mkdir -p build
xcodebuild -project PhotoDesk.xcodeproj -scheme PhotoDesk -configuration Release \
  -derivedDataPath build/DerivedData CODE_SIGNING_ALLOWED=NO build > build/xcodebuild.log 2>&1 || {
  tail -70 build/xcodebuild.log; exit 1;
}
APP="$PWD/build/DerivedData/Build/Products/Release/PhotoDesk.app"
RES="$APP/Contents/Resources"
mkdir -p "$RES"
if [[ -d "$RES/Engine" ]]; then
  OLD_ENGINE="$HOME/.Trash/photodesk-engine-$(date +%Y%m%d-%H%M%S)"
  mv "$RES/Engine" "$OLD_ENGINE"
fi
ditto build/engine/photo-engine "$RES/Engine"
cp icon/AppIcon.icns "$RES/AppIcon.icns"
cp build/THIRD_PARTY_NOTICES.txt "$RES/THIRD_PARTY_NOTICES.txt"
plutil -replace CFBundleDisplayName -string "$DISPLAY_NAME" "$APP/Contents/Info.plist"
plutil -replace CFBundleName -string "$DISPLAY_NAME" "$APP/Contents/Info.plist"
plutil -replace CFBundleIconFile -string AppIcon "$APP/Contents/Info.plist"
BUILD_NUMBER="$(git rev-list --count HEAD 2>/dev/null || echo 1)"
plutil -replace CFBundleVersion -string "$BUILD_NUMBER" "$APP/Contents/Info.plist"
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
