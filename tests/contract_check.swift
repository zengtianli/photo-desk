import Foundation

@main
struct Check {
    static func main() throws {
        let root = URL(fileURLWithPath: CommandLine.arguments[1])
        let audit = try Contract.decode(LibrarySummary.self, from: Data(contentsOf: root.appendingPathComponent("frozen-audit.json")))
        precondition(audit.total == audit.photos + audit.movies)
        for kind in ["classify", "title", "triage", "sensitive", "duplicates", "library"] {
            let plan = try Contract.decode(PhotoPlan.self, from: Data(contentsOf: root.appendingPathComponent("frozen-\(kind).json")))
            precondition(plan.kind == kind)
            precondition(Set(plan.rows.map(\.id)).count == plan.rows.count)
            precondition(plan.rows.allSatisfy { !$0.cloudGuid.isEmpty || $0.localUuid != nil })
            print(kind, plan.rows.count, "rows decoded")
        }
        print("Actual GUI decoder contracts passed; library items:", audit.total)
        let journeyURL = root.appendingPathComponent("journey-enrich.json")
        if FileManager.default.fileExists(atPath: journeyURL.path) {
            let journey = try Contract.decode(JourneyResult.self, from: Data(contentsOf: journeyURL))
            precondition(journey.total == journey.plan.rows.count)
            precondition(journey.total == journey.events.reduce(0) { $0 + $1.count })
            precondition(Set(journey.plan.rows.map(\.id)).count == journey.total)
            precondition(journey.analyzed + journey.pending == journey.total)
            print("Journey decoded:", journey.total, "photos,", journey.events.count, "events")
        }
        // Current engine: a full reply carries its content digest; the same request with that
        // digest as previous_digest answers with the short "unchanged" form the app accepts.
        let nextURL = root.appendingPathComponent("journey-next.json")
        let unchangedURL = root.appendingPathComponent("journey-unchanged.json")
        if FileManager.default.fileExists(atPath: nextURL.path), FileManager.default.fileExists(atPath: unchangedURL.path) {
            let full = try Contract.decode(JourneyResult.self, from: Data(contentsOf: nextURL))
            precondition(full.digest?.count == 64, "a full reply must carry its digest")
            precondition(full.total == full.events.reduce(0) { $0 + $1.count })
            let short = try Data(contentsOf: unchangedURL)
            precondition(short.count < 4096, "the unchanged reply must be small enough for the fast path")
            let reply = try Contract.decode(JourneyUnchanged.self, from: short)
            precondition(reply.unchanged == true && reply.digest == full.digest, "unchanged reply must echo the shown digest")
            let asFull = try? Contract.decode(JourneyResult.self, from: short)
            precondition(asFull == nil, "the short reply must never pass as a (empty) journey")
            let fullAsShort = try Contract.decode(JourneyUnchanged.self, from: Data(contentsOf: nextURL))
            precondition(fullAsShort.unchanged != true, "a full reply must never read as unchanged")
            print("Journey digest contract passed:", full.digest!.prefix(12), full.total, "photos")
        }
    }
}
