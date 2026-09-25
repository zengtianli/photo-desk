#!/bin/bash
# 构建本轮源码到 build/perf-next（不装机、不动 dist/ 与 build/DerivedData）；引擎沿用与发布版相同哈希的 build/engine/photo-engine
set -euo pipefail
cd ~/Apps/photo-desk
source ~/Dev/tools/dev/lib/tools/macapp/xcode_env.sh
xcode_env_use macosx
/opt/homebrew/bin/python3 ~/Dev/tools/dev/lib/tools/macapp/check_codingkeys.py "$PWD"
OUT=build/perf-next
mkdir -p $OUT
xcodebuild -project PhotoDesk.xcodeproj -scheme PhotoDesk -configuration Release \
  -derivedDataPath $OUT/DerivedData CODE_SIGNING_ALLOWED=NO build > $OUT/xcodebuild.log 2>&1 || { tail -70 $OUT/xcodebuild.log; exit 1; }
SRC="$PWD/$OUT/DerivedData/Build/Products/Release/PhotoDesk.app"
APP="$PWD/$OUT/PhotoDesk.app"
rm -rf "$APP"
ditto "$SRC" "$APP"
RES="$APP/Contents/Resources"; mkdir -p "$RES"
ditto build/engine/photo-engine "$RES/Engine"
cp icon/AppIcon.icns "$RES/AppIcon.icns"
cp build/THIRD_PARTY_NOTICES.txt "$RES/THIRD_PARTY_NOTICES.txt"
DISPLAY_NAME="$(sed -n 's/^display_name: //p' project.yaml)"
plutil -replace CFBundleDisplayName -string "$DISPLAY_NAME" "$APP/Contents/Info.plist"
plutil -replace CFBundleName -string "$DISPLAY_NAME" "$APP/Contents/Info.plist"
plutil -replace CFBundleIconFile -string AppIcon "$APP/Contents/Info.plist"
plutil -replace CFBundleVersion -string "$(git rev-list --count HEAD)" "$APP/Contents/Info.plist"
codesign --force --deep -s - "$APP"
codesign --verify --deep --strict "$APP"
echo "构建完成：$APP"
