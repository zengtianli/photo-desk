#!/usr/bin/env python3
"""Verify privacy boundaries with real, network-denied bundled-engine processes.

All assets and mutations belong to a disposable synthetic fixture. The network
result proves this tested workflow can run under enforced denial, not a complete
audit of every application path or of the user's Photos permissions.
"""
import hashlib
import json
from pathlib import Path
import stat
import subprocess
import sys

from _common import ENGINE, fixture, report, require


SANDBOX = Path("/usr/bin/sandbox-exec")
PROFILE = "(version 1)(allow default)(deny network*)"


def network_denied_command(command, env, *, payload=None):
    require(SANDBOX.is_file(), "macOS sandbox-exec is required for enforced network isolation")
    result = subprocess.run([str(SANDBOX), "-p", PROFILE, *command],
                            input=payload, text=True, capture_output=True,
                            env=env, cwd="/", timeout=90)
    require(result.returncode == 0, f"Isolated process exited {result.returncode}")
    return result.stdout


def isolated_engine(request, env):
    require(ENGINE.is_file(), "Build the app first: bash build.sh --no-install")
    response = json.loads(network_denied_command([str(ENGINE)], env,
                                                 payload=json.dumps(request)))
    require(isinstance(response.get("ok"), bool), "Engine response envelope is missing")
    return response


def successful(request, env):
    response = isolated_engine(request, env)
    require(response["ok"], f"Engine rejected isolated {request['command']}")
    return response["data"]


def contents(root):
    return {str(path.relative_to(root)): hashlib.sha256(path.read_bytes()).hexdigest()
            for path in sorted(root.rglob("*")) if path.is_file()}


def rejected(request, env, message):
    response = isolated_engine(request, env)
    require(not response["ok"] and message in response.get("error", ""),
            "Expected privacy boundary did not reject the request")


def main():
    checks = {}
    with fixture("privacy") as (root, env):
        # Unlike fixture's pre-created state directory, this path is created by
        # the production engine itself, so its actual umask is also exercised.
        state = root / "private-state"
        env = dict(env, PHOTODESK_DATA_ROOT=str(state))
        control = """import socket
try:
    socket.socket().connect(('127.0.0.1', 9))
except PermissionError:
    print('network-denied')
else:
    raise SystemExit('Network denial was not enforced')
"""
        require(network_denied_command([sys.executable, "-c", control], env).strip() == "network-denied",
                "Sandbox must reject the loopback network positive control")
        snapshot = successful({"command": "journey-snapshot"}, env)
        enriched = successful({"command": "journey-enrich", "limit": 1}, env)
        require(snapshot["total"] == 10 and enriched["analyzed"] == 1 and enriched["failed"] == 0,
                "Real synthetic timeline and Vision analysis must work with networking denied")
        checks["core_engine_and_vision_run_with_network_denied"] = True

        # Plan generation, duplicate indexing and OCR/Vision artifacts are real
        # runtime output. Check every created file and directory, including root.
        artifacts = [state, *state.rglob("*")]
        require(len(artifacts) > 5, "Expected actual persisted engine artifacts")
        for path in artifacts:
            require(stat.S_IMODE(path.stat().st_mode) & 0o077 == 0,
                    "Engine-created local data is readable or writable by other users")
        checks["engine_created_data_is_owner_only"] = True
        before = contents(root)

        # The demo boundary prevents reaching Apple Photos mutation APIs even
        # with an existing plan and a nonempty exact asset selection.
        plan = enriched["plan"]
        selection = [plan["rows"][0]["id"]]
        for command in ("apply", "delete-preview"):
            rejected({"command": command, "plan_id": plan["id"], "selected": selection,
                      "confirmed": True}, env, "合成演示图库只用于")
            require(contents(root) == before, "Rejected Photos action modified fixture data")
        for kind in ("classify", "title", "sensitive", "triage", "duplicates"):
            rejected({"command": "plan", "kind": kind}, env, "合成演示图库只用于")
            require(contents(root) == before, "Rejected advanced action modified fixture data")
        checks["synthetic_library_rejects_photos_write_and_delete_paths"] = True
        checks["advanced_actions_cannot_bypass_synthetic_boundary"] = True

        # A nested fixture keeps every escape target in our own temporary root,
        # while exercising the same realpath checks as an external path would.
        nested = root / "nested-demo"
        nested.mkdir()
        manifest = json.loads((root / "demo-input.json").read_text())
        manifest["photos"] = [dict(manifest["photos"][0])]
        manifest["photos"][0]["file"] = "../sample-01.png"
        (nested / "demo-input.json").write_text(json.dumps(manifest))
        nested_state = nested / "state"
        nested_env = dict(env, PHOTODESK_DEMO_ROOT=str(nested), PHOTODESK_DATA_ROOT=str(nested_state))
        rejected({"command": "journey-snapshot"}, nested_env, "演示照片必须位于独立演示目录")
        require(not list(nested_state.iterdir()), "Traversal input created an index")
        checks["asset_relative_path_escape_is_rejected"] = True

        (nested / "linked.png").symlink_to(root / "sample-01.png")
        manifest["photos"][0]["file"] = "linked.png"
        (nested / "demo-input.json").write_text(json.dumps(manifest))
        rejected({"command": "journey-snapshot"}, nested_env, "演示照片必须位于独立演示目录")
        require(not list(nested_state.iterdir()), "Symlink input created an index")
        checks["asset_symlink_escape_is_rejected"] = True

        # Data roots are validated after startup creates the empty directory;
        # the failure must occur before any index/plan/OCR state is written.
        outside_state = root / "outside-state"
        outside_env = dict(nested_env, PHOTODESK_DATA_ROOT=str(outside_state))
        rejected({"command": "journey-snapshot"}, outside_env, "演示模式要求独立数据目录")
        require(outside_state.is_dir() and not list(outside_state.iterdir()),
                "Out-of-scope data root received analysis artifacts")
        (nested / "linked-state").symlink_to(outside_state, target_is_directory=True)
        linked_env = dict(nested_env, PHOTODESK_DATA_ROOT=str(nested / "linked-state"))
        rejected({"command": "journey-snapshot"}, linked_env, "演示模式要求独立数据目录")
        require(not list(outside_state.iterdir()), "Symlink data root received analysis artifacts")
        checks["data_root_and_symlink_must_stay_inside_demo_root"] = True

    report("privacy", checks,
           "真实引擎在禁止网络的子进程内完成合成图库归集与 Vision；写入/删除入口、素材与数据目录越界均拒绝，实际数据仅当前用户可读写。",
           network_scope="Kernel-enforced network denial for tested child processes; loopback positive control rejected. This is not a whole-app network audit.",
           permissions_scope="Engine-created local artifacts only; no existing user data or Photos permissions changed.")


if __name__ == "__main__":
    main()
