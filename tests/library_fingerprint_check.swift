import Foundation
import SQLite3

// Regression check for LibraryFingerprint and LibraryBaseline.check, the gate that lets the
// automatic check ignore system writes PhotoDesk does not show. Uses a throwaway WAL-mode
// database with the Photos table and column names in a temporary directory; never a real library.
// Build: xcrun swiftc Sources/Models.swift tests/library_fingerprint_check.swift -o qa/library-fingerprint-check
@main
struct LibraryFingerprintCheck {
    static func main() async throws {
        // `library-fingerprint-check <x.photoslibrary> [runs]` only times read-only fingerprints of a real library.
        if CommandLine.arguments.count > 1 {
            let path = CommandLine.arguments[1], runs = Int(CommandLine.arguments.dropFirst(2).first ?? "") ?? 5
            for _ in 0..<runs {
                let clock = ContinuousClock(), start = clock.now
                let digest = LibraryFingerprint.read(library: path)
                print(digest ?? "nil", clock.now - start)
            }
            return
        }
        let fm = FileManager.default
        let root = fm.temporaryDirectory.appendingPathComponent("photodesk-fingerprint-\(UUID().uuidString)")
        defer { try? fm.removeItem(at: root) }
        let library = root.appendingPathComponent("Fake.photoslibrary")
        try fm.createDirectory(at: library.appendingPathComponent("database"), withIntermediateDirectories: true)
        let path = library.appendingPathComponent("database/Photos.sqlite").path
        let db = try Database(path)
        try db.exec("PRAGMA journal_mode=WAL")
        // Every column the fingerprint reads, plus columns and tables the system churns.
        func create(_ table: String, _ columns: [String], extra: [String] = []) throws {
            let names = (columns + extra).filter { $0 != "Z_PK" }
            try db.exec("CREATE TABLE \(table) (Z_PK INTEGER PRIMARY KEY, Z_OPT INTEGER, \(names.map { "\($0)" }.joined(separator: ", ")))")
        }
        for (table, columns, _) in LibraryFingerprint.tables {
            let extra: [String] = [
                "ZASSET": ["ZCURATIONSCORE", "ZOVERALLAESTHETICSCORE", "ZANALYSISSTATEMODIFICATIONDATE", "ZMOMENT", "ZPHOTOANALYSISATTRIBUTES"],
                "ZADDITIONALASSETATTRIBUTES": ["ZREVERSELOCATIONDATAISVALID", "ZSCENEANALYSISVERSION", "ZVIEWCOUNT", "ZLASTVIEWEDDATE"],
                "ZPERSON": ["ZFACECOUNT", "ZKEYFACE", "ZMANUALORDER"],
                "ZDETECTEDFACE": ["ZQUALITY", "ZCLUSTERSEQUENCENUMBER"],
                "ZGENERICALBUM": ["ZSTARTDATE", "ZENDDATE", "ZCUSTOMSORTKEY"],
            ][table] ?? []
            try create(table, columns, extra: extra)
        }
        try db.exec("""
            CREATE TABLE Z_34ASSETS (Z_34ALBUMS INTEGER, Z_3ASSETS INTEGER, Z_FOK_3ASSETS INTEGER, PRIMARY KEY (Z_34ALBUMS, Z_3ASSETS));
            CREATE TABLE Z_33KEYASSETS (Z_33ALBUMS INTEGER, Z_3KEYASSETS INTEGER);
            CREATE TABLE Z_1KEYWORDS (Z_1ASSETATTRIBUTES INTEGER, Z_53KEYWORDS INTEGER, PRIMARY KEY (Z_1ASSETATTRIBUTES, Z_53KEYWORDS));
            CREATE TABLE Z_METADATA (Z_VERSION INTEGER PRIMARY KEY, Z_UUID VARCHAR, Z_PLIST BLOB);
            CREATE TABLE ZGRAPHNODE (Z_PK INTEGER PRIMARY KEY, ZLABEL VARCHAR);
            CREATE TABLE ZLEOITEM (Z_PK INTEGER PRIMARY KEY, ZCONTENT VARCHAR);
            CREATE TABLE ZCOMPUTEDASSETATTRIBUTES (Z_PK INTEGER PRIMARY KEY, ZASSET INTEGER, ZFAILURESCORE FLOAT);
            INSERT INTO Z_METADATA VALUES (1, 'x', x'00');
            INSERT INTO ZASSET (Z_PK, ZUUID, ZMODIFICATIONDATE, ZHIDDEN, ZLATITUDE, ZCURATIONSCORE, ZMOMENT)
                VALUES (1, 'A-1', 100.0, 0, 30.25, 0.5, 7), (2, 'A-2', 200.0, 0, NULL, 0.1, 7);
            INSERT INTO ZADDITIONALASSETATTRIBUTES (Z_PK, ZASSET, ZTITLE, ZREVERSELOCATIONDATA, ZREVERSELOCATIONDATAISVALID, ZVIEWCOUNT)
                VALUES (1, 1, NULL, x'0102', 1, 0), (2, 2, 'kept', NULL, 0, 0);
            INSERT INTO ZINTERNALRESOURCE (Z_PK, ZASSET, ZLOCALAVAILABILITY, ZDATASTORESUBTYPE, ZFINGERPRINT)
                VALUES (1, 1, 1, 1, 'f1'), (2, 1, 1, 5, 'thumb'), (3, 2, -1, 1, 'f2');
            INSERT INTO ZGENERICALBUM (Z_PK, ZUUID, ZTITLE, ZKIND, ZTRASHEDSTATE, ZSTARTDATE) VALUES (1, 'AL-1', '猫咪', 2, 0, 1.0);
            INSERT INTO Z_34ASSETS VALUES (1, 1, 1);
            INSERT INTO ZKEYWORD (Z_PK, ZTITLE) VALUES (1, '_keep');
            INSERT INTO Z_1KEYWORDS VALUES (1, 1);
            INSERT INTO ZPERSON (Z_PK, ZFULLNAME, ZFACECOUNT) VALUES (1, '大白', 3);
            INSERT INTO ZDETECTEDFACE (Z_PK, ZPERSONFORFACE, ZASSETFORFACE, ZQUALITY) VALUES (1, 1, 1, 0.3);
            """)
        let stampPrefs: String? = nil
        func fingerprint() -> String { LibraryFingerprint.read(library: library.path)! }
        func stamp() -> LibraryStamp { LibraryStamp.read(library: library.path, systemPreferences: stampPrefs)! }

        let first = fingerprint()
        precondition(first == fingerprint(), "an untouched library must give the same fingerprint")
        print("ok: stable on an untouched library")

        // System writes seen on a real library (photoanalysisd, mediaanalysisd, search indexer):
        // the file stamp moves, the fingerprint must not.
        let unrelated = [
            ("analysis score on ZASSET", "UPDATE ZASSET SET ZCURATIONSCORE = 0.9, ZANALYSISSTATEMODIFICATIONDATE = 5, Z_OPT = Z_OPT + 1 WHERE Z_PK = 1"),
            ("moment reassignment", "UPDATE ZASSET SET ZMOMENT = 8 WHERE Z_PK = 2"),
            ("reverse-location validity flag only", "UPDATE ZADDITIONALASSETATTRIBUTES SET ZREVERSELOCATIONDATAISVALID = 0 WHERE Z_PK = 1"),
            ("scene analysis version and view count", "UPDATE ZADDITIONALASSETATTRIBUTES SET ZSCENEANALYSISVERSION = 9, ZVIEWCOUNT = 4, ZLASTVIEWEDDATE = 77"),
            ("knowledge graph node", "INSERT INTO ZGRAPHNODE (ZLABEL) VALUES ('Meaning')"),
            ("search index item", "INSERT INTO ZLEOITEM (ZCONTENT) VALUES ('cat')"),
            ("computed aesthetic scores", "INSERT INTO ZCOMPUTEDASSETATTRIBUTES (ZASSET, ZFAILURESCORE) VALUES (1, 0.2)"),
            ("face clustering attributes", "UPDATE ZDETECTEDFACE SET ZQUALITY = 0.8, ZCLUSTERSEQUENCENUMBER = 3; UPDATE ZPERSON SET ZFACECOUNT = 4, ZKEYFACE = 1"),
            ("thumbnail resource availability", "UPDATE ZINTERNALRESOURCE SET ZLOCALAVAILABILITY = -1 WHERE Z_PK = 2"),
            ("album date range and sort order", "UPDATE ZGENERICALBUM SET ZSTARTDATE = 2.0, ZCUSTOMSORTKEY = 9; UPDATE Z_34ASSETS SET Z_FOK_3ASSETS = 5"),
            ("key-asset table of another relationship", "INSERT INTO Z_33KEYASSETS VALUES (1, 2)"),
        ]
        for (what, sql) in unrelated {
            let before = stamp()
            try db.exec(sql)
            precondition(stamp() != before, "\(what): the write must move the file stamp")
            precondition(fingerprint() == first, "\(what) must not count as a change")
            print("ok: ignores", what)
        }

        // Writes that change what PhotoDesk shows, or its recognition cache keys.
        let related = [
            ("new photo", "INSERT INTO ZASSET (Z_PK, ZUUID, ZMODIFICATIONDATE) VALUES (3, 'A-3', 300.0); INSERT INTO ZADDITIONALASSETATTRIBUTES (Z_PK, ZASSET) VALUES (3, 3)"),
            ("deleted photo", "DELETE FROM ZASSET WHERE Z_PK = 3; DELETE FROM ZADDITIONALASSETATTRIBUTES WHERE Z_PK = 3"),
            ("title", "UPDATE ZADDITIONALASSETATTRIBUTES SET ZTITLE = '会议' WHERE Z_PK = 1"),
            ("reverse-geocoded place", "UPDATE ZADDITIONALASSETATTRIBUTES SET ZREVERSELOCATIONDATA = x'0103' WHERE Z_PK = 1"),
            ("modification date (cache key)", "UPDATE ZASSET SET ZMODIFICATIONDATE = 101.0 WHERE Z_PK = 1"),
            ("hidden", "UPDATE ZASSET SET ZHIDDEN = 1 WHERE Z_PK = 2"),
            ("trashed", "UPDATE ZASSET SET ZTRASHEDSTATE = 1 WHERE Z_PK = 2"),
            ("location", "UPDATE ZASSET SET ZLATITUDE = 30.26 WHERE Z_PK = 1"),
            ("added to an album", "INSERT INTO Z_34ASSETS VALUES (1, 2, 2)"),
            ("album renamed", "UPDATE ZGENERICALBUM SET ZTITLE = '猫' WHERE Z_PK = 1"),
            ("keyword added", "INSERT INTO Z_1KEYWORDS VALUES (2, 1)"),
            ("person named", "UPDATE ZPERSON SET ZFULLNAME = '小白' WHERE Z_PK = 1"),
            ("face assigned to another asset", "UPDATE ZDETECTEDFACE SET ZASSETFORFACE = 2 WHERE Z_PK = 1"),
            ("original downloaded from iCloud", "UPDATE ZINTERNALRESOURCE SET ZLOCALAVAILABILITY = 1 WHERE Z_PK = 3"),
            ("description", "INSERT INTO ZASSETDESCRIPTION (Z_PK, ZLONGDESCRIPTION) VALUES (1, '说明')"),
            ("library model version", "INSERT INTO Z_METADATA VALUES (2, 'y', x'00')"),
        ]
        var previous = first
        for (what, sql) in related {
            try db.exec(sql)
            let now = fingerprint()
            precondition(now != previous, "\(what) must count as a change")
            previous = now
            print("ok: detects", what)
        }

        // A write transaction another process holds open is not visible and does not block.
        try db.exec("BEGIN IMMEDIATE; UPDATE ZADDITIONALASSETATTRIBUTES SET ZTITLE = 'pending' WHERE Z_PK = 2")
        precondition(fingerprint() == previous, "uncommitted writes must not be read")
        try db.exec("COMMIT")
        precondition(fingerprint() != previous, "the commit must be read")
        print("ok: reads only committed state without blocking the writer")

        // Unknown schema: the caller must fall back to rebuilding, never to "unchanged".
        try db.exec("CREATE TABLE Z_35ASSETS (Z_35ALBUMS INTEGER, Z_3ASSETS INTEGER)")
        precondition(LibraryFingerprint.read(library: library.path) == nil, "two album-join candidates are ambiguous")
        try db.exec("DROP TABLE Z_35ASSETS; ALTER TABLE ZPERSON RENAME COLUMN ZFULLNAME TO ZNAME")
        precondition(LibraryFingerprint.read(library: library.path) == nil, "a renamed column must give nil")
        try db.exec("ALTER TABLE ZPERSON RENAME COLUMN ZNAME TO ZFULLNAME; DROP TABLE ZSHARE")
        precondition(LibraryFingerprint.read(library: library.path) == nil, "a missing table must give nil")
        try db.exec("CREATE TABLE ZSHARE (Z_PK INTEGER PRIMARY KEY, ZUUID, ZTITLE, ZCLOUDLOCALSTATE, ZTRASHEDSTATE)")
        precondition(LibraryFingerprint.read(library: root.path) == nil, "not a Photos library")
        print("ok: unknown schema gives nil")

        // LibraryBaseline.check: the decision the automatic check makes after each interval.
        let settle = Duration.milliseconds(300), maxWait = Duration.seconds(3)
        guard let base = await LibraryBaseline.probe(library: library.path, systemPreferences: stampPrefs) else { fatalError("probe") }
        let outcome1 = try await base.check(settle: settle, maxWait: maxWait)
        precondition(outcome1 == .unchanged(base))
        print("ok: untouched library is skipped without reading the database")

        try db.exec("INSERT INTO ZGRAPHNODE (ZLABEL) VALUES ('Trip')")
        guard case .unchanged(let advanced) = try await base.check(settle: settle, maxWait: maxWait) else { fatalError("unrelated write rebuilt") }
        precondition(advanced.stamp != base.stamp && advanced.fingerprint == base.fingerprint, "the baseline must advance to the new stamp")
        let outcome2 = try await advanced.check(settle: settle, maxWait: maxWait)
        precondition(outcome2 == .unchanged(advanced), "no second fingerprint read for the same stamp")
        print("ok: unrelated write only advances the baseline")

        try db.exec("UPDATE ZADDITIONALASSETATTRIBUTES SET ZTITLE = '新的' WHERE Z_PK = 1")
        let outcome3 = try await advanced.check(settle: settle, maxWait: maxWait)
        precondition(outcome3 == .rebuild)
        print("ok: related write rebuilds")

        // A burst (import) is coalesced: the check returns only after the writes stop.
        guard let quiet = await LibraryBaseline.probe(library: library.path, systemPreferences: stampPrefs) else { fatalError("probe") }
        let writer = Task.detached {
            let other = try Database(path)
            for index in 0..<8 {
                try other.exec("INSERT INTO ZASSET (ZUUID) VALUES ('burst-\(index)')")
                try await Task.sleep(for: .milliseconds(150))
            }
        }
        try await Task.sleep(for: .milliseconds(50))
        let clock = ContinuousClock(), startedCheck = clock.now
        let outcome4 = try await quiet.check(settle: settle, maxWait: maxWait)
        precondition(outcome4 == .rebuild)
        try await writer.value
        let waited = clock.now - startedCheck
        precondition(waited >= .milliseconds(1100), "the check must wait for the burst to settle, waited \(waited)")
        print("ok: a burst of writes waits until quiet, then rebuilds once (\(waited))")

        // Continuous writes cannot postpone a rebuild beyond maxWait.
        guard let busy = await LibraryBaseline.probe(library: library.path, systemPreferences: stampPrefs) else { fatalError("probe") }
        let flood = Task.detached {
            let other = try Database(path)
            while !Task.isCancelled {
                try other.exec("INSERT INTO ZASSET (ZUUID) VALUES ('flood')")
                try await Task.sleep(for: .milliseconds(100))
            }
        }
        try await Task.sleep(for: .milliseconds(50))
        let floodStart = clock.now
        let outcome5 = try await busy.check(settle: settle, maxWait: .seconds(1))
        precondition(outcome5 == .rebuild)
        let floodWait = clock.now - floodStart
        flood.cancel(); _ = try? await flood.value
        precondition(floodWait < .milliseconds(1800), "maxWait must bound the wait, waited \(floodWait)")
        print("ok: continuous writes still rebuild within maxWait (\(floodWait))")

        // First run while following the system library: the baseline is taken after the run and
        // only trusted if nothing was written once the run started.
        try await Task.sleep(for: .milliseconds(50))
        let runStart = Date()
        try await Task.sleep(for: .milliseconds(50))
        let settledOK = await LibraryBaseline.settled(library: library.path, systemPreferences: stampPrefs, before: runStart)
        precondition(settledOK?.fingerprint == fingerprint(), "no write since the run started: the baseline is valid")
        let writeStart = Date()
        try await Task.sleep(for: .milliseconds(50))
        try db.exec("INSERT INTO ZGRAPHNODE (ZLABEL) VALUES ('during run')")
        let settledLate = await LibraryBaseline.settled(library: library.path, systemPreferences: stampPrefs, before: writeStart)
        precondition(settledLate == nil, "a write during the run must leave no baseline")
        print("ok: a baseline taken after a run is only kept when nothing was written during it")

        // Stamp-only fallback when the fingerprint cannot be read.
        let blind = LibraryBaseline(stamp: stamp(), fingerprint: nil)
        let outcome6 = try await blind.check(settle: settle, maxWait: maxWait)
        precondition(outcome6 == .unchanged(blind))
        try db.exec("INSERT INTO ZGRAPHNODE (ZLABEL) VALUES ('x')")
        let outcome7 = try await blind.check(settle: settle, maxWait: maxWait)
        precondition(outcome7 == .rebuild, "without a fingerprint any write rebuilds")
        print("LibraryFingerprint checks passed")
    }
}

final class Database {
    let handle: OpaquePointer
    init(_ path: String) throws {
        var db: OpaquePointer?
        guard sqlite3_open(path, &db) == SQLITE_OK, let db else { throw NSError(domain: "db", code: 1) }
        sqlite3_busy_timeout(db, 5000)
        handle = db
    }
    func exec(_ sql: String) throws {
        var message: UnsafeMutablePointer<CChar>?
        guard sqlite3_exec(handle, sql, nil, nil, &message) == SQLITE_OK else {
            let text = message.map { String(cString: $0) } ?? "?"
            sqlite3_free(message)
            throw NSError(domain: "db", code: 2, userInfo: [NSLocalizedDescriptionKey: "\(text): \(sql)"])
        }
    }
    deinit { sqlite3_close(handle) }
}
