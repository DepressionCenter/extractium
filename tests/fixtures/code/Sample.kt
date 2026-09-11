// A small client for a built index, invented for the test suite.
package com.example.search

import java.io.File

/** One ranked result. */
data class Result(val parentId: String, val score: Double)

// Reads a compendium from a file and answers questions about it.
class Compendium(private val source: File) {

    // Returns the results whose title holds the term.
    fun search(term: String): List<Result> {
        return load().filter { it.parentId.contains(term) }
    }

    private fun load(): List<Result> = emptyList()
}

fun rank(results: List<Result>): List<Result> = results.sortedByDescending { it.score }
