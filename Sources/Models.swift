import Foundation

struct Envelope<T: Decodable>: Decodable { let ok: Bool; let error: String?; let data: T? }
struct Probe: Decodable { let ok: Bool; let error: String? }
struct PingResult: Decodable { let message: String; let version: String; let dataRoot: String }
struct LibrarySummary: Decodable {
    let library: String
    let total: Int
    let photos: Int
    let movies: Int
    let favorites: Int
    let live: Int
    let shared: Int
    let local: Int
    let byYear: [String: Int]
    let albums: [String: Int]
    let generated: String
    let message: String
}
struct PlanRow: Decodable, Identifiable {
    let id: String
    let cloudGuid: String
    let filename: String
    let date: String
    let action: String
    let target: String
    let note: String
    let previewPath: String
    let originalTitle: String
    let protected: String
    let group: String
    var actionName: String {
        switch action { case "add-album": return "加入相册"; case "add-keyword": return "添加标签"; case "set-title": return "补充标题"; default: return "人工核对" }
    }
}
struct PhotoPlan: Decodable, Identifiable {
    let id: String
    let kind: String
    let library: String
    let created: String
    let examined: Int
    let warnings: [String]
    let csvPath: String
    let rows: [PlanRow]
    var isReadOnly: Bool { kind == "duplicates" }
    var groups: [String] { Array(Set(rows.map(\.group))).sorted() }
}
struct ApplyResult: Decodable { let message: String; let changed: Int; let receiptPath: String? }
struct HistoryEntry: Decodable, Identifiable {
    let id: String; let kind: String; let created: String; let library: String; let count: Int
}
struct HistoryResult: Decodable { let entries: [HistoryEntry] }
struct WorkProgress: Decodable { let message: String; let done: Int; let total: Int }

enum Page: String, CaseIterable, Identifiable {
    case overview, classify, triage, sensitive, title, duplicates, history
    var id: String { rawValue }
    var name: String {
        switch self {
        case .overview: return "图库概览"
        case .classify: return "分类整理"
        case .triage: return "截图与票据"
        case .sensitive: return "敏感照片"
        case .title: return "照片标题"
        case .duplicates: return "重复核对"
        case .history: return "整理记录"
        }
    }
    var symbol: String {
        switch self {
        case .overview: return "square.grid.2x2"
        case .classify: return "folder.badge.plus"
        case .triage: return "doc.viewfinder"
        case .sensitive: return "lock.shield"
        case .title: return "textformat.abc"
        case .duplicates: return "square.on.square"
        case .history: return "clock.arrow.circlepath"
        }
    }
    var detail: String {
        switch self {
        case .overview: return "看看照片都在哪里，再开始整理。"
        case .classify: return "按年月、人物和场景归入相册，已有分类自动跳过。"
        case .triage: return "本地识别截图和文档，票据保留，拿不准的留给你核对。"
        case .sensitive: return "查找含证件、银行卡或手机号的照片，标记为敏感档案。"
        case .title: return "用拍摄时间、地点和人物补充空标题，保留已有标题。"
        case .duplicates: return "查找相同原片指纹，逐张核对编辑效果和 Live Photo。"
        case .history: return "继续查看之前生成的建议，或在 Finder 中查看操作记录。"
        }
    }
    var usesOCR: Bool { self == .triage || self == .sensitive }
}

enum Contract {
    static func decode<T: Decodable>(_ type: T.Type, from data: Data) throws -> T {
        let decoder = JSONDecoder()
        decoder.keyDecodingStrategy = .convertFromSnakeCase
        let envelope = try decoder.decode(Envelope<T>.self, from: data)
        guard envelope.ok, let value = envelope.data else {
            throw NSError(domain: "PhotoDesk", code: 1, userInfo: [NSLocalizedDescriptionKey: envelope.error ?? "引擎未返回结果。"])
        }
        return value
    }
}
