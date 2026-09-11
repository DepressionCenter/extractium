; Extraction rules for Swift.
;
; Swift's grammar writes a struct, an enum, and a class all as a class
; declaration, so the kind recorded here is "class" for each. The
; signature keeps the word the source actually used, which is what tells
; a reader the difference.
;
; This file is part of Extractium(TM)
; extractium/code/queries/swift.scm
; Copyright (C) 2026 The Regents of the University of Michigan
; Licensed under the GNU General Public License v3.0 or later.
; See README for full license information.

(class_declaration
  name: (type_identifier) @name) @definition.class

(protocol_declaration
  name: (type_identifier) @name) @definition.type

(function_declaration
  name: (simple_identifier) @name) @definition.function

(protocol_function_declaration
  name: (simple_identifier) @name) @definition.function

(typealias_declaration
  name: (type_identifier) @name) @definition.type

(import_declaration
  (identifier) @import.source) @import

(call_expression
  [(simple_identifier) @call.name
   (navigation_expression (navigation_suffix (simple_identifier) @call.name))]) @call
