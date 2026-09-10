import Foundation
import Darwin
import Photos
import AppKit

// Based on the fleet Process adapter: concurrent stdout/stderr drains, stdin after
// launch, timeout and cancellation. The executable and Python runtime are bundled.
private final class Buffer: @unchecked Sendable { var data = Data() }
final class ProcessSlot: @unchecked Sendable {
    private let lock = NSLock()
    private var process: Process?
    private var stopped = false
    func install(_ value: Process) throws {
        lock.lock(); defer { lock.unlock() }
        if stopped { throw CancellationError() }
        process = value
        try value.run()
    }
    func stop() {
        lock.lock(); stopped = true; let p = process; lock.unlock()
        guard let p, p.isRunning else { return }
        p.terminate()
        DispatchQueue.global().asyncAfter(deadline: .now() + 3) {
            if p.isRunning { kill(p.processIdentifier, SIGKILL) }
        }
    }
}

actor BackendClient {
    func execute<T: Decodable>(_ type: T.Type, request: [String: Any]) async throws -> T {
        guard let resources = Bundle.main.resourceURL else { throw failure("应用资源缺失，请重新安装。") }
        let executable = resources.appendingPathComponent("Engine/photo-engine")
        guard FileManager.default.isExecutableFile(atPath: executable.path) else { throw failure("内置整理引擎缺失，请重新安装。") }
        let input = try JSONSerialization.data(withJSONObject: request)
        let data = try await run(executable: executable, input: input)
        return try Contract.decode(type, from: data)
    }

    private func failure(_ message: String) -> NSError {
        NSError(domain: "PhotoDesk", code: 1, userInfo: [NSLocalizedDescriptionKey: message])
    }

    private func run(executable: URL, input: Data) async throws -> Data {
        let slot = ProcessSlot()
        return try await withTaskCancellationHandler {
            try await withCheckedThrowingContinuation { continuation in
                let process = Process()
                process.executableURL = executable
                var environment = ProcessInfo.processInfo.environment
                environment["PATH"] = "/usr/bin:/bin:/usr/sbin:/sbin"
                environment.removeValue(forKey: "PYTHONPATH")
                environment.removeValue(forKey: "PYTHONHOME")
                process.environment = environment
                let output = Pipe(), error = Pipe(), stdin = Pipe()
                process.standardOutput = output; process.standardError = error; process.standardInput = stdin
                let queue = DispatchQueue(label: "PhotoDesk.io", attributes: .concurrent)
                let group = DispatchGroup(), out = Buffer(), err = Buffer()
                do { try slot.install(process) }
                catch { continuation.resume(throwing: error); return }
                for (pipe, box) in [(output, out), (error, err)] {
                    group.enter()
                    queue.async { box.data = pipe.fileHandleForReading.readDataToEndOfFile(); group.leave() }
                }
                queue.async {
                    try? stdin.fileHandleForWriting.write(contentsOf: input)
                    try? stdin.fileHandleForWriting.close()
                }
                let timeout = DispatchWorkItem { slot.stop() }
                queue.asyncAfter(deadline: .now() + 3600, execute: timeout)
                queue.async {
                    process.waitUntilExit(); group.wait(); timeout.cancel()
                    if process.terminationStatus != 0 {
                        let detail = String(decoding: err.data.suffix(2000), as: UTF8.self)
                        continuation.resume(throwing: NSError(domain: "PhotoDesk", code: Int(process.terminationStatus), userInfo: [NSLocalizedDescriptionKey: "整理任务已停止。\n\(detail)"]))
                    } else { continuation.resume(returning: out.data) }
                }
            }
        } onCancel: { slot.stop() }
    }
}

/// PhotoKit owns the deletion transaction and its system confirmation. Never alter
/// .photoslibrary files or turn an algorithm's suggestions into automatic deletion.
@MainActor
enum NativePhotos {
    private static func requireRealLibrary() throws {
        if ProcessInfo.processInfo.environment["PHOTODESK_DEMO_ROOT"] != nil {
            throw fail("合成演示图库不连接 Apple“照片”；写入、删除和系统定位均未执行。")
        }
    }
    static func reveal(_ uuid: String?) throws {
        try requireRealLibrary()
        guard let uuid, let assetID = UUID(uuidString: uuid) else {
            throw fail("这张照片缺少本地标识，请刷新列表后重试。")
        }
        // Photos' installed scripting dictionary exposes spotlight(media item).
        // Only a parsed UUID is interpolated; filenames and user text are not code.
        let source = """
        tell application id "com.apple.Photos"
            activate
            spotlight (media item id "\(assetID.uuidString)/L0/001")
        end tell
        """
        guard let script = NSAppleScript(source: source) else { throw fail("无法创建照片定位请求。") }
        var detail: NSDictionary?
        script.executeAndReturnError(&detail)
        if let detail {
            let code = detail[NSAppleScript.errorNumber] as? Int
            throw fail(code == -1743
                ? "请在系统设置 → 隐私与安全性 → 自动化中允许 PhotoDesk 控制“照片”。"
                : "未能在“照片”中定位这张图片。请确认“照片”打开的是同一个图库，并检查图片是否仍存在。")
        }
    }
    static func fail(_ message: String) -> NSError {
        NSError(domain: "PhotoDesk.Photos", code: 1, userInfo: [NSLocalizedDescriptionKey: message])
    }
    static func authorize() async throws {
        try requireRealLibrary()
        let status = await PHPhotoLibrary.requestAuthorization(for: .readWrite)
        guard status == .authorized || status == .limited else {
            throw fail("请在系统设置 → 隐私与安全性 → 照片中允许 PhotoDesk 访问照片，然后重试。")
        }
    }
    static func resolve(_ items: [DeletionItem]) throws -> [PHAsset] {
        let wanted = Set(items.map { $0.uuid.uppercased() })
        guard !wanted.isEmpty, wanted.count == items.count else { throw fail("删除清单为空或重复，请重新选择。") }
        let options = PHFetchOptions()
        options.includeHiddenAssets = true
        options.includeAssetSourceTypes = .typeUserLibrary
        var found: [String: PHAsset] = [:]
        PHAsset.fetchAssets(with: options).enumerateObjects { asset, _, _ in
            let key = String(asset.localIdentifier.split(separator: "/")[0]).uppercased()
            if wanted.contains(key) { found[key] = asset }
        }
        guard found.count == wanted.count else { throw fail("系统未能匹配全部所选照片。请检查照片权限，并刷新列表后重试；尚未删除任何照片。") }
        return items.compactMap { found[$0.uuid.uppercased()] }
    }
    static func delete(_ items: [DeletionItem], recordRoot: URL) async throws -> DeletionOutcome {
        try await authorize()
        let assets = try resolve(items)
        let identifiers = assets.map(\.localIdentifier)
        let recordURL = recordRoot.appendingPathComponent("history/delete-\(UUID().uuidString).json")
        try FileManager.default.createDirectory(at: recordURL.deletingLastPathComponent(), withIntermediateDirectories: true, attributes: [.posixPermissions: 0o700])
        func record(_ state: String, error: String = "") throws {
            let data: [String: Any] = ["operation": "delete", "state": state,
                "generated": ISO8601DateFormatter().string(from: Date()),
                "identifiers": identifiers, "filenames": items.map(\.filename), "error": error]
            try JSONSerialization.data(withJSONObject: data, options: [.prettyPrinted, .sortedKeys]).write(to: recordURL, options: .atomic)
            try FileManager.default.setAttributes([.posixPermissions: 0o600], ofItemAtPath: recordURL.path)
        }
        try record("awaiting_system_confirmation")
        do {
            try await PHPhotoLibrary.shared().performChanges {
                PHAssetChangeRequest.deleteAssets(assets as NSArray)
            }
        } catch {
            try? record("cancelled_or_failed", error: error.localizedDescription)
            throw error
        }
        var remaining = PHAsset.fetchAssets(withLocalIdentifiers: identifiers, options: nil).count
        for _ in 0..<4 where remaining > 0 {
            try? await Task.sleep(for: .milliseconds(250))
            remaining = PHAsset.fetchAssets(withLocalIdentifiers: identifiers, options: nil).count
        }
        try record(remaining == 0 ? "deleted_and_verified" : "deleted_verification_pending")
        return DeletionOutcome(count: assets.count, verified: remaining == 0)
    }

    /// Explicit diagnostic fixture: creates fresh synthetic content, never selects
    /// an existing photo. Deletion still uses the normal selection + confirmation UI.
    static func createFixture(recordRoot: URL) async throws -> String {
        try await authorize()
        let filename = "PhotoDesk-QA-\(UUID().uuidString).png"
        let image = NSImage(size: NSSize(width: 1200, height: 800))
        image.lockFocus()
        NSColor.white.setFill(); NSBezierPath(rect: NSRect(x: 0, y: 0, width: 1200, height: 800)).fill()
        ("PhotoDesk 功能验收\n可删除的测试图片\nInvoice 2026-09-08 Total USD 100.00\n测试号码 13800138000\n\(filename)" as NSString).draw(in: NSRect(x: 70, y: 150, width: 1060, height: 500), withAttributes: [.font: NSFont.systemFont(ofSize: 42), .foregroundColor: NSColor.systemTeal])
        image.unlockFocus()
        guard let tiff = image.tiffRepresentation, let rep = NSBitmapImageRep(data: tiff), let png = rep.representation(using: .png, properties: [:]) else { throw fail("无法生成测试图片。") }
        var identifier: String?
        try await PHPhotoLibrary.shared().performChanges {
            let creation = PHAssetCreationRequest.forAsset()
            let options = PHAssetResourceCreationOptions(); options.originalFilename = filename
            creation.addResource(with: .photo, data: png, options: options)
            identifier = creation.placeholderForCreatedAsset?.localIdentifier
        }
        guard let identifier, PHAsset.fetchAssets(withLocalIdentifiers: [identifier], options: nil).count == 1 else { throw fail("测试图片导入后的核对未通过。") }
        let folder = recordRoot.appendingPathComponent("diagnostics")
        try FileManager.default.createDirectory(at: folder, withIntermediateDirectories: true, attributes: [.posixPermissions: 0o700])
        let record: [String: String] = ["identifier": identifier, "filename": filename, "created": ISO8601DateFormatter().string(from: Date())]
        try JSONSerialization.data(withJSONObject: record).write(to: folder.appendingPathComponent("fixture.json"), options: .atomic)
        return filename
    }
}
