#!/usr/bin/env python3
"""Run the application's offscreen self-test; never send user input."""
import hashlib
import json
import subprocess

from _common import APP, OUT, fixture, report, require


def main():
    executable = APP / "Contents/MacOS/PhotoDesk"
    require(executable.is_file(), "Build first: bash build.sh --no-install")
    # Launch safety only: an old binary would ignore the flag and open its normal
    # UI. Actual acceptance still comes solely from the in-process assertions.
    require(b"PhotoDesk.UISelfTest" in executable.read_bytes(),
            "App predates the isolated UI entry; rebuild: bash build.sh --no-install")
    output = (OUT / "native-ui").resolve()
    output.mkdir(parents=True, exist_ok=True)
    (output / "ui-self-test.json").unlink(missing_ok=True)
    with fixture("native-ui") as (root, env):
        env["PHOTODESK_LIBRARY"] = str(root)
        env["PHOTODESK_UI_TEST_OUTPUT"] = str(output)
        result = subprocess.run([str(executable), "--ui-self-test"], env=env, cwd="/",
                                capture_output=True, text=True, timeout=120)
        require(result.returncode == 0, f"Native self-test exit {result.returncode}: {result.stderr[-3000:]} {result.stdout[-3000:]}")
        detail = json.loads((output / "ui-self-test.json").read_text())
        require(detail["ok"], "App reported a native UI assertion failure")
        for capture in detail["screenshots"]:
            image = output / capture["file"]
            require(image.read_bytes()[:8] == b"\x89PNG\r\n\x1a\n", "Missing actual PNG screenshot")
            require(image.stat().st_size == capture["bytes"], "Screenshot was not written completely")
            capture["file"] = "native-ui/" + image.name
            capture["sha256"] = hashlib.sha256(image.read_bytes()).hexdigest()
        report("native_ui", detail["checks"],
               "真实 SwiftUI 离屏渲染及模型动作通过：时间线选择、片段计数、预览关闭、设置自动保存与刷新。",
               counts=detail["counts"], screenshots=detail["screenshots"],
               scope=detail["scope"])


if __name__ == "__main__":
    main()
