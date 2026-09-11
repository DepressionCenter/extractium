; Extraction rules for Kotlin.
;
; This file is part of Extractium(TM)
; extractium/code/queries/kotlin.scm
; Copyright (C) 2026 The Regents of the University of Michigan
; Licensed under the GNU General Public License v3.0 or later.
; See README for full license information.

(class_declaration
  name: (identifier) @name) @definition.class

(object_declaration
  name: (identifier) @name) @definition.class

(function_declaration
  name: (identifier) @name) @definition.function

(package_header
  (qualified_identifier) @name) @definition.module

(import
  (qualified_identifier) @import.source) @import

(call_expression
  [(identifier) @call.name
   (navigation_expression (identifier) @call.name)]) @call
