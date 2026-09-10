import SwiftUI
import AppKit

/// Background capture is available only for an explicit, isolated synthetic library.
enum PhotoDeskLaunch {
    static var background: Bool {
        isIsolatedBackground(ProcessInfo.processInfo.environment,
                             home: FileManager.default.homeDirectoryForCurrentUser)
    }

    static func isIsolatedBackground(_ env: [String: String], home: URL) -> Bool {
        guard env["PHOTODESK_BACKGROUND"] == "1",
              let rootPath = env["PHOTODESK_DEMO_ROOT"], rootPath.hasPrefix("/"),
              let dataPath = env["PHOTODESK_DATA_ROOT"], dataPath.hasPrefix("/"),
              let suite = env["PHOTODESK_PREFERENCES_SUITE"],
              suite.hasPrefix("PhotoDesk.Test."), suite.count > "PhotoDesk.Test.".count else { return false }
        let root = URL(fileURLWithPath: rootPath).standardizedFileURL.resolvingSymlinksInPath()
        let data = URL(fileURLWithPath: dataPath).standardizedFileURL.resolvingSymlinksInPath()
        let normal = home.appendingPathComponent("Library/Application Support/PhotoDesk").resolvingSymlinksInPath()
        guard root.path != normal.path, !root.path.hasPrefix(normal.path + "/"),
              data.path.hasPrefix(root.path + "/"),
              data.path != normal.path, !data.path.hasPrefix(normal.path + "/") else { return false }
        var directory: ObjCBool = false
        guard FileManager.default.fileExists(atPath: data.path, isDirectory: &directory), directory.boolValue,
              let bytes = try? Data(contentsOf: root.appendingPathComponent("demo-input.json")),
              let manifest = try? JSONSerialization.jsonObject(with: bytes) as? [String: Any],
              manifest["format"] as? String == "photodesk-synthetic-input-v1" else { return false }
        return true
    }
}

private final class PhotoDeskRecordingPanel: NSPanel {
    override var canBecomeKey: Bool { false }
    override var canBecomeMain: Bool { false }
}

@MainActor
final class AppDelegate: NSObject, NSApplicationDelegate {
    weak var model: PhotoDeskModel?
    private var recordingPanel: NSPanel?

    func applicationDidFinishLaunching(_ notification: Notification) {
        guard PhotoDeskLaunch.background, let model else { return }
        NSApp.setActivationPolicy(.accessory)
        let panel = PhotoDeskRecordingPanel(contentRect: NSRect(x: 120, y: 120, width: 1180, height: 800),
            styleMask: [.titled, .closable, .resizable, .miniaturizable, .nonactivatingPanel], backing: .buffered, defer: false)
        panel.title = "PhotoDesk"
        panel.identifier = NSUserInterfaceItemIdentifier("main")
        panel.isReleasedWhenClosed = false
        panel.hidesOnDeactivate = false
        panel.isFloatingPanel = false
        panel.contentView = NSHostingView(rootView: ContentView(model: model).onAppear { model.startAutomation() })
        recordingPanel = panel
        panel.orderBack(nil)
    }

    func applicationShouldTerminate(_ sender: NSApplication) -> NSApplication.TerminateReply {
        if model?.applying == true {
            let alert = NSAlert(); alert.messageText = "正在写入照片图库"
            alert.informativeText = "请等待写入和核对完成后再退出。"; alert.runModal()
            return .terminateCancel
        }
        model?.cancel(); model?.pauseAutomation(); model?.stopProductControls(); return .terminateNow
    }
    func applicationShouldTerminateAfterLastWindowClosed(_ sender: NSApplication) -> Bool { false }
    func applicationShouldHandleReopen(_ sender: NSApplication, hasVisibleWindows flag: Bool) -> Bool {
        if PhotoDeskLaunch.background { return false }
        for window in sender.windows where window.identifier?.rawValue == "main" {
            if window.isMiniaturized { window.deminiaturize(nil) }
            window.makeKeyAndOrderFront(nil)
        }
        return true
    }
}

@main
struct PhotoDeskApp: App {
    @NSApplicationDelegateAdaptor(AppDelegate.self) private var delegate
    @StateObject private var model: PhotoDeskModel

    init() {
        let model = PhotoDeskModel()
        _model = StateObject(wrappedValue: model)
        if PhotoDeskLaunch.background { delegate.model = model }
    }

    var body: some Scene {
        Window("PhotoDesk", id: "main") {
            ContentView(model: model).onAppear {
                delegate.model = model
                model.startAutomation()
            }
        }.defaultSize(width: 1180, height: 800)
            .defaultLaunchBehavior(PhotoDeskLaunch.background ? .suppressed : .automatic)
            .commands {
                CommandGroup(replacing: .appSettings) {
                    SettingsLink { Text("设置…") }.keyboardShortcut(",")
                }
                CommandMenu("照片") {
                    Button("快速预览所选照片") { model.togglePreview() }.disabled(!model.canPreview && model.enlargedPhoto == nil)
                    Button("下一张") { model.movePhoto(1) }.disabled(!model.photoGridVisible)
                    Button("上一张") { model.movePhoto(-1) }.disabled(!model.photoGridVisible)
                    Divider()
                    Button("全选筛选结果") { model.selectAllPhotos() }.disabled(!model.photoGridVisible || model.busy)
                    Button("取消选择") {
                        if model.timelineVisible { model.clearEventSelection() }
                        else { model.selected = []; model.focusedPhotoID = nil }
                    }.disabled(model.selected.isEmpty && model.selectedEventIDs.isEmpty)
                    Button("在“照片”中打开所选照片") { if let row = model.previewRow { model.revealPhoto(row) } }.disabled(model.previewRow == nil || model.busy)
                    Button("搜索照片") { model.performAction(.search) }.keyboardShortcut("f")
                    Divider()
                    Button("删除所选照片…") { model.performAction(.delete) }.keyboardShortcut(.delete, modifiers: .command).disabled(model.selected.isEmpty || model.busy || !model.gridFocused)
                }
                CommandMenu("整理") {
                    Button("刷新图库") { model.refresh() }.keyboardShortcut("r").disabled(model.busy)
                    Button("选择图库…") { model.chooseLibrary() }.disabled(model.busy)
                    Button("打开照片") { model.openPhotos() }
                    Button("打开本地记录") { model.openRecords() }
                    Menu("高级整理") {
                        ForEach([Page.classify, .triage, .sensitive, .title]) { page in
                            Button(page.name) { model.navigate(page) }.disabled(model.busy)
                        }
                    }
                    Divider()
                    Button("导入验收测试图…") { model.confirmFixture = true }.disabled(model.busy)
                }
                CommandGroup(replacing: .help) {
                    Button("PhotoDesk 安装与使用教程") {
                        if let url = URL(string: "https://app-mac-photodesk.tianli.cyou/#start") { NSWorkspace.shared.open(url) }
                    }
                    SettingsLink { Text("PhotoDesk 设置与快捷键") }
                }
            }
        Settings { PhotoSettingsView(model: model, shortcuts: model.shortcuts) }
    }
}
