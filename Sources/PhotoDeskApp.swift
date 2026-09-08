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
        model?.cancel(); return .terminateNow
    }
    func applicationShouldTerminateAfterLastWindowClosed(_ sender: NSApplication) -> Bool { false }
}

@main
struct PhotoDeskApp: App {
    @StateObject private var model = PhotoDeskModel()
    @NSApplicationDelegateAdaptor(AppDelegate.self) private var delegate
    var body: some Scene {
        Window("PhotoDesk", id: "main") {
            ContentView(model: model).onAppear {
                delegate.model = model
                if model.summary == nil && !model.busy { model.refresh() }
            }
        }.defaultSize(width: 1180, height: 800)
            .commands {
                CommandMenu("整理") {
                    Button("刷新图库") { model.refresh() }.keyboardShortcut("r").disabled(model.busy)
                    Button("选择图库…") { model.chooseLibrary() }.disabled(model.busy)
                    Button("打开照片") { model.openPhotos() }
                    Button("打开本地记录") { model.openRecords() }
                }
            }
    }
}
