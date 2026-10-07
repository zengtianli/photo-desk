// The commands that belong to the app itself: `photodesk config | update | shortcuts | login | automation | cancel`.
// The frozen engine (backend/desk_cli.py, APP_VERBS) starts this executable with the words after `photodesk` and
// brings its stdout, stderr and exit code back unchanged. PhotoDeskEntry.main answers before any NSApplication
// exists: no window, no Dock icon, no prompt, no hotkey registration. A PhotoDesk that is already running is not
// restarted; it follows through AppLifecycleCLI.follow and answers `automation` / `cancel` through PhotoRemote.
import AppKit
import Carbon.HIToolbox
import ServiceManagement

/// One factory for the「配置与更新…」window and the `photodesk config` / `photodesk update` commands.
enum PhotoLifecycle {
    static let name = "PhotoDesk"
    static let command = "photodesk"
    static let productID = "cyou.tianli.PhotoDesk"
    static let updateSource: AppUpdateSource = .github(repository: "zengtianli/photo-desk")
    static let defaultsKeys = [PhotoPreferences.storageKey, "shortcuts.v1"]
    static let testPrefix = "PhotoDesk.Test."
    static let refusal = "这次运行没有指明用哪一份设置：隔离运行（设了 APP_LIFECYCLE_SUPPORT_DIR）必须同时把 PHOTODESK_PREFERENCES_SUITE 设成 PhotoDesk.Test. 开头的测试偏好域；不隔离时不能带 PHOTODESK_PREFERENCES_SUITE 或 PHOTODESK_DEMO_ROOT。未读取也未改动任何设置。"

    static var isolated: Bool { ProcessInfo.processInfo.environment["APP_LIFECYCLE_SUPPORT_DIR"] != nil }
    /// The test preferences domain this run names, if any (the product's own PHOTODESK_PREFERENCES_SUITE).
    static var suite: String? { ProcessInfo.processInfo.environment["PHOTODESK_PREFERENCES_SUITE"] }

    /// The preferences a command may open. An isolated run keeps the shared layer in its temporary support and cloud
    /// folders, so the settings must come from a PhotoDesk.Test.* domain too; a run that is not isolated works on the
    /// owner's own settings, support folder and iCloud, and must not pair those with a test domain or the demo
    /// library. nil: refuse before anything is read.
    static func commandDefaults() -> UserDefaults? {
        if isolated {
            guard let suite, suite.hasPrefix(testPrefix), suite.count > testPrefix.count else { return nil }
            return UserDefaults(suiteName: suite)
        }
        guard suite == nil, ProcessInfo.processInfo.environment["PHOTODESK_DEMO_ROOT"] == nil else { return nil }
        return .standard
    }
    static func makeConfiguration(_ defaults: UserDefaults) -> AppConfiguration {
        AppConfiguration(productID: productID, defaultsKeys: defaultsKeys, defaults: defaults)
    }
    static func product(_ defaults: UserDefaults?) -> AppLifecycleCLI.Product {
        AppLifecycleCLI.Product(command: command, name: name, configuration: defaults.map(makeConfiguration), updateSource: updateSource)
    }

    /// How many times the window's configuration asked the app to re-read (the probe reports it).
    @MainActor static var changes = 0
    /// The app's wiring, used by PhotoDeskApp.init and by the offscreen probe: the window, the reload after an import
    /// or a sync, and the follower for changes made by `photodesk config …` in another process. The follower never
    /// stores the switch, and the reload stores nothing either: it adopts what is stored (`adoptingStored`), so a
    /// reading that is a moment behind another process can never be written back over a newer command.
    @MainActor static func installApp(model: PhotoDeskModel, defaults: UserDefaults) -> AppConfiguration {
        let config = makeConfiguration(defaults)
        config.onChange = { [weak model] in
            MainActor.assumeIsolated {
                guard let model else { return }
                changes += 1
                let restored = PhotoPreferences.load()
                if restored != model.preferences {
                    model.adoptingStored = true
                    model.preferences = restored
                    model.adoptingStored = false
                }
                model.shortcuts.reload()
            }
        }
        AppLifecycleUI.install(name: name, configuration: config, updateSource: updateSource)
        AppLifecycleCLI.follow(config)
        return config
    }
}

/// A running PhotoDesk answers `photodesk automation …` and `photodesk cancel` here: a request and its reply are two
/// distributed notifications, nothing is written to disk and nothing runs while no command asks. The actions are the
/// window's own (the 暂停自动整理 / 继续自动整理 button and the status bar's 取消). A run with a test preferences domain
/// uses a channel of its own, so a test never reaches the owner's running app and the other way round.
@MainActor
enum PhotoRemote {
    static var channel: String { "cyou.tianli.PhotoDesk.remote" + (PhotoLifecycle.suite.map { "." + $0 } ?? "") }
    private static var observer: NSObjectProtocol?

    static func serve(_ model: PhotoDeskModel) {
        guard observer == nil else { return }
        observer = DistributedNotificationCenter.default().addObserver(forName: Notification.Name(channel + ".request"), object: nil, queue: .main) { [weak model] note in
            let text = note.object as? String
            MainActor.assumeIsolated {
                guard let model, let parts = text?.split(separator: " ", maxSplits: 1).map(String.init), parts.count == 2 else { return }
                var reply = perform(parts[1], on: model)
                reply["id"] = parts[0]
                guard let data = try? JSONSerialization.data(withJSONObject: reply, options: [.sortedKeys]) else { return }
                DistributedNotificationCenter.default().postNotificationName(Notification.Name(channel + ".reply"), object: String(decoding: data, as: UTF8.self),
                                                                             userInfo: nil, deliverImmediately: true)
            }
        }
    }

    static func state(_ model: PhotoDeskModel) -> [String: Any] {
        ["pid": Int(ProcessInfo.processInfo.processIdentifier), "automatic_setting": model.preferences.automatic,
         "automatic_enabled": model.automaticEnabled, "organizing": model.organizing,
         "organization_status": model.organizationStatus, "organization_error": model.organizationError ?? NSNull(),
         "busy": model.busy, "applying": model.applying, "task_status": model.status]
    }

    static func perform(_ action: String, on model: PhotoDeskModel) -> [String: Any] {
        var extra: [String: Any] = ["action": action, "was_enabled": model.automaticEnabled, "was_busy": model.busy]
        switch action {
        case "status": break
        case "pause": model.pauseAutomation()
        case "resume": model.startAutomation(restart: true)
        case "cancel":
            extra["cancel_requested"] = model.busy && !model.applying
            model.cancel()
        default: extra["unknown_action"] = true
        }
        return state(model).merging(extra) { _, new in new }
    }

    /// Command side: one request, the first matching reply, or nil when no app answers in time.
    static func ask(_ action: String, timeout: TimeInterval) -> [String: Any]? {
        final class Box: @unchecked Sendable { var value: [String: Any]? }   // touched on the main thread only
        let box = Box(), id = UUID().uuidString, center = DistributedNotificationCenter.default()
        let token = center.addObserver(forName: Notification.Name(channel + ".reply"), object: nil, queue: .main) { note in
            guard let text = note.object as? String, let body = try? JSONSerialization.jsonObject(with: Data(text.utf8)) as? [String: Any],
                  body["id"] as? String == id else { return }
            box.value = body
        }
        defer { center.removeObserver(token) }
        center.postNotificationName(Notification.Name(channel + ".request"), object: id + " " + action, userInfo: nil, deliverImmediately: true)
        // Uptime, not wall time: a Mac that sleeps in the middle must not turn into a false timeout.
        let deadline = ProcessInfo.processInfo.systemUptime + timeout
        while box.value == nil && ProcessInfo.processInfo.systemUptime < deadline { RunLoop.current.run(until: Date().addingTimeInterval(0.02)) }
        return box.value
    }
}

/// Stored bindings only: the command never registers a hotkey with the system and never watches the keyboard.
@MainActor
private final class StoredKeys: PhotoKeyRegistration {
    var onPress: ((UInt32) -> Void)?
    func register(_ chord: PhotoKey, id: UInt32) -> OSStatus { noErr }
    func unregister(_ id: UInt32) {}
}

@MainActor
enum PhotoCommands {
    static let own = ["shortcuts", "login", "automation", "cancel"]
    static func handles(_ verb: String?) -> Bool { verb.map { AppLifecycleCLI.verbs.contains($0) || own.contains($0) } ?? false }

    private struct Failure: Error {
        let exit: Int32, code: String, message: String
        var extra: [String: Any] = [:]
        static func usage(_ message: String) -> Failure { Failure(exit: 2, code: "usage", message: message) }
    }
    private struct Output { var body: [String: Any]; var lines: [String] }
    private struct Arguments { var positionals: [String] = []; var flags: Set<String> = [] }

    /// `words` starts at the verb: ["shortcuts", "--json"]. Returns the exit code.
    static func run(_ words: [String]) -> Int32 {
        let verb = words[0], json = words.contains("--json")
        if AppLifecycleCLI.handles(verb) {
            // The help names no setting, so it is answered whatever the environment says.
            if words.contains("--help") || words.contains("-h") { return AppLifecycleCLI.run(words, product: PhotoLifecycle.product(nil)) }
            guard let defaults = PhotoLifecycle.commandDefaults() else {
                return report(Failure(exit: 1, code: "isolation_incomplete", message: PhotoLifecycle.refusal),
                              command: words.prefix(2).filter { !$0.hasPrefix("-") }.joined(separator: " "), json: json)
            }
            return AppLifecycleCLI.run(words, product: PhotoLifecycle.product(defaults))
        }
        var command = verb
        do {
            let p = try parse(Array(words.dropFirst()))
            if p.flags.contains("--help") || p.flags.contains("-h") { write(help(verb), to: .standardOutput); return 0 }
            let sub = p.positionals.first
            let result: Output
            switch verb {
            case "shortcuts":
                command = "shortcuts" + (sub.map { $0 == "list" ? "" : " " + $0 } ?? "")
                result = try shortcuts(p)
            case "login":
                command = "login " + (sub ?? "status")
                result = try login(p)
            case "automation":
                command = "automation " + (sub ?? "status")
                result = try automation(p)
            default: result = try cancel(p)
            }
            if json {
                var body = result.body
                body["ok"] = true; body["command"] = command
                write(text(body), to: .standardOutput)
            } else { write(result.lines.joined(separator: "\n"), to: .standardOutput) }
            return 0
        } catch let failure as Failure { return report(failure, command: command, json: json) }
        catch { return report(Failure(exit: 1, code: "failed", message: error.localizedDescription), command: command, json: json) }
    }

    // MARK: shortcuts — the 快捷键 page of the settings window, on the same stored bindings and the same rules

    private static func shortcuts(_ p: Arguments) throws -> Output {
        let center = PhotoShortcuts(defaults: PhotoPreferences.defaults, backend: StoredKeys(), monitorsEnabled: false) { _ in }
        func row(_ action: PhotoAction) -> [String: Any] {
            let binding = center.binding(action), conflict = center.errors[action.rawValue]
            var row: [String: Any] = ["action": action.rawValue, "title": action.title, "allows_global": action.allowsGlobal,
                                      "conflict": conflict ?? NSNull(), "binding": NSNull()]
            if let binding {
                row["binding"] = ["label": binding.chord.label, "key": binding.chord.key, "code": Int(binding.chord.code),
                                  "modifiers": Int(binding.chord.modifiers), "scope": binding.scope.rawValue]
            }
            row["status"] = conflict ?? (binding == nil ? "未设置" : binding?.scope == .global ? "已保存 · 全局" : "已保存 · 仅 PhotoDesk 内")
            return row
        }
        func listing(_ changed: [String: Any] = [:]) -> Output {
            let rows = PhotoAction.allCases.map(row)
            var body: [String: Any] = ["domain": domain, "app_running": sharesSettingsWithRunningApp(), "shortcuts": rows,
                                       "load_error": center.errors["load"] ?? NSNull(), "bound": center.bindings.count,
                                       "note": "这里是保存下来的绑定与能从绑定本身判断的冲突；系统是否接受某个全局快捷键的注册只有运行中的 PhotoDesk 知道。"]
            body.merge(changed) { _, new in new }
            var lines = rows.map { row -> String in
                let label = (row["binding"] as? [String: Any])?["label"] as? String ?? "—"
                return "  \(row["action"] ?? "") · \(row["title"] ?? "") · \(label) · \(row["status"] ?? "")"
            }
            if let error = center.errors["load"] { lines.insert(error, at: 0) }
            return Output(body: body, lines: lines)
        }
        guard let sub = p.positionals.first, sub != "list" else {
            guard p.positionals.count <= 1, p.flags.isSubset(of: ["--json"]) else { throw Failure.usage(usage("shortcuts")) }
            return listing()
        }
        guard ["scope", "clear"].contains(sub) else { throw Failure.usage(usage("shortcuts")) }
        func action(_ raw: String) throws -> PhotoAction {
            guard let action = PhotoAction(rawValue: raw) else {
                throw Failure.usage("没有动作 \(raw)；可用：" + PhotoAction.allCases.map(\.rawValue).joined(separator: " "))
            }
            return action
        }
        // Parse first, refuse second: a mistyped command is a usage error whether or not the app is running.
        var change: (() throws -> [String: Any])
        if sub == "scope" {
            guard p.positionals.count == 3, p.flags.isSubset(of: ["--json"]), let scope = PhotoBinding.Scope(rawValue: p.positionals[2]) else {
                throw Failure.usage(usage("shortcuts"))
            }
            let target = try action(p.positionals[1])
            change = {
                guard let binding = center.binding(target) else {
                    throw Failure(exit: 1, code: "not_bound", message: "「\(target.title)」还没有绑定快捷键；组合键要在设置窗口里按键录制，命令只改已有绑定的作用范围。")
                }
                let before = binding.scope
                guard center.set(target, to: PhotoBinding(chord: binding.chord, scope: scope)) else {
                    throw Failure(exit: 1, code: "rejected", message: center.errors[target.rawValue] ?? "未能更改作用范围，原绑定保留。")
                }
                return ["action": target.rawValue, "scope": scope.rawValue, "changed": before != scope]
            }
        } else {
            let all = p.flags.contains("--all")
            guard p.flags.isSubset(of: ["--json", "--all"]), p.positionals.count == (all ? 1 : 2) else { throw Failure.usage(usage("shortcuts")) }
            let target = all ? nil : try action(p.positionals[1])
            change = {
                let before = center.bindings.count
                if let target {
                    let had = center.binding(target) != nil
                    _ = center.set(target, to: nil)
                    return ["action": target.rawValue, "cleared": had ? 1 : 0, "changed": had]
                }
                center.clearAll()
                return ["cleared": before, "changed": before > 0]
            }
        }
        guard !sharesSettingsWithRunningApp() else {
            throw Failure(exit: 1, code: "app_running", message: "PhotoDesk 正在运行：快捷键保存在运行中的 App 里，会覆盖外部修改。请在设置窗口（⌘,）的“快捷键”页修改，或退出 PhotoDesk 后重试。未改动。")
        }
        let changed = try change()
        // The same UserDefaults object wrote it; a short-lived process must not exit before it reaches the store.
        PhotoPreferences.defaults.synchronize()
        var output = listing(changed)
        output.lines.insert(changed["changed"] as? Bool == true ? "已保存。" : "没有需要改的。", at: 0)
        return output
    }

    // MARK: login — 登录 Mac 时启动

    private static func login(_ p: Arguments) throws -> Output {
        func read() -> (enabled: Bool, state: String, sentence: String) {
            switch SMAppService.mainApp.status {
            case .enabled: return (true, "enabled", "登录 Mac 时启动：开")
            case .requiresApproval: return (false, "requires_approval", "登录 Mac 时启动：已登记，等待在系统设置 → 通用 → 登录项中允许 PhotoDesk")
            case .notFound: return (false, "not_found", "登录 Mac 时启动：关（系统里没有这个 App 的登录项记录）")
            default: return (false, "not_registered", "登录 Mac 时启动：关")
            }
        }
        let sub = p.positionals.first ?? "status"
        let now = read()
        var body: [String: Any] = ["enabled": now.enabled, "state": now.state, "app_path": Bundle.main.bundlePath]
        if sub == "status" {
            guard p.positionals.count <= 1, p.flags.isSubset(of: ["--json"]) else { throw Failure.usage(usage("login")) }
            return Output(body: body, lines: [now.sentence])
        }
        guard let target = ["on": true, "off": false][sub], p.positionals.count == 1, p.flags.isSubset(of: ["--json", "--yes", "--dry-run"]) else {
            throw Failure.usage(usage("login"))
        }
        let word = target ? "开" : "关"
        body["action"] = sub; body["check_with"] = "photodesk login status"
        if p.flags.contains("--dry-run") {
            body["dry_run"] = true; body["would_change"] = now.enabled != target
            return Output(body: body, lines: [now.enabled == target ? "「登录 Mac 时启动」已是\(word)，不会改动" : "将把「登录 Mac 时启动」拨到\(word)（未执行）"])
        }
        if now.enabled == target {
            body["changed"] = false
            return Output(body: body, lines: ["「登录 Mac 时启动」已是\(word)"])
        }
        guard p.flags.contains("--yes") else {
            throw Failure(exit: 2, code: "confirmation_required", message: "会\(target ? "把 PhotoDesk 登记为" : "从系统移除 PhotoDesk 的")登录项：确认请加 --yes（或先 --dry-run）")
        }
        // The login item is the system's, not a preference: an isolated or demo run must never change it.
        guard !PhotoLifecycle.isolated, PhotoLifecycle.suite == nil, ProcessInfo.processInfo.environment["PHOTODESK_DEMO_ROOT"] == nil else {
            throw Failure(exit: 1, code: "isolated_run", message: "隔离或演示运行不改系统登录项。未改动。")
        }
        do { if target { try SMAppService.mainApp.register() } else { try SMAppService.mainApp.unregister() } }
        catch { throw Failure(exit: 1, code: "failed", message: "未能更改登录启动：\(error.localizedDescription)", extra: body) }
        let after = read()
        body["enabled"] = after.enabled; body["state"] = after.state; body["changed"] = after.enabled != now.enabled
        guard after.enabled == target else {
            throw Failure(exit: 1, code: after.state == "requires_approval" ? "requires_approval" : "failed",
                          message: after.state == "requires_approval" ? "已登记，还需要在系统设置 → 通用 → 登录项中允许 PhotoDesk。" : "系统没有接受这次更改：\(after.sentence)", extra: body)
        }
        return Output(body: body, lines: [target ? "已启用登录启动" : "登录启动已关闭"])
    }

    // MARK: automation, cancel — a running PhotoDesk's own actions

    /// nil: no PhotoDesk that shares these settings is running. Throws when one is running and does not answer.
    private static func askApp(_ action: String) throws -> [String: Any]? {
        let registered = bundleRunning()
        guard registered || peerRunning() else { return nil }
        if let reply = PhotoRemote.ask(action, timeout: 3) { return reply }
        // No answer. A test domain: only an app on the same channel counts. Not registered as an app: the other
        // process was another command, not a window.
        guard registered, PhotoLifecycle.suite == nil else { return nil }
        throw Failure(exit: 1, code: "no_reply", message: "PhotoDesk 在运行，但 3 秒内没有应答（可能是不带这个命令的旧版本，或正忙）。未做任何改动。")
    }
    private static func stored() -> [String: Any] {
        ["app_running": false, "automatic_setting": PhotoPreferences.load().automatic]
    }
    private static func sentence(_ state: [String: Any]) -> [String] {
        ["自动整理：\(state["automatic_enabled"] as? Bool == true ? "进行中" : "已停") · \(state["organization_status"] as? String ?? "")",
         "任务：\(state["applying"] as? Bool == true ? "正在写入图库" : state["busy"] as? Bool == true ? "进行中" : "空闲") · \(state["task_status"] as? String ?? "")"]
    }

    private static func automation(_ p: Arguments) throws -> Output {
        let sub = p.positionals.first ?? "status"
        guard ["status", "pause", "resume"].contains(sub), p.positionals.count <= 1, p.flags.isSubset(of: ["--json"]) else { throw Failure.usage(usage("automation")) }
        guard var state = try askApp(sub) else {
            if sub == "status" {
                let body = stored()
                return Output(body: body, lines: ["PhotoDesk 未运行：没有正在进行的自动整理。打开后是否自动整理：\(body["automatic_setting"] as? Bool == true ? "是" : "否")（settings set automatic 可改）"])
            }
            throw Failure(exit: 1, code: "app_not_running", message: "PhotoDesk 未运行：没有可\(sub == "pause" ? "暂停" : "继续")的自动整理。打开后是否自动整理用 photodesk settings set automatic 决定。", extra: stored())
        }
        state.removeValue(forKey: "id"); state["app_running"] = true
        guard sub != "status" else { return Output(body: state, lines: sentence(state)) }
        let enabled = state["automatic_enabled"] as? Bool == true
        state["changed"] = (state["was_enabled"] as? Bool) != enabled
        state["check_with"] = "photodesk automation status"
        if sub == "resume" && !enabled {
            throw Failure(exit: 1, code: "automatic_off", message: state["organization_status"] as? String ?? "自动整理已关闭；可在设置中重新开启", extra: state)
        }
        if sub == "pause" && enabled { throw Failure(exit: 1, code: "failed", message: "PhotoDesk 没有停下自动整理。", extra: state) }
        return Output(body: state, lines: sentence(state))
    }

    private static func cancel(_ p: Arguments) throws -> Output {
        guard p.positionals.isEmpty, p.flags.isSubset(of: ["--json"]) else { throw Failure.usage(usage("cancel")) }
        guard var state = try askApp("cancel") else {
            var body = stored(); body["cancelled"] = false
            return Output(body: body, lines: ["PhotoDesk 未运行，没有进行中的任务。"])
        }
        state.removeValue(forKey: "id"); state["app_running"] = true
        state["check_with"] = "photodesk automation status"
        if state["applying"] as? Bool == true {
            state["cancelled"] = false
            throw Failure(exit: 1, code: "applying", message: "PhotoDesk 正在写入照片图库，写入和核对完成前不能取消（窗口里这时也没有“取消”）。", extra: state)
        }
        guard state["cancel_requested"] as? Bool == true else {
            state["cancelled"] = false
            return Output(body: state, lines: ["没有进行中的任务。"])
        }
        // The app cancels its task and stops the engine process it started; wait until the task has really ended.
        let deadline = ProcessInfo.processInfo.systemUptime + 8
        while state["busy"] as? Bool == true && ProcessInfo.processInfo.systemUptime < deadline {
            RunLoop.current.run(until: Date().addingTimeInterval(0.2))
            if var next = PhotoRemote.ask("status", timeout: 2) { next.removeValue(forKey: "id"); next["app_running"] = true; next["check_with"] = state["check_with"]; state = next }
        }
        state["cancel_requested"] = true
        state["cancelled"] = state["busy"] as? Bool != true
        guard state["cancelled"] as? Bool == true else {
            throw Failure(exit: 1, code: "cancel_pending", message: "已请求取消，任务 8 秒内还没有结束；用 photodesk automation status 再读一次。", extra: state)
        }
        return Output(body: state, lines: ["已取消。" + (state["task_status"] as? String ?? "")])
    }

    // MARK: Plumbing

    private static var domain: String { PhotoLifecycle.suite ?? Bundle.main.bundleIdentifier ?? PhotoLifecycle.productID }
    private static func bundleRunning() -> Bool {
        guard let identifier = Bundle.main.bundleIdentifier else { return false }
        let own = ProcessInfo.processInfo.processIdentifier
        return NSRunningApplication.runningApplications(withBundleIdentifier: identifier).contains { $0.processIdentifier != own }
    }
    /// A running app keeps settings and bindings in memory and saves them whole. With the owner's settings that is any
    /// running PhotoDesk; with a test domain only an app answering on that domain's channel.
    private static func sharesSettingsWithRunningApp() -> Bool {
        let registered = bundleRunning()
        if registered && PhotoLifecycle.suite == nil { return true }
        return (registered || peerRunning()) && PhotoRemote.ask("status", timeout: 1.5) != nil
    }
    /// Another process started from this same executable: a PhotoDesk the system does not list as an app yet, or a
    /// second command. Only a reason to ask; the answer decides.
    private static func peerRunning() -> Bool {
        guard let own = Bundle.main.executableURL?.resolvingSymlinksInPath().path else { return false }
        var pids = [pid_t](repeating: 0, count: 16384)
        let count = Int(proc_listallpids(&pids, Int32(MemoryLayout<pid_t>.size * pids.count)))
        let me = ProcessInfo.processInfo.processIdentifier
        var path = [CChar](repeating: 0, count: 4 * Int(MAXPATHLEN))
        for pid in pids.prefix(max(0, count)) where pid > 0 && pid != me {
            guard proc_pidpath(pid, &path, UInt32(path.count)) > 0 else { continue }
            if URL(fileURLWithPath: String(cString: path)).resolvingSymlinksInPath().path == own { return true }
        }
        return false
    }

    private static func parse(_ arguments: [String]) throws -> Arguments {
        var parsed = Arguments()
        for argument in arguments {
            if ["--json", "--yes", "--dry-run", "--all", "--help", "-h"].contains(argument) { parsed.flags.insert(argument) }
            else if argument.hasPrefix("-") { throw Failure.usage("未知参数 \(argument)") }
            else { parsed.positionals.append(argument) }
        }
        return parsed
    }
    private static func usage(_ verb: String) -> String {
        switch verb {
        case "shortcuts": return "用法：photodesk shortcuts [list] | scope <动作> application|global | clear <动作> | clear --all（都可加 --json）"
        case "login": return "用法：photodesk login [status] | on|off --yes [--dry-run]（都可加 --json）"
        case "automation": return "用法：photodesk automation [status] | pause | resume（都可加 --json）"
        default: return "用法：photodesk cancel [--json]"
        }
    }
    private static let shape = """
        --json：成功 {"ok": true, "command": …, …}；失败 {"ok": false, "command": …, "error": {"code", "message"}}，退出码非零。
        退出码：0 成功 · 1 操作未完成 · 2 用法错误或缺确认参数（error.code：usage、confirmation_required）
        命令不弹窗、不抢焦点、不申请权限、不注册快捷键。
        """
    private static func help(_ verb: String) -> String {
        switch verb {
        case "shortcuts": return """
            usage: photodesk shortcuts [list] [--json]
                   photodesk shortcuts scope <动作> application|global [--json]
                   photodesk shortcuts clear <动作> [--json]
                   photodesk shortcuts clear --all [--json]
            设置窗口“快捷键”页：同一份保存的绑定、同一套规则。
            读（不写任何文件或状态）:
              shortcuts            每个动作的绑定、作用范围、冲突提示 → shortcuts[{action, title, allows_global, binding{label, key, code, modifiers, scope}, status, conflict}], bound, load_error, app_running
            写（PhotoDesk 运行时拒绝，error.code = app_running；改完用 photodesk shortcuts 读回）:
              shortcuts scope      改已有绑定的作用范围：application 仅 PhotoDesk 内，global 全局（只有 toggleWindow、settings、pause 可全局）
              shortcuts clear      清除一个动作的绑定；--all 清除所有快捷键
            动作：\(PhotoAction.allCases.map(\.rawValue).joined(separator: " "))
            error.code（退出码 1）：app_running · not_bound（这个动作还没有绑定）· rejected（规则不允许，原因在 message）· failed
            仅在窗口中：录制快捷键（要真人按键）。系统是否接受某个全局快捷键的注册只有运行中的 App 知道，命令报告的是保存的绑定与能从绑定本身判断的冲突。
            \(shape)
            """
        case "login": return """
            usage: photodesk login [status] [--json]
                   photodesk login on|off --yes [--dry-run] [--json]
            设置窗口“登录 Mac 时启动”：同一个系统登录项（SMAppService）。
            读（不写任何文件或状态）:
              login status         → enabled, state（enabled | not_registered | requires_approval | not_found）, app_path
            写:
              login on|off --yes   登记 / 移除登录项（--dry-run 只看会不会变 → would_change；用 photodesk login status 读回）→ changed, enabled, state
            error.code（退出码 1）：requires_approval（已登记，还要在系统设置 → 通用 → 登录项里允许）· isolated_run（隔离或演示运行不改系统登录项）· failed
            \(shape)
            """
        case "automation": return """
            usage: photodesk automation [status] [--json]
                   photodesk automation pause|resume [--json]
            运行中的 PhotoDesk 的“暂停自动整理 / 继续自动整理”：由那个 App 自己执行并应答，命令不启动也不重启它。
            读（不写任何文件或状态）:
              automation status    → app_running, automatic_setting, automatic_enabled, organizing, organization_status, organization_error, busy, applying, task_status
                                   App 未运行时只有 app_running=false 与 automatic_setting（“打开 PhotoDesk 后自动整理”的设置）
            写（只改运行中的 App 这一次的状态，不改设置；改设置用 photodesk settings set automatic）:
              automation pause     暂停后台整理，已有结果仍可浏览 → changed, automatic_enabled=false
              automation resume    重新开始后台整理 → changed, automatic_enabled=true
            error.code（退出码 1）：app_not_running · no_reply（App 在运行但没有应答）· automatic_off（设置里关着自动整理，resume 不会开始）· failed
            \(shape)
            """
        default: return """
            usage: photodesk cancel [--json]
            取消运行中的 PhotoDesk 里进行中的任务（同状态栏的“取消”）：由那个 App 自己取消并停掉它启动的引擎进程。
            → cancelled, busy, applying, task_status, app_running；没有进行中的任务或 App 未运行时 cancelled=false，退出码 0。
            photodesk 命令自己起的任务不归它管：终止那个命令的进程即可。用 photodesk automation status 读回。
            error.code（退出码 1）：applying（正在写入照片图库，不能取消）· cancel_pending（已请求，8 秒内还没结束）· no_reply
            \(shape)
            """
        }
    }
    private static func text(_ body: [String: Any]) -> String {
        let data = (try? JSONSerialization.data(withJSONObject: body, options: [.sortedKeys, .prettyPrinted, .withoutEscapingSlashes])) ?? Data("{\"ok\":false}".utf8)
        return String(decoding: data, as: UTF8.self)
    }
    private static func write(_ text: String, to handle: FileHandle) { handle.write(Data((text + "\n").utf8)) }
    private static func report(_ failure: Failure, command: String, json: Bool) -> Int32 {
        if json {
            var body = failure.extra
            body["ok"] = false; body["command"] = command
            body["error"] = ["code": failure.code, "message": failure.message]
            write(text(body), to: .standardOutput)
        } else { write(failure.message, to: .standardError) }
        return failure.exit
    }
}

/// `--lifecycle-follow-probe <state file>`: this executable as the running app of tests/test_lifecycle_cli.py.
/// It exists for that test only and runs only in an isolated run on the marked synthetic library (the same
/// conditions as --ui-self-test, plus APP_LIFECYCLE_SUPPORT_DIR). Activation policy `.prohibited`: no Dock icon, no
/// menu bar, nothing can be ordered in. It builds the real model, calls the production wiring (PhotoLifecycle.installApp
/// and PhotoRemote.serve), builds the shared window the way the menu item does without showing it, and writes what
/// the configuration, the window's switch and the model hold to the state file for the test to poll.
@MainActor
enum PhotoLifecycleProbe {
    static let flag = "--lifecycle-follow-probe"
    private static var keep: [Any] = []
    private static var configuration: AppConfiguration?

    static func launch(_ words: [String]) -> Never {
        guard PhotoLifecycle.isolated, PhotoDeskLaunch.background, let defaults = PhotoLifecycle.commandDefaults(),
              let index = words.firstIndex(of: flag), words.count > index + 1, words[index + 1].hasPrefix("/") else {
            FileHandle.standardError.write(Data("\(flag) 只在隔离运行里可用：需要 APP_LIFECYCLE_SUPPORT_DIR、带标记的合成图库（PHOTODESK_BACKGROUND、PHOTODESK_DEMO_ROOT、PHOTODESK_DATA_ROOT）和 PhotoDesk.Test.* 偏好域，以及状态文件的绝对路径。\n".utf8))
            exit(64)
        }
        let application = NSApplication.shared
        application.setActivationPolicy(.prohibited)
        let state = URL(fileURLWithPath: words[index + 1])
        let model = PhotoDeskModel()
        configuration = PhotoLifecycle.installApp(model: model, defaults: defaults)
        PhotoRemote.serve(model)
        let built: [String: Bool]
        do { built = try AppLifecycleUI.shared.offscreenSnapshot(to: state.deletingPathExtension().appendingPathExtension("png")) }
        catch { FileHandle.standardError.write(Data("lifecycle window: \(error.localizedDescription)\n".utf8)); exit(1) }
        let control = NSApp.windows.lazy.compactMap { cloudSwitch(in: $0.contentView) }.first
        if words.contains("--probe-automation") { model.startAutomation() }
        // The test asks for a foreground task (the window's ⌘R) by creating this file; cancelling it is the command's job.
        let trigger = URL(fileURLWithPath: state.path + ".refresh")
        var tick = 0
        let timer = Timer.scheduledTimer(withTimeInterval: 0.05, repeats: true) { _ in
            MainActor.assumeIsolated {
                tick += 1
                if FileManager.default.fileExists(atPath: trigger.path) { try? FileManager.default.removeItem(at: trigger); model.refresh() }
                let shown = (control as? NSButton)?.state ?? (control as? NSSwitch)?.state
                var seen: [String: Any] = ["enabled": configuration?.enabled ?? false, "status": configuration?.status ?? "", "changes": PhotoLifecycle.changes, "tick": tick,
                                           "window_switch": shown.map { $0 == .on } ?? NSNull(), "window_built": built,
                                           "windows_on_screen": NSApp.windows.filter(\.isVisible).count,
                                           "policy_prohibited": NSApp.activationPolicy() == .prohibited,
                                           "thumbnailWidth": model.preferences.thumbnailWidth, "appearance": model.preferences.appearance,
                                           "automatic": model.preferences.automatic,
                                           "shortcuts": model.shortcuts.bindings.mapValues { $0.chord.label + " " + $0.scope.rawValue }]
                seen.merge(PhotoRemote.state(model)) { current, _ in current }
                try? JSONSerialization.data(withJSONObject: seen, options: [.sortedKeys]).write(to: state, options: .atomic)
            }
        }
        keep = [model, timer]
        application.run()
        exit(0)
    }

    /// The「使用 iCloud 记住配置」control of the shared window: a checkbox in the copy vendored here, a switch in the current shared source.
    private static func cloudSwitch(in view: NSView?) -> NSControl? {
        guard let view else { return nil }
        if let button = view as? NSButton, button.title == "使用 iCloud 记住配置" { return button }
        if let toggle = view as? NSSwitch { return toggle }
        for child in view.subviews { if let found = cloudSwitch(in: child) { return found } }
        return nil
    }
}
