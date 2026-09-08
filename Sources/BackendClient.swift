import Foundation
import Darwin

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
