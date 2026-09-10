import SwiftUI
import AppKit

@MainActor
final class PhotoDeskModel: ObservableObject {
    @Published var preferences: PhotoPreferences {
        didSet {
            preferences.save()
            if oldValue.automatic != preferences.automatic || oldValue.includeShared != preferences.includeShared ||
                oldValue.recognizeContent != preferences.recognizeContent || oldValue.refreshSeconds != preferences.refreshSeconds ||
                oldValue.batchSize != preferences.batchSize || oldValue.eventHours != preferences.eventHours ||
                oldValue.eventKilometers != preferences.eventKilometers || oldValue.meetingMinutes != preferences.meetingMinutes || oldValue.petNames != preferences.petNames {
                preferenceTask?.cancel()
                preferenceTask = Task { [weak self] in
                    do { try await Task.sleep(for: .milliseconds(650)) } catch { return }
                    guard let self else { return }
                    if self.preferences.automatic { self.startAutomation(restart: true) } else { self.pauseAutomation() }
                }
            }
        }
    }
    @Published var focusedPhotoID: String?
    @Published var searchFocusToken = 0
    @Published var navigationScrollToken = 0
    @Published var gridFocused = false
    var gridColumns = 3
    func updateGridWidth(_ width: Double) { gridColumns = max(1, Int((width - 18) / (preferences.thumbnailWidth + 14))) }
    private var selectionAnchor: String?
    private var keyboardMonitor: Any?
    private var preferenceTask: Task<Void, Never>?
    var openSettingsAction: (() -> Void)?
    lazy var shortcuts = PhotoShortcuts { [weak self] action in self?.performAction(action) }
    init() {
        preferences = PhotoPreferences.load()
        track = preferences.initialTrack
    }
    @Published var page: Page = .journey
    @Published var journey: JourneyResult?
    @Published var activeEvent: JourneyEvent?
    @Published var selectedEventIDs: Set<String> = []
    @Published var focusedEventID: String?
    private var eventAnchor: String?
    private var selectionJourney: JourneyResult?
    var timelineVisible: Bool { page == .journey && activeEvent == nil }
    func clearEventSelection() {
        selectedEventIDs = []; focusedEventID = nil; eventAnchor = nil
        selectionJourney = nil; selected = []; focusedPhotoID = nil; gridFocused = false
        if page == .journey, let journey { plans[.journey] = journey.plan }
    }
    func selectEvent(_ event: JourneyEvent, modifiers: NSEvent.ModifierFlags = []) {
        guard !busy, timelineVisible else { return }
        if selectionJourney == nil { selectionJourney = journey }
        plans[.journey] = selectionJourney?.plan
        gridFocused = true; focusedEventID = event.id; focusedPhotoID = event.cover.id
        NSApp?.keyWindow?.makeFirstResponder(nil)
        if modifiers.contains(.shift), let anchor = eventAnchor,
           let start = events.firstIndex(where: { $0.id == anchor }), let end = events.firstIndex(where: { $0.id == event.id }) {
            selectedEventIDs = Set(events[min(start, end)...max(start, end)].map(\.id))
        } else if modifiers.contains(.command) {
            if selectedEventIDs.contains(event.id) { selectedEventIDs.remove(event.id) } else { selectedEventIDs.insert(event.id) }
            eventAnchor = event.id
        } else { selectedEventIDs = [event.id]; eventAnchor = event.id }
        syncEventSelection()
    }
    private func syncEventSelection() {
        let groups = Set(events.filter { selectedEventIDs.contains($0.id) }.map(\.group))
        selected = Set((plan?.rows ?? []).filter { groups.contains($0.group) && $0.readOnly != true }.map(\.id))
    }
    @Published var track = "全部"
    @Published var eventSearch = ""
    @Published var eventLimit = 60
    @Published var organizing = false
    @Published var automaticEnabled = false
    @Published var organizationStatus = "正在联系图库中的照片…"
    @Published var organizationError: String?
    private var automation: Task<Void, Never>?
    private var automationStarted = false
    private let organizer = BackendClient()
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
    @Published var confirmDelete = false
    @Published var confirmFixture = false
    @Published var pendingDeletion: DeletionPreview?
    @Published var enlargedPhoto: PlanRow?
    private var pendingDeleteSelection: [String] = []
    @Published var history: [HistoryEntry] = []
    @Published var ocrLimit = 100
    @Published var library = ProcessInfo.processInfo.environment["PHOTODESK_LIBRARY"] ?? PhotoPreferences.defaults.string(forKey: "library") ?? ""
    let client = BackendClient()
    private var task: Task<Void, Never>?
    private var poller: Task<Void, Never>?
    private var requestID = ""
    static let dataRoot: URL = {
        if let path = ProcessInfo.processInfo.environment["PHOTODESK_DATA_ROOT"], path.hasPrefix("/") {
            return URL(fileURLWithPath: path, isDirectory: true)
        }
        return FileManager.default.homeDirectoryForCurrentUser.appendingPathComponent("Library/Application Support/PhotoDesk")
    }()
    var plan: PhotoPlan? { plans[page] }
    var filteredRows: [PlanRow] {
        (plan?.rows ?? []).filter { (group == "全部" || $0.group == group) &&
            (search.isEmpty || [$0.filename, $0.target, $0.note, $0.date].contains { $0.localizedCaseInsensitiveContains(search) }) }
    }
    var visibleRows: [PlanRow] { Array(filteredRows.dropFirst(pageNumber * 60).prefix(60)) }
    var selectedRows: [PlanRow] { (plan?.rows ?? []).filter { selected.contains($0.id) } }
    var selectedPhotoCount: Int { Set(selectedRows.map { $0.localUuid ?? ($0.cloudGuid.isEmpty ? $0.id : $0.cloudGuid) }).count }

    func navigate(_ target: Page) {
        guard !busy else { return }
        clearEventSelection()
        page = target; group = "全部"; search = ""; pageNumber = 0; activeEvent = nil
        selected = []; focusedPhotoID = nil; selectionAnchor = nil; gridFocused = false
        if target == .duplicates && preferences.preselectDuplicates { selected = Set(plans[.duplicates]?.rows.filter { $0.recommended == true }.map(\.id) ?? []) }
        if target == .history { loadHistory() }
        if target == .overview && summary == nil { refresh() }
        if target == .library && plans[target] == nil { generate() }
        if [.classify, .triage, .sensitive, .title].contains(target) && plans[target] == nil { generate() }
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
                guard !Task.isCancelled else { break }
                if let data = try? Data(contentsOf: url), let p = try? JSONDecoder().decode(WorkProgress.self, from: data) { progress = p }
            }
        }
        task = Task {
            defer { busy = false; applying = false; poller?.cancel(); progress = nil }
            do { try await work() }
            catch {
                if (error as NSError).code == NSUserCancelledError { status = "已取消；照片未删除" }
                else if !Task.isCancelled { self.error = error.localizedDescription; status = "任务未完成" }
                else { status = "已取消；图库未改动" }
            }
        }
    }
    func cancel() { guard !applying else { return }; task?.cancel() }
    func refresh() {
        startAutomation(restart: true)
        perform("正在读取图库…") {
            let result = try await self.client.execute(LibrarySummary.self, request: self.request("audit"))
            self.summary = result; self.status = "已读取 \(result.total.formatted()) 项个人照片与视频"
        }
    }
    func generate() {
        if page == .duplicates { selected = []; plans[.duplicates] = nil; startAutomation(restart: true); return }
        let target = page
        perform(target.usesOCR ? "正在本地识别…" : "正在生成整理建议…") {
            let result = try await self.client.execute(PhotoPlan.self, request: self.request("plan", extra: ["kind": target.rawValue, "limit": self.ocrLimit]))
            self.plans[target] = result; self.selected = []; self.group = "全部"; self.pageNumber = 0
            self.status = target == .library ? "已载入 \(result.rows.count.formatted()) 张照片与视频" : "已生成 \(result.rows.count.formatted()) 项建议，尚未写入图库"
        }
    }
    func checkBeforeApply() {
        pauseAutomation()
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
    func checkBeforeDelete() {
        pauseAutomation()
        guard let plan, !selected.isEmpty else { return }
        enlargedPhoto = nil
        let chosen = Array(selected)
        perform("正在核对待删除照片…") {
            let preview = try await self.client.execute(DeletionPreview.self, request: self.request("delete-preview", extra: ["plan_id": plan.id, "selected": chosen]))
            try await NativePhotos.authorize()
            _ = try NativePhotos.resolve(preview.items)
            self.pendingDeletion = preview; self.pendingDeleteSelection = chosen
            self.status = "已核对 \(preview.items.count) 张照片，请确认删除范围"; self.confirmDelete = true
        }
    }
    func deleteSelected() {
        guard let preview = pendingDeletion else { return }
        confirmDelete = false; applying = true
        perform("等待系统确认删除…") {
            // Revalidate exact local assets and library ownership after review.
            let current = try await self.client.execute(DeletionPreview.self, request: self.request("delete-preview", extra: ["plan_id": preview.planId, "selected": self.pendingDeleteSelection]))
            guard Set(current.items.map(\.uuid)) == Set(preview.items.map(\.uuid)) else { throw NativePhotos.fail("所选照片发生变化，请重新查看后确认。") }
            let outcome = try await NativePhotos.delete(current.items, recordRoot: Self.dataRoot)
            self.clearEventSelection(); self.plans = [:]; self.selected = []; self.pendingDeletion = nil
            self.activeEvent = nil
            // A successful deletion must not be relabeled as failed if a subsequent read fails.
            self.summary = try? await self.client.execute(LibrarySummary.self, request: self.request("audit"))
            if self.page == .library {
                self.plans[.library] = try? await self.client.execute(PhotoPlan.self, request: self.request("plan", extra: ["kind": "library"]))
            }
            self.pageNumber = 0
            self.status = outcome.verified ? "已删除并核对 \(outcome.count) 张照片，可在“照片 → 最近删除”中恢复" : "系统已完成删除，图库刷新核对尚未完成，请稍后刷新"
            self.startAutomation(restart: true)
        }
    }
    func createFixture() {
        confirmFixture = false; applying = true
        perform("正在创建一张明确标记的测试照片…") {
            let filename = try await NativePhotos.createFixture(recordRoot: Self.dataRoot)
            self.page = .library; self.group = "全部"; self.search = filename; self.selected = []; self.pageNumber = 0
            self.plans[.library] = try await self.client.execute(PhotoPlan.self, request: self.request("plan", extra: ["kind": "library"]))
            self.status = "测试照片已导入并核对。可用这张新图验证整理和删除。"
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
        guard ProcessInfo.processInfo.environment["PHOTODESK_DEMO_ROOT"] == nil else {
            error = "当前为独立合成演示图库。退出演示后再连接自己的图库。"; return
        }
        let panel = NSOpenPanel()
        panel.title = "选择照片图库"; panel.prompt = "连接图库"
        panel.canChooseFiles = true; panel.canChooseDirectories = true
        panel.allowsMultipleSelection = false; panel.treatsFilePackagesAsDirectories = false
        panel.directoryURL = FileManager.default.homeDirectoryForCurrentUser.appendingPathComponent("Pictures")
        if panel.runModal() == .OK, let url = panel.url {
            guard url.pathExtension == "photoslibrary" else { error = "请选择 .photoslibrary 图库。"; return }
            library = url.path; PhotoPreferences.defaults.set(library, forKey: "library")
            pauseAutomation(); journey = nil; activeEvent = nil
            summary = nil; plans = [:]; selected = []; page = .journey; refresh()
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
    func openPhotos() {
        guard ProcessInfo.processInfo.environment["PHOTODESK_DEMO_ROOT"] == nil else {
            error = "合成演示图库不连接 Apple“照片”。"; return
        }
        NSWorkspace.shared.open(URL(fileURLWithPath: "/System/Applications/Photos.app"))
    }
    func revealPhoto(_ row: PlanRow) {
        guard !busy else { return }
        do { try NativePhotos.reveal(row.localUuid); status = "已在“照片”中定位 \(row.filename)" }
        catch { enlargedPhoto = nil; self.error = error.localizedDescription }
    }
    func openPrivacy() { NSWorkspace.shared.open(URL(string: "x-apple.systempreferences:com.apple.preference.security?Privacy_AllFiles")!) }
    func openPhotosPrivacy() { NSWorkspace.shared.open(URL(string: "x-apple.systempreferences:com.apple.preference.security?Privacy_Photos")!) }

    var events: [JourneyEvent] {
        ((selectionJourney ?? journey)?.events ?? []).filter { event in
            (track == "全部" || event.tracks.contains(track)) &&
            (eventSearch.isEmpty || ([event.title, event.date, event.place] + event.people + event.evidence).contains { $0.localizedCaseInsensitiveContains(eventSearch) })
        }
    }
    func openEvent(_ event: JourneyEvent) {
        guard let journey = selectionJourney ?? journey else { return }
        clearEventSelection()
        activeEvent = event; plans[.journey] = journey.plan; page = .journey
        group = event.group; search = ""; selected = []; pageNumber = 0
    }
    func pauseAutomation() {
        automation?.cancel(); automation = nil; organizing = false; automaticEnabled = false
        organizationStatus = "自动整理已暂停，已有结果仍可浏览"
    }
    func startAutomation(restart: Bool = false, retryFailed: Bool = false) {
        guard preferences.automatic else { pauseAutomation(); organizationStatus = "自动整理已关闭；可在设置中重新开启"; return }
        if automationStarted && !restart { return }
        automationStarted = true; automation?.cancel(); organizationError = nil
        automaticEnabled = true
        let chosenLibrary = library
        automation = Task {
            organizing = true
            var command = "journey-snapshot"
            var shouldRetry = retryFailed
            while !Task.isCancelled {
                do {
                    let result = try await organizer.execute(JourneyResult.self, request: ["command": command, "library": chosenLibrary, "limit": preferences.batchSize, "options": preferences.engineOptions, "retry_failed": shouldRetry])
                    shouldRetry = false
                    guard !Task.isCancelled, chosenLibrary == library else { return }
                    journey = result
                    if status == "准备连接你的照片图库" { status = "已自动归集 \(result.total.formatted()) 项照片与视频" }
                    if activeEvent == nil && selectionJourney == nil { plans[.journey] = result.plan }
                    if page != .duplicates || plans[.duplicates] == nil || (command == "journey-snapshot" && selected.isEmpty) {
                        plans[.duplicates] = result.duplicates
                        if page == .duplicates && preferences.preselectDuplicates { selected = Set(result.duplicates.rows.filter { $0.recommended == true }.map(\.id)) }
                    }
                    let needsRecognition = result.pending > 0 && preferences.recognizeContent
                    organizationStatus = !preferences.recognizeContent ? "已按时间、人物和已有相册归集；内容识别已关闭" : result.pending > 0
                        ? "已联系 \(result.total.formatted()) 张照片 · 内容识别 \(result.analyzed.formatted()) / \(result.total.formatted())；可以边看边整理"
                        : "全部照片已归集 · 新照片每分钟自动检查；内容识别缺失 \(result.unavailable) 项，失败 \(result.failed) 项"
                    organizing = needsRecognition
                    command = needsRecognition ? "journey-enrich" : "journey-snapshot"
                    try await Task.sleep(for: needsRecognition ? .milliseconds(300) : .seconds(preferences.refreshSeconds))
                } catch {
                    guard !Task.isCancelled else { return }
                    organizing = false; automaticEnabled = false; organizationError = error.localizedDescription
                    organizationStatus = "本轮自动整理中断，已有结果保留；点击重试继续"
                    return
                }
            }
        }
    }

    var photoGridVisible: Bool { plan != nil && ![Page.overview, .history].contains(page) }
    var previewRow: PlanRow? {
        if timelineVisible { return events.first { $0.id == focusedEventID && selectedEventIDs.contains($0.id) }?.cover }
        return filteredRows.first { $0.id == focusedPhotoID && (selected.contains($0.id) || $0.readOnly == true) } ?? filteredRows.first { selected.contains($0.id) }
    }
    var canPreview: Bool { !busy && photoGridVisible && previewRow != nil }
    func selectPhoto(_ row: PlanRow, modifiers: NSEvent.ModifierFlags = []) {
        guard !busy else { return }
        gridFocused = true; focusedPhotoID = row.id
        NSApp?.keyWindow?.makeFirstResponder(nil)
        if modifiers.contains(.shift), let anchor = selectionAnchor,
           let start = filteredRows.firstIndex(where: { $0.id == anchor }), let end = filteredRows.firstIndex(where: { $0.id == row.id }) {
            selected = Set(filteredRows[min(start, end)...max(start, end)].filter { $0.readOnly != true }.map(\.id))
        } else if modifiers.contains(.command) {
            if selected.contains(row.id) { selected.remove(row.id) } else if row.readOnly != true { selected.insert(row.id) }
            selectionAnchor = row.id
        } else {
            selected = row.readOnly == true ? [] : [row.id]; selectionAnchor = row.id
        }
    }
    func selectAllPhotos() {
        guard photoGridVisible, !busy else { return }
        if timelineVisible {
            if selectionJourney == nil { selectionJourney = journey }
            plans[.journey] = selectionJourney?.plan
            selectedEventIDs = Set(events.map(\.id)); focusedEventID = events.first?.id
            gridFocused = true; syncEventSelection(); NSApp?.keyWindow?.makeFirstResponder(nil); return
        }
        selected = Set(filteredRows.filter { $0.readOnly != true }.map(\.id)); gridFocused = true
        if focusedPhotoID == nil { focusedPhotoID = filteredRows.first?.id }
        NSApp?.keyWindow?.makeFirstResponder(nil)
    }
    func movePhoto(_ delta: Int, extend: Bool = false) {
        if timelineVisible {
            guard !busy, !events.isEmpty else { return }
            let index = events.firstIndex { $0.id == focusedEventID }
            let target = max(0, min(events.count - 1, (index ?? (delta > 0 ? -delta : 0)) + delta))
            selectEvent(events[target], modifiers: extend ? [.shift] : [])
            eventLimit = max(eventLimit, target + 1); navigationScrollToken += 1
            if enlargedPhoto != nil { enlargedPhoto = events[target].cover }
            return
        }
        guard photoGridVisible, !busy, !filteredRows.isEmpty else { return }
        let rows = filteredRows
        let index = focusedPhotoID.flatMap { id in rows.firstIndex { $0.id == id } }
        let target = max(0, min(rows.count-1, (index ?? (delta > 0 ? -delta : 0)) + delta))
        selectPhoto(rows[target], modifiers: extend ? [.shift] : [])
        pageNumber = target / 60
        navigationScrollToken += 1
        if enlargedPhoto != nil { enlargedPhoto = rows[target] }
    }
    func togglePreview() {
        if enlargedPhoto != nil { enlargedPhoto = nil; return }
        guard canPreview else { return }
        enlargedPhoto = previewRow
    }
    func performAction(_ action: PhotoAction) {
        switch action {
        case .toggleWindow:
            if ProcessInfo.processInfo.environment["PHOTODESK_BACKGROUND"] == "1" { return }
            NSApp?.activate(ignoringOtherApps: true)
            if let window = NSApp?.windows.first(where: { $0.identifier?.rawValue == "main" }) {
                window.deminiaturize(nil); window.makeKeyAndOrderFront(nil)
            }
        case .settings: openSettingsAction?()
        case .pause: preferences.automatic.toggle()
        case .search: searchFocusToken += 1; gridFocused = false
        case .preview: togglePreview()
        case .next: movePhoto(1)
        case .previous: movePhoto(-1)
        case .selectAll: selectAllPhotos()
        case .delete: if !selected.isEmpty && photoGridVisible && gridFocused && !busy { checkBeforeDelete() }
        case .refresh: if page == .journey { startAutomation(restart: true) } else if photoGridVisible { generate() } else { refresh() }
        }
    }
    func handleNativeKey(_ code: UInt16, modifiers: NSEvent.ModifierFlags, editingText: Bool, mainWindow: Bool) -> Bool {
        guard mainWindow, !editingText, !busy, !confirmDelete, !confirm, !confirmFixture, !shortcuts.recording else { return false }
        let flags = modifiers.intersection([.command, .shift, .option, .control])
        if flags == .command {
            if code == 3 { performAction(.search); return true }
            if code == 0, photoGridVisible { selectAllPhotos(); return true }
            if code == 51, photoGridVisible, !selected.isEmpty { performAction(.delete); return true }
        }
        guard gridFocused || enlargedPhoto != nil else { return false }
        if code == 49 && flags.isEmpty && (canPreview || enlargedPhoto != nil) { togglePreview(); return true }
        if code == 53 && flags.isEmpty {
            if enlargedPhoto != nil { enlargedPhoto = nil } else if timelineVisible { clearEventSelection() } else { selected = []; focusedPhotoID = nil }
            return true
        }
        if flags.isEmpty || flags == .shift {
            let delta: Int
            switch code { case 123: delta = -1; case 124: delta = 1; case 125: delta = gridColumns; case 126: delta = -gridColumns; default: return false }
            guard photoGridVisible else { return false }; movePhoto(delta, extend: flags == .shift); return true
        }
        return false
    }
    func startProductControls() {
        guard keyboardMonitor == nil else { return }
        _ = shortcuts
        keyboardMonitor = NSEvent.addLocalMonitorForEvents(matching: .keyDown) { [weak self] event in
            let handled = MainActor.assumeIsolated {
                guard let self, NSApp.isActive else { return false }
                let window = NSApp.keyWindow
                let isMain = window?.identifier?.rawValue == "main" || (self.enlargedPhoto != nil && window?.sheetParent?.identifier?.rawValue == "main")
                return self.handleNativeKey(event.keyCode, modifiers: event.modifierFlags,
                                            editingText: (window?.firstResponder as? NSTextView)?.isEditable == true, mainWindow: isMain)
            }
            return handled ? nil : event
        }
    }
    func stopProductControls() {
        if let keyboardMonitor { NSEvent.removeMonitor(keyboardMonitor); self.keyboardMonitor = nil }
        shortcuts.suspend(); preferenceTask?.cancel()
    }
}
