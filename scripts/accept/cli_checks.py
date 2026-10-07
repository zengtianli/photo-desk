"""CLI acceptance helpers; real library data and names never enter the report."""
import hashlib
import json
import marshal
import os
from pathlib import Path
import plistlib
import re
import stat
import subprocess
import types

from _common import APP, CLI, ENGINE, ROOT, require

COMMANDS = {
    # The app's functions (desk_cli, same engine as the window)
    "apply", "audit", "delete-check", "doctor", "duplicates", "photos", "plan", "plan-show", "plans",
    "progress", "records", "refresh", "settings", "timeline",
    # Old names kept as aliases of plan/apply
    "classify-plan", "classify-apply", "title-plan", "title-apply", "triage", "ocr-scan",
    # Command-line-only tools
    "backup", "ocr-extract", "shared-list", "dedup-export", "reconcile",
    # Answered by the app executable; the engine forwards them (desk_cli.APP_VERBS)
    "config", "update", "shortcuts", "login", "automation", "cancel",
}


def cli(arguments, env, *, prefix=(), timeout=180):
    require(CLI.is_file(), "App is missing its photodesk CLI")
    return subprocess.run([*prefix, str(CLI), *arguments], cwd="/", env=env,
                          input="", text=True, capture_output=True, timeout=timeout)


def bundle_snapshot():
    """Include every path, content, mode and symlink, without following links."""
    result = {}
    for path in sorted(APP.rglob("*")):
        metadata = path.lstat()
        value = os.readlink(path) if path.is_symlink() else (
            hashlib.sha256(path.read_bytes()).hexdigest() if path.is_file() else None)
        result[str(path.relative_to(APP))] = (metadata.st_mode, metadata.st_mtime_ns, value)
    return result


def verify_signature():
    result = subprocess.run(["/usr/bin/codesign", "--verify", "--deep", "--strict", str(APP)],
                            capture_output=True, timeout=60)
    require(result.returncode == 0, "CLI execution invalidated the application signature")


def functionality(root, env, checks):
    response = cli(["--help"], env)
    require(response.returncode == 0 and "photodesk" in response.stdout, "CLI help failed")
    listed = set(re.findall(r"^  ([a-z][a-z-]*)\s", response.stdout, re.M))
    require(listed == COMMANDS, "CLI must list exactly the supported commands")
    checks["cli_lists_every_command"] = True
    info = plistlib.loads((APP / "Contents/Info.plist").read_bytes())
    version = cli(["--version"], env)
    require(version.returncode == 0 and info["CFBundleShortVersionString"] in version.stdout
            and re.search(rf"(?<!\d){re.escape(info['CFBundleVersion'])}(?!\d)", version.stdout),
            "CLI version and build must match the App Info.plist")
    checks["cli_version_matches_app"] = True
    result = cli(["audit", "--json"], env)
    require(result.returncode == 0, "CLI synthetic audit failed")
    stats = json.loads(result.stdout)
    source = json.loads((root / "demo-input.json").read_text())["photos"]
    require(stats["total"] == len(source) == 10 and stats["photos"] + stats["movies"] == 10,
            "CLI audit does not conserve the fixture asset count")
    checks["cli_synthetic_audit_json_counts"] = True
    # The agent commands build and read the same timeline the window shows (own state folder,
    # so the app-engine checks that follow start from nothing).
    agent_env = dict(env, PHOTODESK_DATA_ROOT=str(root / "cli-agent-state"))

    def agent(*arguments, ok=True):
        result = cli([*arguments, "--json"], agent_env)
        data = json.loads(result.stdout)
        require(result.returncode == (0 if ok else 1) and data["ok"] is ok, f"CLI {arguments[0]} result")
        return data

    built = agent("refresh")
    view = agent("timeline", "--limit", "0")
    require(built["total"] == view["total"] == 10 and sum(e["count"] for e in view["events"]) == 10
            and view["plan_id"] == built["plan_id"], "CLI timeline does not read what refresh built")
    duplicates = agent("duplicates")
    require(duplicates["row_count"] == 2 and len(duplicates["recommended"]) == 1,
            "CLI duplicates differ from the app's duplicate plan")
    require(agent("photos", "--limit", "0")["total"] == 10, "CLI photo list lost assets")
    refused = agent("apply", built["plan_id"], "--select-all", "--confirm", ok=False)
    require("合成演示图库只用于" in refused["error"], "CLI write was not stopped by the engine's demo guard")
    checks["cli_agent_commands_share_app_timeline"] = True


def recovery(root, env, checks):
    import yaml
    before = bundle_snapshot()
    faults = root / "cli-faults"
    faults.mkdir()
    missing = faults / "missing.yaml"
    missing.write_text(yaml.safe_dump({"library": str(faults / "Missing.photoslibrary")}))
    broken = faults / "broken.yaml"
    broken.write_text("library: [unclosed\n")
    denied = faults / "denied.yaml"
    denied.write_text("library: null\n")
    # Kernel denial works even for an admin/root process, unlike chmod fixtures.
    profile = f"(version 1)(allow default)(deny file-read* (literal {json.dumps(str(denied.resolve()))}))"
    clean_env = dict(env, PHOTODESK_DEMO_ROOT="")
    scenarios = (("missing_library", missing, ()), ("bad_config", broken, ()),
                 ("permission_denied", denied, ("/usr/bin/sandbox-exec", "-p", profile)))
    for name, config, prefix in scenarios:
        result = cli(["--config", str(config), "audit", "--json"], clean_env, prefix=prefix)
        lines = (result.stdout + result.stderr).strip().splitlines()
        require(result.returncode == 1 and len(lines) == 1 and re.search(r"[\u4e00-\u9fff]", lines[0])
                and "Traceback" not in lines[0], f"CLI {name} must exit 1 with one Chinese explanation")
        if name == "permission_denied":
            require("给当前终端完全磁盘访问权限" in lines[0], "CLI permission guidance targets the wrong application")
        checks[f"cli_{name}_friendly_exit_one"] = True
    require(bundle_snapshot() == before, "CLI fault handling changed files inside the App")
    verify_signature()
    checks["cli_faults_preserve_all_bundle_files_and_signature"] = True


def code_strings(code):
    yield code.co_filename
    for value in code.co_consts:
        if isinstance(value, str):
            yield value
        elif isinstance(value, bytes):
            yield value.decode("utf-8", errors="ignore")
        elif isinstance(value, types.CodeType):
            yield from code_strings(value)


def private_content_scan(checks):
    """Read the actual frozen project modules, including compressed bytecode."""
    from PyInstaller.archive.readers import CArchiveReader
    private_pet = "".join(chr(c) for c in (0x5927, 0x767D))
    forbidden = (private_pet, "/" + "Users/", "Dev/" + "tools/kb")
    sources = list((ROOT / "backend").rglob("*.py")) + [ROOT / "backend/defaults.yaml"]
    for source in sources:
        require(not any(token in source.read_text() for token in forbidden),
                "Private literal remains in application source")
    archive = CArchiveReader(str(ENGINE))
    project_names = {path.stem for path in (ROOT / "backend").glob("*.py")}
    seen = set()
    for name, entry in archive.toc.items():
        if entry[-1] == "s" and name in project_names:
            body = code_strings(marshal.loads(archive.extract(name)))
            require(not any(token in value for value in body for token in forbidden),
                    "Private literal remains in bundled entry code")
            seen.add(name)
        elif entry[-1] == "z":
            pyz = archive.open_embedded_archive(name)
            for module in pyz.toc:
                if module in project_names or module == "photocli" or module.startswith("photocli."):
                    code = pyz.extract(module)
                    require(not any(token in value for value in code_strings(code) for token in forbidden),
                            "Private literal remains in bundled application module")
                    seen.add(module)
    require("bridge" in seen and "photocli.cli" in seen and "photocli.title" in seen,
            "Actual frozen project code was not inspected")
    defaults = APP / "Contents/Resources/Engine/_internal/defaults.yaml"
    require(defaults.is_file() and not any(token in defaults.read_text() for token in forbidden),
            "Bundled default configuration contains private content")
    checks["source_and_frozen_project_code_have_no_private_literals"] = True


def privacy(root, env, checks):
    private_content_scan(checks)
    before = bundle_snapshot()
    state = root / "cli-private-state"
    # audit is read-only now; shared-list is the command-line tool that still writes a report.
    result = cli(["shared-list"], dict(env, PHOTODESK_DATA_ROOT=str(state)))
    require(result.returncode == 0, "CLI report generation failed")
    outputs = state / "cli"
    require(outputs.is_dir() and stat.S_IMODE(outputs.stat().st_mode) == 0o700,
            "CLI output directory must have mode 0700")
    require(any(outputs.rglob("shared-manual-checklist.html")), "CLI report was not saved in the CLI subdirectory")
    require(not (state / "plans").exists(), "CLI output mixed with GUI JSON plans")
    require(bundle_snapshot() == before, "CLI report generation changed the application bundle")
    verify_signature()
    checks["cli_artifacts_are_private_and_separate_from_gui_plans"] = True
    checks["cli_report_preserves_bundle_files_and_signature"] = True


def source_signature(library):
    database = library / "database/Photos.sqlite"
    result = {}
    for suffix in ("", "-wal"):
        path = Path(str(database) + suffix)
        try:
            digest = hashlib.sha256()
            with path.open("rb") as handle:
                for chunk in iter(lambda: handle.read(1024 * 1024), b""):
                    digest.update(chunk)
            result[suffix or "db"] = digest.hexdigest()
        except FileNotFoundError:
            result[suffix or "db"] = None
    return result


def real_library_privacy(root, env, checks):
    """One read-only audit; permission failure stays a failed, explicit gate."""
    import yaml
    details = {"photos_library_accessed": False, "real_library_audit": "not_run",
               "owner_confirmation_required": False}
    try:
        private_config = Path.home() / "Library/Application Support/PhotoDesk/cli-config.yaml"
        configured = (yaml.safe_load(private_config.read_text()) or {}) if private_config.is_file() else {}
        library = configured.get("library")
        if not library:
            from osxphotos.utils import get_system_library_path, get_last_library_path
            library = get_system_library_path() or get_last_library_path()
        if not library:
            raise FileNotFoundError("No readable configured Photos library")
        library = Path(library).expanduser().resolve()
        before = source_signature(library)
        if before["db"] is None:
            raise FileNotFoundError("No readable Photos database")
        configuration = root / "readonly-library.yaml"
        configuration.write_text(yaml.safe_dump({"library": str(library)}))
        configuration.chmod(0o600)
        safe_env = dict(env, PHOTODESK_DEMO_ROOT="", PHOTODESK_DATA_ROOT=str(root / "readonly-state"))
        # Deny writes to the real library even if a future command regresses.
        profile = f"(version 1)(allow default)(deny network*)(deny file-write* (subpath {json.dumps(str(library))}))"
        result = cli(["--config", str(configuration), "audit", "--json"], safe_env,
                     prefix=("/usr/bin/sandbox-exec", "-p", profile))
        after = source_signature(library)
        details["photos_library_accessed"] = True
        unchanged = before == after
        checks["real_photos_database_and_wal_bytes_unchanged"] = unchanged
        if result.returncode != 0:
            permission = "权限" in result.stderr or "Permission" in result.stderr
            details.update(real_library_audit="permission_denied" if permission else "audit_failed",
                           owner_confirmation_required=permission)
            checks["real_library_cli_audit_succeeds"] = False
            return details
        stats = json.loads(result.stdout)
        checks["real_library_cli_audit_succeeds"] = all(isinstance(stats.get(k), int)
                                                       for k in ("total", "photos", "movies")) and (
            stats["total"] == stats["photos"] + stats["movies"])
        details["real_library_audit"] = "passed" if unchanged else "database_changed_during_read"
        # Raw audit output contains personal faces and labels; never persist it.
        details["real_library_counts"] = {k: stats[k] for k in ("total", "photos", "movies")}
        return details
    except (PermissionError, FileNotFoundError):
        details.update(real_library_audit="unavailable_to_this_session", owner_confirmation_required=True)
    except (OSError, ValueError, yaml.YAMLError, subprocess.TimeoutExpired):
        details["real_library_audit"] = "readback_failed"
    checks["real_library_cli_audit_succeeds"] = False
    return details
