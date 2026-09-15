// Package search is a small client for a built index, invented for the test suite.
package search

import (
	"fmt"
	"strings"
)

// Limit is the most results one search returns.
const Limit = 10

// Result is one ranked result.
type Result struct {
	ParentID string
	Score    float64
}

// Ranker orders results.
type Ranker interface {
	Rank(results []Result) []Result
}

// Compendium reads a built index and answers questions about it.
type Compendium struct {
	titles []string
}

// Search returns the titles that hold the term.
func (c *Compendium) Search(term string) []string {
	var found []string
	for _, title := range c.titles {
		if strings.Contains(title, term) {
			found = append(found, title)
		}
	}
	return found
}

// Describe prints how many titles the compendium holds.
func Describe(c *Compendium) {
	fmt.Println(len(c.titles))
}
