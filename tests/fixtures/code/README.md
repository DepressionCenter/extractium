<!--
This file is part of Extractium™
tests/fixtures/code/README.md
Author(s): Gabriel Mongefranco
Created: 2026-09-10
Last Modified: 2026-09-10
Summary: What the code fixtures in this folder are, why they carry no
license header of their own, and which test reads each one.
Notes: See README file for documentation and full license information.

Copyright © 2026 The Regents of the University of Michigan

Licensed under the GNU Free Documentation License v1.3 or later.
See <https://www.gnu.org/licenses/fdl-1.3.html>. See README for full license information.

-->

# Extractium™

## Code Analysis Fixtures

[← Back to README](../../../README.md)


## Summary

This folder holds one small file per language the code analysis reads. They are the input to `tests/test_code_analysis.py`, which checks what each language's extraction rules find. Every file here is invented for the test suite: no repository, study, participant, or person in them is real, and nothing here was copied from anywhere.

**These files deliberately carry no license header.** A header would be the first thing in each file, and a file's own opening documentation is the first place a summary is taken from, so a header would hide the very behavior these fixtures exist to test. This page carries the license for the folder instead, which is what the contribution rules ask for where a header cannot go in the file itself.


## What each file is for

| File | What it exercises |
|---|---|
| `broken.py` | Definitions on both sides of a syntax error, and the flag that says the parser recovered |
| `sample.js`, `sample.ts` | Classes, methods, arrow functions, interfaces, type aliases, enums, and both kinds of import |
| `sample.sh` | Functions, a sourced file, and the commands a script runs |
| `sample.lua` | A function on a table, a method on a table, and `require` |
| `Sample.cs` | A namespace, an interface, a constructor, a property, and `using` directives |
| `sample.sql` | A view and a routine, with the query underneath each one left out of the record |
| `Sample.kt`, `Sample.swift` | Classes, methods, and the documentation written above each |
| `Sample.ps1` | Functions with parameter blocks, and `Import-Module` |
| `sample.m` | MATLAB functions, whose documentation sits under the signature rather than above it |
| `sample.R` | A language with no published grammar: the Ctags path, and the file-metadata path |
| `sample.ipynb` | A notebook, including stored outputs that must never be read |
| `sample.Rmd` | R and Python chunks in one document, and the prose around them |
| `sample.lsp` | A Lua Server Page: markup outside the delimiters, Lua inside them |
| `sample.html` | Page text, one inline script, one linked script, and one block of JSON that is not code |


## Conclusion

If you add a language, add a small file here that uses every capture its query file claims, and a test in `tests/test_code_analysis.py` that names what it should find. Keep the file short: these are read by people trying to understand a failure.


## Additional Resources

* [Extractium™ README](../../../README.md) — project overview and quick start.
* [GitHub repository indexing](../../../docs/github-repository-indexing.md) — the design these fixtures test.
* [tests/test_code_analysis.py](../../test_code_analysis.py) — the tests that read this folder.


[← Back to README](../../../README.md)

----

Copyright © 2026 The Regents of the University of Michigan
