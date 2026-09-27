import AppKit
import SwiftUI

/// Fixed, in-process UI acceptance. This entry never creates the normal App scenes,
/// orders a window, registers shortcuts, or connects to the user's Photos library.
@MainActor
enum PhotoDeskUISelfTest {
    static func launch() {
        let env = ProcessInfo.processInfo.environment
        guard PhotoDeskLaunch.background,
              let root = env["PHOTODESK_DEMO_ROOT"], env["PHOTODESK_LIBRARY"] == root,
              let output = env["PHOTODESK_UI_TEST_OUTPUT"], output.hasPrefix("/") else {
            fputs("UI self-test requires a marked synthetic root, isolated preferences and output.\n", stderr)
            exit(2)
        }
        let application = NSApplication.shared
        application.setActivationPolicy(.prohibited)
        Task { await run(output: URL(fileURLWithPath: output, isDirectory: true)) }
        application.run()
    }

    private static func waitUntil(_ condition: () -> Bool) async throws {
        let deadline = Date().addingTimeInterval(40)
        while !condition() {
            guard Date() < deadline else { throw failure("等待真实模型更新超时") }
            try await Task.sleep(for: .milliseconds(80))
        }
    }

    private static func failure(_ text: String) -> NSError {
        NSError(domain: "PhotoDesk.UISelfTest", code: 1, userInfo: [NSLocalizedDescriptionKey: text])
    }

    private static func snapshot<V: View>(_ view: V, name: String, size: NSSize, output: URL) async throws -> [String: Any] {
        let window = NSWindow(contentRect: NSRect(origin: NSPoint(x: -20000, y: -20000), size: size),
                              styleMask: .borderless, backing: .buffered, defer: false)
        window.isReleasedWhenClosed = false
        window.appearance = NSAppearance(named: .aqua)
        let hosting = NSHostingView(rootView: view
            .background(Color(nsColor: .windowBackgroundColor))
            .environment(\.colorScheme, .light))
        window.contentView = hosting
        defer { window.contentView = nil; window.close() }
        hosting.frame = NSRect(origin: .zero, size: size)
        // Materialize lazy cells before yielding so their image tasks can finish.
        hosting.layoutSubtreeIfNeeded()
        hosting.displayIfNeeded()
        try await Task.sleep(for: .milliseconds(500))
        hosting.layoutSubtreeIfNeeded()
        hosting.displayIfNeeded()
        guard !window.isVisible, !window.isKeyWindow, !window.isMainWindow,
              let bitmap = hosting.bitmapImageRepForCachingDisplay(in: hosting.bounds) else {
            throw failure("离屏视图不应成为可见或输入窗口")
        }
        hosting.cacheDisplay(in: hosting.bounds, to: bitmap)
        guard let png = bitmap.representation(using: .png, properties: [:]), png.count > 10000,
              bitmap.pixelsWide >= Int(size.width), bitmap.pixelsHigh >= Int(size.height) else {
            throw failure("真实视图未生成有效截图：\(name)")
        }
        try png.write(to: output.appendingPathComponent(name + ".png"), options: .atomic)
        return ["file": name + ".png", "width": bitmap.pixelsWide, "height": bitmap.pixelsHigh, "bytes": png.count]
    }

    private static func run(output: URL) async {
        var checks: [String: Bool] = [:]
        var screenshots: [[String: Any]] = []
        var counts: [String: Int] = [:]
        let suite = ProcessInfo.processInfo.environment["PHOTODESK_PREFERENCES_SUITE"]!
        PhotoPreferences.defaults.removePersistentDomain(forName: suite)
        var preferences = PhotoPreferences()
        preferences.recognizeContent = false
        preferences.appearance = "light"
        preferences.save()
        let model = PhotoDeskModel()
        defer {
            model.cancel(); model.pauseAutomation(); model.stopProductControls()
            PhotoPreferences.defaults.removePersistentDomain(forName: suite)
        }
        do {
            try FileManager.default.createDirectory(at: output, withIntermediateDirectories: true)
            model.startAutomation()
            try await waitUntil { model.journey != nil || model.organizationError != nil }
            model.pauseAutomation()
            guard let journey = model.journey, journey.events.count >= 3 else {
                throw failure(model.organizationError ?? "合成时间线缺失")
            }
            checks["automatic_timeline"] = journey.total == 10 && journey.plan.rows.count == 10
            counts["photos"] = journey.total; counts["events"] = journey.events.count
            screenshots.append(try await snapshot(ContentView(model: model), name: "timeline", size: NSSize(width: 1180, height: 800), output: output))

            let event = journey.events[0]
            model.selectEvent(event)
            let eventRows = journey.plan.rows.filter { $0.group == event.group && $0.readOnly != true }
            checks["single_click_selects_fragment"] = model.activeEvent == nil && model.selectedEventIDs == [event.id]
                && model.selectedPhotoCount == eventRows.count && model.enlargedPhoto == nil
            counts["selected_fragment_photos"] = model.selectedPhotoCount
            model.selectEvent(journey.events[1], modifiers: .command)
            checks["command_multiselect"] = model.selectedEventIDs.count == 2 && model.selectedPhotoCount > eventRows.count
            let pinnedIDs = model.selected
            model.journey = nil
            checks["selection_is_pinned_during_refresh"] = model.selected == pinnedIDs && model.events.count == journey.events.count
            model.journey = journey
            model.selectEvent(event)
            screenshots.append(try await snapshot(ContentView(model: model), name: "selection", size: NSSize(width: 1180, height: 800), output: output))
            model.togglePreview()
            checks["preview_opens_cover"] = model.enlargedPhoto?.id == event.cover.id
            guard let row = model.enlargedPhoto else { throw failure("预览未打开") }
            screenshots.append(try await snapshot(LargePhotoPreview(row: row, previous: { model.movePhoto(-1) }, next: { model.movePhoto(1) }, reveal: { model.revealPhoto(row) }, close: { model.closePreview() }), name: "preview", size: NSSize(width: 850, height: 700), output: output))
            model.closePreview()
            checks["preview_close_preserves_selection"] = model.enlargedPhoto == nil && model.selectedEventIDs == [event.id]
            model.openEvent(event)
            checks["explicit_open_fragment"] = model.activeEvent?.id == event.id && model.selected.isEmpty && model.filteredRows.count == event.count
            guard let first = model.filteredRows.first else { throw failure("片段内照片缺失") }
            model.selectPhoto(first)
            model.movePhoto(1, extend: true)
            checks["range_selection"] = model.selectedPhotoCount == min(2, model.filteredRows.count)
            let selected = model.selected
            checks["search_typing_isolated"] = !model.handleNativeKey(49, modifiers: [], editingText: true, mainWindow: true) && model.selected == selected && model.enlargedPhoto == nil
            model.updateGridWidth(760); let narrow = model.gridColumns
            model.updateGridWidth(1160)
            checks["adaptive_columns"] = narrow >= 1 && model.gridColumns > narrow
            screenshots.append(try await snapshot(ContentView(model: model), name: "fragment", size: NSSize(width: 1060, height: 760), output: output))

            checks["shortcuts_default_empty"] = model.shortcuts.bindings.isEmpty
            model.preferences.thumbnailWidth = 210
            checks["settings_autosave"] = PhotoPreferences.load().thumbnailWidth == 210
            screenshots.append(try await snapshot(PhotoSettingsView(model: model, shortcuts: model.shortcuts), name: "settings", size: NSSize(width: 670, height: 630), output: output))
            model.refresh()
            try await waitUntil { !model.busy }
            checks["refresh_action"] = model.summary?.total == 10 && model.error == nil
            model.pauseAutomation()
            model.clearEventSelection()
            checks["clear_selection"] = model.selected.isEmpty && model.selectedEventIDs.isEmpty
            checks["offscreen_only"] = NSApp.activationPolicy() == .prohibited && NSApp.windows.allSatisfy { !$0.isVisible && !$0.isKeyWindow }
            checks["real_views_rendered"] = screenshots.count == 5
        } catch {
            checks["runtime_completed"] = false
            fputs("\(error.localizedDescription)\n", stderr)
        }
        let result: [String: Any] = ["ok": !checks.isEmpty && checks.values.allSatisfy { $0 }, "checks": checks,
            "counts": counts, "screenshots": screenshots, "scope": "Real SwiftUI views and model actions; marked synthetic library; no input synthesis or visible windows."]
        if let data = try? JSONSerialization.data(withJSONObject: result, options: [.prettyPrinted, .sortedKeys]) {
            try? data.write(to: output.appendingPathComponent("ui-self-test.json"), options: .atomic)
            print(String(decoding: data, as: UTF8.self))
        }
        model.cancel(); model.pauseAutomation(); model.stopProductControls()
        PhotoPreferences.defaults.removePersistentDomain(forName: suite)
        exit(checks.values.allSatisfy { $0 } ? 0 : 1)
    }
}
