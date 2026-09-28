#!/usr/bin/env python3
"""Run the packaged engine on generated photos, then decode with the app's Swift models.

No Photos library, application window, mocked engine, or network is involved. The
fixture's album/title metadata proves deterministic grouping; real Vision/OCR is
also exercised, without claiming that its synthetic cat drawing is a real cat.
"""
import hashlib
import json
import os
import sqlite3
import subprocess
import sys

from _common import ROOT, engine, fixture, report, require
from cli_checks import functionality as cli_functionality


SWIFT_CHECK = r'''
import Foundation

@main
struct Acceptance {
    static func main() throws {
        let root = URL(fileURLWithPath: CommandLine.arguments[1])
        func read<T: Decodable>(_ name: String, _ type: T.Type) throws -> T {
            try Contract.decode(type, from: Data(contentsOf: root.appendingPathComponent(name + ".json")))
        }
        let snapshot = try read("snapshot", JourneyResult.self)
        let enriched = try read("enriched", JourneyResult.self)
        for result in [snapshot, enriched] {
            precondition(result.total == 10 && result.plan.rows.count == 10)
            precondition(result.events.reduce(0) { $0 + $1.count } == 10)
            precondition(Set(result.plan.rows.map(\.id)).count == 10)
            precondition(result.plan.rows.allSatisfy { $0.localUuid != nil })
            precondition(result.analyzed + result.pending == 10)
            precondition(result.duplicates.rows.count == 2)
            precondition(result.duplicates.rows.filter { $0.recommended == true }.count == 1)
            precondition(result.plan.isReadOnly && result.duplicates.isReadOnly)
        }
        precondition(enriched.analyzed == 10 && enriched.pending == 0)
        let plan = try read("saved-plan", PhotoPlan.self)
        precondition(plan.id == enriched.plan.id && plan.rows.count == 10)
        let history = try read("history", HistoryResult.self)
        precondition(history.entries.contains { $0.id == plan.id && $0.count == 10 })
        let unchanged = try read("unchanged", JourneyUnchanged.self)
        precondition(unchanged.unchanged == true && unchanged.digest == enriched.digest)
        let shortData = try Data(contentsOf: root.appendingPathComponent("unchanged.json"))
        precondition((try? Contract.decode(JourneyResult.self, from: shortData)) == nil)
        print("Actual PhotoDesk Contract.decode: 10 assets, persisted plans, and unchanged response passed")
    }
}
'''


def swift_contract(root, replies):
    for name, value in replies.items():
        (root / f"{name}.json").write_text(json.dumps(value, ensure_ascii=False))
    source = root / "FunctionalityContract.swift"
    source.write_text(SWIFT_CHECK)
    binary = root / "functionality-contract"
    selector = "/Users/tianli/Dev/tools/dev/lib/tools/macapp/xcode_env.py"
    selected = subprocess.run(
        [sys.executable, selector, "--platform", "macosx", "--print", "developer-dir", "--quiet"],
        capture_output=True, text=True, timeout=30, check=True,
    )
    env = dict(os.environ, DEVELOPER_DIR=selected.stdout.strip())
    require(bool(env["DEVELOPER_DIR"]), "Xcode selector did not return a developer directory")
    compiled = subprocess.run(
        ["/usr/bin/xcrun", "swiftc", "-parse-as-library", str(ROOT / "Sources/Models.swift"),
         str(source), "-o", str(binary)], env=env, capture_output=True, text=True, timeout=120,
    )
    require(compiled.returncode == 0, f"Actual Swift model compilation failed: {compiled.stderr[-6000:]}")
    decoded = subprocess.run([str(binary), str(root)], capture_output=True, text=True, timeout=30)
    require(decoded.returncode == 0, f"Actual Swift decoder rejected engine output: {decoded.stderr[-6000:]}")


def main():
    checks = {}
    with fixture("functionality") as (root, env):
        cli_functionality(root, env, checks)
        original = json.loads((root / "demo-input.json").read_text())
        expected = {row["uuid"] for row in original["photos"]}
        replies = {}

        def run(name, request):
            value = engine(request, env)
            require(value["ok"], f"{name}: {value.get('error', 'unknown engine error')}")
            replies[name] = value
            return value["data"]

        snapshot = run("snapshot", {"command": "journey-snapshot"})
        rows = snapshot["plan"]["rows"]
        require(snapshot["total"] == len(rows) == len(expected) == 10, "Snapshot lost assets")
        require({row["local_uuid"] for row in rows} == expected, "Snapshot identities differ from input")
        require(sum(event["count"] for event in snapshot["events"]) == 10, "Event counts do not conserve assets")
        require(len({row["id"] for row in rows}) == 10, "Row identifiers are not unique")
        checks["all_ten_assets_grouped_once"] = True
        for track, count in [("猫时间线", 3), ("会议与工作", 3)]:
            matching = [event for event in snapshot["events"] if track in event["tracks"]]
            require(sum(event["count"] for event in matching) == count, f"Wrong membership for {track}")
        checks["cat_and_meeting_metadata_grouping"] = True
        duplicates = snapshot["duplicates"]["rows"]
        require(len(duplicates) == 2, "Expected exactly the two identical copies")
        require(sum(bool(row["recommended"]) for row in duplicates) == 1, "Expected one duplicate preselection")
        duplicate_ids = {row["local_uuid"] for row in duplicates}
        expected_duplicates = {row["uuid"] for row in original["photos"]
                               if row["file"] in ("sample-01.png", "sample-01-copy.png")}
        require(duplicate_ids == expected_duplicates, "Duplicate plan contains a different photo")
        checks["byte_identical_duplicate_pair_one_preselection"] = True

        enriched = run("enriched", {"command": "journey-enrich", "limit": 24})
        require(enriched["total"] == enriched["analyzed"] == 10 and enriched["pending"] == 0,
                "Real content enrichment did not finish the entire fixture")
        require(enriched["failed"] == enriched["unavailable"] == 0, "Vision/OCR reported an unavailable or failed asset")
        indexes = list((root / "state" / "journey").glob("*/index.sqlite"))
        require(len(indexes) == 1, "Expected one isolated recognition index")
        with sqlite3.connect(f"file:{indexes[0]}?mode=ro", uri=True) as database:
            insights = [json.loads(value) for key, value in database.execute("SELECT key,value FROM cache")
                        if not key.startswith("hash:")]
        require(len(insights) == 10 and all(value["state"] == "complete" for value in insights),
                "Recognition cache does not contain ten successful real analyses")
        require(any("meeting" in value.get("text", "").lower() for value in insights),
                "Real OCR did not recognize the synthetic meeting text")
        checks["real_vision_and_ocr_ten_assets"] = True

        saved = run("saved-plan", {"command": "load-plan", "plan_id": enriched["plan"]["id"]})
        require(saved == enriched["plan"], "Persisted plan differs from engine output")
        history = run("history", {"command": "history"})
        require(any(item["id"] == saved["id"] and item["count"] == 10 for item in history["entries"]),
                "Persisted timeline cannot be found in history")
        checks["saved_plan_and_history_roundtrip"] = True
        unchanged = run("unchanged", {"command": "journey-snapshot", "previous_digest": enriched["digest"]})
        require(unchanged == {"unchanged": True, "digest": enriched["digest"]}, "Unchanged response contract failed")
        checks["incremental_unchanged_response"] = True
        swift_contract(root, replies)
        checks["actual_swift_models_and_decoder"] = True
    report("functionality", checks,
           "真实内置引擎完成 10 张合成图片归集、猫与会议分类、重复预选、Vision/OCR、计划回读和 Swift 合同验证。",
           scope="Synthetic isolated inputs only; no PhotoKit writes or deletion exercised.",
           models_sha256=hashlib.sha256((ROOT / "Sources/Models.swift").read_bytes()).hexdigest())


if __name__ == "__main__":
    main()
