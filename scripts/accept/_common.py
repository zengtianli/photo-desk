"""Shared, isolated runtime for fixed PhotoDesk acceptance commands."""
from contextlib import contextmanager
import hashlib
import importlib.util
import json
import os
from pathlib import Path
import plistlib
import subprocess
import tempfile

ROOT = Path(__file__).resolve().parents[2]
APP = ROOT / "build/DerivedData/Build/Products/Release/PhotoDesk.app"
ENGINE = APP / "Contents/Resources/Engine/photo-engine"
OUT = Path(os.environ.get("SOP_OUT_DIR", ROOT / "build/acceptance"))


def require(condition, message):
    if not condition:
        raise AssertionError(message)


def verify_build():
    """Reuse Chapter's source/binary receipt verifier; never bless a stale app."""
    import sys
    import yaml
    sys.path.insert(0, str(ROOT.parent / "chapter/engine"))
    from app_sop import verify_build_receipt
    config = yaml.safe_load((ROOT / "project.yaml").read_text())["sop"]
    receipt_file = ROOT / "perf/build-receipt.json"
    require(receipt_file.is_file(), "Build receipt missing; run: uv run python scripts/accept/build.py")
    receipt = json.loads(receipt_file.read_text())
    require(receipt.get("source", {}).get("input_globs") == config["source"],
            "Build inputs changed; run: uv run python scripts/accept/build.py")
    valid, reason = verify_build_receipt({"repo": ROOT, "sop": config}, APP)
    require(valid, f"{reason}; run: uv run python scripts/accept/build.py")


@contextmanager
def fixture(name):
    """Use the same marked synthetic inputs as the product demo, in a fresh root."""
    verify_build()
    with tempfile.TemporaryDirectory(prefix=f"PhotoDesk-accept-{name}-") as directory:
        root = Path(directory)
        spec = importlib.util.spec_from_file_location("prepare_accept_demo", ROOT / "scripts/prepare_demo.py")
        module = importlib.util.module_from_spec(spec)
        spec.loader.exec_module(module)
        module.OUT = root
        # The generator normally prints its local path; acceptance logs stay portable.
        import contextlib
        import io
        with contextlib.redirect_stdout(io.StringIO()):
            module.main()
        (root / "state").mkdir(exist_ok=True)
        env = dict(os.environ, PHOTODESK_DEMO_ROOT=str(root),
                   PHOTODESK_DATA_ROOT=str(root / "state"), PHOTODESK_BACKGROUND="1",
                   PHOTODESK_PREFERENCES_SUITE=f"PhotoDesk.Test.Acceptance.{name}.{root.name}")
        yield root, env


def engine(request, env, *, timeout=90):
    require(ENGINE.is_file(), "Build the app first: bash build.sh --no-install")
    result = subprocess.run([str(ENGINE)], input=json.dumps(request), text=True,
                            capture_output=True, env=env, cwd="/", timeout=timeout)
    require(result.returncode == 0, f"Engine exit status {result.returncode}")
    data = json.loads(result.stdout)
    require(isinstance(data.get("ok"), bool), "Missing real engine response envelope")
    return data


def report(name, checks, summary, **extra):
    require(checks and all(checks.values()), "Acceptance assertions did not all pass")
    OUT.mkdir(parents=True, exist_ok=True)
    info = plistlib.loads((APP / "Contents/Info.plist").read_bytes())
    receipt = json.loads((ROOT / "perf/build-receipt.json").read_text())
    detail = dict(summary=summary, checks=checks, synthetic_inputs=True,
                  photos_library_accessed=False,
                  version=info["CFBundleShortVersionString"], build=info["CFBundleVersion"],
                  source_sha256=receipt["source"]["sha256"],
                  app_sha256=receipt["artifact"]["sha256"],
                  engine_sha256=hashlib.sha256(ENGINE.read_bytes()).hexdigest(), **extra)
    (OUT / f"{name}.detail.json").write_text(json.dumps(detail, ensure_ascii=False, indent=2) + "\n")
    print(json.dumps(detail, ensure_ascii=False))
