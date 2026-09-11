// A small reader for a built index, invented for the test suite.
using System;
using System.Collections.Generic;

namespace Example.Search
{
    /// <summary>One ranked result.</summary>
    public interface IResult
    {
        string ParentId { get; }
    }

    // Reads a compendium and answers questions about it.
    public class Compendium
    {
        private readonly List<string> titles;

        public Compendium(List<string> titles)
        {
            this.titles = titles;
        }

        // Returns every title holding the term.
        public IEnumerable<string> Search(string term)
        {
            return titles.FindAll(title => title.Contains(term));
        }
    }
}
