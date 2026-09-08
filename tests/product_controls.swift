import AppKit
import Carbon.HIToolbox

@MainActor
final class FakeKeys: PhotoKeyRegistration {
    var onPress: ((UInt32) -> Void)?
    var registered: Set<UInt32> = []
    var reject = false
    func register(_ chord: PhotoKey, id: UInt32) -> OSStatus {
        if reject { return -9878 }; registered.insert(id); return noErr
    }
    func unregister(_ id: UInt32) { registered.remove(id) }
}

@main
struct ProductChecks {
    @MainActor static func main() throws {
        guard let suite = ProcessInfo.processInfo.environment["PHOTODESK_PREFERENCES_SUITE"], suite.hasPrefix("PhotoDesk.Test.") else { fatalError("isolated preferences required") }
        let defaults = PhotoPreferences.defaults
        defer { defaults.removePersistentDomain(forName: suite) }
        let model = PhotoDeskModel()
        precondition(model.preferences.automatic)
        model.preferences.automatic = false
        model.preferences.thumbnailWidth = 230
        model.preferences.petNames = "大白，小花"
        let reloaded = PhotoPreferences.load()
        precondition(!reloaded.automatic && reloaded.thumbnailWidth == 230)
        precondition((reloaded.engineOptions["pet_names"] as? [String]) == ["大白", "小花"])

        let rows = (0..<70).map { i in
            PlanRow(id: "\(i)", cloudGuid: "guid\(i)", localUuid: "uuid\(i)", filename: "fixture-\(i).png", date: "2026-09-08",
                    action: "review", target: "测试", note: "", previewPath: "", originalPath: nil, isMovie: false, originalTitle: "",
                    protected: "", group: i < 35 ? "测试" : "第二组", recommended: i == 2, readOnly: i == 4)
        }
        model.page = .library
        model.plans[.library] = PhotoPlan(id: "test", kind: "library", library: "/fake", created: "", examined: rows.count, warnings: [], csvPath: "", rows: rows)
        model.selectPhoto(rows[1]); precondition(model.selected == ["1"])
        model.selectPhoto(rows[3], modifiers: .command); precondition(model.selected == ["1", "3"])
        model.selectPhoto(rows[6], modifiers: .shift); precondition(model.selected == ["3", "5", "6"])
        precondition(model.handleNativeKey(49, modifiers: [], editingText: false, mainWindow: true))
        precondition(model.enlargedPhoto?.id == "6")
        precondition(model.handleNativeKey(124, modifiers: [], editingText: false, mainWindow: true))
        precondition(model.enlargedPhoto?.id == "7")
        precondition(model.handleNativeKey(53, modifiers: [], editingText: false, mainWindow: true))
        precondition(model.enlargedPhoto == nil)
        precondition(!model.handleNativeKey(49, modifiers: [], editingText: true, mainWindow: true))
        precondition(!model.handleNativeKey(51, modifiers: .command, editingText: true, mainWindow: true))
        precondition(!model.handleNativeKey(49, modifiers: [], editingText: false, mainWindow: false))
        model.selectPhoto(rows[59]); model.movePhoto(1); precondition(model.pageNumber == 1 && model.selected == ["60"])
        model.selectAllPhotos(); precondition(model.selected.count == 69 && !model.selected.contains("4"))
        model.updateGridWidth(900); precondition(model.gridColumns == 3)

        let timelinePlan = PhotoPlan(id: "timeline", kind: "journey", library: "/fake", created: "", examined: rows.count, warnings: [], csvPath: "", rows: rows)
        let event = JourneyEvent(id: "event", title: "片段", group: "测试", date: "", endDate: "", count: 35, tracks: ["全部"], people: [], place: "", evidence: [], cover: rows[0])
        let second = JourneyEvent(id: "second", title: "第二片段", group: "第二组", date: "", endDate: "", count: 35, tracks: ["全部"], people: [], place: "", evidence: [], cover: rows[35])
        model.journey = JourneyResult(library: "/fake", generated: "", total: rows.count, analyzed: 0, pending: rows.count, unavailable: 0, failed: 0, albums: 1, events: [event, second], tracks: [], plan: timelinePlan, duplicates: timelinePlan)
        model.navigate(.journey)
        model.selectEvent(event)
        precondition(model.activeEvent == nil && model.selectedEventIDs == ["event"] && model.selected.count == 34)
        precondition(model.handleNativeKey(49, modifiers: [], editingText: false, mainWindow: true))
        precondition(model.enlargedPhoto?.id == "0" && model.activeEvent == nil)
        _ = model.handleNativeKey(49, modifiers: [], editingText: false, mainWindow: true)
        precondition(model.enlargedPhoto == nil && model.selected.count == 34)
        model.selectEvent(second, modifiers: .command)
        precondition(model.selectedEventIDs.count == 2 && model.selected.count == 69)
        model.selectEvent(event)
        model.movePhoto(1, extend: true)
        precondition(model.selectedEventIDs.count == 2 && model.selected.count == 69)
        model.selectEvent(event)
        model.selectEvent(event, modifiers: .command); precondition(model.selected.isEmpty && model.selectedEventIDs.isEmpty)
        model.selectAllPhotos(); precondition(model.selected.count == 69)
        model.openEvent(event); precondition(model.activeEvent?.id == "event" && model.selected.isEmpty)
        model.selectPhoto(rows[0]); precondition(model.selected == ["0"] && model.enlargedPhoto == nil)

        let backend = FakeKeys(); var actions: [PhotoAction] = []
        let keys = PhotoShortcuts(defaults: defaults, backend: backend, monitorsEnabled: false) { actions.append($0) }
        precondition(keys.bindings.isEmpty && backend.registered.isEmpty)
        let chord = PhotoKey(code: 35, modifiers: UInt32(controlKey | optionKey), key: "P")
        precondition(keys.set(.pause, to: PhotoBinding(chord: chord, scope: .application)))
        precondition(keys.handleLocal(chord)); precondition(actions == [.pause])
        precondition(!keys.set(.settings, to: PhotoBinding(chord: chord, scope: .application)))
        precondition(keys.set(.pause, to: PhotoBinding(chord: chord, scope: .global)))
        precondition(backend.registered.count == 1)
        backend.reject = true
        let other = PhotoKey(code: 31, modifiers: UInt32(controlKey | optionKey), key: "O")
        precondition(!keys.set(.pause, to: PhotoBinding(chord: other, scope: .global)))
        precondition(keys.binding(.pause)?.chord == chord)
        keys.beginRecording(action: .pause); precondition(backend.registered.isEmpty)
        backend.reject = false; keys.endRecording(); precondition(backend.registered.count == 1)
        let restored = PhotoShortcuts(defaults: defaults, backend: FakeKeys(), monitorsEnabled: false) { _ in }
        precondition(restored.binding(.pause)?.chord == chord)
        precondition(PhotoKey(code: 9, modifiers: UInt32(cmdKey | shiftKey), key: "V").validationError != nil)
        precondition(PhotoKey(code: 49, modifiers: 0, key: "Space").validationError != nil)
        keys.clearAll(); precondition(keys.bindings.isEmpty && backend.registered.isEmpty)
        restored.suspend(); model.stopProductControls()
        print("Product controls passed: native selection, Space/Esc/arrows, paging, text-input isolation, settings persistence, zero default bindings, scope, conflict, registration failure, recording and cleanup.")
    }
}
