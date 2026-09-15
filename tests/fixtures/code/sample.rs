//! A small client for a built index, invented for the test suite.

use std::collections::HashMap;

/// The most results one search returns.
const LIMIT: usize = 10;

/// One ranked result.
pub struct Result {
    pub parent_id: String,
    pub score: f64,
}

/// Orders results.
pub trait Ranking {
    fn rank(&self, results: Vec<Result>) -> Vec<Result>;
}

/// Reads a built index and answers questions about it.
pub struct Compendium {
    titles: Vec<String>,
}

impl Compendium {
    /// Returns the titles that hold the term.
    pub fn search(&self, term: &str) -> Vec<String> {
        self.titles.iter().filter(|t| t.contains(term)).cloned().collect()
    }
}

pub mod util {
    /// Counts how often each title appears.
    pub fn tally(titles: &[String]) -> super::HashMap<String, usize> {
        let mut counts = super::HashMap::new();
        for title in titles {
            *counts.entry(title.clone()).or_insert(0) += 1;
        }
        counts
    }
}

/// Prints how many titles the compendium holds.
pub fn describe(compendium: &Compendium) {
    println!("{}", compendium.titles.len());
}
