#!/usr/bin/env python3
"""Exercise real bundled-engine recovery using a disposable synthetic library.

Each engine() invocation starts a fresh process. This covers application-managed
plans and incremental caches; it does not claim Photos writes or power-loss tests.
"""
import hashlib
import json
import sqlite3

from _common import engine, fixture, report, require


def successful(request, env):
    response = engine(request, env)
    require(response["ok"], f"Engine rejected {request['command']}")
    return response["data"]


def saved_files(root):
    """Check both content and write avoidance, not only the displayed digest."""
    return {
        str(path.relative_to(root)): (
            hashlib.sha256(path.read_bytes()).hexdigest(), path.stat().st_mtime_ns
        )
        for path in sorted(root.rglob("*"))
        if path.is_file() and path.suffix in (".json", ".csv")
    }


def cache_rows(index):
    with sqlite3.connect(f"file:{index}?mode=ro", uri=True) as connection:
        return connection.execute("SELECT key,value FROM cache ORDER BY key").fetchall()


def main():
    checks = {}
    with fixture("recovery") as (root, env):
        state = root / "state"
        snapshot = successful({"command": "journey-snapshot"}, env)
        require(snapshot["total"] == 10, "Synthetic library was not fully read")
        # Run real Vision on one synthetic image to persist incremental content
        # state as well as the duplicate hashes already produced by snapshot.
        enriched = successful({"command": "journey-enrich", "limit": 1}, env)
        require(enriched["analyzed"] == 1 and enriched["failed"] == 0,
                "One synthetic image must complete real content analysis")
        digest = enriched["digest"]
        index_files = list((state / "journey").glob("*/index.sqlite"))
        require(len(index_files) == 1, "Expected a single isolated persistent index")
        index = index_files[0]
        cache = cache_rows(index)
        require(any(key.startswith("hash:") for key, _ in cache), "Duplicate hash cache missing")
        require(any(not key.startswith("hash:") for key, _ in cache), "Content cache missing")
        saved = saved_files(state)

        # Every command is another process: unchanged replies prove that analysis
        # survived process exit, and the physical files must not be rewritten.
        reopened = successful({"command": "journey-snapshot", "previous_digest": digest}, env)
        require(reopened == {"unchanged": True, "digest": digest},
                "Restart did not recover the persisted content and duplicate cache")
        require(cache_rows(index) == cache, "Reopening changed persisted cache contents")
        require(saved_files(state) == saved, "Unchanged snapshot rewrote saved plans")
        checks["fresh_process_recovers_incremental_cache"] = True
        checks["unchanged_snapshot_preserves_content_and_mtime"] = True

        # An existing empty bundle gets past the App's path guard and reaches
        # the actual vendored PhotosDB loader inside the frozen engine.
        invalid_library = root / "Invalid.photoslibrary"
        invalid_library.mkdir()
        failure = engine({"command": "audit", "library": str(invalid_library)},
                         dict(env, PHOTODESK_DEMO_ROOT=""))
        require(not failure["ok"] and "照片库不存在:" in failure.get("error", "")
                and "Traceback" not in failure["error"],
                "Bundled library loader must return the synced readable error")
        require(saved_files(state) == saved and cache_rows(index) == cache,
                "Unreadable library damaged the existing synthetic index")
        checks["unreadable_library_has_actionable_error_without_state_loss"] = True

        for request in (
            {"command": "acceptance-unknown-command"},
            {"command": "load-plan", "plan_id": "../invalid"},
            {"command": "journey-snapshot", "options": {"event_hours": "invalid"}},
            [],
        ):
            failure = engine(request, env)
            require(not failure["ok"] and bool(failure.get("error")),
                    "Invalid request did not return an actionable error envelope")
            require(saved_files(state) == saved and cache_rows(index) == cache,
                    "Rejected request changed the previously valid state")
        checks["invalid_requests_do_not_mutate_valid_state"] = True

        # Simulate a malformed input manifest, not corrupted production data.
        manifest = root / "demo-input.json"
        original = manifest.read_bytes()
        try:
            manifest.write_text("{bad-json", encoding="utf-8")
            failure = engine({"command": "journey-snapshot"}, env)
            require(not failure["ok"] and bool(failure.get("error")),
                    "Malformed library input did not report failure")
            require(saved_files(state) == saved and cache_rows(index) == cache,
                    "Malformed library input damaged the previous index")
        finally:
            manifest.write_bytes(original)
        recovered = successful({"command": "journey-snapshot", "previous_digest": digest}, env)
        require(recovered.get("unchanged") is True, "Corrected input did not recover on retry")
        checks["malformed_input_recovers_without_state_loss"] = True

        # A matching digest must not hide a missing durable plan. Production must
        # regenerate it, then permit loading precisely the same selected rows.
        plan_id = enriched["plan"]["id"]
        plan_file = state / "plans" / f"{plan_id}.json"
        plan_file.unlink()
        missing = engine({"command": "load-plan", "plan_id": plan_id}, env)
        require(not missing["ok"] and bool(missing.get("error")),
                "Missing plan did not report an error")
        rebuilt = successful({"command": "journey-snapshot", "previous_digest": digest}, env)
        require(not rebuilt.get("unchanged") and rebuilt["digest"] == digest,
                "Missing plan was not rebuilt despite matching content digest")
        loaded = successful({"command": "load-plan", "plan_id": plan_id}, env)
        require(loaded["rows"] == enriched["plan"]["rows"],
                "Rebuilt plan changed asset identities or analysis")
        require(cache_rows(index) == cache, "Rebuilding a plan discarded incremental cache")
        require(json.loads(plan_file.read_text())["id"] == plan_id,
                "Rebuilt durable plan has the wrong identity")
        checks["missing_plan_rebuilt_with_stable_asset_identities"] = True
        saved_after_rebuild = saved_files(state)
        final = successful({"command": "journey-snapshot", "previous_digest": digest}, env)
        require(final.get("unchanged") is True and saved_files(state) == saved_after_rebuild,
                "Recovered state did not return to write-free refresh")
        checks["recovered_state_returns_to_write_free_refresh"] = True

    report("recovery", checks,
           "真实包内引擎跨进程恢复合成图库缓存；坏请求及坏输入保留有效状态；缺失计划自动重建，恢复后无变化不重写。",
           scope="Synthetic library; real bundled engine, Vision, SQLite and plan persistence. No Photos writes or crash/power-loss recovery claim.")


if __name__ == "__main__":
    main()
