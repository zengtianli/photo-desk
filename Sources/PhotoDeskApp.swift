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
        model?.cancel(); model?.pauseAutomation(); return .terminateNow
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
            }
    }
}
