#!/usr/bin/env python3
"""Check whether the recorded demo still shows the current app, without opening a window.

    uv run python scripts/media_reuse_check.py recorded=/path/A.app current=/path/B.app [--runs 2]

For every bundle, on fresh copies of the same synthetic demo inputs (scripts/prepare_demo.py):

1. `--ui-self-test`: the app renders its real SwiftUI views (timeline, selected fragment,
   preview, fragment detail, settings) into offscreen borderless windows with activation policy
   `.prohibited`; no input is sent and no window is shown. The PNG hashes are compared.
2. The bundled engine runs `journey-snapshot`, then `journey-enrich` with content recognition
   on (the app's defaults) until nothing is pending, as in the recording; the events, plan and
   duplicate rows the demo shows are compared.

A bundle built before the self-test entry existed (build 31) cannot render offscreen: build its
recorded source commit with the self-test entry added (commit e809a8d's Swift changes), copy
the new executable into a copy of the recorded bundle (which keeps its own engine), re-sign
that copy ad hoc and pass it here. Each run's preferences suite (PhotoDesk.Test.*) is removed
afterwards. Prints JSON; exit 1 if any rendered view or engine result differs.
"""
import argparse
import contextlib
import hashlib
import importlib.util
import io
import json
import os
from pathlib import Path
import subprocess
import sys
import tempfile

ROOT = Path(__file__).resolve().parents[1]


def sha(path):
    return hashlib.sha256(Path(path).read_bytes()).hexdigest()


@contextlib.contextmanager
def demo_root(label):
    with tempfile.TemporaryDirectory(prefix=f"PhotoDesk-reuse-{label}-") as directory:
        root = Path(directory)
        spec = importlib.util.spec_from_file_location("prepare_reuse_demo", ROOT / "scripts/prepare_demo.py")
        module = importlib.util.module_from_spec(spec)
        spec.loader.exec_module(module)
        module.OUT = root
        with contextlib.redirect_stdout(io.StringIO()):
            module.main()
        (root / "state").mkdir(exist_ok=True)
        suite = f"PhotoDesk.Test.MediaReuse.{label}.{root.name}"
        env = dict(os.environ, PHOTODESK_DEMO_ROOT=str(root), PHOTODESK_LIBRARY=str(root),
                   PHOTODESK_DATA_ROOT=str(root / "state"), PHOTODESK_BACKGROUND="1",
                   PHOTODESK_PREFERENCES_SUITE=suite)
        for key in ("PHOTOCLI_CONFIG", "PHOTOCLI_DATA_ROOT", "PHOTOCLI_DOCS_DB", "PYTHONPATH", "PYTHONHOME"):
            env.pop(key, None)
        try:
            yield root, env
        finally:
            subprocess.run(["defaults", "delete", suite], capture_output=True)
            (Path.home() / f"Library/Preferences/{suite}.plist").unlink(missing_ok=True)


def render(label, app, output):
    executable = Path(app) / "Contents/MacOS/PhotoDesk"
    if b"PhotoDesk.UISelfTest" not in executable.read_bytes():
        # An old binary would ignore the flag and open its normal window.
        raise SystemExit(f"{label}: no isolated self-test entry; see this script's docstring")
    output.mkdir(parents=True, exist_ok=True)
    for old in output.glob("*"):
        old.unlink()
    with demo_root(label) as (_, env):
        env["PHOTODESK_UI_TEST_OUTPUT"] = str(output)
        result = subprocess.run([str(executable), "--ui-self-test"], env=env, cwd="/",
                                capture_output=True, text=True, timeout=180)
    detail = json.loads((output / "ui-self-test.json").read_text())
    return dict(exit=result.returncode, ok=detail.get("ok"), counts=detail.get("counts"),
                failed_checks=sorted(k for k, v in (detail.get("checks") or {}).items() if not v),
                screenshots={s["file"]: sha(output / s["file"]) for s in detail.get("screenshots", [])})


def engine_view(label, app):
    executable = str(Path(app) / "Contents/Resources/Engine/photo-engine")

    def call(request, env):
        reply = subprocess.run([executable], input=json.dumps(request), text=True, capture_output=True,
                               env=dict(env, PATH="/usr/bin:/bin:/usr/sbin:/sbin"), cwd="/", timeout=300)
        if reply.returncode != 0:
            raise SystemExit(f"{label}: engine exit {reply.returncode}: {reply.stderr[-1500:]}")
        data = json.loads(reply.stdout)
        if data.get("ok") is not True:
            raise SystemExit(f"{label}: engine refused: {str(data)[:800]}")
        return data["data"]

    with demo_root(label) as (root, env):
        # PhotoPreferences defaults: shared on, recognition on, 3 h / 8 km / 90 min, no pet names.
        options = dict(include_shared=True, recognize_content=True, event_hours=3, event_kilometers=8,
                       meeting_minutes=90, pet_names=[])
        base = dict(library=str(root), limit=12, options=options, retry_failed=False, previous_digest="")
        result = call(dict(base, command="journey-snapshot"), env)
        rounds = 0
        while result.get("pending") and rounds < 10:
            result = call(dict(base, command="journey-enrich"), env)
            rounds += 1
    return dict(
        totals={k: result.get(k) for k in ("total", "analyzed", "pending", "failed", "unavailable", "albums", "tracks")},
        events=[dict(title=e["title"], date=e["date"], end=e.get("end_date"), count=e["count"], tracks=e["tracks"],
                     evidence=e.get("evidence"), place=e.get("place"), cover=(e.get("cover") or {}).get("filename"))
                for e in result["events"]],
        plan=sorted([r.get("filename"), r.get("group"), r.get("action"), r.get("title")] for r in result["plan"]["rows"]),
        duplicates=sorted([r.get("filename"), bool(r.get("recommended")), r.get("action")]
                          for r in result["duplicates"]["rows"]))


def main():
    parser = argparse.ArgumentParser(description=__doc__.split("\n\n")[0])
    parser.add_argument("bundles", nargs="+", help="label=/path/PhotoDesk.app")
    parser.add_argument("--runs", type=int, default=1)
    parser.add_argument("--out", type=Path, default=ROOT / "build/media-reuse")
    args = parser.parse_args()
    bundles = dict(item.split("=", 1) for item in args.bundles)
    report = {"bundles": {}, "renders": {}, "engine": {}}
    for label, app in bundles.items():
        info = subprocess.run(["/usr/libexec/PlistBuddy", "-c", "Print CFBundleVersion", str(Path(app) / "Contents/Info.plist")],
                              capture_output=True, text=True).stdout.strip()
        report["bundles"][label] = dict(build=info, executable_sha256=sha(Path(app) / "Contents/MacOS/PhotoDesk"),
                                        engine_sha256=sha(Path(app) / "Contents/Resources/Engine/photo-engine"))
        report["renders"][label] = [render(label, app, args.out / f"{label}-{run}") for run in range(1, args.runs + 1)]
        report["engine"][label] = engine_view(label, app)
    shots = {json.dumps(r["screenshots"], sort_keys=True) for runs in report["renders"].values() for r in runs}
    engines = {json.dumps(v, sort_keys=True, ensure_ascii=False) for v in report["engine"].values()}
    report["identical_renders"] = len(shots) == 1 and all(r["ok"] and r["exit"] == 0 for runs in report["renders"].values() for r in runs)
    report["identical_engine_results"] = len(engines) == 1
    print(json.dumps(report, ensure_ascii=False, indent=1))
    sys.exit(0 if report["identical_renders"] and report["identical_engine_results"] else 1)


if __name__ == "__main__":
    main()
