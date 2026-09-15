; Extraction rules for Go.
;
; This file is part of Extractium(TM)
; extractium/code/queries/go.scm
; Copyright (C) 2026 The Regents of the University of Michigan
; Licensed under the GNU General Public License v3.0 or later.
; See README for full license information.

(package_clause
  (package_identifier) @name) @definition.module

(function_declaration
  name: (identifier) @name) @definition.function

; A method is written beside its receiver rather than inside a type, so
; it is recorded under its own name; the signature keeps the receiver.
(method_declaration
  name: (field_identifier) @name) @definition.method

; A struct is the nearest thing Go has to a class. Every other named
; type, an interface or an alias, is recorded as a type.
(type_spec
  name: (type_identifier) @name
  type: (struct_type)) @definition.class

(type_spec
  name: (type_identifier) @name
  type: [(interface_type) (type_identifier) (qualified_type) (map_type)
         (slice_type) (array_type) (function_type) (pointer_type)
         (channel_type) (generic_type)]) @definition.type

(const_spec
  name: (identifier) @name) @definition.constant

; A variable declared at package level is a configured value, like a
; constant, and is recorded as one.
(source_file
  (var_declaration
    (var_spec
      name: (identifier) @name) @definition.constant))

(import_spec
  path: (interpreted_string_literal) @import.source) @import

(call_expression
  function: [(identifier) @call.name
             (selector_expression field: (field_identifier) @call.name)]) @call
