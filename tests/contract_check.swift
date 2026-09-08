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
    }
}
