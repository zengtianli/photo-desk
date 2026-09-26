#!/usr/bin/env python3
"""Strip release symbols from the bundled engine and check the whole app (called by build.sh before signing).

    strip_release.py <PhotoDesk.app>           strip Contents/Resources/Engine, then check every Mach-O
    strip_release.py <PhotoDesk.app> --check   only check; exits non-zero if symbols remain

Main executable: Xcode strips it (build.sh passes DEPLOYMENT_POSTPROCESSING=YES
STRIP_INSTALLED_PRODUCT=YES STRIP_STYLE=non-global; the dSYM next to the product keeps crash
symbolication). This script only checks it.

Engine: PyInstaller copies libpython and every extension module (.so/.dylib) with their local
symbols and debug map. `strip -x` removes those from the bundle copy only (build/.../engine stays
as PyInstaller left it); exported symbols such as PyInit_* and the Py* API stay, so loading is
unchanged. strip invalidates the ad-hoc signatures PyInstaller made, so each file is re-signed
(arm64 will not run unsigned code). The photo-engine bootloader is not touched: its archive sits
inside __LINKEDIT and it has no local symbols.

Fail-closed: any Mach-O in the app that still has a local symbol (nm type t/d/b/s) or a debug
entry (type '-', except strip's own radr://5614542 marker) stops the build.
"""
from pathlib import Path
import subprocess
import sys

MACHO = {b"\xcf\xfa\xed\xfe", b"\xce\xfa\xed\xfe", b"\xca\xfe\xba\xbe", b"\xfe\xed\xfa\xcf"}


def macho_files(root):
    for path in sorted(root.rglob("*")):
        if path.is_symlink() or not path.is_file():
            continue
        with path.open("rb") as handle:
            if handle.read(4) in MACHO:
                yield path


def leftover(path):
    """Count local and debug symbols. nm's default format puts the type letter in column 18
    (names can contain spaces, so the line is not split)."""
    local = debug = 0
    listing = subprocess.run(["nm", "-a", str(path)], capture_output=True, text=True, check=True).stdout
    for line in listing.splitlines():
        if len(line) < 19 or line[16] != " " or line[18] != " ":
            continue
        kind = line[17]
        if kind in "tdbs":
            local += 1
        elif kind == "-" and "radr://5614542" not in line:
            debug += 1
    return local, debug


def main():
    app = Path(sys.argv[1]).resolve()
    check_only = "--check" in sys.argv[2:]
    engine = app / "Contents/Resources/Engine"
    bootloader = engine / "photo-engine"
    if not bootloader.is_file():
        raise SystemExit(f"strip_release: bundled engine missing: {bootloader}")
    if not check_only:
        saved = 0
        for path in macho_files(engine):
            if path == bootloader:
                continue
            before = path.stat().st_size
            subprocess.run(["strip", "-x", "-no_code_signature_warning", str(path)], check=True, capture_output=True)
            subprocess.run(["codesign", "--force", "--sign", "-", str(path)], check=True, capture_output=True)
            saved += before - path.stat().st_size
        print(f"strip_release: engine {saved:,} bytes of local symbols removed")
    dirty = []
    for path in macho_files(app):
        local, debug = leftover(path)
        if local or debug:
            dirty.append(f"{path.relative_to(app)}: {local} local, {debug} debug")
    if dirty:
        raise SystemExit("strip_release: symbols left in the release bundle:\n  " + "\n  ".join(dirty))
    print("strip_release: no local or debug symbols in any Mach-O of the bundle")


if __name__ == "__main__":
    main()
