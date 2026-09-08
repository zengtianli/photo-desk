import SwiftUI
import AppKit

@MainActor
final class AppDelegate: NSObject, NSApplicationDelegate {
    weak var model: PhotoDeskModel?
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
        for window in sender.windows where window.identifier?.rawValue == "main" {
            if window.isMiniaturized { window.deminiaturize(nil) }
            window.makeKeyAndOrderFront(nil)
        }
        return true
    }
}

@main
struct PhotoDeskApp: App {
    @StateObject private var model = PhotoDeskModel()
    @NSApplicationDelegateAdaptor(AppDelegate.self) private var delegate
    var body: some Scene {
        Window("PhotoDesk", id: "main") {
            ContentView(model: model).onAppear {
                delegate.model = model
                model.startAutomation()
            }
        }.defaultSize(width: 1180, height: 800)
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
                    Button("取消选择") { model.selected = []; model.focusedPhotoID = nil }.disabled(model.selected.isEmpty)
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
                    SettingsLink { Text("PhotoDesk 使用帮助与快捷键") }
                }
            }
        Settings { PhotoSettingsView(model: model, shortcuts: model.shortcuts) }
    }
}
