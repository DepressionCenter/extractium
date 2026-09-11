; Extraction rules for Python.
;
; Adapted from the tag queries the tree-sitter-python grammar publishes,
; which are licensed under the MIT License, copyright (c) 2016 Max
; Brunsfeld. The capture names differ: this file uses the set
; extractium/code/languages.py defines, so one engine reads every
; language the same way.
;
; This file is part of Extractium(TM)
; extractium/code/queries/python.scm
; Copyright (C) 2026 The Regents of the University of Michigan
; Licensed under the GNU General Public License v3.0 or later.
; See README for full license information.

(class_definition
  name: (identifier) @name) @definition.class

(function_definition
  name: (identifier) @name) @definition.function

; A name assigned at the top level of a module, which is how Python
; writes a constant and how it publishes a configured value.
(module
  (expression_statement
    (assignment
      left: (identifier) @name) @definition.constant))

(import_statement
  name: [(dotted_name) @import.source
         (aliased_import (dotted_name) @import.source)]) @import

(import_from_statement
  module_name: [(dotted_name) @import.source
                (relative_import) @import.source]) @import

; "from package import module" names a file the package holds, so the
; two halves are recorded together as well. The engine keeps whichever
; of the two names more.
(import_from_statement
  module_name: [(dotted_name) @import.source
                (relative_import) @import.source]
  name: [(dotted_name) @import.name
         (aliased_import (dotted_name) @import.name)]) @import

(call
  function: [(identifier) @call.name
             (attribute attribute: (identifier) @call.name)]) @call
