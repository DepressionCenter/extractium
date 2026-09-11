// A small client for a built index, invented for the test suite.
import Foundation

/// One ranked result.
struct Result {
    let parentId: String
    let score: Double
}

protocol Ranking {
    func rank(_ results: [Result]) -> [Result]
}

// Reads a compendium and answers questions about it.
class Compendium: Ranking {
    private let titles: [String]

    init(titles: [String]) {
        self.titles = titles
    }

    // Returns the results whose title holds the term.
    func search(for term: String) -> [String] {
        return titles.filter { $0.contains(term) }
    }

    func rank(_ results: [Result]) -> [Result] {
        return results.sorted { $0.score > $1.score }
    }
}
