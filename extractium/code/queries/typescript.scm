; Extraction rules for TypeScript, and for TypeScript with JSX.
;
; Adapted from the tag queries the tree-sitter-typescript grammar
; publishes, which are licensed under the MIT License, copyright (c) 2017
; GitHub. The capture names differ: this file uses the set
; extractium/code/languages.py defines, so one engine reads every
; language the same way.
;
; This file is part of Extractium(TM)
; extractium/code/queries/typescript.scm
; Copyright (C) 2026 The Regents of the University of Michigan
; Licensed under the GNU General Public License v3.0 or later.
; See README for full license information.

(class_declaration
  name: (type_identifier) @name) @definition.class

(abstract_class_declaration
  name: (type_identifier) @name) @definition.class

(interface_declaration
  name: (type_identifier) @name) @definition.type

(type_alias_declaration
  name: (type_identifier) @name) @definition.type

(enum_declaration
  name: (identifier) @name) @definition.type

(function_declaration
  name: (identifier) @name) @definition.function

(function_signature
  name: (identifier) @name) @definition.function

(method_definition
  name: (property_identifier) @name) @definition.method

(method_signature
  name: (property_identifier) @name) @definition.method

; A function given a name by being assigned to one.
(variable_declarator
  name: (identifier) @name
  value: [(arrow_function) (function_expression)]) @definition.function

(import_statement
  source: (string) @import.source) @import

(call_expression
  function: [(identifier) @call.name
             (member_expression property: (property_identifier) @call.name)]) @call
