import Foundation

// Regression check for LibraryStamp, the gate that lets the automatic check skip an engine
// rebuild. Build: xcrun swiftc Sources/Models.swift tests/library_stamp_check.swift -o qa/library-stamp-check
// Uses a throwaway fake .photoslibrary in a temporary directory; never touches a real library.
@main
struct LibraryStampCheck {
    static func main() throws {
        let fm = FileManager.default
        let root = fm.temporaryDirectory.appendingPathComponent("photodesk-stamp-\(UUID().uuidString)")
        defer { try? fm.removeItem(at: root) }
        let library = root.appendingPathComponent("Fake.photoslibrary")
        let database = library.appendingPathComponent("database")
        try fm.createDirectory(at: database, withIntermediateDirectories: true)
        let main = database.appendingPathComponent("Photos.sqlite")
        let wal = database.appendingPathComponent("Photos.sqlite-wal")
        let prefs = root.appendingPathComponent("com.apple.Photos.plist")
        try Data("db-v1".utf8).write(to: main)
        try Data("wal-1".utf8).write(to: wal)
        try Data("prefs-1".utf8).write(to: prefs)
        func read() -> LibraryStamp? { LibraryStamp.read(library: library.path, systemPreferences: prefs.path) }
        func changed(_ what: String, _ body: () throws -> Void) throws {
            let before = read()!
            try body()
            let after = read()
            precondition(after != before, "\(what) must count as a library change")
            print("ok:", what)
        }

        // Not a Photos library, or database unreadable: unknown, so the caller always rebuilds.
        precondition(LibraryStamp.read(library: root.path, systemPreferences: nil) == nil)
        precondition(LibraryStamp.read(library: root.appendingPathComponent("Missing.photoslibrary").path, systemPreferences: nil) == nil)

        let first = read()!
        precondition(first.current() == first, "an untouched library must compare equal")
        print("ok: untouched library is unchanged")

        try changed("WAL append (normal Photos commit)") {
            let handle = try FileHandle(forWritingTo: wal); _ = try handle.seekToEnd(); try handle.write(contentsOf: Data("+commit".utf8)); try handle.close()
        }
        try changed("same-size rewrite of the WAL") {
            // Overwrite in place (same inode, same length): only the modification time can tell.
            let size = try fm.attributesOfItem(atPath: wal.path)[.size] as! Int
            let handle = try FileHandle(forWritingTo: wal)
            try handle.seek(toOffset: 0); try handle.write(contentsOf: Data(repeating: UInt8(ascii: "x"), count: size)); try handle.close()
            let after = try fm.attributesOfItem(atPath: wal.path)[.size] as! Int
            precondition(after == size, "the rewrite must keep the WAL size")
        }
        try changed("atomic save of the database (write temp, rename over)") {
            let temporary = database.appendingPathComponent("Photos.sqlite.tmp")
            try Data("db-v2".utf8).write(to: temporary)
            _ = try fm.replaceItemAt(main, withItemAt: temporary)
        }
        try changed("rename away and recreate the WAL") {
            try fm.moveItem(at: wal, to: database.appendingPathComponent("old-wal"))
        }
        try changed("WAL created again after checkpoint removal") { try Data("wal-3".utf8).write(to: wal) }
        try changed("delete and recreate the database") {
            try fm.removeItem(at: main); try Data("db-v3".utf8).write(to: main)
        }
        try changed("Photos switches the system library (preferences rewritten)") {
            try Data("prefs-2".utf8).write(to: prefs, options: .atomic)
        }
        try fm.removeItem(at: main)
        precondition(read() == nil, "a missing database must never be treated as unchanged")
        try Data("db-v4".utf8).write(to: main)
        print("ok: missing database forces a rebuild")

        // A stamp taken after a rebuild is only trusted if nothing was written once the rebuild began.
        let beforeWrite = Date()
        Thread.sleep(forTimeInterval: 0.05)
        try Data("wal-4".utf8).write(to: wal)
        precondition(!read()!.settled(before: beforeWrite), "a write during the rebuild must not be trusted")
        Thread.sleep(forTimeInterval: 0.05)
        precondition(read()!.settled(before: Date()), "files last written before the rebuild are trusted")
        print("ok: writes during a rebuild force the next rebuild")

        // Without following the system library, the Photos preferences file is not consulted.
        let pinned = LibraryStamp.read(library: library.path, systemPreferences: nil)!
        try Data("prefs-3".utf8).write(to: prefs, options: .atomic)
        precondition(pinned.current() == pinned)
        print("LibraryStamp checks passed")
    }
}
