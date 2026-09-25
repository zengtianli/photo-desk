import Foundation
import CryptoKit
import SQLite3

struct Envelope<T: Decodable>: Decodable { let ok: Bool; let error: String?; let data: T? }
struct Probe: Decodable { let ok: Bool; let error: String? }
struct PingResult: Decodable { let message: String; let version: String; let dataRoot: String }
struct LibrarySummary: Decodable {
    let library: String
    let total: Int
    let photos: Int
    let movies: Int
    let favorites: Int
    let live: Int
    let shared: Int
    let local: Int
    let byYear: [String: Int]
    let albums: [String: Int]
    let generated: String
    let message: String
}
struct PlanRow: Decodable, Identifiable {
    let id: String
    let cloudGuid: String
    let localUuid: String?
    let filename: String
    let date: String
    let action: String
    let target: String
    let note: String
    let previewPath: String
    let originalPath: String?
    let isMovie: Bool?
    let originalTitle: String
    let protected: String
    let group: String
    let recommended: Bool?
    let readOnly: Bool?
    var actionName: String {
        switch action { case "add-album": return "加入相册"; case "add-keyword": return "添加标签"; case "set-title": return "补充标题"; default: return "人工核对" }
    }
}
struct PhotoPlan: Decodable, Identifiable {
    let id: String
    let kind: String
    let library: String
    let created: String
    let examined: Int
    let warnings: [String]
    let csvPath: String
    let rows: [PlanRow]
    var isReadOnly: Bool { ["duplicates", "library", "journey"].contains(kind) }
    var groups: [String] { Array(Set(rows.map(\.group))).sorted(by: kind == "library" ? (>) : (<)) }
}
struct ApplyResult: Decodable { let message: String; let changed: Int; let receiptPath: String? }
struct HistoryEntry: Decodable, Identifiable {
    let id: String; let kind: String; let created: String; let library: String; let count: Int
}
struct HistoryResult: Decodable { let entries: [HistoryEntry] }
struct WorkProgress: Decodable { let message: String; let done: Int; let total: Int }

enum Page: String, CaseIterable, Identifiable {
    case journey, overview, library, classify, triage, sensitive, title, duplicates, history
    var id: String { rawValue }
    var name: String {
        switch self {
        case .journey: return "我的时间线"
        case .overview: return "图库概览"
        case .library: return "全部照片"
        case .classify: return "分类整理"
        case .triage: return "截图与票据"
        case .sensitive: return "敏感照片"
        case .title: return "照片标题"
        case .duplicates: return "重复核对"
        case .history: return "整理记录"
        }
    }
    var symbol: String {
        switch self {
        case .journey: return "sparkles.rectangle.stack"
        case .overview: return "square.grid.2x2"
        case .library: return "photo.on.rectangle"
        case .classify: return "folder.badge.plus"
        case .triage: return "doc.viewfinder"
        case .sensitive: return "lock.shield"
        case .title: return "textformat.abc"
        case .duplicates: return "square.on.square"
        case .history: return "clock.arrow.circlepath"
        }
    }
    var detail: String {
        switch self {
        case .journey: return "把生活、猫咪和工作中的照片联系起来；打开即自动整理，新照片持续归入。"
        case .overview: return "看看照片都在哪里，再开始整理。"
        case .library: return "浏览、放大查看和删除所选照片；按月份分组，最新照片在前。"
        case .classify: return "按年月、人物和场景归入相册，已有分类自动跳过。"
        case .triage: return "本地识别截图和文档，票据保留，拿不准的留给你核对。"
        case .sensitive: return "查找含证件、银行卡或手机号的照片，标记为敏感档案。"
        case .title: return "用拍摄时间、地点和人物补充空标题，保留已有标题。"
        case .duplicates: return "查找相同原片指纹，逐张核对编辑效果和 Live Photo。"
        case .history: return "继续查看之前生成的建议，或在 Finder 中查看操作记录。"
        }
    }
    var usesOCR: Bool { self == .triage || self == .sensitive }
}

struct DeletionItem: Codable, Identifiable {
    let uuid: String
    let cloudGuid: String
    let filename: String
    let protected: String
    var id: String { uuid }
}
struct DeletionPreview: Decodable {
    let planId: String
    let library: String
    let items: [DeletionItem]
}
struct DeletionOutcome { let count: Int; let verified: Bool }

struct JourneyEvent: Decodable, Identifiable {
    let id: String; let title: String; let group: String; let date: String; let endDate: String
    let count: Int; let tracks: [String]; let people: [String]; let place: String
    let evidence: [String]; let cover: PlanRow
}
struct JourneyResult: Decodable {
    let library: String; let generated: String; let total: Int; let analyzed: Int
    let pending: Int; let unavailable: Int; let failed: Int; let albums: Int
    let events: [JourneyEvent]; let tracks: [String]; let plan: PhotoPlan; let duplicates: PhotoPlan
    /// Content digest of this result without its timestamps (backend/journey.py `content_digest`).
    let digest: String?
}
/// Engine reply when the rebuilt result equals the one the app already shows (`previous_digest`):
/// nothing is sent, decoded or redrawn, and the engine leaves its files untouched.
struct JourneyUnchanged: Decodable { let unchanged: Bool?; let digest: String? }
enum JourneyOutcome { case changed(JourneyResult); case unchanged(String) }

/// Cheap change stamp of the Photos library the engine last rebuilt from. The automatic
/// check compares it before relaunching the engine, so an unchanged library costs a few
/// stat calls instead of a full rebuild (measured ~7–8 s engine CPU and ~13 MB of rewritten
/// index files per run on a 6,373-item library). Any write by Photos lands in the database
/// or its WAL and changes mtime/size; an unreadable database yields nil, which always rebuilds.
struct LibraryStamp: Equatable {
    let library: String
    let systemPreferences: String?
    private let files: [String: [Int64]]

    /// `systemPreferences` is Photos' own preferences file, included when PhotoDesk follows
    /// the library Photos last opened, so switching the system library is also a change.
    static func read(library: String, systemPreferences: String?) -> LibraryStamp? {
        guard library.hasSuffix(".photoslibrary") else { return nil }
        let database = URL(fileURLWithPath: library).appendingPathComponent("database")
        let main = database.appendingPathComponent("Photos.sqlite").path
        var files: [String: [Int64]] = [:]
        for path in [main, main + "-wal"] + (systemPreferences.map { [$0] } ?? []) {
            var info = stat()
            if stat(path, &info) == 0 {
                files[path] = [Int64(info.st_mtimespec.tv_sec) * 1_000_000_000 + Int64(info.st_mtimespec.tv_nsec), Int64(info.st_size)]
            } else if path == main {
                return nil
            } else {
                files[path] = []
            }
        }
        return LibraryStamp(library: library, systemPreferences: systemPreferences, files: files)
    }

    func current() -> LibraryStamp? { Self.read(library: library, systemPreferences: systemPreferences) }

    /// Only a stamp whose files were all last written before the rebuild started describes
    /// what the rebuild read; a write during the run must trigger the next rebuild.
    func settled(before start: Date) -> Bool {
        let limit = Int64((start.timeIntervalSince1970 * 1_000_000_000).rounded(.down))
        return files.values.allSatisfy { $0.isEmpty || $0[0] < limit }
    }

    static var photosPreferences: String {
        FileManager.default.homeDirectoryForCurrentUser
            .appendingPathComponent("Library/Containers/com.apple.Photos/Data/Library/Preferences/com.apple.Photos.plist").path
    }
}

/// Digest of the Photos database content that can change what the engine produces.
///
/// The system writes the library all the time without touching anything PhotoDesk shows:
/// photoanalysisd rebuilds its knowledge graph (ZGRAPHNODE/ZGRAPHEDGE), highlights, memories
/// and suggestions; the search indexer writes ZLEOITEM and its FTS tables; analysis daemons
/// update scores and analysis state. Those writes change the file stamp every 1–5 minutes.
/// This fingerprint reads, with a read-only connection inside one read transaction, only the
/// columns behind the osxphotos properties that backend/journey.py and bridge.item use
/// (uuid, dates and time zone, location and reverse-geocoded place, kind/subtype, hidden,
/// favorite, trash/visibility, title, description, keywords, albums, persons, cloud/shared
/// state, original resource availability and size, adjustments). Columns osxphotos also reads
/// but the engine never uses (scores, EXIF, face attributes, comments, moments, import
/// sessions) are left out on purpose. tests/fingerprint_coverage.py traces the SQL a real
/// engine run issues and fails when it starts to depend on a table this list lacks.
///
/// nil means "unknown" (missing database or table, renamed column, busy): the caller rebuilds.
enum LibraryFingerprint {
    static let asset = ["Z_PK", "ZUUID", "ZMODIFICATIONDATE", "ZDATECREATED", "ZHIDDEN", "ZFAVORITE", "ZDIRECTORY",
        "ZFILENAME", "ZLATITUDE", "ZLONGITUDE", "ZADJUSTMENTSSTATE", "ZCLOUDBATCHPUBLISHDATE", "ZKIND",
        "ZUNIFORMTYPEIDENTIFIER", "ZAVALANCHEUUID", "ZAVALANCHEPICKTYPE", "ZKINDSUBTYPE", "ZHDRTYPE", "ZCLOUDASSETGUID",
        "ZTRASHEDSTATE", "ZHEIGHT", "ZWIDTH", "ZORIENTATION", "ZDEPTHTYPE", "ZADJUSTMENTTIMESTAMP", "ZVISIBILITYSTATE",
        "ZTRASHEDDATE", "ZSAVEDASSETTYPE", "ZADDEDDATE", "ZCLOUDOWNERHASHEDPERSONID", "ZMOMENTSHARE", "ZMASTER",
        "ZCOLLECTIONSHARE", "ZSYNDICATIONSTATE", "ZACTIVELIBRARYSCOPEPARTICIPATIONSTATE", "ZLIBRARYSCOPESHARESTATE",
        "ZLIBRARYSCOPE"]
    static let attributes = ["Z_PK", "ZASSET", "ZORIGINALSTABLEHASH", "ZTITLE", "ZORIGINALFILENAME", "ZTIMEZONEOFFSET",
        "ZINFERREDTIMEZONEOFFSET", "ZTIMEZONENAME", "ZCAMERACAPTUREDEVICE", "ZREVERSELOCATIONDATA",
        "ZORIGINALRESOURCECHOICE", "ZORIGINALHEIGHT", "ZORIGINALWIDTH", "ZORIGINALORIENTATION", "ZORIGINALFILESIZE",
        "ZIMPORTEDBYDISPLAYNAME", "ZIMPORTEDBYBUNDLEIDENTIFIER", "ZASSETDESCRIPTION", "ZUNMANAGEDADJUSTMENT",
        "ZSYNDICATIONHISTORY", "ZSYNDICATIONIDENTIFIER"]
    /// (table, columns, filter). Rows are hashed in primary-key order.
    static let tables: [(String, [String], String)] = [
        ("ZASSET", asset, ""),
        ("ZADDITIONALASSETATTRIBUTES", attributes, ""),
        // The rows osxphotos reads: originals/alternates (1, 3), referenced files (17), and the
        // resource matching each asset's original fingerprint. Thumbnail churn is not included.
        ("ZINTERNALRESOURCE", ["Z_PK", "ZASSET", "ZLOCALAVAILABILITY", "ZREMOTEAVAILABILITY", "ZDATASTORESUBTYPE",
            "ZCOMPACTUTI", "ZFINGERPRINT", "ZDATALENGTH", "ZRESOURCETYPE", "ZFILESYSTEMBOOKMARK", "ZFILESYSTEMVOLUME"],
         "WHERE ZDATASTORESUBTYPE IN (1, 3, 17) OR ZFINGERPRINT IN (SELECT ZORIGINALSTABLEHASH FROM ZADDITIONALASSETATTRIBUTES)"),
        ("ZCLOUDMASTER", ["Z_PK", "ZCLOUDLOCALSTATE", "ZCLOUDMASTERGUID"], ""),
        ("ZGENERICALBUM", ["Z_PK", "ZUUID", "ZTITLE", "ZCLOUDLOCALSTATE", "ZCLOUDOWNERFIRSTNAME", "ZCLOUDOWNERLASTNAME",
            "ZCLOUDOWNERHASHEDPERSONID", "ZKIND", "ZPARENTFOLDER", "ZTRASHEDSTATE"], ""),
        ("ZSHARE", ["Z_PK", "ZUUID", "ZTITLE", "ZCLOUDLOCALSTATE", "ZTRASHEDSTATE"], ""),
        ("ZKEYWORD", ["Z_PK", "ZTITLE"], ""),
        ("ZPERSON", ["Z_PK", "ZPERSONUUID", "ZFULLNAME", "ZDISPLAYNAME", "ZTYPE"], ""),
        ("ZDETECTEDFACE", ["Z_PK", "ZPERSONFORFACE", "ZASSETFORFACE"], ""),
        ("ZASSETDESCRIPTION", ["Z_PK", "ZLONGDESCRIPTION"], ""),
        ("ZUNMANAGEDADJUSTMENT", ["Z_PK", "ZADJUSTMENTFORMATIDENTIFIER"], ""),
        ("ZFILESYSTEMVOLUME", ["Z_PK", "ZUUID", "ZNAME"], ""),
        ("ZFILESYSTEMBOOKMARK", ["Z_PK", "ZRESOURCE", "ZPATHRELATIVETOVOLUME"], ""),
    ]

    static func read(library: String) -> String? {
        guard library.hasSuffix(".photoslibrary") else { return nil }
        let path = URL(fileURLWithPath: library).appendingPathComponent("database/Photos.sqlite").path
        guard FileManager.default.fileExists(atPath: path) else { return nil }
        var db: OpaquePointer?
        guard sqlite3_open_v2(path, &db, SQLITE_OPEN_READONLY | SQLITE_OPEN_NOMUTEX, nil) == SQLITE_OK, let db else {
            sqlite3_close(db); return nil
        }
        defer { sqlite3_close(db) }
        sqlite3_busy_timeout(db, 2000)
        guard sqlite3_exec(db, "BEGIN", nil, nil, nil) == SQLITE_OK else { return nil }
        defer { sqlite3_exec(db, "COMMIT", nil, nil, nil) }
        var queries = tables.map { table, columns, filter in
            (table, "SELECT \(columns.joined(separator: ", ")) FROM \(table) \(filter) ORDER BY Z_PK")
        }
        // Album membership and keyword join tables are named after entity numbers that differ
        // between Photos versions (Z_34ASSETS, Z_1KEYWORDS here); osxphotos resolves them the same way.
        for (pattern, partner) in [("^Z_[0-9]+ASSETS$", "ALBUMS"), ("^Z_[0-9]+KEYWORDS$", "KEYWORDS")] {
            let joins = joinTables(db, pattern: pattern, partner: partner)
            guard joins.count == 1, let (table, columns) = joins.first else { return nil }
            queries.append((table, "SELECT \(columns.joined(separator: ", ")) FROM \(table) ORDER BY \(columns.joined(separator: ", "))"))
        }
        queries.append(("Z_METADATA", "SELECT MAX(Z_VERSION) FROM Z_METADATA"))
        var hasher = SHA256()
        var buffer: [UInt8] = []
        buffer.reserveCapacity(1 << 16)
        func flush() { hasher.update(data: buffer); buffer.removeAll(keepingCapacity: true) }
        for (table, sql) in queries {
            var statement: OpaquePointer?
            guard sqlite3_prepare_v2(db, sql, -1, &statement, nil) == SQLITE_OK, let statement else {
                sqlite3_finalize(statement); return nil
            }
            defer { sqlite3_finalize(statement) }
            buffer.append(contentsOf: Array(table.utf8)); buffer.append(0)
            let count = sqlite3_column_count(statement)
            var step = sqlite3_step(statement)
            while step == SQLITE_ROW {
                for column in 0..<count {
                    let type = sqlite3_column_type(statement, column)
                    buffer.append(UInt8(type))
                    switch type {
                    case SQLITE_INTEGER: withUnsafeBytes(of: sqlite3_column_int64(statement, column).littleEndian) { buffer.append(contentsOf: $0) }
                    case SQLITE_FLOAT: withUnsafeBytes(of: sqlite3_column_double(statement, column).bitPattern.littleEndian) { buffer.append(contentsOf: $0) }
                    case SQLITE_TEXT, SQLITE_BLOB:
                        let bytes = Int(sqlite3_column_bytes(statement, column))
                        withUnsafeBytes(of: Int64(bytes).littleEndian) { buffer.append(contentsOf: $0) }
                        let pointer = type == SQLITE_TEXT ? UnsafeRawPointer(sqlite3_column_text(statement, column)) : sqlite3_column_blob(statement, column)
                        if let pointer, bytes > 0 { buffer.append(contentsOf: UnsafeRawBufferPointer(start: pointer, count: bytes)) }
                    default: break
                    }
                }
                if buffer.count >= 1 << 16 { flush() }
                step = sqlite3_step(statement)
            }
            guard step == SQLITE_DONE else { return nil }
        }
        flush()
        return hasher.finalize().map { String(format: "%02x", $0) }.joined()
    }

    private static func joinTables(_ db: OpaquePointer, pattern: String, partner: String) -> [(String, [String])] {
        var names: [String] = []
        var statement: OpaquePointer?
        if sqlite3_prepare_v2(db, "SELECT name FROM sqlite_master WHERE type = 'table' ORDER BY name", -1, &statement, nil) == SQLITE_OK {
            while sqlite3_step(statement) == SQLITE_ROW {
                if let text = sqlite3_column_text(statement, 0) { names.append(String(cString: text)) }
            }
        }
        sqlite3_finalize(statement)
        return names.filter { $0.range(of: pattern, options: .regularExpression) != nil }.compactMap { name in
            var columns: [String] = []
            var info: OpaquePointer?
            if sqlite3_prepare_v2(db, "PRAGMA table_info(\(name))", -1, &info, nil) == SQLITE_OK {
                while sqlite3_step(info) == SQLITE_ROW {
                    if let text = sqlite3_column_text(info, 1) { columns.append(String(cString: text)) }
                }
            }
            sqlite3_finalize(info)
            // Z_FOK_* is the manual sort position inside an album, which PhotoDesk does not use.
            columns = columns.filter { !$0.hasPrefix("Z_FOK_") }
            return columns.contains(where: { $0.hasSuffix(partner) }) ? (name, columns) : nil
        }
    }
}

/// What the current timeline was built from. The automatic check skips the engine while the
/// stamp is unchanged, and also when the stamp moved but the fingerprint did not. Without a
/// readable fingerprint (older schema, demo) it falls back to the stamp alone.
struct LibraryBaseline: Equatable {
    let stamp: LibraryStamp
    let fingerprint: String?

    /// Stamp first, then fingerprint: a write between the two is either inside the fingerprint
    /// (and read by a rebuild that starts afterwards) or moves the stamp again.
    static func probe(library: String, systemPreferences: String?) async -> LibraryBaseline? {
        await Task.detached(priority: .utility) {
            guard let stamp = LibraryStamp.read(library: library, systemPreferences: systemPreferences) else { return nil }
            return LibraryBaseline(stamp: stamp, fingerprint: LibraryFingerprint.read(library: library))
        }.value
    }

    /// For a rebuild whose library path was unknown before it ran (first run while following the
    /// system library): valid only if nothing was written after the rebuild started and the
    /// stamp did not move while the fingerprint was read.
    static func settled(library: String, systemPreferences: String?, before start: Date) async -> LibraryBaseline? {
        await Task.detached(priority: .utility) {
            guard let first = LibraryStamp.read(library: library, systemPreferences: systemPreferences),
                  first.settled(before: start) else { return nil }
            let fingerprint = LibraryFingerprint.read(library: library)
            guard LibraryStamp.read(library: library, systemPreferences: systemPreferences) == first else { return nil }
            return LibraryBaseline(stamp: first, fingerprint: fingerprint)
        }.value
    }

    /// Whether a probe taken before a run describes the library the run reported.
    func describes(_ library: String) -> Bool { Self.canonical(stamp.library) == Self.canonical(library) }
    private static func canonical(_ path: String) -> String {
        guard let resolved = realpath(path, nil) else { return path }
        defer { free(resolved) }
        return String(cString: resolved)
    }

    enum Check: Equatable { case unchanged(LibraryBaseline), rebuild }

    /// One automatic check. Returns `.unchanged` with an advanced baseline when nothing the
    /// engine reads changed. When the files moved, waits until they stay put for `settle`
    /// (a burst of writes, e.g. an import, becomes one rebuild), but no longer than `maxWait`.
    func check(settle: Duration, maxWait: Duration) async throws -> Check {
        let library = stamp.library, preferences = stamp.systemPreferences
        func readStamp() async -> LibraryStamp? {
            await Task.detached(priority: .utility) { LibraryStamp.read(library: library, systemPreferences: preferences) }.value
        }
        guard var latest = await readStamp() else { return .rebuild }
        if latest == stamp { return .unchanged(self) }
        guard fingerprint != nil else { return .rebuild }
        let clock = ContinuousClock(), deadline = clock.now.advanced(by: maxWait)
        while clock.now < deadline {
            try await Task.sleep(for: settle)
            guard let next = await readStamp() else { return .rebuild }
            if next == latest { break }
            latest = next
        }
        guard let now = await Self.probe(library: library, systemPreferences: preferences),
              now.fingerprint != nil, now.fingerprint == fingerprint else { return .rebuild }
        return .unchanged(now)
    }
}

enum Contract {
    static func decode<T: Decodable>(_ type: T.Type, from data: Data) throws -> T {
        let decoder = JSONDecoder()
        decoder.keyDecodingStrategy = .convertFromSnakeCase
        let envelope = try decoder.decode(Envelope<T>.self, from: data)
        guard envelope.ok, let value = envelope.data else {
            throw NSError(domain: "PhotoDesk", code: 1, userInfo: [NSLocalizedDescriptionKey: envelope.error ?? "引擎未返回结果。"])
        }
        return value
    }
}
