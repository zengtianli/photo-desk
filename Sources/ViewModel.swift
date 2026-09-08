import SwiftUI
import AppKit

@MainActor
final class PhotoDeskModel: ObservableObject {
    @Published var page: Page = .overview
    @Published var summary: LibrarySummary?
    @Published var plans: [Page: PhotoPlan] = [:]
    @Published var selected: Set<String> = []
    @Published var group = "全部"
    @Published var search = ""
    @Published var pageNumber = 0
    @Published var busy = false
    @Published var applying = false
    @Published var status = "准备连接你的照片图库"
    @Published var error: String?
    @Published var progress: WorkProgress?
    @Published var confirm = false
    @Published var history: [HistoryEntry] = []
    @Published var ocrLimit = 100
    @Published var library = UserDefaults.standard.string(forKey: "library") ?? ""
    let client = BackendClient()
    private var task: Task<Void, Never>?
    private var poller: Task<Void, Never>?
    private var requestID = ""
    static let dataRoot = FileManager.default.homeDirectoryForCurrentUser.appendingPathComponent("Library/Application Support/PhotoDesk")
    var plan: PhotoPlan? { plans[page] }
    var filteredRows: [PlanRow] {
        (plan?.rows ?? []).filter { (group == "全部" || $0.group == group) &&
            (search.isEmpty || [$0.filename, $0.target, $0.note, $0.date].contains { $0.localizedCaseInsensitiveContains(search) }) }
    }
    var visibleRows: [PlanRow] { Array(filteredRows.dropFirst(pageNumber * 60).prefix(60)) }
    var selectedRows: [PlanRow] { (plan?.rows ?? []).filter { selected.contains($0.id) } }

    func navigate(_ target: Page) {
        guard !busy else { return }
        page = target; group = "全部"; search = ""; pageNumber = 0
        selected = []
        if target == .history { loadHistory() }
    }
    private func request(_ command: String, extra: [String: Any] = [:]) -> [String: Any] {
        var result: [String: Any] = ["command": command, "library": library, "request_id": requestID]
        result.merge(extra) { _, new in new }; return result
    }
    private func perform(_ message: String, work: @escaping @MainActor () async throws -> Void) {
        guard !busy else { return }
        busy = true; error = nil; status = message; progress = nil; requestID = UUID().uuidString
        let url = Self.dataRoot.appendingPathComponent("progress/\(requestID).json")
        poller = Task {
            while !Task.isCancelled {
                try? await Task.sleep(for: .milliseconds(500))
                if let data = try? Data(contentsOf: url), let p = try? JSONDecoder().decode(WorkProgress.self, from: data) { progress = p }
            }
        }
        task = Task {
            defer { busy = false; applying = false; poller?.cancel(); progress = nil }
            do { try await work() }
            catch { if !Task.isCancelled { self.error = error.localizedDescription; status = "任务未完成" } else { status = "已取消；图库未改动" } }
        }
    }
    func cancel() { guard !applying else { return }; task?.cancel() }
    func refresh() {
        perform("正在读取图库…") {
            let result = try await self.client.execute(LibrarySummary.self, request: self.request("audit"))
            self.summary = result; self.status = "已读取 \(result.total.formatted()) 项个人照片与视频"
        }
    }
    func generate() {
        let target = page
        perform(target.usesOCR ? "正在本地识别…" : "正在生成整理建议…") {
            let result = try await self.client.execute(PhotoPlan.self, request: self.request("plan", extra: ["kind": target.rawValue, "limit": self.ocrLimit]))
            self.plans[target] = result; self.selected = []; self.group = "全部"; self.pageNumber = 0
            self.status = "已生成 \(result.rows.count.formatted()) 项建议，尚未写入图库"
        }
    }
    func checkBeforeApply() {
        guard let plan, !selected.isEmpty else { return }
        perform("正在核对所选照片…") {
            _ = try await self.client.execute(ApplyResult.self, request: self.request("apply", extra: ["plan_id": plan.id, "selected": Array(self.selected), "confirmed": false]))
            self.status = "预检通过，请确认本次整理"; self.confirm = true
        }
    }
    func apply() {
        guard let plan else { return }; confirm = false; applying = true
        perform("正在写入照片图库…") {
            let result = try await self.client.execute(ApplyResult.self, request: self.request("apply", extra: ["plan_id": plan.id, "selected": Array(self.selected), "confirmed": true]))
            self.status = result.message; self.plans.removeValue(forKey: self.page); self.selected = []
        }
    }
    func loadHistory() {
        perform("正在读取整理记录…") {
            self.history = try await self.client.execute(HistoryResult.self, request: self.request("history")).entries
            self.status = "已读取最近 \(self.history.count) 份计划"
        }
    }
    func restore(_ entry: HistoryEntry) {
        perform("正在打开计划…") {
            let result = try await self.client.execute(PhotoPlan.self, request: self.request("load-plan", extra: ["plan_id": entry.id]))
            if let target = Page(rawValue: result.kind) {
                self.plans[target] = result; self.page = target; self.selected = []
                self.group = "全部"; self.search = ""; self.pageNumber = 0
                self.status = "已打开历史计划，写入前会重新核对图库"
            }
        }
    }
    func chooseLibrary() {
        let panel = NSOpenPanel()
        panel.title = "选择照片图库"; panel.prompt = "连接图库"
        panel.canChooseFiles = true; panel.canChooseDirectories = true
        panel.allowsMultipleSelection = false; panel.treatsFilePackagesAsDirectories = false
        panel.directoryURL = FileManager.default.homeDirectoryForCurrentUser.appendingPathComponent("Pictures")
        if panel.runModal() == .OK, let url = panel.url {
            guard url.pathExtension == "photoslibrary" else { error = "请选择 .photoslibrary 图库。"; return }
            library = url.path; UserDefaults.standard.set(library, forKey: "library")
            summary = nil; plans = [:]; selected = []; page = .overview; refresh()
        }
    }
    func exportCSV() {
        guard let plan else { return }
        let panel = NSSavePanel(); panel.nameFieldStringValue = "PhotoDesk-\(page.name).csv"
        if panel.runModal() == .OK, let url = panel.url {
            do { try Data(contentsOf: URL(fileURLWithPath: plan.csvPath)).write(to: url, options: .atomic); status = "清单已导出" }
            catch { self.error = error.localizedDescription }
        }
    }
    func openRecords() {
        try? FileManager.default.createDirectory(at: Self.dataRoot, withIntermediateDirectories: true)
        NSWorkspace.shared.open(Self.dataRoot)
    }
    func openPhotos() { NSWorkspace.shared.open(URL(fileURLWithPath: "/System/Applications/Photos.app")) }
    func openPrivacy() { NSWorkspace.shared.open(URL(string: "x-apple.systempreferences:com.apple.preference.security?Privacy_AllFiles")!) }
}
