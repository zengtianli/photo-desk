// Shortcut recording and Carbon registration adapted from Clip, 2026-09-08.
// Self-contained source snapshot; no runtime dependency on another app.
import AppKit
import Carbon.HIToolbox
import SwiftUI
import ServiceManagement

struct PhotoPreferences: Codable, Equatable {
    static var defaults: UserDefaults {
        if let suite = ProcessInfo.processInfo.environment["PHOTODESK_PREFERENCES_SUITE"] { return UserDefaults(suiteName: suite)! }
        return .standard
    }
    static let storageKey = "product.preferences.v1"
    var automatic = true
    var includeShared = true
    var recognizeContent = true
    var refreshSeconds = 60
    var batchSize = 12
    var eventHours = 3
    var eventKilometers = 8
    var meetingMinutes = 90
    var petNames = ""
    var preselectDuplicates = true
    var thumbnailWidth = 180.0
    var appearance = "system"
    var initialTrack = "全部"
    static func load() -> Self {
        guard let data = defaults.data(forKey: storageKey), var value = try? JSONDecoder().decode(Self.self, from: data) else {
            var fresh = Self()
            if ProcessInfo.processInfo.environment["PHOTODESK_DEMO_ROOT"] != nil { fresh.appearance = "light" }
            return fresh
        }
        value.refreshSeconds = max(30, min(3600, value.refreshSeconds))
        value.batchSize = max(1, min(24, value.batchSize))
        value.eventHours = max(1, min(12, value.eventHours))
        value.eventKilometers = max(1, min(100, value.eventKilometers))
        value.meetingMinutes = max(15, min(180, value.meetingMinutes))
        value.thumbnailWidth = max(140, min(280, value.thumbnailWidth))
        return value
    }
    func save() { if let data = try? JSONEncoder().encode(self) { Self.defaults.set(data, forKey: Self.storageKey) } }
    var engineOptions: [String: Any] {
        ["include_shared": includeShared, "recognize_content": recognizeContent,
         "event_hours": eventHours, "event_kilometers": eventKilometers,
         "meeting_minutes": meetingMinutes,
         "pet_names": petNames.components(separatedBy: CharacterSet(charactersIn: ",，、\n")).map { $0.trimmingCharacters(in: .whitespaces) }.filter { !$0.isEmpty }]
    }
    var colorScheme: ColorScheme? { appearance == "dark" ? .dark : appearance == "light" ? .light : nil }
}

struct PhotoSettingsView: View {
    @ObservedObject var model: PhotoDeskModel
    @ObservedObject var shortcuts: PhotoShortcuts
    @State private var loginEnabled = SMAppService.mainApp.status == .enabled
    @State private var loginStatus = ""
    var body: some View {
        TabView {
            Form {
                Section("启动与显示") {
                    Toggle("打开 PhotoDesk 后自动整理", isOn: $model.preferences.automatic)
                    Toggle("登录 Mac 时启动", isOn: Binding(get: { loginEnabled }, set: setLogin))
                    if !loginStatus.isEmpty { Text(loginStatus).font(.caption).foregroundStyle(.secondary) }
                    Picker("默认时间线", selection: $model.preferences.initialTrack) {
                        ForEach(["全部", "个人时间线", "猫时间线", "会议与工作", "资料与截图"], id: \.self) { Text($0).tag($0) }
                    }
                    Picker("外观", selection: $model.preferences.appearance) {
                        Text("跟随系统").tag("system"); Text("浅色").tag("light"); Text("深色").tag("dark")
                    }
                    LabeledContent("照片大小") { Slider(value: $model.preferences.thumbnailWidth, in: 140...280, step: 10).frame(width: 200) }
                }
                Section("图库与本地数据") {
                    Text(ProcessInfo.processInfo.environment["PHOTODESK_DEMO_ROOT"] != nil ? "合成演示图库（独立样例）" : model.library.isEmpty ? "当前使用“照片”最近打开的图库" : model.library).textSelection(.enabled).font(.caption)
                    Button("选择图库…") { model.chooseLibrary() }
                    Toggle("时间线包含共享相册（只读）", isOn: $model.preferences.includeShared)
                    Button("打开本地数据与记录") { model.openRecords() }
                    HStack { Button("照片权限") { model.openPhotosPrivacy() }; Button("完全磁盘访问权限") { model.openPrivacy() } }
                }
                Text("设置自动保存，关闭设置窗口后仍然生效。").font(.caption).foregroundStyle(.secondary)
            }.formStyle(.grouped).tabItem { Label("通用", systemImage: "gearshape") }
            Form {
                Section("自动识别") {
                    Toggle("在本机识别图像内容与文字", isOn: $model.preferences.recognizeContent)
                    Picker("检查新照片", selection: $model.preferences.refreshSeconds) {
                        Text("每分钟").tag(60); Text("每 5 分钟").tag(300); Text("每 15 分钟").tag(900)
                    }
                    Picker("后台处理强度", selection: $model.preferences.batchSize) {
                        Text("轻量 · 每批 6 项").tag(6); Text("标准 · 每批 12 项").tag(12); Text("较快 · 每批 24 项").tag(24)
                    }
                    Button("重试失败的识别") { model.startAutomation(restart: true, retryFailed: true) }.disabled((model.journey?.failed ?? 0) == 0)
                    Text(model.organizationStatus).font(.caption).foregroundStyle(.secondary)
                }
                Section("照片之间的联系") {
                    Stepper("同一片段最长间隔：\(model.preferences.eventHours) 小时", value: $model.preferences.eventHours, in: 1...12)
                    Stepper("同一片段地点距离：\(model.preferences.eventKilometers) 公里", value: $model.preferences.eventKilometers, in: 1...100)
                    Stepper("会议资料关联时间：\(model.preferences.meetingMinutes) 分钟", value: $model.preferences.meetingMinutes, in: 15...180, step: 15)
                    TextField("已命名的猫（逗号分隔）", text: $model.preferences.petNames)
                    Text("名称匹配“照片”中已命名的人物/宠物，不会把识别到的陌生猫自动命名。修改联系规则会重新归集，已有图像识别缓存继续使用。").font(.caption).foregroundStyle(.secondary)
                }
                Section("重复照片") {
                    Toggle("进入重复核对时预选建议删除项", isOn: $model.preferences.preselectDuplicates)
                    Text("只有字节一致且保留副本覆盖原有信息的静态照片才会被建议删除。收藏、隐藏、独立编辑、视频和 Live Photo 不预选。删除始终需要最后确认。").font(.caption).foregroundStyle(.secondary)
                }
            }.formStyle(.grouped).tabItem { Label("整理规则", systemImage: "slider.horizontal.3") }
            ShortcutSettingsPane(center: shortcuts).tabItem { Label("快捷键", systemImage: "keyboard") }
            Form {
                Section("PhotoDesk") {
                    Text("把照片联系成个人、猫咪与工作时间线。").font(.headline)
                    Text("版本 \(Bundle.main.object(forInfoDictionaryKey: "CFBundleShortVersionString") as? String ?? "") · 构建 \(Bundle.main.object(forInfoDictionaryKey: "CFBundleVersion") as? String ?? "")")
                    Text("图像和文字识别在本机进行；分类索引与缓存保存在本地。共享内容只读，最终删除由你确认。").font(.callout)
                }
                Section("原生操作") {
                    Text("单击选择；⌘单击增减选择；⇧单击连续选择。\n方向键移动，⇧方向键扩选；空格快速预览，再按空格或 Esc 关闭，左右键浏览前后照片。\n⌘A 全选筛选结果；⌘F 搜索；⌘⌫ 请求删除；⌘, 设置。\n文本框内保留系统编辑操作，不把空格或删除键当照片命令。")
                }
            }.formStyle(.grouped).tabItem { Label("关于与帮助", systemImage: "info.circle") }
        }.frame(width: 650, height: 610).padding(10)
            .preferredColorScheme(model.preferences.colorScheme).disabled(model.applying)
            .onDisappear { shortcuts.endRecording() }
    }
    private func setLogin(_ enabled: Bool) {
        do {
            if enabled { try SMAppService.mainApp.register() } else { try SMAppService.mainApp.unregister() }
            loginEnabled = SMAppService.mainApp.status == .enabled
            loginStatus = SMAppService.mainApp.status == .requiresApproval ? "请在系统设置 → 通用 → 登录项中允许 PhotoDesk。" : loginEnabled ? "已启用登录启动" : "登录启动已关闭"
        } catch { loginEnabled = SMAppService.mainApp.status == .enabled; loginStatus = "未能更改登录启动：\(error.localizedDescription)" }
    }
}

enum PhotoAction: String, CaseIterable, Identifiable, Codable {
    case toggleWindow, settings, pause, search, preview, next, previous, selectAll, delete, refresh
    var id: String { rawValue }
    var title: String {
        switch self {
        case .toggleWindow: return "显示主窗口"
        case .settings: return "打开设置"
        case .pause: return "暂停 / 恢复自动整理"
        case .search: return "聚焦搜索"
        case .preview: return "快速预览所选照片"
        case .next: return "下一张照片"
        case .previous: return "上一张照片"
        case .selectAll: return "全选当前筛选结果"
        case .delete: return "删除所选照片…"
        case .refresh: return "刷新当前视图"
        }
    }
    var allowsGlobal: Bool { [.toggleWindow, .settings, .pause].contains(self) }
}

struct PhotoKey: Codable, Equatable {
    let code: UInt32
    let modifiers: UInt32
    let key: String
    static let allowedModifiers = UInt32(cmdKey | controlKey | optionKey | shiftKey)
    init(code: UInt32, modifiers: UInt32, key: String) {
        self.code = code; self.modifiers = modifiers & Self.allowedModifiers; self.key = key
    }
    init(_ event: NSEvent) {
        var mods: UInt32 = 0
        if event.modifierFlags.contains(.command) { mods |= UInt32(cmdKey) }
        if event.modifierFlags.contains(.control) { mods |= UInt32(controlKey) }
        if event.modifierFlags.contains(.option) { mods |= UInt32(optionKey) }
        if event.modifierFlags.contains(.shift) { mods |= UInt32(shiftKey) }
        let special: [UInt16: String] = [49: "Space", 36: "Return", 48: "Tab", 51: "Delete", 53: "Esc", 123: "←", 124: "→", 125: "↓", 126: "↑"]
        self.init(code: UInt32(event.keyCode), modifiers: mods,
                  key: special[event.keyCode] ?? (event.charactersIgnoringModifiers ?? "").uppercased())
    }
    var label: String {
        [(controlKey, "⌃"), (optionKey, "⌥"), (shiftKey, "⇧"), (cmdKey, "⌘")]
            .filter { modifiers & UInt32($0.0) != 0 }.map(\.1).joined() + key
    }
    func matches(_ other: PhotoKey) -> Bool { code == other.code && modifiers == other.modifiers }
    var validationError: String? {
        guard code < 128, !key.isEmpty, modifiers & ~Self.allowedModifiers == 0 else { return "无法识别这个组合，请重新录制。" }
        guard modifiers & UInt32(cmdKey | controlKey | optionKey) != 0 else { return "请至少包含 ⌘、⌃ 或 ⌥，避免影响正常输入。" }
        if code == 9 && modifiers == UInt32(cmdKey | shiftKey) { return "⌘⇧V 已用于你的 Keyboard Maestro 操作，请换一个组合。" }
        if modifiers == UInt32(cmdKey), [0, 1, 3, 6, 7, 8, 9, 12, 13, 15, 43, 51].contains(code) { return "请保留 macOS 的标准菜单和编辑快捷键。" }
        return nil
    }
}

struct PhotoBinding: Codable, Equatable {
    enum Scope: String, Codable, CaseIterable { case application, global }
    let chord: PhotoKey
    let scope: Scope
}

@MainActor
protocol PhotoKeyRegistration: AnyObject {
    var onPress: ((UInt32) -> Void)? { get set }
    func register(_ chord: PhotoKey, id: UInt32) -> OSStatus
    func unregister(_ id: UInt32)
}

@MainActor
final class CarbonPhotoKeys: PhotoKeyRegistration {
    var onPress: ((UInt32) -> Void)?
    private var handler: EventHandlerRef?
    private var refs: [UInt32: EventHotKeyRef] = [:]
    private static let signature: OSType = 0x5048_4F54

    func register(_ chord: PhotoKey, id: UInt32) -> OSStatus {
        if handler == nil {
            var spec = EventTypeSpec(eventClass: OSType(kEventClassKeyboard), eventKind: OSType(kEventHotKeyPressed))
            let rc = InstallEventHandler(GetApplicationEventTarget(), { _, event, context in
                guard let event, let context else { return OSStatus(eventNotHandledErr) }
                var key = EventHotKeyID()
                let rc = GetEventParameter(event, EventParamName(kEventParamDirectObject), EventParamType(typeEventHotKeyID), nil,
                                           MemoryLayout<EventHotKeyID>.size, nil, &key)
                guard rc == noErr, key.signature == 0x5048_4F54 else { return OSStatus(eventNotHandledErr) }
                let center = Unmanaged<CarbonPhotoKeys>.fromOpaque(context).takeUnretainedValue()
                let id = key.id
                MainActor.assumeIsolated { center.onPress?(id) }
                return noErr
            }, 1, &spec, Unmanaged.passUnretained(self).toOpaque(), &handler)
            guard rc == noErr else { return rc }
        }
        var ref: EventHotKeyRef?
        let rc = RegisterEventHotKey(chord.code, chord.modifiers, EventHotKeyID(signature: Self.signature, id: id),
                                    GetApplicationEventTarget(), 0, &ref)
        if rc == noErr, let ref { refs[id] = ref }
        return rc
    }
    func unregister(_ id: UInt32) {
        if let ref = refs.removeValue(forKey: id) { UnregisterEventHotKey(ref) }
        if refs.isEmpty, let handler { RemoveEventHandler(handler); self.handler = nil }
    }
}

@MainActor
final class PhotoShortcuts: ObservableObject {
    static let defaultBindings: [String: PhotoBinding] = [:]
    static let storageKey = "shortcuts.v1"
    @Published private(set) var bindings: [String: PhotoBinding]
    @Published private(set) var errors: [String: String] = [:]
    @Published private(set) var recording = false
    @Published private(set) var recordingAction: PhotoAction?
    private let defaults: UserDefaults
    private let backend: PhotoKeyRegistration
    private let perform: (PhotoAction) -> Void
    private var live: [String: UInt32] = [:]
    private var serial: UInt32 = 0
    private var monitor: Any?
    private let monitorsEnabled: Bool

    init(defaults: UserDefaults = PhotoPreferences.defaults, backend: PhotoKeyRegistration? = nil,
         monitorsEnabled: Bool = true, perform: @escaping (PhotoAction) -> Void) {
        self.defaults = defaults; self.backend = backend ?? CarbonPhotoKeys(); self.perform = perform; self.monitorsEnabled = monitorsEnabled
        if let data = defaults.data(forKey: Self.storageKey) {
            do { bindings = try JSONDecoder().decode([String: PhotoBinding].self, from: data) }
            catch { bindings = Self.defaultBindings; errors["load"] = "快捷键配置无法读取，未注册任何快捷键。请重新设置。" }
        } else { bindings = Self.defaultBindings }
        self.backend.onPress = { [weak self] id in
            guard let self, !self.recording, let raw = self.live.first(where: { $0.value == id })?.key,
                  let action = PhotoAction(rawValue: raw) else { return }
            self.perform(action)
        }
        resume()
    }

    func binding(_ action: PhotoAction) -> PhotoBinding? { bindings[action.rawValue] }
    func status(_ action: PhotoAction) -> String {
        if let error = errors[action.rawValue] { return error }
        guard let b = binding(action) else { return "未设置" }
        return b.scope == .global ? "已启用 · 全局" : "已启用 · 仅 PhotoDesk 内"
    }
    private func invalid(_ action: PhotoAction, _ binding: PhotoBinding) -> String? {
        if let error = binding.chord.validationError { return error }
        if binding.scope == .global && !action.allowsGlobal { return "此操作只能在 PhotoDesk 窗口内使用。" }
        if let duplicate = bindings.first(where: { $0.key != action.rawValue && $0.value.chord.matches(binding.chord) }) {
            return "已用于「\(PhotoAction(rawValue: duplicate.key)?.title ?? duplicate.key)」，请先清除原绑定。"
        }
        return nil
    }
    @discardableResult
    func set(_ action: PhotoAction, to binding: PhotoBinding?) -> Bool {
        if let binding, let error = invalid(action, binding) { errors[action.rawValue] = error; return false }
        if bindings[action.rawValue] == binding,
           binding?.scope != .global || live[action.rawValue] != nil {
            errors[action.rawValue] = nil
            return true
        }
        var newID: UInt32?
        if let binding, binding.scope == .global, !recording {
            serial += 1
            let rc = backend.register(binding.chord, id: serial)
            guard rc == noErr else { errors[action.rawValue] = "未启用：系统拒绝注册（\(rc)）；原绑定保留。"; return false }
            newID = serial
        }
        if let old = live.removeValue(forKey: action.rawValue) { backend.unregister(old) }
        if let newID { live[action.rawValue] = newID }
        bindings[action.rawValue] = binding
        errors[action.rawValue] = nil
        // All fields are primitive Codable values; persistence never invents a default binding.
        if let data = try? JSONEncoder().encode(bindings) { defaults.set(data, forKey: Self.storageKey) }
        refreshMonitor()
        return true
    }
    func clearAll() {
        suspend(); recording = false; recordingAction = nil; bindings = Self.defaultBindings; errors = [:]
        defaults.removeObject(forKey: Self.storageKey)
    }
    func beginRecording(action: PhotoAction? = nil) { recording = true; recordingAction = action; suspend() }
    func endRecording() { guard recording else { return }; recording = false; recordingAction = nil; resume() }
    func suspend() {
        for id in live.values { backend.unregister(id) }; live = [:]
        if let monitor { NSEvent.removeMonitor(monitor); self.monitor = nil }
    }
    private func resume() {
        guard !recording else { return }
        for action in PhotoAction.allCases {
            guard let binding = binding(action) else { continue }
            if let error = invalid(action, binding) { errors[action.rawValue] = error; continue }
            if binding.scope == .global {
                serial += 1
                let rc = backend.register(binding.chord, id: serial)
                if rc == noErr { live[action.rawValue] = serial; errors[action.rawValue] = nil }
                else { errors[action.rawValue] = "未启用：系统拒绝注册（\(rc)）。可重新录制或清除。" }
            }
        }
        refreshMonitor()
    }
    @discardableResult
    func handleLocal(_ chord: PhotoKey, isRepeat: Bool = false) -> Bool {
        guard !recording, !isRepeat, let action = PhotoAction.allCases.first(where: {
            guard let b = binding($0), b.scope == .application, invalid($0, b) == nil else { return false }
            return b.chord.matches(chord)
        }) else { return false }
        perform(action); return true
    }
    private func refreshMonitor() {
        if let monitor { NSEvent.removeMonitor(monitor); self.monitor = nil }
        guard monitorsEnabled, !recording, bindings.values.contains(where: { $0.scope == .application }) else { return }
        monitor = NSEvent.addLocalMonitorForEvents(matching: .keyDown) { [weak self] event in
            let handled = MainActor.assumeIsolated {
                guard NSApp.isActive, NSApp.keyWindow?.identifier?.rawValue == "main",
                      !(NSApp.keyWindow?.firstResponder is NSTextView), NSApp.keyWindow?.attachedSheet == nil else { return false }
                return self?.handleLocal(PhotoKey(event), isRepeat: event.isARepeat) == true
            }
            return handled ? nil : event
        }
    }
}

private struct KeyCapture: NSViewRepresentable {
    let active: Bool
    let captured: (PhotoKey?) -> Void
    func makeNSView(context: Context) -> CaptureView { CaptureView() }
    static func dismantleNSView(_ view: CaptureView, coordinator: ()) { view.active = false }
    func updateNSView(_ view: CaptureView, context: Context) {
        view.captured = captured; view.active = active
        if active, view.window?.firstResponder !== view {
            DispatchQueue.main.async { if view.active { view.window?.makeFirstResponder(view) } }
        }
    }
    final class CaptureView: NSView {
        private var monitor: Any?
        var active = false {
            didSet {
                guard active != oldValue else { return }
                if let monitor { NSEvent.removeMonitor(monitor); self.monitor = nil }
                if active {
                    monitor = NSEvent.addLocalMonitorForEvents(matching: .keyDown) { [weak self] event in
                        let handled = MainActor.assumeIsolated {
                            guard let self, self.active, self.window?.isKeyWindow == true else { return false }
                            self.keyDown(with: event); return true
                        }
                        return handled ? nil : event
                    }
                }
            }
        }
        var captured: ((PhotoKey?) -> Void)?
        override var acceptsFirstResponder: Bool { true }
        override func keyDown(with event: NSEvent) {
            guard active else { super.keyDown(with: event); return }
            let flags = event.modifierFlags.intersection([.command, .control, .option, .shift])
            captured?(event.keyCode == 53 && flags.isEmpty ? nil : PhotoKey(event))
        }
        override func performKeyEquivalent(with event: NSEvent) -> Bool {
            guard active else { return false }; keyDown(with: event); return true
        }
        override func resignFirstResponder() -> Bool {
            if active { captured?(nil) }
            return super.resignFirstResponder()
        }
    }
}

struct ShortcutSettingsPane: View {
    @ObservedObject var center: PhotoShortcuts
    var body: some View {
        Form {
            Section {
                Text("自定义快捷键由你选择，默认不绑定全局键。").font(.headline)
                Text("空格预览、Esc 关闭、方向键导航、⌘A 全选、⌘F 搜索和 ⌘, 设置在应用内直接可用。可为下列动作追加自己的组合键；显示窗口、设置和暂停整理可选择全局。录制时 Esc 取消。")
                    .font(.callout).foregroundStyle(.secondary)
                if let error = center.errors["load"] { Text(error).foregroundStyle(.red) }
            }
            Section("应用操作") {
                ForEach(PhotoAction.allCases) { action in ShortcutRow(center: center, action: action) }
            }
            Section {
                Button("清除所有快捷键") { center.clearAll() }.disabled(center.bindings.isEmpty)
                Text("文本框沿用 macOS 的复制、粘贴等编辑操作；这里不会替你注册任何全局默认键。").font(.caption).foregroundStyle(.secondary)
            }
        }
        .formStyle(.grouped)
        .onDisappear { center.endRecording() }
    }
}

private struct ShortcutRow: View {
    @ObservedObject var center: PhotoShortcuts
    let action: PhotoAction
    private var capturing: Bool { center.recordingAction == action }
    @State private var scope: PhotoBinding.Scope = .application
    var body: some View {
        VStack(alignment: .leading, spacing: 5) {
            HStack {
                Text(action.title)
                Spacer()
                if action.allowsGlobal {
                    Picker("作用范围", selection: $scope) {
                        Text("仅 PhotoDesk 内").tag(PhotoBinding.Scope.application)
                        Text("全局").tag(PhotoBinding.Scope.global)
                    }.labelsHidden().frame(width: 105)
                    .onChange(of: scope) { _, value in
                        if let binding = center.binding(action), binding.scope != value {
                            if !center.set(action, to: PhotoBinding(chord: binding.chord, scope: value)) { scope = binding.scope }
                        }
                    }
                }
                Button(capturing ? "按下组合键…" : center.binding(action)?.chord.label ?? "点击录制") {
                    if capturing { stop(nil) } else { center.beginRecording(action: action) }
                }.frame(width: 130).accessibilityIdentifier("shortcut.\(action.rawValue)")
                    .background(KeyCapture(active: capturing, captured: stop).frame(width: 1, height: 1))
                Button { _ = center.set(action, to: nil); if capturing { stop(nil) } } label: { Image(systemName: "xmark.circle") }
                    .buttonStyle(.plain).help("清除绑定").disabled(center.binding(action) == nil)
            }
            Text(center.status(action)).font(.caption)
                .foregroundStyle(center.errors[action.rawValue] == nil ? Color.secondary : .red)
        }
        .onAppear { scope = center.binding(action)?.scope ?? .application }
        .onDisappear { if capturing { stop(nil) } }
    }
    private func stop(_ chord: PhotoKey?) {
        guard center.recordingAction == action else { return }
        center.endRecording()
        if let chord { _ = center.set(action, to: PhotoBinding(chord: chord, scope: scope)) }
    }
}
